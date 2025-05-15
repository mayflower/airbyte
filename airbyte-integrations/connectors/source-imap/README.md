# IMAP Source Connector for Airbyte

This is a source connector for Airbyte that allows you to sync email messages from an IMAP server.

## Features

- Connect to any IMAP-compliant mail server.
- Specify a mail folder to sync (e.g., INBOX, Archive, custom folders).
- Supports Full Refresh and Incremental sync modes.
  - **Full Refresh**: Fetches all messages in the specified folder, optionally filtered by a start date.
  - **Incremental**:
    - Fetches only unread/unseen messages (default).
    - OR, fetches messages newer than the last synced message based on their `INTERNALDATE` (server arrival time).
- Secure connection using SSL/TLS by default.
- Extracts common email fields: UID, Message-ID, Subject, From, To, CC, Sent Date, Received Date (INTERNALDATE), Text Body, HTML Body, Attachments (metadata only), and Flags.

## Prerequisites

- Python 3.9+
- An IMAP-accessible email account.

## Setup Guide

### 1. Install the connector (Development)

If you are developing the connector or want to run it locally outside of Airbyte:

```bash
git clone <repository_url> # Or your local path
cd source-imap
poetry install
```

### 2. Configuration

Create a `secrets/config.json` file with your IMAP server details:

```json
{
  "host": "imap.example.com",
  "port": 993,
  "username": "your_email@example.com",
  "password": "your_password",
  "folder": "INBOX",
  "use_ssl": true,
  "start_date": "2023-01-01T00:00:00Z", // Optional: For initial full refresh
  "import_unread_only_for_incremental": true // Optional: Default is true
}
```

**Configuration Parameters:**

*   `host` (required): Hostname or IP address of the IMAP server.
*   `port` (optional, default: 993 if `use_ssl` is true, 143 otherwise): Port number of the IMAP server.
*   `username` (required): Username for the IMAP account.
*   `password` (required): Password for the IMAP account.
*   `folder` (optional, default: "INBOX"): Specific mail folder to sync. Use IMAP folder naming conventions (e.g., 'INBOX/Archive').
*   `use_ssl` (optional, default: true): Connect using SSL/TLS encryption.
*   `start_date` (optional, nullable): For the initial sync (Full Refresh or first Incremental), import messages on or after this date. Format: `YYYY-MM-DDTHH:mm:ssZ`. If empty, all messages in the folder are considered (respecting server limits). Example: `"2023-01-01T00:00:00Z"`.
*   `import_unread_only_for_incremental` (optional, default: true): For incremental syncs: If true, only import messages currently marked as unread/unseen. If false, import messages newer than the last synced message based on their internal date or UID (more robust).

## Development

### Build
```bash
poetry build
```

### Run tests (TODO: Add tests)
```bash
poetry run pytest tests/
```

### Run linters
```bash
# Add linter commands here, e.g.
# poetry run flake8 source_imap
# poetry run mypy source_imap
```

### Locally test the connector with Airbyte commands:

1.  **Spec**:
    ```bash
    poetry run source-imap spec
    ```
2.  **Check Connection**:
    ```bash
    poetry run source-imap check --config secrets/config.json
    ```
3.  **Discover Schema**:
    ```bash
    poetry run source-imap discover --config secrets/config.json > sample_files/catalog.json
    ```
    (You might need to create `sample_files/` directory and a `secrets/` directory for `config.json`)

4.  **Configure Catalog for Read**:
    Create `sample_files/configured_catalog.json` from `catalog.json`.
    Example: Mark the stream for incremental sync.
    ```json
    {
      "streams": [
        {
          "stream": {
            "name": "source-imap_emails",
            "json_schema": { "...": "..." },
            "supported_sync_modes": ["full_refresh", "incremental"],
            "source_defined_cursor": true,
            "default_cursor_field": ["internal_date"],
            "source_defined_primary_key": [["message_id"]]
          },
          "sync_mode": "incremental",
          "cursor_field": ["internal_date"],
          "destination_sync_mode": "append"
        }
      ]
    }
    ```

5.  **Read Data**:
    ```bash
    poetry run source-imap read --config secrets/config.json --catalog sample_files/configured_catalog.json
    ```
    To test incremental sync with state:
    ```bash
    poetry run source-imap read --config secrets/config.json --catalog sample_files/configured_catalog.json --state sample_files/state.json
    ```
    (Create `sample_files/state.json` with content like `{"source-imap_emails": {"internal_date": "2024-07-25T10:00:00Z"}}` to simulate a previous run)


## Further Improvements / TODO

*   Add comprehensive unit and integration tests.
*   Implement more robust error handling and retries for network issues.
*   Support OAuth2 authentication for providers like Gmail and Outlook.
*   Option to download attachments and include their content (e.g., base64 encoded).
*   More sophisticated handling of IMAP server capabilities (e.g., `UIDPLUS`, `SORT`).
*   Allow configuration for SSL/TLS verification options (e.g., skip verify for self-signed certs, though not recommended for production).
*   Better handling of timezones for `start_date` and `internal_date`. (Pendulum helps, but cross-server behavior can vary).
*   Consider options for fetching specific message parts beyond full body (e.g., only headers, specific MIME parts).
*   Add options to filter by flags other than UNSEEN for incremental.