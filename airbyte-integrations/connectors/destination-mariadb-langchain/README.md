# Readme

## Installieren:

- Venv mit Python 3.11 anlegen
- poetry install --with dev
- airbyte-ci connectors --name=destination-mariadb-langchain build
- kind load docker-image airbyte/destination-mariadb-langchain:dev -n airbyte-abctl

- Pathmapping:
  - <your path>/airbyte/airbyte-integrations/connectors/destination-mariadb-langchain/.venv/lib/python3.11 -> /usr/local/lib/python3.11


## Pre-commit ausführen
Das sollte das "pre-commit" Tool ausführen, und dadurch 
`pre-commit run -o HEAD -s origin/master`


## ins Repo Pushen

Taggen:
`docker tag airbyte/destination-mariadb-langchain:dev  registry.data.mayflower.zone/airbyte/destination-mariadb-langchain:dev`

Pushen:
`docker push registry.data.mayflower.zone/airbyte/destination-mariadb-langchain:dev`
