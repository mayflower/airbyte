# Copyright (c) 2025 Airbyte, Inc., all rights reserved.

"""
This module is used to customize the build process for this connector.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional


def get_additional_python_dependencies() -> List[str]:
    """
    Return a list of additional Python dependencies to install for the connector.

    This will be called during connector build to install any additional dependencies
    required for the connector that aren't included in the base image.
    """
    return ["python-magic"]


def get_additional_debian_packages() -> List[str]:
    """
    Return a list of additional Debian packages to install for the connector.

    Required to support libmagic for MIME type detection.
    """
    return ["libmagic1"]
