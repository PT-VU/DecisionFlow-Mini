from __future__ import annotations

from typing import Any


class AzureBlobArtifactStore:
    """Small content-addressed artifact writer for large evidence payloads."""

    def __init__(self, account_url: str, container: str, credential: Any = None):
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install azure-storage-blob to use Blob artifacts") from exc
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        service = BlobServiceClient(account_url=account_url, credential=credential)
        self.container = service.get_container_client(container)
        self.container.create_container()

    def put(self, name: str, content: bytes, *, content_type: str = "application/json") -> str:
        from azure.storage.blob import ContentSettings

        self.container.upload_blob(
            name=name,
            data=content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        return name

