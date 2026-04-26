from __future__ import annotations

from google.cloud import storage

from app.core.config import Settings


class StorageBridgeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: storage.Client | None = None

    def _get_client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(project=self.settings.firebase_project_id)
        return self._client

    def download_bytes(self, storage_path: str) -> bytes:
        if not storage_path.startswith("gs://"):
            raise ValueError("Storage path must use the gs://bucket/path format.")

        bucket_and_path = storage_path.removeprefix("gs://")
        bucket_name, _, object_path = bucket_and_path.partition("/")
        if not bucket_name or not object_path:
            raise ValueError("Storage path must include both bucket and object path.")

        bucket = self._get_client().bucket(bucket_name)
        blob = bucket.blob(object_path)
        return blob.download_as_bytes()
