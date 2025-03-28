#!/bin/bash

set -euo pipefail

docker build -f Dockerfile -t registry.data.mayflower.zone/airbyte-base-image:dev --platform=linux/amd64,linux/arm64 .
docker push registry.data.mayflower.zone/airbyte-base-image:dev
airbyte-ci connectors --name=source-langchain-docling-loader build -a linux/arm64
kind load docker-image airbyte/source-langchain-docling-loader:dev -n airbyte-abctl
