#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Artemis (u/AssistantBOT) is a statistics compiler and flair enforcer for subreddits that have invited it to moderate.

Artemis has two primary functions:

* **Enforcing post flairs on a subreddit**.
    * Artemis will help make sure submitters choose an appropriate flair for their post.
* **Recording useful statistics for a subreddit**.
    * Artemis will compile statistics on a community's posts as well as its subscriber/traffic growth.
    * That data will be formatted in a summary wiki page that's updated daily midnight UTC.
    * The wiki page for a subreddit is at: https://www.reddit.com/r/SUBREDDIT/wiki/assistantbot_statistics

Written and maintained by u/kungming2.
"""

import os
import sys

import sqlite3
import requests
import json

import praw
import prawcore

import time
import datetime
import calendar

import traceback
import logging
import shutil

from collections import OrderedDict


"""INTIALIZATION INFORMATION"""

VERSION_NUMBER = "0.9.9 Beta"
WAIT = 120  # Number of seconds Artemis waits in between runs.

SOURCE_FOLDER = os.path.dirname(os.path.realpath(__file__))  # Fetch the absolute directory the script is in.
FILE_ADDRESS_DATA = SOURCE_FOLDER + "/_data.db"  # The main database file.
FILE_ADDRESS_ERROR = SOURCE_FOLDER + "/_error.md"  # The main error log.
FILE_ADDRESS_LOGS = SOURCE_FOLDER + "/_logs.md"  # The main events log.
FILE_ADDRESS_CREDENTIALS = SOURCE_FOLDER + "/_credentials.json"  # JSON file that stores login data.

"""LOAD CREDENTIALS"""


def load_credentials():
    """
    Function that takes information about login and OAuth access from an external JSON file and loads it as a
    dictionary.

    :return: A dictionary with keys for important variables needed to log in and authenticate.
    """

    # Load the JSON file.
    f = open(FILE_ADDRESS_CREDENTIALS, 'r', encoding='utf-8')
    credentials_data = f.read()
    f.close()

    # Convert the JSON data into a Python dictionary.
    credentials_data = json.loads(credentials_data)

    return credentials_data


def load_logger():
    """
    Define the logger to use and its basic parameters for formatting.
    :return:
    """

    global logger

    # Set up the logger.
    logformatter = '%(levelname)s: %(asctime)s - %(message)s'
    logging.basicConfig(format=logformatter, level=logging.INFO)  # By default only display INFO or higher levels.
    logger = logging.getLogger(__name__)

    # Define the logging handler (the file to write to with specific formatting.)
    handler = logging.FileHandler(FILE_ADDRESS_LOGS, 'a', 'utf-8')
    handler.setLevel(logging.INFO)  # By default only log INFO or higher.
    handler_format = logging.Formatter(logformatter, datefmt="%Y-%m-%d [%I:%M:%S %p]")  # Format of the time in the log.
    handler.setFormatter(handler_format)
    logger.addHandler(handler)

    return


# Load the logger, and actually get the credentialed data from the JSON file.
load_logger()
artemis_info = load_credentials()
USERNAME = artemis_info['username']
PASSWORD = artemis_info['password']
APP_ID = artemis_info['app_id']
APP_SECRET = artemis_info['app_secret']
# This gets the folder path that files are backed to. We have to replace the slashes with pluses for JSON compatibility.
BACKUP_FOLDER = artemis_info['backup_folder'].replace("+", "/")

# We don't want to log common connection errors.
CONNECTION_ERRORS = ['404 HTTP', '200 HTTP', '400 HTTP', '401 HTTP', '403 HTTP', '404 HTTP', '500 HTTP', '502 HTTP',
                     '503 HTTP', '504 HTTP', 'CertificateError', 'ConnectionRefusedError', 'Errno 113',
                     'Error 503', 'ProtocolError', 'ServerError', 'socket.gaierror', 'socket.timeout', 'ssl.SSLError']

"""MESSAGE TEMPLATES"""

USER_AGENT = 'Artemis v{} (u/{}), a moderation assistant written by u/kungming2.'.format(VERSION_NUMBER, USERNAME)
BOT_DISCLAIMER = ("\n\n---\n^Artemis: ^a ^moderation ^assistant ^for ^r/{0} ^| "
                  "[^Contact ^r/{0} ^mods](https://www.reddit.com/message/compose?to=%2Fr%2F{0}) ^| "
                  "[^Bot ^Info/Support](https://www.reddit.com/user/assistantbot/posts/?limit=2)")
MSG_ACCEPT_INVITE = """
Thanks for letting me assist the r/{0} moderator team! I've begun enforcing flair for new submissions and will post \
statistics for the community at [this wiki page](https://www.reddit.com/r/{0}/wiki/assistantbot_statistics). 

{1}

{2}

---

