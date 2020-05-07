#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""The settings component simply loads information from the relevant
YAML files, and transforms them into usable objects.
"""
import os
from types import SimpleNamespace

import yaml

# Define the location of the main files Artemis uses.
# They should all be in the same folder as the Python script itself.
# These addresses are then converted into a object for usage.
SOURCE_FOLDER = os.path.dirname(os.path.realpath(__file__))
FILE_PATHS = {'data_main': "/_data_main.db",
              'data_stats': "/_data_stats.db",
              'error': "/_error.md",
              "logs": "/_logs.md",
              "info": "/_info.yaml",
              'messages': "/_messages.md",
              'messages_other': "/_messages_other.md",
              'start': '/_start.md',
              "settings": "/_settings.yaml"}
for file_type in FILE_PATHS:
    FILE_PATHS[file_type] = SOURCE_FOLDER + FILE_PATHS[file_type]
FILE_ADDRESS = SimpleNamespace(**FILE_PATHS)


"""LOAD CREDENTIALS & SETTINGS"""


def load_information():
    """Function that takes information on login/OAuth access from an
    external YAML file and loads it as a dictionary. It also loads the
    settings as a dictionary. Both are returned in a tuple.

    :return: A tuple containing two dictionaries, one for authentication
             data and the other with settings.
    """
    with open(FILE_ADDRESS.info, 'r', encoding='utf-8') as f:
        auth_data = yaml.safe_load(f.read())
    with open(FILE_ADDRESS.settings, 'r', encoding='utf-8') as f:
        settings_data = yaml.safe_load(f.read())

    return auth_data, settings_data


# Retrieve credentials data needed to log in from the YAML file.
AUTH = SimpleNamespace(**load_information()[0])
SETTINGS = SimpleNamespace(**load_information()[1])
