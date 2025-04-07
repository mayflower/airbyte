#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import datetime
import hashlib
import json
import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from docling.chunking import HybridChunker
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType

from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import CheckpointMixin, Stream
from airbyte_cdk.sources.streams.core import StreamData


# Supported MIME types for DoclingLoader
SUPPORTED_MIMETYPES = [
    # PDF
    "application/pdf",  # .pdf
    # Office formats (Office Open XML)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    # Markdown
    "text/markdown",  # .md
    # Rich Text Format
    "application/rtf",  # .rtf
    "text/rtf",  # alternative MIME for .rtf
    # HTML/XHTML
    "text/html",  # .html
    "application/xhtml+xml",  # .xhtml
    # CSV
    "text/csv",  # .csv
    "application/csv",  # alternative for .csv
    "application/x-csv",  # alternative for .csv
    # Image formats
    "image/png",  # .png
    "image/jpeg",  # .jpg, .jpeg
    "image/tiff",  # .tiff, .tif
    "image/bmp",  # .bmp
    "image/x-windows-bmp",  # alternative for .bmp
]

# Supported file extensions for DoclingLoader (fallback)
SUPPORTED_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",  # Office Open XML formats
    ".md",
    ".markdown",  # Markdown
    ".rtf",  # Rich Text Format
    ".adoc",
    ".asciidoc",  # AsciiDoc
    ".html",
    ".htm",
    ".xhtml",  # HTML/XHTML
    ".csv",  # CSV
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",  # Image formats
]

# Initialize mimetypes
mimetypes.init()

# Supported export types
EXPORT_TYPES = ["DOC_CHUNKS", "MARKDOWN"]
DEFAULT_EXPORT_TYPE = "DOC_CHUNKS"

EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

logger = logging.getLogger("airbyte")


