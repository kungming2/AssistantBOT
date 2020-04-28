#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import sqlite3
import time
from ast import literal_eval
from collections import Counter
from json import dumps as json_dumps

from common import logger
from settings import FILE_ADDRESS, SETTINGS
from timekeeping import convert_to_string


"""DATABASE DEFINITION"""


# This connects Artemis with its main SQLite database file.
CONN_STATS = sqlite3.connect(FILE_ADDRESS.data_stats)
CURSOR_STATS = CONN_STATS.cursor()

# This connects Artemis with its flair enforcement SQLite database file.
CONN_MAIN = sqlite3.connect(FILE_ADDRESS.data_main)
CURSOR_MAIN = CONN_MAIN.cursor()


"""DATABASE FUNCTIONS"""


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
        CURSOR_MAIN.execute("INSERT INTO monitored VALUES (?, ?, ?)",
                            (community_name, 1, str(supplement)))
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
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (community_name,))
    result = CURSOR_MAIN.fetchone()

    if result is not None:  # Subreddit is in database. Let's remove it.
        CURSOR_MAIN.execute("DELETE FROM monitored WHERE subreddit = ?",
                            (community_name,))
        CONN_MAIN.commit()
        logger.info('Sub Delete: r/{} deleted from monitored database.'.format(community_name))

    return


def monitored_subreddits_retrieve(flair_enforce_only=False):
    """This function returns a list of all the subreddits that
    Artemis monitors WITHOUT the 'r/' prefix.

    :param flair_enforce_only: A Boolean that if `True`, only returns
                               the subreddits that have flair enforcing
                               turned on.
    :return: A list of all monitored subreddits, in the order which
             they were first stored, oldest to newest.
    """
    if not flair_enforce_only:
        CURSOR_MAIN.execute("SELECT * FROM monitored")
    else:
        CURSOR_MAIN.execute("SELECT * FROM monitored WHERE flair_enforce is 1")
    results = CURSOR_MAIN.fetchall()

    # Gather the saved subreddits' names and add them into a list.
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
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_MAIN.fetchone()

    # This subreddit is stored in the monitored database; modify it.
    if result is not None:

        # If the current status is different, change it.
        if result[1] != s_digit:
            CURSOR_MAIN.execute("UPDATE monitored SET flair_enforce = ? WHERE subreddit = ?",
                                (s_digit, subreddit_name))
            CONN_MAIN.commit()
            logger.info("Enforce Change: r/{} flair enforce set to `{}`.".format(subreddit_name,
                                                                                 to_enforce))

    return


