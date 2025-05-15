import sys

from airbyte_cdk.entrypoint import launch
from source_imap.source import SourceImap


def run():
    source = SourceImap()
    launch(source, sys.argv[1:])

if __name__ == "__main__":
    run()