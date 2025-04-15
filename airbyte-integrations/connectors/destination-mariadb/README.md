# Readme

## Installieren:

- Venv mit Python 3.11 anlegen
- poetry install --with dev
- airbyte-ci connectors --name=destination-mariadb build
- kind load docker-image airbyte/destination-mariadb:dev -n airbyte-abctl

- Pathmapping:
  - <your path>/airbyte/airbyte-integrations/connectors/destination-mariadb/.venv/lib/python3.11 -> /usr/local/lib/python3.11


## Pre-commit ausführen
Das sollte das "pre-commit" Tool ausführen, und dadurch 
`pre-commit run -o HEAD -s origin/master`

