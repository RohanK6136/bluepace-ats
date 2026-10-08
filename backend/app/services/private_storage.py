"""Private document storage with Cloudflare R2 and local fallback.

R2 is enabled when all R2 connection settings are present. Keeping the local
fallback preserves development and test behavior without making production
configuration mandatory during rollout.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

R2_SCHEME = "r2://"


class PrivateStorage:
    def __init__(self) -> None:
        self.local_root = Path(
            os.getenv("RESUME_STORAGE_DIR", os.getenv("RESUME_QUEUE_STORAGE_DIR", "./private_uploads"))
        )
        self.endpoint = os.getenv("R2_ENDPOINT", "").strip()
        self.access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        self.secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("R2_BUCKET", "").strip()
        self.region = os.getenv("R2_REGION", "auto").strip() or "auto"
        self._client = None

    @property
    def r2_enabled(self) -> bool:
        return all((self.endpoint, self.access_key, self.secret_key, self.bucket))

    def _get_client(self):
        if not self.r2_enabled:
            return None
        if self._client is None:
            try:
                import boto3
            except ImportError as error:
                raise RuntimeError("R2 storage is configured but boto3 is not installed") from error
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        key = key.lstrip("/")
        client = self._get_client()
        if client is not None:
            extra = {"ContentType": content_type} if content_type else {}
            client.put_object(Bucket=self.bucket, Key=key, Body=content, **extra)
            return f"{R2_SCHEME}{key}"

        path = self.local_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def read_bytes(self, reference: str) -> bytes:
        if reference.startswith(R2_SCHEME):
            client = self._get_client()
            if client is None:
                raise RuntimeError("R2 storage reference received but R2 is not configured")
            key = reference[len(R2_SCHEME):].lstrip("/")
            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return Path(reference).read_bytes()

    def delete(self, reference: str) -> None:
        if not reference:
            return
        if reference.startswith(R2_SCHEME):
            client = self._get_client()
            if client is None:
                return
            key = reference[len(R2_SCHEME):].lstrip("/")
            client.delete_object(Bucket=self.bucket, Key=key)
            return
        Path(reference).unlink(missing_ok=True)

    def presigned_download_url(self, reference: str, expires_in: int = 900) -> str | None:
        if not reference.startswith(R2_SCHEME):
            return None
        client = self._get_client()
        if client is None:
            return None
        key = reference[len(R2_SCHEME):].lstrip("/")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )


private_storage = PrivateStorage()
