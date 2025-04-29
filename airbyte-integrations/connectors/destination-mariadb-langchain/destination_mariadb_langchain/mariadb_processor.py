"""
A MariaDB implementation of the SQL processor.
Mostly based on the default PGVector connector...
"""

from __future__ import annotations

import abc
import json
import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Optional, cast, List

import dpath
import sqlalchemy
import ulid
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.elements import TextClause
from typing_extensions import Protocol

from airbyte import exceptions as exc
from airbyte._util.name_normalizers import LowerCaseNormalizer
from airbyte.constants import DEBUG_MODE
from airbyte.secrets import SecretString
from airbyte.strategies import WriteStrategy
from airbyte.types import SQLTypeConverter
from airbyte_cdk.destinations.vector_db_based import embedder
from airbyte_cdk.destinations.vector_db_based.document_processor import (
    Chunk,
)
from airbyte_cdk.destinations.vector_db_based.document_processor import (
    DocumentProcessor as DocumentSplitter,
)
from airbyte_cdk.destinations.vector_db_based.document_processor import (
    ProcessingConfigModel as DocumentSplitterConfig,
)
from airbyte_cdk.destinations.vector_db_based.embedder import Document
from airbyte_cdk.models import (
    AirbyteRecordMessage,
    Type,
)
from airbyte_cdk.models.airbyte_protocol import DestinationSyncMode
from airbyte_protocol.models import (
    AirbyteMessage,
)
from destination_mariadb_langchain.common.catalog.catalog_providers import CatalogProvider
from destination_mariadb_langchain.common.sql.mariadb_types import VECTOR
from destination_mariadb_langchain.config import ConfigModel
from destination_mariadb_langchain.globals import (
    CHUNK_ID_COLUMN,
    DOCUMENT_CONTENT_COLUMN,
    DOCUMENT_ID_COLUMN,
    EMBEDDING_COLUMN,
    METADATA_COLUMN,
)
import numpy as np
import re

logger = logging.getLogger("airbyte")


class SQLRuntimeError(Exception):
    """Raised when an SQL operation fails."""


class DatabaseConfig(BaseModel, abc.ABC):
    host: str
    port: int
    database: str
    username: str
    password: SecretString | str
    table_prefix: Optional[str] = ""

    def get_sql_alchemy_url(self) -> SecretString:
        """Return the SQLAlchemy URL to use."""

        # using "mariadb+mariadbconnector" opens a pit to dependency hell, so, not doing that.
        # conn_str = f"mariadb+mariadbconnector://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
        conn_str = f"mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

        return SecretString(conn_str)

    def get_database_name(self) -> str:
        """Return the name of the database."""
        return self.database

    def connect(self) -> None:
        """Attempt to connect, and raise `AirbyteConnectionError` if the connection fails."""
        engine = self.get_sql_engine()
        try:
            connection = engine.connect()
            connection.close()
        except Exception as ex:
            raise exc.AirbyteConnectionError(
                message="Could not connect to the database.",
                guidance="Check the connection settings and try again.",
            ) from ex

    def get_sql_engine(self) -> Engine:
        """Return a new SQL engine to use."""
        return create_engine(
            url=self.get_sql_alchemy_url(),
            echo=DEBUG_MODE,
        )

    def get_vendor_client(self) -> object:
        """Return the vendor-specific client object.

        This is used for vendor-specific operations.

        Raises `NotImplementedError` if a custom vendor client is not defined.
        """
        raise NotImplementedError(f"The type '{type(self).__name__}' does not define a custom client.")


class EmbeddingConfig(Protocol):
    """A protocol for embedding configuration.

    This is necessary because embedding configs do not have a shared base class.

    """

    mode: str


