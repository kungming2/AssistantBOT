#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import sqlite3
import sys
import time
from ast import literal_eval
from calendar import monthrange
from collections import Counter
from random import sample

import artemis_stats
import connection
import database
import timekeeping
from common import logger
from settings import AUTH, FILE_ADDRESS

"""LOGGING IN"""

connection.login()
reddit = connection.reddit
reddit_helper = connection.reddit_helper

"""TESTING / EXTERNAL FUNCTIONS"""


def external_random_test(query):
    """ Fetch initialization information for a random selection of
    non-local subeddits. This is used to test the process and procedure
    of adding new subreddits to the bot's monitored database.
    """
    already_monitored = database.monitored_subreddits_retrieve()

    if query == 'random':
        # Choose a number of random subreddits to test. There is code
        # here to alternately try to get an alternative if the random
        # one is already being monitored.
        random_subs = []
        num_initialize = int(input('\nEnter the number of random subreddits to initialize: '))
        for _ in range(num_initialize):
            # noinspection PyUnboundLocalVariable
            first_retrieve = reddit.random_subreddit().display_name.lower()
            if first_retrieve not in already_monitored:
                random_subs.append(first_retrieve)
            else:
                random_subs.append(reddit.random_subreddit().display_name.lower())
        random_subs.sort()
        print("\n\n### Now testing: r/{}.\n".format(', r/'.join(random_subs)))

        init_times = []
        for test_sub in random_subs:
            print("\n\n### Initializing data for r/{}...\n".format(test_sub))
            starting = time.time()
            artemis_stats.initialization(test_sub, create_wiki=False)
            generated_text = artemis_stats.wikipage_collater(test_sub)
            artemis_stats.wikipage_editor_local(test_sub, generated_text)
            elapsed = (time.time() - starting) / 60
            init_times.append(elapsed)
            print("\n\n# r/{} data ({:.2f} mins):\n\n{}\n\n---".format(test_sub, elapsed,
                                                                       generated_text))
        print('\n\n### All {} initialization tests complete. '
              'Average initialization time: {:.2f} mins'.format(num_initialize,
                                                                sum(init_times) / len(init_times)))
    else:
        # Initialize the data for the sub.
        logger.info('Manually intializing data for r/{}.'.format(query))
        time_initialize_start = time.time()
        artemis_stats.initialization(query, create_wiki=False)
        initialized = (time.time() - time_initialize_start)
        print("\n---\n\nInitialization time: {:.2f} minutes".format(initialized / 60))

        # Generate and print the collated data just as the wiki page
        # would look like.
        print(artemis_stats.wikipage_collater(query))
        elapsed = (time.time() - time_initialize_start)
        print("\nTotal elapsed time: {:.2f} minutes".format(elapsed / 60))

    return


def external_local_test(query):
    """Fetch initialization information for a random selection of
    locally stored subeddits.
    """
    # Now begin to test the collation by running the
    # function, making sure there are no errors.
    if query == 'random':
        # Fetch all the subreddits we monitor and ask for
        # the number to test.
        number_to_test = int(input("\nEnter the number of tests to conduct: "))
        random_subs = sample(database.monitored_subreddits_retrieve(), number_to_test)
        random_subs.sort()
        print("\n\n### Now testing: r/{}.\n".format(', r/'.join(random_subs)))

        init_times = []
        for test_sub in random_subs:
            time_initialize_start = time.time()
            print("\n---\n\n> Testing r/{}...\n".format(test_sub))

            # If the length of the generated text is longer than a
            # certain amount, then it's passed.
            tested_data = artemis_stats.wikipage_collater(test_sub)
            if len(tested_data) > 1000:
                total_time = time.time() - time_initialize_start
                artemis_stats.wikipage_editor_local(test_sub, tested_data)
                print("> Test complete for r/{} in {:.2f} seconds.\n".format(test_sub,
                                                                             total_time))
                init_times.append(total_time)
        print('\n\n# All {} wikipage collater tests complete. '
              'Average initialization time: {:.2f} secs'.format(number_to_test,
                                                                sum(init_times) / len(init_times)))
    else:
        logger.info('Testing data for r/{}.'.format(query))
        print(artemis_stats.wikipage_collater(query))

    return


