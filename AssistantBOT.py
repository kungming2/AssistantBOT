#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Artemis (u/AssistantBOT) is a flair enforcer and statistics compiler
for subreddits that have invited it to assist.

Artemis has two primary functions:
* **Enforcing post flairs on a subreddit**.
* **Recording useful statistics for a subreddit**.

Written and maintained by u/kungming2.
For more information see: https://www.reddit.com/r/AssistantBOT
"""

import ast
import calendar
import datetime
import logging
import os
import random
import re
import shutil
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
from collections import OrderedDict
from urllib.error import HTTPError, URLError

import praw
import prawcore
import pytz
import requests
import yaml
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from requests.exceptions import ConnectionError

from _text import *

"""INITIALIZATION INFORMATION"""

VERSION_NUMBER = "1.6.31 Ginkgo"

# Define the location of the main files Artemis uses.
# They should all be in the same folder as the Python script itself.
SOURCE_FOLDER = os.path.dirname(os.path.realpath(__file__))
FILE_ADDRESS_DATA = SOURCE_FOLDER + "/_data.db"
FILE_ADDRESS_ERROR = SOURCE_FOLDER + "/_error.md"
FILE_ADDRESS_LOGS = SOURCE_FOLDER + "/_logs.md"
FILE_ADDRESS_INFO = SOURCE_FOLDER + "/_info.yaml"

"""LOAD CREDENTIALS, LOGGER, AND CONSTANT VARIABLES"""


def load_information():
    """Function that takes information on login/OAuth access from an
    external YAML file and loads it as a dictionary.

    :return: A dictionary with keys for important variables needed to
             log in and authenticate.
    """
    with open(FILE_ADDRESS_INFO, 'r', encoding='utf-8') as f:
        info_data = f.read()

    return yaml.safe_load(info_data)


# noinspection PyGlobalUndefined
def load_logger():
    """Define the logger to use and its parameters for formatting,
    and declare it as a global variable for other functions.

    :return: `None`.
    """
    global logger

    # Set up the logger. By default only display INFO or higher levels.
    log_format = '%(levelname)s: %(asctime)s - [Artemis] v{} %(message)s'
    logformatter = log_format.format(VERSION_NUMBER)
    logging.basicConfig(format=logformatter, level=logging.INFO)

    # Set the logging time to UTC.
    logging.Formatter.converter = time.gmtime
    logger = logging.getLogger(__name__)

    # Define the logging handler (the file to write to.)
    handler = logging.FileHandler(FILE_ADDRESS_LOGS, 'a', 'utf-8')

    # By default only log INFO level messages or higher.
    handler.setLevel(logging.INFO)

    # Set the time format in the logging handler.
    d = "%Y-%m-%dT%H:%M:%SZ"
    handler.setFormatter(logging.Formatter(logformatter, datefmt=d))
    logger.addHandler(handler)

    return


"""INITIAL SET-UP"""

# Load the logger.
load_logger()

# Retrieve credentials data needed to log in from the YAML file.
ARTEMIS_INFO = load_information()
USERNAME = ARTEMIS_INFO['username']
CREATOR = ARTEMIS_INFO['creator']

# Number of seconds Artemis waits in between runs.
WAIT = 30

# This retrieves cloud and local folder paths that files are backed to.
BACKUP_FOLDER = ARTEMIS_INFO['backup_folder']
BACKUP_FOLDER_LOCAL = ARTEMIS_INFO['backup_folder_2']
BOT_DISCLAIMER = ("\n\n---\n^Artemis: ^a ^moderation ^assistant ^for ^r/{0} ^| "
                  "[^Contact ^r/{0} ^mods](https://www.reddit.com/message/compose?to=%2Fr%2F{0}) "
                  "^| [^Bot ^Info/Support](https://www.reddit.com/r/AssistantBOT/)")

# This connects Artemis with its main SQLite database file.
CONN_DATA = sqlite3.connect(FILE_ADDRESS_DATA)
CURSOR_DATA = CONN_DATA.cursor()

# We don't want to log common connection errors.
CONNECTION_ERRORS = ['500 HTTP', '502 HTTP', '503 HTTP', '504 HTTP', 'RequestException']


"""BASIC VARIABLES"""

# These are major subscriber milestones that a subreddit reaches.
SUBSCRIBER_MILESTONES = [10, 20, 25, 50, 100, 250, 500, 750,
                         1000, 2000, 2500, 3000, 4000, 5000, 6000,
                         7000, 7500, 8000, 9000, 10000, 15000, 20000,
                         25000, 30000, 40000, 50000, 60000, 70000,
                         75000, 80000, 90000, 100000, 150000, 200000,
                         250000, 300000, 400000, 500000, 600000, 700000,
                         750000, 800000, 900000, 1000000, 1250000,
                         1500000, 1750000, 2000000, 2500000, 3000000,
                         4000000, 5000000, 6000000, 7000000, 7500000,
                         8000000, 9000000, 10000000, 15000000, 20000000,
                         25000000, 30000000]

# The day of the month for monthly statistics functions to run.
MONTH_ACTION_DAY = 4

# The hour daily functions will run (midnight UTC in this case).
ACTION_TIME = 0

# The number of Pushshift entries to display in statistics pages.
NUMBER_TO_RETURN = 5

# Minimum and maximum ages (in secs) for Artemis to act on posts.
# The first variable is often used as a baseline for other times.
MINIMUM_AGE_TO_MONITOR = 300
MAXIMUM_AGE_TO_MONITOR = 86400

# A subreddit has to have at least this many subscribers for statistics,
# and a minimum default amount for userflair statistics.
MINIMUM_SUBSCRIBERS = 25
MINIMUM_SUBSCRIBERS_USERFLAIR = 50000

# The number of data entries to store, and how many posts to pull.
ENTRIES_TO_KEEP = 8000
POSTS_BROADER_LIMIT = 500
POSTS_MINIMUM_LIMIT = 175

# Global dictionary that stores formatted data for statistics pages,
# which is cleared after the daily statistics run.
UPDATER_DICTIONARY = {}


"""DATE/TIME CONVERSION FUNCTIONS"""


def date_convert_to_string(unix_integer):
    """Converts a UNIX integer into a date formatted as YYYY-MM-DD,
    according to the UTC equivalent (not local time).

    :param unix_integer: Any UNIX time number.
    :return: A string formatted with UTC time.
    """
    i = int(unix_integer)
    f = "%Y-%m-%d"
    date_string = datetime.datetime.utcfromtimestamp(i).strftime(f)

    return date_string


def date_convert_to_unix(date_string):
    """Converts a date formatted as YYYY-MM-DD into a Unix integer of
    its equivalent UTC time. One can use `common_timezones` in the
    `pytz` module to get a list of commonly used time zones.
    This UTC offset should be altered in the unlikely event that
    Artemis is moved to a new time zone.

    :param date_string: Any date formatted as YYYY-MM-DD.
    :return: The string timestamp of MIDNIGHT that day in UTC.
    """
    # Account for timezone differences, by getting the
    # UTC offset of the region in seconds.
    tz = pytz.timezone('US/Pacific')
    time_difference_sec = int(datetime.datetime.now(tz).utcoffset().total_seconds())

    # Get the Unix timestamp by adding the time difference to
    # the local time.
    utc_timestamp = int(time.mktime(time.strptime(date_string, '%Y-%m-%d'))) + time_difference_sec

    return utc_timestamp


def date_month_convert_to_string(unix_integer):
    """Converts a UNIX integer into a date formatted as YYYY-MM.
    This just retrieves the month string.

    :param unix_integer: Any UNIX time number.
    :return: A month string formatted as YYYY-MM.
    """
    month_string = datetime.datetime.utcfromtimestamp(int(unix_integer)).strftime("%Y-%m")

    return month_string


def date_num_days_between(start_day, end_day):
    """This simple function returns the number of days between
    two given days expressed as strings.

    :param start_day: The day we begin counting from.
    :param end_day: The day we end counting at.
    :return: An integer with the number of days.
    """
    f = "%Y-%m-%d"
    end = datetime.datetime.strptime(end_day, f)
    days_difference = abs((end - datetime.datetime.strptime(start_day, f)).days)

    return days_difference


def date_get_series_of_days(start_day, end_day):
    """A function that takes two date strings and returns a list of all
    days that are between those two days. For example, if passed
    `2018-11-01` and `2018-11-03`, it will also give back a list
    like this:

    ['2018-11-01', '2018-11-02', '2018-11-03'].

    (Note: The list includes the start and end dates.)

    :param start_day: A YYYY-MM-DD string to start.
    :param end_day: A  YYYY-MM-DD string to end.
    :return: A list of days in the YYYY-MM-DD format.
    """
    days_list = []
    f = "%Y-%m-%d"

    # Convert our date strings into datetime objects.
    start_day = datetime.datetime.strptime(start_day, f)
    end_day = datetime.datetime.strptime(end_day, f)

    # Derive the time difference between the two dates.
    delta = end_day - start_day

    # Iterate and get steps, a day each, and append each to the list.
    for i in range(delta.days + 1):
        days_list.append(str((start_day + datetime.timedelta(i)).strftime(f)))

    return days_list


def date_get_historical_series_days(list_of_days):
    """Takes a list of days in YYYY-MM-DD and returns another list.
    If the original list is less than 120 days long, it just returns
    the same list. Otherwise, it tries to get the start of the month.
    This is generally to avoid Artemis having to search through years'
    of data on relatively inactive subreddits.

    :param list_of_days: A list of days in YYYY-MM-DD format.
    :return: Another list of days, the ones to get data for.
    """
    # The max number of past days we want to get historical data for.
    days_limit = 120

    # If number of days contained is fewer than our limit, just return
    # the whole thing back. Otherwise, truncate the number of days.
    if len(list_of_days) <= days_limit:
        pass
    else:
        # This is longer than our limit of days. Truncate it down.
        # If we can get an extra *full* month past this, get it.
        if len(list_of_days) > days_limit + 31:
            first_day = list_of_days[(-1 * days_limit):][0]
            initial_start = first_day[:-3] + '-01'
            list_of_days = list_of_days[list_of_days.index(initial_start):]
        else:
            # Otherwise, just return the last 90 days.
            list_of_days = list_of_days[(-1 * days_limit):]

    return list_of_days


"""DATABASE FUNCTIONS"""


def database_subreddit_insert(community_name, supplement):
    """Add a subreddit to the moderated list. This means Artemis will
    actively work on that community. This function will also check to
    make sure it is not already in the database.

    :param community_name: Name of a subreddit (no r/).
    :param supplement: A dictionary of additional data that we want to
                       save to the database.
    :return: Nothing.
    """
    community_name = community_name.lower()
    command = "SELECT * FROM monitored WHERE subreddit = ?"
    CURSOR_DATA.execute(command, (community_name,))
    result = CURSOR_DATA.fetchone()

    # If the subreddit was not previously in database, insert it in.
    # 1 is the same as `True` for flair enforcing (default setting).
    if result is None:
        CURSOR_DATA.execute("INSERT INTO monitored VALUES (?, ?, ?)",
                            (community_name, 1, str(supplement)))
        CONN_DATA.commit()
        logger.debug("Sub Insert: r/{} added to monitored database.".format(community_name))

    return


def database_subreddit_delete(community_name):
    """This function removes a subreddit from the moderated list and
    Artemis will NO LONGER assist that community.

    :param community_name: Name of a subreddit (no r/).
    :return: Nothing.
    """
    community_name = community_name.lower()
    CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (community_name,))
    result = CURSOR_DATA.fetchone()

    if result is not None:  # Subreddit is in database. Let's remove it.
        CURSOR_DATA.execute("DELETE FROM monitored WHERE subreddit = ?",
                            (community_name,))
        CONN_DATA.commit()
        logger.debug('Sub Delete: r/{} deleted from monitored database.'.format(community_name))

    return


def database_monitored_subreddits_retrieve(flair_enforce_only=False):
    """This function returns a list of all the subreddits that
    Artemis monitors WITHOUT the 'r/' prefix.

    :param flair_enforce_only: A Boolean that if `True`, only returns
                               the subreddits that have flair enforcing
                               turned on.
    :return: A list of all monitored subreddits, in the order which
             they were first stored, oldest to newest.
    """
    if not flair_enforce_only:
        CURSOR_DATA.execute("SELECT * FROM monitored")
    else:
        CURSOR_DATA.execute("SELECT * FROM monitored WHERE flair_enforce is 1")
    results = CURSOR_DATA.fetchall()

    # Gather the saved subreddits' names and add them into a list.
    final_list = [x[0].lower() for x in results]

    return final_list


def database_monitored_subreddits_enforce_change(subreddit_name, to_enforce):
    """This simple function changes the `flair_enforce` status of a
    monitored subreddit.

    True (1): Artemis will send messages reminding
              people of the flairs available. (default behavior)
    False (0): Artemis will not send any messages about flairs,
               making Artemis a statistics-only assistant.

    Note that this is completely separate from the "strict enforcing"
    function. That's covered under `True`.

    :param subreddit_name: The subreddit to modify.
    :param to_enforce: A Boolean denoting which to set it to.
    :return:
    """
    subreddit_name = subreddit_name.lower()
    # Convert the booleans to SQLite3 integers. 1 = True, 0 = False.
    s_digit = int(to_enforce)

    # Access the database.
    CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # This subreddit is stored in the monitored database; modify it.
    if result is not None:

        # If the current status is different, change it.
        if result[1] != s_digit:
            CURSOR_DATA.execute("UPDATE monitored SET flair_enforce = ? WHERE subreddit = ?",
                                (s_digit, subreddit_name))
            CONN_DATA.commit()
            logger.info("Enforce Change: r/{} flair enforce set to `{}`.".format(subreddit_name,
                                                                                 to_enforce))

    return


def database_monitored_subreddits_enforce_status(subreddit_name):
    """A function that returns True or False depending on the
    subreddit's `flair_enforce` status.
    That status is stored as an integer and converted into a Boolean.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A boolean. Default is True.
    """
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # This subreddit is stored in our monitored database; access it.
    if result is not None:
        # This is the current status.
        flair_enforce_status = bool(result[1])
        logger.debug("Enforce Status: r/{} flair enforce status: {}.".format(subreddit_name,
                                                                             flair_enforce_status))
        if not flair_enforce_status:
            return False

    return True


def database_monitored_subreddits_enforce_mode(subreddit_name):
    """This function returns a simple string telling us the flair
    enforcing MODE of the subreddit in question.

    :param subreddit_name: Name of a subreddit.
    :return: The Artemis mode of the subreddit as a string.
    """
    subreddit_name = subreddit_name.lower()
    enforce_mode = 'Default'
    enhancement = ""

    # Get the type of flair enforcing default/strict status.
    # Does it have the `posts` or `flair` mod permission?
    current_permissions = main_obtain_mod_permissions(subreddit_name)

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


def database_monitored_integrity_checker():
    """This function double-checks the database to make sure the local
    list of subreddits that are being monitored are the same as the
    one that is live on-site.

    If it doesn't match, it'll remove ones it is not actually a
    moderator of.

    :return: Nothing.
    """
    # Fetch the *live* list of moderated subreddits directly from
    # Reddit, including private ones. This needs to use the native
    # account.
    mod_target = '/user/{}/moderated_subreddits'.format(USERNAME)
    active_subreddits = [x['sr'].lower() for x in reddit.get(mod_target)['data']]

    # Get only the subreddits that are recorded BUT not live.
    stored_dbs = database_monitored_subreddits_retrieve()
    problematic_subreddits = [x for x in stored_dbs if x not in active_subreddits]

    # If there are extra ones we're not a mod of, remove them.
    if len(problematic_subreddits) > 0:
        for community in problematic_subreddits:
            database_subreddit_delete(community)
            logger.info('Integrity Checker: No longer mod of r/{}. Removed.'.format(community))

    return


def database_delete_filtered_post(post_id):
    """This function deletes a post ID from the flair filtered
    database. Either because it's too old, or because it has
    been approved and restored. Trying to delete a non-existent ID
    just won't do anything.

    :param post_id: The Reddit submission's ID, as a string.
    :return: `None`.
    """
    CURSOR_DATA.execute('DELETE FROM posts_filtered WHERE post_id = ?', (post_id,))
    CONN_DATA.commit()
    logger.debug('Delete Filtered Post: Deleted post `{}` from filtered database.'.format(post_id))

    return


def database_last_subscriber_count(subreddit_name):
    """A function that returns the last and most recent local saved
    subscriber value for a given subreddit.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: The number of subscribers that subreddit has,
             or `None` if the subreddit is not listed.
    """
    stored_data = database_subscribers_retrieve(subreddit_name)
    num_subscribers = 0

    # If we already have stored subscriber data, get the last value.
    if stored_data is not None:
        # This is the last day we have subscriber data for.
        last_day = list(sorted(stored_data.keys()))[-1]
        num_subscribers = stored_data[last_day]

    return num_subscribers


def database_extended_retrieve(subreddit_name):
    """This function fetches the extended data stored in `monitored`
    and returns it as a dictionary.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A dictionary containing the extended data for a
             particular subreddit. None otherwise.
    """
    # Access the database.
    CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name.lower(),))
    result = CURSOR_DATA.fetchone()

    # The subreddit has extended data to convert into a dictionary.
    if result is not None:
        return ast.literal_eval(result[2])


def database_extended_insert(subreddit_name, new_data):
    """This function inserts data into the extended data stored in
    `monitored`. It will add data into the dictionary if the value
     does not exist, otherwise, it will modify it in place.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary containing the data we want to merge
                     or change in the extended data entry.
    :return: Nothing.
    """
    CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name.lower(),))
    result = CURSOR_DATA.fetchone()

    # The subreddit is in the monitored list with extended data.
    if result is not None:
        # Convert this extended data back into a dictionary.
        extended_data_existing = ast.literal_eval(result[2])
        working_dictionary = extended_data_existing.copy()
        working_dictionary.update(new_data)

        # Update the saved data with our new data.
        update_command = "UPDATE monitored SET extended = ? WHERE subreddit = ?"
        CURSOR_DATA.execute(update_command, (str(working_dictionary), subreddit_name.lower()))
        CONN_DATA.commit()
        logger.debug("Extended Insert: Merged new extended data with existing data.")
    return


def database_activity_retrieve(subreddit_name, month, activity_type):
    """This function checks the `subreddit_activity` table for cached
    data from Pushshift on the top activity and top usernames for days
    and usernames.

    :param subreddit_name: Name of a subreddit (no r/).
    :param month: The month year string, expressed as YYYY-MM.
    :param activity_type: The type of activity we want to get the
                          dictionary for.
    :return: A dictionary containing the data for a particular month
    """
    CURSOR_DATA.execute("SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
                        (subreddit_name, month))
    result = CURSOR_DATA.fetchone()

    if result is not None:
        # Convert this back into a dictionary.
        existing_data = ast.literal_eval(result[2])
        if activity_type in existing_data:
            return existing_data[activity_type]
        elif activity_type == "oldest":
            return existing_data

    return


def database_activity_insert(subreddit_name, month, activity_type, activity_data):
    """This function merges data passed to it with the equivalent
    entry in `subreddit_activity`.

    :param subreddit_name: Name of a subreddit (no r/).
    :param month: The month year string, expressed as YYYY-MM.
    :param activity_type: The type of subreddit activity data
                          (often used as a dictionary index).
    :param activity_data: The dictionary corresponding to the type
                          above that we want to store.
    :return:
    """
    CURSOR_DATA.execute("SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
                        (subreddit_name, month))
    result = CURSOR_DATA.fetchone()

    # Process the data. If there is no preexisting entry, Create a new
    # one, indexed with the activity type.
    if result is None:
        if activity_type != 'oldest':
            data_component = {activity_type: activity_data}
            data_package = (subreddit_name, month, str(data_component))
            CURSOR_DATA.execute('INSERT INTO subreddit_activity VALUES (?, ?, ?)', data_package)
            CONN_DATA.commit()
        else:  # 'oldest' posts get indexed by that phrase instead of by month.
            data_package = (subreddit_name, 'oldest', str(activity_data))
            CURSOR_DATA.execute('INSERT INTO subreddit_activity VALUES (?, ?, ?)', data_package)
            CONN_DATA.commit()
    else:
        # We already have data for this. Note that we don't need to
        # update this if data's already there.
        existing_data = ast.literal_eval(result[2])

        # Convert this back into a dictionary.
        # If we do not already have this activity type saved,
        # update the dictionary with it.
        if activity_type not in existing_data:
            existing_data[activity_type] = activity_data
            # Update the existing data.
            update_command = ("UPDATE subreddit_activity SET activity = ? "
                              "WHERE subreddit = ? AND date = ?")
            CURSOR_DATA.execute(update_command, (str(existing_data), subreddit_name, month))
            CONN_DATA.commit()

    return


def database_subscribers_insert(subreddit_name, new_data):
    """This function merges subscriber data in a dictionary passed to
    it with the already saved information, or creates a new entry by
    the subreddit's name.

    It's designed to be able to accept more than one date at a time
    and be able to save information in fewer writes to the database.
    This is integrated into `subreddit_subscribers_recorder()`.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary in this form: {'YYYY-MM-DD': XXXX}
                     where the key is a date string and the value
                     is an integer.
    :return:
    """
    # Check the database first.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # Process the data. If there is no preexisting subscribers entry,
    # create a new one.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_DATA.execute('INSERT INTO subreddit_subscribers_new VALUES (?, ?)', data_package)
        CONN_DATA.commit()
        logger.debug("Subscribers Insert: Added new subscriber data.")
    else:
        # We already have data for this subreddit, so we want to merge
        # the two together.
        existing_dictionary = ast.literal_eval(result[1])
        working_dictionary = existing_dictionary.copy()
        working_dictionary.update(new_data)

        # Update the saved data.
        update_command = "UPDATE subreddit_subscribers_new SET records = ? WHERE subreddit = ?"
        CURSOR_DATA.execute(update_command, (str(working_dictionary), subreddit_name))
        CONN_DATA.commit()
        logger.debug("Subscribers Insert: Merged subscriber data with existing data.")

    return


def database_subscribers_retrieve(subreddit_name):
    """This function returns the dictionary of subscriber data that is
    stored in the new database.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A dictionary containing subscriber data in this form:
             {'YYYY-MM-DD': XXXX} where the key is a date
             string and the value is an integer.
             If there is no data stored, it'll return `None`.
    """
    # Check the database first.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # We have data, let's turn the stored string into a dictionary.
    if result is not None:
        return ast.literal_eval(result[1])

    return


def database_statistics_posts_insert(subreddit_name, new_data):
    """This function inserts a given dictionary of statistics posts
    data into the corresponding subreddit's entry. This replaces an
    earlier system which used individual rows for each day's
    information.

    This function will NOT overwrite a day's data if it already exists.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary containing subscriber data in this
                     form: {'YYYY-MM-DD': {X}} where the key is a date
                     string and the value is another dictionary
                     indexed by post flair and containing
                     integer values.
    :return: Nothing.
    """
    # Check the database first.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM subreddit_stats_posts WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # We have no data.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_DATA.execute('INSERT INTO subreddit_stats_posts VALUES (?, ?)', data_package)
        CONN_DATA.commit()
        logger.debug("Statistics Posts Insert: Added new posts data.")
    else:
        # There is already an entry for this subreddit in our database.
        existing_dictionary = ast.literal_eval(result[1])
        working_dictionary = existing_dictionary.copy()

        # Update the working dictionary with the new data.
        # Making sure we do not overwrite the existing data.
        for key, value in new_data.items():
            if key not in working_dictionary:
                working_dictionary[key] = value

        # Update the dictionary.
        update_command = "UPDATE subreddit_stats_posts SET records = ? WHERE subreddit = ?"
        CURSOR_DATA.execute(update_command, (str(working_dictionary), subreddit_name))
        CONN_DATA.commit()
        logger.debug("Statistics Posts Insert: Merged posts data with existing data.")

    return


def database_statistics_posts_retrieve(subreddit_name):
    """This function returns the dictionary of statistics data for a
    subreddit that is stored in the new database.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A dictionary containing statistics data in this form:
             {'YYYY-MM-DD': {X}} where the key is a date string and
             the value is another dictionary indexed by post flair
             and containing integer values.

             If there is no data stored, it'll return `None`.
    """
    # Check the database first.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM subreddit_stats_posts WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # We have data, let's turn the stored string into a dictionary.
    if result is not None:
        return ast.literal_eval(result[1])

    return


def database_cleanup():
    """This function cleans up the `posts_processed` table and keeps
    only a certain amount left in order to prevent it from becoming
    too large. This keeps the newest `ENTRIES_TO_KEEP` post IDs
    and deletes the oldest ones.

    This function also truncates the events log to keep it at
    a manageable length.

    :return: `None`.
    """
    # How many lines of log entries we wish to preserve in the logs.
    lines_to_keep = int(ENTRIES_TO_KEEP / 2)
    updated_to_keep = int(ENTRIES_TO_KEEP / 5)

    # Access the `processed` database, order the posts by oldest first,
    # and then only keep the above number of entries.
    delete_command = ("DELETE FROM posts_processed WHERE post_id NOT IN "
                      "(SELECT post_id FROM posts_processed ORDER BY post_id DESC LIMIT ?)")
    CURSOR_DATA.execute(delete_command, (ENTRIES_TO_KEEP,))
    CONN_DATA.commit()
    logger.info('Cleanup: Last {:,} processed database entries kept.'.format(ENTRIES_TO_KEEP))

    # Access the `updated` database, order the entries by their date,
    # and then only keep the above number of entries.
    delete_command = ("DELETE FROM subreddit_updated WHERE date NOT IN "
                      "(SELECT date FROM subreddit_updated ORDER BY date DESC LIMIT ?)")
    CURSOR_DATA.execute(delete_command, (updated_to_keep,))
    CONN_DATA.commit()
    logger.info('Cleanup: Last {:,} updated database entries kept.'.format(updated_to_keep))

    # Clean up the logs. Keep only the last `lines_to_keep` lines.
    with open(FILE_ADDRESS_LOGS, "r", encoding='utf-8') as f:
        lines_entries = [line.rstrip("\n") for line in f]

    # If there are more lines than what we want to keep, truncate the
    # entire file to our limit.
    if len(lines_entries) > lines_to_keep:
        lines_entries = lines_entries[(-1 * lines_to_keep):]
        with open(FILE_ADDRESS_LOGS, "w", encoding='utf-8') as f:
            f.write("\n".join(lines_entries))
    logger.info('Cleanup: Last {:,} log entries kept.'.format(lines_to_keep))

    return


"""SUBREDDIT TEMPLATES RETRIEVAL"""


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
        formatted_order[template_order] = messaging_flair_sanitizer(template, False)

    # Reorder and format each line.
    lines = ["* {}".format(formatted_order[key]) for key in sorted(formatted_order.keys())]

    return "\n".join(lines)


"""SUBREDDIT TRAFFIC RETRIEVAL"""


def subreddit_traffic_daily_estimator(subreddit_name):
    """Looks at the DAILY traffic up to now in the current month and
     estimates the total traffic for this month.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A dictionary indexed with various values, including
             averages and estimated totals. `None` if inaccessible.
    """
    daily_traffic_dictionary = {}
    output_dictionary = {}
    total_uniques = []
    total_pageviews = []

    # Get the current month as a YYYY-MM string.
    current_month = date_month_convert_to_string(time.time())

    # Retrieve traffic data as a dictionary.
    # The speed of this function is determined by how fast `traffic()`
    # gets data from the site itself. If the bot does not have the
    # ability to access this data, return `None`.
    try:
        traffic_data = reddit.subreddit(subreddit_name).traffic()
    except prawcore.exceptions.NotFound:
        logger.info('Traffic Estimator: I do not have access to the traffic data.')
        return None
    daily_data = traffic_data['day']

    # Iterate over the data. If there's data for a day, we'll save it.
    for date in daily_data:
        date_string = date_convert_to_string(date[0])
        date_uniques = date[1]
        if date_uniques != 0 and current_month in date_string:
            date_pageviews = date[2]
            daily_traffic_dictionary[date_string] = [date_uniques, date_pageviews]

    # Evaluate our data.
    num_of_recorded_days = len(daily_traffic_dictionary.keys())
    if num_of_recorded_days == 0:
        return None  # Exit if we have no valid data.
    for date, value in daily_traffic_dictionary.items():
        total_uniques.append(value[0])
        total_pageviews.append(value[1])

    # Calculate the daily average of uniques and page views.
    days_uniques_recorded = len(total_uniques)
    average_uniques = int(sum(total_uniques) / days_uniques_recorded)
    average_pageviews = int(sum(total_pageviews) / len(total_pageviews))

    # Get the number of days in the month and calculate the estimated
    # amount for the month.
    year = datetime.datetime.now().year
    days_in_month = calendar.monthrange(year, datetime.datetime.now().month)[1]
    output_dictionary['average_uniques'] = average_uniques
    output_dictionary['average_pageviews'] = average_pageviews
    output_dictionary['estimated_pageviews'] = average_pageviews * days_in_month

    # We now have to calculate the estimated uniques based on the
    # current total recorded, if we already have data for this month
    # that we can estimate off of. Otherwise just give a rough estimate.
    current_sum_uniques = traffic_data['month'][0][1]
    if current_sum_uniques != 0:
        avg_daily_unique = (current_sum_uniques / days_uniques_recorded)
        output_dictionary['estimated_uniques'] = int(avg_daily_unique * days_in_month)
    else:
        output_dictionary['estimated_uniques'] = average_uniques * days_in_month

    return output_dictionary


def subreddit_traffic_recorder(subreddit_name):
    """Retrieve the recorded monthly traffic statistics for a subreddit
    and store them in our database. This function will also merge or
    retrieve it from the local cache if that data is already stored.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A dictionary indexed by YYYY-MM with the traffic data for
             that month.
    """
    subreddit_name = subreddit_name.lower()
    traffic_dictionary = {}
    current_month = date_month_convert_to_string(time.time())

    # Retrieve traffic data as a dictionary.
    try:
        sub_object = reddit.subreddit(subreddit_name)
        traffic_data = sub_object.traffic()
    except prawcore.exceptions.NotFound:
        # We likely do not have the ability to access this.
        logger.info('Traffic Recorder: I do not have access to traffic data for this subreddit.')
        return

    # Save the specific information.
    monthly_data = traffic_data['month']

    # Iterate over the months.
    for month in monthly_data:
        # Convert the listed data into actual variables.
        # Account for UTC with the time.
        unix_month_time = month[0] + 86400
        month_uniques = month[1]
        month_pageviews = month[2]
        year_month = date_month_convert_to_string(unix_month_time)

        # We don't want to save the data for the current month, since
        # it's incomplete.
        # We also don't save the data if there is NOTHING for the month.
        if current_month != year_month and month_uniques > 0 and month_pageviews > 0:
            traffic_dictionary[year_month] = [month_uniques, month_pageviews]

    # Take the formatted dictionary and save it to our database.
    sql_command = "SELECT * FROM subreddit_traffic WHERE subreddit = ?"
    CURSOR_DATA.execute(sql_command, (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    # If the data has not been saved before, add it as a new entry.
    # Otherwise, if saved traffic data already exists merge the data.
    if result is None:
        data_package = (subreddit_name, str(traffic_dictionary))
        CURSOR_DATA.execute("INSERT INTO subreddit_traffic VALUES (?, ?)", data_package)
        CONN_DATA.commit()
        logger.debug('Traffic Recorder: Traffic data for r/{} added.'.format(subreddit_name))
    else:
        existing_dictionary = ast.literal_eval(result[1])
        new_dictionary = existing_dictionary.copy()
        new_dictionary.update(traffic_dictionary)

        update_command = "UPDATE subreddit_traffic SET traffic = ? WHERE subreddit = ?"
        CURSOR_DATA.execute(update_command, (str(new_dictionary), subreddit_name))
        CONN_DATA.commit()
        logger.debug("Traffic Recorder: r/{} data merged.".format(subreddit_name))

    return traffic_dictionary


def subreddit_traffic_retriever(subreddit_name):
    """Function that looks at the monthly traffic data for a subreddit
    and returns it as a Markdown table.

    If available it will also incorporate the estimated monthly targets
    for the current month. This function also calculates the
    month-to-month change and the averages for the entire period.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A Markdown table with all the months we have data for.
    """
    formatted_lines = []
    all_uniques = []
    all_pageviews = []
    all_uniques_changes = []
    all_pageviews_changes = []
    top_month_uniques = None
    top_month_pageviews = None
    basic_line = "| {} | {} | {:,} | *{}%* | {} | {:,} | *{}%* | {} |"

    # Look for the traffic data in our database.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute("SELECT * FROM subreddit_traffic WHERE subreddit = ?", (subreddit_name,))
    results = CURSOR_DATA.fetchone()

    # If we have data, convert it back into a dictionary.
    # Otherwise, return `None.
    if results is not None:
        traffic_dictionary = ast.literal_eval(results[1])
    else:
        return None

    # Iterate over our dictionary.
    for key in sorted(traffic_dictionary, reverse=True):

        # We get the previous month's data so we can track changes.
        month_t = datetime.datetime.strptime(key, '%Y-%m').date()
        previous_month = (month_t + datetime.timedelta(-15)).strftime('%Y-%m')
        current_uniques = traffic_dictionary[key][0]
        current_pageviews = traffic_dictionary[key][1]

        # We SKIP this month for averaging if there's nothing there.
        # Both uniques and pageviews are ZERO.
        if current_uniques == 0 and current_pageviews == 0:
            continue

        all_uniques.append(current_uniques)
        all_pageviews.append(current_pageviews)

        # Get the ratio of uniques to pageviews. We round the ratio to
        # the nearest integer.
        if current_uniques != 0:
            ratio_uniques_pageviews = "≈1:{:.0f}".format(current_pageviews / current_uniques)
        else:
            ratio_uniques_pageviews = '---'

        # Try to get comparative data from the previous month.
        try:
            previous_uniques = traffic_dictionary[previous_month][0]
            previous_pageviews = traffic_dictionary[previous_month][1]

            # Determine the changes in uniques/page views relative to
            # the previous month.
            raw_uniques = (current_uniques - previous_uniques)
            uniques_change = round((raw_uniques / previous_uniques) * 100, 2)
            raw_pageviews = (current_pageviews - previous_pageviews)
            pageviews_change = round((raw_pageviews / previous_pageviews) * 100, 2)
            all_uniques_changes.append(uniques_change)
            all_pageviews_changes.append(pageviews_change)
        except (KeyError, ZeroDivisionError):
            # If we do not have valid data from the previous month,
            # put placeholder blank lines instead.
            uniques_change = "---"
            pageviews_change = "---"

        # Format our necessary symbols to easily indicate the
        # month-over-month change in the table.
        if uniques_change != "---":
            if uniques_change > 0:
                uniques_symbol = "➕"
            elif uniques_change < 0:
                uniques_symbol = "🔻"
            else:
                uniques_symbol = "🔹"
        else:
            uniques_symbol = ""
        if pageviews_change != '---':
            if pageviews_change > 0:
                pageviews_symbol = "➕"
            elif pageviews_change < 0:
                pageviews_symbol = "🔻"
            else:
                pageviews_symbol = "🔹"
        else:
            pageviews_symbol = ""

        # Format the table line and add it to the list.
        line = basic_line.format(key, uniques_symbol, current_uniques, uniques_change,
                                 pageviews_symbol, current_pageviews, pageviews_change,
                                 ratio_uniques_pageviews)
        formatted_lines.append(line)

    # Here we look for the top months we have in the recorded data.
    if len(all_uniques) != 0 and len(all_pageviews) != 0:
        top_uniques = max(all_uniques)
        top_pageviews = max(all_pageviews)
        for key, data in traffic_dictionary.items():
            if top_uniques in data:
                top_month_uniques = key
            if top_pageviews in data:
                top_month_pageviews = key
    else:
        top_uniques = top_pageviews = None

    # Get the estimated CURRENT monthly average for this month.
    # This is generated from the current daily data.
    daily_data = subreddit_traffic_daily_estimator(subreddit_name)
    if daily_data is not None:
        # We have daily estimated data that we can parse.
        # Get month data and the current month as a YYYY-MM string.
        current_month = date_month_convert_to_string(time.time())
        current_month_dt = datetime.datetime.strptime(current_month, '%Y-%m').date()
        previous_month = (current_month_dt + datetime.timedelta(-15)).strftime('%Y-%m')

        # Estimate the change.
        estimated_uniques = daily_data['estimated_uniques']
        estimated_pageviews = daily_data['estimated_pageviews']

        # Get the previous month's data for comparison.
        # This will fail if the keys are not included in the dictionary
        # or if a variable for division is set to zero.
        try:
            previous_uniques = traffic_dictionary[previous_month][0]
            previous_pageviews = traffic_dictionary[previous_month][1]
            uniques_diff = (estimated_uniques - previous_uniques)
            pageviews_diff = (estimated_pageviews - previous_pageviews)
            est_uniques_change = round((uniques_diff / previous_uniques) * 100, 2)
            est_pageviews_change = round((pageviews_diff / previous_pageviews) * 100, 2)
            ratio_raw = round(estimated_pageviews / estimated_uniques, 0)
            ratio_est_uniques_pageviews = "≈1:{}".format(int(ratio_raw))
        except (KeyError, ZeroDivisionError):
            est_uniques_change = est_pageviews_change = ratio_est_uniques_pageviews = "---"

        estimated_line = basic_line.format("*{} (estimated)*".format(current_month), "",
                                           estimated_uniques, est_uniques_change, "",
                                           estimated_pageviews, est_pageviews_change,
                                           ratio_est_uniques_pageviews)

        # Insert at the start of the formatted lines list, position 0.
        formatted_lines.insert(0, estimated_line)

    # Get the averages of both the total amounts and the percentages.
    # If there's no data, set the averages to zero.
    try:
        num_avg_uniques = round(sum(all_uniques) / len(all_uniques), 2)
        num_avg_pageviews = round(sum(all_pageviews) / len(all_uniques), 2)
    except ZeroDivisionError:
        num_avg_uniques = num_avg_pageviews = 0

    # Make sure we have month over month data, because if we don't have
    # more than one month's worth of data, we can't calculate the
    # average per month increase.
    if len(all_uniques_changes) > 0 and len(all_pageviews_changes) > 0:
        num_avg_uniques_change = round(sum(all_uniques_changes) / len(all_uniques_changes), 2)
        num_pageviews_changes = round(sum(all_pageviews_changes) / len(all_pageviews_changes), 2)
    else:
        num_avg_uniques_change = num_pageviews_changes = 0

    # Form the Markdown for the "Average" section.
    average_section = ("* *Average Monthly Uniques*: {:,}\n* *Average Monthly Pageviews*: {:,}\n"
                       "* *Average Monthly Uniques Change*: {:+}%"
                       "\n* *Average Monthly Pageviews Change*: {:+}%\n")
    average_section = average_section.format(num_avg_uniques, num_avg_pageviews,
                                             num_avg_uniques_change, num_pageviews_changes)

    # Get the difference of the top months from the average and
    # form the Markdown for the "Top" section that follows.
    # Get the percentage increase for uniques and pageviews.
    if top_uniques is not None and top_pageviews is not None:
        if num_avg_uniques != 0 and num_avg_pageviews != 0:
            i_uniques = (top_uniques - num_avg_uniques) / num_avg_uniques
            i_pageviews = (top_pageviews - num_avg_pageviews) / num_avg_pageviews
            top_increase_uniques = ", {:+.2%} more than the average month".format(i_uniques)
            top_increase_pageviews = ", {:+.2%} more than the average month".format(i_pageviews)
        else:
            top_increase_uniques = top_increase_pageviews = ""
        top_section = ("* *Top Month for Uniques*: {} ({:,} uniques{})\n"
                       "* *Top Month for Pageviews*: {} ({:,} pageviews{})\n\n")
        top_section = top_section.format(top_month_uniques, top_uniques, top_increase_uniques,
                                         top_month_pageviews, top_pageviews,
                                         top_increase_pageviews)
    else:
        # Leave it blank if there's not enough data to derive a
        # top section.
        top_section = ""

    # Form the overall Markdown table with the header and body text.
    header = ("\n| Month | 📈 | Uniques | Uniques % Change | 📉 | "
              "Pageviews | Pageviews % Change | Uniques : Pageviews |"
              "\n|-------|----|---------|------------------|----|------|"
              "--------------------|---------------------|\n")
    body = average_section + top_section + header + '\n'.join(formatted_lines)

    return body


"""SUBREDDIT STATISTICS RETRIEVAL"""


def subreddit_pushshift_access(query_string, retries=3):
    """This function is called by others as the main point of query to
    Pushshift. It contains code to account for JSON decoding errors and
    to retry if it encounters such problems. It also converts JSON data
    into a Python dictionary.

    :param query_string: The exact API call we want to make.
    :param retries: The number of times (as an integer) that we want to
                    try connecting to the API. Default is 3.
    :return: An empty dictionary if there was a connection error,
             otherwise, a dictionary.
    """
    for _ in range(retries):
        try:
            returned_data = requests.get(query_string)
            returned_data = returned_data.json()
            return returned_data  # Return data as soon as it is found.
        except (ValueError, ConnectionError, HTTPError):
            continue

    return {}


def subreddit_subscribers_recorder(subreddit_name, check_pushshift=False):
    """A quick routine that gets the number of subscribers for a
    specific subreddit and saves it to our database.
    This is intended to be run daily at midnight UTC.

    :param subreddit_name: The name of a Reddit subreddit.
    :param check_pushshift: Whether we want to get the live count of
                            the subscribers from Reddit (normal mode)
                            or we want to try and get the more accurate
                            one from Pushshift. This is because Artemis
                            may have been added at the end of a UTC day
                            and its current subscriber count would not
                            be as accurate as an earlier one.
    :return: Nothing.
    """
    # Get the date by converting the time to YYYY-MM-DD in UTC.
    current_time = time.time()
    current_day = date_convert_to_string(current_time)

    # `check_pushshift`: We want to get a more accurate count from the
    # start of the day. Set `current_subs` to `None` if there is no
    # information retrieved. If we can get data, it'll be in a dict
    # format: {'2018-11-11': 9999}
    if check_pushshift:
        ps_subscribers = subreddit_subscribers_pushshift_historical_recorder(subreddit_name,
                                                                             fetch_today=True)
        if len(ps_subscribers.keys()) == 0:
            current_subs = None
        else:
            current_subs = ps_subscribers[current_day]
    else:
        current_subs = None

    # Get the current state of subscribers. If an exception is thrown
    # the subreddit is likely quarantined or banned.
    if current_subs is None:
        try:
            current_subs = reddit.subreddit(subreddit_name).subscribers
        except prawcore.exceptions.Forbidden:
            current_subs = 0

    # Insert the subscribers information into our database.
    data_package = {current_day: current_subs}
    logger.debug("Subscribers Recorder: {}, r/{}: {:,} subscribers.".format(current_day,
                                                                            subreddit_name,
                                                                            current_subs))
    database_subscribers_insert(subreddit_name, data_package)

    return


def subreddit_subscribers_retriever(subreddit_name):
    """Function that looks at the stored subscriber data and returns it
    as a Markdown table.
    It keeps the daily information from the last 6 months and past that
    only returns monthly information.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A Markdown-formatted table with the daily change in
             subscribers and total number.
    """
    formatted_lines = []
    day_changes = []

    # Check to see if this has been stored before.
    # If there is, get the dictionary. Exit if there is no data.
    subscriber_dictionary = database_subscribers_retrieve(subreddit_name)
    if subscriber_dictionary is None:
        return None

    # Get the founding date of the subreddit, by checking the local
    # database, or the object itself if not monitored.
    try:
        created = database_extended_retrieve(subreddit_name)['created_utc']
        founding_date = date_convert_to_string(created)
    except TypeError:
        founding_date = date_convert_to_string(reddit.subreddit(subreddit_name).created_utc)

    # Iterate over the data. Format the lines together and get their net
    # change as well. We sort in this case, by newest first.
    list_of_dates = list(sorted(subscriber_dictionary.keys()))
    list_of_dates.reverse()
    for date in list_of_dates:
        day_index = list_of_dates.index(date)
        logger.debug("Subscribers Retriever for r/{}: {}, index {}".format(subreddit_name, date,
                                                                           day_index))

        # Get some date variables and the template for each line.
        day_t = datetime.datetime.strptime(date, '%Y-%m-%d').date()
        previous_day = day_t + datetime.timedelta(-1)
        previous_day = str(previous_day.strftime('%Y-%m-%d'))
        line = "| {} | {:,} | {:+,} |"
        subscriber_count = subscriber_dictionary[date]

        # This is a regular day in the last 180 entries. If we are past
        # 180 days (about half a year) then we get only the starts of
        # the months for a shorter table.
        if previous_day in subscriber_dictionary and day_index <= 180:
            subscriber_previous = subscriber_dictionary[previous_day]
            net_change = subscriber_count - subscriber_previous
        elif day_index > 180 and "-01" in date[-3:]:
            # Try to get the previous month's entry, which is not
            # immediately previous to this one.
            try:
                later_line = formatted_lines[-1]
                later_date = later_line.split('|')[1].strip()
                subscriber_later = int(later_line.split('|')[2].strip().replace(',', ''))
            except IndexError:
                later_date = founding_date
                subscriber_later = 1

            # Get the average change of subscribers per day.
            days_difference = date_num_days_between(later_date, date)
            if days_difference != 0:
                subscriber_delta = subscriber_later - subscriber_count
                net_change = round(subscriber_delta / days_difference, 2)
            else:
                net_change = 0
        else:
            continue

        # If there was a change, append the change to our list.
        if net_change != 0:
            day_changes.append(net_change)

        new_line = line.format(date, subscriber_count, net_change)
        if day_index <= 180 or day_index > 180 and "-01" in date[-3:]:
            formatted_lines.append(new_line)

    # Get the average change of subscribers per day.
    if len(day_changes) >= 2:

        average_change = sum(day_changes) / len(day_changes)
        average_change_text = "*Average Daily Change (overall)*: {:+,.2f} subscribers\n\n"
        average_change_section = average_change_text.format(average_change)

        # If the subreddit is actually growing, get the average growth.
        milestone_estimated = subreddit_subscribers_estimator(subreddit_name)
        if milestone_estimated is not None:
            average_change_section += "{}\n\n".format(milestone_estimated)
    else:
        average_change_section = ""

    # Get the milestone chart, if possible. This charts which days the
    # subreddit reached a certain number of subscribers.
    milestone_section = subreddit_subscribers_milestone_chart_former(subreddit_name)
    if milestone_section is None:
        milestone_section = ''

    # Format the actual body of the table.
    subscribers_header = ("\n\n### Log\n\n"
                          "| Date | Subscribers | Average Daily Change |\n"
                          "|------|-------------|----------------------|\n")

    # The last line is appended, which is the start date of the sub,
    # and form the text together.
    founding_line = "\n| {} | Created | --- |".format(founding_date)
    body = average_change_section + milestone_section
    body += subscribers_header + '\n'.join(formatted_lines) + founding_line

    return body


def subreddit_subscribers_estimator(subreddit_name):
    """This function tries to estimate how long it'll be until the
    subreddit reaches the next subscriber milestone. This is based off
    the value `sample_size`, which is the most recent number of entries
    that are evaluated.

    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """
    next_milestone = None
    sample_size = 14
    last_few_entries = []

    # Access the database.
    results = database_subscribers_retrieve(subreddit_name)

    # Exit if there is no data.
    if results is None:
        return None

    # Look through our results, specifically the last X ones of
    # `sample_size`. In this case it means we look through the last two
    # weeks to get the average. We order the data from newest first to
    # oldest last.
    last_few_days = list(sorted(results.keys()))[-sample_size:]
    last_few_days.reverse()
    for day in last_few_days:
        last_few_entries.append(results[day])

    # Get the current number of subscribers, and calculate the average
    # daily change in recent days.
    current_number = results[last_few_days[0]]
    average_changes = [s - t for s, t in zip(last_few_entries, last_few_entries[1:])]
    average_daily_change = sum(average_changes) / len(average_changes)

    # Iterate over the milestones. Calculate the next milestone this
    # subreddit will reach.
    for milestone in SUBSCRIBER_MILESTONES:
        if milestone > current_number:
            next_milestone = milestone
            break

    # Format the daily change text.
    if average_daily_change != 0:
        average_daily_format = ("*Average Daily Change (last {} entries)*: "
                                "{:+,.2f} subscribers\n\n".format(sample_size,
                                                                  average_daily_change))
    else:
        average_daily_format = None

    # We now know what the next milestone is. Calculate the number of
    # days until then.
    if next_milestone is not None:

        # Check how many days we estimate until the next milestone.
        difference_between = next_milestone - current_number
        if average_daily_change != 0:
            days_until_milestone = int(difference_between / float(average_daily_change))
        else:
            days_until_milestone = 10000  # Assign it a really long number
        unix_next_milestone = time.time() + (days_until_milestone * 86400)

        # If the days are too far from now, (over two years) or if the
        # subreddit is shrinking don't return milestones.
        if days_until_milestone > 730 or days_until_milestone < 0:
            milestone_format = None
        else:
            # Format the next milestone as a string. If the next
            # milestone is within four months, just include it as days.
            # Otherwise, format the next time string in months instead.
            unix_next_milestone_string = date_convert_to_string(unix_next_milestone)
            if days_until_milestone <= 120:
                if days_until_milestone == 0:
                    time_until_string = "(today!)"
                else:
                    time_until_string = "({} days from now)".format(days_until_milestone)
            else:
                # Otherwise, format it as months. 30.44 is the average
                # number of days in a month.
                time_until_string = "({:.2f} months from now)".format(days_until_milestone / 30.44)
            milestone_format = "*Next Subscriber Milestone (estimated)*: {:,} subscribers on {} {}"
            milestone_format = milestone_format.format(next_milestone, unix_next_milestone_string,
                                                       time_until_string)
    else:
        milestone_format = None

    # Then we put together the two lines, if possible.
    if average_daily_format is not None:
        if milestone_format is not None:
            returned_body = average_daily_format + milestone_format
        else:
            returned_body = average_daily_format
        return returned_body
    else:
        return None


def subreddit_subscribers_milestone_chart_former(subreddit_name):
    """This function is backwards-looking; that is, it looks back and
    determines when a subreddit passed certain subscriber milestones.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A Markdown table.
    """
    # Create a dictionary with milestones to derive the chart from.
    dictionary_milestones = {}
    formatted_lines = []

    # Check to see if we have stored data. We order this by date,
    # oldest item first, newest item last.
    dictionary_total = database_subscribers_retrieve(subreddit_name)

    # Exit if there is no data.
    if dictionary_total is None:
        return None

    # Get the last number of recorded subscribers.
    current_subscribers = dictionary_total[list(sorted(dictionary_total.keys()))[-1]]
    milestones_to_check = [x for x in SUBSCRIBER_MILESTONES if x <= current_subscribers]

    # We iterate over the data we have, starting with the OLDEST date
    # we have data for.
    for date in list(sorted(dictionary_total.keys())):
        date_subscribers = dictionary_total[date]

        # Iterate over the subscriber milestones that we have defined.
        for milestone in milestones_to_check:
            if date_subscribers > milestone:
                continue
            else:
                # We get the next day for the milestone.
                d_type = '%Y-%m-%d'
                time_delta = datetime.timedelta(days=1)
                next_day = (datetime.datetime.strptime(date, d_type) + time_delta).strftime(d_type)

                # We add the next date here.
                dictionary_milestones[milestone] = next_day

    # Iterate over the dictionary of milestones to make sure to remove
    # any milestone that might not yet be attained. Delete the key if
    # it's somehow larger than our current subscriber count.
    for key in [key for key in dictionary_milestones if key > current_subscribers]:
        del dictionary_milestones[key]

    # Form the Markdown table from our dictionary of data. We also add
    # a first entry for the founding of the sub.
    header = ("### Milestones\n\n\n"
              "| Date Reached | Subscriber Milestone | Average Daily Change "
              "| Days From Previous Milestone |\n"
              "|--------------|----------------------|----------------------|"
              "------------------------------|\n")
    founding_date = date_convert_to_string(reddit.subreddit(subreddit_name).created_utc)
    founding_line = "\n| {} | Created | --- |\n\n".format(founding_date)

    for milestone, date in list(sorted(dictionary_milestones.items())):

        # If we have previous items in this list, we want to calculate
        # the daily growth between this milestone and the previous one.
        if len(formatted_lines) != 0:
            previous_date = formatted_lines[-1].split('|')[1].strip()
            previous_milestone = int(formatted_lines[-1].split('|')[2].strip().replace(',', ''))
        else:
            # If there is no previous entry, we start from the founding
            # of the subreddit.
            previous_date = founding_date
            previous_milestone = 1

        # Calculate the number of days between the two milestones and
        # the changes in between. Start by obtaining the subscriber
        # change between the last milestone.
        milestone_delta = milestone - previous_milestone
        days_difference = date_num_days_between(previous_date, date)

        # Calculate the average daily change. If the difference in days
        # is zero, set the delta value to a generic string.
        if days_difference != 0:
            daily_delta = "{:+,.2f}".format(milestone_delta / days_difference)
        else:
            daily_delta = '---'

        # Create a new line for the table and add it to our list.
        new_line = "| {} | {:,} | {} | {} |".format(date, milestone, daily_delta, days_difference)
        formatted_lines.append(new_line)

    # Join everything together. We also need to delete the last
    # milestone, which is not real since it's in the future.
    # Also sort it by newest first, and replace any double linebreaks
    # so that the table is intact.
    formatted_lines.reverse()
    body = "{}{}".format(header, "\n".join(formatted_lines)) + founding_line
    body = body.replace('\n\n', '\n')

    return body


def subreddit_subscribers_pushshift_historical_recorder(subreddit_name, fetch_today=False):
    """Pushshift's API stores subscriber data for subreddits from about
    2018-03-15. This function will go back until then and get the
    subscribers for each day if it can.

    :param subreddit_name: Name of a subreddit.
    :param fetch_today: Whether we should get just today's stats, or a
                        list of stats from March 15, 2018.
    :return:
    """
    subscribers_dictionary = {}
    logger.info('Subscribers PS: Retrieving subscribers for r/{}...'.format(subreddit_name))

    # If we just want to get today's stats just create a list with today
    # as the only component. Otherwise, fetch a list of days since March
    # 15, which is when subscriber information became available on
    # Pushshift's database.
    if not fetch_today:
        yesterday = int(time.time()) - 86400
        yesterday_string = date_convert_to_string(yesterday)
        list_of_days_to_get = date_get_series_of_days("2018-03-15", yesterday_string)
    else:
        today_string = date_convert_to_string(time.time())
        list_of_days_to_get = [today_string]

    api_search_query = ("https://api.pushshift.io/reddit/search/submission/?subreddit={}"
                        "&after={}&before={}&sort_type=created_utc&size=1")

    # Get the data from Pushshift as JSON. We try to get a submission
    # per day and record the subscribers.
    for day in list_of_days_to_get:  # Iterate over each day.
        start_time = date_convert_to_unix(day)
        end_time = start_time + 86399

        # Access the Pushshift API for this day. If we weren't able to
        # get any data for this day, skip the day.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(subreddit_name,
                                                                            start_time, end_time))
        if 'data' not in retrieved_data:
            continue
        else:
            returned_submission = retrieved_data['data']

        # Make sure we actually have data for this day. If we do, then
        # add the data to our dictionary.
        if len(returned_submission) > 0:
            if 'subreddit_subscribers' in returned_submission[0]:
                subscribers = returned_submission[0]['subreddit_subscribers']
                subscribers_dictionary[day] = int(subscribers)
                logger.debug("Subscribers PS: Data for {}: {} subscribers.".format(day,
                                                                                   subscribers))

    # If we have data we can save it and insert it into the database.
    if len(subscribers_dictionary.keys()) != 0:
        database_subscribers_insert(subreddit_name, subscribers_dictionary)
        logger.info('Subscribers PS: Recorded subscribers for r/{}.'.format(subreddit_name))

    return subscribers_dictionary


def subreddit_subscribers_redditmetrics_historical_recorder(subreddit_name, fetch_mode=False):
    """Retrieve data from the equivalent RedditMetrics page. This goes
    back to November 2012 until March 15, 2018. After March 15 we can
    rely on Pushshift data, which is more consistent, since RM can give
    false data for recent dates after then and *must* not be relied
    upon for that.

    :param subreddit_name: Name of a subreddit.
    :param fetch_mode: When activated this will return the traffic data
                       as a dictionary instead of saving it.
    :return: `None`.
    """
    final_dictionary = {}

    # Access the site and retrieve its serialized data. If we encounter
    # an error loading the site page, return.
    try:
        response = urllib.request.urlopen("http://redditmetrics.com/r/{}/".format(subreddit_name))
    except (HTTPError, URLError):
        return

    # Check if the subreddit exists on the website. If the sub doesn't
    # exist on RedditMetrics, it possibly post-dates the site, and so
    # the function should exit.
    logger.info('Subscribers RM: Retrieving historical r/{} data...'.format(subreddit_name))
    html_source = response.read()
    new_part = str(html_source).split("data:")
    try:
        total_chunk = new_part[2][1:]
        total_chunk = total_chunk.split('pointSize', 1)[0].replace('],', ']').strip()
        total_chunk = total_chunk.replace('\\n', ' ')
        total_chunk = total_chunk.replace("\\'", "'")[5:-5].strip()
    except IndexError:
        return

    # Now convert the raw data from the website into a list.
    list_of_days = total_chunk.split('},')
    list_of_days = [x.strip() for x in list_of_days]
    list_of_days = [x.replace('{', '') for x in list_of_days]
    list_of_days = [x.replace('}', '') for x in list_of_days]

    # Iterate over this list and form a proper dictionary out of it.
    # This dictionary is indexed by day with subscriber counts as
    # values.
    for entry in list_of_days:
        date_string = re.findall(r"'(\S+)'", entry)[0]

        # We have code here to reject any date that's after 2018-03-15,
        # since RM gives false data after then.
        # That date is defined as 1521072001 in Unix time.
        date_string_num = date_convert_to_unix(date_string)
        if date_string_num > 1521072001:
            continue

        subscribers = entry.split('a: ', 1)[1]
        subscribers = int(subscribers)
        if subscribers != 0:
            final_dictionary[date_string] = subscribers

    # If we're in fetch mode, just return the dictionary and do NOT save
    # it to the database.
    if fetch_mode:
        return final_dictionary

    # Insert the data into the new database.
    database_subscribers_insert(subreddit_name, final_dictionary)

    return


def subreddit_pushshift_oldest_retriever(subreddit_name):
    """This function uses Pushshift to retrieve the oldest posts on a
    subreddit and formats it as a Markdown list.

    :param subreddit_name: The community we are looking for.
    :return: A Markdown text paragraph containing the oldest posts as
             links in a bulleted list.
    """
    formatted_lines = []
    header = "\n\n### Oldest Submissions\n\n"
    line_template = '* "[{}]({})", posted by u/{} on {}'

    # Check our database to see if we have the data stored.
    result = database_activity_retrieve(subreddit_name, 'oldest', 'oldest')

    # If we have stored data, use it. Otherwise, let's access Pushshift
    # and get it.
    if result is not None:
        oldest_data = result
    else:
        oldest_data = {}
        api_search_query = ("https://api.pushshift.io/reddit/search/submission/"
                            "?subreddit={}&sort=asc&size={}")

        # Get the data from Pushshift as JSON.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(subreddit_name,
                                                                            NUMBER_TO_RETURN))

        # If there was a problem with interpreting JSON data, return an
        # error message.
        if 'data' not in retrieved_data:
            error_section = ("* There was an temporary issue retrieving the oldest posts for this "
                             "subreddit. Artemis will attempt to re-access the data at the next "
                             "statistics update.")
            error_message = header + error_section
            return error_message
        else:
            returned_submissions = retrieved_data['data']

        # Iterate over the submissions  and get their attributes.
        for submission in returned_submissions:
            post_created = int(submission['created_utc'])
            post_title = submission['title'].strip()
            post_id = submission['id']
            post_link = submission['permalink']
            post_author = submission['author']
            oldest_data[post_created] = {'title': post_title, 'permalink': post_link,
                                         'id': post_id, 'author': post_author}

    # Format the dictionary's data into Markdown.
    for date in sorted(oldest_data):
        date_data = oldest_data[date]
        line = line_template.format(date_data['title'], date_data['permalink'],
                                    date_data['author'], date_convert_to_string(date))
        formatted_lines.append(line)

    oldest_section = header + '\n'.join(formatted_lines)

    # Save it to the database if there isn't a previous record of it and
    # if we have data.
    if result is None and len(oldest_data) != 0 and len(oldest_data) >= NUMBER_TO_RETURN:
        database_activity_insert(subreddit_name, 'oldest', 'oldest', oldest_data)

    return oldest_section


def subreddit_pushshift_time_top_retriever(subreddit_name, start_time, end_time,
                                           last_month_mode=False):
    """This function accesses Pushshift to retrieve the TOP posts on a
    subreddit for a given timespan.
    It also formats it as a dictionary indexed by score. If it is for
    the current month, then it does a backwards looking search for the
    top data.

    It is paired with a SQLite table later to store the data locally.
    Note that the data returned in this dictionary can be very large if
    the subreddit is very active. It will need to be trimmed down before
    it is stored locally.

    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time,
                       expressed as a string.
    :param end_time: We want to find posts *before* this time, expressed
                     as a string.
    :param last_month_mode: A boolean indicating whether we want the
                            actual top X posts directly from PRAW.
    :return: A dictionary with data, indexed by post ID.
    """
    list_of_ids = []
    final_dictionary = {}
    number_to_query = 500

    # Convert YYYY-MM-DD to Unix time and get the current month as a
    # YYYY-MM string.
    start_time_string = str(start_time)
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time)
    current_month = date_month_convert_to_string(time.time())

    # If the search is not for the current month, then we check
    # Pushshift for historical data.
    if current_month not in start_time_string and not last_month_mode:
        api_search_query = ("https://api.pushshift.io/reddit/search/submission/?subreddit={}"
                            "&sort_type=score&sort=desc&after={}&before={}&size={}")

        # Get the data from Pushshift as JSON.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(subreddit_name,
                                                                            start_time, end_time,
                                                                            number_to_query))
        # If I did not get the right data, return an empty dictionary.
        # Otherwise, we can look at the submissions we have.
        if 'data' not in retrieved_data:
            return {}
        else:
            returned_submissions = retrieved_data['data']

        # Iterate over the returned submissions and get their IDs.
        for submission in returned_submissions:

            # Take the ID, fetch the PRAW submission object, and
            # append that object to our list. Add the fullname ID of the
            # submission to the list of IDs.
            list_of_ids.append("t3_{}".format(submission['id']))

        if len(list_of_ids) != 0:
            # If we don't have ANY data, return an empty dictionary.
            # Get info for each object. `info()` is quite fast and
            # accepts a list of fullname IDs.
            reddit_submissions = reddit.info(fullnames=list_of_ids)
            for submission in reddit_submissions:
                post_id = submission.id
                final_dictionary[post_id] = {}
                final_dictionary[post_id]['id'] = post_id
                final_dictionary[post_id]['score'] = submission.score
                final_dictionary[post_id]['title'] = submission.title
                final_dictionary[post_id]['permalink'] = submission.permalink
                final_dictionary[post_id]['created_utc'] = int(submission.created_utc)

                # Check if the author is deleted.
                try:
                    final_dictionary[post_id]['author'] = submission.author.name
                except AttributeError:
                    final_dictionary[post_id]['author'] = '[deleted]'
    else:
        # This is for the last month. We can access Reddit directly to
        # get the top posts, filtering for time.
        submissions = list(reddit.subreddit(subreddit_name).top(time_filter='month'))
        logger.debug('Top Retriever: Getting top posts for r/{} via API.'.format(subreddit_name))
        if len(submissions) != 0:
            for submission in submissions:
                if end_time >= submission.created_utc >= start_time:
                    post_id = submission.id
                    final_dictionary[post_id] = {}
                    final_dictionary[post_id]['id'] = post_id
                    final_dictionary[post_id]['score'] = submission.score
                    final_dictionary[post_id]['title'] = submission.title
                    final_dictionary[post_id]['permalink'] = submission.permalink
                    final_dictionary[post_id]['created_utc'] = int(submission.created_utc)

                    # Check if the author is deleted.
                    try:
                        final_dictionary[post_id]['author'] = submission.author.name
                    except AttributeError:
                        final_dictionary[post_id]['author'] = '[deleted]'

    return final_dictionary


def subreddit_top_collater(subreddit_name, month_string, last_month_mode=False):
    """This function takes a dictionary formed by the earlier function
    and forms a Markdown bulleted list with the top posts from a
    specific month.

    Note that the dictionary in question is indexed by post ID.
    So this function has to sort it by score to get the top.

    :param subreddit_name: The community we are looking for.
    :param month_string: A month expressed as YYYY-MM.
    :param last_month_mode: A boolean indicating whether we want the
                            actual top X posts directly from PRAW.
    :return: A Markdown bulleted list.
    """
    # Set date variables.
    year = int(month_string.split('-')[0])
    month = int(month_string.split('-')[1])
    first_day = "{}-01".format(month_string)
    last_day = "{}-{}".format(month_string, calendar.monthrange(year, month)[1])

    # Get the current month. We don't want to save the data if it is in
    # the current month, which is not over.
    current_month = date_month_convert_to_string(time.time())
    score_sorted = []
    formatted_lines = []
    line_template = "* `{:+}` [{}]({}), posted by u/{} on {}"

    # First we check the database to see if we already have saved data.
    # If there is, we use that data.
    result = database_activity_retrieve(subreddit_name, month_string, 'popular_submission')
    if result is not None:
        dictionary_data = result
    else:
        dictionary_data = subreddit_pushshift_time_top_retriever(subreddit_name, first_day,
                                                                 last_day, last_month_mode)

    # If there's no data, return `None`.
    if len(dictionary_data.keys()) == 0:
        return None

    # Sort through the returned dictionary data, and add it to a list
    # with tuples and their respective IDs (score, ID).
    for key in dictionary_data:
        score = dictionary_data[key]['score']
        score_sorted.append((score, key))

    # Sort our list of tuples with highest score first.
    score_sorted.sort(key=lambda tup: tup[0], reverse=True)

    # Format the dictionary data as a Markdown table, ordered with the
    # highest scoring post first.
    for item in score_sorted[:NUMBER_TO_RETURN]:
        my_score = item[0]
        my_id = item[1]
        my_date = date_convert_to_string(dictionary_data[my_id]['created_utc'])
        new_line = line_template.format(my_score, dictionary_data[my_id]['title'],
                                        dictionary_data[my_id]['permalink'],
                                        dictionary_data[my_id]['author'], my_date)
        formatted_lines.append(new_line)

    # If we have data and we are not in the current month, we can store
    # the retrieved data into the database.
    if dictionary_data is not None and result is None and current_month != month_string:

        # Trim the dictionary data if needed. We don't want to store too
        # much, only the top * 2 submissions.
        # If this is not in the top items, delete it from dictionary.
        for submission_id in list(dictionary_data.keys()):
            if not any(submission_id == entry[1] for entry in score_sorted[:NUMBER_TO_RETURN * 2]):
                del dictionary_data[submission_id]

        # Store the dictionary data to our database.
        database_activity_insert(subreddit_name, month_string, 'popular_submission',
                                 dictionary_data)

    # Put it all together as a formatted chunk of text.
    body = "\n\n##### Most Popular Posts\n\n" + "\n".join(formatted_lines)

    return body


def subreddit_pushshift_time_authors_retriever(subreddit_name, start_time, end_time, search_type):
    """This function accesses Pushshift to retrieve the top FREQUENT
    submitters/commenters on a subreddit for a given timespan. It also
    formats the data as a bulleted Markdown list. Though this can
    technically be used to get data from any particular range of time,
    in this case we only run it on a month-to-month basis.

    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time.
    :param end_time: We want to find posts *before* this time.
    :param search_type: `comment` or `submission`, depending on the
                        type of top results one wants.
    :return: A Markdown list with a header and bulleted list for each
             submitter/commenter.
    """
    # Convert YYYY-MM-DD to Unix time.
    specific_month = start_time.rsplit('-', 1)[0]
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time)
    current_month = date_month_convert_to_string(time.time())
    activity_index = "authors_{}".format(search_type)

    # Check the database first.
    authors_data = database_activity_retrieve(subreddit_name, specific_month, activity_index)

    # If we don't have local data, fetch it.
    if authors_data is None:
        authors_data = {}
        api_search_query = ("https://api.pushshift.io/reddit/search/{}/?subreddit={}"
                            "&sort_type=score&sort=desc&after={}&before={}&aggs=author&size=50")

        # Get the data from Pushshift as a dictionary.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(search_type,
                                                                            subreddit_name,
                                                                            start_time, end_time))

        # If for some reason we encounter an error, we return an error
        # string and will re-access next update.
        if 'aggs' not in retrieved_data:

            # Change the header in the error depending on the type.
            if search_type == 'submission':
                error_message = "\n\n##### Top Submitters\n\n"
            else:
                error_message = "\n\n##### Top Commenters\n\n"

            error_message += ("* There was an temporary issue retrieving this information. "
                              "Artemis will attempt to re-access the data "
                              "at the next statistics update.")
            return error_message

        returned_authors = retrieved_data['aggs']['author']

        # Code to remove bots and [deleted] from the authors list.
        # Otherwise, it is very likely that they will end up as some
        # of the "top" submitters for comments due to frequency.
        excluded_usernames = ['AutoModerator', 'Decronym', '[deleted]', 'RemindMeBot',
                              'TotesMessenger', 'translator-BOT']

        # Iterate over the data and collect top authors into a
        # dictionary that's indexed by key.
        for author in returned_authors:
            submitter = author['key']
            if submitter not in excluded_usernames:
                submit_count = int(author['doc_count'])
                authors_data[submitter] = submit_count

        # Write to the database if we are not in the current month.
        if specific_month != current_month:
            database_activity_insert(subreddit_name, specific_month, activity_index, authors_data)

    # Get the data formatted.
    formatted_data = subreddit_pushshift_time_authors_collater(authors_data, search_type)

    return formatted_data


def subreddit_pushshift_time_authors_collater(input_dictionary, search_type):
    """This simple function takes data from its equivalent dictionary
    and outputs it as a Markdown segment.

    :param input_dictionary: A dictionary containing data on the most
                             frequent authors during a time period.
    :param search_type: Either `submission` or `comment`.
    :return: A Markdown segment.
    """
    formatted_lines = []
    bullet_number = 1
    line_template = "{}. {:,} {}s by u/{}"

    # Go through the dictionary.
    for author in sorted(input_dictionary, key=input_dictionary.get, reverse=True):
        num_type = input_dictionary[author]
        line = line_template.format(bullet_number, num_type, search_type, author)
        formatted_lines.append(line)
        bullet_number += 1

    # Format everything together and change the header depending on the
    # type of item we're processing.
    if search_type == 'submission':
        header = "\n\n##### Top Submitters\n\n"
    else:
        header = "\n\n##### Top Commenters\n\n"

    # If we have entries for this month, format everything together.
    # Otherwise, return a section noting there's nothing.
    if len(formatted_lines) > 0:
        body = header + '\n'.join(formatted_lines[:NUMBER_TO_RETURN])
    else:
        no_section = "* It appears that there were no {}s during this period.".format(search_type)
        body = header + no_section

    return body


def subreddit_pushshift_activity_retriever(subreddit_name, start_time, end_time, search_type):
    """This function accesses Pushshift to retrieve the activity,
    including MOST submissions or comments, on a subreddit for a given
    timespan. It also formats it as a bulleted Markdown list.
    It also calculates the total AVERAGE over this time period and
    includes it at a separate line at the end.

    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time,
                       expressed in string form.
    :param end_time: We want to find posts *before* this time,
                     expressed in string form.
    :param search_type: `comment` or `submission`, depending on the type
                        of top results one wants.
    :return: A Markdown list with a header and bulleted list for each
             most active day.
    """
    # Convert YYYY-MM-DD UTC to Unix time, get the number of days
    # in month, and get the number of days in between these two dates.
    num_days = date_num_days_between(start_time, end_time) + 1
    specific_month = start_time.rsplit('-', 1)[0]
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time) + 86399
    current_month = date_month_convert_to_string(time.time())
    activity_index = "activity_{}".format(search_type)

    # Check the database first.
    days_data = database_activity_retrieve(subreddit_name, specific_month, activity_index)

    # If we don't have local data, fetch it.
    if days_data is None:
        days_data = {}

        api_search_query = ("https://api.pushshift.io/reddit/search/{}/?subreddit={}"
                            "&sort_type=created_utc&after={}&before={}&aggs=created_utc&size=50")

        # Get the data from Pushshift as a dictionary.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(search_type,
                                                                            subreddit_name,
                                                                            start_time, end_time))

        # If for some reason we encounter an error, we return an error
        # string for inclusion.
        if 'aggs' not in retrieved_data:
            error_message = "\n\n##### {}s Activity\n\n".format(search_type)
            error_message += ("* There was an temporary issue retrieving this information. "
                              "Artemis will attempt to re-access the data at "
                              "the next statistics update.")
            return error_message

        returned_days = retrieved_data['aggs']['created_utc']

        # Iterate over the data. If the number of posts in a day is more
        # than zero, save it.
        for day in returned_days:
            day_string = date_convert_to_string(int(day['key']))
            num_of_posts = int(day['doc_count'])
            if num_of_posts != 0:
                days_data[day_string] = num_of_posts

        # Write to the database if we are not in the current month.
        if specific_month != current_month:
            database_activity_insert(subreddit_name, specific_month, activity_index, days_data)

    # Get the data formatted.
    formatted_data = subreddit_pushshift_activity_collater(days_data, search_type, num_days)

    return formatted_data


def subreddit_pushshift_activity_collater(input_dictionary, search_type, num_days):
    """This simple function takes data from its equivalent dictionary
    and outputs it as a Markdown segment.

    :param input_dictionary: A dictionary containing data on the most
                             active days during a time period.
    :param search_type: Either `submission` or `comment`.
    :param num_days: The number of days we are evaluating, passed from
                     the other function.
    :return: A Markdown segment.
    """
    days_highest = []
    lines_to_post = []
    unavailable = "* It appears that there were no {}s during this period.".format(search_type)

    # Find the average number of the type.
    if num_days > 0:
        # If we have a time frame of how many days we're
        # getting, let's get the average.
        num_average = sum(input_dictionary.values()) / num_days
        average_line = "\n\n*Average {0}s per day*: **{1:,.2f}** {0}s.".format(search_type,
                                                                               int(num_average))
    else:
        average_line = str(unavailable)

    # Find the busiest days and add those days to a list with the date.
    most_posts = sorted(zip(input_dictionary.values()), reverse=True)[:NUMBER_TO_RETURN]
    for number in most_posts:
        for date, count in input_dictionary.items():
            if number[0] == count and date not in str(days_highest):  # Get the unique date.
                days_highest.append([date, number[0]])
                break

    # Format the individual lines.
    for day in days_highest:
        if int(day[1]) != 0:
            line = "* **{:,}** {}s on **{}**".format(int(day[1]), search_type, day[0])
            lines_to_post.append(line)

    # Format the text body. If there are days recorded join up all the
    # data. Otherwise, return the `unavailable` message.
    header = "\n\n##### {}s Activity\n\n**Most Active Days**\n\n".format(search_type.title())
    if len(lines_to_post) > 0:  #
        body = header + '\n'.join(lines_to_post) + average_line
    else:
        body = header + unavailable

    return body


def subreddit_statistics_earliest_determiner(subreddit_name):
    """This function uses PRAW to fetch the Reddit limit of 1000 posts.
    Then it checks the dates of those posts and returns the earliest day
    for which we have FULL data as a YYYY-MM-DD string.

    :param subreddit_name: Name of a subreddit.
    :return: YYYY-MM-DD, earliest day for which we have full data.
    """
    dates = []

    # Access the subreddit.
    r = reddit.subreddit(subreddit_name)

    for result in r.new(limit=1000):
        dates.append(int(result.created_utc))

    if len(dates) == 0:
        # There were never any posts on here, it seems.
        # So we return a placeholder date, the start of the bot's
        # operations.
        return "2018-11-01"
    else:
        # We have a list of dates.
        oldest_unix = min(dates)
        oldest_full_day = oldest_unix + 86400
        oldest_day_string = date_convert_to_string(oldest_full_day)

        return oldest_day_string


def subreddit_statistics_recorder(subreddit_name, start_time, end_time):
    """This function takes posts from a given subreddit and tabulates
    how many belonged to each flair and each total. When retrieving
    posts from a subreddit it will exit the loop if the posts return
    start to be older than `start_time` in order to finish the process
    as quickly as possible.

    :param subreddit_name: Name of a subreddit.
    :param start_time: Posts older than this UNIX time UTC will be
                       ignored.
    :param end_time: Posts younger than this UNIX time UTC will be
                     ignored.
    :return: A dictionary indexed by flair text with the number of posts
             that belong to each flair.
             This dictionary will be empty if there were no posts
             recorded during this period.
    """
    statistics_dictionary = {}
    all_flairs = []
    no_flair_count = 0

    # This is a counter of older posts that have been encountered.
    # The loop breaks if a certain amount exceeds (10) which then
    # indicates that the posts being processed don't need to be
    # seen anymore.
    old_post_count = 0
    old_post_limit = 10

    # Access the subreddit. Consider 1000 to be a MAXIMUM limit, as the
    # loop will exit early if results are all too old.
    r = reddit.subreddit(subreddit_name)
    fetch_limit = 1000

    # Iterate over our fetched posts. Newest posts will be returned
    # first, oldest posts last.
    for result in r.new(limit=fetch_limit):

        # Check that the time parameters of the retrieved posts are
        # correct. If it's newer than the time we want, skip.
        result_created = result.created_utc
        if result_created > end_time:
            continue
        elif result_created < start_time:
            # This is older than the time we want. Record how many older
            # posts have been encountered, and if it exceeds our count,
            # we also exit the loop here as subsequent retrieved posts
            # will all be older than the time we want.
            if old_post_count < old_post_limit:
                old_post_count += 1
                continue
            else:
                break

        # Once time parameters are taken care of, we can process our
        # results.
        result_text = result.link_flair_text

        # Get the submission and add its flair to a list. If there is no
        # flair text, add one to the count.
        if result_text is not None:
            all_flairs.append(result_text)
        else:
            no_flair_count += 1

    # Get an alphabetized list of the flairs we have, and for each flair
    # get the number of posts with the post flair.
    alphabetized_list = list(set(all_flairs))
    for flair in alphabetized_list:
        statistics_dictionary[flair] = all_flairs.count(flair)

    # Add the ones that do not have flair. Note that we index it by its
    # *string* "None", but not the value `None`.
    if no_flair_count > 0:
        statistics_dictionary['None'] = no_flair_count

    return statistics_dictionary


def subreddit_statistics_recorder_daily(subreddit, date_string):
    """This is a function that checks the database for
    `subreddit_statistics_recorder` data. It merges it if it finds data
    already, otherwise it adds the day's statistics as a new daily
    entry.
    This is intended to be run daily as well to get the PREVIOUS day's
    statistics.

    :param subreddit: The subreddit we're checking for.
    :param date_string: A date string in the model of YYYY-MM-DD.
    :return:
    """
    to_store = True
    subreddit = subreddit.lower()
    day_start = date_convert_to_unix(date_string)
    day_end = day_start + 86399

    results = database_statistics_posts_retrieve(subreddit)

    # First we check to see if we have proper data. If the data is
    # already stored, `to_store` will be set to `False`.
    if results is not None:
        if date_string in results:
            stat_msg = 'Stat Recorder Daily: Statistics already stored for r/{} on {}.'
            logger.debug(stat_msg.format(subreddit, date_string))
            to_store = False
        else:
            to_store = True

    # If `to_store` is `True`, then let's store the information.
    # Get the data for the day and put it into a dictionary indexed by
    # the date string.
    if to_store:
        day_data = {date_string: subreddit_statistics_recorder(subreddit, day_start, day_end)}
        database_statistics_posts_insert(subreddit, day_data)
        logger.debug('Stat Recorder Daily: Stored statistics for r/{} for {}.'.format(subreddit,
                                                                                      date_string))
        logger.debug('Stat Recorder Daily: Stats for r/{} on {} are: {}'.format(subreddit,
                                                                                date_string,
                                                                                day_data))

    return


def subreddit_statistics_collater(subreddit, start_date, end_date):
    """A function that looks at the information stored for a certain
    time period and generates a Markdown table for it.
    This produces a table that has the posts sorted by alphabetical
    order and how many are of each flair.

    :param subreddit: The community we are looking for.
    :param start_date: The start date, expressed as YYYY-MM-DD we
                       want to get stats from.
    :param end_date: The end date, expressed as YYYY-MM-DD we want
                     to get stats from.
    :return: A nice Markdown table.
    """
    main_dictionary = {}
    final_dictionary = {}
    table_lines = []
    total_amount = 0
    total_days = []  # The days of data that we are evaluating.

    # Convert those days into Unix integers.
    # We get the Unix time of the start date dates at midnight UTC and
    # the end of this end day, right before midnight UTC.
    start_unix = date_convert_to_unix(start_date)
    end_unix = date_convert_to_unix(end_date) + 86399

    # Access our database.
    results = database_statistics_posts_retrieve(subreddit)

    if results is None:
        # There is no information stored. Return `None`.
        return None
    else:
        # Iterate over the returned information.
        # For each day, convert the stored YYYY-MM-DD string to Unix UTC
        # and then take the dictionary of statistics stored per day.
        for date, value in results.items():
            stored_date = date_convert_to_unix(date)
            stored_data = value

            # If the date of the data fits between our parameters, we
            # combine the dictionaries.
            if start_unix <= stored_date <= end_unix:
                total_days.append(date)
                for key in (main_dictionary.keys() | stored_data.keys()):
                    if key in main_dictionary:
                        final_dictionary.setdefault(key, []).append(main_dictionary[key])
                    if key in stored_data:
                        final_dictionary.setdefault(key, []).append(stored_data[key])

    # We get the total amount of all posts during this time period here.
    for count in final_dictionary.values():
        total_amount += sum(count)

    # Format the lines of the table. Each line represents a flair
    # and how many posts were flaired as it.
    for key, value in sorted(final_dictionary.items()):
        posts_num = sum(value)  # Number of posts matching this flair.
        # Calculate the percent that have this flair.
        percentage = posts_num / total_amount

        # We italicize this entry since it represents unflaired posts.
        # Note that it was previously marked with the string "None",
        # rather than the value `None`.
        if key == "None":
            key_formatted = "*None*"
        else:
            key_formatted = messaging_flair_sanitizer(key, False)

        # Format the table's line.
        entry_line = '| {} | {:,} | {:.2%} |'.format(key_formatted, sum(value), percentage)
        table_lines.append(entry_line)

    # Add the total line that tabulates how many posts were posted in
    # total. We put this at the end of the table.
    table_lines.append("| **Total** | {} | 100% |".format(total_amount))

    # Format the whole table.
    table_header = ("| Post Flair | Number of Submissions | Percentage |\n"
                    "|------------|-----------------------|------------|\n")

    # If start of the month was not recorded, data may be incomplete.
    # Add a disclaimer to the top of the table.
    if start_date not in total_days:
        initial = "*Note: Data for this monthly table may be incomplete.*\n\n{}"
        table_header = initial.format(table_header)
    table_body = table_header + '\n'.join(table_lines)

    return table_body


def subreddit_statistics_retriever(subreddit_name):
    """A function that gets ALL of the information on a subreddit's
    statistics and returns it as Markdown tables sorted by month.
    This also incorporates the data from the Pushshift functions above.
    This can be considered the MAIN statistics function, or at least the
    most top-level one.

    :param subreddit_name: Name of a subreddit.
    :return: A Markdown section that collates all the existing
             information for a subreddit.
    """
    formatted_data = []

    # First we want to get all the data.
    results = database_statistics_posts_retrieve(subreddit_name)

    # Get a list of all the dates we have covered, oldest first.
    # If nothing was found, just return.
    if results is None:
        return
    else:
        list_of_dates = list(sorted(results.keys()))

    # Check if there are actually a list of dates. If there aren't any
    # return.
    if not list_of_dates:
        return

    # Get all the months that are between our two dates.
    oldest_date = list_of_dates[0]
    newest_date = list_of_dates[-1]
    intervals = [oldest_date, newest_date]
    start, end = [datetime.datetime.strptime(_, "%Y-%m-%d") for _ in intervals]
    list_of_months = list(OrderedDict(((start + datetime.timedelta(_)).strftime("%Y-%m"),
                                       None) for _ in range((end - start).days)).keys())

    # Iterate per month.
    for entry in list_of_months:
        current_time = int(time.time())
        supplementary_data = []

        # Get the first day per month.
        year = int(entry.split('-')[0])
        month = int(entry.split('-')[1])
        first_day = "{}-01".format(entry)

        # Get the last day per month. If it's the current month, we want
        # yesterday's date as the end date.
        # Otherwise, if it's not the current month get the regular
        # last day of the month.
        if entry == date_month_convert_to_string(current_time):
            last_day = date_convert_to_string(current_time - 86400)
        else:
            last_day = "{}-{}".format(entry, calendar.monthrange(year, month)[1])

        # Get the main statistics data.
        month_header = "### {}\n\n#### Activity".format(entry)
        month_table = subreddit_statistics_collater(subreddit_name, first_day, last_day)

        # Get the supplementary Pushshift data (most frequent posters,
        # activity, etc.)
        # First we get the Pushshift activity data. How many
        # submissions/comments per day, most active days, etc.
        search_types = ['submission', 'comment']
        for object_type in search_types:
            supplementary_data.append(subreddit_pushshift_activity_retriever(subreddit_name,
                                                                             first_day, last_day,
                                                                             object_type))

        # Secondly, we get the top submitters/commenters. People who
        # submitted or commented the most.
        for object_type in search_types:
            supplementary_data.append(subreddit_pushshift_time_authors_retriever(subreddit_name,
                                                                                 first_day,
                                                                                 last_day,
                                                                                 object_type))

        # Thirdly, we combine the supplementary data and get the top
        # posts from the time period.
        supplementary_data = ''.join(supplementary_data)
        top_posts_data = subreddit_top_collater(subreddit_name, entry)
        if top_posts_data is not None:
            supplementary_data += top_posts_data

        # Pull the single month entry together and add it to the list.
        month_body = month_header + supplementary_data
        month_body += "\n\n#### Submissions by Flair\n\n" + month_table
        formatted_data.append(month_body)

    # Collect all the month entries. Reverse them so the newest is
    # listed first.
    formatted_data.reverse()

    # Get the three oldest posts in the sub.
    oldest_posts = subreddit_pushshift_oldest_retriever(subreddit_name)
    total_data = "\n\n".join(formatted_data) + oldest_posts

    return total_data


def subreddit_statistics_retrieve_all(subreddit_name):
    """This function is used when a subreddit is added to the moderation
    list for the first time. We basically go through each day for which
    we can find data from Reddit (subject to the 1000 item limit)
    and store it day by day so that we have data to work with.
    This function used to just fetch up from the first day of the month
    but it's now changed to go much further back.

    :param subreddit_name: Name of a subreddit.
    :return: Nothing, but it will save to the database.
    """
    posts = []
    # This is a dictionary indexed by date of the PRAW objects that are
    # associated with each date.
    days_dictionary = {}
    #  A dictionary indexed by date of submissions and containing a
    #  dictionary of posts indexed by flair.
    saved_dictionary = {}

    # Set our time variables.
    current_time = int(time.time())
    yesterday = date_convert_to_string(current_time - 86400)
    time_start = subreddit_statistics_earliest_determiner(subreddit_name)

    # Otherwise, we're good to go. We get data from the start of our
    # data till yesterday. (Today is not over yet)
    actual_days_to_get = date_get_historical_series_days(date_get_series_of_days(time_start,
                                                                                 yesterday))

    # If there is nothing returned, then it's probably a sub that gets
    # TONS of submissions, so we make it a single list with one item.
    if len(actual_days_to_get) == 0:
        actual_days_to_get = [date_convert_to_string(current_time)]

    # Now we fetch literally all the possible posts we can from Reddit
    # and put it into a list.
    posts += list(reddit.subreddit(subreddit_name).new(limit=1000))
    for post in posts:
        day_created = date_convert_to_string(post.created_utc)

        if day_created not in actual_days_to_get:
            continue
        else:
            # Add the PRAW submission objects to our dictionary.
            if day_created in days_dictionary:
                days_dictionary[day_created].append(post)
            else:
                days_dictionary[day_created] = [post]

    # Now iterate over each day and gather the flairs for that day.
    for day in days_dictionary.keys():
        days_flairs = []
        insert_dictionary = {}
        days_posts = days_dictionary[day]

        for result in days_posts:
            result_text = result.link_flair_text
            days_flairs.append(str(result_text))

        # Now we want to generate a dictionary for the day,
        # indexed by flair.
        for flair in list(set(days_flairs)):
            if flair not in insert_dictionary:
                insert_dictionary[flair] = days_flairs.count(flair)

        # Add the dictionary to the one we will save.
        saved_dictionary[day] = insert_dictionary

    # Save the information to the database. Now that we have generated a
    # dictionary, we can insert the data.
    database_statistics_posts_insert(subreddit_name, saved_dictionary)
    logger.info('Statistics Retrieve All: Got monthly statistics for r/{}.'.format(subreddit_name))

    return


def subreddit_userflair_counter(subreddit_name):
    """This function if called on a subreddit with the `flair`
    permission, allows for Artemis to tally the popularity of
    userflairs. It has two ways of running:

    The better supported one is for the new Reddit Emoji, while
    the other is for the old `css_class` of flairs.
    The former has images in the output table.

    :param subreddit_name: The name of a subreddit.
    :return: `None` if the request is not valid (no Reddit flairs or
             access to flairs), formatted Markdown text otherwise.
    """
    flair_master = {}
    flair_master_css = {}
    emoji_dict = {}
    usage_index = {}
    users_w_flair = 0  # Variable storing how many users have a flair.
    formatted_lines = []
    relevant_sub = reddit.subreddit(subreddit_name)

    # Check to see if emoji are actually used in user flairs on this
    # subreddit, even if the CSS class is set to blank this is okay.
    flair_list = [x['css_class'] for x in list(reddit.subreddit(subreddit_name).flair.templates)]
    flair_list = list(set(flair_list))
    num_userflair = len(flair_list)

    # If there are no userflairs *at all* on the subreddit, exit.
    if num_userflair == 0:
        logger.debug('Userflair Counter: There are no userflairs on r/{}.'.format(subreddit_name))
        return None
    else:
        logger.debug('Userflair Counter: There are {} userflairs on r/{}.'.format(num_userflair,
                                                                                  subreddit_name))

    # Retrieve the whole list of flair emoji. Forms a dictionary keyed
    # by `:emoji:`, value of the emoji image.
    for emoji in relevant_sub.emoji:
        emoji_dict[":{}:".format(emoji)] = emoji.url

    # There are no CSS classes defined (they would all be blank entries)
    # and there are no emoji, exit.
    if all(x == '' for x in flair_list) and len(emoji_dict) == 0:
        logger.info('Userflair Counter:  All userflairs on r/{} are '
                    'blank with no CSS or emoji.'.format(subreddit_name))
        return None

    # Iterate over the flairs that people have. This returns a
    # dictionary per flair, per user.
    try:
        # Iterate over each flair for an individual user here.
        for flair in relevant_sub.flair(limit=None):
            if flair['flair_text'] is not None:
                flair_master[str(flair['user'])] = flair['flair_text']
                users_w_flair += 1

            # Record down the CSS class in case we need to
            # tabulate Old Reddit data, since that's how flairs are
            # defined under the old system (usually).
            if flair['flair_css_class'] is not None:
                flair_master_css[str(flair['user'])] = flair['flair_css_class']
    except prawcore.exceptions.Forbidden:
        # We do not have the `flair` mod permission. Skip.
        logger.info('Userflair Counter: I do not have the `flair` mod permission.')
        return None

    # This is the process for NEW Reddit userflairs, which use Reddit
    # emoji, which are images formed in the template `:image:`.
    # If we have Reddit emoji, count them. Otherwise, count CSS classes
    # instead. This means that tabulating New Reddit userflairs has
    # priority over old ones.
    if len(emoji_dict) > 0:
        logger.debug('Userflair Counter: There are Reddit emoji on r/{}. '
                     'Using new runtime.'.format(subreddit_name))
        # Iterate over the dictionary with user flairs.
        # `flair_text` is an individual user's flair.
        for flair_text in flair_master.values():
            # Iterate over the emoji we have recorded.
            for emoji_string in emoji_dict.keys():
                if emoji_string in flair_text:
                    if emoji_string in usage_index:
                        usage_index[emoji_string] += 1
                    else:
                        usage_index[emoji_string] = 1

        # Get a list of unused emoji, alphabetized.
        unused = list(sorted(emoji_dict.keys() - usage_index.keys(), key=str.lower))

        # Format our header portion.
        header_used = ("\n\n#### Used Emoji\n\n| Reddit Emoji & Image | "
                       "Subscribers w/ Emoji in Flair |\n"
                       "|----------------------|-------------------------------|\n")

        # If there are actually people with emoji flairs, format each
        # individual line and append it.
        if len(usage_index) > 0:
            for emoji_string in list(sorted(emoji_dict.keys(), key=str.lower)):
                if emoji_string in usage_index:
                    new_line = "| [{}]({}) | {:,} |".format(emoji_string, emoji_dict[emoji_string],
                                                            usage_index[emoji_string])
                    formatted_lines.append(new_line)
    else:
        # This is the process for OLD Reddit userflairs
        # (using CSS classes). This takes lower priority than the Reddit
        # emoji system and is more limited (no images).
        logger.debug('Userflair Counter: There are no Reddit emoji on r/{}. '
                     'Using old runtime.'.format(subreddit_name))
        for flair_text in flair_master_css.values():
            for css_string in flair_list:
                if css_string in flair_text:
                    if css_string in usage_index:
                        usage_index[css_string] += 1
                    else:
                        usage_index[css_string] = 1

        # Get a list of unused flairs.
        unused = list(sorted(flair_list - usage_index.keys(), key=str.lower))

        # Format our header portion.
        header_used = ("\n\n#### Used Flairs\n\n| Reddit Flair | Subscribers |\n"
                       "|--------------|-------------|\n")

        # If there are actually people with flairs, check for CSS class.
        if len(usage_index) > 0:
            for css_string in list(sorted(flair_list, key=str.lower)):
                if css_string in usage_index:
                    # There is just a regular default flair.
                    if len(css_string) == 0:
                        css_string_format = "[blank]"
                        new_line = "| `{}` | {:,} |".format(css_string_format,
                                                            usage_index[css_string])
                    else:
                        new_line = "| `{}` | {:,} |".format(css_string,
                                                            usage_index[css_string])
                    formatted_lines.append(new_line)

    # Format our output. Add a header and display everything else
    # as a table.
    header = ("\n\n## Userflairs\n\n"
              "* Subscribers with flair: {:,} ({:.2%} of total subscribers)\n"
              "* Number of used flairs: {}")

    # If there are subscribers, calculate the percentage of those who
    # have userflairs. Otherwise, include a boilerplate string.
    if relevant_sub.subscribers > 0:
        flaired_percentage = users_w_flair / relevant_sub.subscribers
    else:
        flaired_percentage = '---'
    body = header.format(users_w_flair, flaired_percentage, len(usage_index))

    # Add the used parts as needed. If we have a short-ish list of
    # unused flairs, tabulate that too.
    if len(usage_index) > 0:
        body += header_used + '\n'.join(formatted_lines)
    if len(unused) > 0:
        header_unused = "\n\n#### Unused Flairs\n\n* **Number of unused flairs**: {}\n\n* "
        header_unused = header_unused.format(len(unused))
        body += header_unused + '\n* '.join(unused)

    return body


def subreddit_public_moderated(username):
    """A function that retrieves (via the web and not the database)
    a list of public subreddits that a user moderates.

    :param username: Name of a user.
    :return: A list of subreddits that the user moderates.
    """
    subreddit_dict = {}
    active_subreddits = []
    active_fullnames = []

    # Iterate through the data and get the subreddit names and their
    # Reddit fullnames (prefixed with `t5_`).
    mod_target = '/user/{}/moderated_subreddits'.format(username)
    for subreddit in reddit_helper.get(mod_target)['data']:
        active_subreddits.append(subreddit['sr'].lower())
        active_fullnames.append(subreddit['name'].lower())
    active_subreddits.sort()

    subreddit_dict['list'] = active_subreddits
    subreddit_dict['fullnames'] = active_fullnames
    subreddit_dict['total'] = len(active_subreddits)

    return subreddit_dict


"""WIKIPAGE FUNCTIONS"""


def wikipage_creator(subreddit_name):
    """Checks if there is already a wikipage called
    `assistantbot_statistics` on the target subreddit.
    If there isn't one, it creates the page and sets its mod settings.
    It will also add a blank page template.
    This will return the wikipage object that already exists or the new
    one that was just created.

    :param subreddit_name: Name of a subreddit.
    :return: A PRAW Wikipage object of the statistics page.
    """
    # Define the wikipage title to edit or create.
    page_name = "{}_statistics".format(USERNAME.lower())
    r = reddit.subreddit(subreddit_name)

    # Check if the page is there by trying to get the text of the page.
    # This will fail if the page does NOT exist. It will also fail
    # if the bot does not have enough permissions to create it.
    # That will throw a `Forbidden` exception.
    try:
        statistics_test = r.wiki[page_name].content_md

        # If the page exists, then we get the PRAW Wikipage object here.
        statistics_wikipage = r.wiki[page_name]
        log_message = ("Wikipage Creator: Statistics wiki page for r/{} "
                       "already exists with length {}.")
        logger.debug(log_message.format(subreddit_name, statistics_test))
    except prawcore.exceptions.NotFound:
        # There is no wiki page for Artemis's statistics. Let's create
        # the page if it doesn't exist. Also add a message if statistics
        # gathering will be paused due to the subscriber count being
        # below the minimum (`MINIMUM_SUBSCRIBERS`).
        try:
            reason_msg = "Creating the u/{} statistics wiki page.".format(USERNAME)
            statistics_wikipage = r.wiki.create(name=page_name,
                                                content=WIKIPAGE_BLANK.format(MINIMUM_SUBSCRIBERS),
                                                reason=reason_msg)

            # Remove the statistics wiki page from the public list and
            # only let moderators see it. Also add Artemis as a approved
            # submitter/editor for the wiki.
            statistics_wikipage.mod.update(listed=False, permlevel=2)
            statistics_wikipage.mod.add(USERNAME)
            logger.info("Wikipage Creator: Created new statistics "
                        "wiki page for r/{}.".format(subreddit_name))
        except prawcore.exceptions.NotFound:
            # There is a wiki on the subreddit itself,
            # but we can't edit it.
            statistics_wikipage = None
            logger.info("Wikipage Creator: Wiki is present, "
                        "but insufficient privileges to edit wiki on r/{}.".format(subreddit_name))
    except prawcore.exceptions.Forbidden:
        # The wiki doesn't exist and Artemis can't create it.
        statistics_wikipage = None
        logger.info("Wikipage Creator: Insufficient mod privileges "
                    "to edit wiki on r/{}.".format(subreddit_name))

    return statistics_wikipage


def wikipage_collater(subreddit_name):
    """This function collates all the information together and forms the
    Markdown text used to update the wikipage.
    It does NOT post this text to the wiki; that's done by
    `wikipage_editor()`. As such this function can use the database.

    :param subreddit_name: Name of a subreddit.
    :return: A full Markdown page that is the equivalent of the text in
             the `assistantbot_statistics` wikipage for that subreddit.
    """
    # Get the current status of the bot's operations.
    start_time = time.time()
    status = wikipage_status_collater(subreddit_name)
    config_link = ""

    # Form the template by getting the various sections.
    statistics_section = subreddit_statistics_retriever(subreddit_name)
    if statistics_section is None:
        statistics_section = "No statistics data was found."

    subscribers_section = subreddit_subscribers_retriever(subreddit_name)
    if subscribers_section is None:
        subscribers_section = "No subscriber data was found."

    traffic_section = subreddit_traffic_retriever(subreddit_name)
    if traffic_section is None:
        traffic_section = "No traffic data was found."

    # Get the amount of time that has passed for the footer data.
    time_elapsed = int(time.time() - start_time)
    today = date_convert_to_string(start_time)

    # Check extended data to see if there are advanced settings in
    # there. If there is, add a link to the configuration page.
    # If there isn't any, leave that part as blank.
    extended_data = database_extended_retrieve(subreddit_name)
    if extended_data is not None:
        if 'custom_name' in extended_data:
            config_link = ("[🎚️ Advanced Config](https://www.reddit.com/r/{}"
                           "/wiki/assistantbot_config) • ".format(subreddit_name))

    # Compile the entire page together.
    body = WIKIPAGE_TEMPLATE.format(subreddit_name, status, statistics_section,
                                    subscribers_section, traffic_section, VERSION_NUMBER,
                                    time_elapsed, today, ANNOUNCEMENT, config_link)
    logger.debug("Wikipage Collater: Statistics page for r/{} collated.".format(subreddit_name))

    return body


def wikipage_config(subreddit_name):
    """
    This will return the wikipage object that already exists or the new
    one that was just created for the configuration page.

    :param subreddit_name: Name of a subreddit.
    :return: A tuple. In the first, `False` if an error was encountered,
             `True` if everything went right.
             The second parameter is a string with the error text if
             `False`, `None` if `True`.
    """
    # The wikipage title to edit or create.
    page_name = "{}_config".format(USERNAME.lower())
    r = reddit.subreddit(subreddit_name)

    # This is the max length (in characters) of the custom flair
    # enforcement message.
    limit_msg = 500
    # This is the max length (in characters) of the custom bot name and
    # goodbye.
    limit_name = 20
    # A list of Reddit's `tags` that are flair-external.
    permitted_tags = ['nsfw', 'oc', 'spoiler']

    # Check moderator permissions.
    current_permissions = main_obtain_mod_permissions(subreddit_name)[1]
    if 'wiki' not in current_permissions and 'all' not in current_permissions:
        logger.info("Wikipage Config: Insufficient mod permissions to edit "
                    "wiki config on r/{}.".format(subreddit_name))
        error = ("Artemis does not have the `wiki` mod permission "
                 "and thus cannot access the configuration page.")
        return False, error

    # Check the subreddit subscriber number. This is only used in
    # generating the initial default page. If there are enough
    # subscribers for userflair statistics, replace the boolean.
    if r.subscribers > MINIMUM_SUBSCRIBERS_USERFLAIR:
        page_template = CONFIG_DEFAULT.replace('userflair_statistics: False',
                                               'userflair_statistics: True')
    else:
        page_template = str(CONFIG_DEFAULT)

    # Check if the page is there and try and get the text of the page.
    # This will fail if the page does NOT exist.
    try:
        config_test = r.wiki[page_name].content_md

        # If the page exists, then we get the PRAW Wikipage object here.
        config_wikipage = r.wiki[page_name]
        logger.debug('Wikipage Config: Config wikipage found, length {}.'.format(len(config_test)))
    except prawcore.exceptions.NotFound:
        # The page does *not* exist. Let's create the config page.
        reason_msg = "Creating the {} config wiki page.".format(USERNAME)
        config_wikipage = r.wiki.create(name=page_name, content=page_template,
                                        reason=reason_msg)

        # Remove it from the public list and only let moderators see it.
        # Also add Artemis as a approved submitter/editor for the wiki.
        config_wikipage.mod.update(listed=False, permlevel=2)
        config_wikipage.mod.add(USERNAME)
        logger.info("Wikipage Config: Created new config wiki "
                    "page for r/{}.".format(subreddit_name))

    # Now we have the `config_wikipage`. We pass its data to YAML and
    # see if we can get proper data from it.
    # If it's a newly created page then the default data will be what
    # it gets from the page.
    default_data = yaml.safe_load(CONFIG_DEFAULT)
    # A list of the default variables (which are keys).
    default_vs_keys = list(default_data.keys())
    default_vs_keys.sort()
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
                try:
                    regex_pattern = r'[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}'
                    valid = re.search(regex_pattern, flair)
                except TypeError:
                    valid = False
                if not valid:
                    error_msg = ('Please ensure data in `flair_tags` has '
                                 'valid flair IDs, not `{}`.'.format(flair))
                    return False, error_msg

    # If we've reached this point, the data should be accurate and
    # properly typed. Write to database.
    database_extended_insert(subreddit_name, subreddit_config_data)
    logger.info('Wikipage Config: Inserted configuration data for '
                'r/{} into extended data.'.format(subreddit_name))

    return True, None


def wikipage_get_new_subreddits():
    """This function checks the last few submissions for the bot and
    returns a list of the ones that invited it since the last statistics
    run time. This is to tell wikipage_editor whether or not it needs to
    send an initial message to the subreddit moderators about their
    newly updated statistics page.

    :return: A list of subreddits that were added since the last
             midnight UTC. Empty list otherwise.
    """
    new_subreddits = []

    # Get the last midnight UTC from a day ago.
    today_string = date_convert_to_string(time.time() - 86400)
    last_midnight_utc = date_convert_to_unix(today_string)

    # Iterate over the last few subreddits on the user page that are
    # recorded as having added the bot. Get only moderator invites
    # posts and skip other sorts of posts.
    for result in reddit.subreddit('u_{}'.format(USERNAME)).new(limit=20):

        if "Accepted mod invite" in result.title:
            # If the time is older than the last midnight, tell the sub
            # and get the subreddit name from the subject.
            if result.created_utc > last_midnight_utc:
                new_subreddits.append(re.findall(" r/([a-zA-Z0-9-_]*)", result.title)[0].lower())

    return new_subreddits


def wikipage_editor(subreddit_dictionary):
    """This function takes a dictionary indexed by subreddit with the
    wikipage data for each one. Then it proceeds to update the wikipage
    on the relevant subreddit, going through the list of communities.

    This is also run secondarily as a process because editing wikipages
    on Reddit can be extremely unpredictable in terms of how long it
    will take, so we want to run it concurrently so that flair enforcing
    functions can have minimal disruption while the statistics routine
    is running.

    :param subreddit_dictionary: A dictionary indexed by subreddit with
                                 the wikipage data for each one.
    :return: None.
    """
    date_today = date_convert_to_string(time.time())
    logger.info("Wikipage Editor: BEGINNING editing ALL statistics wikipages.")
    logger.debug("Wikipage Editor: All wikipages are for: {}".format(UPDATER_DICTIONARY.keys()))

    # Fetch the list of new subreddits.
    new_subreddits = wikipage_get_new_subreddits()
    logger.info("Wikipage Editor: Newly updated subreddits are: {}".format(new_subreddits))

    # Iterate over our communities, starting in alphabetical order
    # (numbers, then A-Z).
    for subreddit_name in sorted(subreddit_dictionary.keys()):

        # We check to see if this subreddit is new. If we have NEVER
        # done statistics for this subreddit before, we will send an
        # initial setup message later once statistics are done.
        if subreddit_name in new_subreddits:
            send_initial_message = True
        else:
            send_initial_message = False

        # Check to make sure we have the wiki editing permission.
        # Exit early if we do not have the wiki editing permission.
        current_permissions = main_obtain_mod_permissions(subreddit_name)[1]
        if current_permissions is None:
            logger.error("Wikipage Editor: No longer a mod on r/{}; "
                         "cannot edit the wiki.".format(subreddit_name))
            continue
        if 'wiki' not in current_permissions and 'all' not in current_permissions:
            logger.info("Wikipage Editor: Insufficient mod permissions to edit "
                        "the wiki on r/{}.".format(subreddit_name))
            continue

        # Make sure that we have a page to write to. This returns the
        # `wikipage` PRAW object. Then get the *existing* text.
        statistics_wikipage = wikipage_creator(subreddit_name)
        statistics_wikipage_text = statistics_wikipage.content_md

        # If there is a pre-existing section for userflairs, split off
        # the pre-existing section and re-add it at the end of the
        # new data. If there is no section for userflairs,
        # leave it blank.
        if '## Userflairs' in statistics_wikipage_text:
            userflair_section = ('\n\n## Userflairs\n\n'
                                 + statistics_wikipage_text.split('## Userflairs')[1].strip())
        else:
            userflair_section = ""

        try:
            # Add the specific data that we have to the wikipage.
            # This will take into account a userflair section.
            content_data = subreddit_dictionary[subreddit_name] + userflair_section
            statistics_wikipage.edit(content=content_data,
                                     reason='Updating with statistics data '
                                            'on {} UTC.'.format(date_today))
            logger.info('Wikipage Editor: Successfully updated '
                        'r/{} statistics, {}.'.format(subreddit_name, date_today))

        except prawcore.exceptions.TooLarge:
            # The wikipage is going to be too big and is unable to
            # be saved without an error.
            logger.info('Wikipage Editor: The wikipage for '
                        'r/{} is too large.'.format(subreddit_name))

        except Exception as exc:
            # Catch-all broader exception during editing. Record to log.
            # This is split off here because this function is run in a
            # thread external to that of the main runtime.
            # Write the error to the error log.
            wiki_error_entry = "\n> {}\n\n".format(exc)
            wiki_error_entry += traceback.format_exc()
            main_error_log_(wiki_error_entry)
            logger.error('Wikipage Editor: Encountered an error on '
                         'r/{}: {}'.format(subreddit_name, wiki_error_entry))

        # If this is a newly added subreddit, send a message to the mods
        # to let them know that their statistics have been posted.
        if send_initial_message:
            initial_subject = ('[Notification] 📊 Community statistics for '
                               'r/{} have been posted!'.format(subreddit_name))
            initial_body = (MSG_MOD_STATISTICS_FIRST.format(subreddit_name)
                            + BOT_DISCLAIMER.format(subreddit_name))
            reddit.subreddit(subreddit_name).message(initial_subject, initial_body)
            logger.info('Wikipage Editor: Sent first wiki edit message '
                        'to r/{} mods.'.format(subreddit_name))

    # Clear the master statistics dictionary when completed.
    UPDATER_DICTIONARY.clear()
    logger.info("Wikipage Editor: COMPLETED editing ALL statistics "
                "wikipages and cleared data dictionary.")

    return


def wikipage_userflair_editor(subreddit_list):
    """This function is run secondarily as a process that needs no
    database access and goes through a given list of subreddits,
    tabulates their userflair statistics, and then edits the wikipage
    with the new information. This is run monthly at the start of the
    month.

    :param subreddit_list: A list of subreddit names as strings to
                           check and edit.
    :return: None.
    """
    current_time = int(time.time())
    month = date_month_convert_to_string(current_time)

    for community in list(sorted(subreddit_list)):

        # Check mod permissions; if I am not a mod, skip this.
        # If I have the `flair` mod permission, get the data for the
        # subreddit.
        perms = main_obtain_mod_permissions(community)
        if not perms[0]:
            continue
        elif 'flair' in perms[1] or 'all' in perms[1]:
            # Retrieve the data from the counter.
            # This will either return `None` if not available, or a
            # Markdown segment for integration.
            userflair_section = subreddit_userflair_counter(community)

            # If the result is not None, there's valid data.
            if userflair_section is not None:
                logger.info('Wikipage Userflair Editor: Now updating '
                            'r/{} userflair statistics.'.format(community))
                stats_page = reddit.subreddit(community).wiki["{}_statistics".format(USERNAME)]
                stats_page_existing = stats_page.content_md

                # If there's no preexisting section for userflairs, add
                # to the existing statistics. Otherwise, remove the old
                # section and replace it.
                if '## Userflairs' not in stats_page_existing:
                    new_text = stats_page_existing + userflair_section
                else:
                    stats_page_existing = stats_page_existing.split('## Userflairs')[0].strip()
                    new_text = stats_page_existing + userflair_section

                # Edit the actual page with the updated data.
                stats_page.edit(content=new_text,
                                reason='Updating with userflair data for {}.'.format(month))

    logger.info('Wikipage Userflair Editor: '
                'Completed userflair update in {:.2f}s.'.format(time.time() - current_time))

    return


def wikipage_status_collater(subreddit_name):
    """This function generates a Markdown chunk of text to include in
    the edited wikipage. The chunk notes the various settings of
    Artemis. This chunk is placed in the header of the edited wikipage.

    There are also sections in this function that account for situations
    where a subreddit may not actually be monitored - that is, it's
    done as part of a `start` test locally.

    :param subreddit_name: The name of a monitored subreddit.
    :return: A Markdown chunk that serves as the header.
    """
    absent = "N/A"
    ext_data = database_extended_retrieve(subreddit_name)
    # Fix for manual initialization tests which will have no
    # extended data due to the fact that a sub won't be monitored.
    if ext_data is None:
        ext_data = {}

    # Get the date as YYYY-MM-DD.
    current_time = int(time.time())
    current_day = date_convert_to_string(current_time)

    # Get flair enforcing status.
    flair_enforce_status = "**Flair Enforcing**: {}"
    current_status = database_monitored_subreddits_enforce_status(subreddit_name)

    # Format the section that contains the subreddit's flair enforcing
    # mode for inclusion.
    if current_status:
        flair_enforce_status = flair_enforce_status.format("`On`")

        # Get flair enforcing default/strict status (basically, does it
        # have the `posts` moderator permission?)
        flair_enforce_mode = "\n\n* Flair Enforcing Mode: `{}`"
        mode_type = database_monitored_subreddits_enforce_mode(subreddit_name)
        flair_enforce_status += flair_enforce_mode.format(mode_type)
    else:
        flair_enforce_status = flair_enforce_status.format("`Off`")

    # Get the day the subreddit added this bot.
    if 'added_utc' in ext_data:
        added_date = date_convert_to_string(ext_data['added_utc'])
    else:
        added_date = absent
    added_since = "**Artemis Added**: {}".format(added_date)

    # We get the earliest day we have statistics data for. (this gives
    # us an idea of how long we've monitored)
    statistics_data_since = "**Statistics Recorded Since**: {}"
    results = database_statistics_posts_retrieve(subreddit_name)

    # Get the date the subreddit was created.
    if 'created_utc' in ext_data:
        created_string = date_convert_to_string(ext_data['created_utc'])
    else:
        created_string = date_convert_to_string(reddit.subreddit(subreddit_name).created_utc)
    created_since = "**Subreddit Created**: {}".format(created_string)

    # If we don't have results, we must have just started monitoring
    # this sub, so set the date today. Otherwise, retrieve the oldest
    # date we have recorded. If there are no statistics data recorded
    # at all, then return "N/A", because in any case it's likely that
    # the subreddit is too small for statistics anyway.
    if results is None:
        statistics_data_since = statistics_data_since.format(current_day)
    else:
        dates = list(sorted(results.keys()))
        if dates:
            earliest_date = dates[0]  # The earliest date on the list.
        else:
            earliest_date = absent
        statistics_data_since = statistics_data_since.format(earliest_date)

    # Get the activity index (the place of the subreddit relative to
    # the others).
    currently_monitored = database_monitored_subreddits_retrieve()
    try:
        index_num = "#{}/{}".format(currently_monitored.index(subreddit_name) + 1,
                                    len(currently_monitored))
    except ValueError:
        # The subreddit is not monitored and thus has no index. This
        # error only comes when testing non-monitored subreddits.
        index_num = absent
    created_since += "\n\n**Subreddit Index**: `{}`".format(index_num)

    # Get the Markdown table of actions Artemis has performed if
    # available and add it to the section.
    actions_section = main_counter_collater(subreddit_name)
    if actions_section is not None:
        created_since += actions_section

    # Compile it together.
    status_chunk = "{}\n\n{}\n\n{}\n\n{}".format(flair_enforce_status,
                                                 added_since,
                                                 statistics_data_since,
                                                 created_since)
    logger.debug(("Status Collater: Compiled status settings for r/{}.".format(subreddit_name)))

    return status_chunk


def wikipage_compare_bots():
    """This function is very simple - it just looks at a few other bots
    and returns how many subreddits they each moderate, and as a
    percentage of Artemis's PUBLIC total. This is part of a project
    for r/Bot to document the growth of moderation bots on Reddit.
    This list is hosted on a wiki page along with the dashboard.

    :return: A Markdown table comparing Artemis's number of moderated
             subreddits with others.
    """
    bot_list = list(BOTS_COMPARED)
    bot_list.append(USERNAME.lower())
    bot_dictionary = {}
    formatted_lines = []

    # Access the moderated subreddits for each bot in JSON data and
    # count how many subreddits are there.
    for username in bot_list:
        my_data = subreddit_public_moderated(username)
        bot_dictionary[username] = (my_data['total'], my_data['list'])

    # Access the moderated subreddits for those in TheSentinelBot
    # network and combine them together in one entry.
    sentinel_list = ['TheSentinel_0', 'TheSentinel_1', 'TheSentinel_2', 'TheSentinel_3',
                     'TheSentinel_4', 'TheSentinel_6', 'TheSentinel_7', 'TheSentinel_8',
                     'TheSentinel_09', 'TheSentinel_10', 'TheSentinel_11', 'thesentinel_12',
                     'TheSentinel_13', 'TheSentinel_14', 'TheSentinel_15', 'TheSentinel_16',
                     'TheSentinel_17', 'TheSentinel_18', 'TheSentinel_19', 'TheSentinel_20',
                     'TheSentinel_30', 'YT_Killer', 'thesentinelbot']
    sentinel_mod_list = []
    for instance in sentinel_list:
        my_list = subreddit_public_moderated(instance)['list']
        sentinel_mod_list += my_list

    # Remove duplicate subreddits on this list.
    sentinel_mod_list = list(set(sentinel_mod_list))
    sentinel_count = len(sentinel_mod_list)
    bot_dictionary[sentinel_list[-1]] = (sentinel_count, sentinel_mod_list)

    # Look at Artemis's modded subreddits and process through all the
    # data as well.
    my_public_monitored = bot_dictionary[USERNAME.lower()][1]
    header = ("\n\n### Comparative Data\n\n"
              "| Bot | # Subreddits (Public) | Percentage | # Overlap |\n"
              "|-----|-----------------------|------------|-----------|\n")

    # Sort through the usernames alphabetically.
    for username in sorted(bot_dictionary.keys()):
        num_subs = bot_dictionary[username][0]
        list_subs = bot_dictionary[username][1]

        # Format the entries appropriately.
        if username != USERNAME.lower():
            percentage = num_subs / bot_dictionary[USERNAME.lower()][0]

            # Also calculate the number of subreddits that overlap.
            overlap = [value for value in my_public_monitored if value in list_subs]
            overlap_num = len(overlap)
            line = "| u/{} | {:,} | {:.0%} | {} |".format(username, num_subs, percentage,
                                                          overlap_num)
        else:
            line = "| u/{} | {:,} | --- | --- |".format(username, num_subs)
        formatted_lines.append(line)

    # Format everything together.
    body = header + '\n'.join(formatted_lines)

    return body


def wikipage_get_all_actions():
    """This function sums up all the actions cumulatively that Artemis
    has ever done.

    :return: A Markdown table detailing all those actions.
    """
    formatted_lines = []
    CURSOR_DATA.execute('SELECT * FROM subreddit_actions')
    results = CURSOR_DATA.fetchall()

    # Get a list of the action keys, and then create a dictionary with
    # each value set to zero.
    all_keys = list(set().union(*[ast.literal_eval(x[1]) for x in results]))
    main_dictionary = dict.fromkeys(all_keys, 0)

    # Iterate over each community.
    for community in results:
        main_actions = ast.literal_eval(community[1])
        for action in main_dictionary.keys():
            if action in main_actions:
                main_dictionary[action] += main_actions[action]
    for key, value in sorted(main_dictionary.items()):
        formatted_lines.append("| {} | {:,} |".format(key, value))
    body = "\n\n### Total Actions\n\n| Action | Count |\n|--------|-------|\n"
    body += '\n'.join(formatted_lines)

    return body


def wikipage_dashboard_collater(run_time=2.00):
    """This function generates a Markdown table to serve as a
    "dashboard" with links to the wikis that Artemis edits.
    This information is updated on a wikipage on r/translatorBOT to
    serve as a easy center for trouble-shooting.

    :param run_time: The float length (in minutes) it took to process
                     everything. Default is just two minutes.
    :return: A Markdown table for inclusion.
    """
    formatted_lines = []
    total_subscribers = []
    addition_dates = {}
    created_dates = {}
    index = {}
    index_num = 1
    advanced = {}
    advanced_num = 0
    template = ("| r/{0} | {1} | {2} | {3} | {4} |"
                "[Statistics](https://www.reddit.com/r/{0}/wiki/assistantbot_statistics) | {5} | "
                "[Traffic](https://www.reddit.com/r/{0}/about/traffic/) | "
                "[Moderators](https://www.reddit.com/r/{0}/about/moderators) |")

    # Get the list of monitored subs and alphabetize it.
    list_of_subs = database_monitored_subreddits_retrieve()
    list_of_subs.sort()

    # Access my database to get the addition and created dates for
    # monitored subreddits.
    CURSOR_DATA.execute("SELECT * FROM monitored")
    results = CURSOR_DATA.fetchall()
    for line in results:
        community = line[0]
        extended_data = ast.literal_eval(line[2])
        index[community] = index_num
        index_num += 1
        addition_dates[community] = date_convert_to_string(extended_data['added_utc'])
        created_dates[community] = date_convert_to_string(extended_data['created_utc'])
        if 'custom_name' in extended_data:
            config_line = "[Config](https://www.reddit.com/r/{}/wiki/assistantbot_config)"
            advanced[community] = config_line.format(community)
            advanced_num += 1
        else:
            advanced[community] = "---"

    # Iterate over our monitored subreddits.
    for subreddit in list_of_subs:
        # Access the database and create table rows where the subreddit
        # and subscribers are included.
        result = database_last_subscriber_count(subreddit)
        if result is not None:
            last_subscribers = result
        else:  # We couldn't find anything.
            last_subscribers = 0

        # Format the lines.
        formatted_lines.append(template.format(subreddit, last_subscribers, index[subreddit],
                                               created_dates[subreddit], addition_dates[subreddit],
                                               advanced[subreddit]))
        total_subscribers.append(last_subscribers)

    # Format the main body and the table's footer.
    header = ("# Artemis Dashboard ([Config]"
              "(https://www.reddit.com/r/translatorBOT/wiki/artemis_config))\n\n"
              "### Monitored Subreddits\n\n"
              "| Subreddit | # Subscribers | # Index | Created | Added | "
              "Statistics | Config | Moderators | Traffic |\n"
              "|-----------|---------------|---------|---------|-------|"
              "------------|--------|------------|---------|\n")
    footer = "\n| **Total** | {:,} | {:,} communities|".format(sum(total_subscribers),
                                                               len(list_of_subs))
    body = header + "\n".join(formatted_lines) + footer

    # Note down how long it took and tabulate some overall data.
    num_of_enforced_subs = len(database_monitored_subreddits_retrieve(True))
    num_of_stats_enabled_subs = len([x for x in total_subscribers if x >= MINIMUM_SUBSCRIBERS])
    percentage_enforced = num_of_enforced_subs / len(list_of_subs)
    percentage_gathered = num_of_stats_enabled_subs / len(list_of_subs)
    average_subscribers = int(sum(total_subscribers) / len(total_subscribers))
    body += ("\n\n* **Average number of subscribers per subreddit:** {:,} subscribers."
             "\n* **Flair enforcing active on:** {:,} subreddits ({:.0%})."
             "\n* **Statistics gathering active on:** {:,} subreddits ({:.0%})."
             "\n* **Advanced configuration active on:** {:,} subreddits."
             "\n* **Process run time**: {:.2f} minutes. {} {}")
    body = body.format(average_subscribers, num_of_enforced_subs, percentage_enforced,
                       num_of_stats_enabled_subs, percentage_gathered, advanced_num, run_time,
                       wikipage_get_all_actions(), wikipage_compare_bots())

    # Access the dashboard wikipage and update it with the information.
    dashboard = reddit.subreddit('translatorBOT').wiki['artemis']
    dashboard.edit(content=body,
                   reason='Updating dashboard for {}.'.format(date_convert_to_string(time.time())))
    logger.info('Dashboard: Updated the overall dashboard.')

    return


"""WIDGET UPDATING FUNCTIONS"""


def widget_updater(action_data):
    """This function updates three widgets on r/AssistantBOT.
    The first one tells the date for the most recent completed
    statistics, given a green background. It also includes a count of
    how many public subreddits the bot assists.
    The second is a table of public statistics pages. This runs in a
    secondary thread in the background separately from the main one.
    The third is a table of cumulative actions undertaken by the bot.

    :param action_data: A string of actions data passed for updating.
    :return: `None`, but widgets are edited.
    """
    # Get the list of public subreddits that are moderated.
    subreddit_list = subreddit_public_moderated(USERNAME)['list']

    # Search for the relevant status and table widgets for editing.
    status_id = 'widget_13xm3fwr0w9mu'
    status_widget = None
    table_id = 'widget_13xztx496z34h'
    table_widget = None
    actions_id = 'widget_14159zz24snay'
    action_widget = None

    # Assign the widgets to our variables.
    for widget in reddit.subreddit(USERNAME).widgets.sidebar:
        if isinstance(widget, praw.models.TextArea):
            if widget.id == status_id:
                status_widget = widget
            elif widget.id == table_id:
                table_widget = widget
            elif widget.id == actions_id:
                action_widget = widget

    # If we are unable to access either widget, return.
    if status_widget is None or table_widget is None or action_widget is None:
        return

    # Edit the status widget. Change it to a color green, indicating
    # everything's updated.
    status_template = ('### Statistics have been updated for:\n\n'
                       '# 🗓️ **{}** [UTC](https://time.is/UTC)\n\n'
                       '### Assisting {} public subreddits')
    status = status_template.format(date_convert_to_string(time.time()), len(subreddit_list))
    status_widget.mod.update(text=status, styles={'backgroundColor': '#349e48',
                                                  'headerColor': '#222222'})
    logger.debug('Widget Updater: Updated the status widget.')

    # Access subreddits to check for public wiki pages, using
    # ArtemisHelper. We try and get the text of the page, which will
    # fail if the page does NOT exist or is inaccessible.
    formatted_lines = []
    line = "| r/{0}{1} | **[Link](https://www.reddit.com/r/{0}/wiki/assistantbot_statistics)** |"
    for subreddit in list(sorted(subreddit_list, key=str.lower)):
        sub = reddit_helper.subreddit(subreddit)
        try:
            stats_test = sub.wiki['assistantbot_statistics'].content_md
        except (prawcore.exceptions.NotFound, prawcore.exceptions.Forbidden):
            continue

        if stats_test:
            logger.debug('Widget Updater: The statistics page for r/{} is public.'.format(sub))
            if sub.over18:  # Add an NSFW warning.
                formatted_lines.append(line.format(sub.display_name, ' (NSFW)'))
            else:
                formatted_lines.append(line.format(sub.display_name, ''))

    # Combine the text of the table into a single chunk and edit the
    # table widget with the text.
    body = ("**{} subreddits** have made their statistics pages generated by Artemis "
            "available to the public:\n\n"
            "| Subreddit | Statistics Page |\n|-----------|-----------------|\n{}")
    body = body.format(len(formatted_lines), "\n".join(formatted_lines))
    table_widget.mod.update(text=body)
    logger.debug('Widget Updater: Updated the table widget.')

    # Update the actions widget.
    actions_table = action_data.split('\n\n')[2].strip()
    action_widget.mod.update(text=actions_table)
    logger.debug('Widget Updater: Updated the actions widget.')

    return


def widget_status_updater(index_num, list_amount, current_day, start_time):
    """A quick function that takes the number of the current place
    Artemis is working through a statistics cycle and updates a widget
    on r/AssistantBOT. In-progress widget updates are given an
    orange background.

    :param index_num: Artemis's current index in the cycle.
    :param list_amount: The total number of subreddits in the cycle.
    :param current_day: The current UTC day expressed as YYYY-MM-DD.
    :param start_time: The Unix time at which the cycle started.
    :return: `None`.
    """
    # Get the status widget.
    status_id = 'widget_13xm3fwr0w9mu'
    status_widget = None
    for widget in reddit.subreddit(USERNAME).widgets.sidebar:
        if isinstance(widget, praw.models.TextArea):
            if widget.id == status_id:
                status_widget = widget
                break

    # Exit if the status widget is inaccessible.
    if status_widget is None:
        return

    # Calculate how long it's taken per subreddit and estimate the time
    # remaining for the entire cycle.
    time_per_sub = (time.time() - start_time) / index_num
    remaining_secs = (list_amount - index_num) * time_per_sub
    remaining_time = str(datetime.timedelta(seconds=int(remaining_secs)))[:-3]

    # Format the text for inclusion in the updated widget and update it.
    status_template = ('### Statistics are being updated for:\n\n'
                       '# 🗓️ **{}** [UTC](https://time.is/UTC)\n\n'
                       '### The cycle is {:.2%} completed.\n\n'
                       '### Estimated time remaining: {}')
    percentage = index_num / list_amount
    status = status_template.format(current_day, percentage, remaining_time)
    status_widget.mod.update(text=status, styles={'backgroundColor': '#ffa500',
                                                  'headerColor': '#222222'})
    logger.debug("Widget Status Updater: Widget updated at {:.2%} completion.".format(percentage))

    return


def widget_comparison_updater():
    """This function updates a widget on r/Bot that has comparative data
    for various moderator bots on Reddit.

    :return: `None`.
    """
    # Search for the relevant status and table widgets for editing.
    comp_id = 'widget_1415da9pei8k2'
    comp_widget = None
    for widget in reddit.subreddit('bot').widgets.sidebar:
        if isinstance(widget, praw.models.TextArea):
            if widget.id == comp_id:
                comp_widget = widget
                break

    # Get the comparative data to save.
    edited_body = []
    my_text = wikipage_compare_bots().split('\n\n')[2].strip()
    for line in my_text.split('\n'):
        edited_body.append("|".join(line.split("|", 3)[:3]) + '|')
    final_text = '\n'.join(edited_body)

    # Edit the widget.
    if comp_widget is not None:
        comp_widget.mod.update(text=final_text)
        logger.debug("Widget Comparison Updater: Widget updated.")

    return


"""FLAIR ENFORCING FUNCTIONS"""


def flair_notifier(post_object, message_to_send):
    """This function takes a PRAW Submission object - that of a post
    that is missing flair - and messages its author about the missing
    flair. It lets them know that they should select a flair.

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
    extended_data = database_extended_retrieve(active_subreddit)
    name_to_use = extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
    if not name_to_use:
        name_to_use = "Artemis"

    # Format the message and send the message.
    disclaimer_to_use = BOT_DISCLAIMER.replace('Artemis', name_to_use).format(active_subreddit)
    message_body = message_to_send + disclaimer_to_use
    try:
        reddit.redditor(author).message(MSG_USER_FLAIR_SUBJECT.format(active_subreddit),
                                        message_body)
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
    CURSOR_DATA.execute("SELECT * FROM posts_filtered WHERE post_id = ?", (post_id,))
    result = CURSOR_DATA.fetchone()

    if result is None:  # ID has not been saved before. We can save it.
        CURSOR_DATA.execute("INSERT INTO posts_filtered VALUES (?, ?)",
                            (post_id, int(post_object.created_utc)))
        CONN_DATA.commit()
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
    for user in list_of_users:
        if flair_is_user_mod(user, submission_obj.subreddit.display_name):

            # Form the message to send to the moderator.
            alert = ("I removed this [unflaired post here]"
                     "(https://www.reddit.com{}).".format(submission_obj.permalink))
            if submission_obj.over_18:
                alert += " (Warning: This post is marked as NSFW)"
            alert += BOT_DISCLAIMER.format(submission_obj.display_name)

            # Send the message to the moderator, accounting for if there
            # is a username error.
            subject = '[Notification] Post on r/{} removed.'.format(submission_obj.display_name)
            try:
                reddit.redditor(user).message(subject=subject, message=alert)
                logger.info('Send Alert: Messaged u/{} on '
                            'r/{} about removal.'.format(user, submission_obj.display_name))
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
    ext_data = database_extended_retrieve(praw_submission.subreddit.display_name.lower())
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
    subject_dict = {"add": 'Added new subreddit: r/{}',
                    "remove": "Demodded from subreddit: r/{}",
                    "skip": "Skipped subreddit: r/{}",
                    "mention": "New item mentioning Artemis on r/{}"
                    }

    # If we have a matching subject type, send a message to the creator.
    if subject_type in subject_dict:
        reddit.redditor(CREATOR).message(subject=subject_dict[subject_type].format(subreddit_name),
                                         message=message)

    return