class MariaDBProcessor(abc.ABC):
    """A MariaDB implementation of the SQL Processor."""

    supports_merge_insert = True
    """We use the emulated merge code path because each primary key has multiple rows (chunks)."""

    sql_config: DatabaseConfig
    """The configuration for the MariaDB processor, including the vector length."""

    splitter_config: DocumentSplitterConfig
    """The configuration for the document splitter."""

    sql_engine = None
    """Allow the engine to be overwritten"""

    type_converter_class: type[SQLTypeConverter] = SQLTypeConverter
    """The type converter class to use for converting JSON schema types to SQL types."""

    normalizer = LowerCaseNormalizer
    """The name normalizer to user for table and column name normalization."""

    """The file writer class to use for writing files to the cache."""

    def __init__(
        self,
        sql_config: DatabaseConfig,
        config: ConfigModel,
        catalog_provider: CatalogProvider,
    ) -> None:
        """Initialize the MariaDB processor."""

        self.collection_metadata = None # for now. figure out how to actually use it later
        self._collection_meta_col_name = "metadata"
        self._collection_label_col_name = "label"
        self._collection_id_col_name = "id"
        self._collection_table_name = "langchain_collection"
        self._embedding_table_name = "langchain_embedding"
        self._embedding_id_col_name = "id"
        self._embedding_content_col_name = "content"
        self._embedding_meta_col_name = "metadata"
        self._embedding_emb_col_name = "embedding"
        self._embedding_coll_id_col_name = "collection_id"

        self.temp_tables = {}
        self.temp_streams = {}

        self.splitter_config = config.processing
        self.embedder_config = config.embedding

        self._sql_config: DatabaseConfig = sql_config
        self._catalog_provider: CatalogProvider | None = catalog_provider  # move up

        self.type_converter = self.type_converter_class()


        # cache of collection name (label) to collection ID
        self._collection_id_cache: dict[str, str] = {}

        # cache of currently existing tables
        self._table_list_cache: list[str] | None = None



    def _fully_qualified(
        self,
        table_name: str,
    ) -> str:
        """Return the fully qualified name of the given table."""
        return f"{self._quote_identifier(table_name)}"

    def _quote_identifier(self, identifier: str) -> str:
        """Return the given identifier, quoted."""
        return f"`{identifier}`"

    @property
    def embedder(self) -> embedder.Embedder:
        return embedder.create_from_config(
            embedding_config=self.embedder_config,  # type: ignore [arg-type]  # No common base class
            processing_config=self.splitter_config,
        )

    @property
    def embedding_dimensions(self) -> int:
        """Return the number of dimensions for the embeddings."""
        return self.embedder.embedding_dimensions

    @property
    def splitter(self) -> DocumentSplitter:
        return DocumentSplitter(
            config=self.splitter_config,
            catalog=self.catalog_provider.configured_catalog,
        )

    def _create_document_id(self, record_msg: AirbyteRecordMessage) -> str:
        """Create document id based on the primary key values. Returns a random uuid if no primary key is found"""
        stream_name = record_msg.stream
        primary_key = self._get_record_primary_key(record_msg=record_msg)
        if primary_key is not None:
            return f"Stream_{stream_name}_Key_{primary_key}"
        return str(uuid.uuid4().int)

    def _get_record_primary_key(self, record_msg: AirbyteRecordMessage) -> str | None:
        """Create primary key for the record by appending the primary keys."""
        stream_name = record_msg.stream
        primary_keys = self._get_primary_keys(stream_name)

        if not primary_keys:
            return None

        primary_key = []
        for key in primary_keys:
            try:
                primary_key.append(str(dpath.get(record_msg.data, key)))
            except KeyError:
                primary_key.append("__not_found__")
        # return a stringified version of all primary keys
        stringified_primary_key = "_".join(primary_key)
        return stringified_primary_key

    def _get_primary_keys(
        self,
        stream_name: str,
    ) -> list[str]:
        pks = self.catalog_provider.get_configured_stream_info(stream_name).primary_key
        if not pks:
            return []

        joined_pks = [".".join(pk) for pk in pks]
        for pk in joined_pks:
            if "." in pk:
                msg = f"Nested primary keys are not yet supported. Found: {pk}"
                raise NotImplementedError(msg)

        return joined_pks

    def get_writing_strategy(self, stream_name):
        sync_mode = self.catalog_provider.get_configured_stream_info(stream_name).destination_sync_mode

        if sync_mode == DestinationSyncMode.overwrite:
            return WriteStrategy.REPLACE
        elif sync_mode == DestinationSyncMode.append:
            return WriteStrategy.APPEND
        elif sync_mode == DestinationSyncMode.append_dedup:
            return WriteStrategy.MERGE

        return WriteStrategy.APPEND

    def insert_airbyte_message(self, stream_name: str, input_message: AirbyteRecordMessage, merge: bool):

        document_id = self._create_document_id(input_message)
        document_chunks, _ = self.splitter.process(input_message)

        embeddings = self.embedder.embed_documents(
            documents=self.chunks_to_documents(document_chunks),
        )


        query = f"""INSERT INTO {self._embedding_table_name} (
                {self._embedding_id_col_name}, 
                {self._embedding_content_col_name}, 
                {self._embedding_meta_col_name}, 
                {self._embedding_emb_col_name}, 
                {self._embedding_coll_id_col_name}
                ) VALUES ( :doc_id, :content, :meta , Vec_FromText( :embedding ), :collection_id ) 
                """


        if merge:
            query += f"""ON DUPLICATE KEY UPDATE 
                {self._embedding_content_col_name} = 
                VALUES({self._embedding_content_col_name}), 
                {self._embedding_meta_col_name} = 
                VALUES({self._embedding_meta_col_name}), 
                {self._embedding_emb_col_name} = 
                VALUES({self._embedding_emb_col_name})"""
        else:
            query += """ON DUPLICATE KEY IGNORE"""

        collection_id = self._get_collection_id(stream_name)
        data = []
        for i, chunk in enumerate(document_chunks, start=0):

            # ok so here we need to insert it into the DB the langchain way

            # maybe generate the ID using the chunk index, too?
            # or add an extra column which then gets the unique key constraint?
            chunk_id = f"{document_id}_{i}"



            # doc_id, content, meta, embedding, collection_id


            # this doesn't seem to work with conn.execute, so, trying this differently
            # binary_emb = self._embedding_to_binary(embeddings[i])
            # try doing it the Vec_FromText() style
            string_emb = embeddings[i]
            data.append({
                    "doc_id": chunk_id,
                    "content": chunk.page_content,
                    "meta": json.dumps(chunk.metadata),
                    "embedding": json.dumps(string_emb),
                    "collection_id": collection_id,
               })


        with self.get_sql_connection() as conn:
            conn.execute(text(query), data)


    def _ensure_tables_exist(self):
        if not self._table_exists(self._collection_table_name):
            self._create_collection_table()

        if not self._table_exists(self._embedding_table_name):
            self._create_embeddings_table()

    def _create_embeddings_table(self):
        # Create embedding table index name
        index_name = (
            f"idx_{self._embedding_table_name}_{self._embedding_emb_col_name}_idx"
        )
        index_name = re.sub(r"[^0-9a-zA-Z_]", "", index_name)

        # Create embedding table
        table_query = (
            f"""
        CREATE TABLE IF NOT EXISTS {self._embedding_table_name} (
            {self._embedding_id_col_name} VARCHAR(36) NOT NULL DEFAULT UUID_v7() PRIMARY KEY,
            {self._embedding_content_col_name} TEXT,
            {self._embedding_meta_col_name} JSON,
            {self._embedding_emb_col_name} VECTOR({self.embedding_dimensions}) NOT NULL,
            {self._embedding_coll_id_col_name} UUID,
            VECTOR INDEX {index_name} ({self._embedding_emb_col_name}),
            FOREIGN KEY ({self._embedding_coll_id_col_name}) REFERENCES {self._collection_table_name}({self._collection_id_col_name}) ON DELETE CASCADE,
            INDEX coll_id_idx ({self._embedding_coll_id_col_name})
        ) ENGINE=InnoDB
        """
        )
        
        self._execute_sql(text(table_query))


    def _create_collection_table(self):
        # Create collection table index names
        col_uniq_key_name = self._sanitize_identifier(
            f"idx_{self._collection_table_name}_{self._collection_label_col_name}"
        )

        col_table_query = (
            f"""
            CREATE TABLE IF NOT EXISTS {self._collection_table_name}(
            {self._collection_id_col_name} UUID
             NOT NULL DEFAULT UUID_v7() PRIMARY KEY,
            {self._collection_label_col_name} VARCHAR(256),
            {self._collection_meta_col_name} JSON,
            UNIQUE KEY {col_uniq_key_name} ({self._collection_label_col_name}) 
            )
            """
        )

        self._execute_sql(text(col_table_query))


    def _sanitize_identifier(self, stuff):
        return re.sub(r"[^0-9a-zA-Z_]", "", stuff)

    def _get_collection_id(self, collection_name: str):
        # upsert for collections
        if collection_name in self._collection_id_cache:
            return self._collection_id_cache[collection_name]

        # table_name = self._collection_table_name
        
        qry=f"""
        SELECT {self._quote_identifier(self._collection_id_col_name)} 
        FROM {self._quote_identifier(self._collection_table_name)}
        WHERE {self._quote_identifier(self._collection_label_col_name)} = :label
        """
        #conn.execute(text(query), new_data)
        data = {
            "label": collection_name
        }

        result = self._execute_sql(qry, data)

        rows = result.fetchone()
        if rows:
            self._collection_id_cache[collection_name] = rows[0]
            return rows[0]

        # other wise create
        query = (
            f"INSERT INTO {self._collection_table_name}"
            f"({self._collection_label_col_name},"
            f" {self._collection_meta_col_name})"
            f" VALUES (:label,:meta) RETURNING {self._collection_id_col_name}"
        )

        create_data = {
            "label": collection_name,
            "meta": self.collection_metadata,
        }

        result = self._execute_sql(query, create_data)
        data = result.fetchone()
        self._collection_id_cache[collection_name] = data[0]

        return data[0]

    def _embedding_to_binary(self, embedding: List[float]) -> bytes:
        """Convert embedding vector to binary format for storage.

        Args:
            embedding: List of floating point values

        Returns:
            Packed binary representation of the embedding
        """
        return np.array(embedding, np.float32).tobytes()

    def chunks_to_documents(self, chunks: list[Chunk]) -> list[Document]:
        result = []
        for chunk in chunks:
            result.append(
                Document(
                    page_content=chunk.page_content,
                    record=chunk.record,
                )
            )

        return result

    def _get_temp_stream_name(self, stream_name):

        if stream_name in self.temp_streams:
            return self.temp_streams[stream_name]

        uid = str(ulid.ULID())
        temp_stream_name = self.normalizer.normalize(f"{stream_name}_{uid}")

        self.temp_streams[stream_name] = temp_stream_name

        return temp_stream_name


    def _finalize_temp_streams(self):
        for final_stream_name, temp_stream_name in self.temp_streams.items():
            # swap
            self._swap_temp_stream_with_final_stream(temp_stream_name, final_stream_name)
        pass

    def _get_tables_list(
        self,
    ) -> list[str]:
        """Return a list of all tables in the database."""
        with self.get_sql_connection() as conn:
            inspector: Inspector = sqlalchemy.inspect(conn)
            return inspector.get_table_names()  # type: ignore

    def process_airbyte_record_message(
        self,
        message: AirbyteRecordMessage,
        write_strategy: WriteStrategy,
    ):
        stream_name = message.stream

        if write_strategy == WriteStrategy.AUTO:
            write_strategy = self.get_writing_strategy(stream_name)

        if write_strategy == WriteStrategy.REPLACE:
            # - create temp table
            temp_stream_name = self._get_temp_stream_name(stream_name)

            # - do the processing with appending
            self.insert_airbyte_message(temp_stream_name, message, True)
            #  _finalize_writing should then swap the streams back
            return

        if write_strategy == WriteStrategy.MERGE:
            # do the processing with merging
            self.insert_airbyte_message(stream_name, message, True)
            return

        if write_strategy == WriteStrategy.APPEND:
            # do the processing with appending
            self.insert_airbyte_message(stream_name, message, False)
            return

    def _finalize_writing(self):
        self._finalize_temp_streams()

    def process_airbyte_messages_as_generator(
        self,
        input_messages: Iterable[AirbyteMessage],
        write_strategy: WriteStrategy,
    ):
        self._ensure_tables_exist()

        # ok, so:
        # - for APPEND, we're just going to iterate and append
        # - for MERGE, similar, but do a query which deletes and writes new (or think of something smarter).
        #       see also https://stackoverflow.com/questions/71515981/making-merge-in-mariadb-update-when-matched-insert-when-not-matched
        # - for REPLACE, either empty the table first, or write into a temp table first, then switch them?
        #       probably the latter, because we can have different tables within the same iterable
        # - for AUTO, this is what airbyte says, but pgvector uses the stream's destination_sync_mode
        #     This will use the following logic:
        #       - If there's a primary key, use merge.
        #       - Else, if there's an incremental key, use append.
        #       - Else, use full replace (table swap).

        queued_messages = []

        logger.info("Processing message...")
        for message in input_messages:
            # So basically, if it's a record, process it as such. If it's a state, yield it back out

            if message.type is Type.RECORD:
                logger.info("Processing a RECORD")
                self.process_airbyte_record_message(cast(AirbyteRecordMessage, message.record), write_strategy)

            elif message.type is Type.STATE:
                logger.info("Processing a STATE")
                # yield message
                queued_messages.append(message)
            else:
                pass

        self._finalize_writing()

        yield from queued_messages

    @property
    def catalog_provider(
        self,
    ) -> CatalogProvider:
        """Return the catalog manager.

        Subclasses should set this property to a valid catalog manager instance if one
        is not explicitly passed to the constructor.

        Raises:
            PyAirbyteInternalError: If the catalog manager is not set.
        """
        if not self._catalog_provider:
            raise exc.PyAirbyteInternalError(
                message="Catalog manager should exist but does not.",
            )

        return self._catalog_provider

    @property
    def sql_config(self) -> DatabaseConfig:
        return self._sql_config

    def get_sql_engine(self) -> Engine:
        """Return a new SQL engine to use."""
        return self.sql_config.get_sql_engine()

    @contextmanager
    def get_sql_connection(self) -> Generator[sqlalchemy.engine.Connection, None, None]:
        """A context manager which returns a new SQL connection for running queries.

        If the connection needs to close, it will be closed automatically.
        """

        with self.get_sql_engine().begin() as connection:
            yield connection

        connection.close()
        del connection

    def _execute_sql(self, sql: str | TextClause | Executable, *multiparams, **params) -> CursorResult:
        """Execute the given SQL statement."""
        if isinstance(sql, str):
            sql = text(sql)
        if isinstance(sql, TextClause):
            sql = sql.execution_options(
                autocommit=True,
            )

        with self.get_sql_connection() as conn:
            try:
                result = conn.execute(sql, *multiparams, **params)
            except (
                sqlalchemy.exc.ProgrammingError,
                sqlalchemy.exc.SQLAlchemyError,
            ) as ex:
                msg = f"Error when executing SQL:\n{sql}\n{type(ex).__name__}{ex!s}"
                raise SQLRuntimeError(msg) from None  # from ex

        return result

    def _swap_temp_stream_with_final_stream(
            self,
            temp_stream_name,
            final_stream_name
        ):

        temp_id = self._get_collection_id(temp_stream_name)
        final_id = self._get_collection_id(final_stream_name)

        deletion_name = final_stream_name + "_deleteme"
        params = {
            "final_name": final_stream_name,
            "final_id": final_id,
            "deletion_name": deletion_name,
            "temp_id": temp_id,
        }

        commands = [
               text(f"UPDATE {self._collection_table_name} SET label=:deletion_name WHERE id=:final_id;"),
               text(f"UPDATE {self._collection_table_name} SET label=:final_name WHERE id=:temp_id;"),
               text(f"DELETE FROM {self._collection_table_name} WHERE id=:final_id;"),
        ]

        for cmd in commands:
            self._execute_sql(cmd, params)

        # reset the cache
        self._collection_id_cache = {}

        pass


    def _table_exists(
        self,
        table_name: str,
    ) -> bool:
        """Return true if the given table exists.
        """
        if self._table_list_cache is None:
            self._table_list_cache = self._get_tables_list()

        return table_name in self._table_list_cache