def external_artemis_monthly_statistics(month_string):
    """This function collects various statistics on the bot's actions
    over a certain month and returns them as a Markdown segment.

    :param month_string: A month later than December 2019, expressed as
                         YYYY-MM.
    :return: A Markdown segment of text.
    """
    list_of_days = []
    list_of_actions = []
    list_of_lines = []
    list_of_posts = []
    added_subreddits = {}
    formatted_subreddits = []
    actions = {}
    actions_total = {}
    actions_flaired = {}
    posts = {}

    # Omit these actions from the chart.
    omit_actions = ['Removed as moderator']

    # Get the UNIX times that bound our month.
    year, month = month_string.split('-')
    start_time = timekeeping.convert_to_unix(month_string + '-01')
    end_time = "{}-{}".format(month_string, monthrange(int(year), int(month))[1])
    end_time = timekeeping.convert_to_unix(end_time) + 86399

    # Get the subreddits that were added during this month.
    current_subreddits = database.monitored_subreddits_retrieve()
    for post in reddit_helper.redditor(AUTH.username).submissions.new(limit=100):
        if "accepted" in post.title.lower() and end_time >= post.created_utc >= start_time:
            new_sub = post.title.split('r/')[1]
            added_subreddits[new_sub] = post.over_18
    for subreddit in added_subreddits:
        if subreddit not in current_subreddits:
            continue
        elif reddit.subreddit(subreddit).subreddit_type not in ['public', 'restricted']:
            continue
        else:
            is_nsfw = added_subreddits[subreddit]
            if is_nsfw:
                formatted_subreddits.append(subreddit + " (NSFW)")
            else:
                formatted_subreddits.append(subreddit)
    formatted_subreddits.sort(key=lambda y: y.lower())
    added_section = "\n# Artemis Overall Statistics — {}".format(month_string)
    added_section += ("\n\n### Added Subreddits\n\n"
                      "* r/{}".format('\n* r/'.join(formatted_subreddits)))
    added_section += "\n* **Total**: {} public subreddits".format(len(formatted_subreddits))

    # Get the actions from during this time period.
    database.CURSOR_STATS.execute('SELECT * FROM subreddit_actions WHERE subreddit == ?', ('all',))
    actions_s = literal_eval(database.CURSOR_STATS.fetchone()[1])
    database.CURSOR_MAIN.execute('SELECT * FROM subreddit_actions WHERE subreddit == ?', ('all',))
    actions_m = literal_eval(database.CURSOR_MAIN.fetchone()[1])

    # Combine the actions together.
    all_days = list(set(list(actions_s.keys()) + list(actions_m.keys())))
    all_days.sort()
    for day in all_days:
        actions[day] = dict(Counter(actions_s[day]) + Counter(actions_m[day]))

    # Iterate over the days and actions in the actions dictionaries.
    for day in actions:
        if end_time >= timekeeping.convert_to_unix(day) >= start_time:
            list_of_days.append(day)
        for action in actions[day]:
            if action not in list_of_actions and action not in omit_actions:
                list_of_actions.append(action)

    # Sort and form the header.
    list_of_actions.sort()
    list_of_days.sort()
    for action in list_of_actions:
        actions_total[action] = 0
    header = "Date | " + " | ".join(list_of_actions)
    divider = "----|---" * len(list_of_actions)

    # Iterate over the days and form line-by-line actions.
    for day in list_of_days:
        day_data = actions[day]
        formatted_components = []
        for action in list_of_actions:
            if action in day_data:
                formatted_components.append("{:,}".format(day_data[action]))
                actions_total[action] += day_data[action]
                if action.startswith('Flaired'):
                    actions_flaired[day] = day_data[action]
            else:
                formatted_components.append('---')
        day_line = "| {} | {} ".format(day, ' | '.join(formatted_components))
        list_of_lines.append(day_line)

    # Sum up the total number of actions as a final line.
    formatted_components = []
    for action in list_of_actions:
        formatted_components.append("{:,}".format(actions_total[action]))
    total_line = "| **Total** | {} ".format(' | '.join(formatted_components))
    list_of_lines.append(total_line)

    # Calculate the result of actions upon messages. This will also
    # calculate the percentage of each action per day.
    messages_dict = {}
    messages_lines = []
    messages_header = ('### Daily Flairing Messages\n\n'
                       '| Date | Total messages | Directly flaired | Fuzzed | Matched | Passed |\n'
                       '|------|----------------|------------------|--------|---------|--------|\n'
                       )
    with open(FILE_ADDRESS.messages, 'r', encoding='utf-8') as f:
        messages_data = f.read()
    messages_list = messages_data.split('\n')[2:]  # Skip table headers.

    # Process the messages list into a dictionary indexed by date.
    # Within each date entry is a dictionary with actions.
    for entry in messages_list:
        message_date = entry.split('|')[1].strip()
        message_action = entry.split('|')[5].strip()
        if message_date in messages_dict:
            if message_action in messages_dict[message_date]:
                messages_dict[message_date][message_action] += 1
            else:
                messages_dict[message_date][message_action] = 1
        else:
            messages_dict[message_date] = {message_action: 1}
    message_line = ("| {} | {} | **{}** ({:.0%}) | **{}** ({:.0%}) "
                    "| **{}** ({:.0%}) | **{}** ({:.0%}) |")
    for day in list_of_days:
        successful_count = actions_flaired[day]
        if day in messages_dict:
            fuzzed_count = messages_dict[day].get('Fuzzed', 0)
            matched_count = messages_dict[day].get('Matched', 0)
            passed_count = messages_dict[day].get('None', 0)
            total = successful_count + fuzzed_count + matched_count + passed_count
        else:
            fuzzed_count = matched_count = passed_count = 0
            total = int(successful_count)
        line = message_line.format(day, total, successful_count, successful_count / total,
                                   fuzzed_count, fuzzed_count / total, matched_count,
                                   matched_count / total, passed_count, passed_count / total)
        messages_lines.append(line)
    messages_body = messages_header + '\n'.join(messages_lines)

    # Collect the number of posts across ALL subreddits.
    # This also adds a final line summing up everything.
    posts_total = 0
    database.CURSOR_STATS.execute("SELECT * FROM subreddit_stats_posts")
    stats_results = database.CURSOR_STATS.fetchall()
    for entry in stats_results:
        sub_data = literal_eval(entry[1])
        for day in list_of_days:
            if day not in sub_data:
                continue
            if day in posts:
                posts[day] += sum(sub_data[day].values())
            else:
                posts[day] = sum(sub_data[day].values())
            posts_total += sum(sub_data[day].values())
    for day in list(sorted(posts.keys())):
        line = "| {} | {:,} |".format(day, posts[day])
        list_of_posts.append(line)
    list_of_posts.append('| **Total** | {:,} |'.format(posts_total))
    posts_data = ("### Daily Processed Posts\n\n| Date | Number of Posts |"
                  "\n|------|-----------------|\n{}".format('\n'.join(list_of_posts)))

    # Finalize the text to return.
    body = "{}\n\n{}\n\n{}\n\n### Daily Actions\n\n".format(added_section, posts_data,
                                                            messages_body)
    body += "{}\n{}\n{}".format(header, divider, "\n".join(list_of_lines))

    return body


