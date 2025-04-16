import hashlib
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, TypedDict

import requests


class AbstractFileSource(ABC):
    @abstractmethod
    def get_file_id(self, uri: str)  -> str:
        """
        Generate a unique ID for a file based on its uri and modification time
        """
        pass

    @abstractmethod
    def list_files(self, uri: str) -> List[str]:
        """
        Recursively scan an uri for supported document files
        """
        pass

    @abstractmethod
    def download_file(self, uri: str) -> str:
        """
        Downloads a file to the local filesystem.
        """
        pass

    @abstractmethod
    def get_modified_time(self, uri: str) -> datetime:
        """
        Get the last modified time of a file
        """
        pass

def _generate_file_id(uri: str, modified_time: datetime) -> str:
    """
    Generate a unique ID for a file based on its uri and modification time
    """
    unique_string = f"{uri}_{modified_time.isoformat()}"
    return hashlib.md5(unique_string.encode()).hexdigest()

class LocalFileSystemSource(AbstractFileSource):
    """
    Leverages the os module for interacting with local filesystem.
    """
    def __init__(self):
        self.logger = logging.getLogger("local-file-system-source")

    def get_file_id(self, uri: str)  -> str:
        return _generate_file_id(uri, self._get_modified_time(uri))

    def list_files(self, uri: str) -> List[str]:
        filelist: List[str] = []
        directory = Path(uri)

        if not directory.exists() or not directory.is_dir():
            self.logger.error(f"Directory not found or not a directory: {uri}")
            return []

        # Walk through the directory and all subdirectories
        for root, _, files in os.walk(uri):
            for file in files:
                file_path = os.path.join(root, file)
                filelist.append(file_path)
                self.logger.info(f"Found supported document: {file_path}")

        return filelist

    def download_file(self, uri: str) -> str:
        # we dont need to download the file, it is already on the local filesystem
        return uri

    def get_modified_time(self, uri) -> datetime:
        return self._get_modified_time(uri)

    def get_modified_time(self, uri: str) -> datetime:
        file_stats = os.stat(uri)
        return datetime.fromtimestamp(file_stats.st_mtime)

class SharepointConfig(TypedDict):
    site_url: str
    client_id: str
    client_secret: str
    site_url: str
    drive: str


class SharepointFileSource(AbstractFileSource):
    def __init__(self, config: SharepointConfig):
        self.client = SharePointClient(config.get("site_url"), config.get("client_id"), config.get("client_secret"))
        self.site_id = self.client.get_site(config.get("site_url"))["id"]
        drives = self.client.get_drives(self.site_id)
        filtered_drives = [drive for drive in drives if drive["name"] == config.get("drive")]
        self.drive_id = filtered_drives.pop()["id"] # assuming drive names on a sharepoint site are unique, TODO they are in fact not unique

    def get_file_id(self, uri):
        pass

    def list_files(self, uri) -> List[str]:
        files = []
        for item in self.client.get_files_recursively(self.site_id, self.drive_id, path=uri):
            files.append(f"{item.get("path")}/{item.get("name")}")

        return files

    def download_file(self, uri):
        pass

    def get_modified_time(self, uri) -> datetime:
        pass


class SharePointClient:
    def __init__(self, tenant_id, client_id, client_secret):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource = "https://graph.microsoft.com"
        self.headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        self.access_token = self._login().get('access_token')

    def _login(self):
        body = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': self.resource + '/.default'
        }
        response = requests.post(f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token", headers=self.headers, data=body)
        return response.json()

    def _get_folder_id_by_path(self, site_id, drive_id, path):
        full_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:/{path}"
        response = requests.get(full_url, headers={'Authorization': f'Bearer {self.access_token}'})
        return response.json()["id"]

    def get_site(self, site_url):
        full_url = f"https://graph.microsoft.com/v1.0/sites/{site_url}"
        response = requests.get(full_url, headers={'Authorization': f'Bearer {self.access_token}'})
        return response.json()

    def get_drives(self, site_id):
        # Retrieve drive IDs and names associated with a site
        drives_url = f'{self.resource}/v1.0/sites/{site_id}/drives'
        response = requests.get(drives_url, headers={'Authorization': f'Bearer {self.access_token}'})
        drives = response.json().get('value', [])
        return drives

    def get_files_recursively(self, site_id, drive_id, path="root"):
        folder_contents_url = f'{self.resource}/v1.0/sites/{site_id}/drives/{drive_id}/items/root/children'
        if path != "root":
            folder_id = self._get_folder_id_by_path(site_id, drive_id, path)
            folder_contents_url = f'{self.resource}/v1.0/sites/{site_id}/drives/{drive_id}/items/{folder_id}/children'
        contents_headers = {'Authorization': f'Bearer {self.access_token}'}
        contents_response = requests.get(folder_contents_url, headers=contents_headers)
        folder_contents = contents_response.json()
        items_list = []  # List to store information

        if 'value' in folder_contents:
            for item in folder_contents['value']:
                if 'folder' in item:
                    full_path = item['name']
                    if path != "root":
                        full_path = f"{path}/{item['name']}"
                    items_list.extend(self.get_files_recursively(site_id, drive_id, full_path))
                elif 'file' in item:
                    items_list.append({
                        "name": item["name"],
                        "id": item["id"],
                        "sharepoint_path": item["parentReference"]["path"],
                        "path": item["parentReference"]["path"].split(":")[1],
                        "created_at": item["createdDateTime"],
                        "modified_at": item["lastModifiedDateTime"],
                        "mime_type": item["file"]["mimeType"],
                        "download_url": item["@microsoft.graph.downloadUrl"],
                        "web_url": item["webUrl"]

                    })
        return items_list

    def download_file(self, download_url, file_name, download_dir="."):
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(download_url, headers=headers)
        if response.status_code == 200:
            full_path = os.path.join(download_dir, file_name)
            with open(full_path, 'wb') as file:
                file.write(response.content)
            print(f"File downloaded: {full_path}")
        else:
            print(f"Failed to download {file_name}: {response.status_code} - {response.reason}")