* To completely disable flair enforcing on r/{0}, please send me a *modmail message* \
[from your subreddit](https://mod.reddit.com/mail/create) with `Disable` in the subject. \
Flair enforcing can be turned on again by sending another modmail message with `Enable` in the subject.
* Statistics for subreddits are updated every midnight UTC.
* Please contact my creator u/kungming2 if you have any other questions.

Have a good day!
"""
MSG_ACCEPT_STRICT = '''
Since I have the `posts` moderator permission, "strict mode" for flair enforcing has been activated on this subreddit. 
I will *remove* posts without any flair and automatically restore them once their submitter selects a flair. 
Unflaired posts older than 24 hours will be considered as abandoned by their submitter.

To disable "strict mode" but continue flair enforcement, simply uncheck my `posts` moderator permission. 
'''
MSG_ACCEPT_NO_FLAIRS = '''
It appears that there are no post flairs associated with this subreddit. Please check out these \
Reddit Help articles ([New Reddit](https://mods.reddithelp.com/hc/en-us/articles/360010513191-Post-Flair), \
[Old Reddit](https://mods.reddithelp.com/hc/en-us/articles/360002598912-Flair)) for guidance on how to set up post \
flairs for your subreddit as a moderator.
'''
MSG_ACCEPT_WRONG_PERMISSIONS = '''
It appears that I do not have the right moderator permissions to operate on this subreddit. I just need the `wiki` mod \
permission to update a subreddit's statistics page. If you would still like me to assist, please \
grant me the `wiki` mod permission.
'''
MSG_LEAVE = '''
Artemis will no longer enforce flair or record statistics for r/{}. Have a good day!
'''
MSG_FLAIR_YOUR_POST = '''
Hey there, u/{0},

Thanks for [your submission]({3}) to r/{1}! This is a friendly reminder that the moderators of this community have \
asked for all posts in r/{1} to have a *post flair* - in other words, a relevant tag or category. 

**Here's how to select a flair for [your submission]({3})**: 

*[Mobile](https://i.imgur.com/q9OIOaU.gifv)* | *[Tablet](https://i.imgur.com/I35qWPZ.gifv)* | \
*[Desktop (New)](https://i.imgur.com/AAjN8en.gifv)* | *[Desktop (Old)](https://i.imgur.com/RmZr6Cv.gifv)*.

**The following post flairs are available on r/{1}**:


{2}


{5} 
Post flairs help keep r/{1} organized and allow our subscribers to easily sort through the posts \
they want to see. Please [contact the mods of r/{1}]({4}) if you have any questions. Thank you very much!
'''
MSG_FLAIR_MOD_MSG = ("https://www.reddit.com/message/compose?to=%2Fr%2F{}&subject="
                     "About+My+Unflaired+Post&message=About+my+post+%5Bhere%5D%28{}%29...")
MSG_FLAIR_REMOVAL = ("Your post has been removed but will be automatically restored if you select a flair for it within"
                     " 24 hours. We apologize for the inconvenience.")
MSG_FLAIR_APPROVAL = ("Thanks for selecting a flair for [your post]({})! It has been approved and is now fully visible "
                      "on  r/{}. Have a great day!")
MSG_MOD_ENABLE = ("Flair enforcing is now **ENABLED** on r/{}. Artemis will send reminder messages to users "
                  "who submit posts without flairing them.")
MSG_MOD_DISABLE = ("Flair enforcing is now **DISABLED** on r/{}. Artemis will *NOT* send reminder messages to users "
                   "who submit posts without flairing them.")
WIKIPAGE_BLANK = ("# Statistics by Artemis (u/AssistantBOT)\n\n"
                  "📊 *This statistics page will be updated in {} hours at midnight UTC.*")
WIKIPAGE_TEMPLATE = '''

# Statistics by Artemis (u/AssistantBOT)

## Bot Status

{}

## Posts

{}

## Subscribers

{}

## Traffic 

{}

---

*Compiled by Artemis v{} in {} seconds and updated on {}.*
'''

# This connects the bot with its main database file.
conn_data = sqlite3.connect(FILE_ADDRESS_DATA)
cursor_data = conn_data.cursor()


"""DATE/TIME CONVERSION FUNCTIONS"""


def date_convert_to_string(unix_integer):
    """
    Converts a UNIX integer into a date formatted as YYYY-MM-DD.

    :param unix_integer: Any UNIX time number.
    :return: A string formatted with UTC time.
    """
    unix_integer = int(unix_integer)  # Just in case we are passed a string.
    date_string = datetime.datetime.utcfromtimestamp(unix_integer).strftime("%Y-%m-%d")

    return date_string


def date_convert_to_unix(date_string):
    """
    Converts a date formatted as YYYY-MM-DD into a UNIX integer.

    :param date_string: Any date formatted as YYYY-MM-DD.
    :return: The timestamp of MIDNIGHT that day UTC.
    """

    # Account for timezone differences.
    time_difference = -8  # UTC offset
    time_difference_sec = time_difference * 3600

    local_unix_integer = int(time.mktime(time.strptime(date_string, '%Y-%m-%d')))
    utc_timestamp = local_unix_integer + time_difference_sec

    return utc_timestamp


def date_month_convert_to_string(unix_integer):
    """
    Converts a UNIX integer into a date formatted as YYYY-MM. It just gets the month string.

    :param unix_integer: Any UNIX time number.
    :return: A month string formatted as YYYY-MM.
    """
    unix_integer = int(unix_integer)  # Just in case we are passed a string.
    month_string = datetime.datetime.utcfromtimestamp(unix_integer).strftime("%Y-%m")

    return month_string


def date_next_midnight():
    """
    Function to determine seconds until midnight UTC. Returns how many seconds until then.

    :return: Returns the number of seconds remaining until midnight UTC as an integer
    """

    # Define the time of the hour we want this to operate
    today = datetime.datetime.utcnow().date()  # Current day UTC
    tomorrow = str(today + datetime.timedelta(days=1))  # Tomorrow's midnight as a string.

    # Get the Unix time of the next midnight.
    next_midnight_unix = int(time.mktime(time.strptime(tomorrow, '%Y-%m-%d')))

    # Get the time difference in seconds.
    time_difference = int(time.time() - next_midnight_unix) * -1

    return time_difference


"""DATABASE FUNCTIONS"""


def database_subreddit_insert(community_name):
    """
    Add a subreddit to the moderated list. This means Artemis will actively work on that community.

    :param community_name: Name of a subreddit (no r/).
    :return:
    """
    community_name = community_name.lower()

    # Access the database.
    sql_command = "SELECT * FROM monitored WHERE subreddit = ?"
    cursor_data.execute(sql_command, (community_name,))
    results = cursor_data.fetchone()

    # Check the results.
    if results is None:  # Subreddit was not previously in database.
        cursor_data.execute("INSERT INTO monitored VALUES (?, ?)", (community_name, 1))  # 1 is True for flair enforcing
        conn_data.commit()
        logger.info("[Artemis] Sub Insert: Subreddit r/{} added to my monitored database.".format(community_name))
    else:  # Subreddit was already in the database.
        logger.info("[Artemis] Sub Insert: Subreddit r/{} is already in my monitored database.".format(community_name))

    return


def database_subreddit_delete(community_name):
    """
    Remove a subreddit from the moderated list.  This means Artemis will NOT work on that community.

    :param community_name: Name of a subreddit (no r/).
    :return:
    """
    community_name = community_name.lower()

    # Access the database.
    sql_command = "SELECT * FROM monitored WHERE subreddit = ?"
    cursor_data.execute(sql_command, (community_name,))
    results = cursor_data.fetchone()

    if results is not None:  # Subreddit is in database. Let's remove it.
        cursor_data.execute("DELETE FROM monitored WHERE subreddit = ?", (community_name,))
        conn_data.commit()
        logger.info('[Artemis] Sub Delete: Subreddit r/{} deleted from my monitored database.'.format(community_name))

    return


def database_monitored_subreddits_retrieve():
    """
    Function returns a list of all the subreddits that this bot monitors.

    :return:
    """
    final_list = []

    # Access the database.
    sql_command = "SELECT * FROM monitored"
    cursor_data.execute(sql_command)
    results = cursor_data.fetchall()

    # Collate the saved subreddits and add them into a list.
    for item in results:
        community_name = item[0]
        final_list.append(community_name)

    logger.debug("[Artemis] Monitored Subs Retrieve: Currently monitored communities are {}.".format(final_list))

    return final_list


def database_monitored_subreddits_enforce_change(subreddit_name, to_enforce):
    """
    This simple function changes the `flair_enforce` status of a monitored subreddit.
    True (1): Artemis will send messages reminding people of the flairs available. (default)
    False (0): Artemis will not send any messages about flairs. This effectively makes Artemis a statistics-only
               assistant.
    Note that this is completely separate from the "strict enforcing" function. That's covered under `True`.

    :param subreddit_name: The subreddit to modify.
    :param to_enforce: A Boolean denoting which to set it to.
    :return:
    """
    subreddit_name = subreddit_name.lower()

    # Convert the Booleans to SQLite3 integers. 1 = True, 0 = False.
    subreddit_digit = int(to_enforce)

    # Access the database.
    cursor_data.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name,))
    result = cursor_data.fetchone()

    if result is not None:  # Subreddit is stored in our monitored database. We can modify it.
        flair_enforce_status = int(result[1])  # This is the current status.

        # Change it if they are different.
        if flair_enforce_status != subreddit_digit:
            cursor_data.execute("UPDATE monitored SET flair_enforce = ? WHERE subreddit = ?", (subreddit_digit,
                                                                                               subreddit_name))
            conn_data.commit()

    logger.info("[Artemis] Enforce Change: r/{} flair enforce status set to {}.".format(subreddit_name, to_enforce))

    return


def database_monitored_subreddits_enforce_status(subreddit_name):
    """
    A function that returns True or False depending on the subreddit's `flair_enforce` status.

    :param subreddit_name:
    :return: A Boolean. Default is True.
    """
    subreddit_name = subreddit_name.lower()

    # Access the database.
    cursor_data.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name,))
    result = cursor_data.fetchone()

    if result is not None:  # Subreddit is stored in our monitored database. We can access it.
        flair_enforce_status = int(result[1])  # This is the current status.
        logger.debug("[Artemis] Enforce Status: r/{} flair enforce status is {}.".format(subreddit_name,
                                                                                         bool(flair_enforce_status)))

        if flair_enforce_status == 0:
            return False

    return True


def database_delete_filtered_post(post_id):
    """
    This function deletes a post ID from the flair filtered database. Either because it's too old, or because it has
    been approved and restored.

    :param post_id: The Reddit submission's ID, as a string.
    :return:
    """

    # Delete it from our database.
    cursor_data.execute('DELETE FROM posts_filtered WHERE post_id = ?', (post_id,))
    conn_data.commit()

    logger.info('[Artemis] Delete Filtered Post: Deleted the post {} from the filtered database.'.format(post_id))

    return


def database_cleanup():
    """
    This function cleans up the `posts_processed` table and keeps only a certain amount left in order to prevent it
    from becoming too large. This keeps the newest X post IDs and deletes the oldest ones.

    :return:
    """
    items_to_keep = 1000  # How many entries in `posts_processed` we want to preserve.
    lines_to_keep = 2000  # How many lines of entries we wish to preserve in the logs.

    # Access the database, order the posts by oldest first, and then only keep the above number of entries.
    delete_command = ("DELETE FROM posts_processed WHERE post_id NOT IN "
                      "(SELECT post_id FROM posts_processed ORDER BY post_id DESC LIMIT ?)")
    cursor_data.execute(delete_command, (items_to_keep,))
    conn_data.commit()

    logger.info('[Artemis] Cleanup: Last {} database entries kept.'.format(items_to_keep))

    # Clean up the logs. Keep only the last `lines_to_keep` lines.
    # Open the logs file and take its contents.
    f = open(FILE_ADDRESS_LOGS, "r", encoding='utf-8')
    events_logs = f.read()
    f.close()
    lines_entries = events_logs.split('\n')

    # If there are more lines, truncate it.
    if len(lines_entries) > lines_to_keep:
        lines_entries = lines_entries[(-1 * lines_to_keep):]
        lines_entries = "\n".join(lines_entries)
        f = open(FILE_ADDRESS_LOGS, "w", encoding='utf-8')
        f.write(lines_entries)
        f.close()

    logger.info('[Artemis] Cleanup: Last {} log entries kept.'.format(lines_to_keep))

    return


"""SUBREDDIT DATA RETRIEVAL"""


def subreddit_templates_retrieve(subreddit_name):
    """
    Retrieve the templates that are available for a particular subreddit's flair.
    Note that moderator-only post flairs ARE NOT included in the data that Reddit returns.

    :param subreddit_name: Name of a subreddit.
    :return:
    """

    subreddit_templates = {}
    order = 1
    subreddit_name = subreddit_name.lower()
    r = reddit.subreddit(subreddit_name)

    # Access the templates on the subreddit and assign their attributes to our dictionary.
    try:
        for template in r.flair.link_templates:
            subreddit_templates[template['text']] = {}
            subreddit_templates[template['text']]['id'] = template['id']
            subreddit_templates[template['text']]['order'] = order
            subreddit_templates[template['text']]['css_class'] = template['css_class']
            order += 1
    except prawcore.exceptions.Forbidden:
        # The flairs don't appear to be available to us. It may be that they are mod-only.
        pass

    logger.debug("[Artemis] Templates Retrieve: r/{} templates are: {}".format(subreddit_name, subreddit_templates))

    return subreddit_templates


def subreddit_templates_collater(subreddit_name):
    """
    A function that generates a bulleted list of flairs available on a subreddit based on a dictionary by
    `subreddit_templates_retrieve`.

    :param subreddit_name: The name of a Reddit subreddit.
    :return: A Markdown bulleted list of templates.
    """

    formatted_order = {}
    formatted_lines = []

    template_dictionary = subreddit_templates_retrieve(subreddit_name)

    # Iterate over our keys, indexing by the order.
    for template in template_dictionary.keys():
        template_text = template
        template_order = template_dictionary[template]['order']
        formatted_order[template_order] = template_text

    # Reorder and format each line.
    for key in sorted(formatted_order.keys()):
        formatted_lines.append("* {}".format(formatted_order[key]))

    bulleted_list = "\n".join(formatted_lines)

    logger.debug("[Artemis] Templates Collater: r/{} templates list is: {}".format(subreddit_name, bulleted_list))

    return bulleted_list


def subreddit_traffic_daily_estimator(subreddit_name):
    """
    Retrieves the daily traffic up to now and estimates the total traffic for this month.

    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """

    daily_traffic_dictionary = {}
    output_dictionary = {}
    total_uniques = []
    total_pageviews = []
    current_month = date_month_convert_to_string(time.time())  # Get the current month as a YYYY-MM string.

    # Retrieve traffic data as a dictionary.
    try:
        traffic_data = reddit.subreddit(subreddit_name).traffic()
    except prawcore.exceptions.NotFound:  # We likely do not have the ability to access this.
        return None

    # Save the specific information.
    daily_data = traffic_data['day']

    # Iterate over the data:
    for date in daily_data:

        date_string = date_convert_to_string(date[0])
        date_uniques = date[1]
        if date_uniques != 0 and current_month in date_string:  # If there's data for a day, we'll save it.
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
    average_uniques = int(sum(total_uniques) / len(total_uniques))
    average_pageviews = int(sum(total_pageviews) / len(total_pageviews))

    # Get the number of days in the month and calculate the estimated amount for the month.
    days_in_month = calendar.monthrange(datetime.datetime.now().year, datetime.datetime.now().month)[1]
    output_dictionary['average_uniques'] = average_uniques
    output_dictionary['average_pageviews'] = average_pageviews
    output_dictionary['estimated_uniques'] = average_uniques * days_in_month
    output_dictionary['estimated_pageviews'] = average_pageviews * days_in_month

    return output_dictionary


def subreddit_traffic_recorder(subreddit_name):
    """
    Retrieve the monthly traffic statistics for a subreddit and store them in our database.

    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """

    traffic_dictionary = {}
    subreddit_name = subreddit_name.lower()
    current_month = date_month_convert_to_string(time.time())  # Get the current month as a YYYY-MM string.

    # Retrieve traffic data as a dictionary.
    try:
        traffic_data = reddit.subreddit(subreddit_name).traffic()
    except prawcore.exceptions.NotFound:  # We likely do not have the ability to access this.
        return

    # Save the specific information.
    monthly_data = traffic_data['month']

    # Iterate over the months.
    for month in monthly_data:

        # Convert the listed data into actual variables.
        unix_month_time = month[0] + 86400  # Account for UTC
        month_uniques = month[1]
        month_pageviews = month[2]
        year_month = date_month_convert_to_string(unix_month_time)  # Get the month as YYYY-MM in UTC

        if current_month != year_month:  # We don't want to save the data for the current month, since it's incomplete.
            traffic_dictionary[year_month] = [month_uniques, month_pageviews]

    # Take the formatted dictionary and save it to our database.
    sql_command = "SELECT * FROM subreddit_traffic WHERE subreddit = ?"
    cursor_data.execute(sql_command, (subreddit_name,))
    results = cursor_data.fetchone()

    if results is None:  # This has not been saved before.
        cursor_data.execute("INSERT INTO subreddit_traffic VALUES (?, ?)", (subreddit_name, str(traffic_dictionary)))
        conn_data.commit()
        logger.info('[Artemis] Traffic Recorder: Traffic data for r/{} saved.'.format(subreddit_name))
    else:  # Saved traffic data already exists. Let's merge the data.
        existing_dictionary = eval(results[1])
        new_dictionary = existing_dictionary.copy()
        new_dictionary.update(traffic_dictionary)

        # Update the saved data.
        update_command = "UPDATE subreddit_traffic SET traffic = ? WHERE subreddit = ?"
        cursor_data.execute(update_command, (str(new_dictionary), subreddit_name))
        conn_data.commit()
        logger.info("[Artemis] Traffic Recorder: Traffic data for r/{} merged w/ existing data.".format(subreddit_name))

    return traffic_dictionary


def subreddit_traffic_retriever(subreddit_name):
    """
    Function that looks at the traffic data for a subreddit and returns it as a Markdown table
    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """
    formatted_lines = []
    subreddit_name = subreddit_name.lower()
    all_uniques = []
    all_pageviews = []
    all_uniques_changes = []
    all_pageviews_changes = []
    basic_line = "| {} | {} | *{}%* | {} | *{}%* |"

    # Look for the traffic data in our database.
    sql_command = "SELECT * FROM subreddit_traffic WHERE subreddit = ?"
    cursor_data.execute(sql_command, (subreddit_name,))
    results = cursor_data.fetchone()

    if results is not None:  # We have data.
        traffic_dictionary = eval(results[1])
    else:  # There is no traffic data stored. Return None.
        return None

    # Iterate over our dictionary.
    for key in sorted(traffic_dictionary, reverse=True):
    
        # We get the previous month's data so we can track changes.
        month_t = datetime.datetime.strptime(key, '%Y-%m').date()
        previous_month = (month_t + datetime.timedelta(-15)).strftime('%Y-%m')

        current_uniques = traffic_dictionary[key][0]
        current_pageviews = traffic_dictionary[key][1]
        all_uniques.append(current_uniques)
        all_pageviews.append(current_pageviews)

        # Try to get comparative data from the previous month.
        try:
            previous_uniques = traffic_dictionary[previous_month][0]
            previous_pageviews = traffic_dictionary[previous_month][1]

            # Determine the changes in uniques/page views relative to the previous month.
            uniques_change = round(((current_uniques - previous_uniques) / previous_uniques) * 100, 2)
            pageviews_change = round(((current_pageviews - previous_pageviews) / previous_pageviews) * 100, 2)
            all_uniques_changes.append(uniques_change)
            all_pageviews_changes.append(pageviews_change)
        except KeyError:
            uniques_change = "---"
            pageviews_change = "---"

        line = basic_line.format(key, current_uniques, uniques_change, current_pageviews, pageviews_change)
        formatted_lines.append(line)

    # Get the estimated CURRENT monthly average for this month. (this is generated from the current daily data)
    daily_data = subreddit_traffic_daily_estimator(subreddit_name)
    if daily_data is not None:  # We have daily estimated data that we can parse.

        # Get month data.
        current_month = date_month_convert_to_string(time.time())  # Get the current month as a YYYY-MM string.
        current_month_dt = datetime.datetime.strptime(current_month, '%Y-%m').date()
        previous_month = (current_month_dt + datetime.timedelta(-15)).strftime('%Y-%m')

        # Estimate the change.
        estimated_uniques = daily_data['estimated_uniques']
        estimated_pageviews = daily_data['estimated_pageviews']

        # Get the previous month's data for comparison.
        try:
            previous_uniques = traffic_dictionary[previous_month][0]
            previous_pageviews = traffic_dictionary[previous_month][1]
            est_uniques_change = round(((estimated_uniques - previous_uniques) / previous_uniques) * 100, 2)
            est_pageviews_change = round(((estimated_pageviews - previous_pageviews) / previous_pageviews) * 100, 2)
        except KeyError:
            est_uniques_change = est_pageviews_change = "---"

        estimated_line = basic_line.format("*{} (est.)*".format(current_month), estimated_uniques, est_uniques_change,
                                           estimated_pageviews, est_pageviews_change)

        # Insert it at the start of the formatted lines list.
        formatted_lines.insert(0, estimated_line)  # Insert it at position 0

    # Get the averages of both the total amounts and the percentages.
    num_avg_uniques = round(sum(all_uniques) / len(all_uniques), 2)
    num_avg_pageviews = round(sum(all_pageviews) / len(all_uniques), 2)
    num_avg_uniques_change = round(sum(all_uniques_changes) / len(all_uniques_changes), 2)
    num_pageviews_changes = round(sum(all_pageviews_changes) / len(all_pageviews_changes), 2)
    average_section = ("* *Average Monthly Uniques*: {}\n* *Average Monthly Pageviews*: {}\n"
                       "* *Average Monthly Uniques Change*: {}%\n* *Average Monthly Pageviews Change*: {}%\n\n")
    average_section = average_section.format(num_avg_uniques, num_avg_pageviews,
                                             num_avg_uniques_change, num_pageviews_changes)

    # Form the Markdown table.
    header = ("| Month | Uniques | Uniques % Change | Pageviews | Pageviews % Change |\n"
              "|-------|---------|------------------|-----------|--------------------|\n")
    body = average_section + header + '\n'.join(formatted_lines)

    return body


def subreddit_subscribers_recorder(subreddit_name):
    """
    A quick routine that gets the number of subscribers for a specific subreddit and saves it to our database.
    This is intended to be run daily.

    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """
    subreddit_name = subreddit_name.lower()

    # Get the date.
    current_time = time.time()
    current_day = date_convert_to_string(current_time)  # Convert time to YYYY-MM-DD in UTC

    # Get the current state of subscribers.
    current_subscribers = reddit.subreddit(subreddit_name).subscribers

    # Check to see if subscriber data has been stored before for this day.
    sql_command = "SELECT * FROM subreddit_subscribers WHERE subreddit = ? AND date = ?"
    cursor_data.execute(sql_command, (subreddit_name, current_day))
    results = cursor_data.fetchone()

    # Add it to our database.
    if results is None:
        data_to_insert = (subreddit_name, current_day, current_subscribers)
        cursor_data.execute("INSERT INTO subreddit_subscribers VALUES (?, ?, ?)", data_to_insert)
        conn_data.commit()
        save_message = "[Artemis] Subscribers Recorder: Subscribers for r/{} saved: {}, {} subscribers."
        logger.info(save_message.format(subreddit_name, current_day, current_subscribers))
    else:  # Data already exists for this day.
        save_message = "[Artemis] Subscribers Recorder: Subscribers for r/{} already saved for {}."
        logger.info(save_message.format(subreddit_name, current_day))

    return


def subreddit_subscribers_retriever(subreddit_name):
    """
    Function that looks at the subscriber data and returns it as a Markdown table.

    :param subreddit_name: The name of a Reddit subreddit.
    :return:
    """
    subscriber_dictionary = {}
    formatted_lines = []
    day_changes = []
    subreddit_name = subreddit_name.lower()

    # Check to see if this has been stored before.
    sql_command = "SELECT * FROM subreddit_subscribers WHERE subreddit = ?"
    cursor_data.execute(sql_command, (subreddit_name,))
    results = cursor_data.fetchall()

    # Exit if there is no data.
    if len(results) == 0:
        return None

    # Iterate over the data.
    for result in results:
        date = result[1]
        subscribers_num = result[2]
        subscriber_dictionary[date] = subscribers_num

    # Format the lines together and get their net change as well.
    for key in sorted(subscriber_dictionary, reverse=True):
        day_t = datetime.datetime.strptime(key, '%Y-%m-%d').date()
        previous_day = day_t + datetime.timedelta(-1)
        previous_day = str(previous_day.strftime('%Y-%m-%d'))

        line = "| {} | {} | {} |"
        subscriber_count = subscriber_dictionary[key]
        try:
            subscriber_previous = subscriber_dictionary[previous_day]
            net_change = subscriber_count - subscriber_previous

            if net_change > 0:  # Add a '+' if it's positive:
                day_changes.append(net_change)
                net_change = '+' + str(net_change)

        except KeyError:  # No previous day recorded.
            net_change = '---'

        new_line = line.format(key, subscriber_count, net_change)
        formatted_lines.append(new_line)

    # Get the average change of subscribers per day.
    if len(day_changes) >= 2:
        average_change = round(sum(day_changes) / len(day_changes), 2)
        if average_change > 0:  # Add a + for clarity if it's positive.
            average_change = "+{}".format(average_change)
        average_change_section = "*Average Daily Change*: {} subscribers.\n\n".format(average_change)
    else:
        average_change_section = ""

    # Format the actual body of the table.
    subscribers_header = ("| Date | Subscribers | Net Change |\n"
                          "|------|-------------|------------|\n")
    body = average_change_section + subscribers_header + '\n'.join(formatted_lines)

    return body


def subreddit_statistics_recorder(subreddit_name, start_time, end_time, daily_mode=False):
    """
    This function takes posts from a given subreddit and tabulates how many belonged to each flair, and how many total.

    :param subreddit_name: Name of a subreddit.
    :param start_time: Posts older than this UNIX time will be ignored.
    :param end_time: Posts younger than this UNIX time will be ignored.
    :param daily_mode: True if this is just to download the day's stats, False if we are initializing a subreddit.
    :return:
    """

    statistics_dictionary = {}
    all_flairs = []
    no_flair_count = 0

    # Access the subreddit.
    subreddit_name = subreddit_name.lower()
    r = reddit.subreddit(subreddit_name)

    # Set the limit of how many posts to fetch depending on whether or not this is just fetching the day's stats.
    if daily_mode:
        fetch_limit = 100
    else:
        fetch_limit = 1000

    # Iterate over our fetched posts.
    for result in r.new(limit=fetch_limit):

        # Check that the time parameters are correct.
        result_created = result.created_utc
        if result_created > end_time:  # This is after the time we want.
            continue
        elif result_created < start_time:  # This is older than the time we want
            continue

        # Once that's taken care of, we can process our results.
        result_text = result.link_flair_text

        # Iterate.
        if result_text is not None:
            all_flairs.append(result_text)
        else:
            no_flair_count += 1

    # Get an alphabetized list of the flairs we have.
    alphabetized_list = list(set(all_flairs))
    for flair in alphabetized_list:
        statistics_dictionary[flair] = all_flairs.count(flair)  # Get the number of posts with this flair.

    # Add the ones that do not have flair.
    if no_flair_count > 0:
        statistics_dictionary['None'] = no_flair_count

    return statistics_dictionary


def subreddit_statistics_recorder_daily(subreddit, date_string):
    """
    This is a function that checks the database for `subreddit_statistics_recorder` data.
    It merges it if it finds data already, otherwise it adds it as a new daily entry.

    :param  subreddit: The subreddit we're checking for.
    :param date_string: A date string in the model of YYYY-MM-DD.
    :return:
    """
    subreddit = subreddit.lower()
    day_start = date_convert_to_unix(date_string)  # Convert it from YYYY-MM-DD to Unix time.
    day_end = day_start + 86399

    cursor_data.execute("SELECT * FROM subreddit_statistics WHERE subreddit = ? and date = ?", (subreddit, date_string))
    results = cursor_data.fetchone()

    if results is None:
        day_data = str(subreddit_statistics_recorder(subreddit, day_start, day_end, daily_mode=True))
        cursor_data.execute("INSERT INTO subreddit_statistics VALUES (?, ?, ?)", (subreddit, date_string, day_data))
        conn_data.commit()
        logger.info('[Artemis] Stat Recorder Daily: Stored statistics for r/{} for {}.'.format(subreddit, date_string))
    else:
        logger.info('[Artemis] Stat Recorder Daily: Statistics already stored for r/{} for {}.'.format(subreddit,
                                                                                                       date_string))

    return


def subreddit_statistics_collater(subreddit, start_date, end_date):
    """
    A function that looks at the information stored for a certain time period and generates a Markdown table for it.

    :param subreddit: The community we are looking for.
    :param start_date: The start date, expressed as YYYY-MM-DD we want to get stats from.
    :param end_date: The end date, expressed as YYYY-MM-DD we want to get stats from.
    :return: A nice Markdown table.
    """

    main_dictionary = {}
    final_dictionary = {}
    table_lines = []
    total_amount = 0
    subreddit = subreddit.lower()

    # Convert those days into Unix integers.
    start_unix = date_convert_to_unix(start_date)  # We get the Unix time of these dates, midnight UTC
    end_unix = date_convert_to_unix(end_date) + 86399  # End of this particular day, right before midnight UTC

    # Access our database.
    cursor_data.execute("SELECT * FROM subreddit_statistics WHERE subreddit = ?", (subreddit,))
    results = cursor_data.fetchall()

    if len(results) == 0:  # There is no information stored.
        return None
    else:  # Iterate over the returned information.
        for result in results:
            stored_date = date_convert_to_unix(result[1])  # Convert the stored YYYY-MM-DD string to Unix UTC.
            stored_data = eval(result[2])  # Take the dictionary of statistics stored per day.

            # If the date of the data fits between our parameters, we combine the dictionaries.
            if start_unix <= stored_date <= end_unix:
                for key in (main_dictionary.keys() | stored_data.keys()):
                    if key in main_dictionary:
                        final_dictionary.setdefault(key, []).append(main_dictionary[key])
                    if key in stored_data:
                        final_dictionary.setdefault(key, []).append(stored_data[key])

    # We get the total amount of all posts during this time period here.
    for count in final_dictionary.values():
        total_amount += sum(count)

    # Format the lines of the table. Each line represents a flair and how many posts were flaired as it.
    for key, value in sorted(final_dictionary.items()):
        posts_num = sum(value)  # Number of posts matching this flair
        percentage = round((posts_num / total_amount)*100, 2)  # Percent of the overall total that were this flair.
        if key == "None":  # We italicize this entry since it represents unflaired posts.
            key_formatted = "*None*"
        else:
            key_formatted = key
        entry_line = '| {} | {} | {}% |'.format(key_formatted, sum(value), percentage)  # Format the table's line.
        table_lines.append(entry_line)

    # Add the total line that tabulates how many posts were posted in total. We put this at the end of the table.
    table_lines.append("| **Total** | {} | 100% |".format(total_amount))

    # Format the whole table.
    table_header = ("| Post Flair | Number of Submissions | Percentage |\n"
                    "|------------|-----------------------|------------|\n")
    table_body = table_header + '\n'.join(table_lines)

    return table_body


def subreddit_pushshift_oldest_retriever(subreddit_name):
    """
    This function accesses the Pushshift API to retrieve the oldest posts ever on a subreddit.
    It also formats it as a bulleted Markdown list.

    :param subreddit_name: The community we are looking for.
    :return:
    """

    num_to_get = 3  # How many of the oldest posts we want to get.
    formatted_lines = []
    api_search_query = "https://api.pushshift.io/reddit/search/submission/?subreddit={}&sort=asc&size={}"
    
    # Get the data from Pushshift as JSON.
    retrieved_data = requests.get(api_search_query.format(subreddit_name, num_to_get))
    returned_submissions = retrieved_data.json()['data']

    # Iterate over the returned submissions and get their attributes.
    line_template = '* "[{}]({})", posted on {}'
    for submission in returned_submissions:
        post_title = submission['title'].strip()
        post_link = submission['full_link']
        post_created = date_convert_to_string(int(submission['created_utc']))  # Convert to YYYY-MM-DD in UTC
        new_line = line_template.format(post_title, post_link, post_created)  # Format the bulleted line.
        formatted_lines.append(new_line)

    # Format the returned Markdown text.
    header = "\n\n### Oldest Submissions\n\n"
    oldest_section = header + '\n'.join(formatted_lines)

    return oldest_section


def subreddit_pushshift_time_top_retriever(subreddit_name, start_time, end_time):
    """
    This function accesses Pushshift to retrieve the TOP posts on a subreddit for a given timespan.
    It also formats it as a bulleted Markdown list.
    The function is currently NOT used because it takes a long time to run and create PRAW submission objects
    for each returned ID. It could probably be paired with a SQLite table later.
    
    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time, expressed in Unix time.
    :param end_time: We want to find posts *before* this time, expressed in Unix time.
    :return:
    """

    number_to_return = 5  # How many top posts we want.
    number_to_query = 100

    # Convert YYYY-MM-DD to Unix time.
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time)

    formatted_lines = []
    dict_by_score = {}
    api_search_query = ("https://api.pushshift.io/reddit/search/submission/?subreddit={}"
                        "&sort_type=score&sort=desc&after={}&before={}&size={}")

    # Get the data from Pushshift as JSON.
    retrieved_data = requests.get(api_search_query.format(subreddit_name, start_time, end_time, number_to_query))
    returned_submissions = retrieved_data.json()['data']
    
    # Iterate over the returned submissions and get their IDs.
    for submission in returned_submissions:
        
        # Take the ID, fetch the PRAW submission object, and append that object to our list.
        praw_submission = reddit.submission(id=submission['id'])  # Get the actual PRAW object. This takes a while.
        praw_submission_score = praw_submission.score
        dict_by_score[praw_submission_score] = praw_submission  # Use the score as a dictionary key.
    
    # Iterate over the PRAW submissions that are sort by highest score.
    line_template = "* [{}]({}) (`+{}`), posted on {}."
    for item in list(sorted(dict_by_score.keys(), reverse=True)[:number_to_return]):
        relevant_submission = dict_by_score[item]
        title = relevant_submission.title
        score = relevant_submission.score
        link = relevant_submission.permalink
        created = date_convert_to_string(relevant_submission.created_utc)  # Convert to YYYY-MM-DD in UTC.
        new_line = line_template.format(title, link, score, created)  # Format the new line.
        formatted_lines.append(new_line)

    # Put it all together.
    header = "\n\n##### Most Popular Posts\n\n"
    body = header + "\n".join(formatted_lines)

    return body


def subreddit_pushshift_time_authors_retriever(subreddit_name, start_time, end_time, search_type):
    """
    This function accesses Pushshift to retrieve the top FREQUENT submitters/commenters on a subreddit
    for a given timespan. It also formats the data as a bulleted Markdown list.
    
    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time, expressed in Unix time.
    :param end_time: We want to find posts *before* this time, expressed in Unix time.
    :param search_type: `comment` or `submission`, depending on the type of top results one wants.
    :return:
    """

    # Convert YYYY-MM-DD to Unix time.
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time)
    
    number_to_return = 3  # The number of top entries we want.
    formatted_lines = []
    api_search_query = ("https://api.pushshift.io/reddit/search/{}/?subreddit={}"
                        "&sort_type=score&sort=desc&after={}&before={}&aggs=author&size=0")

    # Get the data from Pushshift as JSON.
    retrieved_data = requests.get(api_search_query.format(search_type, subreddit_name, start_time, end_time))
    returned_authors = retrieved_data.json()['aggs']['author']

    # Code to remove AutoModerator and [deleted] from the authors list.
    excluded_usernames = ['AutoModerator', '[deleted]']

    # Iterate over the data and collect the top authors.
    bullet_number = 1
    line_template = "{}. {} {}s by u/{}"
    for author in returned_authors[:(number_to_return * 2)]:
        submitter = author['key']
        if submitter not in excluded_usernames:
            submit_count = author['doc_count']
            new_line = line_template.format(bullet_number, submit_count, search_type, submitter)
            formatted_lines.append(new_line)
            bullet_number += 1
    
    # Format everything together.
    if search_type == 'submission':  # Change the header depending on the type.
        header = "\n\n##### Top Submitters\n\n"
    else:
        header = "\n\n##### Top Commenters\n\n"
        
    if len(formatted_lines) > 0:  # We have entries for this month.
        body = header + '\n'.join(formatted_lines[:number_to_return])
    else:  # We do not have any entries.
        body = header + "* It appears that there were no {} during this time period.".format(search_type)

    return body


def subreddit_pushshift_activity_retriever(subreddit_name, start_time, end_time, search_type):
    """
    This function accesses Pushshift to retrieve the activity, including MOST submissions or comments,
    on a subreddit for a given timespan. It also formats it as a bulleted Markdown list.
    It also calculates the total AVERAGE over this time period and includes it at a separate line at the end.
    
    :param subreddit_name: The community we are looking for.
    :param start_time: We want to find posts *after* this time, expressed in Unix time.
    :param end_time: We want to find posts *before* this time, expressed in Unix time.
    :param search_type: `comment` or `submission`, depending on the type of top results one wants.
    :return:
    """

    # Convert YYYY-MM-DD UTC to Unix time.
    start_time = date_convert_to_unix(start_time)
    end_time = date_convert_to_unix(end_time)

    number_to_return = 3  # The number of top days of activity we want.
    days_data = {}
    days_highest = []
    lines_to_post = []
    unavailable = "* It appears that there were no {}s during this time period.".format(search_type)

    api_search_query = ("https://api.pushshift.io/reddit/search/{}/?subreddit={}"
                        "&sort_type=created_utc&after={}&before={}&aggs=created_utc&size=0")

    # Get the data from Pushshift as JSON.
    retrieved_data = requests.get(api_search_query.format(search_type, subreddit_name, start_time, end_time))
    returned_days = retrieved_data.json()['aggs']['created_utc']

    # Iterate over the data.
    for day in returned_days:
        day_string = date_convert_to_string(int(day['key']))  # Convert to YYYY-MM-DD
        num_of_posts = int(day['doc_count'])
        if num_of_posts > 0:
            days_data[num_of_posts] = day_string

    # Find the average number of the type.
    if len(days_data.keys()) > 0:  # We want to make sure we actually have posts. Can't average zero.
        num_average = round(sum(days_data.keys()) / len(days_data.keys()), 2)
        average_line = "\n\n*Average {0}s per day*: **{1}** {0}s.".format(search_type, num_average)
    else:
        average_line = str(unavailable)

    # Find the busiest day.
    most_posts = sorted(zip(days_data.keys()), reverse=True)[:number_to_return]
    for number in most_posts:
        days_highest.append(number[0])

    # Format the lines.
    for day in days_highest:
        line = "* **{}** {}s on **{}**".format(day, search_type, days_data[day])
        lines_to_post.append(line)

    # Format the text body.
    header = "\n\n##### {}s Activity\n\n**Most Active Days**\n\n".format(search_type.title())
    if len(lines_to_post) > 0:  # There are days recorded.
        body = header + '\n'.join(lines_to_post) + average_line
    else:  # No days recorded.
        body = header + unavailable

    return body


def subreddit_statistics_retriever(subreddit_name):
    """
    A function that gets ALL of the information on a subreddit's statistics and returns it as Markdown tables
    sorted by month.

    :param subreddit_name:
    :return:
    """

    list_of_dates = []
    formatted_data = []
    subreddit_name = subreddit_name.lower()

    # First we want to get all the data.
    cursor_data.execute("SELECT * FROM subreddit_statistics WHERE subreddit = ?", (subreddit_name,))
    results = cursor_data.fetchall()

    if len(results) == 0:  # Nothing found.
        return
    else:
        for result in results:
            stored_date = result[1]
            list_of_dates.append(stored_date)

    # Get all the months that are between our two dates.
    list_of_dates = sorted(list_of_dates)  # Arrange it oldest to newest.
    oldest_date = list_of_dates[0]
    newest_date = list_of_dates[-1]
    intervals = [oldest_date, newest_date]
    start, end = [datetime.datetime.strptime(_, "%Y-%m-%d") for _ in intervals]
    list_of_months = list(OrderedDict(((start + datetime.timedelta(_)).strftime("%Y-%m"),
                                       None) for _ in range((end - start).days)).keys())

    # Iterate per month
    for entry in list_of_months:
        # Get the first and last day per month.
        year = int(entry.split('-')[0])
        month = int(entry.split('-')[1])
        first_day = "{}-01".format(entry)
        last_day = "{}-{}".format(entry, calendar.monthrange(year, month)[1])

        # Get the main statistics data.
        month_header = "### {}\n\n#### Activity".format(entry)
        month_table = subreddit_statistics_collater(subreddit_name, first_day, last_day)

        # Get the supplementary Pushshift data (most frequent posters, activity, etc.)
        # First we get the Pushshift activity data. How many submissions/comments per day, most active days, etc.
        supplementary_data = subreddit_pushshift_activity_retriever(subreddit_name, first_day, last_day, 'submission')
        supplementary_data += subreddit_pushshift_activity_retriever(subreddit_name, first_day, last_day, 'comment')
        # Secondly, we get the top submitters/commenters. People who submitted or commented the most.
        supplementary_data += subreddit_pushshift_time_authors_retriever(subreddit_name, first_day, 
                                                                         last_day, 'submission')
        supplementary_data += subreddit_pushshift_time_authors_retriever(subreddit_name, first_day, last_day, 'comment')

        # Pull the single month entry together.
        month_body = month_header + supplementary_data + "\n\n#### Submissions by Flair\n\n" + month_table
        formatted_data.append(month_body)  # Add it to the list.

    # Collect all the month entries. Reverse them so the newest is listed first.
    formatted_data.reverse()
    oldest_posts = subreddit_pushshift_oldest_retriever(subreddit_name)  # Get the three oldest posts in the sub.
    total_data = "\n\n".join(formatted_data) + oldest_posts

    return total_data


def get_series_of_days(start_day, end_day):
    """
    A function that takes two date strings and returns a list of all days that are between those two days.
    For example, if passed `2018-11-01` and `2018-11-03`, it will also give back a list like this: 
    ['2018-11-01', '2018-11-02', '2018-11-03'].

    :param start_day: YYYY-MM-DD to start.
    :param end_day: YYYY-MM-DD to end.
    :return: A list of days in YYYY-MM-DD.
    """

    days_list = []

    start_day = datetime.datetime.strptime(start_day, "%Y-%m-%d")  # Convert to datetime object.
    end_day = datetime.datetime.strptime(end_day, "%Y-%m-%d")  # Convert to datetime object.
    delta = end_day - start_day  # Time difference between the two.

    # Iterate and get steps of a day each and append to list.
    for i in range(delta.days + 1):
        days_list.append(str((start_day + datetime.timedelta(i)).strftime('%Y-%m-%d')))

    return days_list


def subreddit_statistics_whole_month(subreddit_name):
    """
    This function is used when a subreddit is added to the moderation list for the first time.
    We basically go through each day since the start of the month until the day before the present, and download stats
    for each day.

    :param subreddit_name:
    :return: Nothing, but it will save to the database.
    """

    # Set our time variables.
    subreddit_name = subreddit_name.lower()
    current_time = time.time()
    yesterday = date_convert_to_string(current_time-86400)
    current_month = str(datetime.datetime.utcfromtimestamp(current_time).strftime("%Y-%m"))
    month_start = current_month + "-01"

    # Check to make sure that our starting point isn't in the previous month.
    if current_month not in yesterday:  # If the current YYYY-MM is not in the yesterday's date (say 2018-10-31)
        # Then we do *not* want to get the data because it will be incomplete and we are at the start of the month.
        return

    # Otherwise, we're good to go.
    list_of_days_to_get = get_series_of_days(month_start, yesterday)

    # Iterate over the days and get the proper data.
    for day in list_of_days_to_get:
        subreddit_statistics_recorder_daily(subreddit_name, day)

    logger.info('[Artemis] Statistics Whole Month: Retrieved current month statistics for r/{}.'.format(subreddit_name))

    return


"""WIKIPAGE FUNCTION"""


def wikipage_creator(subreddit_name):
    """
    Checks if there is already a wikipage called `AssistantBOT_statistics`. If there isn't one, it creates it.
    :param subreddit_name: Name of a subreddit.
    :return:
    """
    page_name = "{}_statistics".format(USERNAME)  # The wikipage title to edit or create.
    r = reddit.subreddit(subreddit_name)

    # Check if the page is there.
    try:
        page_exist = len(r.wiki[page_name].content_md)
    except prawcore.exceptions.NotFound:  # There is no wiki page for Artemis's statistics.
        page_exist = False

    # Create the page if it doesn't exist.
    if not page_exist:
        time_till_midnight = round((date_next_midnight() / 3600), 2)  # Find out how long till midnight UTC.
        new_page = r.wiki.create(name=page_name, content=WIKIPAGE_BLANK.format(time_till_midnight),
                                 reason="Creating the {} statistics wiki page.".format(USERNAME))
        new_page.mod.update(listed=False, permlevel=2)  # Remove it from the public list and only let moderators see it.
        new_page.mod.add(USERNAME)
        logger.info("[Artemis] Wikipage Creator: Created a new statistics wiki page for r/{}.".format(subreddit_name))
    else:  # The page already exists.
        logger.debug("[Artemis] Wikipage Creator: Statistics wiki page for r/{} already exists.".format(subreddit_name))

    return


def wikipage_collater(subreddit_name):
    """
    This function collates all the information together and forms the Markdown text used to update the wikipage.

    :param subreddit_name:
    :return:
    """

    # Get the current status of the bot's operations.
    start_time = time.time()
    status = wikipage_status_collater(subreddit_name)

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

    # Compile the entire page together.
    body = WIKIPAGE_TEMPLATE.format(status, statistics_section, subscribers_section,
                                    traffic_section, VERSION_NUMBER, time_elapsed, today)
    logger.info("[Artemis] Wikipage Collater: Statistics page content for r/{} collated.".format(subreddit_name))

    return body


def wikipage_editor(subreddit_name):
    """
    This function takes the body text from the above function and updates the wikipage.

    :param subreddit_name: Name of a subreddit.
    :return:
    """

    date_today = date_convert_to_string(time.time())  # Convert to YYYY-MM-DD
    r = reddit.subreddit(subreddit_name)

    # Make sure that we have a page to write to.
    wikipage_creator(subreddit_name)
    statistics_wikipage = r.wiki["{}_statistics".format(USERNAME.lower())]

    # Add our text to the page.
    text_to_add = wikipage_collater(subreddit_name)
    statistics_wikipage.edit(content=text_to_add, reason='Updating with statistics data from {}.'.format(date_today))

    logger.info('[Artemis] Wikipage Editor: Successfully edited page for r/{} w/ {} info.'.format(subreddit_name,
                                                                                                  date_today))

    return


def wikipage_status_collater(subreddit_name):
    """
    This function generates a Markdown chunk of text to include in the edited wikipage. The chunk notes the various
    settings of Artemis. This chunk is placed in the header of the edited wikipage.

    :param subreddit_name: The name of a monitored subreddit.
    :return: A markdown chunk.
    """

    subreddit_name = subreddit_name.lower()
    days_of_data = []

    # Get the date.
    current_time = int(time.time())
    current_day = date_convert_to_string(current_time)  # Convert to YYYY-MM-DD

    # Get flair enforcing status.
    flair_enforce_status = "**Flair Enforcing**: {}"
    current_status = database_monitored_subreddits_enforce_status(subreddit_name)
    if current_status:  # Enforcing is on.
        flair_enforce_status = flair_enforce_status.format("`On`")

        # Get flair enforcing default/strict status (basically, does it have the `posts` moderator permission?)
        flair_enforce_mode = "\n\n* Flair Enforcing Mode: {}"
        current_permissions = main_obtain_mod_permissions(subreddit_name)
        if 'posts' in current_permissions:
            flair_enforce_status += flair_enforce_mode.format('`Strict`')
        else:
            flair_enforce_status += flair_enforce_mode.format('`Default`')

    else:
        flair_enforce_status = flair_enforce_status.format("`Off`")

    # We get the earliest day we have subscriber traffic for. (this gives us an idea of how long we've monitored)
    statistics_data_since = "**Statistics Recorded Since**: {}"
    cursor_data.execute("SELECT * FROM subreddit_subscribers WHERE subreddit = ?", (subreddit_name,))
    results = cursor_data.fetchall()

    if len(results) == 0:  # We don't have results. We must have just started monitoring this sub.
        statistics_data_since = statistics_data_since.format(current_day)  # Set the date to today.
    else:  # We have results. Take the earliest day.

        # Get all the days in a list.
        for entry in results:
            date = entry[1]  # Take the entry as YYYY-MM-DD
            days_of_data.append(date)  # Add it to our list.

        earliest_date = list(sorted(days_of_data))[0]  # Sort the list of days and get the earliest.
        statistics_data_since = statistics_data_since.format(earliest_date)

    # Compile it together.
    status_chunk = "{}\n\n{}".format(flair_enforce_status, statistics_data_since)
    logger.debug(("[Artemis] Status Collater: Compiled settings for r/{}.".format(subreddit_name)))

    return status_chunk


"""FLAIR ENFORCING FUNCTIONS"""


def flair_notifier(post_object, message_to_send):
    """
    This function takes a PRAW Submission object - that of a post that is missing flair - and messages its author
    about the missing flair. It lets them know that they should select a flair.

    :param post_object: The PRAW Submission object of the post that's missing a flair.
    :param message_to_send: The text of the body we want to send to the author.
    :return:
    """

    # Get some basic variables.
    author = post_object.author.name
    active_subreddit = str(post_object.subreddit)
    subject_text = "[Notification] ⚠ Your post on r/{} needs a post flair!".format(active_subreddit)

    # Format the message.
    message_body = message_to_send + BOT_DISCLAIMER.format(active_subreddit)

    # Send the message.
    reddit.redditor(author).message(subject_text, message_body)
    logger.debug("[Artemis] Notifier: Messaged u/{} about their post on r/{}.".format(author, active_subreddit))

    return


def flair_none_saver(post_object):
    """
    This function removes a post that lacks flair and saves it to the database to check later.
    It saves the post ID as well as the time it was created. Another function will check them later to see if they
    have been assigned a flair.

    :param post_object: The PRAW Submission object of the post that's missing a flair.
    :return:
    """

    # Get the unique Reddit ID of the post.
    post_id = post_object.id

    # First we want to check if the post ID has already been saved.
    cursor_data.execute("SELECT * FROM posts_filtered WHERE post_id = ?", (post_id,))
    result = cursor_data.fetchone()

    if result is None:  # ID has not been saved before. We can save it.
        created = int(post_object.created_utc)
        cursor_data.execute("INSERT INTO posts_filtered VALUES (?, ?)", (post_id, created))
        conn_data.commit()
        logger.info("[Artemis] Flair Saver: Added post {} to the filtered database".format(post_id))
    else:  # ID is already in database.
        logger.info('[Artemis] Flair Saver: The post {} is already in the filtered database.'.format(post_id))

    return


def flair_is_user_mod(query_username, subreddit_name):
    """
    This function checks to see if a user is a moderator in the sub they posted in.
    Artemis won't remove an unflaired post if it's by a moderator.

    :param query_username: The username of the person.
    :param subreddit_name: The subreddit in which they posted a comment.
    :return: True if they are a moderator, False if they are not.
    """

    moderators_list = []  # Make a list of the subreddit moderators.

    # Fetch the moderator list.
    for moderator in reddit.subreddit(subreddit_name).moderator():
        moderators_list.append(moderator.name.lower())

    if query_username.lower() in moderators_list:  # This user is a moderator.
        logger.debug("[Artemis] Is User Mod: u/{} is a mod of r/{}.".format(query_username, subreddit_name))
        return True
    else:  # User is not a moderator.
        logger.debug("[Artemis] Is User Mod: u/{} is not a mod of r/{}.".format(query_username, subreddit_name))
        return False


"""MAIN FUNCTIONS"""


def main_error_log_(entry):
    """
    A function to save errors to a log for later examination.
    This one is more basic and does not include the last comments or submission text.
    The advantage is that it can be shared between different routines, as it does not depend on PRAW.

    :param entry: The text we wish to include in the error log entry. Typically this is the traceback.
    :return: Nothing.
    """
    bot_version = "Artemis v{}".format(VERSION_NUMBER)

    # Open the file for the error log in appending mode.
    f = open(FILE_ADDRESS_ERROR, 'a+', encoding='utf-8')

    # Add the error entry formatted our way.
    error_date_format = datetime.datetime.utcnow().strftime("%Y-%m-%d %I:%M:%S UTC")
    f.write("\n-----------------------------------\n{} ({})\n{}".format(error_date_format, bot_version, entry))
    f.close()

    logger.debug("[Artemis] Error Log: Error at {} recorded to the error log.".format(error_date_format))

    return


def main_backup_daily():
    """
    This function backs up the database file to a secure Box account. It does not back up the credentials file.
    This is called by the master timer during its daily routine.

    :return:
    """

    current_day = date_convert_to_string(time.time())

    if not os.path.isdir(BACKUP_FOLDER):  # Check to see if Box is mounted.
        logger.error("[Artemis] Main Backup: >> It appears that the backup disk may not be mounted.")
        return False
    else:
        new_folder_path = "{}/{}".format(BACKUP_FOLDER, current_day)  # Make a new folder /YYYY-MM-DD.
        print(new_folder_path)
        if os.path.isdir(new_folder_path):  # There already is a folder with today's date.
            logger.info("[Artemis] Main Backup: Backup folder for {} already exists.".format(current_day))
            return False
        else:  # We can back up.
            os.makedirs(new_folder_path)  # Create the new target folder.
            source_files = os.listdir(SOURCE_FOLDER)  # Get the list of files (incl. extensions) from our home folder.

            # We don't need to back up files with these extensions. Exclude them from backup.
            exclude_keywords = ['.json', '.py', 'journal']
            source_files = [x for x in source_files if not any(keyword in x for keyword in exclude_keywords)]

            # Iterate over each file and back it up.
            for file_name in source_files:

                # Get the full path of the file.
                full_file_name = os.path.join(SOURCE_FOLDER, file_name)

                if os.path.isfile(full_file_name):  # If the file exists, try backing it up.
                    try:
                        shutil.copy(full_file_name, new_folder_path)
                    except OSError:  # Copying error. Skip it.
                        pass

            logger.info('[Artemis] Main Backup: Completed for {}.'.format(current_day))

        return True


def main_multireddit_update():
    """
    A simple function that keeps a multireddit called `monitored` up-to-date and in sync with the actual list of
    communities Artemis assists with.

    :return:
    """
    online_list = []

    # Get the local list from the database of all our monitored subreddits.
    local_list = database_monitored_subreddits_retrieve()

    # Access the online version of the multireddit.
    mr = reddit.multireddit(USERNAME, 'monitored')
    multireddit_subs = mr.subreddits
    for sub in multireddit_subs:
        online_list.append(str(sub.display_name.lower()))

    # Find the differences between the two.
    num_local_list = len(local_list)
    num_online_list = len(online_list)

    # The list of monitored subs is NOT the same as the multireddit. We want to make sure they are in sync.
    if num_local_list != num_online_list:
        if num_local_list > num_online_list:  # We need to *add* to the multireddit, as local is more than online.
            to_add = True
            differences = list(set(local_list) - set(online_list))
        else:  # This means we need to *remove* from the multireddit as there are more online than local.
            to_add = False
            differences = list(set(online_list) - set(local_list))

        if to_add:  # We need to add subs from the multireddit.
            for subreddit in differences:
                mr.add(subreddit)  # Add the community to the online list.
        else:  # We need to remove subs from the multireddit.
            for subreddit in differences:
                mr.remove(subreddit)  # Remove the community from the online list.

        logger.info("[Artemis] Multireddit Update: Updated the multireddit with: {}. Add is {}.".format(differences,
                                                                                                        to_add))

    return


def main_login():
    """
    A simple function to log in to Reddit.

    :return: Nothing, but a global `reddit` variable is declared.
    """

    global reddit  # Declare the connection as a global variable.

    # Authenticate the connection.
    reddit = praw.Reddit(client_id=APP_ID, client_secret=APP_SECRET, password=PASSWORD,
                         user_agent=USER_AGENT, username=USERNAME)
    logger.info("[Artemis] v{} Startup: Logging in as u/{}.".format(VERSION_NUMBER, USERNAME))

    return


def main_timer():
    """
    This function helps time certain routines to be done only at specific times or days of the month.

    Daily at midnight: Retrieve number of subscribers.
                       Record post statistics.

    5th day of every month: Retrieve subreddit traffic.

    :return:
    """

    action_time = 0
    month_action_day = 5

    # Get the hour (24-hour) as a zero-padded digit.
    current = time.time()
    previous_date_string = date_convert_to_string(current-86400)
    current_date_string = date_convert_to_string(current)
    current_hour = int(datetime.datetime.utcfromtimestamp(current).strftime('%H'))
    current_date_only = datetime.datetime.utcfromtimestamp(current).strftime('%d')

    # Get the list of all our monitored subreddits.
    monitored_list = database_monitored_subreddits_retrieve()

    if current_hour != action_time:  # Update it after midnight.
        return

    # Iterate over the communities we're monitoring.
    for community in monitored_list:

        # Check to see if we have acted upon this.
        act_command = 'SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?'
        cursor_data.execute(act_command, (community, current_date_string))
        if cursor_data.fetchone():
            # We have already updated this subreddit for today.
            logger.debug("[Artemis] Main Timer: Statistics already updated for r/{}".format(community))
            continue

        logger.info("[Artemis] Main Timer: Beginning daily update for r/{}.".format(community))

        # Update the number of subscribers and get the statistics for the previous day.
        subreddit_subscribers_recorder(community)
        subreddit_statistics_recorder_daily(community, previous_date_string)
        logger.info("[Artemis] Main Timer: Recorded number of subscribers for r/{}.".format(community))

        # Update the post statistics.
        wikipage_editor(community)
        cursor_data.execute("INSERT INTO subreddit_updated VALUES (?, ?)", (community, current_date_string))
        logger.info("[Artemis] Main Timer: Updated statistics wikipage for r/{}.".format(community))

        # Update the multireddit.
        main_multireddit_update()

        # If we are deployed on Linux (Raspberry Pi), also run the backup and cleanup routine.
        if sys.platform == "linux":  # Linux
        
            # Backup data files.
            main_backup_daily()
            
            # Clean up the `posts_processed` database table.
            # database_cleanup()

        # If it's a certain day of the month, also get the traffic data.
        if int(current_date_only) == month_action_day:
            subreddit_traffic_recorder(community)
            logger.info("[Artemis] Main Timer: Recorded traffic information for r/{}.".format(community))

        logger.info("[Artemis] Main Timer: Completed daily update for r/{}.".format(community))

    return


def main_initialization(subreddit_name):
    """
    This is a function that is called when a moderator invite is accepted for the first time.
    It fetches the traffic data, the subscriber data, and also tries to get all the statistics for the current month
    into the database.
    It also

    :param subreddit_name: Name of a subreddit.
    :return: Nothing.
    """

    # Get post statistics for the current month, dating all the way back to the first of the month.
    subreddit_statistics_whole_month(subreddit_name)

    # Get the traffic data that is stored.
    subreddit_traffic_recorder(subreddit_name)

    # Get the subscriber data for the current moment.
    subreddit_subscribers_recorder(subreddit_name)

    # Create the wikipage for statistics with a default message.
    wikipage_creator(subreddit_name)

    logger.info('[Artemis] Initialization: Initialized data for new monitored subreddit r/{}.'.format(subreddit_name))

    return


def main_obtain_mod_permissions(subreddit_name):
    """
    A function to check if Artemis has mod permissions in a subreddit, and what kind of mod permissions it has.

    :param subreddit_name: Name of a subreddit.
    :return: A tuple. First item is True/False on whether Artemis is a moderator. Second item is permissions, if any.
    """
    am_moderator = False
    my_permissions = None
    list_of_moderators = reddit.subreddit(subreddit_name).moderator()  # Get the list of moderators.

    # Iterate over the list of moderators to see if Artemis is in it.
    for moderator in list_of_moderators:

        if moderator == USERNAME:  # This is me!
            am_moderator = True
            my_permissions = moderator.mod_permissions  # Get the permissions I have as a list. e.g. `['wiki']`

    mod_log = '[Artemis] Mod Permissions: Artemis r/{} moderator status is {}. Permissions are {}.'
    logger.debug(mod_log.format(subreddit_name, am_moderator, my_permissions))

    return am_moderator, my_permissions


def main_messaging():
    """
    The basic function for checking for moderator invites to a subreddit, and accepting them.
    This function also accepts enabling or disabling flair enforcing if Artemis gets a message with either
    `Enable` or `Disable` from a SUBREDDIT. A message from a moderator user account does *not* count.
    There is also a function that removes the SUBREDDIT from being monitored when de-modded.

    :return:
    """

    # Iterate over the inbox.
    for message in reddit.inbox.unread(limit=10):
        message.mark_read()

        # Get the variables of the message.
        msg_subject = message.subject.lower()
        msg_subreddit = message.subreddit

        # Only accept PMs. This excludes, say, comment replies.
        if not message.fullname.startswith('t4_'):
            logger.debug('[Artemis] Messaging: Inbox item is not a message. Skipped.')
            continue

        # Reject non-subreddit messages. This includes messages from regular users.
        if msg_subreddit is None:
            logger.debug('[Artemis] Messaging: Message "{}" is not from a subreddit. Skipped.'.format(msg_subject))
            continue

        if 'invitation to moderate' in msg_subject:  # This is an auto-generated moderation invitation message.

            # Accept the invitation to moderate.
            logger.info("[Artemis] Messaging: New moderation invite from r/{}.".format(msg_subreddit))
            try:
                message.subreddit.mod.accept_invite()  # Accept the invite.
                logger.info("[Artemis] Messaging: Invite accepted.")
            except praw.exceptions.APIException:  # Invite already accepted error.
                logger.error("[Artemis] Messaging: Moderation invite error. Already accepted?")
                continue
            new_subreddit = message.subreddit.display_name.lower()

            # Add the subreddit to our monitored list.
            database_subreddit_insert(new_subreddit)

            # Fetch initialization data for this subreddit.
            main_initialization(new_subreddit)

            # Reply to the subreddit confirming the invite.
            current_permissions = main_obtain_mod_permissions(str(msg_subreddit))
            if current_permissions[0]:  # We are a moderator
                # Fetch the list of moderator permissions we have. This will be an empty list if Artemis is a mod
                # but has no actual permissions.
                list_of_permissions = current_permissions[1]
                mode = "Default"  # By default, Artemis will
                mode_component = ""
                # This subreddit has opted for the strict mode.
                if 'posts' in list_of_permissions and 'wiki' in list_of_permissions:
                    mode = "Strict"
                    mode_component = MSG_ACCEPT_STRICT
                elif 'wiki' not in list_of_permissions:
                    # We were invited to be a mod but don't have the proper permissions. Let the mods know.
                    message.reply(MSG_ACCEPT_WRONG_PERMISSIONS + BOT_DISCLAIMER.format(msg_subreddit))
                    logger.info("[Artemis] Messaging: I don't have the right permissions. Replied to subreddit.")
            else:
                return  # Exit as we are not a moderator.

            # Check for the templates that are available to Artemis.
            # Get how many flair templates we can find.
            template_number = len(subreddit_templates_retrieve(str(msg_subreddit)))
            if template_number == 0:  # There are no publicly available flairs for this sub. Let the mods know.
                template_section = MSG_ACCEPT_NO_FLAIRS
            else:  # We have access to X number of templates on this subreddit.
                template_section = "\nI found the following {} templates on this subreddit:\n\n".format(template_number)
                template_section += subreddit_templates_collater(str(msg_subreddit))

            body = MSG_ACCEPT_INVITE.format(msg_subreddit, mode_component, template_section)
            message.reply(body + BOT_DISCLAIMER.format(msg_subreddit))
            logger.info("[Artemis] Messaging: Sent confirmation reply to moderators. Set to {} mode.".format(mode))

            # Post a message to Artemis's profile noting that it is now active on the appropriate subreddit.
            status_title = "Accepted mod invite to r/{}".format(str(msg_subreddit))
            subreddit_url = 'https://www.reddit.com/r/{}'.format(str(msg_subreddit))
            reddit.subreddit("u_AssistantBOT").submit(title=status_title, url=subreddit_url, send_replies=False)

        else:  # Check for messages from subreddits Artemis monitors.
            monitored_list = database_monitored_subreddits_retrieve()  # Retrieve the currently monitored list.

            if str(msg_subreddit).lower() not in monitored_list:

                # We got a message but we are not monitoring that subreddit.
                not_monitored_log = "[Artemis] Messaging: New actable message but subreddit r/{} is not monitored."
                logger.debug(not_monitored_log.format(msg_subreddit))
                continue

            if 'enable' in msg_subject:

                # This is a request to toggle ON the flair_enforce status of the subreddit.
                logger.info('[Artemis] Messaging: New message to enable r/{} flair enforcing.'.format(msg_subreddit))
                database_monitored_subreddits_enforce_change(str(msg_subreddit), True)
                message.reply(MSG_MOD_ENABLE.format(msg_subreddit) + BOT_DISCLAIMER.format(msg_subreddit))

            elif 'disable' in msg_subject:

                # This is a request to toggle OFF the flair_enforce status of the subreddit.
                logger.info('[Artemis] Messaging: New message to disable r/{} flair enforcing.'.format(msg_subreddit))
                database_monitored_subreddits_enforce_change(str(msg_subreddit), False)
                message.reply(MSG_MOD_DISABLE.format(msg_subreddit) + BOT_DISCLAIMER.format(msg_subreddit))

            elif 'has been removed' in msg_subject:

                # Artemis was removed as a mod from a subreddit. Delete from monitored.
                logger.info("[Artemis] Messaging: New demod message from r/{}.".format(msg_subreddit))
                database_subreddit_delete(str(msg_subreddit))
                message.reply(MSG_LEAVE.format(msg_subreddit))
                logger.info("[Artemis] Messaging: Sent demod confirmation reply to moderators.")

    return


def main_flair_checker():
    """
    This function checks the database of posts that have been filtered out for lacking a flair.
    It examines each one to see if they now have a flair, and if they do, it restores them to the subreddit by approving
    the post.
    This function will also clean the database of posts that are older than 24 hours.

    :return:
    """

    # Access the database.
    cursor_data.execute("SELECT * FROM posts_filtered")
    results = cursor_data.fetchall()

    if len(results) == 0:  # Nothing found in the filtered database.
        return
    else:  # We have posts to look over.

        for result in results:

            # Define basic variables
            post_id = result[0]
            created = result[1]
            working_submission = reddit.submission(id=post_id)  # Get the PRAW object of this submission.
            post_subreddit = str(working_submission.subreddit)
            post_css = working_submission.link_flair_css_class
            post_flair_text = working_submission.link_flair_text

            # Check to see if the post now has a flair.
            if post_css is None and post_flair_text is None:  # Still no flair for this post.

                logger.debug("[Artemis] Flair Checker: Post {} on r/{} still has no flair.".format(post_id,
                                                                                                   post_subreddit))
                continue  # We do not restore this post.

            else:  # This post now has a flair. We want to restore it if possible.

                # Get our permissions for this subreddit.
                current_permissions = main_obtain_mod_permissions(post_subreddit)
                if not current_permissions[0]:  # Artemis is not a mod of this subreddit. Don't do anything.
                    continue
                else:
                    current_permissions = current_permissions[1]  # Collect the permissions as a list.

                if 'posts' in current_permissions:  # Make sure we have the power to approve and remove posts.

                    log_message = "[Artemis] Flair Checker: Post {} on r/{} has been approved as it now has a flair."
                    logger.info(log_message.format(post_id, post_subreddit))

                    # Approve the post.
                    working_submission.mod.approve()

                    # Message the OP that it's been approved.
                    try:  # Check to see if user is a valid target.
                        post_author = working_submission.author.name
                    except AttributeError:
                        # Author is deleted. We don't care about this post.
                        post_author = None

                    # There is an author to send to.
                    if post_author is not None:
                        post_permalink = working_submission.permalink
                        subject_line = "[Notification] 😊 Your flaired post is approved on r/{}!".format(post_subreddit)
                        body = (MSG_FLAIR_APPROVAL.format(post_permalink, post_subreddit) +
                                BOT_DISCLAIMER.format(post_subreddit))
                        reddit.redditor(post_author).message(subject_line, body)
                        send_log = "[Artemis] Flair Checker: Sent a message to u/{} about their approved post {}."
                        logger.info(send_log.format(post_author, post_id))

                    # Remove the post from database now that it's been flaired.
                    database_delete_filtered_post(post_id)

            # Age check. If the entry is over 24 hours old, we want to delete it.
            current_time = time.time()
            if (current_time - created) >= 86400:  # This post is older than 24 hours.

                # Delete it from our database.
                database_delete_filtered_post(post_id)
                log_message = '[Artemis] Flair Checker: Post {} is over 24 hrs old. Deleted from the filtered database.'
                logger.info(log_message.format(post_id))
            else:
                continue

    return


def main_get_submissions():
    """
    This function checks all the monitored subreddits' submissions and checks for new posts.
    If a new post does not have a flair, it will send a message to the submitter asking them to select a flair.
    If Artemis has `posts` mod permissions on a subreddit, it will *also* remove that post until the user
    selects a flair.

    :return:
    """

    posts = []

    # First, get the list of all our monitored subreddits that want flair enforcing.
    monitored_list = database_monitored_subreddits_retrieve()
    for community in monitored_list:
        # We remove subreddits that have opted out of flair enforcing.
        if not database_monitored_subreddits_enforce_status(community):
            monitored_list.remove(community)
    monitored_string = "+".join(monitored_list)
    logger.debug('[Artemis] Get: Retrieving submissions from "{}".'.format(monitored_string))

    # Access the posts.
    posts += list(reddit.subreddit(monitored_string).new(limit=25))
    posts.reverse()  # Reverse it so that we start processing the older ones first. Newest ones last.

    # Iterate over the fetched posts. We have a number of built-in checks to reduce the amount of lifting.
    for post in posts:

        # Check to see if the post has already been processed.
        post_id = post.id
        cursor_data.execute('SELECT * FROM posts_processed WHERE post_id = ?', (post_id,))
        if cursor_data.fetchone():
            # Post is already in the database
            logger.debug('[Artemis] Get: Post {} already recorded in the processed database. Skipped.'.format(post_id))
            continue

        # Check if the author exists second.
        try:
            post_author = post.author.name
        except AttributeError:
            # Author is deleted. We don't care about this post.
            logger.debug(('[Artemis] Get: Post {} author is deleted. Skipped.'.format(post_id)))
            continue

        # Post age check, third.
        current_time = time.time()
        post_created_time = post.created_utc  # Unix time when this post was created.
        time_difference = current_time - post_created_time  # How many second old this post is.
        minimum_age = 300  # In seconds
        maximum_age = 21600  # In seconds
        
        if time_difference < minimum_age:

            # We give OPs `minimum_age` seconds to choose a flair. If it's a post that's younger than this, skip.
            logger.debug('[Artemis] Get: Post {} is under {} seconds old. Skipped.'.format(post_id, minimum_age))
            continue

        elif time_difference > maximum_age:

            # If the time difference is greater than `maximum_age` seconds, skip.
            # For example, Artemis may have just been invited to moderate a subreddit.
            # We don't want to go and start messaging everyone for old posts.
            logger.debug('[Artemis] Get: Post {} is over {} seconds old. Skipped.'.format(post_id, maximum_age))

            continue

        # Define basic attributes of the post.
        post_flair_css = post.link_flair_css_class
        post_flair_text = post.link_flair_text
        post_permalink = post.permalink
        post_title = post.title
        post_subreddit = str(post.subreddit).lower()

        # Insert this post's ID into the database.
        cursor_data.execute('INSERT INTO posts_processed VALUES(?)', (post_id,))
        conn_data.commit()
        log_line = ('[Artemis] Get: New Post "{}" on r/{} (https://redd.it/{}), flaired with "{}". '
                    'Added to the processed database.')
        logger.info(log_line.format(post_title, post_subreddit, post_id, post_flair_text))

        # We check for posts that have no flairs whatsoever.
        if post_flair_css is None and post_flair_text is None:  # This post has no flair.

            # Get our permissions for this subreddit.
            current_permissions = main_obtain_mod_permissions(post_subreddit)
            if not current_permissions[0]:  # We are not a mod of this subreddit. Don't do anything.
                continue
            else:
                current_permissions = current_permissions[1]  # Collect the permissions as a list.

            # Check to see if the author is a moderator.
            if flair_is_user_mod(post_author, post_subreddit):

                # If they are, don't do anything.
                logger.info('[Artemis] Get: Post author u/{} is a moderator of r/{}. Skipped.'.format(post_author,
                                                                                                      post_subreddit))
                continue

            # Retrieve the available flairs as a Markdown list. This will be blank if there aren't actually flairs.
            available_templates = subreddit_templates_collater(post_subreddit)
            logger.info("[Artemis] Get: Post on r/{} (https://redd.it/{}) is unflaired.".format(post_subreddit,
                                                                                                post_id))

            # Remove the post if we have the permission to do so.
            moderator_mail_link = MSG_FLAIR_MOD_MSG.format(post_subreddit, post_permalink)  # Format the mod mail link.
            if 'posts' in current_permissions:  # We are in strict enforcement mode.

                # Write the object to the filtered database.
                flair_none_saver(post)

                # Remove the post.
                post.mod.remove()
                logger.info("[Artemis] Get: Also removed post {} and added to the filtered database.".format(post_id))

                # We will tell OP that their post has been removed.
                # Format the message to the user, incorporating the list of templates.

                message_to_send = MSG_FLAIR_YOUR_POST.format(post_author, post_subreddit, available_templates,
                                                             post_permalink, moderator_mail_link, MSG_FLAIR_REMOVAL)

            else:  # We are not in strict enforcement mode. Just send them a normal message.
                message_to_send = MSG_FLAIR_YOUR_POST.format(post_author, post_subreddit, available_templates,
                                                             post_permalink, moderator_mail_link, "")

            # Send the flair reminder message to the user.
            flair_notifier(post, message_to_send)
            logger.info("[Artemis] Get: Sent a message to u/{} about their unflaired post {}.".format(post_author,
                                                                                                      post_id))

        else:  # This post has a flair. We don't need to process it.

            logger.debug('[Artemis] Get: Post {} already has a flair. Doing nothing.'.format(post_id))

            continue

    return


'''RUNNING THE BOT'''

# This is the actual loop that runs the top-level MAIN functions of the bot.

# Log in and authenticate with Reddit.
main_login()

try:
    while True:
        # noinspection PyBroadException
        try:
            main_messaging()
            main_get_submissions()
            main_flair_checker()
            main_timer()
        except Exception as e:  # The bot encountered an error/exception.
            # Format the error text.
            error_entry = traceback.format_exc()
            
            # Artemis will not log common connection issues.
            if any(keyword in error_entry for keyword in CONNECTION_ERRORS):
                logger.debug(error_entry)
            else:  # Error is not a connection error. Log it.
                main_error_log_(error_entry)  # Write the error to the error log.
                logger.error(error_entry)  # Also record the error in the events log.

        time.sleep(WAIT)  # Sleep until the next run.
        
except KeyboardInterrupt:  # Manual termination of the script with Ctrl-C.
    logger.info('[Artemis] v{} Manual shutdown.'.format(VERSION_NUMBER))
    sys.exit()