def messaging_flair_sanitizer(text_to_parse, change_case=True):
    """This is a small function that sanitizes the input from the user
    for flairs and from flair dictionaries' text in order to make them
    consistent. This includes removing extraneous characters,
    lower-casing and stripping, and removing Reddit and Unicode emoji.

    :param text_to_parse: The text we want to convert and clean up.
    :param change_case: Whether or not we want to change the
                        capitalization of the text. Generally we want to
                        change it if it's for a case-insensitive
                        situation like matching people's messages.
                        Otherwise, if we're just displaying the options
                        available, we *do not* want to change case.
    :return: The sanitized text.
    """
    # Here we REMOVE the brackets and characters that may be in post
    # flairs so that they can match.
    deleted_characters = ["[", "]", ">", "•"]
    for character in deleted_characters:
        if character in text_to_parse:
            text_to_parse = text_to_parse.replace(character, "")

    # Here we REPLACE some problematic characters that may cause
    # rendering issues, namely vertical pipes in tables.
    replaced_characters = {"|": "◦"}
    for character in replaced_characters:
        if character in text_to_parse:
            text_to_parse = text_to_parse.replace(character, replaced_characters[character])

    # Process the text further. If changing case is desired, change it.
    # In case people keep the Reddit emoji text in, delete it.
    text_to_parse = text_to_parse.strip()
    if change_case:
        text_to_parse = text_to_parse.lower()
    text_to_parse = re.sub(r':\S+:', '', text_to_parse)

    # Account for Unicode emoji by deleting them as well.
    # uFE0F is an invisible character marking emoji.
    reg = re.compile(u'[\U0001F300-\U0001F64F'
                     u'\U0001F680-\U0001F6FF'
                     u'\U0001F7E0-\U0001F7EF'
                     u'\U0001F900-\U0001FA9F'
                     u'\uFE0F\u2600-\u26FF\u2700-\u27BF]',
                     re.UNICODE)
    text_to_parse = reg.sub('', text_to_parse).strip()

    return text_to_parse


