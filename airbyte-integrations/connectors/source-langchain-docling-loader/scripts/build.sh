#!/bin/bash

set -euo pipefail

docker build -f Dockerfile -t airbyte/source-langchain-docling-loader:dev --platform=linux/amd64,linux/arm64 .
docker tag airbyte/source-langchain-docling-loader:dev registry.data.mayflower.zone/airbyte/source-langchain-docling-loader:dev
docker push registry.data.mayflower.zone/airbyte/source-langchain-docling-loader:dev
kind load docker-image airbyte/source-langchain-docling-loader:dev -n airbyte-abctl