class DoclingStream(CheckpointMixin, Stream):
    """
    Unified stream class for DoclingLoader source
    Handles both full refresh and incremental sync modes
    """

    primary_key = "id"
    cursor_field = "file_modified_at"

    # Define logger as a class attribute
    logger = logger

    def __init__(self, paths: List[str], export_type: str = DEFAULT_EXPORT_TYPE, chunker_tokenizer: str = None):
        self.paths = paths
        self._state = {}  # Initialize internal state storage for incremental sync

        # Parse export type option
        if export_type == "MARKDOWN":
            self.export_type = ExportType.MARKDOWN
        else:
            self.export_type = ExportType.DOC_CHUNKS

        # Configure default chunker if not provided
        if chunker_tokenizer is None:
            chunker_tokenizer = EMBED_MODEL_ID

        self.logger.info(f"Using chunker tokenizer: {chunker_tokenizer}")
        self.chunker = HybridChunker(tokenizer=chunker_tokenizer, max_tokens=100)

    @property
    def name(self) -> str:
        return "docling_documents"

    @property
    def state(self) -> Mapping[str, Any]:
        """
        Return the current state of the stream
        Required by CheckpointMixin
        """
        return self._state

    @state.setter
    def state(self, value: Mapping[str, Any]):
        """
        Set the state of the stream
        Required by CheckpointMixin
        """
        self._state = value or {}

    def get_json_schema(self) -> Mapping[str, Any]:
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas", f"{self.name}.json")
        with open(schema_path, "r") as f:
            return dict(json.loads(f.read()))

    def _get_file_id(self, file_path: str) -> str:
        """
        Generate a unique ID for a file based on its path and modification time
        """
        file_stats = os.stat(file_path)
        unique_string = f"{file_path}_{file_stats.st_mtime}"
        return hashlib.md5(unique_string.encode()).hexdigest()

    def _is_supported_file(self, file_path: str) -> bool:
        """
        Check if the file has a supported MIME type or extension
        """
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            # If we can't determine the MIME type, check fallback based on extension
            ext = os.path.splitext(file_path.lower())[1]
            if ext in SUPPORTED_EXTENSIONS:
                self.logger.warning(f"Could not determine MIME type for {file_path}, using extension-based fallback")
                return True
            return False

        # Check if it's a supported MIME type
        if mime_type in SUPPORTED_MIMETYPES:
            return True

        return False

    def _scan_directory(self, directory_path: str) -> List[str]:
        """
        Recursively scan a directory for supported document files
        """
        supported_files = []
        directory = Path(directory_path)

        if not directory.exists() or not directory.is_dir():
            self.logger.error(f"Directory not found or not a directory: {directory_path}")
            return []

        # Walk through the directory and all subdirectories
        for root, _, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                # Check if the file has a supported MIME type
                if self._is_supported_file(file_path):
                    supported_files.append(file_path)
                    self.logger.info(f"Found supported document: {file_path}")

        self.logger.info(f"Found {len(supported_files)} supported documents in directory {directory_path}")
        return supported_files

    def _get_all_files_to_process(self) -> List[Dict[str, str]]:
        """
        Process all paths and collect files to process.
        Returns a list of dictionaries with file path and base directory path.
        """
        files_to_process = []

        for path in self.paths:
            path = os.path.expanduser(path)  # Expand user's home directory if present

            if not os.path.exists(path):
                self.logger.warning(f"Path does not exist: {path}")
                continue

            if os.path.isfile(path):
                # For individual files, check if they're supported
                if self._is_supported_file(path):
                    # For individual files, the base directory is the containing directory
                    files_to_process.append({"file_path": path, "base_dir": os.path.dirname(path)})
                    self.logger.info(f"Added individual file: {path}")
                else:
                    self.logger.warning(f"Skipping unsupported file: {path}")

            elif os.path.isdir(path):
                # For directories, scan recursively for supported files
                found_files = self._scan_directory(path)
                # For directory scans, the base directory is the directory itself
                for file_path in found_files:
                    files_to_process.append({"file_path": file_path, "base_dir": path})
            else:
                self.logger.warning(f"Skipping path of unknown type: {path}")

        return files_to_process

    def _get_file_modified_time(self, file_path: str) -> datetime:
        """
        Get the last modified time of a file
        """
        file_stats = os.stat(file_path)
        return datetime.fromtimestamp(file_stats.st_mtime)

    def _get_document_records(self, file_info: Dict[str, str], cursor_field: str = None, cursor_value: str = None) -> List[Dict[str, Any]]:
        """
        Process a single file and return its document records
        """
        records = []
        file_path = file_info["file_path"]
        base_dir = file_info["base_dir"]

        try:
            file_id = self._get_file_id(file_path)
            file_modified_time = self._get_file_modified_time(file_path)

            # For incremental, skip files not modified since last sync
            if cursor_field and cursor_value:
                if cursor_field == "file_modified_at" and file_modified_time <= datetime.fromisoformat(cursor_value):
                    self.logger.info(f"Skipping file not modified since last sync: {file_path}")
                    return records

            # Load document using DoclingLoader
            self.logger.info(f"Loading document: {file_path}")
            loader = DoclingLoader(file_path=file_path, export_type=self.export_type, chunker=self.chunker)

            chunks = loader.lazy_load()

            for chunk_id, chunk in enumerate(chunks):
                # Create a unique ID for each document chunk
                chunk_id = f"{file_id}_{chunk_id}"

                # Add file path information to metadata
                metadata = chunk.metadata.copy() if chunk.metadata else {}
                metadata["source_file"] = file_path
                metadata["relative_path"] = os.path.relpath(file_path, base_dir)

                # Current timestamp
                now = datetime.now()

                # Convert document to a record format
                record = {
                    "id": chunk_id,
                    "content": chunk.page_content,
                    "metadata": metadata,
                    "extracted_at": now.isoformat(),
                    "file_modified_at": file_modified_time.isoformat(),
                }
                records.append(record)

        except Exception as e:
            self.logger.error(f"Error loading document {file_path}: {str(e)}")

        return records

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Update the state with the latest record's modified time
        Used for incremental sync
        """
        if not current_stream_state:
            current_stream_state = {self.cursor_field: None}

        current_cursor_value = current_stream_state.get(self.cursor_field)
        latest_cursor_value = latest_record.get(self.cursor_field)

        if latest_cursor_value and (not current_cursor_value or latest_cursor_value > current_cursor_value):
            current_stream_state[self.cursor_field] = latest_cursor_value
            # Update our internal state as well
            self.state = current_stream_state.copy()

        return current_stream_state

    def stream_slices(self, stream_state: Mapping[str, Any] = None, **kwargs) -> Iterable[Optional[Mapping[str, Any]]]:
        """
        Return stream slices
        For both sync modes, we return a single slice with state info
        """
        # Initialize state from stream_state for incremental sync if provided
        if stream_state is not None:
            self.state = stream_state

        # Return a slice containing the current state
        return [{"state": self.state}]

    def _process_files_full_refresh(self, files_to_process: List[Dict[str, str]]) -> Iterable[StreamData]:
        """
        Process files in full refresh mode
        """
        self.logger.info(f"Processing {len(files_to_process)} files with export type: {self.export_type} (Full Refresh)")

        record_counter = 0
        for file_info in files_to_process:
            records = self._get_document_records(file_info)
            record_counter += len(records)
            for record in records:
                yield record

        self.logger.info(f"Extracted {record_counter} records from {len(files_to_process)} files")

    def _process_files_incremental(self, files_to_process: List[Dict[str, str]]) -> Iterable[StreamData]:
        """
        Process files in incremental mode, only yielding records from files modified since last sync
        """
        cursor_value = self.state.get(self.cursor_field)

        self.logger.info(f"Processing {len(files_to_process)} files with export type: {self.export_type} (Incremental)")
        if cursor_value:
            self.logger.info(f"Only processing files modified since: {cursor_value}")

        record_counter = 0
        processed_counter = 0
        checkpoint_interval = 100  # Emit checkpoint every 100 records

        for file_info in files_to_process:
            records = self._get_document_records(file_info, self.cursor_field, cursor_value)
            if records:
                processed_counter += 1

            for record in records:
                record_counter += 1
                yield record

                # Check if we should emit a checkpoint state
                if record_counter % checkpoint_interval == 0:
                    self.logger.info(f"Emitting checkpoint state after {record_counter} records")
                    yield self.state

        self.logger.info(f"Extracted {record_counter} records from {processed_counter} files (out of {len(files_to_process)} total files)")

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[StreamData]:
        """
        Read records based on the sync mode
        """
        # Initialize state from input stream_state for incremental mode
        self.state = stream_state or {}

        # Get all files to process
        files_to_process = self._get_all_files_to_process()

        if not files_to_process:
            self.logger.warning("No valid files found to process")
            return

        # Delegate to appropriate method based on sync mode
        if sync_mode == SyncMode.full_refresh:
            yield from self._process_files_full_refresh(files_to_process)
        else:
            yield from self._process_files_incremental(files_to_process)


class SourceLangchainDoclingLoader(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        """
        Check if the provided paths are valid and at least one exists.
        Also validate that the export_type is supported.
        """
        try:
            # Check export_type parameter if provided
            export_type = config.get("export_type", DEFAULT_EXPORT_TYPE)
            if export_type not in EXPORT_TYPES:
                return False, f"Unsupported export_type: {export_type}. Must be one of {', '.join(EXPORT_TYPES)}"

            paths = config.get("paths", [])

            # Check if paths is provided and is a list
            if not isinstance(paths, list) or not paths:
                return False, "Paths must be a non-empty list of strings"

            # Check if at least one path exists
            valid_paths = 0

            for path in paths:
                path = os.path.expanduser(path)  # Expand user's home directory if present

                if os.path.exists(path):
                    valid_paths += 1

                    if os.path.isdir(path):
                        # For directories, check if we can read contents
                        try:
                            next(os.scandir(path))
                        except StopIteration:
                            # Empty directory is acceptable
                            pass
                        except PermissionError:
                            logger.warning(f"Permission denied to read directory: {path}")
                            continue

                    elif os.path.isfile(path):
                        # For files, check if it's a supported format based on MIME type
                        if self._is_supported_file_mime(path):
                            # Check if we can read the file
                            try:
                                with open(path, "rb") as f:
                                    f.read(1)
                            except PermissionError:
                                logger.warning(f"Permission denied to read file: {path}")
                                continue
                        else:
                            logger.warning(f"Unsupported file format: {path}")
                            continue

            if valid_paths == 0:
                return False, "No valid paths found. Please provide at least one valid file or directory path."

            return True, None
        except Exception as e:
            return False, f"Error checking connection: {str(e)}"

    def _is_supported_file_mime(self, file_path: str) -> bool:
        """
        Check if the file has a supported MIME type or extension
        """
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            # If we can't determine the MIME type, check fallback based on extension
            ext = os.path.splitext(file_path.lower())[1]
            if ext in SUPPORTED_EXTENSIONS:
                return True
            return False

        # Check if it's a supported MIME type
        if mime_type in SUPPORTED_MIMETYPES:
            return True

        return False

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """
        Return all stream implementations.
        Airbyte will use the appropriate one based on the UI-selected sync mode.
        """
        export_type = config.get("export_type", DEFAULT_EXPORT_TYPE)
        paths = config.get("paths", [])
        chunker_tokenizer = config.get("chunker_tokenizer")

        # Return the unified stream that handles both sync modes
        return [DoclingStream(paths=paths, export_type=export_type, chunker_tokenizer=chunker_tokenizer)]
