#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import datetime
import os
import re
import sys
import time
import traceback
from ast import literal_eval
from calendar import monthrange
from collections import Counter, OrderedDict
from shutil import copy
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import praw
import prawcore
import psutil
import requests
from requests.exceptions import ConnectionError

import connection
import database
import timekeeping
from common import flair_sanitizer, logger, main_error_log
from settings import AUTH, FILE_ADDRESS, SETTINGS, SOURCE_FOLDER
from text import *


"""LOGGING IN"""

connection.login()
reddit = connection.reddit
reddit_helper = connection.reddit_helper
CYCLES = 0

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
    current_month = timekeeping.month_convert_to_string(time.time())

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
        date_string = timekeeping.time_convert_to_string(date[0])
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
    days_in_month = monthrange(year, datetime.datetime.now().month)[1]
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
    current_month = timekeeping.month_convert_to_string(time.time())

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
        year_month = timekeeping.month_convert_to_string(unix_month_time)

        # This would also save the data for the current month, which is
        # fine except that traffic data usually has initial gaps.
        # Therefore, this function is run twice. It will update the
        # numbers with whatever is most recent.
        if current_month != year_month and month_uniques > 0 and month_pageviews > 0:
            traffic_dictionary[year_month] = [month_uniques, month_pageviews]

    # Check for pre-existing traffic data stored in the database.
    sql_command = "SELECT * FROM subreddit_traffic WHERE subreddit = ?"
    database.CURSOR_STATS.execute(sql_command, (subreddit_name,))
    result = database.CURSOR_STATS.fetchone()

    # If the data has not been saved before, add it as a new entry.
    # Otherwise, if saved traffic data already exists merge the data.
    if result is None:
        data_package = (subreddit_name, str(traffic_dictionary))
        database.CURSOR_STATS.execute("INSERT INTO subreddit_traffic VALUES (?, ?)",
                                      data_package)
        database.CONN_STATS.commit()
        logger.debug('Traffic Recorder: Traffic data for r/{} added.'.format(subreddit_name))
    else:
        existing_dictionary = literal_eval(result[1])
        new_dictionary = existing_dictionary.copy()
        new_dictionary.update(traffic_dictionary)

        update_command = "UPDATE subreddit_traffic SET traffic = ? WHERE subreddit = ?"
        database.CURSOR_STATS.execute(update_command, (str(new_dictionary), subreddit_name))
        database.CONN_STATS.commit()
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
    correlated_data = {}
    formatted_lines = []
    all_uniques = []
    all_pageviews = []
    all_uniques_changes = []
    all_pageviews_changes = []
    top_month_uniques = None
    top_month_pageviews = None
    basic_line = "| {} | {} | {:,} | *{}%* | {} | {:,} | *{}%* | {} | {} | {}"

    # Look for the traffic data in our database.
    subreddit_name = subreddit_name.lower()
    database.CURSOR_STATS.execute("SELECT * FROM subreddit_traffic WHERE subreddit = ?",
                                  (subreddit_name,))
    results = database.CURSOR_STATS.fetchone()

    # If we have data, convert it back into a dictionary.
    # Otherwise, return `None.
    if results is not None:
        traffic_dictionary = literal_eval(results[1])
        if not len(traffic_dictionary):  # Empty dictionary.
            return None
    else:
        return None

    # Fetch some submission / comment data from Pushshift's database
    # for integration into the overall traffic table.
    for search_type in ['submission', 'comment']:
        correlated_data[search_type] = {}
        earliest_month = list(traffic_dictionary.keys())[0] + "-01"
        stat_query = ("https://api.pushshift.io/reddit/search/{}/?subreddit={}&after={}"
                      "&aggs=created_utc&frequency=month&size=0".format(search_type,
                                                                        subreddit_name,
                                                                        earliest_month))
        retrieved_data = subreddit_pushshift_access(stat_query)
        returned_months = retrieved_data['aggs']['created_utc']

        for entry in returned_months:
            month = timekeeping.month_convert_to_string(entry['key'])
            count = entry['doc_count']
            if not count:
                formatted_count = "N/A"
            else:
                formatted_count = "{:,}".format(count)
            correlated_data[search_type][month] = formatted_count

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
                                 ratio_uniques_pageviews,
                                 correlated_data['submission'].get(key, "N/A"),
                                 correlated_data['comment'].get(key, "N/A"))
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
        current_month = timekeeping.month_convert_to_string(time.time())
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
            x_ratio = 1 + (est_pageviews_change * .01)

            # Interpolate estimated number of posts and comments based
            # on the Pushshift data and the ratio we have for pageviews.
            now_posts = int(correlated_data['submission'].get(current_month, "0").replace(',', ''))
            est_posts = "{:,.0f}".format(now_posts * x_ratio)
            now_comments = int(correlated_data['comment'].get(current_month, "0").replace(',', ''))
            est_comments = "{:,.0f}".format(now_comments * x_ratio)
        except (KeyError, ZeroDivisionError):
            est_uniques_change = est_pageviews_change = ratio_est_uniques_pageviews = "---"
            est_posts = est_comments = "N/A"

        estimated_line = basic_line.format("*{} (estimated)*".format(current_month), "",
                                           estimated_uniques, est_uniques_change, "",
                                           estimated_pageviews, est_pageviews_change,
                                           ratio_est_uniques_pageviews, est_posts, est_comments)

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
              "Pageviews | Pageviews % Change | Uniques : Pageviews | "
              "Total Posts | Total Comments |"
              "\n|-------|----|---------|------------------|----|------|"
              "--------------------|---------------------|-----|-----|\n")
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
        except (ValueError, ConnectionError, HTTPError, requests.exceptions.ChunkedEncodingError):
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
    current_day = timekeeping.convert_to_string(current_time)

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
    database.subscribers_insert(subreddit_name, data_package)

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
    subscriber_dictionary = database.subscribers_retrieve(subreddit_name)
    if subscriber_dictionary is None:
        return None

    # Get the founding date of the subreddit, by checking the local
    # database, or the object itself if not monitored. If the local
    # database does not contain the date, check the subreddit.
    try:
        created = database.extended_retrieve(subreddit_name)['created_utc']
        founding_date = timekeeping.convert_to_string(created)
    except TypeError:
        try:
            founding_epoch = reddit.subreddit(subreddit_name).created_utc
            founding_date = timekeeping.convert_to_string(founding_epoch)
        except prawcore.exceptions.Forbidden:
            # No access to a private subreddit. In case of this very
            # unlikely situation, set the founding date to the epoch.
            founding_date = "1970-01-01"

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
        day_limit = SETTINGS.num_display_subscriber_days
        if previous_day in subscriber_dictionary and day_index <= day_limit:
            subscriber_previous = subscriber_dictionary[previous_day]
            net_change = subscriber_count - subscriber_previous
        elif day_index > day_limit and "-01" in date[-3:]:
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
            days_difference = timekeeping.num_days_between(later_date, date)
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
        if day_index <= day_limit or day_index > day_limit and "-01" in date[-3:]:
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
    sample_size = SETTINGS.subscriber_sample_size
    last_few_entries = []

    # Access the database.
    results = database.subscribers_retrieve(subreddit_name)

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
    for milestone in SETTINGS.milestones:
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
        if days_until_milestone > SETTINGS.subscriber_milestone_upper or days_until_milestone < 0:
            milestone_format = None
        else:
            # Format the next milestone as a string. If the next
            # milestone is within four months, just include it as days.
            # Otherwise, format the next time string in months instead.
            unix_next_milestone_string = timekeeping.convert_to_string(unix_next_milestone)
            if days_until_milestone <= SETTINGS.subscriber_milestone_format_days:
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
    dictionary_total = database.subscribers_retrieve(subreddit_name)

    # Exit if there is no data.
    if dictionary_total is None:
        return None

    # Get the last number of recorded subscribers.
    current_subscribers = dictionary_total[list(sorted(dictionary_total.keys()))[-1]]
    milestones_to_check = [x for x in SETTINGS.milestones if x <= current_subscribers]

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
    founding_date = timekeeping.convert_to_string(reddit.subreddit(subreddit_name).created_utc)
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
        days_difference = timekeeping.num_days_between(previous_date, date)

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
    subscribers for each day if it can, namely by grabbing data in
    chunks and analyzing them for subscriber count.

    :param subreddit_name: Name of a subreddit.
    :param fetch_today: Whether we should get just today's stats, or a
                        list of stats from March 15, 2018 onwards.
    :return:
    """
    subscribers_dictionary = {}
    chunk_size = SETTINGS.pushshift_subscriber_chunks
    logger.info('Subscribers PS: Retrieving historical '
                'subscribers for r/{}...'.format(subreddit_name))

    # If we just want to get today's stats just create a list with today
    # as the only component. Otherwise, fetch a list of days since March
    # 15, which is when subscriber information became available on
    # Pushshift's database.
    if not fetch_today:
        yesterday = int(time.time()) - 86400
        yesterday_string = timekeeping.convert_to_string(yesterday)

        # Insert check for subreddit age. If the subreddit was created
        # after the default start date of March 15, 2018, use the
        # creation date as the starting point instead.
        subreddit_created = int(reddit.subreddit(subreddit_name).created_utc)
        subreddit_created_date = timekeeping.convert_to_string(subreddit_created)
        if SETTINGS.pushshift_subscriber_start > subreddit_created_date:
            start_date = SETTINGS.pushshift_subscriber_start
        else:
            start_date = subreddit_created_date
        logger.info("Subscribers PS: Retrieval will start from {}.".format(start_date))
        list_of_days_to_get = timekeeping.get_series_of_days(start_date, yesterday_string)
    else:
        today_string = timekeeping.convert_to_string(time.time())
        list_of_days_to_get = [today_string]

    api_search_query = ("https://api.pushshift.io/reddit/search/submission/"
                        "?subreddit={}&after={}&before={}&sort_type=created_utc"
                        "&fields=subreddit_subscribers,created_utc&size=750")

    # Get the data from Pushshift as JSON. We try to get a submission
    # per day and record the subscribers.
    list_chunked = [list_of_days_to_get[i:i + chunk_size] for i in range(0,
                                                                         len(list_of_days_to_get),
                                                                         chunk_size)]

    # Iterate over our chunks of days.
    for chunk in list_chunked:
        processed_days = []

        # Set time variables.
        first_day = chunk[0]
        start_time = timekeeping.convert_to_unix(first_day)
        last_day = chunk[-1]
        end_time = timekeeping.convert_to_unix(last_day) + 86399

        # Access Pushshift for the data.
        retrieved_data = subreddit_pushshift_access(api_search_query.format(subreddit_name,
                                                                            start_time, end_time))
        if 'data' not in retrieved_data:
            continue
        else:
            returned_data = retrieved_data['data']

        # Process the days in our chunk and get the earliest matching
        # submission's subscriber count for each day.
        for day in chunk:
            for unit in returned_data:
                unit_day = timekeeping.convert_to_string(int(unit['created_utc']))
                if unit_day not in processed_days and day == unit_day:
                    subscribers = int(unit['subreddit_subscribers'])
                    subscribers_dictionary[unit_day] = subscribers
                    processed_days.append(unit_day)
                    logger.info("Subscribers PS: Data for {}: "
                                "{:,} subscribers.".format(unit_day, subscribers))

        # Check to see if all the days are accounted for in our chunk.
        # If there are missing days, we pull a manual check for those.
        # This check involves getting just a single submission from the
        # day, usually the earliest one.
        processed_days.sort()
        if processed_days != chunk:
            missing_days = [x for x in chunk if x not in processed_days]
            logger.info("Subscribers PS: Still missing data for {}. "
                        "Retrieving individually.".format(missing_days))

            # If there are multiple missing days, run a quick check
            # to see if there are *any* posts at all in the time
            # frame. If they aren't any, skip and do not fetch
            # individual data for each day.
            if len(missing_days) > 1:
                first_day = timekeeping.convert_to_unix(missing_days[0])
                last_day = timekeeping.convert_to_unix(missing_days[-1]) + 86399
                multiple_missing_query = ("https://api.pushshift.io/reddit/search/submission/"
                                          "?subreddit={}&after={}&before={}&sort_type=created_utc"
                                          "&size=1".format(subreddit_name, first_day, last_day))
                multiple_data = subreddit_pushshift_access(multiple_missing_query).get('data',
                                                                                       None)
                if not multiple_data:
                    logger.info('Subscribers PS: No posts from {} to {}. '
                                'Skipping chunk...'.format(missing_days[0], missing_days[-1]))
                    continue

            for day in missing_days:
                day_start = timekeeping.convert_to_unix(day)
                day_end = day_start + 86399
                day_query = ("https://api.pushshift.io/reddit/search/submission/?subreddit={}"
                             "&after={}&before={}&sort_type=created_utc&size=1")
                day_data = subreddit_pushshift_access(day_query.format(subreddit_name, day_start,
                                                                       day_end))

                if 'data' not in day_data:
                    continue
                else:
                    returned_submission = day_data['data']

                # We have data here, so let's add it to the dictionary.
                if len(returned_submission) > 0:
                    if 'subreddit_subscribers' in returned_submission[0]:
                        subscribers = returned_submission[0]['subreddit_subscribers']
                        subscribers_dictionary[day] = int(subscribers)
                        logger.info("Subscribers PS: Individual data for {}: "
                                    "{:,} subscribers.".format(day, subscribers))

    # If we have data we can save it and insert it into the database.
    if len(subscribers_dictionary.keys()) != 0:
        database.subscribers_insert(subreddit_name, subscribers_dictionary)
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
        response = urlopen("http://redditmetrics.com/r/{}/".format(subreddit_name))
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
        date_string_num = timekeeping.convert_to_unix(date_string)
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
    database.subscribers_insert(subreddit_name, final_dictionary)

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
    result = database.activity_retrieve(subreddit_name, 'oldest', 'oldest')

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
                                                                            SETTINGS.num_display))

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
                                    date_data['author'], timekeeping.convert_to_string(date))
        formatted_lines.append(line)

    oldest_section = header + '\n'.join(formatted_lines)

    # Save it to the database if there isn't a previous record of it and
    # if we have data.
    if result is None and len(oldest_data) != 0 and len(oldest_data) >= SETTINGS.num_display:
        database.activity_insert(subreddit_name, 'oldest', 'oldest', oldest_data)

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
    number_to_query = SETTINGS.pushshift_top_check_num

    # Convert YYYY-MM-DD to Unix time and get the current month as a
    # YYYY-MM string.
    start_time_string = str(start_time)
    start_time = timekeeping.convert_to_unix(start_time)
    end_time = timekeeping.convert_to_unix(end_time)
    current_month = timekeeping.convert_to_string(time.time())

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
    last_day = "{}-{}".format(month_string, monthrange(year, month)[1])

    # Get the current month. We don't want to save the data if it is in
    # the current month, which is not over.
    current_month = timekeeping.convert_to_string(time.time())
    score_sorted = []
    formatted_lines = []
    line_template = "* `{:+}` [{}]({}), posted by u/{} on {}"

    # First we check the database to see if we already have saved data.
    # If there is, we use that data.
    result = database.activity_retrieve(subreddit_name, month_string, 'popular_submission')
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
    for item in score_sorted[:SETTINGS.num_display]:
        my_score = item[0]
        my_id = item[1]
        my_date = timekeeping.convert_to_string(dictionary_data[my_id]['created_utc'])
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
        store_limit = SETTINGS.num_display * 2
        for submission_id in list(dictionary_data.keys()):
            if not any(submission_id == entry[1] for entry in score_sorted[:store_limit]):
                del dictionary_data[submission_id]

        # Store the dictionary data to our database.
        database.activity_insert(subreddit_name, month_string, 'popular_submission',
                                 dictionary_data)

    # Put it all together as a formatted chunk of text.
    body = "\n\n**Most Popular Posts**\n\n" + "\n".join(formatted_lines)

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
    start_time = timekeeping.convert_to_unix(start_time)
    end_time = timekeeping.convert_to_unix(end_time)
    current_month = timekeeping.convert_to_string(time.time())
    activity_index = "authors_{}".format(search_type)

    # Check the database first.
    authors_data = database.activity_retrieve(subreddit_name, specific_month, activity_index)

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
                error_message = "\n\n**Top Submitters**\n\n"
            else:
                error_message = "\n\n**Top Commenters**\n\n"

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
            database.activity_insert(subreddit_name, specific_month, activity_index, authors_data)

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
        header = "\n\n**Top Submitters**\n\n"
    else:
        header = "\n\n**Top Commenters**\n\n"

    # If we have entries for this month, format everything together.
    # Otherwise, return a section noting there's nothing.
    if len(formatted_lines) > 0:
        body = header + '\n'.join(formatted_lines[:SETTINGS.num_display])
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
    # When getting the `end_time`, Artemis will get it from literally
    # the last second of the day to account for full coverage.
    num_days = timekeeping.num_days_between(start_time, end_time) + 1
    specific_month = start_time.rsplit('-', 1)[0]
    start_time = timekeeping.convert_to_unix(start_time)
    end_time = timekeeping.convert_to_unix(end_time) + 86399
    current_month = timekeeping.convert_to_string(time.time())
    activity_index = "activity_{}".format(search_type)

    # Check the database first.
    days_data = database.activity_retrieve(subreddit_name, specific_month, activity_index)

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
            error_message = "\n\n**{}s Activity**\n\n".format(search_type)
            error_message += ("* There was an temporary issue retrieving this information. "
                              "Artemis will attempt to re-access the data at "
                              "the next statistics update.")
            return error_message

        returned_days = retrieved_data['aggs']['created_utc']

        # Iterate over the data. If the number of posts in a day is more
        # than zero, save it.
        for day in returned_days:
            day_string = timekeeping.convert_to_string(int(day['key']))
            num_of_posts = int(day['doc_count'])
            if num_of_posts != 0:
                days_data[day_string] = num_of_posts

        # Write to the database if we are not in the current month.
        if specific_month != current_month:
            database.activity_insert(subreddit_name, specific_month, activity_index, days_data)

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
        average_line = "\n\n*Average {0}s per day*: **{1:,}** {0}s.".format(search_type,
                                                                            int(num_average))
    else:
        average_line = str(unavailable)

    # Find the busiest days and add those days to a list with the date.
    most_posts = sorted(zip(input_dictionary.values()), reverse=True)[:SETTINGS.num_display]
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
    header = "\n\n**{}s Activity**\n\n*Most Active Days:*\n\n".format(search_type.title())
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
        oldest_day_string = timekeeping.convert_to_string(oldest_full_day)

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

    # Access the subreddit. By default, this will use the helper account
    # in order to reduce the API use on the main account. However, if
    # the subreddit is private, the bot will use the regular account.
    r = reddit_helper.subreddit(subreddit_name)
    try:
        if r.subreddit_type is 'private':
            r = reddit.subreddit(subreddit_name)
    except prawcore.exceptions.Forbidden:
        return {}

    # Iterate over our fetched posts. Newest posts will be returned
    # first, oldest posts last. Consider 1000 to be a MAXIMUM limit, as
    # the loop will exit early if results are all too old.
    for result in r.new(limit=1000):

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
            if old_post_count < SETTINGS.old_post_limit:
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
    day_start = timekeeping.convert_to_unix(date_string)
    day_end = day_start + 86399

    results = database.statistics_posts_retrieve(subreddit)

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
        database.statistics_posts_insert(subreddit, day_data)
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
    format_dictionary = {}
    table_lines = []
    total_amount = 0
    total_days = []  # The days of data that we are evaluating.

    # Convert those days into Unix integers.
    # We get the Unix time of the start date dates at midnight UTC and
    # the end of this end day, right before midnight UTC.
    start_unix = timekeeping.convert_to_unix(start_date)
    end_unix = timekeeping.convert_to_unix(end_date) + 86399

    # Access our database.
    results = database.statistics_posts_retrieve(subreddit)

    if results is None:
        # There is no information stored. Return `None`.
        return None
    else:
        # Iterate over the returned information.
        # For each day, convert the stored YYYY-MM-DD string to Unix UTC
        # and then take the dictionary of statistics stored per day.
        for date, value in results.items():
            stored_date = timekeeping.convert_to_unix(date)
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

    # Go through the dictionary and combine equivalent flairs. # NEW
    for key, value in sorted(final_dictionary.items()):
        # We italicize this entry since it represents unflaired posts.
        # Note that it was previously marked with the string "None",
        # rather than the value `None`.
        if key == "None":
            key_formatted = "*None*"
        elif "//" in key:
            # Splitting the Layer7 dev reply keys off. See the docs:
            # https://bitbucket.org/layer7solutions/bungie-replied/
            key_formatted = flair_sanitizer(key.split('//')[0].strip(), False)
        else:
            key_formatted = flair_sanitizer(key, False)

        if key_formatted in format_dictionary:
            format_dictionary[key_formatted] += sum(value)
        else:
            format_dictionary[key_formatted] = sum(value)

    # Combine the flairs and form them into a table. One line per
    # post flair entry.
    for key, value in sorted(format_dictionary.items()):
        # Calculate the percent that have this flair.
        percentage = value / total_amount

        # Format the table's line.
        entry_line = '| {} | {:,} | {:.2%} |'.format(key, value, percentage)
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
    results = database.statistics_posts_retrieve(subreddit_name)

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

    # Get all the months that are between our two dates with results.
    oldest_date = list_of_dates[0]
    newest_date = list_of_dates[-1]
    intervals = [oldest_date, newest_date]
    start, end = [datetime.datetime.strptime(_, "%Y-%m-%d") for _ in intervals]
    list_of_months = list(OrderedDict(((start + datetime.timedelta(_)).strftime("%Y-%m"),
                                       None) for _ in range((end - start).days)).keys())

    # If there are results from the first day, we add the current month
    # as well. This is to allow for results from the first day to appear
    # in the update on the second day. Otherwise, because the first day
    # begins at midnight the latest month will not be included
    if newest_date.endswith('-01') and newest_date[:-3] not in list_of_months:
        list_of_months.append(newest_date[:-3])

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
        if entry == timekeeping.convert_to_string(current_time):
            last_day = timekeeping.convert_to_string(current_time - 86400)
        else:
            last_day = "{}-{}".format(entry, monthrange(year, month)[1])

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
    yesterday = timekeeping.convert_to_string(current_time - 86400)
    time_start = subreddit_statistics_earliest_determiner(subreddit_name)

    # Otherwise, we're good to go. We get data from the start of our
    # data till yesterday. (Today is not over yet)
    series_days = timekeeping.get_series_of_days(time_start, yesterday)
    actual_days_to_get = timekeeping.get_historical_series_days(series_days)

    # If there is nothing returned, then it's probably a sub that gets
    # TONS of submissions, so we make it a single list with one item.
    if not actual_days_to_get:
        actual_days_to_get = [timekeeping.convert_to_string(current_time)]

    # Now we fetch literally all the possible posts we can from Reddit
    # and put it into a list.
    posts += list(reddit.subreddit(subreddit_name).new(limit=1000))
    for post in posts:
        day_created = timekeeping.convert_to_string(post.created_utc)

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
    database.statistics_posts_insert(subreddit_name, saved_dictionary)
    logger.info('Statistics Retrieve All: Got monthly statistics for r/{}.'.format(subreddit_name))

    return


def subreddit_userflair_counter(subreddit_name):
    """This function if called on a subreddit with the `flair`
    permission, allows for Artemis to tally the popularity of
    userflairs. It has two modes:

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
    flair_list = [x['css_class'] for x in list(relevant_sub.flair.templates)]
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
              "* **Userflair statistics last recorded**: {}\n"
              "* **Subscribers with flair**: {:,} ({:.2%} of total subscribers)\n"
              "* **Number of used flairs**: {}")

    # If there are subscribers, calculate the percentage of those who
    # have userflairs. Otherwise, include a boilerplate string.
    if relevant_sub.subscribers > 0:
        flaired_percentage = users_w_flair / relevant_sub.subscribers
    else:
        flaired_percentage = '---'
    body = header.format(timekeeping.convert_to_string(time.time()), users_w_flair,
                         flaired_percentage, len(usage_index))

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
    page_name = "{}_statistics".format(AUTH.username[:12].lower())
    r = reddit.subreddit(subreddit_name)

    # Check if the page is there by trying to get the text of the page.
    # This will fail if the page does NOT exist. It will also fail
    # if the bot does not have enough permissions to create it.
    # That will throw a `Forbidden` exception.
    try:
        statistics_test = r.wiki[page_name].content_md

        # If the page exists, then we get the PRAW Wikipage object here.
        stats_wikipage = r.wiki[page_name]
        log_message = ("Wikipage Creator: Statistics wiki page for r/{} "
                       "already exists with length {}.")
        logger.debug(log_message.format(subreddit_name, statistics_test))
    except prawcore.exceptions.NotFound:
        # There is no wiki page for Artemis's statistics. Let's create
        # the page if it doesn't exist. Also add a message if statistics
        # gathering will be paused due to the subscriber count being
        # below the minimum (`SETTINGS.min_s_stats`).
        try:
            reason_msg = "Creating the Artemis statistics wiki page."
            stats_wikipage = r.wiki.create(name=page_name,
                                           content=WIKIPAGE_BLANK.format(SETTINGS.min_s_stats),
                                           reason=reason_msg)

            # Remove the statistics wiki page from the public list and
            # only let moderators see it. Also add Artemis as a approved
            # submitter/editor for the wiki.
            stats_wikipage.mod.update(listed=False, permlevel=2)
            stats_wikipage.mod.add(AUTH.username)
            logger.info("Wikipage Creator: Created new statistics "
                        "wiki page for r/{}.".format(subreddit_name))
        except prawcore.exceptions.NotFound:
            # There is a wiki on the subreddit itself,
            # but we can't edit it.
            stats_wikipage = None
            logger.info("Wikipage Creator: Wiki is present, "
                        "but insufficient privileges to edit wiki on r/{}.".format(subreddit_name))
    except prawcore.exceptions.Forbidden:
        # The wiki doesn't exist and Artemis can't create it.
        stats_wikipage = None
        logger.info("Wikipage Creator: Insufficient mod privileges "
                    "to edit wiki on r/{}.".format(subreddit_name))

    # Add bot as wiki contributor.
    try:
        r.wiki.contributor.add(AUTH.username)
    except prawcore.exceptions.Forbidden:
        logger.info("Wikipage Creator: Unable to add bot as "
                    "approved wiki contributor.")

    return stats_wikipage


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
    today = timekeeping.convert_to_string(start_time)

    # Check extended data to see if there are advanced settings in
    # there. If there is, add a link to the configuration page.
    # If there isn't any, leave that part as blank.
    extended_data = database.extended_retrieve(subreddit_name)
    if extended_data is not None:
        if 'custom_name' in extended_data:
            config_link = ("[🎚️ Advanced Config](https://www.reddit.com/r/{}"
                           "/wiki/assistantbot_config) • ".format(subreddit_name))

    # Compile the entire page together.
    body = WIKIPAGE_TEMPLATE.format(subreddit_name, status, statistics_section,
                                    subscribers_section, traffic_section, AUTH.version_number,
                                    time_elapsed, today, connection.CONFIG.announcement,
                                    config_link)
    logger.debug("Wikipage Collater: Statistics page for r/{} collated.".format(subreddit_name))

    return body