def monitored_subreddits_enforce_status(subreddit_name):
    """A function that returns True or False depending on the
    subreddit's `flair_enforce` status.
    That status is stored as an integer and converted into a Boolean.

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A boolean. Default is True.
    """
    subreddit_name = subreddit_name.lower()
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name,))
    result = CURSOR_MAIN.fetchone()

    # This subreddit is stored in our monitored database; access it.
    if result is not None:
        # This is the current status.
        flair_enforce_status = bool(result[1])
        logger.debug("Enforce Status: r/{} flair enforce status: {}.".format(subreddit_name,
                                                                             flair_enforce_status))
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
    CURSOR_MAIN.execute('DELETE FROM posts_filtered WHERE post_id = ?', (post_id,))
    CONN_MAIN.commit()
    logger.debug('Delete Filtered Post: Deleted post `{}` from filtered database.'.format(post_id))

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

    :param subreddit_name: Name of a subreddit (no r/).
    :return: A dictionary containing the extended data for a
             particular subreddit. None otherwise.
    """
    # Access the database.
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?", (subreddit_name.lower(),))
    result = CURSOR_MAIN.fetchone()

    # The subreddit has extended data to convert into a dictionary.
    if result is not None:
        return literal_eval(result[2])


def extended_insert(subreddit_name, new_data):
    """This function inserts data into the extended data stored in
    `monitored`. It will add data into the dictionary if the value
     does not exist, otherwise, it will modify it in place.

    :param subreddit_name: Name of a subreddit (no r/).
    :param new_data: A dictionary containing the data we want to merge
                     or change in the extended data entry.
    :return: Nothing.
    """
    CURSOR_MAIN.execute("SELECT * FROM monitored WHERE subreddit = ?",
                        (subreddit_name.lower(),))
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
                         (subreddit_name, month))
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_activity WHERE subreddit = ? AND date = ?",
                         (subreddit_name, month))
    result = CURSOR_STATS.fetchone()

    # Process the data. If there is no preexisting entry, Create a new
    # one, indexed with the activity type.
    if result is None:
        if activity_type != 'oldest':
            data_component = {activity_type: activity_data}
            data_package = (subreddit_name, month, str(data_component))
            CURSOR_STATS.execute('INSERT INTO subreddit_activity VALUES (?, ?, ?)', data_package)
            CONN_STATS.commit()
        else:  # 'oldest' posts get indexed by that phrase instead of by month.
            data_package = (subreddit_name, 'oldest', str(activity_data))
            CURSOR_STATS.execute('INSERT INTO subreddit_activity VALUES (?, ?, ?)', data_package)
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
            update_command = ("UPDATE subreddit_activity SET activity = ? "
                              "WHERE subreddit = ? AND date = ?")
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?",
                         (subreddit_name,))
    result = CURSOR_STATS.fetchone()

    # Process the data. If there is no preexisting subscribers entry,
    # create a new one.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_STATS.execute('INSERT INTO subreddit_subscribers_new VALUES (?, ?)', data_package)
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_subscribers_new WHERE subreddit = ?",
                         (subreddit_name,))
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_stats_posts WHERE subreddit = ?",
                         (subreddit_name,))
    result = CURSOR_STATS.fetchone()

    # We have no data.
    if result is None:
        data_package = (subreddit_name, str(new_data))
        CURSOR_STATS.execute('INSERT INTO subreddit_stats_posts VALUES (?, ?)', data_package)
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
    CURSOR_STATS.execute("SELECT * FROM subreddit_stats_posts WHERE subreddit = ?",
                         (subreddit_name,))
    result = CURSOR_STATS.fetchone()

    # We have data, let's turn the stored string into a dictionary.
    if result is not None:
        return literal_eval(result[1])

    return


def counter_updater(subreddit_name, action_type, database_type,
                    action_count=1, post_id=None, id_only=False):
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
        counter_cursor.execute('SELECT * FROM posts_operations WHERE id = ?', (post_id,))
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
    counter_cursor.execute('SELECT * FROM subreddit_actions WHERE subreddit = ?',
                           (subreddit_name,))
    result = counter_cursor.fetchone()

    # No actions data recorded. Create a new dictionary and save it.
    if result is None:
        actions_dictionary = {action_type: action_count}
        data_package = (subreddit_name, str(actions_dictionary))
        counter_cursor.execute('INSERT INTO subreddit_actions VALUES (?, ?)', data_package)
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
    counter_cursor.execute('SELECT * FROM subreddit_actions WHERE subreddit = ?', ('all',))
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
        counter_cursor.execute(update_command, (str(master_actions), 'all'))
        conn.commit()

    return


def counter_combiner(subreddit_name):
    """This function retrieves all actions from the two databases and
    combines them together into a single dictionary. Please note that
    this not work with `all`, for some reason.

    :return: A dictionary with action data, otherwise, `None`.
    """
    retrieve_command = 'SELECT * FROM subreddit_actions WHERE subreddit = ?'
    CURSOR_STATS.execute(retrieve_command, (subreddit_name,))
    result_s = CURSOR_STATS.fetchone()
    CURSOR_MAIN.execute(retrieve_command, (subreddit_name,))
    result_m = CURSOR_MAIN.fetchone()

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
    master_dictionary = {'actions': counter_combiner(subreddit_name),
                         'activity': {},
                         'settings': extended_retrieve(subreddit_name)}

    # Package the activity.
    CURSOR_STATS.execute('SELECT * FROM subreddit_activity WHERE subreddit = ?', (subreddit_name,))
    results = CURSOR_STATS.fetchall()
    if results is not None:
        for entry in results:
            contents = literal_eval(entry[2])
            master_dictionary['activity'][entry[1]] = contents

    # Package the posts.
    posts_stats = statistics_posts_retrieve(subreddit_name)
    if posts_stats is not None:
        master_dictionary['statistics_posts'] = posts_stats

    # Package the subscribers.
    subbed_stats = subscribers_retrieve(subreddit_name)
    if subbed_stats is not None:
        master_dictionary['subscribers'] = subbed_stats

    # Package the traffic.
    CURSOR_STATS.execute("SELECT * FROM subreddit_traffic WHERE subreddit = ?", (subreddit_name,))
    traffic_result = CURSOR_STATS.fetchone()
    if traffic_result is not None:
        master_dictionary['traffic'] = literal_eval(traffic_result[1])

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
    updated_to_keep = int(SETTINGS.entries_to_keep / SETTINGS.updated_to_keep_divider)
    ops_to_keep = int(SETTINGS.entries_to_keep * SETTINGS.operations_to_keep_multiplier)

    # Access the `processed` database, order the posts by oldest first,
    # and then only keep the above number of entries.
    delete_command = ("DELETE FROM posts_processed WHERE post_id NOT IN "
                      "(SELECT post_id FROM posts_processed ORDER BY post_id DESC LIMIT ?)")
    CURSOR_MAIN.execute(delete_command, (SETTINGS.entries_to_keep,))
    CONN_MAIN.commit()
    logger.info('Cleanup: Last {:,} processed database '
                'entries kept.'.format(SETTINGS.entries_to_keep))

    # Access the `updated` database, order the entries by their date,
    # and then only keep the above number of entries.
    delete_command = ("DELETE FROM subreddit_updated WHERE date NOT IN "
                      "(SELECT date FROM subreddit_updated ORDER BY date DESC LIMIT ?)")
    CURSOR_MAIN.execute(delete_command, (updated_to_keep,))
    CONN_MAIN.commit()
    logger.info('Cleanup: Last {:,} updated database entries kept.'.format(updated_to_keep))

    # Access the `operations` database, and order the entries by
    # oldest first.
    delete_command = ("DELETE FROM posts_operations WHERE id NOT IN "
                      "(SELECT id FROM posts_operations ORDER BY id DESC LIMIT ?)")
    CURSOR_MAIN.execute(delete_command, (ops_to_keep,))
    CONN_MAIN.commit()
    logger.info('Cleanup: Last {:,} operations database '
                'entries kept.'.format(ops_to_keep))

    # Clean up the logs. Keep only the last `lines_to_keep` lines.
    with open(FILE_ADDRESS.logs, "r", encoding='utf-8') as f:
        lines_entries = [line.rstrip("\n") for line in f]

    # If there are more lines than what we want to keep, truncate the
    # entire file to our limit.
    if len(lines_entries) > lines_to_keep:
        lines_entries = lines_entries[(-1 * lines_to_keep):]
        with open(FILE_ADDRESS.logs, "w", encoding='utf-8') as f:
            f.write("\n".join(lines_entries))
        logger.info('Cleanup: Last {:,} log entries kept.'.format(lines_to_keep))

    return
