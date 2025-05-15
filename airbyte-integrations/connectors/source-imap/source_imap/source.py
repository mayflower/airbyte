import logging
import ssl
from typing import Any, List, Mapping, Tuple, Optional


from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError, LoginError

from .streams import MailStream

# logger = logging.getLogger("airbyte")


class SourceImap(AbstractSource):
    def _create_client(self, config: Mapping[str, Any]) -> IMAPClient:
        """
        Helper method to create and configure an IMAPClient instance.
        """
        ssl_context = None
        if config.get("use_ssl", True):
            ssl_context = ssl.create_default_context()
            # Optionally, allow insecure connections if needed for some servers,
            # but this should be a specific configuration option if added.
            # ssl_context.check_hostname = False
            # ssl_context.verify_mode = ssl.CERT_NONE

        client = IMAPClient(
            host=config["host"],
            port=config.get("port", 993 if config.get("use_ssl", True) else 143),
            ssl=config.get("use_ssl", True),
            ssl_context=ssl_context,
            timeout=60  # seconds
        )
        return client

    def check_connection(
        self, logger:  logging.Logger, config: Mapping[str, Any]
    ) -> Tuple[bool, Optional[Any]]:
        """
        Tests if the input configuration can be used to successfully connect to the IMAP server.

        :param logger: Airbyte logger
        :param config: The user-provided configuration as specified by the source's spec.yaml file
        :return: A tuple (boolean, error_message). If (True, None), the connection was successful.
                 If (False, error_message), the connection failed.
        """
        client = None
        try:
            client = self._create_client(config)
            logger.info("Attempting to connect to IMAP server...")
            # The connection is typically established on IMAPClient instantiation or first command.
            # We'll try to login and list folders to confirm.

            client.login(config["username"], config["password"])
            logger.info("Login successful.")

            # Check if the specified folder exists
            folder_to_check = config.get("folder", "INBOX")
            if not client.folder_exists(folder_to_check):
                logger.error(f"Folder '{folder_to_check}' does not exist.")
                return False, f"Folder '{folder_to_check}' does not exist. Please check the folder name and path."

            logger.info(f"Folder '{folder_to_check}' exists.")

            client.logout()
            logger.info("Logout successful. Connection check passed.")
            return True, None

        except LoginError as e:
            logger.error(f"Login failed: {e}")
            return False, f"Failed to login to IMAP server: {e}. Please check your username and password."
        except IMAPClientError as e:
            logger.error(f"IMAPClient error during connection check: {e}")
            return False, f"Failed to connect to IMAP server due to IMAPClientError: {e}. Check host, port, and SSL settings."
        except ssl.SSLError as e:
            logger.error(f"SSL error during connection check: {e}")
            return False, f"SSL error: {e}. Ensure SSL/TLS is configured correctly for the server and port."
        except socket.gaierror as e:
            logger.error(f"Address-related error connecting to IMAP server: {e}")
            return False, f"Failed to resolve IMAP server address: {e}. Check the host name."
        except socket.timeout:
            logger.error("Connection to IMAP server timed out.")
            return False, "Connection timed out. The IMAP server may be slow or unreachable."
        except Exception as e:
            logger.error(f"An unexpected error occurred during connection check: {e}")
            return False, f"An unexpected error occurred: {e}"
        finally:
            if 'client' in locals() and client:
                try:
                    client.logout()
                except Exception:
                    pass # Ignore errors during cleanup logout

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """
        :param config: A Mapping (e.g., a dict) containing the configuration parameters for this source.
        :return: A list of Stream objects.
        """
        return [MailStream(config=config, source_name=self.name)]

# Need to import socket for gaierror and timeout
import socket