def wikipage_get_new_subreddits():
    """This function checks the last few submissions for the bot and
    returns a list of the ones that invited it since the last statistics
    run time. This is to tell wikipage_editor whether or not it needs to
    send an initial message to the subreddit moderators about their
    newly updated statistics page.

    :return: A list of subreddits that were added between yesterday's
             midnight UTC and the last one. Empty list otherwise.
    """
    new_subreddits = []

    # Get the last midnight UTC from a day ago.
    yesterday_string = timekeeping.convert_to_string(time.time() - 86400)
    today_string = timekeeping.convert_to_string(time.time())
    yesterday_midnight_utc = timekeeping.convert_to_unix(yesterday_string)
    today_midnight_utc = timekeeping.convert_to_unix(today_string)

    # Iterate over the last few subreddits on the user page that are
    # recorded as having added the bot. Get only moderator invites
    # posts and skip other sorts of posts.
    for result in reddit_helper.subreddit('u_{}'.format(AUTH.username)).new(limit=20):

        if "Accepted mod invite" in result.title:
            # If the time is older than the last midnight, get the
            # subreddit name from the subject and add it to the list.
            if today_midnight_utc > result.created_utc >= yesterday_midnight_utc:
                new_subreddits.append(re.findall(" r/([a-zA-Z0-9-_]*)", result.title)[0].lower())

    return new_subreddits


