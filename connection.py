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
from settings import INFO, load_instances, SETTINGS


"""GLOBAL DEFINITIONS"""
# These values are defined later.
CONFIG = None
reddit = None
reddit_helper = None
reddit_monitor = None
INSTANCE = None
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
    target_page = reddit_helper.subreddit(SETTINGS.wiki).wiki["artemis_config"].content_md
    config_data = yaml.safe_load(target_page)

    # Here are some basic variables to use, making sure everything is
    # lowercase for consistency.
    config_data["subreddits_omit"] = [x.lower().strip() for x in config_data["subreddits_omit"]]
    config_data["users_omit"] = [x.lower().strip() for x in config_data["users_omit"]]
    config_data["users_omit"] += [INFO.creator]
    config_data["bots_comparative"] = [x.lower().strip() for x in config_data["bots_comparative"]]
    config_data["users_reply_omit"] = [x.lower().strip() for x in config_data["users_reply_omit"]]
    config_data["sub_mention_omit"] = [x.lower().strip() for x in config_data["sub_mention_omit"]]
    config_data["available_instances"] = [int(x) for x in config_data["available_instances"]]
    logger.info("Config Retriever: Available: {}".format(config_data["available_instances"]))

    # This is a custom phrase that can be included on all wiki pages as
    # an announcement from the bot creator.
    if "announcement" in config_data:
        # Format it properly as a header with an emoji.
        if config_data["announcement"] is not None:
            config_data["announcement"] = "📢 *{}*".format(config_data["announcement"])
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
    if not sys.platform.startswith("linux"):
        NUMBER_TO_FETCH = SETTINGS.min_get_posts
        logger.info(
            "Get Posts Frequency: Testing on `{}`. " "Limit set to minimum.".format(sys.platform)
        )
        return

    # 15 minutes is our interval to test for.
    # Begin processing from the oldest post.
    time_interval = SETTINGS.min_monitor_sec * 3
    # noinspection PyUnresolvedReferences
    posts = list(reddit.subreddit("mod").new(limit=SETTINGS.max_get_posts))
    posts.reverse()

    # Take the creation time of the oldest post and calculate the
    # interval between that and now. Then get the average time period
    # for posts to come in and the nominal amount of posts that come in
    # within our interval.
    time_difference = int(time.time()) - int(posts[0].created_utc)
    interval_between_posts = time_difference / SETTINGS.max_get_posts
    boundary_posts = int(time_interval / interval_between_posts)
    logger.info(
        "Get Posts Frequency: {:,} posts came in the last {:.2f} "
        "minutes. New post every {:.2f} seconds.".format(
            len(posts), time_difference / 60, interval_between_posts
        )
    )

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
        logger.info(
            "Get Posts Frequency: The broader limit of {} posts "
            "may need to be higher.".format(SETTINGS.max_get_posts)
        )
    elif NUMBER_TO_FETCH < SETTINGS.min_get_posts:
        NUMBER_TO_FETCH = int(SETTINGS.min_get_posts)
        logger.info(
            "Get Posts Frequency: Limit set to "
            "minimum limit of {} posts.".format(SETTINGS.min_get_posts)
        )
    else:
        logger.info(
            "Get Posts Frequency: Adjusted: "
            "{} posts / {} minutes.".format(NUMBER_TO_FETCH, int(time_interval / 60))
        )
        logger.info(
            "Get Posts Frequency: Actual: {:.2f} posts "
            "per minute.".format(NUMBER_TO_FETCH / 120)
        )
        logger.info(
            "Get Posts Frequency: {:.0f} posts per "
            "isochronism per section.".format(NUMBER_TO_FETCH / SETTINGS.num_chunks)
        )

    return


# noinspection PyGlobalUndefined,PyGlobalUndefined
def login(posts_frequency=True, instance_num=99):
    """A simple function to log in and authenticate to Reddit. This
    declares a global `reddit` object for all other functions to work
    with. It also authenticates under a secondary regular account as a
    work-around to get only user-accessible flairs from the subreddits
    it moderates and from which to post if shadowbanned.

    :param posts_frequency: A Boolean denoting whether we should
                            check for the post frequency.
    :param instance_num: An integer denoting which instance we want to
                         launch the bot as.
    :return: `None`, but global `reddit` and `reddit_helper` variables
             are declared.
    """
    # Declare the connections as global variables.
    global reddit
    global reddit_helper
    global reddit_monitor
    instance_login = SimpleNamespace(**load_instances(instance_num))

    # Format the instance.
    user_agent = "Artemis v{} (u/{}), a moderation assistant written by u/{}."
    if instance_num != 99:
        username_adapted = "{}{}".format(INFO.username, instance_num)
    else:
        username_adapted = INFO.username
    user_agent = user_agent.format(INFO.version_number, username_adapted, INFO.creator)

    # Authenticate the main connection.
    reddit = praw.Reddit(
        client_id=instance_login.app_id,
        client_secret=instance_login.app_secret,
        password=instance_login.password,
        user_agent=user_agent,
        username=username_adapted,
    )
    logger.info("Startup: Logging in as u/{}.".format(username_adapted))

    # Authenticate the secondary helper connection.
    reddit_helper = praw.Reddit(
        client_id=INFO.helper_app_id,
        client_secret=INFO.helper_app_secret,
        password=INFO.helper_password,
        user_agent="{} Assistant".format(INFO.username),
        username=INFO.helper_username,
    )

    # Access configuration data.
    config_retriever()
    if posts_frequency:
        get_posts_frequency()

    return


