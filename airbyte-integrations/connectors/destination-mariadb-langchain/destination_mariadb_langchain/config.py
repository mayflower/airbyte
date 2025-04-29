#
# Copyright (c) 2024 Airbyte, Inc., all rights reserved.
#


from pydantic.v1 import BaseModel, Field

from airbyte_cdk.destinations.vector_db_based.config import VectorDBConfigModel


class PasswordBasedAuthorizationModel(BaseModel):
    password: str = Field(
        ...,
        title="Password",
        airbyte_secret=True,
        description="Enter the password you want to use to access the database",
        examples=["AIRBYTE_PASSWORD"],
        order=7,
    )

    class Config:
        title = "Credentials"


class MariaDBIndexingModel(BaseModel):
    host: str = Field(
        ...,
        title="Host",
        order=1,
        description="Enter the account name you want to use to access the database.",
        examples=["AIRBYTE_ACCOUNT"],
    )
    port: int = Field(
        default=3306,
        title="Port",
        order=2,
        description="Enter the port you want to use to access the database",
        examples=["3306"],
    )
    database: str = Field(
        ...,
        title="Database",
        order=4,
        description="Enter the name of the database that you want to sync data into",
        examples=["AIRBYTE_DATABASE"],
    )
    username: str = Field(
        ...,
        title="Username",
        order=6,
        description="Enter the name of the user you want to use to access the database",
        examples=["AIRBYTE_USER"],
    )

    # E.g. "credentials": {"password": "AIRBYTE_PASSWORD"}
    credentials: PasswordBasedAuthorizationModel

    class Config:
        title = "MariaDB Connection"
        schema_extra = {
            "description": "MariaDB can be used to store vector data and retrieve embeddings.",
            "group": "indexing",
        }

class LangchainDbConfig(BaseModel):

    collection_table_name: str = Field(
        default="langchain_collection",
        title="Collection Table Name",
        description="Name of the table storing collections",
    )

    collection_id_col_name: str = Field(
        default="id",
        title="Collection ID Column Name",
        description="Name of the primary key column",
    )
    collection_label_col_name: str = Field(
        default="label",
        title="Collection Label Column Name",
        description="Name of the column storing collection labels (names)",
    )
    collection_meta_col_name: str = Field(
        default="metadata",
        title="Collection Metadata Column Name",
        description="Name of the column storing collection metadata",
    )

    embedding_table_name: str = Field(
        default="langchain_embedding",
        title="Table Name",
        description="Name of the table storing embeddings",
    )
    embedding_id_col_name: str = Field(
        default="id",
        title="ID Column Name",
        description="Name of the primary key column",
    )
    embedding_content_col_name: str = Field(
        default="content",
        title="Content Column Name",
        description="Name of the column storing content (text)",
    )
    embedding_meta_col_name: str = Field(
        default="metadata",
        title="Embedding Metadata Column Name",
        description="Name of the column storing metadata (JSON)",
    )
    embedding_emb_col_name: str = Field(
        default="embedding",
        title="Embedding Vector Column Name",
        description="Name of the column storing the embedding vectors",
    )
    embedding_coll_id_col_name: str = Field(
        default="collection_id",
        title="Collection ID Reference Column Name",
        description="Name of the column storing the FK to the collections",
    )

    class Config:
        # does this even do anything?
        title = "Langchain DB Config"


class ConfigModel(VectorDBConfigModel):
    indexing: MariaDBIndexingModel
    langchain: LangchainDbConfig
