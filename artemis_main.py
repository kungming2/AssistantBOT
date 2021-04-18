#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The MAIN runtime provides the messaging and flair enforcement
operations for the bot.
"""
import os
import re
import sys
import time
import traceback
import yaml
from ast import literal_eval
from random import choice

import praw
import prawcore
import psutil
from pbwrap import Pastebin
from rapidfuzz import process

import connection
import database
import timekeeping
from common import (
    flair_sanitizer,
    flair_template_checker,
    logger,
    main_error_log,
    markdown_escaper,
)
from settings import INFO, FILE_ADDRESS, SETTINGS
from text import *

# Number of regular top-level routine runs that have been made.
ISOCHRONISMS = 0


"""WIDGET UPDATING FUNCTIONS"""


def widget_operational_status_updater():
    """Widget updated on r/AssistantBOT with the current time.
    This basically tells us that the bot is active with the time being
    formatted according to ISO 8601: https://www.w3.org/TR/NOTE-datetime
    It is run every isochronism.

    :return: `None`.
    """
    # Don't update this widget if it's being run on an alternate account
    if INSTANCE != 99:
        return

    current_time = timekeeping.time_convert_to_string(time.time())
    wa_time = "{} {} UTC".format(current_time.split('T')[0], current_time.split('T')[1][:-1])
    wa_link = "https://www.wolframalpha.com/input/?i={}+to+current+geoip+location".format(wa_time)
    current_time = current_time.replace('Z', '[Z]({})'.format(wa_link))  # Add the link.

    # Get the operational status widget.
    operational_widget = None
    for widget in reddit.subreddit(INFO.username).widgets.sidebar:
        if isinstance(widget, praw.models.TextArea):
            if widget.id == SETTINGS.widget_operational_status:
                operational_widget = widget
                break

    # Update the widget with the current time.
    if operational_widget is not None:
        operational_status = '# ✅ {}'.format(current_time)
        operational_widget.mod.update(text=operational_status,
                                      styles={'backgroundColor': '#349e48',
                                              'headerColor': '#222222'})
        return True
    else:
        return False


def wikipage_config(subreddit_name):
    """This will return the wikipage object that already exists or the
    new one that was just created for the configuration page.
    This function also validates the YAML content of the configuration
    page to ensure that it is properly formed and that the data is as
    expected.

    :param subreddit_name: Name of a subreddit.
    :return: A tuple. In the first, `False` if an error was encountered,
             `True` if everything went right.
             The second parameter is a string with the error text if
             `False`, `None` if `True`.
    """
    # The wikipage title to edit or create.
    page_name = "{}_config".format(INFO.username[:12].lower())
    r = reddit.subreddit(subreddit_name)

    # This is the max length (in characters) of the custom flair
    # enforcement message.
    limit_msg = SETTINGS.advanced_limit_msg
    # This is the max length (in characters) of the custom bot name and
    # goodbye.
    limit_name = SETTINGS.advanced_limit_name
    # A list of Reddit's `tags` that are flair-external.
    permitted_tags = ['nsfw', 'oc', 'spoiler']
    permitted_days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

    # Check moderator permissions.
    current_permissions = connection.obtain_mod_permissions(subreddit_name, INSTANCE)[1]
    if not current_permissions:
        logger.info("Wikipage Config: Not a moderator "
                    "of r/{}.".format(subreddit_name))
        error = "Artemis is not a moderator of this subreddit."
        return False, error
    if 'wiki' not in current_permissions and 'all' not in current_permissions:
        logger.info("Wikipage Config: Insufficient mod permissions to edit "
                    "wiki config on r/{}.".format(subreddit_name))
        error = ("Artemis does not have the `wiki` mod permission "
                 "and thus cannot access the configuration page.")
        return False, error

    # Check the subreddit subscriber number. This is only used in
    # generating the initial default page. If there are enough
    # subscribers for userflair statistics, replace the boolean.
    if r.subscribers > SETTINGS.min_s_userflair:
        page_template = ADV_DEFAULT.replace('userflair_statistics: False',
                                            'userflair_statistics: True')
    else:
        page_template = str(ADV_DEFAULT)

    # Check if the page is there and try and get the text of the page.
    # This will fail if the page does NOT exist.
    try:
        config_test = r.wiki[page_name].content_md

        # If the page exists, then we get the PRAW Wikipage object here.
        config_wikipage = r.wiki[page_name]
        logger.debug('Wikipage Config: Config wikipage found, length {}.'.format(len(config_test)))
    except prawcore.exceptions.NotFound:
        # The page does *not* exist. Let's create the config page.
        reason_msg = "Creating the Artemis config wiki page."
        config_wikipage = r.wiki.create(name=page_name, content=page_template,
                                        reason=reason_msg)

        # Remove it from the public list and only let moderators see it.
        # Also add Artemis as a approved submitter/editor for the wiki.
        config_wikipage.mod.update(listed=False, permlevel=2)
        config_wikipage.mod.add(USERNAME_REG)
        logger.info("Wikipage Config: Created new config wiki "
                    "page for r/{}.".format(subreddit_name))

    # Now we have the `config_wikipage`. We pass its data to YAML and
    # see if we can get proper data from it.
    # If it's a newly created page then the default data will be what
    # it gets from the page.
    default_data = yaml.safe_load(ADV_DEFAULT)
    # A list of the default variables (which are keys).
    default_vs_keys = list(default_data.keys())
    default_vs_keys.sort()
    # noinspection PyUnresolvedReferences
    try:
        # `subreddit_config_data` should be a dictionary from the sub
        # assuming the YAML parser is able to get it right.
        subreddit_config_data = yaml.safe_load(config_wikipage.content_md)
        subreddit_config_keys = list(subreddit_config_data.keys())
        subreddit_config_keys.sort()
    except yaml.composer.ComposerError as err:
        # Encountered an error in the data's composition and this YAML
        # data does not translate into a proper Python dictionary.
        logger.info('Wikipage Config: The data on r/{} config page '
                    'has syntax errors.'.format(subreddit_name))
        error = ("There was an error with the page's YAML syntax "
                 "and this error occurred: {}".format(repr(err)))
        return False, error
    except yaml.parser.ParserError:
        # Encountered an error in parsing the data. This is likely due
        # to the inclusion of document markers (`---`) which are
        # mandatory on AutoModerator configuration pages.
        error = ("There was an error with the page's YAML syntax. "
                 "Please make sure there are no `---` lines.")
        return False, error
    except yaml.scanner.ScannerError:
        # Encountered an error in formatting. This can happen if the
        # indentation is faulty or invalid.
        error = ("There was an error with the page's YAML syntax. "
                 "Please make sure that all indents are *four* spaces, "
                 "and that there are spaces after each colon `:`.")
        return False, error
    logger.info('Wikipage Config: Configuration data for '
                'r/{} is {}.'.format(subreddit_name, subreddit_config_data))

    # Check to make sure that the subreddit's variables are a valid
    # subset of the default configuration.
    if not set(subreddit_config_keys).issubset(default_vs_keys):
        logger.info('Wikipage Config: The r/{} config variables '
                    'are incorrect.'.format(subreddit_name))
        error = "The configuration variables do not match the ones in the default specification."
        return False, error

    # Integrity check to make sure all of the subreddit config data is
    # properly typed and will not cause problems.
    for v in subreddit_config_keys:
        default_type = type(default_data[v])
        subreddit_config_type = type(subreddit_config_data[v])
        if default_type != subreddit_config_type:
            logger.info("Wikipage Config: Variable `{}` "
                        "wrongly set as `{}`.".format(v, subreddit_config_type))
            error = ("Configuration variable `{}` has a wrong type: "
                     "It should be of type `{}`.".format(v, default_type))
            return False, error

        # Make sure every username on the username lists are in
        # lowercase, if it's a non-empty list.
        if v == 'flair_enforce_whitelist' and len(subreddit_config_data[v]) > 0:
            subreddit_config_data[v] = [x.lower().strip() for x in subreddit_config_data[v]]
        elif v == 'flair_enforce_alert_list' and len(subreddit_config_data[v]) > 0:
            subreddit_config_data[v] = [x.lower().strip() for x in subreddit_config_data[v]]

        # Length checks to make sure the custom strings are not too
        # long. If there are, they are truncated to the limits set
        # above.
        elif v == 'flair_enforce_custom_message' and len(subreddit_config_data[v]) > limit_msg:
            subreddit_config_data[v] = subreddit_config_data[v][:limit_msg].strip()
        elif v == 'custom_name' and len(subreddit_config_data[v]) > limit_name:
            subreddit_config_data[v] = subreddit_config_data[v][:limit_name].strip()
        elif v == 'custom_goodbye' and len(subreddit_config_data[v]) > limit_name:
            subreddit_config_data[v] = subreddit_config_data[v][:limit_name].strip()

        # This checks the integrity of the `flair_tags` dictionary.
        # It has the `spoiler` and `nsfw` keys (ONLY)
        # and make sure each have lists of flair IDs that match a regex
        # template and are valid.
        elif v == 'flair_tags':
            # First check to make sure that the tags are allowed and the
            # right ones, with no more variables than allowed.
            if len(subreddit_config_data[v]) > len(permitted_tags):
                return False, "There are more than the allowed number of tags in `flair_tags`."
            if not set(subreddit_config_data['flair_tags'].keys()).issubset(permitted_tags):
                return False, "There are tags in `flair_tags` that are not of the expected type."

            # Now we check to make sure that the contents of the tags
            # are LISTS, rather than strings. Return an error if they
            # contain anything other than lists.
            for key in subreddit_config_data['flair_tags']:
                if type(subreddit_config_data['flair_tags'][key]) != list:
                    error_msg = ("Each tag in `flair_tags` should "
                                 "contain a *list* of flair templates.")
                    return False, error_msg

            # Next we iterate over the lists to make sure they contain
            # proper post flair IDs. If not, return an error.
            # Add all present flairs together and iterate over them.
            tagged_flairs = sum(subreddit_config_data['flair_tags'].values(), [])
            for flair in tagged_flairs:
                if not flair_template_checker(flair):
                    error_msg = ('Please ensure data in `flair_tags` has '
                                 'valid flair IDs, not `{}`.'.format(flair))
                    return False, error_msg

        # Properly check the integrity of the `flair_schedule`
        # dictionary. It should have three-letter weekdays as
        # keys and each have lists of flair IDs that are valid.
        elif v == 'flair_schedule':
            # Check to make sure that they
            if not set(subreddit_config_data['flair_schedule'].keys()).issubset(permitted_days):
                error_msg = ("Please ensure that days in `flair_schedule` are listed as "
                             "**abbreviations in title case**. For example, `Sun`, `Tue`, etc.")
                return False, error_msg

            # Now we check to make sure that the contents of the tags
            # are LISTS, rather than strings. Return an error if they
            # contain anything other than lists.
            for key in subreddit_config_data['flair_schedule']:
                if type(subreddit_config_data['flair_schedule'][key]) != list:
                    error_msg = ("Each day in `flair_schedule` should "
                                 "contain a *list* of flair templates.")
                    return False, error_msg

            # Next we iterate over the lists to make sure they contain
            # proper post flair IDs. If not, return an error.
            # Add all present flairs together and iterate over them.
            tagged_flairs = sum(subreddit_config_data['flair_schedule'].values(), [])
            for flair in tagged_flairs:
                if not flair_template_checker(flair):
                    error_msg = ('Please ensure data in `flair_schedule` has '
                                 'valid flair IDs, not `{}`.'.format(flair))
                    return False, error_msg

    # If we've reached this point, the data should be accurate and
    # properly typed. Write to database.
    database.extended_insert(subreddit_name, subreddit_config_data)
    logger.info('Wikipage Config: Inserted configuration data for '
                'r/{} into extended data.'.format(subreddit_name))

    return True, None


def wikipage_access_history(action, data_package):
    """Function to save a record of a removed subreddit to the wiki.

    :param action: A string, one of `readd`, `remove`, or `read`.
                   * `remove` means that the subreddit will be entered
                      on this history page.
                   * `readd` means that the subreddit, if it exists
                      should be cleared from this history.
                   * `read` just fetches the existing data as a
                      dictionary.
    :param data_package: A dictionary indexed with a subreddit's
                         lowercase name and with the former extended
                         data for it if the action is `remove`.
                         If the action is `readd` then it will be a
                         string.
                         If the action is `read`, `None` is fine.
    """
    # Access the history wikipage and load its data.
    history_wikipage = reddit.subreddit('translatorbot').wiki['artemis_history']
    history_data = yaml.safe_load(history_wikipage.content_md)

    # Update the dictionary depending on the action.
    if action == 'remove':
        history_data.update(data_package)
    elif action == 'readd':
        if data_package in history_data:
            del history_data[data_package]
        else:  # This subreddit was never in the history.
            return
    elif action == 'read':
        return history_data

    # Format the YAML code with indents for readability and edit.
    history_yaml = yaml.safe_dump(history_data)
    history_yaml = "    " + history_yaml.replace('\n', '\n    ')
    history_wikipage.edit(content=history_yaml,
                          reason='Updating with action `{}`.'.format(action))
    logger.info('Access History: Saved `{}`, '
                'data `{}`, to history wikipage.'.format(action, data_package))

    return


"""TEMPLATE FUNCTIONS"""


def subreddit_templates_retrieve(subreddit_name, display_mod_flairs=False):
    """Retrieve the templates that are available for a particular
    subreddit's post flairs.

    Note that moderator-only post flairs ARE NOT included in the data
    that Reddit returns, because we use the alternate `reddit_helper`
    account, which is NOT a moderator account and can only see the post
    flairs that regular users can see.

    However, if the subreddit is private and only accessible to the
    main account, we still use the main account to access the flairs.

    :param subreddit_name: Name of a subreddit.
    :param display_mod_flairs: A Boolean as to whether or not we want
                               to retrieve the mod-only post flairs.
                               Not used now but is an option.
                               * True: Display mod-only flairs.
                               * False (default): Don't.
    :return: A dictionary of the templates available on that subreddit,
             indexed by their flair text.
             This dictionary will be empty if Artemis is unable to
             access the templates for some reason.
             Those reasons may include all flairs being mod-only,
             no flairs at all, etc.
    """
    subreddit_templates = {}
    order = 1

    # Determine the status of the subreddit.
    # `public` is normal, `private`, and the `Forbidden` exception if
    # it is a quarantined subreddit.
    try:
        subreddit_type = reddit.subreddit(subreddit_name).subreddit_type
    except prawcore.exceptions.Forbidden:
        subreddit_type = 'private'

    # Primarily we do not want to get mod-only flairs,
    # so we use the helper account to get available flairs.
    if not display_mod_flairs and subreddit_type == 'public':
        r = reddit_helper.subreddit(subreddit_name)
    else:
        r = reddit.subreddit(subreddit_name)

    # Access the templates on the subreddit and assign their attributes
    # to our dictionary.
    try:
        for template in r.flair.link_templates:

            # This template has no text at all; do not process it.
            if len(template['text']) == 0:
                continue

            # Create an entry in the dictionary for this flair.
            subreddit_templates[template['text']] = {'id': template['id'], 'order': order,
                                                     'css_class': template['css_class']}

            # This variable presents the dictionary of templates in the
            # same order it is on the sub.
            order += 1
        logger.debug("Templates Retrieve: r/{} templates are: {}".format(subreddit_name,
                                                                         subreddit_templates))
    except prawcore.exceptions.Forbidden:
        # The flairs don't appear to be available to me.
        # It may be that they are mod-only. Return an empty dictionary.
        logger.debug("Templates Retrieve: r/{} templates not accessible.".format(subreddit_name))

    return subreddit_templates


def subreddit_templates_collater(subreddit_name):
    """A function that generates a bulleted list of flairs available on
     a subreddit based on a dictionary by the function
     `subreddit_templates_retrieve()`.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A Markdown-formatted bulleted list of templates.
    """
    formatted_order = {}

    # Iterate over our keys, indexing by the order in which they are
    # displayed in the flair selector. The templates are also passed to
    # the flair sanitizer for processing.
    template_dictionary = subreddit_templates_retrieve(subreddit_name)
    for template in template_dictionary.keys():
        template_order = template_dictionary[template]['order']
        formatted_order[template_order] = flair_sanitizer(template, False)

    # Reorder and format each line.
    lines = ["* {}".format(formatted_order[key]) for key in sorted(formatted_order.keys())]

    return "\n".join(lines)


"""ADVANCED SUB-FUNCTIONS"""


def advanced_send_alert(submission_obj, list_of_users):
    """A small function to send a message to moderators who want to be
    notified each time a removal action is taken. This is not a
    widely-used function and in v1.6 was surfaced for others to use
    if needed via advanced configuration.

    :param submission_obj: A PRAW submission object.
    :param list_of_users: A list of users to notify.
                          They must be moderators.
    :return: Nothing.
    """
    sub_name = submission_obj.subreddit.display_name.lower()
    for user in list_of_users:
        if flair_is_user_mod(user, sub_name):

            # Form the message to send to the moderator.
            alert = ("I removed this [unflaired post here]"
                     "(https://www.reddit.com{}).".format(submission_obj.permalink))
            if submission_obj.over_18:
                alert += " (Warning: This post is marked as NSFW)"
            alert += BOT_DISCLAIMER.format(sub_name)

            # Send the message to the moderator, accounting for if there
            # is a username error.
            subject = '[Notification] Post on r/{} removed.'.format(sub_name)
            try:
                reddit.redditor(user).message(subject=subject, message=alert)
                logger.info('Send Alert: Messaged u/{} on '
                            'r/{} about removal.'.format(user, sub_name))
            except praw.exceptions.APIException:
                continue

    return


def advanced_set_flair_tag(praw_submission, template_id=None):
    """A function to check if a submission has flairs associated with
    certain Reddit tags, namely `nsfw`, `oc`, and `spoiler`.
    This is defined through extended data as a dictionary of lists.
    This requires the `posts` mod permission to work. If spoilers are
    not enabled, nothing will happen for that.

    :param praw_submission: A PRAW Reddit submission object.
    :param template_id: Optionally, a template ID for usage to directly
                        assign instead of getting from the submission.
    :return: Nothing.
    """
    # Check for the post template.
    if template_id is None:
        try:
            post_template = praw_submission.link_flair_template_id
        except AttributeError:  # No template ID assigned.
            return
    else:
        post_template = template_id

    # Fetch the extended data and check the flair tags dictionary.
    # This is a dictionary with keys `spoiler`, `nsfw` etc. with lists.
    post_id = praw_submission.id
    ext_data = database.extended_retrieve(praw_submission.subreddit.display_name.lower())
    if 'flair_tags' not in ext_data:
        return
    else:
        flair_tags = ext_data['flair_tags']

    # Iterate over our dictionary, checking for the template ID of the
    # submission.
    for tag in flair_tags:
        flair_list = flair_tags[tag]
        if tag == 'nsfw':
            if post_template in flair_list:
                # This flair is specified to be marked as NSFW.
                praw_submission.mod.nsfw()
                logger.info('Set Tag: >> Marked post `{}` as NSFW.'.format(post_id))
        elif tag == 'oc':
            # We use an unsurfaced method here from u/nmtake. This will
            # be integrated into a future version of PRAW.
            # https://redd.it/dr4kti
            if post_template in flair_list:
                # This flair is specified to be marked as original
                # content.
                package = {'id': post_id, 'fullname': 't3_' + post_id, 'should_set_oc': True,
                           'executed': False, 'r': praw_submission.subreddit.display_name}
                reddit.post('api/set_original_content', data=package)
                logger.info('Set Tag: >> Marked post `{}` as original content.'.format(post_id))
        elif tag == 'spoiler':
            if post_template in flair_list:
                # This flair is specified to be marked as a spoiler.
                praw_submission.mod.spoiler()
                logger.info('Set Tag: >> Marked post `{}` as a spoiler.'.format(post_id))

    return


"""MESSAGING FUNCTIONS"""


def messaging_send_creator(subreddit_name, subject_type, message):
    """A function that messages Artemis's creator updates on certain
    actions taken by this bot.

    :param subreddit_name: Name of a subreddit.
    :param subject_type: The type of message we want to send.
    :param message: The text of the message we want to send,
                    passed in from above.
    :return: None.
    """
    # This is a dictionary that defines what the subject line will be
    # based on the action. The add portion is currently unused.
    subject_dict = {"add": 'Added former subreddit: r/{}',
                    "remove": "Demodded from subreddit: r/{}",
                    "forbidden": "Subscribers forbidden for subreddit: r/{}",
                    "not_found": "Subscribers not found for subreddit: r/{}",
                    "omit": "Omitted subreddit: r/{}",
                    "mention": "New item mentioning Artemis on r/{}"
                    }

    # Taking note of exempted subreddits.
    if subject_type == "mention" and subreddit_name in connection.CONFIG.sub_mention_omit:
        logger.info("Messaging Send Creator: "
                    "Mention in omitted subreddit r/{}.".format(subreddit_name))
        return

    # If we have a matching subject type, send a message to the creator.
    if subject_type in subject_dict:
        creator = reddit.redditor(INFO.creator)
        creator.message(subject=subject_dict[subject_type].format(subreddit_name), message=message)

    return


def messaging_parse_flair_response(subreddit_name, response_text, post_id):
    """This function looks at a user's response to determine if their
    response is a valid flair in the subreddit that they posted in.
    If it is a valid template, then the function returns a template ID.
    The template ID is long and looks like this:
    `c1503580-7c00-11e7-8b43-0e560b183184`

    :param subreddit_name: Name of a subreddit.
    :param response_text: The text that a user sent back as a response
                          to the message.
    :param post_id: The ID of the submitter's post (used only for action
                    counting purposes).
    :return: `None` if it does not match anything;
             a template ID otherwise.
    """
    # Whether or not the message should be saved to a file for record
    # keeping and examination.
    to_messages_save = False
    flair_match_text = None
    action_type = None

    # Process the response from the user to make it consistent.
    response_text = flair_sanitizer(response_text)

    # Generate a new dictionary with template names all in lowercase.
    lowercased_flair_dict = {}

    # Get the flairs for this particular community.
    template_dict = subreddit_templates_retrieve(subreddit_name)

    # Iterate over the dictionary and assign its values in lowercase
    # for the keys.
    for key in template_dict.keys():
        # The formatted key is what we check the user's message against
        # to see if they match a flair on the sub.
        # Assign the value to a new dictionary indexed with
        # the formatted key.
        formatted_key = flair_sanitizer(key)
        lowercased_flair_dict[formatted_key] = template_dict[key]

    # If we find the text that the user sent back in the templates, we
    # return the template ID.
    if response_text in lowercased_flair_dict:
        returned_template = lowercased_flair_dict[response_text]['id']
        logger.debug("Parse Response: > Found r/{} template: `{}`.".format(subreddit_name,
                                                                           returned_template))
        database.counter_updater(subreddit_name, "Parsed exact flair in message", "main",
                                 post_id=post_id, id_only=True)
    else:
        # No exact match found. Use fuzzy matching to determine the
        # best match from the flair dictionary.
        # Returns as tuple `('FLAIR' (text), INT)` or `None`.
        # If the match is higher than or equal to `min_fuzz_ratio`, then
        # assign that to `returned_template`. Otherwise, `None`.
        best_match = process.extractOne(response_text, list(lowercased_flair_dict.keys()))
        if best_match is None:
            # No results at all.
            returned_template = None
        elif best_match[1] >= SETTINGS.min_fuzz_ratio:
            # We are very sure this is right.
            returned_template = lowercased_flair_dict[best_match[0]]['id']
            flair_match_text = best_match[0]
            logger.info("Parse Response: > Fuzzed {:.2f}% certainty match for "
                        "`{}`: `{}`".format(best_match[1], flair_match_text, returned_template))
            database.counter_updater(subreddit_name, "Fuzzed flair match in message", "main",
                                     post_id=post_id, id_only=True)
            to_messages_save = True
            action_type = "Fuzzed"
        else:
            # No good match found.
            returned_template = None

    # If there was no match (either exact or fuzzed) then this will
    # check the text itself to see if there are any matching post
    # flairs contained within it. This is the last attempt.
    if not returned_template:
        for flair_text in lowercased_flair_dict.keys():
            if flair_text in response_text:
                returned_template = lowercased_flair_dict[flair_text]['id']
                logger.info("Parse Response: > Found `{}` in text: `{}`".format(flair_text,
                                                                                returned_template))
                database.counter_updater(subreddit_name, "Found flair match in message", "main",
                                         post_id=post_id, id_only=True)
                to_messages_save = True
                action_type = "Matched"
                flair_match_text = flair_text
                break

    if not returned_template or to_messages_save:
        message_package = {'subreddit': subreddit_name, 'id': post_id, 'action': action_type,
                           'message': response_text, 'template_name': flair_match_text,
                           'template_id': returned_template}
        main_messages_log(message_package)
        logger.info("Parse Response: >> Recorded `{}` to messages log.".format(post_id))

    return returned_template


def messaging_modlog_parser(praw_submission):
    """This function is used when restoring a post after it's been
    flaired. It checks the mod log to see if a mod was the one to
    assign the post a flair.

    :param praw_submission: A PRAW submission object.
    :return: `True` if the moderation log indicates a mod flaired it,
             `False` otherwise.
    """
    flaired_by_other_mods = []

    # Here we iterate through the recent mod log for flair edits, and
    # look for this submission. Look for the Reddit fullname of the item
    # in question. We only want submissions.
    specific_subreddit = reddit.subreddit(praw_submission.subreddit.display_name)
    for item in specific_subreddit.mod.log(action='editflair', limit=25):
        i_fullname = item.target_fullname

        # If we cannot get the fullname, just ignore the item.
        # (e.g. editing flair templates gives `None` in the log.)
        if (i_fullname is None) or ("t3_" not in i_fullname):
            continue

        # Here we check for flair edits done by moderators, while making
        # sure the flair edit was not done by the bot. Then append the
        # submission ID of the edited link to our list.
        if str(item.mod).lower() != USERNAME_REG.lower():
            flaired_by_other_mods.append(i_fullname[3:])

    # If the post was flaired by another mod, return `True`.
    if praw_submission.id in flaired_by_other_mods:
        return True
    else:
        return False


def messaging_op_approved(subreddit_name, praw_submission, strict_mode=True, mod_flaired=False):
    """This function messages an OP that their post has been approved.
    This function will ALSO remove the post ID from the `posts_filtered`
    table of the database, if applicable.

    :param subreddit_name: Name of a subreddit.
    :param praw_submission: A relevant PRAW submission that we're
                            messaging the OP about.
    :param strict_mode: A Boolean denoting whether this message is for
                        Strict mode (that is, the post was removed)
    :param mod_flaired: A Boolean denoting whether the submission was
                        flaired by the mods.
    :return: Nothing.
    """
    # Check to see if user is a valid name. If the author is deleted,
    # we don't care about this post so skip it.
    try:
        post_author = praw_submission.author.name
    except AttributeError:
        post_author = None

    # There is an author to send to. Message the OP that it's
    # been approved.
    if post_author is not None:
        # Get variables.
        post_permalink = praw_submission.permalink
        post_id = praw_submission.id
        post_subreddit = praw_submission.subreddit.display_name

        # Form our message body, with slight variations depending on
        # whether the addition was via strict mode or not.
        subject_line = "[Notification] ✅ "
        key_phrase = "Thanks for selecting"

        # The wording will vary based on the mode. In strict mode, we
        # add text noting that the post has been approved. In addition
        # if a mod flaired this, we want to change the text to indicate
        # that.
        if strict_mode:
            subject_line += "Your flaired post is approved on r/{}!".format(post_subreddit)
            approval_message = MSG_USER_FLAIR_APPROVAL_STRICT.format(post_subreddit)
            database.counter_updater(post_subreddit, 'Restored post', "main", post_id=post_id)

            if mod_flaired:
                key_phrase = "It appears a mod has selected"
        else:
            # Otherwise, this is a Default mode post, so the post was
            # never removed and there is no need for an approval section
            # and instead the author is simply informed of the post's
            # assignment.
            subject_line += "Your post has been assigned a flair on r/{}!".format(post_subreddit)
            approval_message = ""
            database.counter_updater(subreddit_name, 'Flaired post', "main", post_id=post_id)

        # See if there's a custom name or custom goodbye in the extended
        # data to use.
        extended_data = database.extended_retrieve(subreddit_name)
        name_to_use = extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
        if not name_to_use:
            name_to_use = "Artemis"
        bye_phrase = extended_data.get('custom_goodbye',
                                       choice(GOODBYE_PHRASES)).capitalize()
        if not bye_phrase:
            bye_phrase = "Have a good day"

        # Format the message together.
        body = MSG_USER_FLAIR_APPROVAL.format(post_author, key_phrase, post_permalink,
                                              approval_message, bye_phrase)
        body += BOT_DISCLAIMER.replace('Artemis', name_to_use).format(post_subreddit)

        # Send the message.
        try:
            reddit.redditor(post_author).message(subject_line, body)
            logger.info("Flair Checker: > Sent a message to u/{} "
                        "about post `{}`.".format(post_author, post_id))
        except praw.exceptions.APIException:
            # NOT_WHITELISTED_BY_USER_MESSAGE, see
            # https://redd.it/h17rgd for more information.
            pass

        # Remove the post from database now that it's been flaired.
        database.delete_filtered_post(post_id)
        database.counter_updater(None, "Cleared post", "main", post_id=post_id, id_only=True)

    return


def messaging_example_collater(subreddit):
    """This is a simple function that takes in a PRAW subreddit OBJECT
    and then returns a Markdown chunk that is an example of the flair
    enforcement message that users get.

    :param subreddit: A PRAW subreddit *object*.
    :return: A Markdown-formatted string.
    """
    new_subreddit = subreddit.display_name.lower()
    stored_extended_data = database.extended_retrieve(new_subreddit)
    template_header = "*Here's an example flair enforcement message for r/{}:*"
    template_header = template_header.format(subreddit.display_name)
    sub_templates = subreddit_templates_collater(new_subreddit)
    current_permissions = connection.obtain_mod_permissions(new_subreddit, INSTANCE)

    # For the example, instead of putting a permalink to a post, we just
    # use the subreddit URL itself.
    post_permalink = 'https://www.reddit.com{}'.format(subreddit.url)

    # Get our permissions for this subreddit as a list.
    if not current_permissions[0]:
        return
    else:
        current_permissions_list = current_permissions[1]

    # Determine the permissions/appearances of flair removal message.
    if 'posts' in current_permissions_list or 'all' in current_permissions_list:
        # Check the extended data for auto-approval.
        # If it's false, we can't approve it and change the text.
        auto_approve = stored_extended_data.get('flair_enforce_approve_posts', True)
        if auto_approve:
            removal_section = MSG_USER_FLAIR_REMOVAL
        else:
            removal_section = MSG_USER_FLAIR_REMOVAL_NO_APPROVE
    else:
        removal_section = ''
    if 'flair' in current_permissions_list or 'all' in current_permissions_list:
        flair_option = MSG_USER_FLAIR_BODY_MESSAGING
    else:
        flair_option = ''

    # Check to see if there's a custom message to send to the user from
    # the extended config data.
    if 'flair_enforce_custom_message' in stored_extended_data:
        if stored_extended_data['flair_enforce_custom_message']:
            custom_text = '**Message from the moderators:** {}'
            custom_text = custom_text.format(stored_extended_data['flair_enforce_custom_message'])
        else:
            custom_text = ''
    else:
        custom_text = ''

    # Check if there's a custom name and goodbye. If the phrase is an
    # empty string, just use the default.
    name_to_use = stored_extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
    if not name_to_use:
        name_to_use = "Artemis"
    bye_phrase = stored_extended_data.get('custom_goodbye', "have a good day").lower()
    if not bye_phrase:
        bye_phrase = "have a good day"

    # Combine everything together. This is one of the few places where
    # `BOT_DISCLAIMER` is used outside a runtime.
    message_to_send = MSG_USER_FLAIR_BODY.format("USERNAME", subreddit.display_name, sub_templates,
                                                 post_permalink, post_permalink, removal_section,
                                                 bye_phrase, flair_option, "EXAMPLE POST TITLE",
                                                 custom_text)
    reply_text = "{}\n\n---\n\n{}".format(template_header, message_to_send)
    reply_text += BOT_DISCLAIMER.format(subreddit.display_name).replace('Artemis', name_to_use)

    return reply_text


"""FLAIR ENFORCING FUNCTIONS"""


def flair_notifier(post_object, message_to_send):
    """This function takes a PRAW Submission object - that of a post
    that is missing flair - and messages its author about the missing
    flair. It lets them know that they should select a flair.
    This is also used by the scheduling function to send messages.

    :param post_object: The PRAW Submission object of the post.
    :param message_to_send: The text of the message to the author.
    :return: Nothing.
    """
    # Get some basic variables.
    try:
        author = post_object.author.name
    except AttributeError:  # Issue with the user. Suspended?
        return
    active_subreddit = post_object.subreddit.display_name

    # Check if there's a custom name in the extended data.
    extended_data = database.extended_retrieve(active_subreddit)
    name_to_use = extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
    if not name_to_use:
        name_to_use = "Artemis"

    # Format the subject accordingly.
    if "scheduled weekday" in message_to_send:
        subject_line = MSG_SCHEDULE_REMOVAL_SUBJECT.format(active_subreddit)
    else:
        subject_line = MSG_USER_FLAIR_SUBJECT.format(active_subreddit)

    # Format the message and send the message.
    disclaimer_to_use = BOT_DISCLAIMER.replace('Artemis', name_to_use).format(active_subreddit)
    message_body = message_to_send + disclaimer_to_use
    try:
        reddit.redditor(author).message(subject_line, message_body)
        logger.debug("Notifier: Messaged u/{} about post `{}`.".format(author, post_object.id))
    except praw.exceptions.APIException:
        logger.debug('Notifier: Error sending message to u/{} about `{}`.'.format(author,
                                                                                  post_object.id))

    return


def flair_none_saver(post_object):
    """This function removes a post that lacks flair and saves it to
    the database to check later. It saves the post ID as well as the
    time it was created. The `main_flair_checker` function will check
    the post later to see if it has been assigned a flair, either by
    the OP or by a mod.

    :param post_object: PRAW Submission object of the post
                        missing a flair.
    :return: Nothing.
    """
    # Get the unique Reddit ID of the post.
    post_id = post_object.id

    # First we want to check if the post ID has already been saved.
    database.CURSOR_MAIN.execute("SELECT * FROM posts_filtered WHERE post_id = ?", (post_id,))
    result = database.CURSOR_MAIN.fetchone()

    if result is None:  # ID has not been saved before. We can save it.
        database.CURSOR_MAIN.execute("INSERT INTO posts_filtered VALUES (?, ?)",
                                     (post_id, int(post_object.created_utc)))
        database.CONN_MAIN.commit()
        logger.debug("Flair Saver: Added post {} to the filtered database.".format(post_id))

    return


def flair_is_user_mod(query_username, subreddit_name):
    """This function checks to see if a user is a moderator in the sub
    they posted in. Artemis WILL NOT remove an unflaired post if it's
    by a moderator unless there's a special setting in extended data.

    :param query_username: The username of the person.
    :param subreddit_name: The subreddit in which they posted a comment.
    :return: `True` if they are a moderator, `False` if they are not.
    """
    # Fetch the moderator list.
    moderators_list = [mod.name.lower() for mod in reddit.subreddit(subreddit_name).moderator()]

    # Go through the list and check the users to see if they are mods.
    # Return `True` if the user is a moderator, `False` if they are not.
    if query_username.lower() in moderators_list:
        logger.debug("Is User Mod: u/{} is a mod of r/{}.".format(query_username, subreddit_name))
        return True
    else:
        return False


"""MAIN ROUTINES"""


def main_monitored_integrity_checker():
    """This function double-checks the database to make sure the local
    list of subreddits that are being monitored are the same as the
    one that is live on-site, an integrity check.

    If it doesn't match, it'll remove ones it is not actually a
    moderator of. This function will also automatically remove a
    subreddit from the monitored list if it is banned by the site.

    :return: Nothing.
    """
    # Fetch the *live* list of moderated subreddits directly from
    # Reddit, including private ones. This needs to use the native
    # account.
    mod_target = '/user/{}/moderated_subreddits'.format(USERNAME_REG)
    active_subreddits = [x['sr'].lower() for x in connection.reddit.get(mod_target)['data']]

    # Get only the subreddits that are recorded BUT not live.
    stored_dbs = database.monitored_subreddits_retrieve()
    problematic_subreddits = [x for x in stored_dbs if x not in active_subreddits]

    # If there are extra ones we're not a mod of, remove them.
    if len(problematic_subreddits) > 0:
        for community in problematic_subreddits:

            # Remove their information to the history page.
            problematic_extended = database.extended_retrieve(community)
            problematic_extended['removal_utc'] = int(time.time())
            problematic_extended['instance'] = INSTANCE
            wikipage_access_history('remove', problematic_extended)

            # Delete the subreddit.
            database.subreddit_delete(community)
            logger.info('Integrity Checker: No longer mod of r/{}. Removed.'.format(community))

    return


def main_messages_log(data_package, other=False):
    """This function writes to a messages log for messages which are
    either fuzzed, matched, or did not have a viable match. It's
    linked to `messaging_parse_flair_response` and will not necessarily
    write one for all messaging matches, just non-standard ones or no
    matches at all.

    :param data_package: A dictionary of information passed from the
                         above function `messaging_parse_flair_response`
                         to append.
    :param other: Whether or not to write to the `_messages_other` file,
                  which is a more simple log.
    :return: `None`.
    """
    # Format the line to add to the messages log for the regular
    # routine, including the match types.
    message_date = timekeeping.convert_to_string(time.time())

    # Open the relevant file in append mode and add the new line.
    if not other:
        line_to_insert = ("\n| {6} | **r/{0}** | `{1}` | [Link](https://redd.it/{1}) "
                          "| {2} | {3} | `{4}` | `{5}` |")
        line_to_insert = line_to_insert.format(data_package['subreddit'], data_package['id'],
                                               data_package['action'],
                                               data_package['message'].replace('\n', ' '),
                                               data_package['template_name'],
                                               data_package['template_id'], message_date)
        with open(FILE_ADDRESS.messages, 'a+', encoding='utf-8') as f:
            f.write(line_to_insert)
    else:
        # Code an exception for any bots which constantly
        # spams replies back. No need to record these interactions.
        ignore_list = ['modnewsletter', 'reddit', 'redditcareresources', 'ytlinkerbot']
        if data_package['author'].lower() in ignore_list:
            return

        line_to_insert = "\n| {} | u/{} | `{}` | {} | {} |"
        line_to_insert = line_to_insert.format(message_date, data_package['author'],
                                               data_package['id'], data_package['subject'],
                                               data_package['message'].replace('\n', ' '))
        with open(FILE_ADDRESS.messages_other, 'a+', encoding='utf-8') as f:
            f.write(line_to_insert)

    return


def main_takeout(subreddit_name):
    """A function that fetches all the data of a subreddit and then
    uploads it to a time-limited Pastebin link. More info here:
    https://pbwrap.readthedocs.io/en/latest/pastebin.html and
    https://pastebin.com/api#6

    :param subreddit_name: Name of a subreddit.
    :return: A Pastebin link containing the takeout JSON data.
    """
    expiry_time = '1H'

    # Connect to Pastebin and authenticate.
    pb = Pastebin(INFO.pastebin_api_key)
    pb.authenticate(INFO.username[:12], INFO.pastebin_password)

    # Upload the data. `1` means it's an unlisted paste.
    json_data = database.takeout(subreddit_name.lower())

    # If the length of the JSON data is a set amount, then there is
    # nothing recorded because that's the default dictionary that is
    # created by the takeout function.
    if len(json_data) == 44:
        return None
    else:
        title = "Artemis Takeout Data for r/{}".format(subreddit_name)
        url = pb.create_paste(json_data, 1, title, expiry_time, 'json')
        database.counter_updater(subreddit_name, 'Exported takeout data', 'main')

    return url


def main_query_operations(id_list, specific_subreddit=None):
    """This function looks at the operations table of the posts passed
    into it as a list, and then returns a Markdown segment with tables
    of the Artemis operations conducted on those posts.
    If the function is fed bad data it will just return `None`.

    :param id_list: A list of Reddit submission IDs.
    :param specific_subreddit: If a normal moderator is requesting this
                               information, they can only see the
                               operations for posts in their subreddit.
                               If set to `None` (only for creator) then
                               all posts' information can be seen.
    :return: A Markdown formatted segment if information is obtained,
            otherwise, `None`.
    """
    operations_dictionary = {}

    # Retrieve the submissions from Reddit as PRAW objects. If invalid
    # this will return an empty list which can be used as a means to
    # exit the function. This also accounts for an empty or duplicates
    # in the passed list.
    if not id_list:
        return
    else:
        id_list = list(set(id_list))
    fullnames_list = ["t3_" + x for x in id_list]
    reddit_submissions = list(reddit.info(fullnames=fullnames_list))
    if not reddit_submissions:
        return

    # Iterate over each ID and place the PRAW object
    # as well as the retrieved dictionary in a tuple for it.
    for post_id in id_list:
        # Check to see that the post actually belongs to the
        # specified subreddit.
        try:
            equivalent_submission = [x for x in reddit_submissions if x.id == post_id][0]
        except IndexError:  # This is not recorded as a PRAW object.
            continue
        post_subreddit = equivalent_submission.subreddit.display_name.lower()

        # Exit early if the post's subreddit does not match the one
        # the function is supposed to grab. If the specific subreddit is
        # `None`, then it's from my creator and the information *can*
        # be returned.
        if specific_subreddit and specific_subreddit != post_subreddit:
            continue

        # Fetch the local operations data.
        database.CURSOR_MAIN.execute('SELECT * FROM posts_operations WHERE id = ?', (post_id,))
        operation_result = database.CURSOR_MAIN.fetchone()
        if not operation_result:  # Exit if no local results.
            continue

        operation_dict = literal_eval(operation_result[1])
        operations_dictionary[post_id] = (equivalent_submission, operation_dict)

    # Iterate over our dictionary and generate a formatted chunk for
    # each submission.
    ids_formatted = []
    for post_id in list(sorted(operations_dictionary.keys())):
        praw_object = operations_dictionary[post_id][0]
        dict_object = operations_dictionary[post_id][1]
        item_created = timekeeping.time_convert_to_string(praw_object.created_utc)

        # Get the author.
        try:
            author = praw_object.author.name
        except AttributeError:
            author = "[deleted]"

        # Get the post flair text and sanitize it for formatting. Then,
        # form a header.
        header = "#### [{}]({})\n\n* **Post ID**: `{}`\n* **Author**: u/{}\n"
        header = header.format(praw_object.title, praw_object.permalink, post_id, author)
        if praw_object.link_flair_text:
            rendered_flair = flair_sanitizer(praw_object.link_flair_text, False)
        else:
            rendered_flair = "None"
        header += "* **Created**: {}\n* **Current Post Flair**: {}".format(item_created,
                                                                           rendered_flair)
        # Try to get the "removed" status of the object. This will fail
        # if the bot does not have the `posts` mod permission.
        try:
            header += "\n* **Currently Removed?**: {}".format(praw_object.removed)
        except AttributeError:
            pass

        # Now iterate over the operations and form a table.
        # Note that the created time of the post is added as the first
        # line in the table.
        table_lines = ["| {} | User created post |".format(item_created)]
        table_header = "\n\n| Time (UTC) | Action |\n|------------|--------|\n"
        for item in list(sorted(dict_object.keys())):
            line = "| {} | {} |".format(timekeeping.time_convert_to_string(item),
                                        dict_object[item])
            table_lines.append(line)
        table = table_header + '\n'.join(table_lines)

        # Combine everything for this particular post.
        id_body = header + table
        ids_formatted.append(id_body)

    # Combine everything from all posts together.
    if not ids_formatted:
        return None
    else:
        combined_header = ("*Here are the Artemis actions data for {} "
                           "submission(s)*:\n\n---\n\n".format(len(ids_formatted)))
        combined_text = combined_header + "\n\n".join(ids_formatted)
        database.counter_updater(specific_subreddit, "Retrieved query data", 'main',
                                 action_count=len(ids_formatted))
        if len(combined_text) >= 10000:
            combined_text = combined_text[:9500] + ("\n\n---*This message has been truncated due "
                                                    "to private message length limits on Reddit. "
                                                    "Please try fewer IDs per query.")
            logger.info('Parse Operations: Text too long. Truncated and added reply.')

        return combined_text


def main_post_approval(submission, template_id=None, extended_data=None):
    """This function combines the flair setting and approval functions
    formerly used in both the `messaging_set_post_flair`
    and `main_flair_checker` functions in order to unify the process
    of checking and approving posts with flairs.

    It examines a submission to see if it now has a flair,
    and if it does, it restores them to the subreddit by approving the
    post. If a `template_id` is passed to it then this function helps
    select that flair for the user.

    Note: While the function assumes that the person who chooses a flair
    is the OP, it will also restore the post if a moderator is the one
    who picked a flair.

    It will NOT restore flaired posts that were removed by another
    moderator even if they are flaired. It will also proactively delete
    posts from the filtered database if they do not meet the
    requirements for processing.

    :param submission: The PRAW submission to examine and approve.
    :param template_id: An optionally passed flair template ID. It also
                        effectively acts as a Boolean for whether or not
                        this is part of the messaging system or the main
                        flair checker.
    :param extended_data: An optionally passed extended data package on
                          a subreddit. This is to reduce calls to the
                          database if that information is already
                          present as a dictionary.
    :return: `True` if post approved and everything went well,
             `False` otherwise.
    """
    # Define basic variables for the post.
    post_id = submission.id
    created = submission.created_utc
    post_subreddit = submission.subreddit.display_name.lower()
    post_css = submission.link_flair_css_class
    post_flair_text = submission.link_flair_text

    # A boolean that can be marked as `False` to indicate that the post
    # should not be processed by me.
    can_process = True

    # This is the username of the mod who removed the post.
    # This will be `None` if the post was not removed.
    moderator_removed = submission.banned_by

    # The number of reports the post has.
    num_reports = submission.num_reports

    # Check if the age is older than our limit.
    if int(time.time()) - created > SETTINGS.max_monitor_sec:
        logger.info('Post Approval: Post `{}` is 24+ hours old.'.format(post_id))
        can_process = False

    # Check to see if the moderator who removed it is Artemis.
    # We don't want to override other mods.
    if moderator_removed is not None:
        if moderator_removed != USERNAME_REG:
            # The moderator who removed this is not me. Don't restore.
            logger.debug('Post Approval: Post `{}` removed by mod u/{}.'.format(post_id,
                                                                                moderator_removed))
            database.counter_updater(post_subreddit, 'Other moderator removed post', "main",
                                     post_id=post_id, id_only=True)
            can_process = False

    # Check the number of reports existing on it. If there are some,
    # do not approve it. The number seems to be positive if the reports
    # are still present and the post has not been approved by a mod;
    # otherwise they will be negative.
    if num_reports is not None:
        if num_reports <= -4:
            logger.info('Post Approval: Post `{}` has {} reports.'.format(post_id, num_reports))
            database.counter_updater(post_subreddit, 'Excessive reports on post', "main",
                                     post_id=post_id, id_only=True)
            can_process = False

    # Check here to see if the author has deleted the post, which will
    # throw an `AttributeError` exception.
    # If that's true, the post is not eligible for processing.
    try:
        post_author = submission.author.name
        logger.debug("Post Approval: Post author is u/{}.".format(post_author))
    except AttributeError:
        # Author is deleted.
        logger.debug('Post Approval: Post `{}` author deleted.'.format(post_id))
        database.counter_updater(post_subreddit, 'Author deleted', "main",
                                 post_id=post_id, id_only=True)
        can_process = False

    # Run a check for the boolean `can_process`. If it's `False`,
    # delete the post ID from our database. This is done a little
    # earlier so that a call to grab mod permissions does not need to be
    # done if the post is not eligible for processing anyway.
    if not can_process:
        database.delete_filtered_post(post_id)
        logger.debug('Post Approval: Post `{}` not eligible for processing. '
                     'Deleted from filtered database.'.format(post_id))
        return False

    # Run the check to see if the post has been flaired yet, if we're
    # just using the `main_flair_checker` routine to check if it has
    # a flair. This DOES NOT delete the post from the database.
    if template_id is None and post_css is None and post_flair_text is None:
        logger.debug("Post Approval: Post `{}` still lacks flair.".format(post_id))
        return False

    # Get our permissions for this subreddit.
    # If Artemis is not a mod of this subreddit, Don't do anything.
    # This makes an API call, so we try to exit as much as possible
    # before it to speed things up.
    current_permissions = connection.obtain_mod_permissions(post_subreddit, INSTANCE)
    if not current_permissions[0]:
        return False
    else:
        # Collect the permissions as a list.
        current_permissions = current_permissions[1]

    # Get the extended data to see if I can approve the
    # post, then check extended data for whether or
    # not I should approve posts directly.
    # By default, we will be allowed to approve posts.
    if extended_data is None:
        extended_data = database.extended_retrieve(post_subreddit)
    approve_perm = extended_data.get('flair_enforce_approve_posts', True)

    # Checks complete. Now this function checks the post for whether it
    # should now be given a post flair if `template_id` is not `None`.
    if template_id is not None:
        if 'flair' in current_permissions or 'all' in current_permissions:
            # We flair it with the template ID that was provided.
            submission.flair.select(template_id)
            logger.debug('Post Approval: Directly flaired post `{}` on r/{} '
                         'with template `{}`.'.format(post_id, post_subreddit, template_id))
        else:
            # The reply was to select a flair but we do not have the
            # proper permissions to select flair for this submission.
            return False

    # After all that, check to see if approval can be given.
    # Either way, this is where messages are sent; either for strict
    # mode or for the default mode. This is also where the posts are
    # removed from the filtered database via `messaging_op_approved`.
    if approve_perm and 'posts' in current_permissions or 'all' in current_permissions:
        # Approve the post and send a message to the OP
        # letting them know that their post is approved.
        try:
            submission.mod.approve()
        except prawcore.exceptions.Forbidden:
            # If accidentally shadow-banned, this will be
            # triggered and the bot will check for a
            # shadow ban post that has already been up.
            logger.error('Post Approval: `403 Forbidden` error for approval. Shadowban?')
            sb_posts = list(reddit.subreddit(INFO.username[:12]).search("title:Shadowban",
                                                                        sort='new',
                                                                        time_filter='week'))

            # If this shadow-ban alert hasn't been submitted
            # yet, use u/ArtemisHelper instead to submit a
            # post about this possibility.
            if len(sb_posts) == 0:
                reddit_helper.subreddit(INFO.username[:12]).submit(title="Possible Shadowban",
                                                                   selftext='')
                logger.info('Post Approval: Submitted a possible shadowban '
                            'alert to r/AssistantBOT.')
        else:
            # Approval successful! Now check to see if the post
            # was mod-flaired.
            flaired_by_mod = messaging_modlog_parser(submission)
            messaging_op_approved(post_subreddit, submission, strict_mode=True,
                                  mod_flaired=flaired_by_mod)
            logger.info("Post Approval: Post `{}` on "
                        "r/{} flaired. Approved.".format(post_id, post_subreddit))

    else:
        # Approval needs to be manual, or the subreddit itself is only
        # in Default mode. Send the submission author the default
        # message instead.
        messaging_op_approved(post_subreddit, submission, strict_mode=False)
        logger.info('Post Approval: Sent the default approval message '
                    'to post `{}` author.'.format(post_id))

    # Check to see if there are specific tags for this
    # submission to assign.
    advanced_set_flair_tag(submission)

    return True


def main_post_schedule_reject(post_subreddit, post, post_author, schedule_data):
    """This function takes care of sending messages to individuals who
    submit posts on off-days from the schedule. It formats the message
    to send to them, and sends the actual message.

    :param post_subreddit: A PRAW subreddit object.
    :param post: A PRAW submission object.
    :param post_author: The author of the post, passed as a string.
    :param schedule_data: Data from `check_flair_schedule`, passed as a
                          tuple.
    :return: Nothing.
    """
    post_id = post.id
    post_flair_text = flair_sanitizer(post.link_flair_text, False)

    # Convert abbreviations to full weekday names for greater clarity.
    permitted_days = [timekeeping.convert_weekday_text(x) for x in schedule_data[1]]
    current_weekday = timekeeping.convert_weekday_text(schedule_data[2])

    # Format message to the user, using the template.
    message_to_send = MSG_SCHEDULE_REMOVAL.format(post_author, post.subreddit.display_name,
                                                  post_flair_text, ', '.join(permitted_days),
                                                  current_weekday, post.permalink)

    # Send a message to the author if they exist.
    if post_author != "[deleted]":
        flair_notifier(post, message_to_send)
        notify = "Schedule Reject: Sent message to u/{} about unscheduled post `{}`."
        logger.info(notify.format(post_author, post_id))

        # Record the action.
        database.counter_updater(post_subreddit, 'Removed unscheduled post',
                                 "main", post_id=post_id)
        logger.info('Get: >> Removed post `{}` on r/{} posted on '
                    'off-day from the schedule. '.format(post_id, post_subreddit))

    return


def main_messaging():
    """The basic function for checking for messages to the user account.

    This function also accepts certain defined commands if Artemis gets
    a message from a SUBREDDIT. A message from a moderator
    user account does *not* count.

    MOD COMMANDS (subject):
    `Disable`: Completely disable flair enforcing on a subreddit.
    `Enable`: Re-enable flair enforcing on a subreddit.
    `Example`: See an example of a flair enforcement message to users.
    `Update`: Create/update an advanced config page for a subreddit.
    `Query`: Retrieve information on posts processed by Artemis.
    `Revert`: Revert to the default config and clear all advanced
              settings.
    `Takeout`: Export a subreddit's Artemis data as JSON.

    There is also a function that removes the SUBREDDIT from being
    monitored when de-modded.

    :return: `None`.
    """
    # Get the unread messages from the inbox and process with oldest
    # first to newest last.
    messages = list(reddit.inbox.unread(limit=None))
    messages.reverse()

    # Iterate over the inbox, marking messages as read along the way.
    for message in messages:
        message.mark_read()

        # Define the variables of the message.
        msg_subject = message.subject.lower()
        msg_subreddit = message.subreddit
        msg_author = str(message.author)
        msg_body = message.body.strip().lower()
        msg_parent_id = message.parent_id

        # Artemis only accepts PMs. We skip everything else unless
        # it's a comment mentioning my username.
        if not message.fullname.startswith('t4_'):
            # This is a username mention of me.
            # It won't ever be a comment reply since I don't post
            # comments in non-locked posts.
            # Let my creator know of this mention and get the link
            # with full context of the comment.
            cmt_permalink = message.context[:-1] + "10000"
            omit_usernames = [INFO.creator.lower()] + connection.CONFIG.users_omit
            if message.fullname.startswith('t1_') and msg_author.lower() not in omit_usernames:
                # Make sure my creator isn't also tagged in the comment.
                if 'u/{}'.format(INFO.creator) not in message.body:
                    body_format = message.body.replace('\n', '\n> ')
                    message_content = "**[Link]({})**\n\n> ".format(cmt_permalink) + body_format
                    messaging_send_creator(msg_subreddit, 'mention',
                                           "* {}".format(message_content))
                    logger.debug('Messaging: Forwarded username mention'
                                 ' comment to my creator.')

                    # Save the comment that was a mention, by converting
                    # it into a PRAW object. This prevents it from being
                    # forwarded again when mentions are searched daily.
                    mention_comment = reddit.comment(id=message.fullname[3:])
                    mention_comment.save()
            else:
                logger.debug('Messaging: Inbox item is not a valid message. Skipped.')
            continue

        # Allow for remote maintenance actions from my creator.
        if msg_author == INFO.creator:
            logger.info('Messaging: Received `{}` message from my creator.'.format(msg_subject))

            # There are a number of remote actions available, including
            # manually disabling flair enforcement for a specific sub.
            if 'disable' in msg_subject:
                disabled_subreddit = msg_body.lower().strip()
                database.monitored_subreddits_enforce_change(disabled_subreddit, False)
                message.reply('Messaging: Disabled flair enforcement for '
                              'r/{}.'.format(disabled_subreddit))
            elif 'remove' in msg_subject:
                # Manually remove a subreddit from the monitored list.
                removed_subreddit = msg_body.lower().strip()
                database.subreddit_delete(removed_subreddit)
                message.reply('Messaging: Removed r/{} from monitoring.'.format(removed_subreddit))
            elif 'freeze' in msg_subject:
                # This instructs the bot to freeze a list of subreddits,
                # which means that statistics will no longer be
                # generated for them due to inactivity.
                # Parse the message body for a list of subreddits,
                # then insert an attribute into extended data.
                list_to_freeze = msg_body.lower().split(',')
                list_to_freeze = [x.strip() for x in list_to_freeze]
                for sub in list_to_freeze:
                    database.extended_insert(sub, {'freeze': True})
                    logger.info('Messaging: Froze r/{} at request of u/{}.'.format(sub,
                                                                                   INFO.creator))
                message.reply('Messaging: Froze these subreddits: **{}**.'.format(list_to_freeze))
            elif 'kill' in msg_subject:
                message.reply('Messaging: Terminated process runtime.')
                database.CONN_MAIN.close()
                database.CONN_STATS.close()
                logger.info('Messaging: Terminated process runtime via a `kill` command from '
                            'my creator.')
                sys.exit()

        # FLAIR ENFORCEMENT AND SELECTION
        # If the reply is to a flair enforcement message, we process it
        # and see if we can set it for the user.
        # There is no need to respond to a scheduling message because
        # there's nothing Artemis can do for the user about that.
        if "needs a post flair" in msg_subject and len(msg_subject) <= 88:
            # Get the subreddit name from the subject using RegEx.
            relevant_subreddit = re.findall(" r/([a-zA-Z0-9-_]*)", msg_subject)[0]

            # Get the relevant submission. We fetch the body of the
            # parent message and get the submission ID from that.
            # Of course, we make sure that there actually is a parent
            # message from myself to work with.
            if msg_parent_id is not None:
                parent_message = reddit.inbox.message(msg_parent_id[3:])
                message_parent_body = parent_message.body
                message_parent_author = parent_message.author.name
                relevant_post_id = re.findall("/comments/([a-zA-Z0-9-_]*)", message_parent_body)[0]
                logger.info('Messaging: Checking flair for '
                            'post `{}` by u/{}.'.format(relevant_post_id, msg_author))

                # Check if reply matches a template for the subreddit.
                # This returns a template ID or `None`.
                template_result = messaging_parse_flair_response(relevant_subreddit, msg_body,
                                                                 relevant_post_id)

                # If there's a matching template and the original sender
                # of the chain is Artemis, we set the post flair.
                # We first check to see if it's a post that is subject
                # to schedule rules.
                if template_result is not None and message_parent_author == USERNAME_REG:
                    relevant_submission = reddit.submission(relevant_post_id)

                    # Get the flair schedule and check the template
                    # against it. If there is no schedule, skip this
                    # step completely.
                    relevant_ext_data = database.extended_retrieve(relevant_subreddit)
                    flair_schedule = relevant_ext_data.get('flair_schedule', None)
                    if flair_schedule is not None:
                        schedule_data = timekeeping.check_flair_schedule(template_result,
                                                                         flair_schedule)
                        # If the post is not on a schedule day,
                        # exit early with a message to the author
                        # informing them that the flair is not
                        # posted on a scheduled day.
                        if not schedule_data[0]:
                            relevant_subreddit_obj = reddit.subreddit(relevant_subreddit)
                            main_post_schedule_reject(relevant_subreddit_obj, relevant_submission,
                                                      msg_author, schedule_data)
                            continue

                    main_post_approval(relevant_submission, template_result, relevant_ext_data)
                    logger.info('Messaging: > Set flair via messaging for '
                                'post `{}`.'.format(relevant_post_id))

            # Once this is completed, proceed to the next item.
            continue

        # If it's not a flair enforcement message, reject non-subreddit
        # messages. Flair enforcement replies to regular users were
        # done earlier. An example of such a message is a reply to a
        # flair confirmation message.
        if msg_subreddit is None:
            logger.debug('Messaging: > Message "{}" from u/{} is not from a '
                         'subreddit.'.format(msg_subject, msg_author))
            data_package = {'subject': msg_subject, 'author': msg_author, 'id': message.id,
                            'message': msg_body}

            # Save the message unless otherwise specified in a list
            # of users defined in configuration.
            if msg_author not in connection.CONFIG.users_reply_omit:
                main_messages_log(data_package=data_package, other=True)
            continue

        # MODERATION-RELATED MESSAGING FUNCTIONS
        # Get just the short name of the subreddit.
        relevant_subreddit = msg_subreddit.display_name.lower()

        if 'invitation to moderate' in msg_subject:
            # Note the invitation to moderate.
            logger.info("Messaging: New moderation invite from r/{}.".format(msg_subreddit))

            # Get a list of open instances.
            available = connection.CONFIG.available_instances
            open_instance = choice(["{}{}".format(INFO.username, x) for x in available if x != 99])

            # Check against our configuration data. Exit if it matches
            # pre-existing data.
            if relevant_subreddit in connection.CONFIG.subreddits_omit:
                # Message my creator about this.
                messaging_send_creator(relevant_subreddit, "omit",
                                       "View it at r/{}.".format(relevant_subreddit))
                continue

            # Check if this instance is currently open for invites.
            # If it's not, redirect with a reply and a redirect.
            if INSTANCE not in connection.CONFIG.available_instances:
                message.reply(MSG_MOD_INIT_REDIRECT.format(relevant_subreddit, open_instance))
                logger.info("Messaging: Current instance {} is not available for mod invites. "
                            "Replied with redirect message to u/{}.".format(INSTANCE,
                                                                            open_instance))
                continue

            # Check to see if the subreddit is already being currently
            # monitored by an instance of Artemis. This tuple's first
            # value will return `True` if the subreddit is already
            # monitored by an instance.
            instance_results = connection.monitored_instance_checker(relevant_subreddit)
            if instance_results[0]:
                active_instance = instance_results[1][0]
                message.reply(MSG_MOD_INIT_ALREADY_MONITORED.format(relevant_subreddit,
                                                                    active_instance,
                                                                    open_instance))
                logger.info("Messaging: Subreddit r/{} is already monitored by "
                            "an instance at {}.".format(relevant_subreddit, active_instance))
                continue

            # Check for minimum subscriber count.
            # Note that quarantined subreddits' subscriber counts will
            # return a 0 from the API as well, or they will throw an
            # exception: `prawcore.exceptions.Forbidden:` or another.
            try:
                subscriber_count = msg_subreddit.subscribers
            except prawcore.exceptions.Forbidden:
                # This subreddit is quarantined; message my creator.
                messaging_send_creator(relevant_subreddit, "forbidden",
                                       "View it at r/{}.".format(relevant_subreddit))
                # Also reply to the relevant subreddit.
                message.reply(MSG_MOD_INIT_QUARANTINED)
                continue
            except prawcore.exceptions.NotFound:
                # Error fetching the subscriber count.
                messaging_send_creator(relevant_subreddit, "not_found",
                                       "View it at r/{}.".format(relevant_subreddit))
                continue

            # Check if it's a user profile subreddit, that begins with
            # the prefix "u_". Since these don't have post flairs,
            # it's pointless to moderate them.
            if relevant_subreddit.startswith("u_"):
                logger.info("Messaging: > Invite to user profile subreddit. Not supported.")
                message.reply(MSG_MOD_INIT_PROFILE)
                continue

            # Actually accept the invitation to moderate.
            # There is an escape here in case the invite is already
            # accepted for some reason. For example, the subreddit may
            # have tried to send the invite at two separate times.
            try:
                message.subreddit.mod.accept_invite()
                logger.info("Messaging: > Invite accepted.")
            except praw.exceptions.APIException:
                logger.error("Messaging: > Moderation invite error. Already accepted? Withdrawn?")
                continue

            # Add the subreddit to our monitored list and we also fetch
            # some supplementary info for it, which is saved into the
            # extended data space.
            extended_data = {'created_utc': int(msg_subreddit.created_utc),
                             'display_name': msg_subreddit.display_name,
                             'added_utc': int(message.created_utc),
                             'invite_id': message.id}
            database.subreddit_insert(relevant_subreddit, extended_data)

            # Check for the minimum subscriber count.
            # If it's below the minimum, turn off statistics gathering.
            if subscriber_count < SETTINGS.min_s_stats:
                subscribers_until_minimum = SETTINGS.min_s_stats - subscriber_count
                minimum_section = MSG_MOD_INIT_MINIMUM.format(SETTINGS.min_s_stats,
                                                              subscribers_until_minimum)
                logger.info("Messaging: r/{} subscribers below "
                            "minimum required for statistics.".format(relevant_subreddit))
            else:
                minimum_section = MSG_MOD_INIT_NON_MINIMUM.format(relevant_subreddit)

            # Determine the permissions I have and what sort of status
            # the subreddit wants.
            current_permissions = connection.obtain_mod_permissions(relevant_subreddit, INSTANCE)
            if current_permissions[0]:
                # Fetch the list of moderator permissions we have.
                # The second element will be an empty list if Artemis is
                # a mod but has no actual permissions.
                # By default, Artemis will only *remind* unflaired
                # posts' submitters.
                list_perms = current_permissions[1]
                mode = "Default"
                mode_component = ""

                # This subreddit has opted for the strict mode if
                # `posts` mod permission is granted.
                if 'posts' in list_perms and 'wiki' in list_perms or 'all' in list_perms:
                    mode = "Strict"
                    mode_component = MSG_MOD_INIT_STRICT.format(relevant_subreddit)
                elif 'wiki' not in list_perms and 'all' not in list_perms:
                    # We were invited to be a mod but don't have the
                    # proper permissions. Let the mods know.
                    content = MSG_MOD_INIT_NEED_WIKI.format(relevant_subreddit)
                    message.reply(content + BOT_DISCLAIMER.format(relevant_subreddit))
                    logger.info("Messaging: Don't have the right permissions. Replied to sub.")

                # Check for the `flair` permission.
                if 'flair' in list_perms or 'all' in list_perms:
                    messaging_component = MSG_MOD_INIT_MESSAGING
                else:
                    messaging_component = ''
            else:
                # Exit as we are not a moderator. Note: This will not
                # exit if given *wrong* permissions.
                logger.info('Messaging: I do not appear to be a moderator '
                            'of this subreddit (Instance `{}`). Exiting...'.format(INSTANCE))
                return

            # Check for the templates that are available to Artemis and
            # see how many flair templates we can find.
            template_number = len(subreddit_templates_retrieve(relevant_subreddit))

            # There are no publicly available flairs for this sub.
            # Let the mods know.
            if template_number == 0:
                template_section = MSG_MOD_INIT_NO_FLAIRS
                # Disable flair enforcement since there are no flairs
                # for people to select anyway.
                database.monitored_subreddits_enforce_change(relevant_subreddit, False)
                logger.info("Messaging: Subreddit has no flairs. Disabled flair enforcement.")
                flair_mode = 'Off'
            else:
                # We have access to X number of templates on this
                # subreddit. Format the template section.
                template_section = ("\nThis subreddit has **{} user-accessible post flairs** "
                                    "to enforce:\n\n".format(template_number))
                template_section += subreddit_templates_collater(relevant_subreddit)
                flair_mode = connection.monitored_subreddits_enforce_mode(relevant_subreddit,
                                                                          INSTANCE)

            # Check against the history to see if this subreddit was on
            # a previous instance. If it is, migrate the data over to
            # the new database and let the mods know.
            previous_data = wikipage_access_history('read', None).get(relevant_subreddit, None)
            migration_component = ''
            if previous_data:
                previous_instance = previous_data.get('instance', None)
                if previous_instance != INSTANCE and previous_instance:
                    # Only migrate if the two instances are different.
                    database.migration_assistant(relevant_subreddit, previous_instance, INSTANCE)
                    migration_component = MSG_MOD_INSTANCE_MIGRATION.format(relevant_subreddit,
                                                                            previous_instance,
                                                                            INSTANCE)

            # Format the reply to the subreddit, and confirm the invite.
            body = MSG_MOD_INIT_ACCEPT.format(relevant_subreddit, mode_component, template_section,
                                              messaging_component, minimum_section,
                                              flair_mode, migration_component)
            message.reply(body + BOT_DISCLAIMER.format(relevant_subreddit))
            logger.info("Messaging: Sent confirmation reply. Set to `{}` mode.".format(mode))

            # If the flair enforce state is `On`, send an example
            # message as a new message to modmail.
            if database.monitored_subreddits_enforce_status(relevant_subreddit):
                example_text = "*Should your subreddit choose to enforce post flairs:*\n\n"
                example_text += messaging_example_collater(msg_subreddit)
                example_subject = ("[Artemis] Example Flair Enforcement Message "
                                   "for r/{}".format(relevant_subreddit))
                msg_subreddit.message(example_subject, example_text)
                logger.info("Messaging: Sent example message.".format(mode))

            # Post a submission to Artemis's profile noting that it is
            # active on the appropriate subreddit.
            # We do a quick check to see if we have noted this subreddit
            # before on my user profile. Mark NSFW appropriately.
            status = "Accepted mod invite to r/{}".format(relevant_subreddit)
            subreddit_url = 'https://www.reddit.com/r/{}'.format(relevant_subreddit)
            try:
                user_sub = 'u_{}'.format(USERNAME_REG)
                log_entry = reddit.subreddit(user_sub).submit(title=status, url=subreddit_url,
                                                              send_replies=False, resubmit=False,
                                                              nsfw=msg_subreddit.over18)
            except praw.exceptions.APIException:
                # This link was already submitted to my profile before.
                # Set `log_entry` to `None`. Send message to creator.
                logger.info('Messaging: r/{} has already been added '
                            'previously.'.format(relevant_subreddit))
                log_entry = None
            else:
                # If the log submission is successful, lock this log
                # entry so comments can't be made on it.
                log_entry.mod.lock()

            # Instruct stats to fetch initialization data for this
            # subreddit by writing the subreddit name into a scratch
            # file that stats will pick up, and clear.
            with open(FILE_ADDRESS.start, 'a+', encoding='utf-8') as f:
                start_data = "{}: {}".format(INSTANCE, relevant_subreddit)
                f.write("\n{}".format(start_data))

            if log_entry is not None:
                # This has not been noted before. Format a preview text.
                # Send a message to my creator notifying them about the
                # new addition if it's new.
                subreddit_about = msg_subreddit.public_description
                info = ('**r/{} ({:,} subscribers, created {})**'
                        '\n\n* `{}` mode\n\n> *{}*\n\n> {}')
                info = info.format(relevant_subreddit, msg_subreddit.subscribers,
                                   timekeeping.convert_to_string(msg_subreddit.created_utc),
                                   flair_mode, msg_subreddit.title,
                                   subreddit_about.replace("\n", "\n> "))

                # If the subreddit is public, add a comment and sticky.
                # Don't leave a comment if the subreddit is private and
                # not viewable by most people.
                if msg_subreddit.subreddit_type in ['public', 'restricted']:
                    log_comment = log_entry.reply(info)
                    log_comment.mod.distinguish(how='yes', sticky=True)
                    log_comment.mod.lock()

            # Check against the history.
            wikipage_access_history('readd', relevant_subreddit)

        # Takeout, or exporting data, is located here in order to allow
        # for subreddits that formerly used Artemis to gain access to
        # any stored data.
        if 'takeout' in msg_subject:
            logger.info('Messaging: New message to export '
                        'r/{} takeout data.'.format(relevant_subreddit))

            # Get the Pastebin data and reply to the message.
            pastebin_url = main_takeout(relevant_subreddit)
            if pastebin_url is not None:
                body = MSG_MOD_TAKEOUT.format(relevant_subreddit, pastebin_url)
            else:
                body = MSG_MOD_TAKEOUT_NONE.format(relevant_subreddit)
            message.reply(body + BOT_DISCLAIMER.format(relevant_subreddit))
            logger.info('Messaging: Replied with takeout data.')

        # EXIT EARLY if subreddit is NOT in monitored list and it wasn't
        # a mod invite or a takeout request, as there's no point in
        # processing said message.
        current_permissions = connection.obtain_mod_permissions(relevant_subreddit, INSTANCE)
        removal_subject = 'has been removed as a moderator from'
        if not current_permissions[0] and removal_subject not in msg_subject:
            # We got a message but we are not monitoring that subreddit.
            logger.info("Messaging: New message but not a mod of r/{}.".format(relevant_subreddit))
            continue

        # OTHER MODERATION-RELATED MESSAGING FUNCTIONS
        if 'enable' in msg_subject:
            # This is a request to toggle ON the flair_enforce status of
            # the subreddit.
            logger.info('Messaging: New message to enable '
                        'r/{} flair enforcing.'.format(relevant_subreddit))
            database.monitored_subreddits_enforce_change(relevant_subreddit, True)

            # Add the example flair enforcement text as well.
            # Also check to see if there are *actually* public flairs
            # available now. If there aren't any, append a header
            # letting the mods know.
            available_templates = subreddit_templates_retrieve(msg_subreddit.display_name)
            example_text = messaging_example_collater(msg_subreddit)
            if not len(available_templates):
                warning_header = MSG_MOD_INIT_NO_FLAIRS.rsplit('\n', 3)[0]
                example_text = "*Please note:*\n\n{}\n\n---\n\n{}".format(warning_header,
                                                                          example_text)
            message_body = "{}\n\n{}".format(MSG_MOD_RESP_ENABLE.format(relevant_subreddit),
                                             example_text)
            message.reply(message_body)

        elif 'disable' in msg_subject:
            # This is a request to toggle OFF the flair_enforce status
            # of the subreddit.
            logger.info('Messaging: New message to disable '
                        'r/{} flair enforcing.'.format(relevant_subreddit))
            database.monitored_subreddits_enforce_change(relevant_subreddit, False)
            message.reply(MSG_MOD_RESP_DISABLE.format(relevant_subreddit)
                          + BOT_DISCLAIMER.format(relevant_subreddit))

        elif 'example' in msg_subject:
            # This is a request to check out what the flair template
            # message looks like. Calls a sub-function.
            example_text = messaging_example_collater(msg_subreddit)
            message.reply(example_text)

        elif 'update' in msg_subject:
            logger.info('Messaging: New message to update '
                        'r/{} config data.'.format(relevant_subreddit))

            # The first argument will either be `True` or `False`.
            config_status = wikipage_config(relevant_subreddit)
            if config_status[0]:
                # Send back a reply confirming everything was processed
                # successfully and include an example of the flair
                # enforcement message.
                example_text = messaging_example_collater(msg_subreddit)
                reply_text = "{}\n\n---\n\n{}"
                reply_text = reply_text.format(CONFIG_GOOD.format(msg_subreddit.display_name),
                                               example_text)
                message.reply(reply_text)
                logger.info('Messaging: > Configuration data for '
                            'r/{} processed successfully.'.format(relevant_subreddit))
                database.counter_updater(relevant_subreddit, "Updated configuration", 'main')
            else:
                # Send back a reply noting that there was some sort of
                # error, and include the error.
                body = CONFIG_BAD.format(msg_subreddit.display_name, config_status[1])
                message.reply(body + BOT_DISCLAIMER.format(relevant_subreddit))
                logger.info('Messaging: > Configuration data for '
                            'r/{} encountered an error.'.format(relevant_subreddit))

        elif 'revert' in msg_subject:
            logger.info('Messaging: New message to revert '
                        'r/{} configuration data.'.format(relevant_subreddit))
            database.CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?",
                                         (relevant_subreddit,))
            result = database.CURSOR_MAIN.fetchone()
            if result is not None:
                # We have saved extended data. We want to wipe out the
                # settings.
                extended_data_existing = literal_eval(result[2])
                extended_keys = list(extended_data_existing.keys())

                # Iterate over the default variable keys and remove them
                # from the extended data in order to reset the info.
                default_vs_keys = list(yaml.safe_load(ADV_DEFAULT).keys())
                for key in extended_keys:
                    if key in default_vs_keys:
                        del extended_data_existing[key]  # Delete the settings.

                # Reset the settings in extended data.
                update_command = "UPDATE monitored SET extended = ? WHERE subreddit = ?"
                database.CURSOR_MAIN.execute(update_command, (str(extended_data_existing),
                                                              relevant_subreddit))
                database.CONN_MAIN.commit()

                # Clear the wikipage, and check the subreddit subscriber
                # number, to make sure of the accurate template.
                # If there are enough subscribers for userflair stats,
                # replace the relevant section to disable it..
                if msg_subreddit.subscribers > SETTINGS.min_s_userflair:
                    page_template = ADV_DEFAULT.replace('userflair_statistics: False',
                                                        'userflair_statistics: True')
                else:
                    page_template = str(ADV_DEFAULT)
                config_page = msg_subreddit.wiki["{}_config".format(INFO.username[:12])]
                config_page.edit(content=page_template,
                                 reason='Reverting configuration per mod request.')

                # Send back a reply.
                message.reply(CONFIG_REVERT.format(relevant_subreddit)
                              + BOT_DISCLAIMER.format(relevant_subreddit))
                database.counter_updater(relevant_subreddit, "Reverted configuration", 'main')
                logger.info('Messaging: > Config data for r/{} '
                            'reverted.'.format(relevant_subreddit))

        elif 'query' in msg_subject:
            # This fetches the operations that have been performed
            # by the bot on specific IDs.
            # This code allows for the input of long-form and short-form
            # links, as well as individual Reddit post IDs.
            extracted_ids = []
            list_of_items = re.split(r',|;|\s|\n', msg_body.lower())
            for item in list_of_items:
                if "comments" in item:
                    extracted_id = re.search(r'.*?comments/(\w+)/.*', item).group(1)
                elif "redd.it" in item:
                    extracted_id = re.search(r'redd.it/(.*)(?:/|\b)', item).group(1)
                else:
                    extracted_id = str(item)
                if extracted_id:
                    extracted_ids.append(extracted_id.strip())

            # If the person who sent it was my creator, allow for full
            # access. Otherwise, restrict to the subreddit it came from.
            if msg_author == INFO.creator:
                subreddit_check = None
            else:
                subreddit_check = str(relevant_subreddit)
            operations_info = main_query_operations(extracted_ids, subreddit_check)
            if operations_info:
                op_reply = operations_info
            else:
                op_reply = str(MSG_MOD_QUERY_NONE)
            message.reply(op_reply + BOT_DISCLAIMER.format(subreddit_check))
            logger.info('Messaging: Sent query operations data for `{}` '
                        'to r/{}.'.format(extracted_ids, relevant_subreddit))

        elif removal_subject in msg_subject:
            # Artemis was removed as a mod from a subreddit.
            # Delete from the monitored database.
            logger.info("Messaging: New demod message from r/{}.".format(relevant_subreddit))

            # Verification check to make sure it's the right one.
            # This prevents theoretical abuse of say, by a subreddit
            # sending a fake de-mod message for another subreddit.
            try:
                removed_subreddit = re.findall(r"[ /]r/([a-zA-Z0-9-_]*)", msg_subject)[0].lower()
            except IndexError:
                logger.error('Messaging: > Error retrieving subreddit name from message `{}` '
                             'with regex. Subject: {}'.format(message.id, msg_subject))
                continue

            # If the subreddits match, then we can process the removal.
            if removed_subreddit == relevant_subreddit:
                # Update the history with the removal.
                relevant_extended = database.extended_retrieve(relevant_subreddit)
                relevant_extended['removal_id'] = message.id
                relevant_extended['removal_utc'] = int(message.created_utc)
                relevant_extended['instance'] = INSTANCE
                wikipage_access_history("remove", {relevant_subreddit: relevant_extended})

                # Delete the subreddit from the monitored list.
                database.subreddit_delete(relevant_subreddit)
                message.reply(MSG_MOD_LEAVE.format(relevant_subreddit)
                              + BOT_DISCLAIMER.format(relevant_subreddit))
                database.counter_updater(relevant_subreddit, "Removed as moderator", "main")
                logger.info("Messaging: > Sent demod confirmation reply to moderators.")
            else:
                logger.error('Messaging: > Demod message is for r/{} but was sent '
                             'from r/{}.'.format(removed_subreddit, relevant_subreddit))
                continue

    return


def main_flair_checker():
    """This function checks the filtered database.
    It also uses `.info()` to retrieve PRAW submission objects,
    which is about 40 times faster than fetching one ID individually.

    This function will also clean the database of posts that are older
    than 24 hours by checking their timestamp.

    :return: Nothing.
    """
    fullname_ids = []

    # Access the database.
    database.CURSOR_MAIN.execute("SELECT * FROM posts_filtered")
    results = database.CURSOR_MAIN.fetchall()

    # If we have results, iterate over them, checking for age.
    # Note: Each result is a tuple with the ID in [0] and the
    # created Unix UTC time in [1] of the tuple.
    if len(results) != 0:
        for result in results:
            short_id = result[0]
            if int(time.time()) - result[1] > SETTINGS.max_monitor_sec:
                database.delete_filtered_post(short_id)
                database.counter_updater(None, "Cleared post", "main", post_id=short_id,
                                         id_only=True)
                logger.debug('Flair Checker: Deleted `{}` as it is too old.'.format(short_id))
            else:
                fullname_ids.append("t3_{}".format(short_id))

        # We have posts to look over. Convert the fullname IDs to PRAW
        # objects with `.info()`.
        reddit_submissions = reddit.info(fullnames=fullname_ids)

        # Iterate over our PRAW submission objects.
        for submission in reddit_submissions:
            # Pass the submission to the unified routine for processing.
            main_post_approval(submission)
            logger.debug('Flair Checker: Passed the post `{}` for '
                         'approval checking.'.format(submission.id))

    return


def main_get_posts_sections():
    """This function checks the moderated subreddits that have requested
    flair enforcing and divides them into smaller sets. This is because
    Reddit appears to have a limit of 250 subreddits per feed, which
    would mean that Artemis encounters the limit regularly.
    If the number of subreddits is below 250, the entirety will be
    returned as a one-item list.
    If there are zero subreddits, it will return an empty list.

    :return: A list of strings consisting of subreddits added together.
    """
    # Access the database, selecting only ones with flair enforcing.
    enforced_subreddits = database.monitored_subreddits_retrieve(True)

    # If the number of subreddits is few, don't return multiple chunks.
    if len(enforced_subreddits) == 0:
        logger.info('Get Posts Sections: No subreddits with flair enforcement.')
        return []
    elif 0 < len(enforced_subreddits) < 250:
        final_components = ['+'.join(enforced_subreddits)]
        logger.info('Get Posts Sections: {} subreddits with flair enforcement. '
                    'Returning as a single section.'.format(len(enforced_subreddits)))
        return final_components

    # Determine the number of subreddits we want per section.
    # Then divide the list into `num_chunks`chunks.
    # Then join the subreddits with `+` in order to make it
    # parsable by `main_get_submissions` as a "multi-reddit."
    n = int(len(enforced_subreddits) // SETTINGS.num_chunks) + 10
    my_range = len(enforced_subreddits) + n - 1
    final_lists = [enforced_subreddits[i * n:(i + 1) * n] for i in range(my_range // n)]
    final_components = ['+'.join(x) for x in final_lists]

    return final_components


def main_get_submissions(statistics_mode=False):
    """This function checks all the monitored subreddits' submissions
    and checks for new posts.
    If a new post does not have a flair, it will send a message to the
    submitter asking them to select a flair.
    If Artemis also has `posts` mod permissions, it will *also* remove
    that post until the user selects a flair.

    :param statistics_mode: Whether or not this is being run within
                            statistics mode.
    :return: Nothing.
    """
    # Access the posts from my moderated communities and add them to a
    # list. Reverse the posts so that we start processing the older ones
    # first. The newest posts will be processed last.
    # The communities are fetched in sections in order to keep the
    # coverage good. If the bot is started for the first time, a full
    # 1000 posts are fetched initially.
    posts = []
    sections = main_get_posts_sections()
    # Exit in the less likely case that there are no subreddits
    # whatsoever to monitor.
    if not len(sections):
        logger.info('Get: There are no subreddit sections to monitor. Exiting.')
        return

    for section in sections:
        if ISOCHRONISMS == 0:
            logger.info('Get: Starting fresh for section number {} '
                        'as there are 0 isochronisms.'.format(sections.index(section) + 1))
            pull_num = 1000
        elif statistics_mode and ISOCHRONISMS != 0:
            pull_num = int(NUMBER_TO_FETCH)
        else:
            pull_num = int(NUMBER_TO_FETCH / SETTINGS.num_chunks)
        posts += list(reddit.subreddit(section).new(limit=pull_num))
    posts.sort(key=lambda x: x.id.lower())
    processed = []  # List containing processed IDs as tuples.

    # Iterate over the fetched posts. We have a number of built-in
    # checks to reduce the amount of processing.
    for post in posts:

        # Check to see if this is a subreddit with flair enforcing.
        # Also retrieve a dictionary containing extended data.
        post_subreddit = post.subreddit.display_name.lower()
        sub_ext_data = database.extended_retrieve(post_subreddit)
        if not database.monitored_subreddits_enforce_status(post_subreddit):
            continue

        # Check to see if the post has already been processed.
        post_id = post.id
        database.CURSOR_MAIN.execute('SELECT * FROM posts_processed WHERE post_id = ?', (post_id,))
        if database.CURSOR_MAIN.fetchone():
            # Post is already in the database.
            logger.debug('Get: Post {} recorded in the processed database. Skip.'.format(post_id))
            continue

        # Check if the author exists. If they don't, give them the same
        # text Reddit would, which is `[deleted]`.
        try:
            post_author = post.author.name
        except AttributeError:
            post_author = "[deleted]"

        # Checks for the age of this post. We have a minimum and maximum
        # age. First check how many seconds old this post is.
        time_difference = time.time() - post.created_utc

        # Perform the age check. It should be older than our minimum age
        # and less than our maximum. We give OPs `minimum_age` seconds
        # to choose a flair. If it's a post that's younger than this,
        # skip.
        if time_difference < SETTINGS.min_monitor_sec:
            logger.debug('Get: Post {} is < {}s old. Skip.'.format(post_id,
                                                                   SETTINGS.min_monitor_sec))
            continue

        # If the time difference is greater than
        # `SETTINGS.max_monitor_sec / 4` seconds, skip (at 6 hours).
        # Artemis may have just been invited to moderate a subreddit; it
        # should not act on every old post.
        elif time_difference > (SETTINGS.max_monitor_sec / 4):
            msg = 'Get: Post {} is over {} seconds old. Skipped.'
            logger.debug(msg.format(post_id, (SETTINGS.max_monitor_sec / 4)))
            continue

        # Define basic attributes of the post.
        post_flair_css = post.link_flair_css_class
        post_flair_text = post.link_flair_text
        post_permalink = post.permalink
        post_nsfw = post.over_18

        # If the post is NSFW, we want to truncate the displayed text
        # on the terminal. Otherwise, replace potentially problematic
        # closing brackets.
        if post_nsfw:
            post_title = "{}...".format(post.title[:10])
        else:
            post_title = markdown_escaper(post.title)

        # Insert this post's ID into the processed list for insertion.
        # This is done as a tuple.
        database.CURSOR_MAIN.execute('INSERT INTO posts_processed VALUES(?)', (post_id,))
        database.CONN_MAIN.commit()
        processed.append(post_id)
        log_line = ('Get: New Post "{}" on r/{} (https://redd.it/{}), flaired with "{}". '
                    'Added to processed database.')
        logger.info(log_line.format(post_title, post_subreddit, post_id, post_flair_text))
        database.counter_updater(None, "Fetched post", "main", post_id=post_id, id_only=True)

        # Check to see if the author is me or AutoModerator.
        # If it is, don't process.
        if post_author.lower().startswith(INFO.username[:12].lower()) \
                or post_author.lower() == 'automoderator':
            logger.info('Get: > Post `{}` is by me or AutoModerator. Skipped.'.format(post_id))
            continue

        # We check for posts that have no flairs whatsoever.
        # If this post has no flair CSS and no flair text, then we can
        # act upon it. otherwise, we do skip it.
        if post_flair_css is None and post_flair_text is None:

            # Get our permissions for this subreddit.
            # If we are not a mod of this subreddit, don't do anything.
            # Otherwise, collect the mod permissions as a list.
            current_permissions = connection.obtain_mod_permissions(post_subreddit, INSTANCE)
            if not current_permissions[0]:
                continue
            else:
                current_permissions_list = current_permissions[1]

            # Check to see if the author is a moderator.
            # Artemis will not remove unflaired posts by mods.
            # But also check extended data for a boolean that denotes
            # whether or not flair enforcing should be conducted on
            # moderators.
            if 'flair_enforce_moderators' in sub_ext_data:
                enforce_moderators = sub_ext_data['flair_enforce_moderators']
                logger.debug('Get: > r/{} mods flair enforcement: {}.'.format(post_subreddit,
                                                                              enforce_moderators))
            else:
                # This is the default. Moderators will *not* have their
                # posts flair enforced.
                enforce_moderators = False

            # If they are a mod and enforcement is not turned on for
            # mods, don't do anything.
            if flair_is_user_mod(post_author, post_subreddit) and not enforce_moderators:
                logger.info('Get: > Post author u/{} is mod of r/{}. Skip.'.format(post_author,
                                                                                   post_subreddit))
                database.counter_updater(None, "Skipped mod post", "main", post_id=post_id,
                                         id_only=True)
                continue

            # Check to see if author is on a whitelist in extended data.
            if 'flair_enforce_whitelist' in sub_ext_data:
                if post_author.lower() in sub_ext_data['flair_enforce_whitelist']:
                    logger.info('Get: > Post author u/{} is on the extended whitelist. Skipped.')
                    database.counter_updater(None, "Skipped whitelist post", "main",
                                             post_id=post_id, id_only=True)
                    continue

            # Retrieve the available flairs as a Markdown list.
            # This will be blank if there aren't actually any flairs.
            available_templates = subreddit_templates_collater(post_subreddit)
            main_msg = "Get: > Post on r/{} (https://redd.it/{}) is unflaired."
            logger.info(main_msg.format(post_subreddit, post_id))

            # Format the modmail link for the OP to message in case
            # they have questions, and add a goodbye phrase.
            moderator_mail_link = MSG_USER_FLAIR_MODMAIL_LINK.format(post_subreddit,
                                                                     post_permalink)
            bye_phrase = sub_ext_data.get('custom_goodbye', choice(GOODBYE_PHRASES)).lower()
            if not bye_phrase:
                bye_phrase = choice(GOODBYE_PHRASES).lower()

            # Determine if we allow for flair selection via messaging.
            if 'flair' in current_permissions_list or 'all' in current_permissions_list:
                flair_option = MSG_USER_FLAIR_BODY_MESSAGING
            else:
                flair_option = ''

            # We are in strict enforcement mode, remove the post if we
            # have the permission to do so.
            if 'posts' in current_permissions_list or 'all' in current_permissions_list:

                # Write the object to the filtered database.
                flair_none_saver(post)

                # Remove the post. This is the only place a post can get
                # removed by Artemis.
                post.mod.remove()
                removal = "Get: >> Also removed post `{}` and added to the filtered database."
                logger.info(removal.format(post_id))
                database.counter_updater(post_subreddit, 'Removed post', "main", post_id=post_id)

                # Change the removal message depending on whether the
                # extended data allows for removal.
                auto_approve = sub_ext_data.get('flair_enforce_approve_posts', True)
                if auto_approve:
                    removal_option = MSG_USER_FLAIR_REMOVAL
                else:
                    removal_option = MSG_USER_FLAIR_REMOVAL_NO_APPROVE

                # Alert moderators who have opted in if necessary.
                # Send the PRAW object and a list of users.
                if "flair_enforce_alert_list" in sub_ext_data:
                    if len(sub_ext_data['flair_enforce_alert_list']) > 0:
                        advanced_send_alert(post, sub_ext_data['flair_enforce_alert_list'])
            else:
                # Not in strict enforcement mode. Send a normal message.
                database.counter_updater(post_subreddit, 'Sent flair reminder', "main",
                                         post_id=post_id)
                removal_option = ""

            # Check to see if there's a custom message to send to the
            # user from the extended configuration data.
            if 'flair_enforce_custom_message' in sub_ext_data:
                custom_message = sub_ext_data['flair_enforce_custom_message']
                if custom_message:
                    custom_text = '**Message from the moderators:** {}'.format(custom_message)
                else:
                    custom_text = ''
            else:
                custom_text = ''

            # Format message to the user, using the list of templates.
            # Tell OP that their post has been removed if that happened.
            message_to_send = MSG_USER_FLAIR_BODY.format(post_author, post.subreddit.display_name,
                                                         available_templates, post_permalink,
                                                         moderator_mail_link, removal_option,
                                                         bye_phrase, flair_option, post.title,
                                                         custom_text)

            # Send the flair reminder message to the user, but we want
            # to message only if there are actual flairs available and
            # if the author is not deleted.
            if len(available_templates) != 0 and post_author != "[deleted]":
                flair_notifier(post, message_to_send)
                notify = "Get: >> Sent message to u/{} about unflaired post `{}`."
                logger.info(notify.format(post_author, post_id))

        else:
            # Scheduling function to make sure posts match the schedule.
            # The post has a flair, but we need to check its template
            # if the subreddit has `flair_schedule` data to enforce
            # flairs on certain days only.
            if 'flair_schedule' in sub_ext_data:
                try:
                    post_flair_template = post.link_flair_template_id
                except AttributeError:
                    # There's a post flair but no template ID. Rare
                    # occurrence but it does happen.
                    logger.info('Get: >> Post `{}` has no flair template ID. '
                                'Skipping.'.format(post_id))
                    continue

                # Check to make sure I have the proper permissions for
                # this subreddit. Need to be able to remove posts.
                # Otherwise, collect the mod permissions as a list.
                current_permissions = connection.obtain_mod_permissions(post_subreddit, INSTANCE)
                if not current_permissions[0]:
                    continue
                else:
                    current_permissions_list = current_permissions[1]

                # If we can process posts properly, check the flair
                # template ID against the schedule.
                if 'posts' in current_permissions_list or 'all' in current_permissions_list:
                    # Gather data about the schedule and check to see
                    # if the post flair is allowable on the schedule.
                    scheduling_dictionary = sub_ext_data['flair_schedule']
                    schedule_data = timekeeping.check_flair_schedule(post_flair_template,
                                                                     scheduling_dictionary)
                    permission_for_schedule = schedule_data[0]

                    # The post does not fit our schedule. Remove and
                    # inform the author about it.
                    if not permission_for_schedule:
                        post.mod.remove()
                        main_post_schedule_reject(post_subreddit, post, post_author, schedule_data)
                else:
                    logger.info("Get: >> I do not have post removal permissions on r/{} to remove "
                                "post `{}` for the schedule.".format(post_subreddit, post_id))
                    continue

            # This post has a flair. We don't need to process it.
            logger.debug('Get: >> Post `{}` already has a flair. Doing nothing.'.format(post_id))
            continue

    # At the end, list the number of insertions into the `processed`
    # database out of all the ones fetched.
    if processed:
        logger.info('Get: Retrieval of {} new post IDs out of {} into processed '
                    'database COMPLETE.'.format(len(processed), len(posts)))

    return


# This is the regular loop for Artemis, running main functions in
# sequence while taking a `SETTINGS.wait` break in between.
if __name__ == "__main__":
    # Get the instance number as an integer.
    if len(sys.argv) > 1:
        INSTANCE = int(sys.argv[1].strip())
        logger.info("Launching with instance {}.".format(INSTANCE))
        database.define_database(INSTANCE)
    else:
        INSTANCE = 99

    # Log into Reddit.
    connection.login(False, INSTANCE)
    reddit = connection.reddit
    reddit_helper = connection.reddit_helper
    NUMBER_TO_FETCH = connection.NUMBER_TO_FETCH
    if INSTANCE != 99:
        USERNAME_REG = "{}{}".format(INFO.username, INSTANCE)
    else:
        USERNAME_REG = INFO.username

    try:
        while True:
            try:
                print('')
                logger.info("------- Isochronism {:,} START.".format(ISOCHRONISMS))

                # Every `post_frequency_cycles` recheck the frequency of
                # posts that come in to moderated subreddits, and check
                # the moderated subreddits' integrity.
                if not ISOCHRONISMS % SETTINGS.post_frequency_cycles and ISOCHRONISMS != 0:
                    connection.get_posts_frequency()
                    main_monitored_integrity_checker()
                # Update the operational status widget every
                # `post_frequency_cycles` cycles divided by 25.
                if not ISOCHRONISMS % (SETTINGS.post_frequency_cycles / 25):
                    widget_operational_status_updater()
                # Clean up the database and truncate the logs and
                # posts every `post_frequency_cycles` times 20.
                if not ISOCHRONISMS % (SETTINGS.post_frequency_cycles * 20) and ISOCHRONISMS != 0:
                    logger.info("Cleaning up database...")
                    database.cleanup()

                # Main runtime functions.
                main_messaging()
                main_get_submissions()
                main_flair_checker()

                # Record API usage limit.
                probe = reddit.redditor(USERNAME_REG).created_utc
                used_calls = reddit.auth.limits['used']

                # Record memory usage at the end of an isochronism.
                mem_num = psutil.Process(os.getpid()).memory_info().rss
                mem_usage = "Memory usage: {:.2f} MB.".format(mem_num / (1024 * 1024))
                logger.info("------- Isochronism {:,} COMPLETE. Calls used: {}. "
                            "{}\n".format(ISOCHRONISMS, used_calls, mem_usage))
            except SystemExit:
                logger.info('Manual user shutdown via message.')
                sys.exit()
            except Exception as e:
                # Artemis encountered an error/exception, and if the
                # error is not a common connection issue, log it in a
                # separate file. Otherwise, merely record it in the
                # events log.
                error_entry = "\n### {} \n\n".format(e)
                error_entry += traceback.format_exc()
                logger.error(error_entry)
                if not any(keyword in error_entry for keyword in SETTINGS.conn_errors):
                    main_error_log(error_entry)

            ISOCHRONISMS += 1
            time.sleep(SETTINGS.wait)
    except KeyboardInterrupt:
        # Manual termination of the script with Ctrl-C.
        logger.info('Manual user shutdown via keyboard.')
        database.CONN_MAIN.close()
        database.CONN_STATS.close()
        sys.exit()
