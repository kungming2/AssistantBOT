#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The STREAM runtime is a low-key replacement for some of the
functions that Pushshift did for aggregations. It stores selected post
data in a local database to use for searches and aggregations.

Note that Stream does not use any of the main databases used by Main or
Stats. It's a separate database, and the other routines will not WRITE
to that database.

When imported as a module, this script also hosts a function that can be
used to query the database about post data.
"""
import re
import sqlite3
from ast import literal_eval
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

import connection
import timekeeping
from common import logger
from database import database_access
from settings import INFO, FILE_ADDRESS
from timekeeping import convert_to_unix

CONN_STREAM = sqlite3.connect(FILE_ADDRESS.data_stream)
CURSOR_STREAM = CONN_STREAM.cursor()

# A list of saved post attributes, in addition to author and
# subreddit. These are additional ones.
ATTRIBUTE_LIST = [
    "author_flair_text",
    "domain",
    "id",
    "is_self",
    "is_video",
    "link_flair_css_class",
    "link_flair_template_id",
    "link_flair_text",
    "over_18",
    "spoiler",
    "subreddit_subscribers",
    "title",
]

"""ACCESS/SEARCH FUNCTIONS"""


def stream_query_access(query_string, return_pushshift_format=True):
    """Function that interacts with `subreddit_pushshift_access` to
    provide local access to the stream database and parcel out
    different queries to different functions.
    This function will return an empty dictionary if a query looking for
    comment data is passed to it.

    :param query_string: The exact API call made to Pushshift. This will
                         be broken up by this function.
    :param return_pushshift_format: Whether or not to return the data in
                                    a format that mimics the PS `aggs`
                                    data for backwards compatibility.
                                    Newer functions built on top of
                                    Stream do not need to return it in
                                    such a format.
    :return: An empty dictionary if the query is for comment data,
             otherwise, it'll return a Pushshift formatted dictionary or
             a Counter, depending on `return_pushshift_format`.
    """
    query_object = {}

    # Ensure that we're searching for submissions, not comments.
    search_type = re.search(r"/search.*/(.*)/", query_string).group(1)
    if search_type != "submission":
        logger.info("Stream Query Access: Query is for unstored comment data.")
        return {}

    # Get the main variables and store them in a dictionary, which is
    # then turned into the `query` object for working with.
    request_variables = urlparse(query_string).query
    query_dictionary = parse_qs(request_variables)
    for key, value in query_dictionary.items():
        main_value = query_dictionary[key][0]
        if key in ["after", "before", "size"]:
            query_object[key] = int(main_value)
        else:
            query_object[key] = main_value
    query = SimpleNamespace(**query_object)

    # `aggs` can serve as the main operator telling us what kind of
    # query we wanna run.
    query_type = query.aggs
    logger.info("Stream Query Access: Now querying `{}` on "
                "r/{} data.".format(query_type, query.subreddit))
    sub_data = stream_database_fetcher(query.subreddit, query.after, query.before)
    most_common_data = stream_most_common(query_type, sub_data)

    # If specific compatibility with Pushshift is requested, format the
    # response in a way that matches the results normally returned.
    if return_pushshift_format:
        logger.info("Stream Query Access: Returning data in Pushshift format.")
        final_data = stream_ps_response_former(most_common_data, query_type, query.size)
    else:
        final_data = most_common_data

    return final_data


def stream_database_fetcher(subreddit_name, after_time, before_time):
    """This function fetches all the data in the stream dictionary
    matching that of a particular subreddit and its time parameters.

    :param subreddit_name: Name of the subreddit we're looking for.
    :param after_time: We want to find posts *after* this UNIX time.
    :param before_time: We want to find posts *before* this UNIX time.
    :return: An object with all the posts belonging to that subreddit.
    """
    master_dictionary = {}
    subreddit_name = subreddit_name.lower()

    # Conduct a search matching these particular search conditions.
    # These are returned as a list of tuples, which we then convert
    # into a dictionary with each post as an object.
    sub_search_string = f"%'subreddit': '{subreddit_name}'%"
    results = database_access(
        "SELECT id, data FROM posts WHERE created_utc >= ? "
        "AND ? >= created_utc AND data LIKE ?",
        (after_time, before_time, sub_search_string),
        cursor=CURSOR_STREAM,
        fetch_many=True,
    )

    # Objectify the posts and their contained data and assign them
    # to the main dictionary.
    for result in results:
        post_id = result[0]
        post_data_dict = literal_eval(result[1])
        post_object = SimpleNamespace(**post_data_dict)
        master_dictionary[post_id] = post_object

    return master_dictionary


def stream_most_common(query_field, master_dictionary):
    """A basic function to get the most common value for posts in a
    certain set.
    :param query_field: The attribute of the object we're looking for.
    :param master_dictionary: A dictionary from the above function
                              `stream_database_fetcher` containing
                              post objects to iterate over.
    :return:
    """
    operating_list = []

    # Iterate over the dictionary and add the values we're looking for
    # to the operating list.
    for item in master_dictionary.values():
        dict_value = getattr(item, query_field)
        # If looking for dates in UTC, we convert the number to the
        # start of that day in UNIX time for standardization.
        if query_field == "created_utc":
            date_as_string = getattr(item, "created_str").split("T")[0]
            dict_value = convert_to_unix(date_as_string)
        operating_list.append(dict_value)

    # Call Counter to get most common items, sorted by most common
    # first.
    logger.info(
        "Stream Most Common: {:,} items for `{}` query subset.".format(
            len(operating_list), query_field
        )
    )
    sorted_counter = Counter(operating_list)
    logger.info(
        "Stream Most Common: Top 3 results were: " "`{}`".format(sorted_counter.most_common(3))
    )

    return sorted_counter


def stream_ps_response_former(counter_object, query_type, results_size):
    """This simple function formats counter data from
    `stream_most_common` into a dictionary format that is compatible
    with Pushshift response data for backwards compatibility.
    :param counter_object: A Counter object from `stream_most_common`.
    :param query_type: The original query type.
    :param results_size: How many results to return.
    :return:
    """
    # Get the most common objects according to `results_size` amount.
    counter_list = []
    most_common_objs = counter_object.most_common(results_size)
    for listing in most_common_objs:
        counter_list.append({"key": listing[0], "doc_count": listing[1]})

    # Format for compatibility with Pushshift aggs data. Return an
    # empty dictionary if there's no data.
    if len(counter_list):
        pushshift_formatted_dict = {"aggs": {query_type: counter_list}}
    else:
        pushshift_formatted_dict = {}

    return pushshift_formatted_dict


"""FETCH FUNCTIONS"""


def chunks(list_items, num_per_chunk):
    """Simple function that divides the list of subreddits into
    chunks to fetch.

    :param list_items: A list with items to divide.
    :param num_per_chunk: How many items per chunk.
    :return: A list of chunks.
    """
    # For item i in a range that is a length of l,
    for i in range(0, len(list_items), num_per_chunk):
        # Create an index range for l of n items:
        yield list_items[i:i + num_per_chunk]


def posts_writer(posts_data):
    """Routine that writes to the database the post data from a list of
    posts. Does not overwrite any previously stored data.
    """
    count = 0
    progress_marker = 50

    for post in posts_data:
        relevant_data = posts_data[post]
        post_id = str(post)
        post_time = int(relevant_data["created_utc"])
        command = "SELECT * FROM posts WHERE id = ?"
        CURSOR_STREAM.execute(command, (post_id,))
        result = CURSOR_STREAM.fetchone()

        if not result:
            CURSOR_STREAM.execute(
                "INSERT INTO posts VALUES (?, ?, ?)",
                (post_id, post_time, str(relevant_data)),
            )
            CONN_STREAM.commit()
            logger.debug("Posts Writer: Post `{}` added to stream database.".format(post_id))
            count += 1
        else:
            logger.debug(
                "Posts Writer: Post `{}` already exists in " "stream database.".format(post_id)
            )

        # Show the progress.
        if count % progress_marker == 0 and count != 0:
            logger.info("Posts Writer: {:,} posts written.".format(count))

    return


def posts_parser(posts_list):
    """This function parses a list of posts and fetches certain
    information about each post to save. This reduces the amount of
    space needed to save by only saving relevant data fields.

    :param posts_list: A list of posts as PRAW objects.
    :return: A dictionary of ID-indexed dictionaries with the smaller
             elements of data we want to save.
    """
    master_dictionary = {}
    skipped = 0

    # Check for the last created post time. We only want posts after
    # this time period.
    CURSOR_STREAM.execute("SELECT * FROM posts ORDER BY created_utc DESC LIMIT 1")
    last_saved = CURSOR_STREAM.fetchone()
    last_saved_time = int(last_saved[1])
    logger.info(
        "Posts Parser: Keeping posts made after: "
        "{}".format(timekeeping.time_convert_to_string(last_saved_time))
    )

    # Iterate over posts.
    for post in posts_list:

        # Skip posts older than our last saved.
        if int(post.created_utc) < last_saved_time:
            skipped += 1
            continue

        # At minimum, we save these attributes.
        shortened_package = {
            "author": str(post.author).lower(),
            "created_utc": int(post.created_utc),
            "created_str": timekeeping.time_convert_to_string(post.created_utc),
            "subreddit": str(post.subreddit).lower(),
        }
        try:
            logger.debug(post.link_flair_template_id)
        except AttributeError:
            logger.debug(
                "> Post has no template ID at: " "https://www.reddit.com{}".format(post.permalink)
            )
            if post.link_flair_text is not None:
                logger.debug(">> Post has post flair text `{}`.".format(post.link_flair_text))

        # Save the additional attributes.
        for attribute_save in ATTRIBUTE_LIST:
            shortened_package[attribute_save] = vars(post).get(attribute_save)

        # Assign this package to the master dictionary.
        master_dictionary[post.id] = shortened_package

    logger.info("Posts Parser: {:,} posts to be saved.".format(len(master_dictionary)))
    logger.info("Posts Parser: {:,} posts skipped.".format(skipped))
    posts_writer(master_dictionary)

    return master_dictionary


"""RUNTIME FUNCTIONS"""


def get_stream():
    """This just gathers data from public subreddits, instead of
    any private ones. As such, we can avoid using the databases.
    Then, this splits the list of subreddits into groups of 100.
    """
    chunk_size = 100
    instances = connection.CONFIG.available_instances

    # Fetch the available instances and their usernames.
    username = INFO.username
    available_usernames = ["{}{}".format(username, x) for x in instances]
    available_usernames += [INFO.username]
    available_usernames.sort()
    public_subreddits = []
    logger.info("Get Stream: Available usernames to check: {}".format(available_usernames))

    # Check and get the moderated subreddits for each username.
    for account in available_usernames:
        subs = connection.obtain_subreddit_public_moderated(account)["list"]
        public_subreddits += subs
    chunked = list(chunks(public_subreddits, chunk_size))
    logger.info(
        "Get Stream: Found {:,} public subreddits, "
        "broken into {} chunks.".format(len(public_subreddits), len(chunked))
    )

    return chunked


def get_streamed_posts(pull_amount=100):
    """This fetches the latest posts and organizes them across several
    subreddits. These posts are fetched as PRAW objects.

    :param pull_amount: The number of posts to get per portion.
    :return:
    """
    posts_all = []
    differences = []

    portions = get_stream()

    # Iterate through the lists of subreddits.
    for portion in portions:
        logger.info(
            "Get Posts: Checking portion {} of "
            "{}...".format(portions.index(portion) + 1, len(portions))
        )
        combined_multi = "+".join(portion)
        posts_new = list(reddit.subreddit(combined_multi).new(limit=pull_amount))
        posts_all += posts_new

        # Calculate the time differential per portion.
        first = posts_new[-1].created_utc
        last = posts_new[0].created_utc
        difference = int(last - first)
        average = difference / len(posts_new)
        differences.append(average)
        logger.info("Get Posts: {:.2f} minutes differential.".format(difference / 60))
        logger.info("Get Posts: Post every {:.2f} seconds on average.".format(average))

    logger.info(
        "Get Posts: Total average is a post every {:.2f} "
        "seconds.".format(sum(differences) / len(differences))
    )

    # Sort the posts by oldest first.
    posts_all.sort(key=lambda x: x.id.lower())
    posts_parser(posts_all)

    return


def integrity_check():
    """Simple function to check database integrity."""
    CURSOR_STREAM.execute(
        "PRAGMA quick_check;",
    )
    result = CURSOR_STREAM.fetchone()

    if 'ok' in result:
        logger.info("Integrity Check: Passed.")
        return True
    else:
        logger.info("Integrity Check: Failed.")
        return False


def get_streamed_comments(pull_amount=1000):
    """This fetches the latest comments across several
    subreddits. These posts are fetched as PRAW objects.
    This function is currently unused and exists as a proof-of-concept.

    :param pull_amount: The number of comments to get per portion.
    :return:
    """
    comments_all = []
    differences = []

    portions = get_stream()
    for portion in portions[0:6]:
        logger.info(
            "Get Comments: Checking portion {} of "
            "{}...".format(portions.index(portion) + 1, len(portions))
        )
        combined_multi = "+".join(portion)
        posts_new = list(reddit.subreddit(combined_multi).comments(limit=pull_amount))
        comments_all += posts_new

        first = posts_new[0].created_utc
        last = posts_new[-1].created_utc

        difference = int(abs(last - first))
        print(difference)
        print(difference / len(posts_new))
        differences.append(difference / len(posts_new))

    print(
        "Average = New comment every {:.2f} seconds.".format(sum(differences) / len(differences))
    )
    # Sort the posts by oldest first.
    comments_all.sort(key=lambda x: x.id.lower())

    return


# The main runtime if the module itself is called.
# */20 * * * *
if __name__ == "__main__":
    # Log into Reddit.
    logger.info("Stream: Beginning fetch.")
    connection.login(False, 0)
    reddit = connection.reddit
    logger.info("Stream: Logging in as u/{}.".format(reddit.user.me()))
    reddit_helper = connection.reddit_helper

    # Run the proper functions.
    get_streamed_posts()
    # get_streamed_comments()
    integrity_check()
    CONN_STREAM.close()
    logger.info("Stream: Ended fetch.")
