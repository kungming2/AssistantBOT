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
FILE_PATHS = {
    "auth": "/_auth.yaml",
    "data_main": "/_data_main.db",
    "data_stats": "/_data_stats.db",
    "data_stream": "/_data_stream.db",
    "error": "/_error.md",
    "logs": "/_logs.md",
    "logs_stats": "/_logs_stats.md",
    "logs_stream": "/_logs_stream.md",
    "info": "/_info.yaml",
    "messages": "/_messages.md",
    "messages_other": "/_messages_other.md",
    "start": "/_start.md",
    "settings": "/_settings.yaml",
}
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
    with open(FILE_ADDRESS.info, "r", encoding="utf-8") as f:
        info_data = yaml.safe_load(f.read())
    with open(FILE_ADDRESS.settings, "r", encoding="utf-8") as f:
        settings_data = yaml.safe_load(f.read())

    return info_data, settings_data


def load_instances(instance_num=99):
    """Function that loads specific authentication information for
    specific Artemis instances, indexed by a number between 0-9.
    The main (original) instance is given a unique number of 99.
    The function defaults to the main instance if no number is
    supplied.
    """
    with open(FILE_ADDRESS.auth, "r", encoding="utf-8") as f:
        instance_data = yaml.safe_load(f.read())

    return instance_data["accounts"][instance_num]


# Retrieve credentials data needed to log in from the YAML file.
INFO = SimpleNamespace(**load_information()[0])
SETTINGS = SimpleNamespace(**load_information()[1])
