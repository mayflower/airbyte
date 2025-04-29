import logging
import typing
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, Mock, patch

import pydantic
from destination_mariadb_langchain.common.catalog.catalog_providers import CatalogProvider
from destination_mariadb_langchain.config import ConfigModel
from destination_mariadb_langchain.mariadb_processor import DatabaseConfig, MariaDBProcessor
from sqlalchemy.dialects.mysql.pymysql import MySQLDialect_pymysql

from airbyte._batch_handles import BatchHandle
from airbyte.secrets import SecretString
from airbyte.strategies import WriteStrategy
from airbyte_cdk.destinations.vector_db_based import FakeEmbeddingConfigModel, ProcessingConfigModel
from airbyte_cdk.models import (
    AirbyteMessage,
    AirbyteRecordMessage,
    AirbyteStateMessage,
    AirbyteStateType,
    AirbyteStreamState,
    ConnectorSpecification,
    Status,
    Type,
)

# from airbyte_cdk.sql.shared.catalog_providers import CatalogProvider
from airbyte_protocol.models import AirbyteStream, ConfiguredAirbyteCatalog, ConfiguredAirbyteStream, DestinationSyncMode, SyncMode


SQL_CREATE_STATEMENT = """
        CREATE TABLE `users_123` (
            `document_id` VARCHAR(255),
            `chunk_id` VARCHAR(255),
            `metadata` JSON,
            `document_content` TEXT,
            `embedding` VECTOR(1536)
        )
        """

SQL_DESTORY_STATEMENT = "DROP TABLE IF EXISTS `users_123`"


class TestDestinationMariaDB(unittest.TestCase):
    def setUp(self):
        self.config = {
            "processing": {"text_fields": ["str_col"], "metadata_fields": [], "chunk_size": 1000},
            "embedding": {"mode": "openai", "openai_key": "mykey"},
            "indexing": {
                "host": "MYACCOUNT",
                "port": 5432,
                "database": "MYDATABASE",
                "default_schema": "MYSCHEMA",
                "username": "MYUSERNAME",
                "credentials": {"password": "xxxxxxx"},
            },
        }
        self.config_model = ConfigModel.parse_obj(self.config)
        self.logger = logging.getLogger("airbyte")

        self.test_splitter = ProcessingConfigModel(chunk_size=666)

        self.fake_embedder = FakeEmbeddingConfigModel(mode="fake")

        # mocks testProcessor.get_sql_connection()
        self.get_sql_conn_mock = MagicMock()

        # mocks "with testProcessor.get_sql_connection() as conn:"
        self.sql_conn_mock_enter = MagicMock()

        # This is how you mock away a "with get_sql_conn_mock() as sql_conn_mock_enter:" call
        self.get_sql_conn_mock.return_value.__enter__.return_value = self.sql_conn_mock_enter

        # we need a "dialect", must be instance of MySQLDialect_pymysql
        dialect = MySQLDialect_pymysql(is_mariadb=True)
        self.sql_conn_mock_enter.dialect = dialect

        # ok, we actually need a catalog provider
        self.configured_catalog = ConfiguredAirbyteCatalog(
            streams=[
                ConfiguredAirbyteStream(
                    cursor_field=["updated_at"],
                    destination_sync_mode=DestinationSyncMode.overwrite,
                    generation_id=None,
                    minimum_generation_id=None,
                    primary_key=[["id"]],
                    sync_id=None,
                    sync_mode=SyncMode.full_refresh,
                    stream=AirbyteStream(
                        default_cursor_field=["updated_at"],
                        is_resumable=True,
                        name="users",
                        namespace=None,
                        source_defined_cursor=True,
                        source_defined_primary_key=[["id"]],
                        supported_sync_modes=[SyncMode.full_refresh, SyncMode.incremental],
                        json_schema={
                            "$schema": "http://json-schema.org/schema#",
                            "additionalProperties": True,
                            "properties": {
                                "academic_degree": {"type": "string"},
                                "address": {
                                    "properties": {
                                        "city": {"type": "string"},
                                        "country_code": {"type": "string"},
                                        "postal_code": {"type": "string"},
                                        "province": {"type": "string"},
                                        "state": {"type": "string"},
                                        "street_name": {"type": "string"},
                                        "street_number": {"type": "string"},
                                    },
                                    "type": "object",
                                },
                                "age": {"type": "integer"},
                                "blood_type": {"type": "string"},
                                "created_at": {"airbyte_type": "timestamp_with_timezone", "format": "date-time", "type": "string"},
                                "email": {"type": "string"},
                                "gender": {"type": "string"},
                                "height": {"type": "string"},
                                "id": {"type": "integer"},
                                "language": {"type": "string"},
                                "name": {"type": "string"},
                                "nationality": {"type": "string"},
                                "occupation": {"type": "string"},
                                "telephone": {"type": "string"},
                                "title": {"type": "string"},
                                "updated_at": {"airbyte_type": "timestamp_with_timezone", "format": "date-time", "type": "string"},
                                "weight": {"type": "integer"},
                            },
                            "type": "object",
                        },
                    ),
                )
            ]
        )

        test_message = AirbyteMessage(
            catalog=None,
            connectionStatus=None,
            control=None,
            log=None,
            spec=None,
            state=None,
            trace=None,
            type=Type.RECORD,
            record=AirbyteRecordMessage(
                data={
                    "academic_degree": "Master",
                    "address": {
                        "city": "Austin",
                        "country_code": "UG",
                        "postal_code": "49893",
                        "province": "North Carolina",
                        "state": "Kentucky",
                        "street_name": "Princeton",
                        "street_number": "789",
                    },
                    "age": 53,
                    "blood_type": "B−",
                    "created_at": "2012-07-02T08:32:31+00:00",
                    "email": "reason1932+1@protonmail.com",
                    "gender": "Male",
                    "height": "1.55",
                    "id": 1,
                    "language": "Tamil",
                    "name": "Patria",
                    "nationality": "Italian",
                    "occupation": "Word Processing Operator",
                    "telephone": "+1-(110)-795-7610",
                    "title": "M.A.",
                    "updated_at": "2025-03-27T14:37:27+00:00",
                    "weight": 58,
                },
                emitted_at=1743086247202,
                meta=None,
                namespace=None,
                stream="users",
            ),
        )

        self.input_messages = [test_message]

        self.sql_config = DatabaseConfig(
            host=self.config_model.indexing.host,
            port=self.config_model.indexing.port,
            database=self.config_model.indexing.database,
            username=self.config_model.indexing.username,
            password=SecretString(self.config_model.indexing.credentials.password),
        )

        self.testProcessor = MariaDBProcessor(
            self.sql_config,
            splitter_config=self.test_splitter,
            embedder_config=self.fake_embedder,
            catalog_provider=CatalogProvider(self.configured_catalog),
        )

    @staticmethod
    def _multiline_trim(text):
        lines = text.split("\n")

        result_lines = []

        for line in lines:
            result_lines.append(line.strip())

        return "\n".join(result_lines).strip()

    def assertMultilineTrimmed(self, expected, actual, msg=None):
        self.assertMultiLineEqual(self._multiline_trim(expected), self._multiline_trim(actual), msg)
        pass


   # todo
