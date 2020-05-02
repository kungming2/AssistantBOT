#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The connection component contains basic functions for login and
connection to Reddit.
"""
import sys
from types import SimpleNamespace

import praw
import prawcore
import yaml

from common import *
from settings import AUTH, SETTINGS


"""GLOBAL DEFINITIONS"""
# These values are defined later.
CONFIG = None
reddit = None
reddit_helper = None
NUMBER_TO_FETCH = SETTINGS.max_get_posts


def config_retriever():
    """This function retrieves data from a configuration page in order
    to get certain runtime variables. It also gets a chunk of text if
    present to serve as an announcement to be included on wikipages.
    For more on YAML syntax, please see:
    https://learn.getgrav.org/16/advanced/yaml

    :return: `None`.
    """
    global CONFIG

    # Access the configuration page on the wiki.
    # noinspection PyUnresolvedReferences
    target_page = reddit.subreddit('translatorBOT').wiki['artemis_config'].content_md
    config_data = yaml.safe_load(target_page)

    # Here are some basic variables to use, making sure everything is
    # lowercase for consistency.
    config_data['subreddits_omit'] = [x.lower().strip() for x in config_data['subreddits_omit']]
    config_data['users_omit'] = [x.lower().strip() for x in config_data['users_omit']]
    config_data['users_omit'] += [AUTH.creator]
    config_data['bots_comparative'] = [x.lower().strip() for x in config_data['bots_comparative']]

    # This is a custom phrase that can be included on all wiki pages as
    # an announcement from the bot creator.
    if 'announcement' in config_data:
        # Format it properly as a header with an emoji.
        if config_data['announcement'] is not None:
            config_data['announcement'] = "📢 *{}*".format(config_data['announcement'])
    CONFIG = SimpleNamespace(**config_data)

    return


# noinspection PyGlobalUndefined
def get_posts_frequency():
    """This function checks the frequency of posts that Artemis mods and
    returns a number that's based on 2x the number of posts retrieved
    during a specific interval. This is intended to be run once daily on
    a secondary thread.

    :return: `None`, but global variable `NUMBER_TO_FETCH` is declared.
    """
    global NUMBER_TO_FETCH

    # If not deployed on Linux, we can use a set number instead.
    if not sys.platform.startswith('linux'):
        NUMBER_TO_FETCH = SETTINGS.min_get_posts
        logger.info('Get Posts Frequency: Testing on `{}`. '
                    'Limit set to minimum.'.format(sys.platform))
        return

    # 15 minutes is our interval to test for.
    # Begin processing from the oldest post.
    time_interval = SETTINGS.min_monitor_sec * 3
    # noinspection PyUnresolvedReferences
    posts = list(reddit.subreddit('mod').new(limit=SETTINGS.max_get_posts))
    posts.reverse()

    # Take the creation time of the oldest post and calculate the
    # interval between that and now. Then get the average time period
    # for posts to come in and the nominal amount of posts that come in
    # within our interval.
    time_difference = (int(time.time()) - int(posts[0].created_utc))
    interval_between_posts = time_difference / SETTINGS.max_get_posts
    boundary_posts = int(time_interval / interval_between_posts)
    logger.info('Get Posts Frequency: {:,} posts came in the last {:.2f} '
                'minutes. New post every {:.2f} seconds.'.format(len(posts), time_difference / 60,
                                                                 interval_between_posts))

    # Next we determine how many posts Artemis should *fetch* in a 15
    # minute period defined by the data. That number is 2 times the
    # earlier number in order to account for overlap.
    if boundary_posts < SETTINGS.max_get_posts:
        NUMBER_TO_FETCH = int(boundary_posts * 2)
    else:
        NUMBER_TO_FETCH = SETTINGS.max_get_posts

    # If we need to adjust the broader limit, note that. Also make sure
    # the number to fetch is always at least our minimum.
    if SETTINGS.max_get_posts < NUMBER_TO_FETCH:
        logger.info('Get Posts Frequency: The broader limit of {} posts '
                    'may need to be higher.'.format(SETTINGS.max_get_posts))
    elif NUMBER_TO_FETCH < SETTINGS.min_get_posts:
        NUMBER_TO_FETCH = int(SETTINGS.min_get_posts)
        logger.info('Get Posts Frequency: Limit set to '
                    'minimum limit of {} posts.'.format(SETTINGS.min_get_posts))
    else:
        logger.info('Get Posts Frequency: Adjusted: '
                    '{} posts / {} minutes.'.format(NUMBER_TO_FETCH, int(time_interval / 60)))
        logger.info('Get Posts Frequency: Actual: {:.2f} posts '
                    'per minute.'.format(NUMBER_TO_FETCH / 120))
        logger.info('Get Posts Frequency: {:.0f} posts per '
                    'isochronism per section.'.format(NUMBER_TO_FETCH / SETTINGS.num_chunks))

    return


# noinspection PyGlobalUndefined,PyGlobalUndefined
def login(posts_frequency=True):
    """A simple function to log in and authenticate to Reddit. This
    declares a global `reddit` object for all other functions to work
    with. It also authenticates under a secondary regular account as a
    work-around to get only user-accessible flairs from the subreddits
    it moderates and from which to post if shadowbanned.

    :param posts_frequency: A Boolean denoting whether we should
                            check for the post frequency.
    :return: `None`, but global `reddit` and `reddit_helper` variables
             are declared.
    """
    # Declare the connections as global variables.
    global reddit
    global reddit_helper

    # Authenticate the main connection.
    user_agent = 'Artemis v{} (u/{}), a moderation assistant written by u/{}.'
    user_agent = user_agent.format(AUTH.version_number, AUTH.username, AUTH.creator)
    reddit = praw.Reddit(client_id=AUTH.app_id,
                         client_secret=AUTH.app_secret,
                         password=AUTH.password,
                         user_agent=user_agent, username=AUTH.username)
    logger.info("Startup: Logging in as u/{}.".format(AUTH.username))

    # Authenticate the secondary helper connection.
    reddit_helper = praw.Reddit(client_id=AUTH.helper_app_id,
                                client_secret=AUTH.helper_app_secret,
                                password=AUTH.helper_password,
                                user_agent="{} Assistant".format(AUTH.username),
                                username=AUTH.helper_username)

    # Access configuration data.
    config_retriever()
    if posts_frequency:
        get_posts_frequency()

    return


def obtain_mod_permissions(subreddit_name):
    """A function to check if Artemis has mod permissions in a
    subreddit, and what kind of mod permissions it has.
    The important ones Artemis needs are: `wiki`, so that it can edit
                                          the statistics wikipage.
                                          `posts` (optional), so that it
                                          can remove unflaired posts.
                                          'flair` (optional), so that it
                                          can directly flair posts via
                                          messaging.
    Giving Artemis extra permissions doesn't matter as it will not
    use any of them.
    More info: https://www.reddit.com/r/modhelp/wiki/mod_permissions

    :param subreddit_name: Name of a subreddit.
    :return: A tuple. First item is `True`/`False` on whether Artemis is
                      a moderator.
                      Second item is a list of permissions, if any.
    """
    # noinspection PyUnresolvedReferences
    r = reddit.subreddit(subreddit_name)

    # This is a try/except sequence to account for private subreddits
    # since one is unable to get a mod list from a private one.
    try:
        moderators_list = [mod.name.lower() for mod in r.moderator()]
    except prawcore.exceptions.Forbidden:
        return False, None
    am_mod = True if AUTH.username.lower() in moderators_list else False

    if not am_mod:
        my_perms = None
    else:
        me_as_mod = [x for x in r.moderator(AUTH.username) if x.name == AUTH.username][0]

        # The permissions I have become a list. e.g. `['wiki']`
        my_perms = me_as_mod.mod_permissions

    return am_mod, my_perms


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

    # If we have a matching subject type, send a message to the creator.
    if subject_type in subject_dict:
        # noinspection PyUnresolvedReferences
        creator = reddit.redditor(AUTH.creator)
        creator.message(subject=subject_dict[subject_type].format(subreddit_name), message=message)

    return


def monitored_subreddits_enforce_mode(subreddit_name):
    """This function returns a simple string telling us the flair
    enforcing MODE of the subreddit in question.

    :param subreddit_name: Name of a subreddit.
    :return: The Artemis mode of the subreddit as a string.
    """
    enforce_mode = 'Default'
    enhancement = ""

    # Get the type of flair enforcing default/strict status.
    # Does it have the `posts` or `flair` mod permission?
    current_permissions = obtain_mod_permissions(subreddit_name.lower())

    # If I am a moderator, check for the `+` enhancement and then for
    # strict mode. Return `N/A` if not a moderator.
    if current_permissions[0]:
        if 'flair' in current_permissions[1] or 'all' in current_permissions[1]:
            enhancement = "+"
        if 'posts' in current_permissions[1] or 'all' in current_permissions[1]:
            enforce_mode = 'Strict'
        flair_enforce_status = enforce_mode + enhancement
    else:
        flair_enforce_status = 'N/A'

    return flair_enforce_status