def messaging_parse_flair_response(subreddit_name, response_text):
    """This function looks at a user's response to determine if their
    response is a valid flair in the subreddit that they posted in.
    If it is a valid template, then the function returns a template ID.
    The template ID is long and looks like this:
    `c1503580-7c00-11e7-8b43-0e560b183184`

    :param subreddit_name: Name of a subreddit.
    :param response_text: The text that a user sent back as a response
                          to the message.
    :return: `None` if it does not match anything;
             a template ID otherwise.
    """
    # Process the response from the user to make it consistent.
    response_text = messaging_flair_sanitizer(response_text)

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
        formatted_key = messaging_flair_sanitizer(key)
        lowercased_flair_dict[formatted_key] = template_dict[key]

    # If we find the text that the user sent back in the templates, we
    # return the template ID.
    if response_text in lowercased_flair_dict:
        returned_template = lowercased_flair_dict[response_text]['id']
        logger.debug("Parse Response: > Found r/{} template: `{}`.".format(subreddit_name,
                                                                           returned_template))
    else:
        # No exact match found. Try one last effort.
        # Use fuzzy matching to determine the best match from the flair
        # dictionary. Returns as tuple `('FLAIR', INT)`
        # If the match is higher than or equal to 95, then assign that
        # to `returned_template`. Otherwise, `None`.
        best_match = process.extractOne(response_text, list(lowercased_flair_dict.keys()),
                                        scorer=fuzz.WRatio)
        if best_match[1] >= 95:  # We are very sure this is right.
            returned_template = lowercased_flair_dict[best_match[0]]['id']
            logger.info("Parse Response: > Fuzzed match for `{}`: `{}`".format(best_match[0],
                                                                               returned_template))
        else:
            returned_template = None

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
        if str(item.mod).lower() != USERNAME.lower():
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
        subject_line = "[Notification] 😊 "
        key_phrase = "Thanks for selecting"

        # The wording will vary based on the mode. In strict mode, we
        # add text noting that the post has been approved. In addition
        # if a mod flaired this, we want to change the text to indicate
        # that.
        if strict_mode:
            subject_line += "Your flaired post is approved on r/{}!".format(post_subreddit)
            approval_message = MSG_USER_FLAIR_APPROVAL_STRICT.format(post_subreddit)
            main_counter_updater(post_subreddit, 'Restored post')

            if mod_flaired:
                key_phrase = "It appears a mod has selected"
        else:
            # Otherwise, this is a Default mode post, so the post was
            # never removed and there is no need for an approval section
            # and instead the author is simply informed of the post's
            # assignment.
            subject_line += "Your post has been assigned a flair on r/{}!".format(post_subreddit)
            approval_message = ""
            main_counter_updater(subreddit_name, 'Flaired post')

        # See if there's a custom name or custom goodbye in the extended
        # data to use.
        extended_data = database_extended_retrieve(subreddit_name)
        name_to_use = extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
        if not name_to_use:
            name_to_use = "Artemis"
        bye_phrase = extended_data.get('custom_goodbye',
                                       random.choice(GOODBYE_PHRASES)).capitalize()
        if not bye_phrase:
            bye_phrase = "Have a good day"

        # Format the message together.
        body = MSG_USER_FLAIR_APPROVAL.format(post_author, key_phrase, post_permalink,
                                              approval_message, bye_phrase)
        body += BOT_DISCLAIMER.replace('Artemis', name_to_use).format(post_subreddit)

        # Send the message.
        reddit.redditor(post_author).message(subject_line, body)
        logger.info("Flair Checker: > Sent a message to u/{} about post `{}`.".format(post_author,
                                                                                      post_id))

        # Remove the post from database now that it's been flaired.
        database_delete_filtered_post(post_id)

    return


