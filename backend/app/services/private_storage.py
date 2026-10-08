"""Private document storage with Backblaze B2 and local fallback.

B2 is accessed through its S3-compatible API. When all B2 connection
settings are present, uploaded documents are stored in B2 and references are
returned as `b2://...`. Keeping the local fallback preserves development
and test behavior without requiring cloud configuration during rollout.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

B2_SCHEME = "b2://"
LOCAL_SCHEME = "local://"
B2_REGION = os.getenv("B2_REGION", "").strip()
B2_ENDPOINT = os.getenv("B2_ENDPOINT", "").strip()
B2_ACCESS_KEY_ID = os.getenv("B2_ACCESS_KEY_ID", "").strip()
B2_SECRET_ACCESS_KEY = os.getenv("B2_SECRET_ACCESS_KEY", "").strip()
B2_BUCKET = os.getenv("B2_BUCKET", "").strip()


class PrivateStorage:
    def __init__(self) -> None:
        self.local_root = Path(
            os.getenv(
                "RESUME_STORAGE_DIR",
                os.getenv("RESUME_QUEUE_STORAGE_DIR", "./private_uploads"),
            )
        )
        self.endpoint = os.getenv("B2_ENDPOINT", "").strip()
        self.access_key = os.getenv("B2_ACCESS_KEY_ID", "").strip()
        self.secret_key = os.getenv("B2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("B2_BUCKET", "").strip()
        self.region = os.getenv("B2_REGION", "").strip()
        self._client = None

    @property
    def b2_enabled(self) -> bool:
        return all(
            (
                self.endpoint,
                self.access_key,
                self.secret_key,
                self.bucket,
                self.region,
            )
        )

    def _get_client(self):
        if not self.b2_enabled:
            return None
        if self._client is None:
            try:
                import boto3
            except ImportError as error:
                raise RuntimeError(
                    "Backblaze B2 storage is configured but boto3 is not installed"
                ) from error

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    def put_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        key = key.lstrip("/")
        client = self._get_client()
        if client is not None:
            extra = {"ContentType": content_type} if content_type else {}
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                **extra,
            )
            return f"{B2_SCHEME}{key}"

        path = self.local_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def read_bytes(self, reference: str) -> bytes:
        if reference.startswith(B2_SCHEME):
            client = self._get_client()
            if client is None:
                raise RuntimeError(
                    "Backblaze B2 storage reference received but B2 is not configured"
                )
            key = reference[len(B2_SCHEME) :].lstrip("/")
            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        if reference.startswith(LOCAL_SCHEME):
            key = reference[len(LOCAL_SCHEME) :].lstrip("/")
            return (self.local_root / key).read_bytes()

        return Path(reference).read_bytes()

    def delete(self, reference: str) -> None:
        if not reference:
            return

        if reference.startswith(B2_SCHEME):
            client = self._get_client()
            if client is None:
                return
            key = reference[len(B2_SCHEME) :].lstrip("/")
            client.delete_object(Bucket=self.bucket, Key=key)
            return

        if reference.startswith(LOCAL_SCHEME):
            key = reference[len(LOCAL_SCHEME) :].lstrip("/")
            (self.local_root / key).unlink(missing_ok=True)
            return

        Path(reference).unlink(missing_ok=True)

    def presigned_upload_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_in: int = 900,
    ) -> str | None:
        if not self.b2_enabled:
            return None

        client = self._get_client()
        if client is None:
            return None

        clean_key = key.lstrip("/")
        params = {"Bucket": self.bucket, "Key": clean_key}
        if content_type:
            params["ContentType"] = content_type

        return client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )

    def presigned_download_url(
        self,
        reference: str,
        expires_in: int = 900,
    ) -> str | None:
        if not reference.startswith(B2_SCHEME):
            return None

        client = self._get_client()
        if client is None:
            return None

        key = reference[len(B2_SCHEME) :].lstrip("/")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )


private_storage = PrivateStorage()