def external_mail_alert():
    """ Function to mail moderators of subreddits that use the flair
    enforcement function to let them know about downtime or any other
    such issues. To be rarely used.
    """
    flair_enforced_subreddits = database.monitored_subreddits_retrieve(True)
    flair_enforced_subreddits.sort()

    # Retrieve the message to send.
    subject = input("\nPlease enter the subject of the message: ").strip()
    subject = '[Artemis Alert] {}'.format(subject)
    message = input("\nPlease enter the message you wish to send "
                    "to {} subreddits: ".format(len(flair_enforced_subreddits))).strip()

    # Send the message to moderators.
    for subreddit in flair_enforced_subreddits:
        reddit.subreddit(subreddit).message(subject, message)
        logger.info('External Mail: Sent a message to the moderators of r/{}.'.format(subreddit))

    return


def external_database_splitter():
    """This function splits a monolithic `_data.db` Artemis Classic
    database into two separate ones for use in 2.0 Juniper.
    """
    # Define the location of the donor database file to split.
    donor_db_address = FILE_ADDRESS.data_main.replace('data_main', 'data')
    conn_donor = sqlite3.connect(donor_db_address)
    cursor_donor = conn_donor.cursor()

    # Fetch the subreddit actions for saving and to be processed.
    # This is because subreddit actions have to be parsed out between
    # the two databases, in accordance with their action type.
    cursor_donor.execute('SELECT * FROM subreddit_actions WHERE subreddit != ?', ('all',))
    actions = cursor_donor.fetchall()
    cursor_donor.execute('SELECT * FROM subreddit_actions WHERE subreddit = ?', ('all',))
    all_actions = literal_eval(cursor_donor.fetchone()[1])

    # Create the main database tables if they do not already exist.
    main_tables = ['monitored', 'posts_filtered', 'posts_operations', 'posts_processed']
    database.CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS monitored (subreddit text, "
                                 "flair_enforce integer, extended text);")
    database.CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS posts_filtered (post_id text, "
                                 "post_created integer);")
    database.CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS posts_operations (id text, "
                                 "operations text);")
    database.CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS posts_processed (post_id text);")
    database.CURSOR_MAIN.execute("CREATE TABLE IF NOT EXISTS subreddit_actions (subreddit text,"
                                 "recorded_actions text);")
    database.CONN_MAIN.commit()
    print("Main tables created, if they don't exist already.")

    # Create the statistics database tables if they do not already
    # exist.
    stats_tables = ['subreddit_activity', 'subreddit_stats_posts', 'subreddit_subscribers_new',
                    'subreddit_traffic', 'subreddit_updated']
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_actions (subreddit text, "
                                  "recorded_actions text);")
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_activity (subreddit text, "
                                  "date text, activity text);")
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_stats_posts "
                                  "(subreddit text, records text);")
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_subscribers_new "
                                  "(subreddit text, records text);")
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_traffic "
                                  "(subreddit text, traffic text);")
    database.CURSOR_STATS.execute("CREATE TABLE IF NOT EXISTS subreddit_updated "
                                  "(subreddit text, date text);")
    print("Statistics tables created, if they don't exist already.")

    # Start the copying for both databases. Subreddit actions is dealt
    # with later.
    database.CURSOR_MAIN.execute("ATTACH ? AS donor", (donor_db_address,))
    for table in main_tables:
        database.CURSOR_MAIN.execute("SELECT * FROM {}".format(table))
        result = database.CURSOR_MAIN.fetchone()
        if result:
            print("Data already exists in main table `{}`. Skipping...".format(table))
            continue
        command = "INSERT INTO {0} SELECT * from donor.{0}".format(table)
        database.CURSOR_MAIN.execute(command)
        database.CONN_MAIN.commit()
        print("Completed copying main database table `{}`.".format(table))
    database.CURSOR_STATS.execute("ATTACH ? AS donor", (donor_db_address,))
    for table in stats_tables:
        database.CURSOR_STATS.execute("SELECT * FROM {}".format(table))
        result = database.CURSOR_STATS.fetchone()
        if result:
            print("Data already exists in stats table `{}`. Skipping...".format(table))
            continue
        command = "INSERT INTO {0} SELECT * from donor.{0}".format(table)
        database.CURSOR_STATS.execute(command)
        database.CONN_STATS.commit()
        print("Completed copying statistics database table `{}`.".format(table))

    # Deal with subreddit actions.
    actions_main = ['Exported takeout data', 'Flaired post', 'Removed as moderator',
                    'Removed post', 'Restored post', 'Retrieved query data',
                    'Reverted configuration', 'Sent flair reminder', 'Updated configuration']
    actions_stats = ['Updated statistics', 'Updated userflair statistics']
    for entry in actions:
        subreddit_main_actions = {}
        subreddit_stats_actions = {}

        # Sort out the actions by their respective databases.
        subreddit = entry[0]
        actions_data = literal_eval(entry[1])
        for action in actions_data:
            if action in actions_main:
                subreddit_main_actions[action] = actions_data[action]
            elif action in actions_stats:
                subreddit_stats_actions[action] = actions_data[action]
            elif action not in actions_main and action not in actions_stats:
                print("Error: Action `{}` on r/{} is not listed.".format(action, subreddit))

        # Insert the actions into their respective tables.
        if subreddit_main_actions:
            database.CURSOR_MAIN.execute('INSERT INTO subreddit_actions VALUES (?, ?)',
                                         (subreddit, str(subreddit_main_actions)))
            database.CONN_MAIN.commit()
        if subreddit_stats_actions:
            database.CURSOR_STATS.execute('INSERT INTO subreddit_actions VALUES (?, ?)',
                                          (subreddit, str(subreddit_stats_actions)))
            database.CONN_STATS.commit()
    print("Completed actions transfer.")

    # Now deal with the 'all' actions table. We duplicate this in the
    # sense that there are going to be one respective 'all' table per
    # `subreddit_actions` table that can be conjoined later.
    all_main_actions = {}
    all_stats_actions = {}
    for date in sorted(all_actions)[:100]:
        date_stats = dict((k, all_actions[date][k]) for k in actions_stats
                          if k in all_actions[date])
        all_stats_actions[date] = date_stats
        date_main = dict((k, all_actions[date][k]) for k in actions_main
                         if k in all_actions[date])
        all_main_actions[date] = date_main
    if all_main_actions:
        database.CURSOR_MAIN.execute('INSERT INTO subreddit_actions VALUES (?, ?)',
                                     ('all', str(all_main_actions)))
        database.CONN_MAIN.commit()
    if all_stats_actions:
        database.CURSOR_STATS.execute('INSERT INTO subreddit_actions VALUES (?, ?)',
                                      ('all', str(all_stats_actions)))
        database.CONN_STATS.commit()
    print("Completed 'all' actions transfer.")

    return


