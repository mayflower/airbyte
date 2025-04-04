#
# Copyright (c) 2025 Airbyte, Inc., all rights reserved.
#

import sys

from airbyte_cdk.entrypoint import launch

from .source import SourceLangchainDoclingLoader


def run(args=None):
    args = args or sys.argv[1:]
    source = SourceLangchainDoclingLoader()
    launch(source, args)