def messaging_example_collater(subreddit):
    """This is a simple function that takes in a PRAW subreddit OBJECT
    and then returns a Markdown chunk that is an example of the flair
    enforcement message that users get.

    :param subreddit: A PRAW subreddit *object*.
    :return: A Markdown-formatted string.
    """
    new_subreddit = subreddit.display_name.lower()
    stored_extended_data = database_extended_retrieve(new_subreddit)
    template_header = "*Here's an example flair enforcement message for r/{}:*"
    template_header = template_header.format(subreddit.display_name)
    sub_templates = subreddit_templates_collater(new_subreddit)
    current_permissions = main_obtain_mod_permissions(new_subreddit)

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

    # Check if there's a custom name and goodbye.
    name_to_use = stored_extended_data.get('custom_name', 'Artemis').replace(' ', ' ^')
    if not name_to_use:
        name_to_use = "Artemis"
    bye_phrase = stored_extended_data.get('custom_goodbye', "have a good day").lower()
    if not bye_phrase:  # If the phrase is an empty string.
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


"""MAIN FUNCTIONS"""


def main_error_log_(entry):
    """A function to save detailed errors to a log for later review.
    This is easier to check for issues than to search through the entire
    events log, and is based off of a basic version of the function
    used in Wenyuan/Ziwen.

    :param entry: The text we wish to include in the error log entry.
                  Typically this is the traceback entry.
    :return: Nothing.
    """

    # Open the file for the error log in appending mode.
    # Then add the error entry formatted our way.
    with open(FILE_ADDRESS_ERROR, 'a+', encoding='utf-8') as f:
        error_date_format = datetime.datetime.utcnow().strftime("%Y-%m-%dT%I:%M:%SZ")
        bot_format = "Artemis v{}".format(VERSION_NUMBER)
        f.write("\n---------------\n{} ({})\n{}".format(error_date_format, bot_format, entry))

    return