def obtain_mod_permissions(subreddit_name, instance_num=99):
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
    :param instance_num: Instance of the mod account we are checking.
    :return: A tuple. First item is `True`/`False` on whether Artemis is
                      a moderator.
                      Second item is a list of permissions, if any.
    """
    # noinspection PyUnresolvedReferences
    r = reddit.subreddit(subreddit_name)

    if instance_num != 99:
        check_username = "{}{}".format(INFO.username.lower(), instance_num)
    else:
        check_username = INFO.username.lower()

    # This is a try/except sequence to account for private subreddits
    # since one is unable to get a mod list from a private one.
    try:
        moderators_list = [mod.name.lower() for mod in r.moderator()]
    except prawcore.exceptions.Forbidden:
        return False, None
    am_mod = True if check_username in moderators_list else False

    if not am_mod:
        my_perms = None
    else:
        me_as_mod = [x for x in r.moderator(check_username) if x.name.lower() == check_username][0]

        # The permissions I have become a list. e.g. `['wiki']`
        my_perms = me_as_mod.mod_permissions

    return am_mod, my_perms


# noinspection PyUnresolvedReferences
def obtain_subreddit_public_moderated(username):
    """A function that retrieves (via the web and not the database)
    a list of public subreddits that a user moderates.

    :param username: Name of a user.
    :return: A list of subreddits that the user moderates.
    """
    subreddit_dict = {}
    active_subreddits = []
    active_fullnames = []

    # Iterate through the data and get the subreddit names and their
    # Reddit fullnames (prefixed with `t5_`). It will fail gracefully
    # if the account does not moderate anything.
    mod_target = "/user/{}/moderated_subreddits".format(username)
    try:
        for subreddit in reddit_helper.get(mod_target)["data"]:
            active_subreddits.append(subreddit["sr"].lower())
            active_fullnames.append(subreddit["name"].lower())
    except KeyError:  # This username does not moderate anything.
        return {}
    else:
        active_subreddits.sort()

    subreddit_dict["list"] = active_subreddits
    subreddit_dict["fullnames"] = active_fullnames
    subreddit_dict["total"] = len(active_subreddits)

    return subreddit_dict


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
    subject_dict = {
        "add": "Added former subreddit: r/{}",
        "remove": "Demodded from subreddit: r/{}",
        "forbidden": "Subscribers forbidden for subreddit: r/{}",
        "not_found": "Subscribers not found for subreddit: r/{}",
        "omit": "Omitted subreddit: r/{}",
        "mention": "New item mentioning Artemis on r/{}",
    }

    # If we have a matching subject type, send a message to the creator.
    if subject_type in subject_dict:
        # noinspection PyUnresolvedReferences
        creator = reddit.redditor(INFO.creator)
        creator.message(subject=subject_dict[subject_type].format(subreddit_name), message=message)

    return


def monitored_subreddits_enforce_mode(subreddit_name, instance_num=99):
    """This function returns a simple string telling us the flair
    enforcing MODE of the subreddit in question.

    :param subreddit_name: Name of a subreddit.
    :param instance_num: Instance number of a subreddit.
    :return: The Artemis mode of the subreddit as a string.
    """
    enforce_mode = "Default"
    enhancement = ""

    # Get the type of flair enforcing default/strict status.
    # Does it have the `posts` or `flair` mod permission?
    current_permissions = obtain_mod_permissions(subreddit_name.lower(), instance_num)

    # If I am a moderator, check for the `+` enhancement and then for
    # strict mode. Return `N/A` if not a moderator.
    if current_permissions[0]:
        if "flair" in current_permissions[1] or "all" in current_permissions[1]:
            enhancement = "+"
        if "posts" in current_permissions[1] or "all" in current_permissions[1]:
            enforce_mode = "Strict"
        flair_enforce_status = enforce_mode + enhancement
    else:
        flair_enforce_status = "N/A"

    return flair_enforce_status


def monitored_instance_checker(query_subreddit=None, max_num=9):
    """This function checks across all instances to see all the
    subreddits moderated. This is important for avoiding duplicate
    additions to a moderation team.

    :param query_subreddit: A subreddit to check if it's already
                            on the moderated list.
    :param max_num: The largest instance number there is an account for.
    :return: Tuples: `True` if the subreddit is already being monitored,
                     `False` if it isn't.
             Without a subreddit query, it just returns a broader
             dictionary with all the instance data.
    """
    full_dict = {}
    accounts_on = []
    usernames = [INFO.username, "AssistantBOT0"]
    count = 1

    # Create a list of the accounts to check.
    while count <= max_num:
        usernames.append("{}{}".format(INFO.username, count))
        count += 1
    logger.debug("Usernames to check for instances: {}".format(usernames))

    # Iterate through the usernames.
    for instance in usernames:
        instance_data = obtain_subreddit_public_moderated(instance)
        full_dict[instance] = instance_data

    # Iterate over the instances and check if the subreddit is on
    # any of them, if there is a subreddit to query. Otherwise,
    # just return the data dictionary.
    if query_subreddit:
        query_subreddit = query_subreddit.lower()
        logger.info("Instance Checker: Searching for subreddit r/{}".format(query_subreddit))
        for account in full_dict:
            if "list" in full_dict[account]:
                if query_subreddit in full_dict[account]["list"]:
                    accounts_on.append(account)
            else:
                continue

        if accounts_on:
            logger.info(
                "Instance Checker: Subreddit r/{} is "
                "already on instances: {}".format(query_subreddit, accounts_on)
            )
            return True, accounts_on
        else:
            logger.info(
                "Instance Checker: Subreddit r/{} is not "
                "moderated by any instance.".format(query_subreddit)
            )
            return False, []
    else:
        logger.info("Instance Checker: No subreddit query. Dictionary returned.")
        return full_dict


# Manual test of the configuration data.
if __name__ == "__main__":
    login(posts_frequency=False)
    config_retriever()
    print(CONFIG)