def wikipage_editor_local(subreddit_name, subreddit_data):
    """A simple local function for testing purposes to save generated
    wikipage data to local files for inspection, which can replace
    `wikipage_editor()` since that one edits wikipages.

    :param subreddit_name: The name a subreddit to edit.
    :param subreddit_data: The wikipage data for a subreddit.
    :return: `None`.
    """
    # Create a new sub-folder for local tests.
    destination_folder = FILE_ADDRESS.error.rsplit('/')[0] + "/Edited/"

    # Exit early if passed a value of `None`.
    if not subreddit_data:
        return

    # Create the folder if it doesn't exist.
    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)

    file_name = "{}{}.md".format(destination_folder, subreddit_name)
    with open(file_name, 'w', encoding='utf-8') as f:
        f.write(subreddit_data.strip())
        logger.info("Wikipage Editor Local: Wrote r/{} data to disk.".format(subreddit_name))

    return


def wikipage_editor(subreddit_name, subreddit_data, new_subreddits):
    """This function takes a dictionary indexed by subreddit with the
    wikipage data for each one. Then it proceeds to update the wikipage
    on the relevant subreddit, going through the list of communities.

    This is also run secondarily as a process because editing wikipages
    on Reddit can be extremely unpredictable in terms of how long it
    will take, so we want to run it concurrently so that flair enforcing
    functions can have minimal disruption while the statistics routine
    is running.

    :param subreddit_name: The name a subreddit to edit.
    :param subreddit_data: The wikipage data for a subreddit.
    :param new_subreddits: A list of subreddits that are new and the
                           mods should be alerted about their new
                           statistics page being updated.
    :return: None.
    """
    current_now = int(time.time())
    date_today = timekeeping.convert_to_string(current_now)
    logger.info("Wikipage Editor: BEGINNING editing statistics wikipage "
                "for r/{}.".format(subreddit_name))

    # We check to see if this subreddit is new. If we have NEVER
    # done statistics for this subreddit before, we will send an
    # initial setup message later once statistics are done.
    if subreddit_name in new_subreddits:
        send_initial_message = True
    else:
        send_initial_message = False

    # Check to make sure we have the wiki editing permission.
    # Exit early if we do not have the wiki editing permission.
    current_permissions = connection.obtain_mod_permissions(subreddit_name)[1]
    if current_permissions is None:
        logger.error("Wikipage Editor: No longer a mod on r/{}; "
                     "cannot edit the wiki.".format(subreddit_name))
        return
    if 'wiki' not in current_permissions and 'all' not in current_permissions:
        logger.info("Wikipage Editor: Insufficient mod permissions to edit "
                    "the wiki on r/{}.".format(subreddit_name))
        return

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
        content_data = subreddit_data + userflair_section
        statistics_wikipage.edit(content=content_data,
                                 reason='Updating with statistics data '
                                        'on {} UTC.'.format(date_today))
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
        main_error_log(wiki_error_entry)
        logger.error('Wikipage Editor: Encountered an error on '
                     'r/{}: {}'.format(subreddit_name, wiki_error_entry))
    else:
        logger.info('Wikipage Editor: Successfully updated r/{} '
                    'statistics'.format(subreddit_name))

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

    logger.info("Wikipage Editor: COMPLETED editing r/{}'s statistics "
                "wikipage in {} seconds.".format(subreddit_name,
                                                 int(time.time() - current_now)))

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
    month = timekeeping.convert_to_string(current_time)

    for community in subreddit_list:

        # Check mod permissions; if I am not a mod, skip this.
        # If I have the `flair` and `wiki` mod permissions,
        # get the data for the subreddit.
        perms = connection.obtain_mod_permissions(community)
        if not perms[0]:
            continue
        elif 'flair' in perms[1] and 'wiki' in perms[1] or 'all' in perms[1]:
            # Retrieve the data from the counter.
            # This will either return `None` if not available, or a
            # Markdown segment for integration.
            logger.info('Wikipage Userflair Editor: Checking r/{} userflairs...'.format(community))
            userflair_section = subreddit_userflair_counter(community)

            # If the result is not None, there's valid data.
            if userflair_section is not None:
                logger.info('Wikipage Userflair Editor: Now updating '
                            'r/{} userflair statistics.'.format(community))
                page_address = "{}_statistics".format(AUTH.username[:12])
                stat_page = reddit.subreddit(community).wiki[page_address]
                stat_page_existing = stat_page.content_md

                # If there's no preexisting section for userflairs, add
                # to the existing statistics. Otherwise, remove the old
                # section and replace it.
                if '## Userflairs' not in stat_page_existing:
                    new_text = stat_page_existing + userflair_section
                else:
                    stat_page_existing = stat_page_existing.split('## Userflairs')[0].strip()
                    new_text = stat_page_existing + userflair_section

                # Edit the actual page with the updated data.
                stat_page.edit(content=new_text,
                               reason='Updating with userflair data for {}.'.format(month))

    minutes_elapsed = round((time.time() - current_time) / 60, 2)
    logger.info('Wikipage Userflair Editor: Completed userflair update '
                'in {:.2f} minutes.'.format(minutes_elapsed))

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
    ext_data = database.extended_retrieve(subreddit_name)
    # Fix for manual initialization tests which will have no
    # extended data due to the fact that a sub won't be monitored.
    if ext_data is None:
        ext_data = {}

    # Get the date as YYYY-MM-DD.
    current_time = int(time.time())
    current_day = timekeeping.convert_to_string(current_time)

    # Get flair enforcing status.
    flair_enforce_status = "**Flair Enforcing**: {}"
    current_status = database.monitored_subreddits_enforce_status(subreddit_name)

    # Format the section that contains the subreddit's flair enforcing
    # mode for inclusion.
    if current_status:
        flair_enforce_status = flair_enforce_status.format("`On`")

        # Get flair enforcing default/strict status (basically, does it
        # have the `posts` moderator permission?)
        flair_enforce_mode = "\n\n* Flair Enforcing Mode: `{}`"
        mode_type = connection.monitored_subreddits_enforce_mode(subreddit_name)
        flair_enforce_status += flair_enforce_mode.format(mode_type)
    else:
        flair_enforce_status = flair_enforce_status.format("`Off`")

    # Get the day the subreddit added this bot.
    if 'added_utc' in ext_data:
        added_date = timekeeping.convert_to_string(ext_data['added_utc'])
    else:
        added_date = absent
    added_since = "**Artemis Added**: {}".format(added_date)

    # We get the earliest day we have statistics data for. (this gives
    # us an idea of how long we've monitored)
    statistics_data_since = "**Statistics Recorded Since**: {}"
    results = database.statistics_posts_retrieve(subreddit_name)

    # Get the date the subreddit was created.
    if 'created_utc' in ext_data:
        created_string = timekeeping.convert_to_string(ext_data['created_utc'])
    else:
        created_utc = reddit.subreddit(subreddit_name).created_utc
        created_string = timekeeping.convert_to_string(created_utc)
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
    currently_monitored = database.monitored_subreddits_retrieve()
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
    actions_section = database.counter_collater(subreddit_name)
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
    bot_list = list(connection.CONFIG.bots_comparative)
    bot_list.append(AUTH.username.lower())
    bot_dictionary = {}
    formatted_lines = []

    # Access the moderated subreddits for each bot in JSON data and
    # count how many subreddits are there. We also make sure to omit
    # any user profiles, which begin with "u_"
    for username in bot_list:
        my_data = subreddit_public_moderated(username)
        my_list = my_data['list']
        my_list = [x for x in my_list if not x.startswith("u_")]
        bot_dictionary[username] = (len(my_list), my_list)

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
        my_list = [x for x in my_list if not x.startswith("u_")]
        sentinel_mod_list += my_list

    # Remove duplicate subreddits on this list.
    sentinel_mod_list = list(set(sentinel_mod_list))
    sentinel_count = len(sentinel_mod_list)
    bot_dictionary[sentinel_list[-1]] = (sentinel_count, sentinel_mod_list)

    # Look at Artemis's modded subreddits and process through all the
    # data as well.
    my_public_monitored = bot_dictionary[AUTH.username.lower()][1]
    header = ("\n\n### Comparative Data\n\n"
              "| Bot | # Subreddits (Public) | Percentage | # Overlap |\n"
              "|-----|-----------------------|------------|-----------|\n")

    # Sort through the usernames alphabetically.
    for username in sorted(bot_dictionary.keys()):
        num_subs = bot_dictionary[username][0]
        list_subs = bot_dictionary[username][1]

        # Format the entries appropriately.
        if username != AUTH.username.lower():
            percentage = num_subs / bot_dictionary[AUTH.username.lower()][0]

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
    has ever done. Note that this needs to grab all rows except for the
    one with `all`, as that is a special row containing a dictionary of
    aggregate day-indexed actions instead.

    :return: A Markdown table detailing all those actions.
    """
    formatted_lines = []

    # Combine the actions databases.
    database.CURSOR_MAIN.execute('SELECT * FROM subreddit_actions WHERE subreddit != ?', ('all',))
    results_m = database.CURSOR_MAIN.fetchall()
    database.CURSOR_STATS.execute('SELECT * FROM subreddit_actions WHERE subreddit != ?', ('all',))
    results_s = database.CURSOR_STATS.fetchall()
    results = dict(Counter(results_m) + Counter(results_s))

    # Get a list of the action keys, and then create a dictionary with
    # each value set to zero.
    all_keys = list(set().union(*[literal_eval(x[1]) for x in results]))
    main_dictionary = dict.fromkeys(all_keys, 0)

    # Iterate over each community.
    for community in results:
        main_actions = literal_eval(community[1])
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
    list_of_subs = database.monitored_subreddits_retrieve()
    list_of_subs.sort()

    # Access my database to get the addition and created dates for
    # monitored subreddits. This fetches it from the other main database
    # but only *reads*, not writes to it.
    database.CURSOR_MAIN.execute("SELECT * FROM monitored")
    results = database.CURSOR_MAIN.fetchall()
    for line in results:
        community = line[0]
        extended_data = literal_eval(line[2])
        index[community] = index_num
        index_num += 1
        addition_dates[community] = timekeeping.convert_to_string(extended_data['added_utc'])
        created_dates[community] = timekeeping.convert_to_string(extended_data['created_utc'])
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
        result = database.last_subscriber_count(subreddit)
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
    num_of_enforced_subs = len(database.monitored_subreddits_retrieve(True))
    num_of_stats_enabled_subs = len([x for x in total_subscribers if x >= SETTINGS.min_s_stats])
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
    time_note = 'Updating dashboard for {}.'.format(timekeeping.convert_to_string(time.time()))
    dashboard.edit(content=body, reason=time_note)
    logger.info('Dashboard: Updated the overall dashboard.')

    return


"""WIDGET ROUTINES"""


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
    # Don't update this widget if it's being run on an alternate account
    if AUTH.username != "AssistantBOT":
        return

    # Get the list of public subreddits that are moderated.
    subreddit_list = subreddit_public_moderated(AUTH.username)['list']

    # Search for the relevant status and table widgets for editing.
    status_id = 'widget_13xm3fwr0w9mu'
    status_widget = None
    table_id = 'widget_13xztx496z34h'
    table_widget = None
    actions_id = 'widget_14159zz24snay'
    action_widget = None

    # Assign the widgets to our variables.
    for widget in reddit.subreddit(AUTH.username).widgets.sidebar:
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
    status = status_template.format(timekeeping.convert_to_string(time.time()),
                                    len(subreddit_list))
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
    # Don't update this widget if it's being run on an alternate account
    if AUTH.username != "AssistantBOT":
        return

    # Get the status widget.
    status_id = 'widget_13xm3fwr0w9mu'
    status_widget = None
    for widget in reddit.subreddit(AUTH.username).widgets.sidebar:
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
    # Don't update this widget if it's being run on an alternate account
    if AUTH.username != "AssistantBOT":
        return

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


"""MAIN STATISTICS FUNCTIONS"""


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
    for community in database.monitored_subreddits_retrieve():
        # Check to see if there's saved data. If there isn't it'll be
        # returned as `None`.
        result = database.activity_retrieve(community, 'oldest', 'oldest')

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
    query = ("{0} OR url:{0} OR selftext:{0} NOT author:{1} "
             "NOT author:{0}".format(AUTH.username[:12].lower(), AUTH.creator))
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
            if comment_info['author'].lower() in connection.CONFIG.users_omit:
                continue
            comment = reddit.comment(id=comment_info['id'])  # Convert into PRAW object.
            try:
                if not comment.saved:  # Don't process saved comments.
                    if comment.subreddit.display_name.lower() != AUTH.username[:12].lower():
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
            connection.messaging_send_creator(value[0], "mention", value[1])
            logger.info('Obtain Mentions: Sent my creator a message about item `{}`.'.format(key))

    return


def main_check_start():
    """This is a function that checks the `_start.md` for subreddits
    passed to it from the main routine. If one is detected, it's
    loaded and initialized, and the text document is cleared.
    This function can account for newlines as divisors in the text file.

    :return: `None` if the file is blank, a list of subreddits
             otherwise.
    """
    # Load the file, then clear it.
    with open(FILE_ADDRESS.start, 'r', encoding='utf-8') as f:
        scratchpad = f.read().strip()

    # Return the data in it.
    if not len(scratchpad):
        return
    else:
        new_subs = scratchpad.split('\n')
        new_subs = list(set([x.strip() for x in new_subs if len(x) > 0]))

        # Actually initialize data.
        for subreddit in new_subs:

            # Skip if the subreddit has already been initialized. If it
            # has, it would have traffic data.
            if subreddit_traffic_retriever(subreddit):
                logger.info('Check Start: Subreddit r/{} already initialized.'.format(subreddit))
                continue
            logger.info('Check Start: New subreddit to initialize: r/{}.'.format(subreddit))
            initialization(subreddit, True)
        open(FILE_ADDRESS.start, 'w', encoding='utf-8').close()  # Clear

        return


def initialization(subreddit_name, create_wiki=True):
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


def seconds_till_next_run():
    """
    Function to determine seconds until the next midnight UTC to act.
    The bot uses this time to wait for that period, thus
    running itself at the same time each day (right after midnight).

    :return: Returns the number of seconds remaining until the next
             action time as an integer.
    """
    current_time = time.time()
    current_date = timekeeping.convert_to_string(current_time)
    last_utc_midnight = timekeeping.convert_to_unix(current_date)
    seconds_remaining = int((last_utc_midnight + 86405) - current_time)

    return seconds_remaining


def main_backup_daily():
    """This function backs up the database files to a secure Box account
    and a local target. It does not back up the credentials file or the
    main Artemis file itself. This is called by the master timer during
    its daily routine.

    :return: Nothing.
    """
    current_day = timekeeping.convert_to_string(time.time())

    # Iterate over the backup paths that are listed.
    for backup_path in [AUTH.backup_folder, AUTH.backup_folder_2]:
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
                            copy(full_file_name, new_folder_path)
                        except OSError:
                            pass

                logger.info('Main Backup: Completed for {}.'.format(current_day))

    return


def main_maintenance_daily():
    """This function brings in the backup function, which backs up files
    to Box and a local external disk.

    This function is intended to be run *once* daily. It will insert an
    entry into `subreddit_updated` with the subreddit code 'all' and the
    date to indicate that the process has been completed.

    :return: `None`.
    """
    # Add an entry into the database so that Artemis knows it's already
    # completed the actions for the day.
    current_day = timekeeping.convert_to_string(time.time())
    database.CURSOR_STATS.execute("INSERT INTO subreddit_updated VALUES (?, ?)",
                                  ('all', current_day))
    database.CONN_STATS.commit()

    # Back up the relevant files.
    main_backup_daily()

    return


def main_maintenance_secondary():
    """This function brings together secondary functions that are NOT
    database-related and are run on a separate thread.

    :return: `None`.
    """
    # Check if there are any mentions and update comparison widget
    main_obtain_mentions()
    widget_comparison_updater()

    return


def main_timer(manual_start=False):
    """This function helps time certain routines to be done only at
    specific times or days of the month.
    SETTINGS.action_time: Defined above, usually at midnight UTC.
    Daily at midnight: Retrieve number of subscribers.
                       Record post statistics and post them to the wiki.
                       Backup the data files to Box.
    Xth day of every month: Retrieve subreddit traffic. We don't do this
                            on the first of the month because Reddit
                            frequently takes a few days to update
                            traffic statistics.

    :param manual_start: A Boolean for whether the statistics cycle was
                         manually triggered.
    :return: `None`.
    """
    # Get the time variables that we need.
    start_time = int(time.time())
    previous_date_string = timekeeping.convert_to_string(start_time - 86400)
    current_date_string = timekeeping.convert_to_string(start_time)
    current_hour = int(datetime.datetime.utcfromtimestamp(start_time).strftime('%H'))
    current_date_only = datetime.datetime.utcfromtimestamp(start_time).strftime('%d')

    # Define the alternate times and dates for userflair updates.
    # This is run at a varying time period in order to avoid
    # too many API calls at the same time.
    userflair_update_days = [SETTINGS.day_action, SETTINGS.day_action + 14]
    userflair_update_time = SETTINGS.action_time + 12

    # Check to see if the statistics functions have already been run.
    # If we have already processed the actions for today, note that.
    query = "SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?"
    database.CURSOR_STATS.execute(query, ('all', current_date_string))
    result = database.CURSOR_STATS.fetchone()
    if result is not None:
        all_stats_done = True
    else:
        all_stats_done = False

    # Check to see on certain days if the userflair statistics function
    # has already been run.
    userflair_done = True
    if int(current_date_only) in userflair_update_days and current_hour == userflair_update_time:
        query = "SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?"
        database.CURSOR_STATS.execute(query, ('userflair', current_date_string))
        userflair_result = database.CURSOR_STATS.fetchone()
        if userflair_result is None:
            userflair_done = False

    # If we are outside the update window, exit. Otherwise, if a manual
    # update by the creator was not requested, and all statistics were
    # retrieved, also exit.
    exit_early = True
    # Run a date check first. If the current day is a userflair update
    # day, then check the time. If it matches the time for the userflair
    # update, make it so we don't exit early.
    if int(current_date_only) in userflair_update_days:
        if current_hour == userflair_update_time and not userflair_done:
            exit_early = False
    if exit_early:
        if current_hour <= (SETTINGS.action_time + SETTINGS.action_window) and not all_stats_done:
            exit_early = False
        if manual_start:
            exit_early = False

    if exit_early:
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
    # Also refresh the configuration data.
    monitored_list = database.monitored_subreddits_retrieve()
    connection.config_retriever()

    # Temporary dictionary that stores formatted data for statistics
    # pages, which is cleared after the daily statistics run.
    # This was originally a global variable.
    already_processed = []

    # On a few specific days, run the userflair updating thread first in
    # order to not conflict with the main runtime.
    # This is currently set for 1st and 15th of each month, and more
    # specifically only twelve hours from the regular routine to avoid
    # over-use of API calls.
    if int(current_date_only) in userflair_update_days and current_hour == userflair_update_time:
        logger.info('Main Timer: Initializing a secondary thread for userflair updates.')
        userflair_check_list = []

        # Iterate over the subreddits, to see if they meet the minimum
        # amount of subscribers needed OR if they have manually opted in
        # to getting userflair statistics, or if they have opted out.
        for sub in monitored_list:
            if database.last_subscriber_count(sub) > SETTINGS.min_s_userflair:
                userflair_check_list.append(sub)
                if 'userflair_statistics' in database.extended_retrieve(sub):
                    if not database.extended_retrieve(sub)['userflair_statistics']:
                        userflair_check_list.remove(sub)
            elif 'userflair_statistics' in database.extended_retrieve(sub):
                if database.extended_retrieve(sub)['userflair_statistics']:
                    userflair_check_list.append(sub)

        # Update our counters.
        for sub in userflair_check_list:
            database.counter_updater(sub, 'Updated userflair statistics', 'stats')
        # Insert an entry into the database, telling us that it's done.
        # This is technically a 'dummy' subreddit, named `userflair`
        # much like `all` which is inserted after statistics runs.
        database.CURSOR_STATS.execute("INSERT INTO subreddit_updated VALUES (?, ?)",
                                      ('userflair', current_date_string))
        database.CONN_STATS.commit()

        # Launch the secondary userflair updating thread as another
        # thread run concurrently. It is alphabetized ahead of time.
        if not userflair_done:
            userflair_check_list = list(sorted(userflair_check_list))
            logger.info('Main Timer: Checking the following subreddits '
                        'for userflairs: r/{}'.format(', r/'.join(userflair_check_list)))
            userflair_thread = Thread(target=wikipage_userflair_editor,
                                      kwargs=dict(subreddit_list=userflair_check_list))
            userflair_thread.start()

    # Exit if not running userflairs.
    if all_stats_done:
        return

    # Fetch the list of new and paused statistics subreddits.
    new_subreddits = wikipage_get_new_subreddits()
    paused_subreddits = database.monitored_paused_retrieve()
    logger.info("Main Timer: Newly updated subreddits are: {}".format(new_subreddits))

    # This is the main part of gathering statistics.
    # Iterate over the communities we're monitoring, compile the
    # statistics and add to dictionary.
    for community in monitored_list:
        # Check to see if we have acted upon this subreddit for today
        # and already have its statistics.
        community_start = time.time()
        community_compiled_data = None
        act_command = 'SELECT * FROM subreddit_updated WHERE subreddit = ? AND date = ?'
        database.CURSOR_STATS.execute(act_command, (community, current_date_string))
        if database.CURSOR_STATS.fetchone():
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
        database.CURSOR_STATS.execute("INSERT INTO subreddit_updated VALUES (?, ?)",
                                      (community, current_date_string))
        database.CONN_STATS.commit()

        # Update the status widget's initial position, given a value
        # instead of zero in order to avoid an error dividing by zero.
        # Also check to see if there are any pending subreddits to
        # initialize data for.
        if not bool(community_place % 10) and community_place != 0:
            widget_status_updater(community_place, len(monitored_list), current_date_string,
                                  start_time)
            main_check_start()

        # If it's a certain day of the month, also get the traffic data.
        # Traffic data is retrieved twice in order to account for any
        # gaps that might occur due to the site issues.
        if int(current_date_only) in [SETTINGS.day_action, SETTINGS.day_traffic]:
            subreddit_traffic_recorder(community)

        # SKIP CHECK: See if a subreddit either
        #   a) has enough subscribers, or
        #   b) isn't frozen.
        # Check to see how many subscribers the subreddit has.
        # If it is below minimum, skip but record the subscriber
        # count so that we could resume statistics gathering
        # automatically once it passes that minimum.
        ext_data = database.extended_retrieve(community)
        if ext_data is not None:
            freeze = database.extended_retrieve(community).get('freeze', False)
        else:
            logger.info('Main Timer: r/{} has no extended data. '
                        'Statistics frozen.'.format(community))
            freeze = True

        # If there are too few subscribers to record statistics,
        # or the statistics status is frozen, record the number of
        # subscribers and continue without recording statistics.
        if community in paused_subreddits or freeze:
            subreddit_subscribers_recorder(community)
            logger.info('Main Timer: COMPLETED: r/{} below minimum or frozen. '
                        'Recorded subscribers.'.format(community))
            continue

        # If it's a certain day of the month (the first), also get the
        # top posts from the last month and save them.
        if int(current_date_only) == SETTINGS.day_action:
            last_month_dt = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
            last_month_string = last_month_dt.strftime("%Y-%m")
            subreddit_top_collater(community, last_month_string, last_month_mode=True)

        # Update the number of subscribers and get the statistics for
        # the previous day.
        subreddit_subscribers_recorder(community)
        subreddit_statistics_recorder_daily(community, previous_date_string)

        # Compile the post statistics text and add it to our dictionary.
        if community not in already_processed:
            already_processed.append(community)
            community_compiled_data = wikipage_collater(community)
            logger.info("Main Timer: Compiled statistics wikipage for r/{}.".format(community))

        # Update the counter, as all processes are done for this sub.
        logger.info("Main Timer: COMPLETED daily collation for r/{} in {} "
                    "seconds.".format(community, int(time.time() - community_start)))
        database.counter_updater(community, 'Updated statistics', 'stats')

        # Here the function actually edits the wiki pages. There is a
        # boolean in settings which governs whether the stats are
        # written locally for testing or on the live wikipages.
        if SETTINGS.stats_local:
            wikipage_editor_local(community, community_compiled_data)
        else:
            wikipage_editor(community, community_compiled_data, new_subreddits)

    # Recheck for oldest submissions once a month for those subreddits
    # that lack them, recheck on the same as the traffic day.
    if int(current_date_only) == SETTINGS.day_traffic:
        main_recheck_oldest()

    # If we are deployed on Linux (Raspberry Pi), also run other
    # routines. These will not run on non-live platforms.
    if sys.platform.startswith('linux'):
        # We have not performed the main actions for today yet.
        # Run the backup and cleanup routines, and update the
        # configuration data in a parallel thread.
        # `main_maintenance_daily` also inserts `all` into the
        # database to tell it's done with statistics.
        secondary_thread = Thread(target=main_maintenance_secondary)
        secondary_thread.start()
        main_maintenance_daily()

        # Mark down the total process time in minutes.
        end_process_time = time.time()
        elapsed_process_time = (end_process_time - start_time) / 60

        # Update the dashboard and finalize the widgets in the sidebar.
        wikipage_dashboard_collater(run_time=elapsed_process_time)
        action_data = wikipage_get_all_actions()
        widget_thread = Thread(target=widget_updater,
                               args=(action_data,))
        widget_thread.start()

    return


if __name__ == "__main__":
    try:
        while True:
            try:
                main_check_start()
                main_timer()

                # Record memory usage at the end of a cycle.
                mem_num = psutil.Process(os.getpid()).memory_info().rss
                mem_usage = "Memory usage: {:.2f} MB.".format(mem_num / (1024 * 1024))
                logger.info("------- Cycle {:,} COMPLETE. {}\n".format(CYCLES, mem_usage))
            except Exception as e:
                # Artemis encountered an exception, and if the error
                # is not a common connection issue, log it in a separate
                # file. Otherwise, merely record it in the events log.
                error_entry = "\n### {} \n\n".format(e)
                error_entry += traceback.format_exc()
                logger.error(error_entry)
                if not any(keyword in error_entry for keyword in SETTINGS.conn_errors):
                    main_error_log(error_entry)

            CYCLES += 1
            time.sleep(SETTINGS.wait * 4)
    except KeyboardInterrupt:
        # Manual termination of the script with Ctrl-C.
        logger.info('Manual user shutdown via keyboard.')
        sys.exit()
