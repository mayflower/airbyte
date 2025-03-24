#
# Copyright (c) 2025 Airbyte, Inc., all rights reserved.
#
import logging
from abc import ABC
from datetime import datetime
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from airbyte_cdk import IncrementalMixin, AvailabilityStrategy
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream, CheckpointMixin

import os

from airbyte_protocol_dataclasses.models import SyncMode
from langchain_docling import DoclingLoader

class NotAValidFileException(Exception):
    pass

mylogger = logging.getLogger(__name__)

class IncrementalFileLoaderStream(Stream, CheckpointMixin):
    primary_key = ["uri", "modified_timestamp", "chunk"]

    def __init__(
            self,
            uris: List[str],
            **kwargs: Any,
    ):
        """
        Initialize the LangchainDoclingLoaderStream.

        Args:
            uri: uri of target to be doclinged
            recursive: Optional list of URLs to exclude from processing
            **kwargs: Additional keyword arguments passed to the parent Stream class
        """

        super().__init__(**kwargs)
        self._state = None
        self._uris = uris

    def read_records(
            self,
            sync_mode: str,
            cursor_field: Optional[List[str]] = None, # we dont need the cursor_field, we use filetimestamps instead
            stream_slice: Optional[Mapping[str, Any]] = None,
            stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[Mapping[str, Any]]:
        # reset state if we run in full_refresh mode
        if sync_mode == SyncMode.full_refresh:
            mylogger.info(f"========== SYN MODE: {SyncMode.full_refresh}")
            stream_state = None

        # load previous state or initialize
        self._state = stream_state or {}
        last_processed_timestamp = self._state.get("processed_timestamp")
        last_chunk = self._state.get("chunk")

        for uri in self._uris:
            mylogger.info(f"===CURRENT URI: {uri}")

            for root, _, file_names in os.walk(uri):
                for file_name in file_names:
                    file_path = os.path.join(root, file_name)

                    mylogger.info(f"======FOUND FILE: {file_path}")

                    # get files modified timestamp
                    modified_timestamp = os.path.getmtime(file_path)

                    # Only process new/modified files
                    if last_processed_timestamp is None or modified_timestamp > last_processed_timestamp:
                        mylogger.info(f"START PROCESSING: {file_path}")
                        loader = DoclingLoader(file_path=file_path)
                        docs = loader.load()

                        for chunk_number, doc in enumerate(docs[last_chunk:]):
                            yield {
                                "uri": file_path,
                                "modified_timestamp": modified_timestamp,
                                "chunk": chunk_number,
                                "content": doc,
                            }
                            # update chunk in state after yielding
                            self._state["chunk"] = chunk_number
                    # update processed in state after yielding all chunks
                    self._state["processed_timestamp"] = modified_timestamp


    @property
    def state(self) -> MutableMapping[str, Any]:
        return self._state

    @state.setter
    def state(self, value: MutableMapping[str, Any]):
        self._state = value
#
#     def stream_slices(self, stream_state: Mapping[str, Any] = None, **kwargs) -> Iterable[Optional[Mapping[str, any]]]:
#         """
#         TODO: Optionally override this method to define this stream's slices. If slicing is not needed, delete this method.
#
#         Slices control when state is saved. Specifically, state is saved after a slice has been fully read.
#         This is useful if the API offers reads by groups or filters, and can be paired with the state object to make reads efficient. See the "concepts"
#         section of the docs for more information.
#
#         The function is called before reading any records in a stream. It returns an Iterable of dicts, each containing the
#         necessary data to craft a request for a slice. The stream state is usually referenced to determine what slices need to be created.
#         This means that data in a slice is usually closely related to a stream's cursor_field and stream_state.
#
#         An HTTP request is made for each returned slice. The same slice can be accessed in the path, request_params and request_header functions to help
#         craft that specific request.
#
#         For example, if https://example-api.com/v1/employees offers a date query params that returns data for that particular day, one way to implement
#         this would be to consult the stream state object for the last synced date, then return a slice containing each date from the last synced date
#         till now. The request_params function would then grab the date from the stream_slice and make it part of the request by injecting it into
#         the date query param.
#         """
#         raise NotImplementedError("Implement stream slices or delete this method!")


class File(IncrementalFileLoaderStream):
    def __init__(
            self,
            uris: List[str],
            **kwargs: Any,
    ):
        """
        Initialize the LangchainDoclingLoaderStream.

        Args:
            uris: List of URIs
            **kwargs: Additional keyword arguments passed to the parent Stream class
        """

        super().__init__(uris, **kwargs)

    def path(self, **kwargs) -> str:
        return "local_file_system"

class SourceLangchainDoclingLoader(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        logger.info("running CHECK")
        """
        :param config:  the user-input config object conforming to the connector's spec.yaml
        :param logger:  logger object
        :return Tuple[bool, any]: (True, None) if the input config can be used to connect to the API successfully, (False, error) otherwise.
        """
        uris = config["uris"]

        logger.info("checking input URIs...")
        for uri in uris:
            if not os.path.isfile(uri) and not os.path.isdir(uri):
                err_msg = f"'{uri}' is not a valid URI."
                logger.error(err_msg)
                return False, err_msg
        logger.info("done")
        return True, None

    @property
    def availability_strategy(self) -> Optional[AvailabilityStrategy]:
        # Availability strategies are a legacy concept used to filter out streams that might not be available given a user's permissions.
        return None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        """
        mylogger.info("running DISCOVER")
        uris = config["uris"]
        return [File(uris=uris)]