if len(sys.argv) > 1:
    REGULAR_MODE = False
    # Get the mode keyword that's accepted after the script path.
    specific_mode = sys.argv[1].strip().lower()
    # noinspection PyUnboundLocalVariable
    logger.info("LOCAL MODE: Launching Artemis in '{}' mode.".format(specific_mode))

    if specific_mode == 'start':  # We want to fetch specific information for a sub.
        l_mode = input("\n====\n\nEnter 'random', name of a new sub, or 'x' to exit: ")
        l_mode = l_mode.lower().strip()

        # Exit the routine if the value is x.
        if l_mode == 'x':
            sys.exit()
        else:
            external_random_test(l_mode)
    elif specific_mode == "test":
        # This runs the wikipage generator through randomly selected
        # subreddits that have already saved data.
        l_mode = input("\n====\n\nEnter 'random', name of a sub, or 'x' to exit: ").lower().strip()

        # Exit the routine if the value is x.
        if l_mode == 'x':
            sys.exit()
        else:
            external_local_test(l_mode)
    elif specific_mode == "userflair":
        userflair_subs = input("\n====\n\nEnter a list of subreddits for userflair statistcs: ")
        userflair_subs_list = userflair_subs.split(',')
        userflair_subs_list = [x.strip() for x in userflair_subs_list]
        artemis_stats.wikipage_userflair_editor(userflair_subs_list)
    elif specific_mode == 'alert':
        external_mail_alert()
    elif specific_mode == 'split':
        external_database_splitter()
    elif specific_mode == 'stats':
        month_stats = input("\n====\n\nEnter the month in YYYY-MM format or 'x' to exit: ").strip()
        print(external_artemis_monthly_statistics(month_stats))
