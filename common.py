#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import datetime
import logging
import re
import time

from settings import AUTH, FILE_ADDRESS

"""INITIALIZATION INFORMATION"""


def main_error_log(entry):
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
    with open(FILE_ADDRESS.error, 'a+', encoding='utf-8') as f:
        error_date_format = datetime.datetime.utcnow().strftime("%Y-%m-%dT%I:%M:%SZ")
        bot_format = "Artemis v{}".format(AUTH.version_number)
        entry = entry.replace('\n', '\n    ')  # Indent the code.
        f.write("\n---------------\n### {} ({})\n{}\n".format(error_date_format, bot_format,
                                                              entry))

    return


"""LOGGER SETUP"""

# Set up the logger. By default only display INFO or higher levels.
log_format = '%(levelname)s: %(asctime)s - [Artemis] v{} %(message)s'
logformatter = log_format.format(AUTH.version_number)
logging.basicConfig(format=logformatter, level=logging.INFO)

# Set the logging time to UTC.
logging.Formatter.converter = time.gmtime
logger = logging.getLogger(__name__)

# Define the logging handler (the file to write to.)
# By default only log INFO level messages or higher.
handler = logging.FileHandler(FILE_ADDRESS.logs, 'a', 'utf-8')
handler.setLevel(logging.INFO)

# Set the time format in the logging handler.
d = "%Y-%m-%dT%H:%M:%SZ"
handler.setFormatter(logging.Formatter(logformatter, datefmt=d))
logger.addHandler(handler)


"""OTHER FUNCTIONS"""


def flair_sanitizer(text_to_parse, change_case=True):
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
