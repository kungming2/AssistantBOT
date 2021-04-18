#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The database component contains functions to manage reading and
writing to the two SQLite databases.
"""
import sqlite3
import time
from ast import literal_eval
from collections import Counter
from json import dumps as json_dumps

from common import logger
from settings import FILE_ADDRESS, SETTINGS
from timekeeping import convert_to_string


"""BASE DEFINITIONS"""

CONN_STATS = sqlite3.connect(FILE_ADDRESS.data_stats)
CURSOR_STATS = CONN_STATS.cursor()
CONN_MAIN = sqlite3.connect(FILE_ADDRESS.data_main)
CURSOR_MAIN = CONN_MAIN.cursor()


"""DATABASE DEFINITIONS"""


def define_database(instance_num=99):
    """This function connects to per-instance databases as needed
    by the active instance.

    :param instance_num: The Artemis instance to use.
    :return:
    """
    global CONN_STATS
    global CURSOR_STATS
    global CONN_MAIN
    global CURSOR_MAIN

    if instance_num is 99:
        stats_address = FILE_ADDRESS.data_stats
        main_address = FILE_ADDRESS.data_main
        logger.info("Define Database: Using default database.")
    else:
        stats_address = "{}{}.db".format(FILE_ADDRESS.data_stats[:-3], instance_num)
        main_address = "{}{}.db".format(FILE_ADDRESS.data_main[:-3], instance_num)
        logger.info("Define Database: Using database for instance {}.".format(instance_num))

    # This connects Artemis with its statistics SQLite database file.
    CONN_STATS = sqlite3.connect(stats_address)
    CURSOR_STATS = CONN_STATS.cursor()

    # This connects Artemis with its flair enforcement SQLite
    # database file.
    CONN_MAIN = sqlite3.connect(main_address)
    CURSOR_MAIN = CONN_MAIN.cursor()

    return


"""DATABASE CREATION"""


def table_creator():
    """This function creates the tables in the databases if they do not
    already exist.

    :return: `None`.
    """
    # Parse and create the main database if necessary.
    CURSOR_MAIN.execute(
        "CREATE TABLE IF NOT EXISTS monitored "
        "(subreddit text, flair_enforce integer, extended text);"
    )
    CURSOR_MAIN.execute(
        "CREATE TABLE IF NOT EXISTS posts_filtered " "(post_id text, post_created integer);"
    )
    CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS posts_operations (id text, operations text);")
    CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS posts_processed (post_id text);")
    CURSOR_MAIN.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_actions " "(subreddit text, recorded_actions text);"
    )
    CONN_MAIN.commit()

    # Parse and create the statistics database if necessary.
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_actions " "(subreddit text, recorded_actions text);"
    )
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_activity "
        "(subreddit text, date text, activity text);"
    )
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_stats_posts " "(subreddit text, records text);"
    )
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_subscribers_new " "(subreddit text, records text);"
    )
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_traffic " "(subreddit text, traffic text);"
    )
    CURSOR_STATS.execute(
        "CREATE TABLE IF NOT EXISTS subreddit_updated " "(subreddit text, date text);"
    )
    return


"""DATABASE FUNCTIONS"""


def database_access(command, data, cursor=None, retries=3, fetch_many=False):
    """This is a wrapper function that is used by functions that may be
    called by the statistics runtime on the MAIN database. A built-in
    function will wait if it encounters any lock.

    :param command: The SQLite command to be run on the main database.
    :param data: The data package for the search query. `None` if none
                 is needed.
    :param cursor: A cursor object can be passed.
    :param retries: The number of times the function will ask for data.
    :param fetch_many: Whether to fetch just one result or many.
    :return:
    """
    if cursor:
        cursor_used = cursor
    else:
        cursor_used = CURSOR_MAIN

    for _ in range(retries):
        try:
            # If there's data to search for, include it. Otherwise, just
            # conduct a straight command.
            if data:
                cursor_used.execute(command, data)
            else:
                cursor_used.execute(command)

            # Choose whether or not to fetch many results or just one.
            if not fetch_many:
                result = cursor_used.fetchone()
            else:
                result = cursor_used.fetchall()

            # Ext early with the result if we have it.
            if result is not None:
                return result
        except sqlite3.OperationalError:
            # Back off if there's a temporary lock on the database.
            time.sleep(_ + 1)
            continue

    return


def subreddit_insert(community_name, supplement):
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
    CURSOR_MAIN.execute(command, (community_name,))
    result = CURSOR_MAIN.fetchone()

    # If the subreddit was not previously in database, insert it in.
    # 1 is the same as `True` for flair enforcing (default setting).
    if result is None:
        CURSOR_MAIN.execute(
            "INSERT INTO monitored VALUES (?, ?, ?)", (community_name, 1, str(supplement))
        )
        CONN_MAIN.commit()
        logger.info("Sub Insert: r/{} added to monitored database.".format(community_name))

    return


def subreddit_delete(community_name):
    """This function removes a subreddit from the moderated list and
    Artemis will NO LONGER assist that community.

    :param community_name: Name of a subreddit (no r/).
    :return: Nothing.
    """
    community_name = community_name.lower()
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?", (community_name,))
    result = CURSOR_MAIN.fetchone()

    if result is not None:  # Subreddit is in database. Let's remove it.
        CURSOR_MAIN.execute("DELETE FROM monitored WHERE subreddit = ?", (community_name,))
        CONN_MAIN.commit()
        logger.info("Sub Delete: r/{} deleted from monitored database.".format(community_name))

    return


def monitored_subreddits_retrieve(flair_enforce_only=False):
    """This function returns a list of all the subreddits that
    Artemis monitors WITHOUT the 'r/' prefix.
    This function is used by both routines.

    :param flair_enforce_only: A Boolean that if `True`, only returns
                               the subreddits that have flair enforcing
                               turned on.
    :return: A list of all monitored subreddits, in the order which
             they were first stored, oldest to newest.
    """

    if not flair_enforce_only:
        query = "SELECT * FROM monitored"
    else:
        query = "SELECT * FROM monitored WHERE flair_enforce is 1"
    results = database_access(query, None, fetch_many=True)
    final_list = [x[0].lower() for x in results]

    return final_list


def monitored_subreddits_enforce_change(subreddit_name, to_enforce):
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
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name,))
    result = CURSOR_MAIN.fetchone()

    # This subreddit is stored in the monitored database; modify it.
    if result is not None:

        # If the current status is different, change it.
        if result[1] != s_digit:
            CURSOR_MAIN.execute(
                "UPDATE monitored SET flair_enforce = ? WHERE subreddit = ?",
                (s_digit, subreddit_name),
            )
            CONN_MAIN.commit()
            logger.info(
                "Enforce Change: r/{} flair enforce set to `{}`.".format(
                    subreddit_name, to_enforce
                )
            )

    return


def monitored_subreddits_enforce_status(subreddit_name):
    """A function that returns True or False depending on the
    subreddit's `flair_enforce` status.
    That status is stored as an integer and converted into a Boolean.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A boolean. Default is True.
    """
    subreddit_name = subreddit_name.lower()
    result = database_access("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name,))

    # This subreddit is stored in our monitored database; access it.
    if result is not None:
        # This is the current status.
        flair_enforce_status = bool(result[1])
        logger.debug(
            "Enforce Status: r/{} flair enforce status: {}.".format(
                subreddit_name, flair_enforce_status
            )
        )
        if not flair_enforce_status:
            return False

    return True


def monitored_paused_retrieve():
    """This function retrieves a list of the subreddits that have below
    the minimum count of subscribers that's needed for statistics.
    """
    paused_subs = []
    monitored = monitored_subreddits_retrieve()

    for sub in monitored:
        current = last_subscriber_count(sub)
        if current < SETTINGS.min_s_stats:
            paused_subs.append(sub)

    return paused_subs


def delete_filtered_post(post_id):
    """This function deletes a post ID from the flair filtered
    database. Either because it's too old, or because it has
    been approved and restored. Trying to delete a non-existent ID
    just won't do anything.

    :param post_id: The Reddit submission's ID, as a string.
    :return: `None`.
    """
    CURSOR_MAIN.execute("DELETE FROM posts_filtered WHERE post_id = ?", (post_id,))
    CONN_MAIN.commit()
    logger.debug("Delete Filtered Post: Deleted post `{}` from filtered database.".format(post_id))

    return


def last_subscriber_count(subreddit_name):
    """A function that returns the last and most recent local saved
    subscriber value for a given subreddit.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: The number of subscribers that subreddit has,
             or `None` if the subreddit is not listed.
    """
    stored_data = subscribers_retrieve(subreddit_name)
    num_subscribers = 0

    # If we already have stored subscriber data, get the last value.
    if stored_data is not None:
        # This is the last day we have subscriber data for.
        last_day = list(sorted(stored_data.keys()))[-1]
        num_subscribers = stored_data[last_day]

    return num_subscribers


def extended_retrieve(subreddit_name):
    """This function fetches the extended data stored in `monitored`
    and returns it as a dictionary.
    This function is used by both routines.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A dictionary containing the extended data for a
             particular subreddit. An empty dictionary otherwise.
    """
    # Access the database.
    query = "SELECT * FROM monitored WHERE subreddit = ?"
    result = database_access(query, (subreddit_name.lower(),))
    if result is not None:
        return literal_eval(result[2])
    else:
        return {}


def extended_insert(subreddit_name, new_data):
    """This function inserts data into the extended data stored in
    `monitored`. It will add data into the dictionary if the value
     does not exist, otherwise, it will modify it in place.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary containing the data we want to merge
                     or change in the extended data entry.
    :return: Nothing.
    """
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name.lower(),))
    result = CURSOR_MAIN.fetchone()

    # The subreddit is in the monitored list with extended data.
    if result is not None:
        # Convert this extended data back into a dictionary.
        extended_data_existing = literal_eval(result[2])
        working_dictionary = extended_data_existing.copy()
        working_dictionary.update(new_data)

        # Update the saved data with our new data.
        update_command = "UPDATE monitored SET extended = ? WHERE subreddit = ?"
        CURSOR_MAIN.execute(update_command, (str(working_dictionary), subreddit_name.lower()))
        CONN_MAIN.commit()
        logger.info("Extended Insert: Merged new extended data with existing data.")
    return


def activity_retrieve(subreddit_name, month, activity_type):
    """This function checks the `subreddit_activity` table for cached
    data from Pushshift on the top activity and top usernames for days
    and usernames.

    :param subreddit_name: Name of a subreddit (no r/).
    :param month: The month year string, expressed as YYYY-MM.
    :param activity_type: The type of activity we want to get the
                          dictionary for.
    :return: A dictionary containing the data for a particular month
    """
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
        (subreddit_name, month),
    )
    result = CURSOR_STATS.fetchone()

    if result is not None:
        # Convert this back into a dictionary.
        existing_data = literal_eval(result[2])
        if activity_type in existing_data:
            return existing_data[activity_type]
        elif activity_type == "oldest":
            return existing_data

    return


def activity_insert(subreddit_name, month, activity_type, activity_data):
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
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
        (subreddit_name, month),
    )
    result = CURSOR_STATS.fetchone()

    # Process the data. If there is no preexisting entry, Create a new
    # one, indexed with the activity type.
    if result is None:
        if activity_type != "oldest":
            data_component = {activity_type: activity_data}
            data_package = (subreddit_name, month, str(data_component))
            CURSOR_STATS.execute("INSERT INTO subreddit_activity VALUES (?, ?, ?)", data_package)
            CONN_STATS.commit()
        else:  # 'oldest' posts get indexed by that phrase instead of by month.
            data_package = (subreddit_name, "oldest", str(activity_data))
            CURSOR_STATS.execute("INSERT INTO subreddit_activity VALUES (?, ?, ?)", data_package)
            CONN_STATS.commit()
    else:
        # We already have data for this. Note that we don't need to
        # update this if data's already there.
        existing_data = literal_eval(result[2])

        # Convert this back into a dictionary.
        # If we do not already have this activity type saved,
        # update the dictionary with it.
        if activity_type not in existing_data:
            existing_data[activity_type] = activity_data
            # Update the existing data.
            update_command = (
                "UPDATE subreddit_activity SET activity = ? " "WHERE subreddit = ? AND date = ?"
            )
            CURSOR_STATS.execute(update_command, (str(existing_data), subreddit_name, month))
            CONN_STATS.commit()

    return


def subscribers_insert(subreddit_name, new_data):
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
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?", (subreddit_name,)
    )
    result = CURSOR_STATS.fetchone()

    # Process the data. If there is no preexisting subscribers entry,
    # create a new one.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_STATS.execute("INSERT INTO subreddit_subscribers_new VALUES (?, ?)", data_package)
        CONN_STATS.commit()
    else:
        # We already have data for this subreddit, so we want to merge
        # the two together.
        existing_dictionary = literal_eval(result[1])
        working_dictionary = existing_dictionary.copy()
        working_dictionary.update(new_data)

        # Update the saved data.
        update_command = "UPDATE subreddit_subscribers_new SET records = ? WHERE subreddit = ?"
        CURSOR_STATS.execute(update_command, (str(working_dictionary), subreddit_name))
        CONN_STATS.commit()

    return


def subscribers_retrieve(subreddit_name):
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
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?", (subreddit_name,)
    )
    result = CURSOR_STATS.fetchone()

    # We have data, let's turn the stored string into a dictionary.
    if result is not None:
        return literal_eval(result[1])

    return


def statistics_posts_insert(subreddit_name, new_data):
    """This function inserts a given dictionary of statistics posts
    data into the corresponding subreddit's entry. This replaces an
    earlier system which used individual rows for each day's
    information.

    This function will NOT overwrite a day's data if it already exists.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary containing posts data in this
                     form: {'YYYY-MM-DD': {X}} where the key is a date
                     string and the value is another dictionary
                     indexed by post flair and containing
                     integer values.
    :return: Nothing.
    """
    # Check the database first.
    subreddit_name = subreddit_name.lower()
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_stats_posts WHERE subreddit = ?", (subreddit_name,)
    )
    result = CURSOR_STATS.fetchone()

    # We have no data.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_STATS.execute("INSERT INTO subreddit_stats_posts VALUES (?, ?)", data_package)
        CONN_STATS.commit()
    else:
        # There is already an entry for this subreddit in our database.
        existing_dictionary = literal_eval(result[1])
        working_dictionary = existing_dictionary.copy()

        # Update the working dictionary with the new data.
        # Making sure we do not overwrite the existing data.
        for key, value in new_data.items():
            if key not in working_dictionary:
                working_dictionary[key] = value

        # Update the dictionary.
        update_command = "UPDATE subreddit_stats_posts SET records = ? WHERE subreddit = ?"
        CURSOR_STATS.execute(update_command, (str(working_dictionary), subreddit_name))
        CONN_STATS.commit()

    return


def statistics_posts_retrieve(subreddit_name):
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
    CURSOR_STATS.execute(
        "SELECT * FROM subreddit_stats_posts WHERE subreddit = ?", (subreddit_name,)
    )
    result = CURSOR_STATS.fetchone()

    # We have data, let's turn the stored string into a dictionary.
    if result is not None:
        return literal_eval(result[1])

    return


def counter_updater(
    subreddit_name, action_type, database_type, action_count=1, post_id=None, id_only=False
):
    """This function writes a certain number to an action log in the
    database to indicate how many times an action has been performed for
    a subreddit. For example, how many times posts have been removed,
    how many times posts have been restored, etc.
    This function is used by both routines.

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
    :param database_type: The database to write to. Either `stats` or
                          `main`. The updater will alternate based on
                          this selection.
    :param action_count: Defaults to 1, but can be changed if desired.
    :param post_id: The ID of a post (optional) for record-keeping in
                    the operations log.
    :param id_only: A Boolean telling whether the action should be
                    recorded only to the post ID operations log.
                    If `True`, then this will not be recorded in the SQL
                    database.
    :return: `None`.
    """
    # Switch the databases based on the input.
    if database_type == "stats":
        counter_cursor = CURSOR_STATS
        conn = CONN_STATS
    else:
        counter_cursor = CURSOR_MAIN
        conn = CONN_MAIN

    # If the data is for a single post, we can save it to the
    # per-post ID operations log.
    if action_count == 1 and post_id:
        counter_cursor.execute("SELECT * FROM posts_operations WHERE id = ?", (post_id,))
        operation_result = counter_cursor.fetchone()

        # In case the main file is blank, recreate it. Note that the
        # insertion command reverses the order of the columns.
        if not operation_result:
            operation_result = {}
            op_command = "INSERT INTO posts_operations (operations, id) VALUES (?, ?)"
        else:
            operation_result = literal_eval(operation_result[1])  # This is a dictionary.
            op_command = "UPDATE posts_operations SET operations = ? WHERE id = ?"

        # Create the data package to update the main dictionary with.
        post_package = {int(time.time()): action_type}
        if operation_result:
            operation_result.update(post_package)
        else:
            operation_result = post_package

        counter_cursor.execute(op_command, (str(operation_result), post_id))
        conn.commit()

    # Exit early if all we want is to record to that operations log.
    if id_only:
        return

    # Make the name lowercase. If the subreddit is `None`, exit.
    if subreddit_name:
        subreddit_name = subreddit_name.lower()
    else:
        return

    # Access the database to see if we have recorded actions for this
    # subreddit already.
    counter_cursor.execute(
        "SELECT * FROM subreddit_actions WHERE subreddit = ?", (subreddit_name,)
    )
    result = counter_cursor.fetchone()

    # No actions data recorded. Create a new dictionary and save it.
    if result is None:
        actions_dictionary = {action_type: action_count}
        data_package = (subreddit_name, str(actions_dictionary))
        counter_cursor.execute("INSERT INTO subreddit_actions VALUES (?, ?)", data_package)
        conn.commit()
    else:  # We already have an entry recorded for this.
        # Convert this back into a dictionary.
        actions_dictionary = literal_eval(result[1])
        # Check the data in the database. Update it if it exists,
        # otherwise create a new dictionary item.
        if action_type in actions_dictionary:
            actions_dictionary[action_type] += action_count
        else:
            actions_dictionary[action_type] = action_count

        # Update the existing data.
        update_command = "UPDATE subreddit_actions SET recorded_actions = ? WHERE subreddit = ?"
        counter_cursor.execute(update_command, (str(actions_dictionary), subreddit_name))
        conn.commit()

    # Also save the data to the master actions dictionary.
    # That dictionary is classified under `all`.
    # This is a dictionary that indexes all actions done, per day.
    counter_cursor.execute("SELECT * FROM subreddit_actions WHERE subreddit = ?", ("all",))
    result = counter_cursor.fetchone()
    if result is not None:
        master_actions = literal_eval(result[1])
        current_day = convert_to_string(time.time())

        # Add the action to the daily count.
        if current_day not in master_actions:
            master_actions[current_day] = {action_type: action_count}
        else:
            saved_day_actions = master_actions[current_day]
            if action_type in saved_day_actions:
                master_actions[current_day][action_type] += action_count
            else:
                master_actions[current_day][action_type] = action_count

        # Update the master actions data.
        update_command = "UPDATE subreddit_actions SET recorded_actions = ? WHERE subreddit = ?"
        counter_cursor.execute(update_command, (str(master_actions), "all"))
        conn.commit()
    else:
        # Create an "all" master entry in the database for actions
        # if one doesn't already exist. This is likely to only happen
        # a single time per database file.
        create_command = "INSERT INTO subreddit_actions VALUES (?, ?)"
        counter_cursor.execute(create_command, ("all", str({})))
        conn.commit()
        logger.info("Counter Updater: Created new 'all' entry in `subreddit_actions` table.")

    return


def counter_combiner(subreddit_name):
    """This function retrieves all actions from the two databases and
    combines them together into a single dictionary. Please note that
    this not work with `all`, for some reason.
    This function is used by both routines.

    :return: A dictionary with action data, otherwise, `None`.
    """
    retrieve_command = "SELECT * FROM subreddit_actions WHERE subreddit = ?"
    CURSOR_STATS.execute(retrieve_command, (subreddit_name,))
    result_s = CURSOR_STATS.fetchone()
    result_m = database_access(retrieve_command, (subreddit_name,))

    # Exit if there are zero results.
    if result_s is None and result_m is None:
        return

    # Combine the two dictionaries' data as one.
    if result_s is not None:
        action_data_stats = literal_eval(result_s[1])
    else:
        action_data_stats = {}
    if result_m is not None:
        action_data_main = literal_eval(result_m[1])
    else:
        action_data_main = {}
    action_data = dict(Counter(action_data_stats) + Counter(action_data_main))

    return action_data


def counter_collater(subreddit_name):
    """This function looks at the counter of actions that has been saved
    for the subreddit before and returns a Markdown table noting what
    actions were taken on the particular subreddit and how many of each.

    :param subreddit_name: Name of a subreddit.
    :return: A Markdown table if there is data, `None` otherwise.
    """
    formatted_lines = []

    # Access the database to get a subreddit's recorded actions.
    subreddit_name = subreddit_name.lower()
    action_data = counter_combiner(subreddit_name)

    # We have a result.
    if action_data:
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
        if "Removed post" in action_data and "Restored post" in action_data:
            if action_data["Removed post"] > 0:
                restored_percentage = action_data["Restored post"] / action_data["Removed post"]
                restored_line = "| *% Removed posts flaired and restored* | *{:.2%}* |"
                restored_line = restored_line.format(restored_percentage)
                if restored_percentage > 0.1:
                    formatted_lines.append(restored_line)

        # If we have no lines to make a table, just return `None`.
        if len(formatted_lines) == 0:
            return None
        else:
            # Format the text content together.
            header = "\n\n| Actions | Count |\n|---------|-------|\n"
            body = header + "\n".join(formatted_lines)

            return body

    return


"""OTHER DATABASE TOOLS"""


def migration_assistant(subreddit_name, source, target):
    """This function takes information stored in one instance's database
    and ports it over to a target database. The data is cleared from the
    source database after the port.

    :param subreddit_name: The subreddit we need to port data for.
    :param source: The source instance number, expressed as an integer.
    :param target: The target instance number, expressed as an integer.
    :return:
    """
    main_data = {}
    main_tables = ["monitored", "subreddit_actions"]
    stats_data = {}
    stats_tables = [
        "subreddit_actions",
        "subreddit_stats_posts",
        "subreddit_subscribers_new",
        "subreddit_traffic",
    ]

    # Don't do anything if the two databases are intended
    # to be the same.
    if source == target:
        return False

    database_dictionary = {"source": {"instance": source}, "target": {"instance": target}}

    # Make connections and cursors and store them in a dictionary.
    for database_type in database_dictionary:
        instance_num = database_dictionary[database_type]["instance"]
        if instance_num is 99:
            stats_address = FILE_ADDRESS.data_stats
            main_address = FILE_ADDRESS.data_main
        else:
            stats_address = "{}{}.db".format(FILE_ADDRESS.data_stats[:-3], instance_num)
            main_address = "{}{}.db".format(FILE_ADDRESS.data_main[:-3], instance_num)
        conn_stats = sqlite3.connect(stats_address)
        cursor_stats = conn_stats.cursor()
        conn_main = sqlite3.connect(main_address)
        cursor_main = conn_main.cursor()
        database_dictionary[database_type] = {
            "instance": instance_num,
            "conn_stats": conn_stats,
            "cursor_stats": cursor_stats,
            "conn_main": conn_main,
            "cursor_main": cursor_main,
        }

    # Access the main database's information first.
    # This consists of:
    #     1. The monitored information (including extended data).
    #     2. The subreddit's actions.
    cursor_source_main = database_dictionary["source"]["cursor_main"]
    conn_source_main = database_dictionary["source"]["conn_main"]
    for table in main_tables:
        query_command = "SELECT * FROM {} WHERE subreddit = '{}'".format(table, subreddit_name)
        main_data[table] = database_access(
            query_command, data=None, cursor=cursor_source_main, fetch_many=False
        )
        logger.info(
            "Migration Assistant: Data for r/{} retrieved "
            "from main table `{}`.".format(subreddit_name, table)
        )

    # Access the statistics database's information next.
    # This consists of almost all tables EXCEPT `subreddit_updated`.
    cursor_source_stats = database_dictionary["source"]["cursor_stats"]
    conn_source_stats = database_dictionary["source"]["conn_stats"]
    for table in stats_tables:
        query_command = "SELECT * FROM {} WHERE subreddit = '{}'".format(table, subreddit_name)
        stats_data[table] = database_access(
            query_command, data=None, cursor=cursor_source_stats, fetch_many=False
        )
        logger.info(
            "Migration Assistant: Data for r/{} retrieved "
            "from stats table `{}`.".format(subreddit_name, table)
        )
    # Subreddit activity data is accessed and stored separately, as
    # there are multiple lines. This returns a list of tuples.
    activity_query = "SELECT * FROM subreddit_activity WHERE subreddit = ?"
    stats_activity_data = database_access(
        activity_query, (subreddit_name,), cursor=cursor_source_stats, fetch_many=True
    )

    # Having obtained the data, write it to the target database.
    cursor_target_main = database_dictionary["target"]["cursor_main"]
    conn_target_main = database_dictionary["target"]["conn_main"]
    # Insert main data.
    for table in main_tables:
        # Check if data already exists for this subreddit in the main.
        query_command = "SELECT * FROM {} WHERE subreddit = '{}'".format(table, subreddit_name)
        exist_check = database_access(
            query_command, data=None, cursor=cursor_target_main, fetch_many=False
        )
        if exist_check:
            logger.info(
                "Migration Assistant: Data for r/{} already exists in target "
                "main table `{}`. Skipped.".format(subreddit_name, table)
            )
            continue
        else:
            payload = main_data[table]  # The actual data to insert.
            if payload:
                insert_command = "INSERT INTO {} VALUES {}".format(table, payload)
                cursor_target_main.execute(insert_command)
                conn_target_main.commit()
                logger.info(
                    "Migration Assistant: Data inserted for r/{} "
                    "into target main table `{}`.".format(subreddit_name, table)
                )
    # Insert stats data.
    cursor_target_stats = database_dictionary["target"]["cursor_stats"]
    conn_target_stats = database_dictionary["target"]["conn_stats"]
    for table in stats_tables:
        # Check if data already exists for this subreddit in the main.
        query_command = "SELECT * FROM {} WHERE subreddit = '{}'".format(table, subreddit_name)
        exist_check = database_access(
            query_command, data=None, cursor=cursor_target_stats, fetch_many=False
        )
        if exist_check:
            logger.info(
                "Migration Assistant: Data for r/{} already exists in target "
                "stats table `{}`. Skipped.".format(subreddit_name, table)
            )
            continue
        else:
            payload = stats_data[table]  # The actual data to insert.
            if payload:
                value_filler = "?, " * len(payload)
                value_filler = value_filler[:-2].strip()
                insert_command = "INSERT INTO {} VALUES ({})".format(table, value_filler)
                cursor_target_stats.execute(insert_command, payload)
                conn_target_stats.commit()
                logger.info(
                    "Migration Assistant: Data inserted for r/{} "
                    "into target stats table `{}`.".format(subreddit_name, table)
                )
    # Insert stats activity data.
    for line in stats_activity_data:
        month = line[1]
        activity_query = "SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?"
        exist_check = database_access(
            activity_query,
            data=(subreddit_name, month),
            cursor=cursor_target_stats,
            fetch_many=False,
        )
        if exist_check:
            logger.info(
                "Migration Assistant: Data for r/{} already exists in "
                "`subreddit_activity` for month {}. Skipped.".format(subreddit_name, month)
            )
            continue
        else:
            cursor_target_stats.execute("INSERT INTO subreddit_activity VALUES (?, ?, ?)", line)
            conn_target_stats.commit()
            logger.info(
                "Migration Assistant: Data inserted for r/{} "
                "into `subreddit_activity` for month {}.".format(subreddit_name, month)
            )

    # Delete the data from the source databases.
    for table in main_tables:
        delete_command = "DELETE FROM {} WHERE subreddit = ?".format(table)
        cursor_source_main.execute(delete_command, (subreddit_name,))
        conn_source_main.commit()
        logger.info(
            "Migration Assistant: Data removed for r/{} "
            "from source main table `{}`.".format(subreddit_name, table)
        )
    stats_tables += ["subreddit_activity"]  # Add `subreddit_activity`
    for table in stats_tables:
        delete_command = "DELETE FROM {} WHERE subreddit = ?".format(table)
        cursor_source_stats.execute(delete_command, (subreddit_name,))
        conn_source_stats.commit()
        logger.info(
            "Migration Assistant: Data removed for r/{} "
            "from source stats table `{}`.".format(subreddit_name, table)
        )

    return


def takeout(subreddit_name):
    """This function gets all the information about a subreddit and
    converts it to JSON to share with the moderators of a subreddit
    upon request. This should work for any subreddit that has data
    in the database, not just currently monitored.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A JSON document. If the document is of length 44,
             it can be treated as blank by other functions that use it.
    """

    # Package the actions and create the dictionary.
    master_dictionary = {
        "actions": counter_combiner(subreddit_name),
        "activity": {},
        "settings": extended_retrieve(subreddit_name),
    }

    # Package the activity.
    CURSOR_STATS.execute("SELECT * FROM subreddit_activity WHERE subreddit = ?", (subreddit_name,))
    results = CURSOR_STATS.fetchall()
    if results is not None:
        for entry in results:
            contents = literal_eval(entry[2])
            master_dictionary["activity"][entry[1]] = contents

    # Package the posts.
    posts_stats = statistics_posts_retrieve(subreddit_name)
    if posts_stats is not None:
        master_dictionary["statistics_posts"] = posts_stats

    # Package the subscribers.
    subbed_stats = subscribers_retrieve(subreddit_name)
    if subbed_stats is not None:
        master_dictionary["subscribers"] = subbed_stats

    # Package the traffic.
    CURSOR_STATS.execute("SELECT * FROM subreddit_traffic WHERE subreddit = ?", (subreddit_name,))
    traffic_result = CURSOR_STATS.fetchone()
    if traffic_result is not None:
        master_dictionary["traffic"] = literal_eval(traffic_result[1])

    # Convert to JSON.
    master_json = json_dumps(master_dictionary, sort_keys=True, indent=4)

    return master_json


def cleanup():
    """This function cleans up the `posts_processed` table and keeps
    only a certain amount left in order to prevent it from becoming
    too large. This keeps the newest `SETTINGS.entries_to_keep` post IDs
    and deletes the oldest ones.

    This function also truncates the events log to keep it at
    a manageable length, as well as the `posts_operations` table.

    :return: `None`.
    """
    # How many lines of log entries we wish to preserve in the logs.
    lines_to_keep = int(SETTINGS.entries_to_keep / SETTINGS.lines_to_keep_divider)
    ops_to_keep = int(SETTINGS.entries_to_keep * SETTINGS.operations_to_keep_multiplier)

    # Access the `processed` database, order the posts by oldest first,
    # and then only keep the above number of entries.
    delete_command = (
        "DELETE FROM posts_processed WHERE post_id NOT IN "
        "(SELECT post_id FROM posts_processed ORDER BY post_id DESC LIMIT ?)"
    )
    CURSOR_MAIN.execute(delete_command, (SETTINGS.entries_to_keep,))
    CONN_MAIN.commit()
    logger.info(
        "Cleanup: Last {:,} processed database " "entries kept.".format(SETTINGS.entries_to_keep)
    )

    # Access the `operations` database, and order the entries by
    # oldest first.
    delete_command = (
        "DELETE FROM posts_operations WHERE id NOT IN "
        "(SELECT id FROM posts_operations ORDER BY id DESC LIMIT ?)"
    )
    CURSOR_MAIN.execute(delete_command, (ops_to_keep,))
    CONN_MAIN.commit()
    logger.info("Cleanup: Last {:,} operations database " "entries kept.".format(ops_to_keep))

    # Clean up the logs. Keep only the last `lines_to_keep` lines.
    with open(FILE_ADDRESS.logs, "r", encoding="utf-8") as f:
        lines_entries = [line.rstrip("\n") for line in f]

    # If there are more lines than what we want to keep, truncate the
    # entire file to our limit.
    if len(lines_entries) > lines_to_keep:
        lines_entries = lines_entries[(-1 * lines_to_keep):]
        with open(FILE_ADDRESS.logs, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_entries))
        logger.info("Cleanup: Last {:,} log entries kept.".format(lines_to_keep))

    return


def cleanup_updated():
    """This function is called by the statistics routine to clean up the
    `subreddit_updated` table, which records which subreddits have had
    their statistics updated. Since that is a running number, it can
    be cleared after several days' worth of entries.

    :return: `None`.
    """
    updated_to_keep = int(SETTINGS.entries_to_keep / SETTINGS.updated_to_keep_divider)

    # Access the `updated` database, order the entries by their date,
    # and then only keep the above number of entries.
    delete_command = (
        "DELETE FROM subreddit_updated WHERE date NOT IN "
        "(SELECT date FROM subreddit_updated ORDER BY date DESC LIMIT ?)"
    )
    CURSOR_STATS.execute(delete_command, (updated_to_keep,))
    CONN_STATS.commit()
    logger.info("Cleanup: Last {:,} updated database entries kept.".format(updated_to_keep))

    return


define_database()
table_creator()  # Create the database tables if they do not exist.
