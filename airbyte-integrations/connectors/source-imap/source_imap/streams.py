import base64
import email
import logging

import pendulum
import ssl
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.policy import default as default_email_policy
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union, Generator, Tuple

from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams import IncrementalMixin, Stream
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError
from dateutil import parser as dateutil_parser


class MailStream(Stream, IncrementalMixin):
    primary_key = "message_id"  # Corresponds to RFC822 Message-ID header
    cursor_field = "internal_date"  # IMAP INTERNALDATE
    # Alternatively, UID could be a cursor if strictly monotonically increasing and persistent.
    # However, INTERNALDATE is more standard for "when message arrived at server".

    # IMAPClient default fetch chunk size for multiple messages
    # This is not directly used by IMAPClient's fetch, but good to keep in mind for batching logic if any.
    FETCH_BATCH_SIZE = 100
    # Max number of UIDs to send in a single FETCH command to avoid overly long commands
    UID_FETCH_BATCH_SIZE = 500

    def __init__(self, config: Mapping[str, Any], source_name: str, **kwargs):
        super().__init__(**kwargs)
        self._config = config
        self._logger = logging.getLogger("airbyte")

        self._source_name = source_name  # e.g. "source-imap"
        self._client: Optional[IMAPClient] = None
        self._folder_selected = False
        self._state = {}  # Initialize state

    @property
    def name(self) -> str:
        return f"{self._source_name}_emails"  # e.g. source-imap_emails

    @property
    def state(self) -> Mapping[str, Any]:
        return self._state

    @state.setter
    def state(self, value: Mapping[str, Any]):
        self._state = value

    def _create_client(self) -> IMAPClient:
        ssl_context = None
        if self._config.get("use_ssl", True):
            ssl_context = ssl.create_default_context()
        client = IMAPClient(
            host=self._config["host"],
            port=self._config.get("port", 993 if self._config.get("use_ssl", True) else 143),
            ssl=self._config.get("use_ssl", True),
            ssl_context=ssl_context,
            timeout=120  # Increased timeout for potentially long operations
        )
        return client

    def _connect_and_select_folder(self):
        if self._client and self._client.is_connected() and self._folder_selected:
            return  # Already connected and folder selected

        try:
            self._client = self._create_client()
            self._logger.info(f"Logging in as {self._config['username']}...")
            self._client.login(self._config["username"], self._config["password"])
            self._logger.info("Login successful.")

            folder = self._config.get("folder", "INBOX")
            self._logger.info(f"Selecting folder: {folder}")
            # Select in read-only mode to prevent accidental changes like marking as read by SELECT
            self._client.select_folder(folder, readonly=True)
            self._folder_selected = True
            self._logger.info(f"Folder '{folder}' selected successfully.")
        except LoginError as e:
            self._logger.error(f"Login failed: {e}")
            raise ConnectionError(f"Failed to login to IMAP server: {e}. Check credentials.") from e
        except IMAPClient.Error as e:  # Catch specific IMAP folder errors
            self._logger.error(f"Error selecting folder '{folder}': {e}")
            if self._client and self._client.is_connected():
                self._client.logout()
            self._client = None
            self._folder_selected = False
            raise ConnectionError(f"Failed to select IMAP folder '{folder}': {e}. Ensure it exists.") from e
        except IMAPClientError as e:
            self._logger.error(f"IMAPClient error during connect/select: {e}")
            if self._client and self._client.is_connected():
                self._client.logout()
            self._client = None
            self._folder_selected = False
            raise ConnectionError(f"IMAPClient error: {e}") from e

    def _disconnect(self):
        if self._client and self._client.is_connected():
            try:
                self._logger.info("Logging out and disconnecting from IMAP server.")
                self._client.logout()
            except IMAPClientError as e:
                self._logger.warning(f"Error during IMAP logout: {e}")
            finally:
                self._client = None
                self._folder_selected = False

    def _decode_header_value(self, header_value: Union[str, bytes]) -> str:
        if not header_value:
            return ""
        try:
            decoded_parts = []
            for part, charset in decode_header(header_value):
                if isinstance(part, bytes):
                    decoded_parts.append(part.decode(charset or 'utf-8', errors='replace'))
                else:
                    decoded_parts.append(part)
            return "".join(decoded_parts)
        except Exception as e:
            self._logger.warning(f"Could not decode header part: {header_value}. Error: {e}")
            if isinstance(header_value, bytes):
                return header_value.decode('utf-8', errors='replace')  # Fallback
            return str(header_value)

    def _parse_email_body(self, msg: email.message.Message) -> Tuple[
        Optional[str], Optional[str], List[Dict[str, Any]]]:
        text_body = None
        html_body = None
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                if "attachment" not in content_disposition:
                    if content_type == "text/plain" and text_body is None:  # Prefer first text/plain
                        try:
                            text_body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8',
                                                                             errors='replace')
                        except Exception as e:
                            self._logger.warning(f"Could not decode text part: {e}")
                    elif content_type == "text/html" and html_body is None:  # Prefer first text/html
                        try:
                            html_body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8',
                                                                             errors='replace')
                        except Exception as e:
                            self._logger.warning(f"Could not decode html part: {e}")
                else:  # It's an attachment
                    filename = part.get_filename()
                    if filename:
                        decoded_filename = self._decode_header_value(filename)
                        attachments.append({
                            "filename": decoded_filename,
                            "content_type": content_type,
                            "size": len(part.get_payload(decode=True)),
                            "content": base64.b64encode(part.get_payload(decode=True)).decode()
                            # Optionally include content
                        })
        else:  # Not multipart, try to get body directly
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                body_content = payload.decode(charset, errors='replace')
                if content_type == "text/plain":
                    text_body = body_content
                elif content_type == "text/html":
                    html_body = body_content
                else:  # Fallback for unknown non-multipart type, treat as text
                    text_body = body_content
            except Exception as e:
                self._logger.warning(f"Could not decode single part message body: {e}")

        return text_body, html_body, attachments

    def _process_message_data(self, uid: int, data: Dict[bytes, Any]) -> Optional[Dict[str, Any]]:
        raw_rfc822 = data.get(b"BODY[]")
        envelope = data.get(b"ENVELOPE")
        internal_date_bytes = data.get(b"INTERNALDATE")
        flags = data.get(b"FLAGS", [])

        if not raw_rfc822 or not envelope or not internal_date_bytes:
            self._logger.warning(f"Missing essential data for UID {uid}. Skipping.")
            return None

        try:
            # Parse email using email.parser
            email_message = BytesParser(policy=default_email_policy).parsebytes(raw_rfc822)

            # INTERNALDATE is often a string like "22-Jul-2024 10:30:00 +0000"
            # Need to parse it robustly. IMAPClient might already parse it for some servers.
            # If it's already a datetime object from IMAPClient, use it.
            if isinstance(internal_date_bytes, pendulum.DateTime):
                internal_date_dt = internal_date_bytes
            elif isinstance(internal_date_bytes, str):  # Common case
                internal_date_dt = pendulum.parse(internal_date_bytes.strip())
            else:  # bytes
                internal_date_dt = pendulum.parse(internal_date_bytes.decode().strip())

            internal_date_iso = internal_date_dt.to_iso8601_string()

            # Envelope date might be different, prefer INTERNALDATE for cursor
            # envelope.date can be None
            message_date_iso = None
            if envelope.date:
                message_date_iso = pendulum.instance(envelope.date).to_iso8601_string()

            text_body, html_body, attachments = self._parse_email_body(email_message)

            # Decode headers carefully
            subject = self._decode_header_value(envelope.subject)
            from_ = self._decode_header_value(
                make_header([(addr.mailbox, addr.host) for addr in envelope.from_] if envelope.from_ else []))
            to_ = self._decode_header_value(
                make_header([(addr.mailbox, addr.host) for addr in envelope.to_] if envelope.to_ else []))
            cc_ = self._decode_header_value(
                make_header([(addr.mailbox, addr.host) for addr in envelope.cc_] if envelope.cc_ else []))

            # Message-ID header is crucial for deduplication and unique identification
            message_id_header = email_message.get("Message-ID")
            message_id = self._decode_header_value(message_id_header).strip(
                '<>') if message_id_header else f"no-id-{uid}"

            record = {
                "uid": uid,
                "message_id": message_id,
                "subject": subject,
                "from_address": from_,
                "to_addresses": to_,
                "cc_addresses": cc_,
                "sent_date": message_date_iso,  # Date from email headers
                "received_date": internal_date_iso,  # Date email arrived at server (INTERNALDATE)
                "internal_date": internal_date_iso,  # Used as cursor
                "body_text": text_body,
                "body_html": html_body,
                "attachments": attachments,  # List of {"filename": "...", "content_type": "...", "size": ...}
                "flags": [f.decode('utf-8', 'replace') for f in flags],  # e.g., ['\\Seen', '\\Answered']
                "raw_rfc822_content_preview": raw_rfc822[:500].decode('utf-8', 'replace')  # For debugging
            }
            return record

        except Exception as e:
            self._logger.error(f"Error processing message UID {uid}: {e}", exc_info=True)
            return None

    def _get_search_criteria(self, sync_mode: SyncMode, stream_state: Optional[Mapping[str, Any]] = None) -> List[
        Union[str, bytes, List[Any]]]:
        criteria = ["ALL"]  # Start with all messages in the folder

        start_date_str = self._config.get("start_date")
        cursor_value_str = stream_state.get(self.cursor_field) if stream_state else None

        # Determine the effective date to search from
        effective_since_date = None
        if sync_mode == SyncMode.incremental and cursor_value_str:
            try:
                # For incremental, search for messages SINCE the last cursor + 1 second to avoid re-fetching the exact same message.
                # IMAP SINCE is inclusive of the date, but not time. Using ON for specific date.
                # INTERNALDATE is often just a date, so using ON is better.
                # If INTERNALDATE has time, SINCE might be okay.
                # Let's try to use UID for incremental if possible, or rely on UNSEEN.
                # For now, let's stick to date based on INTERNALDATE.
                # A common strategy is to fetch UIDs greater than the last known UID if server supports UIDPLUS and UIDs are monotonic.
                # Or, if using INTERNALDATE, fetch messages ON or AFTER the date.
                # IMAPClient search for date: ['SINCE', date(YYYY, MM, DD)]
                # For INTERNALDATE, it's better to fetch all and filter, or use server-side search if available.
                # The `search` command in IMAP is powerful.
                # Let's use 'UNSEEN' for incremental if configured, otherwise SINCE last date.

                if self._config.get("import_unread_only_for_incremental", True):
                    criteria = ["UNSEEN"]
                    self._logger.info("Incremental sync: Searching for UNSEEN messages.")
                else:  # Date-based incremental
                    if cursor_value_str:
                        # Add 1 day to cursor to get messages *after* that date.
                        # IMAP 'SINCE' is exclusive of the date part for some servers, inclusive for others.
                        # 'ON' or 'SENTSINCE' / 'SENTON' might be more precise if available.
                        # For INTERNALDATE, which is server arrival, 'SINCE' should work.
                        # We need to be careful with timezones. Pendulum handles this well.
                        cursor_dt = pendulum.parse(cursor_value_str)
                        # Search for messages SINCE the day of the cursor.
                        # This might re-fetch messages from the same day if not careful.
                        # A better approach for INTERNALDATE might be to fetch all UIDs, then fetch INTERNALDATEs
                        # and filter client-side, or use a more precise server search if the server supports it.
                        # For simplicity, let's use SINCE the date of the cursor.
                        # This means messages on the cursor_dt day might be re-fetched.
                        # To avoid this, we'd need to store UID as well or filter more carefully.
                        # Let's try to fetch messages strictly *after* the cursor_dt.
                        # IMAP date format for search: DD-Mon-YYYY
                        since_date_imap_format = cursor_dt.strftime("%d-%b-%Y")
                        criteria = ["SINCE", since_date_imap_format]
                        self._logger.info(
                            f"Incremental sync: Searching for messages SINCE {since_date_imap_format} (from cursor {cursor_value_str}).")

            except Exception as e:
                self._logger.warning(
                    f"Could not parse cursor_value '{cursor_value_str}' for date-based incremental. Defaulting to UNSEEN or ALL. Error: {e}")
                if self._config.get("import_unread_only_for_incremental", True):
                    criteria = ["UNSEEN"]
                # else, criteria remains ["ALL"] or uses start_date if that's next

        # Apply start_date if it's a full refresh or if incremental didn't set a 'SINCE' from cursor
        # and start_date is more recent or applicable.
        is_full_refresh = sync_mode == SyncMode.full_refresh
        no_incremental_date_criteria = not any(isinstance(c, str) and c.upper() == "SINCE" for c in criteria)

        if start_date_str and (is_full_refresh or no_incremental_date_criteria):
            try:
                start_dt = pendulum.parse(start_date_str)
                start_date_imap_format = start_dt.strftime("%d-%b-%Y")
                # If criteria is already UNSEEN, we AND it with SINCE.
                # If criteria is ALL, we replace it with SINCE.
                if "UNSEEN" in criteria:
                    criteria.append("SINCE")
                    criteria.append(start_date_imap_format)
                else:  # criteria is ["ALL"] or something else without SINCE
                    criteria = ["SINCE", start_date_imap_format]
                self._logger.info(f"Applying start_date: Searching for messages SINCE {start_date_imap_format}.")
            except Exception as e:
                self._logger.warning(f"Could not parse start_date '{start_date_str}'. Ignoring. Error: {e}")

        # If criteria ended up empty (e.g. error in parsing), default to ALL
        if not criteria:
            criteria = ["ALL"]

        self._logger.info(f"Final IMAP search criteria: {criteria}")
        return criteria

    def read_records(
            self,
            sync_mode: SyncMode,
            cursor_field: Optional[List[str]] = None,
            stream_slice: Optional[Mapping[str, Any]] = None,
            stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Generator[Dict[str, Any], None, None]:

        self._connect_and_select_folder()
        if not self._client or not self._folder_selected:
            self._logger.error("IMAP client not connected or folder not selected. Cannot read records.")
            return

        search_criteria = self._get_search_criteria(sync_mode, stream_state)

        try:
            self._logger.info(f"Searching messages with criteria: {search_criteria}")
            # Sort by UID to process in a somewhat consistent order, though INTERNALDATE is the cursor.
            # Some servers might not support SORT or return UIDs sorted by default.
            # For now, let's not specify sort and rely on default order.
            message_uids = self._client.search(criteria=search_criteria)  # Returns list of UIDs
            self._logger.info(f"Found {len(message_uids)} message UIDs matching criteria.")

            if not message_uids:
                self._disconnect()
                return

            # Fetch messages in batches of UIDs
            latest_cursor_value = stream_state.get(self.cursor_field) if stream_state else None
            if latest_cursor_value:
                latest_cursor_value = pendulum.parse(latest_cursor_value)

            for i in range(0, len(message_uids), self.UID_FETCH_BATCH_SIZE):
                batch_uids = message_uids[i:i + self.UID_FETCH_BATCH_SIZE]
                self._logger.info(
                    f"Fetching details for UID batch {i // self.UID_FETCH_BATCH_SIZE + 1} ({len(batch_uids)} UIDs)")

                # Fetch ENVELOPE, INTERNALDATE, FLAGS, BODY.PEEK[] (non-altering) or BODY[]
                # BODY.PEEK[] is preferred as it doesn't set \Seen flag.
                # However, our select_folder is readonly=True, so BODY[] should be fine.
                # Let's use BODY[] for simplicity as PEEK might not be universally supported or might behave differently.
                fetch_items = [b"UID", b"ENVELOPE", b"INTERNALDATE", b"FLAGS", b"BODY[]", b"RFC822.SIZE"]

                # messages_data is a dict: {uid: {item_name: item_value, ...}}
                messages_data = self._client.fetch(batch_uids, fetch_items)

                for uid, data in messages_data.items():
                    record = self._process_message_data(uid, data)
                    if record:
                        record_cursor_val_str = record[self.cursor_field]
                        try:
                            record_cursor_val_dt = pendulum.parse(record_cursor_val_str)

                            # Update state: track the latest internal_date encountered
                            if latest_cursor_value is None or record_cursor_val_dt > latest_cursor_value:
                                latest_cursor_value = record_cursor_val_dt
                                self._state[self.cursor_field] = latest_cursor_value.to_iso8601_string()
                                # self._logger.info(f"Updating state cursor to: {self._state[self.cursor_field]} from UID {uid}")

                            yield record
                        except Exception as e:
                            self._logger.error(
                                f"Error parsing or comparing cursor for UID {uid} ('{record_cursor_val_str}'): {e}")

            if latest_cursor_value:
                self._logger.info(
                    f"Stream finished. Final state cursor for '{self.cursor_field}': {self._state.get(self.cursor_field)}")


        except IMAPClientError as e:
            self._logger.error(f"IMAPClient error during message fetching: {e}", exc_info=True)
            # Depending on the error, might want to raise or try to recover.
            # For now, log and stop the stream for this run.
        except Exception as e:
            self._logger.error(f"Unexpected error during message fetching: {e}", exc_info=True)
        finally:
            self._disconnect()

    def get_json_schema(self) -> Mapping[str, Any]:
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "uid": {"type": "integer", "description": "IMAP Unique ID of the message in the folder."},
                "message_id": {"type": ["string", "null"],
                               "description": "Message-ID header value (RFC822). Used as primary key."},
                "subject": {"type": ["string", "null"], "description": "Subject of the email."},
                "from_address": {"type": ["string", "null"], "description": "Sender's email address(es)."},
                "to_addresses": {"type": ["string", "null"], "description": "Recipient's email address(es)."},
                "cc_addresses": {"type": ["string", "null"], "description": "CC recipient's email address(es)."},
                "sent_date": {"type": ["string", "null"], "format": "date-time",
                              "description": "Date from email 'Date' header."},
                "received_date": {"type": ["string", "null"], "format": "date-time",
                                  "description": "Date email was received by the server (IMAP INTERNALDATE)."},
                "internal_date": {"type": ["string", "null"], "format": "date-time",
                                  "description": "IMAP INTERNALDATE, used as cursor field."},
                "body_text": {"type": ["string", "null"], "description": "Plain text body of the email."},
                "body_html": {"type": ["string", "null"], "description": "HTML body of the email."},
                "attachments": {
                    "type": "array",
                    "description": "List of attachments.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": ["string", "null"]},
                            "content_type": {"type": ["string", "null"]},
                            "size": {"type": ["integer", "null"], "description": "Size in bytes."}
                            # "content": {"type": ["string", "null"], "description": "Base64 encoded content (optional)"}
                        }
                    }
                },
                "flags": {
                    "type": "array",
                    "description": "IMAP flags for the message (e.g., \\Seen, \\Answered).",
                    "items": {"type": "string"}
                },
                "raw_rfc822_content_preview": {"type": ["string", "null"],
                                               "description": "Preview of the raw RFC822 email content (first 500 chars). For debugging."}
            }
        }

    def stream_slices(
            self, sync_mode: SyncMode, cursor_field: Optional[List[str]] = None,
            stream_state: Optional[Mapping[str, Any]] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        # For IMAP, we typically don't need to slice by anything other than what read_records handles (e.g. folder).
        # If we were to support multiple folders in one stream instance (not typical for Airbyte stream design),
        # then slices could be per folder.
        # For now, the stream operates on a single configured folder.
        # So, we yield one slice (None) which means read_records will be called once.
        yield None
