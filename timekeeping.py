#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The timekeeping component primarily deals with time conversion and
formatting.
"""
import calendar
import datetime
import time

import pytz

from settings import SETTINGS

"""DATE/TIME CONVERSION FUNCTIONS"""


def time_convert_to_string(unix_integer):
    """Converts a UNIX integer into a time formatted according to
    ISO 8601 for UTC time.

    :param unix_integer: Any UNIX time number.
    """
    i = int(unix_integer)
    utc_time = datetime.datetime.fromtimestamp(i, tz=datetime.timezone.utc).isoformat()[:19]
    utc_time = "{}Z".format(utc_time)

    return utc_time


def convert_to_string(unix_integer):
    """Converts a UNIX integer into a date formatted as YYYY-MM-DD,
    according to the UTC equivalent (not local time).

    :param unix_integer: Any UNIX time number.
    :return: A string formatted with UTC time.
    """
    i = int(unix_integer)
    f = "%Y-%m-%d"
    date_string = datetime.datetime.utcfromtimestamp(i).strftime(f)

    return date_string


def convert_to_unix(date_string):
    """Converts a date formatted as YYYY-MM-DD into a Unix integer of
    its equivalent UTC time.

    :param date_string: Any date formatted as YYYY-MM-DD.
    :return: The string timestamp of MIDNIGHT that day in UTC.
    """
    year, month, day = date_string.split("-")
    dt = datetime.datetime(int(year), int(month), int(day))
    utc_timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())

    return utc_timestamp


def month_convert_to_string(unix_integer):
    """Converts a UNIX integer into a date formatted as YYYY-MM.
    This just retrieves the month string.

    :param unix_integer: Any UNIX time number.
    :return: A month string formatted as YYYY-MM.
    """
    month_string = datetime.datetime.utcfromtimestamp(int(unix_integer)).strftime("%Y-%m")

    return month_string


def convert_weekday_text(day_string):
    """This simple function converts a weekday abbreviation to its full
    English form, or vice versa.
    """

    if len(day_string) == 3:
        weekday_num = time.strptime(day_string, "%a").tm_wday
        return calendar.day_name[weekday_num]
    else:
        return day_string[:3]


def num_days_between(start_day, end_day):
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


def get_series_of_days(start_day, end_day):
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


def get_historical_series_days(list_of_days):
    """Takes a list of days in YYYY-MM-DD and returns another list.
    If the original list is less than 120 days long, it just returns
    the same list. Otherwise, it tries to get the start of the month.
    This is generally to avoid Artemis having to search through years'
    of data on relatively inactive subreddits.

    :param list_of_days: A list of days in YYYY-MM-DD format.
    :return: Another list of days, the ones to get data for.
    """
    # The max number of past days we want to get historical data for.
    days_limit = SETTINGS.hist_days_limit

    # If number of days contained is fewer than our limit, just return
    # the whole thing back. Otherwise, truncate the number of days.
    if len(list_of_days) <= days_limit:
        pass
    else:
        # This is longer than our limit of days. Truncate it down.
        # If we can get an extra *full* month past this, get it.
        if len(list_of_days) > days_limit + 31:
            first_day = list_of_days[(-1 * days_limit) :][0]
            initial_start = first_day[:-3] + "-01"
            list_of_days = list_of_days[list_of_days.index(initial_start) :]
        else:
            # Otherwise, just return the last 90 days.
            list_of_days = list_of_days[(-1 * days_limit) :]

    return list_of_days


def check_flair_schedule(flair_template_id, flair_days_dict):
    """This function checks a given flair template ID against
    a dictionary of what flairs are allowed on what weekdays (stored in
    the advanced configuration). If the dictionary is empty, anything
    will be approved.

    :return: If it is allowed, then the function
             returns `True` (user can post on this weekday).
             Otherwise, `False` (cannot post on this weekday).
    """
    west_timezone = "Pacific/Auckland"
    east_timezone = "Pacific/Honolulu"
    current_moment = time.time()
    current_weekday = datetime.date.today().strftime("%a")

    # Define the time boundaries of the day by getting the weekday
    # abbreviated names in the bounded locales. (e.g. Mon, Wed, Sat)
    # Get the western bound of the weekday (latest time).
    tz_west = pytz.timezone(west_timezone)
    west_bound = datetime.datetime.fromtimestamp(current_moment, tz_west).strftime("%a")
    # Get the eastern bound of the weekday (earliest time).
    tz_east = pytz.timezone(east_timezone)
    east_bound = datetime.datetime.fromtimestamp(current_moment, tz_east).strftime("%a")

    # Get the permitted days from the flair dictionary.
    permitted_days = [key for key, value in flair_days_dict.items() if flair_template_id in value]

    # Check the flair ID against a list of all the flairs.
    # If it's not in any of them, just return and approve.
    all_flairs = sum(flair_days_dict.values(), [])
    if flair_template_id not in all_flairs:
        return True, permitted_days, current_weekday

    # Check the two day boundaries and see if there's an overlap. If
    # there is an overlap, then it is permitted to post this flair.
    current_days = list({east_bound, west_bound})
    overlap_days = [value for value in current_days if value in permitted_days]

    if overlap_days:
        return True, permitted_days, current_weekday
    else:
        return False, permitted_days, current_weekday


def previous_month():
    """Gets previous month in YYYY-MM form."""
    prev_month = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m")

    return prev_month
