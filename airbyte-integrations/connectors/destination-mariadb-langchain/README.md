# Readme

## Setup for local development:

- Create a VENV with Python 3.11 
- `poetry install --with dev`

## Testing in a local kind airbyte:
- `airbyte-ci connectors --name=destination-mariadb-langchain build`
- `kind load docker-image airbyte/destination-mariadb-langchain:dev -n airbyte-abctl`

## Debugging (IntelliJ):

- Create a new Python Debug Server configuration. Put in some local IP which should be reachable from within docker, and some number as a port, like 55507 
- Put the lines which the IDE gives you into `write`, `check`, or just at the top of destination.py.
### Path Mapping
Seems to require absolute local paths:
- <your path>/airbyte/airbyte-integrations/connectors/destination-mariadb-langchain/.venv/lib -> /usr/local/lib
- <your path>/airbyte/airbyte-integrations/connectors/destination-mariadb-langchain -> /airbyte/integration_code


## Push to Repo

Tag with the target repository:
`docker tag airbyte/destination-mariadb-langchain:dev registry.data.mayflower.zone/airbyte/destination-mariadb-langchain:dev`

Push to the target repository:
`docker push registry.data.mayflower.zone/airbyte/destination-mariadb-langchain:dev`
