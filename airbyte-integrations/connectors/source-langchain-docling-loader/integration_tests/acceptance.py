#
# Copyright (c) 2025 Airbyte, Inc., all rights reserved.
#

import json
import os

from source_langchain_docling_loader.source import SourceLangchainDoclingLoader

from airbyte_cdk.models import ConnectorSpecification, SyncMode
from airbyte_protocol.models import DestinationSyncMode
