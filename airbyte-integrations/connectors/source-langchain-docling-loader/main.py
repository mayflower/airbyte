#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import sys

from source_langchain_docling_loader.run import run


if __name__ == "__main__":
    run(sys.argv[1:])