# noinspection PyGlobalUndefined,PyGlobalUndefined
def main_config_retriever():
    """This function retrieves data from a configuration page in order
    to help prevent abuse of Artemis. It also gets a chunk of text if
    present to serve as an announcement to be included on wikipages.
    For more on YAML syntax, please see:
    https://learn.getgrav.org/16/advanced/yaml

    :return: `None`.
    """
    global SUBREDDITS_OMIT
    global USERS_OMIT
    global ANNOUNCEMENT
    global BOTS_COMPARED

    # Access the configuration page on the wiki.
    target_page = reddit.subreddit('translatorBOT').wiki['artemis_config'].content_md
    config_data = yaml.safe_load(target_page)

    # Here are some basic variables to use, making sure everything is
    # lowercase for consistency.
    SUBREDDITS_OMIT = [x.lower().strip() for x in config_data['subreddits_excluded']]
    BOTS_COMPARED = [x.lower().strip() for x in config_data['bots_comparative']]
    USERS_OMIT = [x.lower().strip() for x in config_data['users_excluded']] + [CREATOR]

    # This is a custom phrase that can be included on all wiki pages as
    # an announcement from the bot creator.
    ANNOUNCEMENT = ""
    if 'announcement' in config_data:
        # Format it properly as a header with an emoji.
        if config_data['announcement'] is not None:
            ANNOUNCEMENT = "📢 *{}*".format(config_data['announcement'])

    return


