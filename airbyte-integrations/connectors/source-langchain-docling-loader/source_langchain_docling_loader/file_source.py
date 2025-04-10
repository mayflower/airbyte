import hashlib
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List

class AbstractFileSource(ABC):
    @abstractmethod
    def get_file_id(self, uri)  -> str:
        """
        Generate a unique ID for a file based on its uri and modification time
        """
        pass

    @abstractmethod
    def list_files(self, uri) -> List[str]:
        """
        Recursively scan an uri for supported document files
        """
        pass

    @abstractmethod
    def download_files(self, uri) -> List[str]:
        """
        Download files to the local filesystem.
        """
        pass

    @abstractmethod
    def get_modified_time(self, uri) -> datetime:
        """
        Get the last modified time of a file
        """
        pass

def _generate_file_id(uri: str, modified_time: datetime) -> str:
    """
    Generate a unique ID for a file based on its uri and modification time
    """
    unique_string = f"{uri}_{modified_time.isoformat()}"
    return hashlib.md5(unique_string.encode()).hexdigest()

class LocalFileSystemSource(AbstractFileSource):
    """
    Leverages the os module for interacting with local filesystem.
    """
    def __init__(self):
        self.logger = logging.getLogger("local-file-system-source")

    def get_file_id(self, uri) -> str:
        return _generate_file_id(uri, self._get_modified_time(uri))

    def list_files(self, uri) -> List[str]:
        filelist: List[str] = []
        directory = Path(uri)

        if not directory.exists() or not directory.is_dir():
            self.logger.error(f"Directory not found or not a directory: {uri}")
            return []

        # Walk through the directory and all subdirectories
        for root, _, files in os.walk(uri):
            for file in files:
                file_path = os.path.join(root, file)
                filelist.append(file_path)
                self.logger.info(f"Found supported document: {file_path}")

        return filelist

    def download_files(self, uri):
        # we dont need to download the files, they are already on the local filesystem
        return self.list_files(uri)

    def get_modified_time(self, uri) -> datetime:
        return self._get_modified_time(uri)

    def _get_modified_time(self, uri) -> datetime:
        file_stats = os.stat(uri)
        return datetime.fromtimestamp(file_stats.st_mtime)