def main_counter_updater(subreddit_name, action_type, action_count=1):
    """This function writes a certain number to an action log in the
    database to indicate how many times an action has been performed for
    a subreddit. For example, how many times posts have been removed,
    how many times posts have been restored, etc.

    :param subreddit_name: Name of a subreddit.
    :param action_type: The type of action that Artemis did.
                        Action types include:
                        * `Removed post` - a post removed by Artemis
                                           due to not having a flair.
                        * `Restored post` - a post restored by Artemis
                                            after it was given a flair
                                            and was removed.
                        * `Flaired post` - a post directly flaired by
                                           Artemis through messaging.
                        * `Statistics updated` - how many times the
                                                 statistics page was
                                                 updated (once a day).
    :param action_count: Defaults to 1, but can be changed if desired.
    :return: `None`.
    """
    # Make the name lowercase.
    subreddit_name = subreddit_name.lower()

    # Access the database to see if we have recorded actions for this
    # subreddit already.
    CURSOR_DATA.execute('SELECT * FROM subreddit_actions WHERE subreddit = ?', (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    if result is None:  # No actions data recorded. Create a new dictionary and save it.
        actions_dictionary = {action_type: action_count}
        data_package = (subreddit_name, str(actions_dictionary))
        CURSOR_DATA.execute('INSERT INTO subreddit_actions VALUES (?, ?)', data_package)
        CONN_DATA.commit()
    else:  # We already have an entry recorded for this.
        actions_dictionary = ast.literal_eval(result[1])  # Convert this back into a dictionary.
        # Check the data in the database. Update it if it exists,
        # otherwise create a new dictionary item.
        if action_type in actions_dictionary:
            actions_dictionary[action_type] += action_count
        else:
            actions_dictionary[action_type] = action_count

        # Update the existing data.
        update_command = "UPDATE subreddit_actions SET recorded_actions = ? WHERE subreddit = ?"
        CURSOR_DATA.execute(update_command, (str(actions_dictionary), subreddit_name))
        CONN_DATA.commit()

    return


def main_counter_collater(subreddit_name):
    """This function looks at the counter of actions that has been saved
    for the subreddit before and returns a Markdown table noting what
    actions were taken on the particular subreddit and how many of each.

    :param subreddit_name: Name of a subreddit.
    :return: A Markdown table if there is data, `None` otherwise.
    """
    formatted_lines = []

    # Access the database to get a subreddit's recorded actions.
    subreddit_name = subreddit_name.lower()
    CURSOR_DATA.execute('SELECT * FROM subreddit_actions WHERE subreddit = ?', (subreddit_name,))
    result = CURSOR_DATA.fetchone()

    if result is not None:
        # We have a result. The second part is the dictionary
        # containing the action data.
        action_data = ast.literal_eval(result[1])

        # Form the table lines, including both the action and the
        # number of times it was done.
        for action in sorted(action_data.keys()):
            line = "| {} | {:,} |".format(action, int(action_data[action]))
            formatted_lines.append(line)

        # If we have both the "Removed" and "Restored" posts actions,
        # we can calculate the percentage of flaired posts.
        # Make sure we don't divide by zero, however.
        # There is also an exception. If the restored percentage is
        # below ten percent, it's likely modes were switched in the
        # past and are thus not particularly valid.
        if 'Removed post' in action_data and 'Restored post' in action_data:
            if action_data['Removed post'] > 0:
                restored_percentage = (action_data['Restored post'] / action_data['Removed post'])
                restored_line = "| *% Removed posts flaired and restored* | *{:.2%}* |"
                restored_line = restored_line.format(restored_percentage)
                if restored_percentage > .1:
                    formatted_lines.append(restored_line)

        # If we have no lines to make a table, just return `None`.
        if len(formatted_lines) == 0:
            return None
        else:
            # Format the text content together.
            header = "\n\n| Actions | Count |\n|---------|-------|\n"
            body = header + '\n'.join(formatted_lines)

            return body

    return


def main_backup_daily():
    """This function backs up the database files to a secure Box account
    and a local target. It does not back up the credentials file or the
    main Artemis file itself. This is called by the master timer during
    its daily routine.

    :return: Nothing.
    """
    current_day = date_convert_to_string(time.time())

    # Iterate over the backup paths that are listed.
    for backup_path in [BACKUP_FOLDER, BACKUP_FOLDER_LOCAL]:
        if not os.path.isdir(backup_path):
            # If the web disk or the physical disk is not mounted,
            # record an error.
            logger.error("Main Backup: It appears that the backup disk "
                         "at {} is not mounted.".format(backup_path))
        else:
            # Mounted successfully. Create a new folder in the
            # YYYY-MM-DD format.
            new_folder_path = "{}/{}".format(backup_path, current_day)

            # If there already is a folder with today's date, do not
            # do anything. Otherwise, start the backup process.
            if os.path.isdir(new_folder_path):
                logger.info("Main Backup: Backup folder for {} "
                            "already exists at {}.".format(current_day, backup_path))
            else:
                # Create the new target folder and get the list of files
                # from the home folder.
                os.makedirs(new_folder_path)
                source_files = os.listdir(SOURCE_FOLDER)

                # We don't need to back up files with these file name
                # extensions. Exclude them from backup.
                xc = ['journal', '.json', '.out', '.py', '.yaml']
                source_files = [x for x in source_files if not any(keyword in x for keyword in xc)]

                # Iterate over each file and back it up.
                for file_name in source_files:

                    # Get the full path of the file.
                    full_file_name = os.path.join(SOURCE_FOLDER, file_name)

                    # If the file exists, try backing it up. If there
                    # happens to be a copying error, skip the file.
                    if os.path.isfile(full_file_name):
                        try:
                            shutil.copy(full_file_name, new_folder_path)
                        except OSError:
                            pass

                logger.info('Main Backup: Completed for {}.'.format(current_day))

    return


def main_maintenance_daily():
    """This function brings in two primary functions together:
    The backup function, which backs up files to Box, and the
    database_cleanup function, which truncates the database to fit
    with a certain length.

    This function is intended to be run *once* daily. It will insert an
    entry into `subreddit_updated` with the subreddit code 'all' and the
    date to indicate that the process has been completed.

    :return: `None`.
    """
    # Add an entry into the database so that Artemis knows it's already
    # completed the actions for the day.
    current_day = date_convert_to_string(time.time())
    CURSOR_DATA.execute("INSERT INTO subreddit_updated VALUES (?, ?)", ('all', current_day))
    CONN_DATA.commit()

    # Clean up the database and truncate the logs and processed posts.
    database_cleanup()

    # Back up the relevant files to Box.
    main_backup_daily()

    return


def main_maintenance_secondary():
    """This function brings together secondary functions that are NOT
    database-related and are run on a separate thread.

    :return: `None`.
    """
    # Refresh the configuration data.
    main_config_retriever()
    main_get_posts_frequency()

    # Check if there are any mentions and mark all modmail as read.
    main_obtain_mentions()
    main_read_modmail()
    widget_comparison_updater()

    return


# noinspection PyGlobalUndefined,PyGlobalUndefined
def main_login():
    """A simple function to log in and authenticate to Reddit. This
    declares a global `reddit` object for all other functions to work
    with. It also authenticates under a secondary regular account as a
    work-around to get only user-accessible flairs from the subreddits
    it moderates and from which to post if shadowbanned.

    :return: `None`, but global `reddit` and `reddit_helper` variables
             are declared.
    """
    # Declare the connections as global variables.
    global reddit
    global reddit_helper

    # Authenticate the main connection.
    user_agent = 'Artemis v{} (u/{}), a moderation assistant written by u/{}.'
    user_agent = user_agent.format(VERSION_NUMBER, USERNAME, CREATOR)
    reddit = praw.Reddit(client_id=ARTEMIS_INFO['app_id'],
                         client_secret=ARTEMIS_INFO['app_secret'],
                         password=ARTEMIS_INFO['password'],
                         user_agent=user_agent, username=USERNAME)
    logger.info("Startup: Logging in as u/{}.".format(USERNAME))

    # Authenticate the secondary helper connection.
    reddit_helper = praw.Reddit(client_id=ARTEMIS_INFO['helper_app_id'],
                                client_secret=ARTEMIS_INFO['helper_app_secret'],
                                password=ARTEMIS_INFO['helper_password'],
                                user_agent="{} Assistant".format(USERNAME),
                                username=ARTEMIS_INFO['helper_username'])

    # Access configuration data.
    main_config_retriever()
    main_get_posts_frequency()

    return


def main_timer(manual_start=False):
    """This function helps time certain routines to be done only at
    specific times or days of the month.
    ACTION_TIME: Defined above, usually at midnight UTC.
    Daily at midnight: Retrieve number of subscribers.
                       Record post statistics and post them to the wiki.
                       Backup the data files to Box.
    Xth day of every month: Retrieve subreddit traffic. We don't do this
                            on the first of the month because Reddit
                            frequently takes a few days to update
                            traffic statistics.

    :return: `None`.
    """
    # Define the times we want actions to take place, in order:
    # The day of the month to gather the top posts from the last month.
    # The amount of hours to allow for the statistics routine to run.
    top_action_day = 1
    action_window = 6
    cycle_position = 0

    # Get the time variables that we need.
    start_time = int(time.time())
    previous_date_string = date_convert_to_string(start_time - 86400)
    current_date_string = date_convert_to_string(start_time)
    current_hour = int(datetime.datetime.utcfromtimestamp(start_time).strftime('%H'))
    current_date_only = datetime.datetime.utcfromtimestamp(start_time).strftime('%d')

    # Check to see if the statistics activity has already been run.
    query = "SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?"
    CURSOR_DATA.execute(query, ('all', current_date_string))
    result = CURSOR_DATA.fetchone()

    # If we have already processed the actions for today, note that.
    if result is not None:
        all_stats_done = True
    else:
        all_stats_done = False

    # If we are outside the update window, exit. Otherwise, if a manual
    # update by the creator was not requested, and all statistics were
    # retrieved, also exit.
    if current_hour > (ACTION_TIME + action_window):
        return
    if all_stats_done and not manual_start:
        return
    '''
    Here we start a cycle. The cycles here basically make it so that
    while Artemis is gathering statistics it will check
    in on unflaired posts at certain intervals. It's simple - if the
    time elapsed is longer than the cycle's duration,
    Artemis will check for unflaired posts. This is to allow consistency
    in dealing with unflaired posts.
    '''
    # Get the list of all our monitored subreddits.
    # Check integrity first, make sure the subs to update are accurate.
    # This is done by comparing the local list to the online list.
    database_monitored_integrity_checker()
    monitored_list = database_monitored_subreddits_retrieve()

    # Start the first timer. This will be reset each cycle later.
    cycle_initialize_time = int(time.time())

    # Check the cache if we have saved data. If there is and dict is
    # blank (len 0), then load the dictionary from cache.
    # This is mostly in case of a crash during the statistics-gathering
    # period, so the bot can start where it left off.
    # This should *not* run the first time, because both the cache and
    # `UPDATER_DICTIONARY` should be len() == 0.
    CURSOR_DATA.execute("SELECT * FROM cache_statistics WHERE date = ?", (current_date_string,))
    results = CURSOR_DATA.fetchall()

    # If there's cached data from a current statistics run, create a
    # blank dictionary with our local data, and then index the
    # dictionary by sub, with the string data for each entry, and
    # finally update the dictionary with the existing values.
    # This is only used when the bot is recovering the cycle from a
    # crash since there will not be cached data under normal times.
    if len(results) != 0:
        existing_updater_dict = {}
        for result in results:
            existing_updater_dict[result[1]] = str(result[2])
        if len(existing_updater_dict) > 0 and len(UPDATER_DICTIONARY) == 0:
            logger.info('Main Timer: Reloading the blank updater dictionary from cache.')
            UPDATER_DICTIONARY.update(existing_updater_dict)

    # On a few specific days, run the userflair updating thread first in
    # order to not conflict with the main runtime.
    # This is currently set for 1st and 15th of each month, and more
    # specifically only in the first hour window.
    userflair_update_days = [top_action_day, top_action_day + 14]
    if int(current_date_only) in userflair_update_days and current_hour == ACTION_TIME:
        logger.info('Main Timer: Initializing a secondary thread for userflair updates.')
        userflair_check_list = []

        # Iterate over the subreddits, to see if they meet the minimum
        # amount of subscribers needed OR if they have manually opted in
        # to getting userflair statistics, or if they have opted out.
        for sub in monitored_list:
            if database_last_subscriber_count(sub) > MINIMUM_SUBSCRIBERS_USERFLAIR:
                userflair_check_list.append(sub)
                if 'userflair_statistics' in database_extended_retrieve(sub):
                    if not database_extended_retrieve(sub)['userflair_statistics']:
                        userflair_check_list.remove(sub)
            elif 'userflair_statistics' in database_extended_retrieve(sub):
                if database_extended_retrieve(sub)['userflair_statistics']:
                    userflair_check_list.append(sub)

        # Launch the secondary userflair updating thread as another
        # thread run concurrently.
        logger.info('Main Timer: Checking the following subreddits '
                    'for userflairs: {}'.format(userflair_check_list))
        userflair_thread = threading.Thread(target=wikipage_userflair_editor,
                                            kwargs=dict(subreddit_list=userflair_check_list))
        userflair_thread.start()

    # Update the status widget's initial position.
    widget_status_updater(.2, len(monitored_list), current_date_string, start_time)

    # This is the main part of gathering statistics.
    # Iterate over the communities we're monitoring, compile the
    # statistics and add to dictionary.
    for community in monitored_list:
        # We do a quick check to see if it's time to make a new cycle
        # and check for new submissions.
        cycle_current_time = int(time.time())
        cycle_position += 1

        # If the cycle time is exceeded, save the dictionary to cache
        # and do a quick pull for new submissions.
        if cycle_current_time - cycle_initialize_time > (MINIMUM_AGE_TO_MONITOR * 1.5):
            # Reset the initialize time and save the current state of
            # the updater dictionary to cache.
            logger.info('Main Timer: Cycle RESET started.\n')

            # The following part is to save the data to cache so it can
            # be resumed in case of an error.
            logger.info('Main Timer: Updating current updater dictionary state in cache...')

            # Generate a unique index if it doesn't exist to avoid
            # creating more than one entry per date.
            CURSOR_DATA.execute("CREATE UNIQUE INDEX IF NOT EXISTS subreddit_index "
                                "ON cache_statistics (subreddit)")
            CONN_DATA.commit()

            # Get a list of the currently stored subreddits so we don't
            # overwrite them, and check the list of subreddits who
            # already have data saved and do not save their data too.
            package = (current_date_string,)
            CURSOR_DATA.execute("SELECT * FROM cache_statistics WHERE date = ?", package)
            results = CURSOR_DATA.fetchall()
            already_saved = [x[1] for x in results]

            # Iterate over the subreddits which have unsaved data, and
            # save their data. Indexed by key.
            for unsaved in UPDATER_DICTIONARY.keys() - already_saved:
                # Replace into the cache database. This will change the
                # information to the most up-to-date version.
                replace = (current_date_string, unsaved, str(UPDATER_DICTIONARY[unsaved]))
                c = 'REPLACE INTO cache_statistics (date, subreddit, stored_data) VALUES (?, ? ,?)'
                CURSOR_DATA.execute(c, replace)
                CONN_DATA.commit()
                logger.debug('Main Timer: Cached r/{} statistics '
                             'for {}.'.format(unsaved, current_date_string))

            # Update the status widget.
            widget_status_updater(cycle_position, len(monitored_list), current_date_string,
                                  start_time)

            # Check for unflaired submissions, or submissions that have
            # now been flaired. This is essentially a cycle within a
            # cycle. If this is a manual check for statistics, however,
            # we don't want to have recursion and call the messaging
            # system from within itself.
            logger.info('Main Timer: Fetching submissions...')
            if not manual_start:
                main_messaging(check_for_invites=False)
            main_get_submissions()
            main_flair_checker()

            # Finally, reset the start time.
            cycle_initialize_time = int(time.time())
            logger.info('Main Timer: Cycle RESET complete. Submissions fetched.\n')

        # Check to see if we have acted upon this subreddit for today
        # and already have its statistics.
        act_command = 'SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?'
        CURSOR_DATA.execute(act_command, (community, current_date_string))
        if CURSOR_DATA.fetchone():
            # We have already updated this subreddit for today.
            logger.debug("Main Timer: Statistics already updated for r/{}".format(community))
            continue

        # Begin the update, and insert an entry into the database so we
        # know it's done. Also fetch what number this community is in
        # the overall process (its index number) so that the progress
        # can be measured as it goes along.
        community_place = monitored_list.index(community) + 1
        logger.info("Main Timer: BEGINNING r/{} (#{}/{}).".format(community, community_place,
                                                                  len(monitored_list)))
        CURSOR_DATA.execute("INSERT INTO subreddit_updated VALUES (?, ?)", (community,
                                                                            current_date_string))
        CONN_DATA.commit()

        # If it's a certain day of the month, also get the traffic data
        # and update the user flairs in a new thread.
        if int(current_date_only) == MONTH_ACTION_DAY:
            subreddit_traffic_recorder(community)

        # SKIP CHECK: See if a subreddit either
        #   a) has enough subscribers, or
        #   b) isn't frozen.
        # Check to see how many subscribers the subreddit has.
        # If it is below minimum, skip but record the subscriber
        # count so that we could resume statistics gathering
        # automatically once it passes that minimum.
        subreddit_current_sub_count = database_last_subscriber_count(community)
        ext_data = database_extended_retrieve(community)
        if ext_data is not None:
            freeze = database_extended_retrieve(community).get('freeze', False)
        else:
            logger.info('Main Timer: r/{} has no extended data. '
                        'Statistics frozen.'.format(community))
            freeze = True

        # If there are too few subscribers to record statistics,
        # or the statistics status is frozen, record the number of
        # subscribers and continue without recording statistics.
        if subreddit_current_sub_count < MINIMUM_SUBSCRIBERS or freeze:
            subreddit_subscribers_recorder(community)
            logger.info('Main Timer: COMPLETED: r/{} below minimum or frozen. '
                        'Recorded subscribers.'.format(community))
            continue

        # If it's a certain day of the month (the first), also get the
        # top posts from the last month and save them.
        if int(current_date_only) == top_action_day:
            last_month_dt = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
            last_month_string = last_month_dt.strftime("%Y-%m")
            subreddit_top_collater(community, last_month_string, last_month_mode=True)

        # Update the number of subscribers and get the statistics for
        # the previous day.
        subreddit_subscribers_recorder(community)
        subreddit_statistics_recorder_daily(community, previous_date_string)

        # Compile the post statistics text and add it to our dictionary.
        if community not in UPDATER_DICTIONARY:
            UPDATER_DICTIONARY[community] = wikipage_collater(community)
            logger.info("Main Timer: Compiled statistics wikipage for r/{}.".format(community))

        # Update the counter, as all processes are done for this sub.
        logger.info("Main Timer: COMPLETED daily collation for r/{}.".format(community))
        main_counter_updater(community, 'Updated statistics')

    # Here we have done everything in terms of statistics gathering.
    # Now we need to start editing those wiki pages.  If the dictionary
    # to update is not empty, update the wiki pages.
    #
    # Initialize a secondary writing thread to update wiki pages
    # separately. We pass arguments according to this:
    # http://blog.acipo.com/python-threading-arguments/
    if len(UPDATER_DICTIONARY) != 0:
        # Start the secondary wiki updating thread.
        writing_thread = threading.Thread(target=wikipage_editor,
                                          kwargs=dict(subreddit_dictionary=UPDATER_DICTIONARY))
        writing_thread.start()

        # Clear the cached statistics data for the day as we don't
        # need it anymore.
        CURSOR_DATA.execute('DELETE FROM cache_statistics WHERE date = ?', (current_date_string,))
        CONN_DATA.commit()
        logger.info('Main Timer: Cleared statistics cache '
                    'for date {}.'.format(current_date_string))

    # Recheck for oldest submissions once a month for those subreddits
    # that lack them.
    if int(current_date_only) == top_action_day:
        main_recheck_oldest()

    # If we are deployed on Linux (Raspberry Pi), also run other
    # routines. These will not run on non-live platforms.
    if sys.platform == "linux":
        # We have not performed the main actions for today yet.
        # Run the backup and cleanup routines, and update the
        # configuration data in a parallel thread.
        # `main_maintenance_daily` also inserts `all` into the
        # database to tell it's done with statistics.
        secondary_thread = threading.Thread(target=main_maintenance_secondary)
        secondary_thread.start()
        main_maintenance_daily()

        # Mark down the total process time in minutes.
        end_process_time = time.time()
        elapsed_process_time = (end_process_time - start_time) / 60

        # Update the dashboard and finalize the widgets in the sidebar.
        wikipage_dashboard_collater(run_time=elapsed_process_time)
        action_data = wikipage_get_all_actions()
        widget_thread = threading.Thread(target=widget_updater,
                                         args=(action_data,))
        widget_thread.start()

    return


def main_initialization(subreddit_name, create_wiki=True):
    """This is a function that is called when a moderator invite is
    accepted for the first time.
    It fetches the traffic data, the subscriber data, and also tries to
    get all the statistics that it can into the database. This process
    may take a while as Artemis will try to get the last 1000 posts
    allowed by the API into its database.

    :param subreddit_name: Name of a subreddit.
    :param create_wiki: Whether or not we want to create a wikipage for
                        this subreddit.
                        For example, a manual initialization would not
                        require the wikipage to be set up.
    :return: Nothing.
    """
    # Get post statistics for the subreddit, as far back as we
    # can (about 1000 posts).
    subreddit_statistics_retrieve_all(subreddit_name)

    # Get the traffic data that is stored on the subreddit.
    # Typically this is the eleven months prior to the current one.
    subreddit_traffic_recorder(subreddit_name)

    # Get the subscriber data via three different functions.
    # The first function gets subscriber data for the current moment.
    # Next, it retrieves data from RedditMetrics.
    # Finally, it gets historical subscriber numbers from Pushshift.
    subreddit_subscribers_recorder(subreddit_name, check_pushshift=True)
    subreddit_subscribers_redditmetrics_historical_recorder(subreddit_name)
    subreddit_subscribers_pushshift_historical_recorder(subreddit_name)

    # Create the wikipage for statistics with a default message.
    if create_wiki:
        wikipage_creator(subreddit_name)
    logger.info('Initialization: Initialized data for r/{}.'.format(subreddit_name))

    return


def main_obtain_mod_permissions(subreddit_name):
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
    r = reddit.subreddit(subreddit_name)
    moderators_list = [mod.name.lower() for mod in r.moderator()]
    am_mod = True if USERNAME.lower() in moderators_list else False

    if not am_mod:
        my_perms = None
    else:
        me_as_mod = [x for x in r.moderator(USERNAME) if x.name == USERNAME][0]

        # The permissions I have become a list. e.g. `['wiki']`
        my_perms = me_as_mod.mod_permissions

    return am_mod, my_perms


def main_read_modmail():
    """The purpose of this function is to simply mark as read the
    modmail on the subreddits it has access to. It does not need to use
    the database so it is run in a separate secondary thread.

    :return: `None`.
    """
    all_subs = {}
    list_with_modmail = []

    # Get the list of all monitored subreddits (this is NOT database
    # dependent). For each fetch the real name of the subreddit, and the
    # fullname ID of the subreddit, prefixed with `t5_`.
    returned_data = reddit.get('/user/{}/moderated_subreddits'.format(USERNAME))['data']
    for item in returned_data:
        modded_sub = item['sr'].lower()
        all_subs[modded_sub] = item['name'].lower()  # Fullname.

    # Fetch the subreddits we have modmail access to, convert them to
    # PRAW objects, and append to a list.
    for subreddit in all_subs.keys():
        if any(x in main_obtain_mod_permissions(subreddit)[1] for x in ['mail', 'all']):
            list_with_modmail.append(all_subs[subreddit])
    list_with_modmail = list(reddit.info(fullnames=list_with_modmail))
    logger.info('Read Modmail: Modmail perms on {} subreddits. '
                'Marking as read.'.format(len(list_with_modmail)))

    # Now I mark the modmail conversations as read, going through each
    # subreddit individually.
    for subreddit in list_with_modmail:
        try:
            subreddit.modmail.bulk_read(state='all')
        except prawcore.exceptions.Forbidden:
            continue

    return


def main_recheck_oldest():
    """Sometimes, a subreddit is too new when it's added to my monitored
    list, and consequently there's no oldest posts since it's empty.
    This function is run every month on the subreddits for which we have
    *no* oldest data for to check and see if we can update the
    oldest data for them.

    Note that this only checks `public` subreddits to see if there are
    new oldest posts to save, not private ones as private subreddits are
    usually for testing purposes only, and in any case Pushshift has no
    ability to see posts on private subreddits.

    :return: `None`.
    """
    # We check public subreddits to see if we can get new data about
    # their oldest posts.
    for community in database_monitored_subreddits_retrieve():
        # Check to see if there's saved data. If there isn't it'll be
        # returned as `None`.
        result = database_activity_retrieve(community, 'oldest', 'oldest')

        # If there's no saved oldest data, check first if it's private.
        # If it's not, recheck and save the data if applicable.
        if result is None:

            if reddit.subreddit(community).subreddit_type != 'private':
                logger.info("Recheck Oldest: Rechecking oldest stats for r/{}.".format(community))
                subreddit_pushshift_oldest_retriever(community)

    return


def main_obtain_mentions():
    """The purpose of this function is to check and see if Artemis is
    mentioned in a post/comment somewhere on Reddit. This function
    conducts a quick search on Reddit and if it finds a new mention it
    sends the link to my creator.
    It does not require any usage of the local database since it will
    check the `saved` status instead to see if the post/comment has
    already been processed.

    :return: `None`.
    """
    full_dictionary = {}
    message_template = "View it **[here]({})**."

    # Run a regular Reddit search for posts mentioning this bot.
    # If a post is not saved, it means we haven't acted upon it yet.
    query = "{0} OR url:{0} OR selftext:{0} NOT author:{1} NOT author:{0}".format(USERNAME.lower(),
                                                                                  CREATOR)
    for submission in reddit.subreddit('all').search(query, sort='new', time_filter='week'):
        if not submission.saved:
            full_dictionary[submission.id] = (submission.subreddit.display_name,
                                              message_template.format(submission.permalink))
            submission.save()
            logger.info('Obtain Mentions: Found new post `{}` with mention.'.format(submission.id))

    # Run a Pushshift search for comments mentioning this bot.
    comment_query = ("https://api.pushshift.io/reddit/search/comment/?q=assistantbot"
                     "&fields=subreddit,id,author&size=10")
    retrieved_data = subreddit_pushshift_access(comment_query)

    # We have comments. Iterate through them.
    # Note that username mentions should already be saved in the
    # messaging function.
    if 'data' in retrieved_data:
        returned_comments = retrieved_data['data']
        for comment_info in returned_comments:
            if comment_info['author'].lower() in USERS_OMIT:
                continue
            comment = reddit.comment(id=comment_info['id'])  # Convert into PRAW object.
            try:
                if not comment.saved:  # Don't process saved comments.
                    full_dictionary[comment.id] = (comment.subreddit.display_name,
                                                   message_template.format(comment.permalink))
                    logger.debug('Obtain Mentions: Found new `{}` mention.'.format(comment.id))
                    comment.save()
            except praw.exceptions.ClientException:  # Comment is not accessible to me.
                continue

    # Send the retrieved mentions information to my creator,
    # if there are any.
    if len(full_dictionary) > 0:
        for key, value in full_dictionary.items():
            messaging_send_creator(value[0], "mention", value[1])
            logger.info('Obtain Mentions: Sent my creator a message about item `{}`.'.format(key))

    return


def main_post_approval(submission, template_id=None):
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
    if int(time.time()) - created > MAXIMUM_AGE_TO_MONITOR:
        logger.info('Post Approval: Post `{}` is 24+ hours old.'.format(post_id))
        can_process = False

    # Check to see if the moderator who removed it is Artemis.
    # We don't want to override other mods.
    if moderator_removed is not None:
        if moderator_removed != USERNAME:
            # The moderator who removed this is not me. Don't restore.
            logger.debug('Post Approval: Post `{}` removed by mod u/{}.'.format(post_id,
                                                                                moderator_removed))
            can_process = False

    # Check the number of reports existing on it. If there are some,
    # do not approve it. The number seems to be positive if the reports
    # are still present and the post has not been approved by a mod;
    # otherwise they will be negative.
    if num_reports is not None:
        if num_reports <= -4:
            logger.info('Post Approval: Post `{}` has {} reports.'.format(post_id, num_reports))
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
        can_process = False

    # Run a check for the boolean `can_process`. If it's `False`,
    # delete the post ID from our database. This is done a little
    # earlier so that a call to grab mod permissions does not need to be
    # done if the post is not eligible for processing anyway.
    if not can_process:
        database_delete_filtered_post(post_id)
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
    current_permissions = main_obtain_mod_permissions(post_subreddit)
    if not current_permissions[0]:
        return False
    else:
        # Collect the permissions as a list.
        current_permissions = current_permissions[1]

    # Get the extended data to see if I can approve the
    # post, then check extended data for whether or
    # not I should approve posts directly.
    # By default, we will be allowed to approve posts.
    relevant_ext_data = database_extended_retrieve(post_subreddit)
    approve_perm = relevant_ext_data.get('flair_enforce_approve_posts', True)

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
            sb_posts = list(reddit.subreddit(USERNAME).search("title:Shadowban", sort='new',
                                                              time_filter='week'))

            # If this shadow-ban alert hasn't been submitted
            # yet, use u/ArtemisHelper instead to submit a
            # post about this possibility.
            if len(sb_posts) == 0:
                reddit_helper.subreddit(USERNAME).submit(title="Possible Shadowban",
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
        logger.info('Post Approval: Post `{}` author sent the '
                    'default approval message.'.format(post_id))

    # Check to see if there are specific tags for this
    # submission to assign.
    advanced_set_flair_tag(submission)

    return True


def main_messaging(check_for_invites=True):
    """The basic function for checking for moderator invites to a
    subreddit, and accepting them. This function also accepts enabling
    or disabling flair enforcing if Artemis gets a message with either
    `Enable` or `Disable` from a SUBREDDIT. A message from a moderator
    user account does *not* count.

    There is also a function that removes the SUBREDDIT from being
    monitored when de-modded.

    :param check_for_invites: A Boolean determining whether Artemis
                              should check for moderator invites. This
                              is set to `False` when running this
                              process within the `main_timer` routine,
                              in order to avoid having to intialize a
                              subreddit in the middle of a statistics
                              gathering cycle.
    :return: `None`.
    """
    # Get the unread messages from the inbox and process with oldest
    # first to newest last.
    messages = list(reddit.inbox.unread(limit=None))
    messages.reverse()
    mod_invite_counter = 0

    # Iterate over the inbox, marking messages as read along the way.
    for message in messages:
        message.mark_read()

        # Get the variables of the message.
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
            if message.fullname.startswith('t1_') and msg_author != CREATOR:
                # Make sure my creator isn't also tagged.
                if 'u/{}'.format(CREATOR) not in message.body:
                    body_format = message.body.replace('\n', '\n> ')
                    message_content = "**[Link]({})**\n\n> ".format(cmt_permalink) + body_format
                    messaging_send_creator(msg_subreddit, 'mention',
                                           "* {}".format(message_content))
                    logger.debug('Messaging: Forwarded username mention'
                                 ' comment to my creator.')

                    # Save the comment that was a mention, by converting
                    # it into a PRAW object.
                    mention_comment = reddit.comment(id=message.fullname[3:])
                    mention_comment.save()
            else:
                logger.debug('Messaging: Inbox item is not a valid message. Skipped.')
            continue

        # Allow for remote maintenance actions from my creator.
        if msg_author == CREATOR:
            logger.info('Messaging: Received `{}` message from my creator.'.format(msg_subject))

            # There are a number of remote actions available, including
            # manually disabling flair enforcement for a specific sub.
            if 'disable' in msg_subject:
                disabled_subreddit = msg_body.lower().strip()
                database_monitored_subreddits_enforce_change(disabled_subreddit, False)
                message.reply('Messaging: Disabled enforcement, r/{}.'.format(disabled_subreddit))
            elif 'remove' in msg_subject:
                # Manually remove a subreddit from the monitored list.
                removed_subreddit = msg_body.lower().strip()
                database_subreddit_delete(removed_subreddit)
                message.reply('Messaging: Removed r/{} from monitoring.'.format(removed_subreddit))
            elif 'freeze' in msg_subject:
                # This instructs the bot to freeze a list of subreddits.
                # Parse the message body for a list of subreddits,
                # then insert an attribute into extended data.
                list_to_freeze = msg_body.lower().split(',')
                list_to_freeze = [x.strip() for x in list_to_freeze]
                for sub in list_to_freeze:
                    database_extended_insert(sub, {'freeze': True})
                    logger.info('Messaging: Froze r/{} at the request of u/{}.'.format(sub,
                                                                                       CREATOR))
                message.reply('Messaging: Froze these subreddits: **{}**.'.format(list_to_freeze))
            elif 'initiate' in msg_subject:
                # To manually initiate the `main_timer` for statistics,
                # in the rare case that a daily run was missed.
                #
                # First, purge the `subreddit_updated` database of
                # today's entries so that it can start fresh.
                today = date_convert_to_string(time.time())
                CURSOR_DATA.execute("DELETE FROM subreddit_updated WHERE date = ?", (today,))
                CONN_DATA.commit()

                # Secondly, initiate the update cycle.
                main_timer(manual_start=True)
                message.reply('Messaging: Finished retrieving statistics.')

        # FLAIR ENFORCEMENT AND SELECTION
        # If the reply is to a flair enforcement message, we process it
        # and see if we can set it for the user.
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
                template_result = messaging_parse_flair_response(relevant_subreddit, msg_body)

                # If there's a matching template and the original sender
                # of the chain is Artemis, we set the post flair.
                if template_result is not None and message_parent_author == USERNAME:
                    relevant_submission = reddit.submission(relevant_post_id)
                    main_post_approval(relevant_submission, template_result)
                    logger.info('Messaging: > Set flair via messaging for '
                                'post `{}`.'.format(relevant_post_id))

        # Otherwise, reject non-subreddit messages. Flair enforcement
        # replies to regular users were done earlier.
        if msg_subreddit is None:
            logger.debug('Messaging: > Message "{}" not from a subreddit.'.format(msg_subject))
            continue

        # MODERATION-RELATED MESSAGING FUNCTIONS
        # Get just the short name of the subreddit.
        new_subreddit = msg_subreddit.display_name.lower()
        # This is an auto-generated moderation invitation message.
        # If we are in a mode where we DO NOT want to accept invites
        # yet during a statistics cycle, save the message for later.
        # This also has a `mod_invite_counter` which helps space out
        # multiple invites if there are a bunch at the same time.
        # If the counter is reached, Artemis will process it again
        # later so that it can also get to other things first.
        if 'invitation to moderate' in msg_subject and mod_invite_counter <= 3:

            if not check_for_invites:
                message.mark_unread()
                logger.info("Messaging: r/{} invite detected but deferred.".format(new_subreddit))

                # Check the message thread to see if I've replied to
                # them before with the deferral message.
                # If the time is relatively recent (avoiding repeat
                # replies).
                if (int(time.time()) - message.created_utc) < (MINIMUM_AGE_TO_MONITOR * 3):
                    # If there are no existing messages, reply, letting
                    # the mods know I will accept soon.
                    if len(message.replies) == 0:
                        message.reply(MSG_MOD_RESP_CYCLE)
                        defer = 'Messaging: Replied to r/{} with a DEFERRAL hold message.'
                        logger.info(defer.format(new_subreddit))
                continue

            # Note the invitation to moderate.
            logger.info("Messaging: New moderation invite from r/{}.".format(msg_subreddit))

            # Check against our configuration data. Exit if it matches
            # pre-existing data.
            if new_subreddit in SUBREDDITS_OMIT:
                # Message my creator about this.
                messaging_send_creator(new_subreddit, "skip",
                                       "View it at r/{}.".format(new_subreddit))
                continue

            # Check for minimum subscriber count.
            # Note that quarantined subreddits' subscriber counts will
            # return a 0 from the API as well, or they will throw an
            # exception: `prawcore.exceptions.Forbidden:` or another.
            try:
                subscriber_count = msg_subreddit.subscribers
            except (prawcore.exceptions.Forbidden, prawcore.exceptions.NotFound):
                # This subreddit is quarantined; message my creator.
                messaging_send_creator(new_subreddit, "skip",
                                       "View it at r/{}.".format(new_subreddit))
                continue

            # Actually accept the invitation to moderate.
            # There is an escape here in case the invite is already
            # accepted for some reason. For example, the subreddit may
            # have tried to send the invite at two separate times.
            try:
                message.subreddit.mod.accept_invite()
                logger.info("Messaging: > Invite accepted.")
            except praw.exceptions.APIException:
                logger.error("Messaging: > Moderation invite error. Already accepted?")
                continue

            # Add the subreddit to our monitored list and we also fetch
            # some supplementary info for it, which is saved into the
            # extended data space.
            extended_data = {'created_utc': int(msg_subreddit.created_utc),
                             'display_name': msg_subreddit.display_name,
                             'added_utc': int(message.created_utc),
                             'invite_id': message.id}
            database_subreddit_insert(new_subreddit, extended_data)
            mod_invite_counter += 1

            # Check for the minimum subscriber count.
            # If it's below the minimum, turn off statistics gathering.
            if subscriber_count < MINIMUM_SUBSCRIBERS:
                subscribers_until_minimum = MINIMUM_SUBSCRIBERS - subscriber_count
                minimum_section = MSG_MOD_INIT_MINIMUM.format(MINIMUM_SUBSCRIBERS,
                                                              subscribers_until_minimum)
                logger.info("Messaging: r/{} subscribers below minimum.".format(new_subreddit))
            else:
                minimum_section = MSG_MOD_INIT_NON_MINIMUM.format(new_subreddit)

            # Determine the permissions I have and what sort of status
            # the subreddit wants.
            current_permissions = main_obtain_mod_permissions(new_subreddit)
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
                    mode_component = MSG_MOD_INIT_STRICT.format(new_subreddit)
                elif 'wiki' not in list_perms and 'all' not in list_perms:
                    # We were invited to be a mod but don't have the
                    # proper permissions. Let the mods know.
                    content = MSG_MOD_INIT_NEED_WIKI.format(new_subreddit)
                    message.reply(content + BOT_DISCLAIMER.format(new_subreddit))
                    logger.info("Messaging: Don't have the right permissions. Replied to sub.")

                # Check for the `flair` permission.
                if 'flair' in list_perms or 'all' in list_perms:
                    messaging_component = MSG_MOD_INIT_MESSAGING
                else:
                    messaging_component = ''
            else:
                # Exit as we are not a moderator. Note: This will not
                # exit if given *wrong* permissions.
                return

            # Check for the templates that are available to Artemis and
            # see how many flair templates we can find.
            template_number = len(subreddit_templates_retrieve(new_subreddit))

            # There are no publicly available flairs for this sub.
            # Let the mods know.
            if template_number == 0:
                template_section = MSG_MOD_INIT_NO_FLAIRS
                # Disable flair enforcement since there are no flairs
                # for people to select anyway.
                database_monitored_subreddits_enforce_change(new_subreddit, False)
                logger.info("Messaging: Subreddit has no flairs. Disabled flair enforcement.")
            else:
                # We have access to X number of templates on this
                # subreddit. Format the template section.
                template_section = ("\nThis subreddit has **{} user-accessible post flairs** "
                                    "to enforce:\n\n".format(template_number))
                template_section += subreddit_templates_collater(new_subreddit)

            # Format the reply to the subreddit, and confirm the invite.
            body = MSG_MOD_INIT_ACCEPT.format(new_subreddit, mode_component, template_section,
                                              messaging_component, minimum_section)
            message.reply(body + BOT_DISCLAIMER.format(new_subreddit))
            logger.info("Messaging: Sent confirmation reply. Set to `{}` mode.".format(mode))

            # Post a submission to Artemis's profile noting that it is
            # active on the appropriate subreddit.
            # We do a quick check to see if we have noted this subreddit
            # before on my user profile. Mark NSFW appropriately.
            status = "Accepted mod invite to r/{}".format(new_subreddit)
            subreddit_url = 'https://www.reddit.com/r/{}'.format(new_subreddit)
            try:
                user_sub = 'u_{}'.format(USERNAME)
                log_entry = reddit.subreddit(user_sub).submit(title=status, url=subreddit_url,
                                                              send_replies=False, resubmit=False,
                                                              nsfw=msg_subreddit.over18)
            except praw.exceptions.APIException:
                # This link was already submitted to my profile before.
                # Set `log_entry` to `None`.
                logger.info('Messaging: r/{} has already been added before.'.format(new_subreddit))
                log_entry = None
            else:
                # If the log submission is successful, lock this log
                # entry so comments can't be made on it.
                log_entry.mod.lock()

            # Fetch initialization data for this subreddit. This takes a
            # while, so we do it after the reply to mods.
            main_initialization(new_subreddit)

            if log_entry is not None:
                # This has not been noted before. Format a preview text.
                # Send a message to my creator notifying them about the
                # new addition if it's new.
                subreddit_about = msg_subreddit.public_description
                info = ('**r/{} ({:,} subscribers, created {})**'
                        '\n\n* `{}` mode\n\n> *{}*\n\n> {}')
                info = info.format(new_subreddit, msg_subreddit.subscribers,
                                   date_convert_to_string(msg_subreddit.created_utc),
                                   database_monitored_subreddits_enforce_mode(new_subreddit),
                                   msg_subreddit.title,  subreddit_about.replace("\n", "\n> "))

                # If the subreddit is public, add a comment and sticky.
                # Don't leave a comment if the subreddit is private and
                # not viewable by most people.
                if msg_subreddit.subreddit_type in ['public', 'restricted']:
                    log_comment = log_entry.reply(info)
                    log_comment.mod.distinguish(how='yes', sticky=True)
        elif 'invitation to moderate' in msg_subject and mod_invite_counter > 3:
            message.mark_unread()
            logger.info("Messaging: r/{} invite detected "
                        "but mod counter reached.".format(new_subreddit))

        # EXIT EARLY if subreddit is NOT in monitored list and it wasn't
        # a mod invite, as there's no point in processing said message.
        current_permissions = main_obtain_mod_permissions(new_subreddit)
        if new_subreddit not in database_monitored_subreddits_retrieve():
            # We got a message but we are not monitoring that subreddit.
            logger.debug("Messaging: New message but not a mod of r/{}.".format(new_subreddit))
            continue

        # OTHER MODERATION-RELATED MESSAGING FUNCTIONS
        if 'enable' in msg_subject:
            # This is a request to toggle ON the flair_enforce status of
            # the subreddit.
            logger.info('Messaging: New message to enable '
                        'r/{} flair enforcing.'.format(new_subreddit))
            database_monitored_subreddits_enforce_change(new_subreddit, True)

            # Add the example flair enforcement text as well.
            example_text = messaging_example_collater(msg_subreddit)
            message_body = "{}\n\n{}".format(MSG_MOD_RESP_ENABLE.format(new_subreddit),
                                             example_text)
            message.reply(message_body)

        elif 'disable' in msg_subject:
            # This is a request to toggle OFF the flair_enforce status
            # of the subreddit.
            logger.info('Messaging: New message to disable '
                        'r/{} flair enforcing.'.format(new_subreddit))
            database_monitored_subreddits_enforce_change(new_subreddit, False)
            message.reply(MSG_MOD_RESP_DISABLE.format(new_subreddit)
                          + BOT_DISCLAIMER.format(new_subreddit))

        elif 'example' in msg_subject:
            # This is a request to check out what the flair template
            # message looks like. Calls a sub-function.
            example_text = messaging_example_collater(msg_subreddit)
            message.reply(example_text)

        elif 'update' in msg_subject:
            logger.info('Messaging: New message to update r/{} config data.'.format(new_subreddit))

            # The first argument will either be `True` or `False`.
            config_status = wikipage_config(new_subreddit)
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
                            'r/{} processed successfully.'.format(new_subreddit))
                main_counter_updater(new_subreddit, action_type="Updated configuration")
            else:
                # Send back a reply noting that there was some sort of
                # error, and include the error.
                body = CONFIG_BAD.format(msg_subreddit.display_name, config_status[1])
                message.reply(body + BOT_DISCLAIMER.format(new_subreddit))
                logger.info('Messaging: > Configuration data for '
                            'r/{} encountered an error.'.format(new_subreddit))

        elif 'revert' in msg_subject:
            logger.info('Messaging: New message to revert '
                        'r/{} configuration data.'.format(new_subreddit))
            CURSOR_DATA.execute("SELECT * FROM monitored WHERE subreddit = ?", (new_subreddit,))
            result = CURSOR_DATA.fetchone()
            if result is not None:
                # We have saved extended data. We want to wipe out the
                # settings.
                extended_data_existing = ast.literal_eval(result[2])
                extended_keys = list(extended_data_existing.keys())

                # Iterate over the default variable keys and remove them
                # from the extended data in order to reset the info.
                default_vs_keys = list(yaml.safe_load(CONFIG_DEFAULT).keys())
                for key in extended_keys:
                    if key in default_vs_keys:
                        del extended_data_existing[key]  # Delete the settings.

                # Reset the settings in extended data.
                update_command = "UPDATE monitored SET extended = ? WHERE subreddit = ?"
                CURSOR_DATA.execute(update_command, (str(extended_data_existing), new_subreddit))
                CONN_DATA.commit()

                # Clear the wikipage, and check the subreddit subscriber
                # number, to make sure of the accurate template.
                # If there are enough subscribers for userflair stats,
                # replace the relevant section to disable it..
                if msg_subreddit.subscribers > MINIMUM_SUBSCRIBERS_USERFLAIR:
                    page_template = CONFIG_DEFAULT.replace('userflair_statistics: False',
                                                           'userflair_statistics: True')
                else:
                    page_template = str(CONFIG_DEFAULT)
                config_page = msg_subreddit.wiki["{}_config".format(USERNAME)]
                config_page.edit(content=page_template,
                                 reason='Reverting configuration per mod request.')

                # Send back a reply.
                message.reply(CONFIG_REVERT.format(new_subreddit)
                              + BOT_DISCLAIMER.format(new_subreddit))
                main_counter_updater(new_subreddit, action_type="Reverted configuration")
                logger.info('Messaging: > Config data for r/{} reverted.'.format(new_subreddit))

        elif 'userflair' in msg_subject:
            # Not surfaced at the moment, but still here for
            # compatibility due to its announcement in v1.5 Fir.
            logger.info('Messaging: New message to toggle r/{} userflair.'.format(new_subreddit))
            relevant_extended = database_extended_retrieve(new_subreddit)

            # Check if I have the relevant permissions. This user
            # command will be deprecated in the future.
            if 'flair' in current_permissions[1] or 'all' in current_permissions[1]:
                # If `userflair_statistics` is in the subreddit's
                # extended data, then toggle the setting.
                if 'userflair_statistics' in relevant_extended:
                    current_userflair_status = relevant_extended['userflair_statistics']
                    new_status = not current_userflair_status
                else:
                    # This value has not been saved before.
                    new_status = True

                # Insert the userflair setting into the database and
                # reply to the moderators.
                database_extended_insert(new_subreddit, {'userflair_statistics': new_status})
                body = MSG_MOD_RESP_USERFLAIR.format(new_status, new_subreddit)
                message.reply(body + BOT_DISCLAIMER.format(new_subreddit))
                logger.info('Messaging: > r/{} userflair stats is now {}.'.format(new_subreddit,
                                                                                  new_status))
            else:
                # Do not have the appropriate mod permissions to
                # gather userflair statistics. Let the mods know that.
                body = MSG_MOD_RESP_USERFLAIR_NEED_FLAIR.format(new_subreddit)
                message.reply(body + BOT_DISCLAIMER.format(new_subreddit))
                logger.info('Messaging: > No `flair` mod permission '
                            'on r/{}.'.format(new_subreddit))

        elif 'has been removed' in msg_subject:
            # Artemis was removed as a mod from a subreddit.
            # Delete from the monitored database.
            logger.info("Messaging: New demod message from r/{}.".format(new_subreddit))
            database_subreddit_delete(new_subreddit)
            message.reply(MSG_MOD_LEAVE.format(new_subreddit)
                          + BOT_DISCLAIMER.format(new_subreddit))
            main_counter_updater(new_subreddit, action_type="Removed as moderator")
            logger.info("Messaging: > Sent demod confirmation reply to moderators.")

            # Notify my creator about it.
            creator_msg = ("[What?](https://media.giphy.com/media/uLTvMTebsVdSw/giphy.gif)"
                           '\n\n* **r/{}**'.format(new_subreddit))
            subject_line = 'Demodded from subreddit: r/{}'.format(new_subreddit)
            reddit.redditor(CREATOR).message(subject=subject_line,
                                             message=creator_msg)

    return


def main_flair_checker():
    """This function checks the filtered database.
    It also uses `.info()` to retrieve PRAW submission objects,
    which is about 40 times faster
    than fetching one ID individually.

    This function will also clean the database of posts that are older
    than 24 hours by checking their timestamp.

    :return: Nothing.
    """
    fullname_ids = []

    # Access the database.
    CURSOR_DATA.execute("SELECT * FROM posts_filtered")
    results = CURSOR_DATA.fetchall()

    # If we have results, iterate over them, checking for age.
    # Note: Each result is a tuple with the ID in [0] and the
    # created Unix time in [1] of the tuple.
    if len(results) != 0:
        for result in results:
            short_id = result[0]
            if int(time.time()) - result[1] > MAXIMUM_AGE_TO_MONITOR:
                database_delete_filtered_post(short_id)
                logger.debug('Flair Checker: Deleted `{}` as it is too old.'.format(short_id))
            else:
                fullname_ids.append("t3_{}".format(short_id))

        # We have posts to look over. Get their fullname IDs then
        # convert the fullname IDs to PRAW objects with `.info()`.
        reddit_submissions = reddit.info(fullnames=fullname_ids)

        # Iterate over our PRAW submission objects.
        for submission in reddit_submissions:
            # Pass the submission to the unified routine for processing.
            main_post_approval(submission)
            logger.debug('Flair Checker: Passed the post `{}` for '
                         'approval checking.'.format(submission.id))

    return


# noinspection PyGlobalUndefined
def main_get_posts_frequency():
    """This function checks the frequency of posts that Artemis mods and
    returns a number that's based on 2x the number of posts retrieved
    during a specific interval. This is intended to be run once daily on
    a secondary thread.

    :return: `None`, but global variable `NUMBER_TO_FETCH` is declared.
    """
    global NUMBER_TO_FETCH

    # 15 minutes is our interval to test for.
    # Begin processing from the oldest post.
    time_interval = MINIMUM_AGE_TO_MONITOR * 3
    posts = list(reddit.subreddit('mod').new(limit=POSTS_BROADER_LIMIT))
    posts.reverse()

    # Take the creation time of the oldest post and calculate the
    # interval between that and now. Then get the average time period
    # for posts to come in and the nominal amount of posts that come in
    # within our interval.
    interval_between_posts = (int(time.time()) - int(posts[0].created_utc)) / POSTS_BROADER_LIMIT
    boundary_posts = int(time_interval / interval_between_posts)

    # Next we determine how many posts Artemis should *fetch* in a 15
    # minute period defined by the data. That number is 1.5 times the
    # earlier number in order to account for overlap.
    if boundary_posts < POSTS_BROADER_LIMIT:
        NUMBER_TO_FETCH = boundary_posts * 1.5
    else:
        NUMBER_TO_FETCH = POSTS_BROADER_LIMIT

    # If we need to adjust the broader limit, note that. Also make sure
    # the number to fetch is always at least our minimum.
    if POSTS_BROADER_LIMIT < NUMBER_TO_FETCH:
        logger.info('Get Posts Frequency: The broader limit of {} posts'
                    'may need to be higher.'.format(POSTS_BROADER_LIMIT))
    elif NUMBER_TO_FETCH < POSTS_MINIMUM_LIMIT:
        NUMBER_TO_FETCH = int(POSTS_MINIMUM_LIMIT)
        logger.info('Get Posts Frequency: Limit set to minimum limit of {} posts.'.format(POSTS_MINIMUM_LIMIT))
    else:
        logger.info('Get Posts Frequency: {} posts / {} minutes.'.format(NUMBER_TO_FETCH,
                                                                         int(time_interval / 60)))

    return


def main_get_posts_sections():
    """This function checks the moderated subreddits that have requested
    flair enforcing and divides them into smaller sets. This is because
    Reddit appears to have a limit of 250 subreddits per feed, which
    would mean that Artemis encounters the limit regularly.

    :return: A list of strings consisting of subreddits added together.
    """
    num_chunks = 4

    # Access the database, selecting only ones with flair enforcing.
    enforced_subreddits = database_monitored_subreddits_retrieve(True)

    # Determine the number of subreddits we want per section.
    # Then divide the list into `num_chunks`chunks.
    # Then join the subreddits with `+` in order to make it
    # parsable by `main_get_submissions` as a "multi-reddit."
    n = int(len(enforced_subreddits) // num_chunks) + 10
    my_range = len(enforced_subreddits) + n - 1
    final_lists = [enforced_subreddits[i * n:(i + 1) * n] for i in range(my_range // n)]
    final_components = ['+'.join(x) for x in final_lists]

    return final_components


def main_get_submissions():
    """This function checks all the monitored subreddits' submissions
    and checks for new posts.
    If a new post does not have a flair, it will send a message to the
    submitter asking them to select a flair.
    If Artemis also has `posts` mod permissions, it will *also* remove
    that post until the user selects a flair.

    :return: Nothing.
    """
    # Access the posts from my moderated communities and add them to a
    # list. Reverse the posts so that we start processing the older ones
    # first. The newest posts will be processed last.
    # The communities are fetched in sections in order to keep the
    posts = []
    sections = main_get_posts_sections()
    for section in sections:
        posts += list(reddit.subreddit(section).new(limit=NUMBER_TO_FETCH))
    posts.sort(key=lambda x: x.id.lower())

    # Iterate over the fetched posts. We have a number of built-in
    # checks to reduce the amount of processing.
    for post in posts:

        # Check to see if this is a subreddit with flair enforcing.
        # Also retrieve a dictionary containing extended data.
        post_subreddit = post.subreddit.display_name.lower()
        sub_ext_data = database_extended_retrieve(post_subreddit)
        if not database_monitored_subreddits_enforce_status(post_subreddit):
            continue

        # Check to see if the post has already been processed.
        post_id = post.id
        CURSOR_DATA.execute('SELECT * FROM posts_processed WHERE post_id = ?', (post_id,))
        if CURSOR_DATA.fetchone():
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
        if time_difference < MINIMUM_AGE_TO_MONITOR:
            logger.debug('Get: Post {} is < {} seconds old. Skip.'.format(post_id,
                                                                          MINIMUM_AGE_TO_MONITOR))
            continue

        # If the time difference is greater than
        # `MAXIMUM_AGE_TO_MONITOR / 4` seconds, skip (at 6 hours).
        # Artemis may have just been invited to moderate a subreddit; it
        # should not act on every old post.
        elif time_difference > (MAXIMUM_AGE_TO_MONITOR / 4):
            msg = 'Get: Post {} is over {} seconds old. Skipped.'
            logger.debug(msg.format(post_id, (MAXIMUM_AGE_TO_MONITOR / 4)))
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
            post_title = post.title.replace("]", r"\]")

        # Insert this post's ID into the database.
        CURSOR_DATA.execute('INSERT INTO posts_processed VALUES(?)', (post_id,))
        CONN_DATA.commit()
        log_line = ('Get: New Post "{}" on r/{} (https://redd.it/{}), flaired with "{}". '
                    'Added to processed database.')
        logger.info(log_line.format(post_title, post_subreddit, post_id, post_flair_text))

        # Check to see if the author is me or AutoModerator.
        # If it is, don't process.
        if post_author.lower() == USERNAME.lower() or post_author.lower() == 'automoderator':
            logger.info('Get: > Post `{}` is by me or AutoModerator. Skipped.'.format(post_id))
            continue

        # We check for posts that have no flairs whatsoever.
        # If this post has no flair CSS and no flair text, then we can
        # act upon it. otherwise, we do skip it.
        if post_flair_css is None and post_flair_text is None:

            # Get our permissions for this subreddit.
            # If we are not a mod of this subreddit, don't do anything.
            # Otherwise, collect the mod permissions as a list.
            current_permissions = main_obtain_mod_permissions(post_subreddit)
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
                continue

            # Check to see if author is on a whitelist in extended data.
            if 'flair_enforce_whitelist' in sub_ext_data:
                if post_author.lower() in sub_ext_data['flair_enforce_whitelist']:
                    logger.info('Get: > Post author u/{} is on the extended whitelist. Skipped.')
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
            bye_phrase = sub_ext_data.get('custom_goodbye', random.choice(GOODBYE_PHRASES)).lower()
            if not bye_phrase:
                bye_phrase = random.choice(GOODBYE_PHRASES).lower()

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
                main_counter_updater(post_subreddit, 'Removed post')

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
                main_counter_updater(post_subreddit, 'Sent flair reminder')
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
            # This post has a flair. We don't need to process it.
            logger.debug('Get: >> Post `{}` already has a flair. Doing nothing.'.format(post_id))
            continue

    return


'''RUNNING THE BOT'''
main_login()

"""
The below are two modes for Artemis to run tests directly from the
command line. The modes are:

    * `start` - fetch specific information for a random selection of,
                or a single unmonitored subreddit.
    * `test`  - generate statistics pages for a random selection of,
                or a single monitored subreddits.
"""
if len(sys.argv) > 1:
    REGULAR_MODE = False
    # Get the mode keyword that's accepted after the script path.
    specific_mode = sys.argv[1].strip().lower()

    if specific_mode == 'start':  # We want to fetch specific information for a sub.
        logger.info("LOCAL MODE: Launching Artemis in 'start' mode.")
        l_mode = input("\n====\n\nEnter 'random', name of a new sub, or 'x' to exit: ")
        l_mode = l_mode.lower().strip()

        # Exit the routine if the value is x.
        if l_mode == 'x':
            sys.exit()
        elif l_mode == 'random':
            # Choose a number of random subreddits to test.
            random_subs = []
            num_initialize = int(input('\nEnter the number of random subreddits to initialize: '))
            for _ in range(num_initialize):
                random_subs.append(reddit.random_subreddit().display_name.lower())
            print("\n\n### Now testing: r/{}.\n".format(', r/'.join(random_subs)))

            for test_sub in random_subs:
                print("\n\n### Initializing data for r/{}...".format(test_sub))
                starting = time.time()
                main_initialization(test_sub, create_wiki=False)
                generated_text = wikipage_collater(test_sub)
                elapsed = (time.time() - starting) / 60
                print("\n\n# r/{} data ({:.2f} mins):\n\n{}\n\n---".format(test_sub, elapsed,
                                                                           generated_text))
            print('\n\n### All {} initialization tests complete.'.format(num_initialize))
        else:
            # Initialize the data for the sub.
            logger.info('Manually intializing data for r/{}.'.format(l_mode))
            time_initialize_start = time.time()
            main_initialization(l_mode, create_wiki=False)
            initialized = (time.time() - time_initialize_start)
            print("\n---\n\nInitialization time: {:.2f} minutes".format(initialized / 60))

            # Generate and print the collated data just as the wiki page
            # would look like.
            print(wikipage_collater(l_mode))
            elapsed = (time.time() - time_initialize_start)
            print("\nTotal elapsed time: {:.2f} minutes".format(elapsed / 60))

    elif specific_mode == "test":
        # This runs the wikipage generator through randomly selected
        # subreddits that have already saved data.
        logger.info("LOCAL MODE: Launching Artemis in 'test' mode.")
        l_mode = input("\n====\n\nEnter 'random', name of a sub, or 'x' to exit: ").lower().strip()

        # Exit the routine if the value is x.
        if l_mode == 'x':
            sys.exit()
        elif l_mode == 'random':
            # Next we fetch all the subreddits we monitor and ask for
            # the number to test.
            number_to_test = int(input("\nEnter the number of tests to make: "))
            random_subs = random.sample(database_monitored_subreddits_retrieve(), number_to_test)

            # Now we begin to test the collation by running the
            # function, making sure there are no errors.
            for test_sub in random_subs:
                time_initialize_start = time.time()
                print("\n---\n\n> Testing r/{}...\n".format(test_sub))

                # If the length of the generated text is longer than a
                # certain amount, then it's passed.
                if len(wikipage_collater(test_sub)) > 1000:
                    total_time = time.time() - time_initialize_start
                    print("> Test complete for r/{} in {:.2f} seconds.\n".format(test_sub,
                                                                                 total_time))
            print('\n\n# All {} wikipage collater tests complete.'.format(number_to_test))
        else:
            print(wikipage_collater(l_mode))
    else:
        REGULAR_MODE = True
else:
    # We only want to enable the regular loop if we're running on Linux.
    REGULAR_MODE = True if sys.platform == "linux" else False

# This is the regular loop for Artemis, running main functions in
# sequence while taking a `WAIT` break in between.
try:
    while REGULAR_MODE:
        try:
            main_messaging()
            main_get_submissions()
            main_flair_checker()
            main_timer()
            print("\n---\n")
        except Exception as e:
            # Artemis encountered an error/exception, and if the error
            # is not a common connection issue, log it in a separate
            # file. Otherwise, merely record it in the events log.
            error_entry = "\n> {} \n\n".format(e)
            error_entry += traceback.format_exc()
            logger.error(error_entry)
            if not any(keyword in error_entry for keyword in CONNECTION_ERRORS):
                main_error_log_(error_entry)

        time.sleep(WAIT)
except KeyboardInterrupt:
    # Manual termination of the script with Ctrl-C.
    logger.info('Manual user shutdown.')
    sys.exit()
