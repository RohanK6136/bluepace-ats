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

R2_SCHEME = "r2://"
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
        self.r2_endpoint = os.getenv("R2_ENDPOINT", "").strip()
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        self.r2_bucket = os.getenv("R2_BUCKET", "").strip()
        self.r2_region = os.getenv("R2_REGION", "auto").strip() or "auto"

        self.endpoint = os.getenv("B2_ENDPOINT", "").strip()
        self.access_key = os.getenv("B2_ACCESS_KEY_ID", "").strip()
        self.secret_key = os.getenv("B2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("B2_BUCKET", "").strip()
        self.region = os.getenv("B2_REGION", "").strip()
        self._clients = {}

    @property
    def r2_enabled(self) -> bool:
        return all((self.r2_endpoint, self.r2_access_key, self.r2_secret_key, self.r2_bucket))

    @property
    def b2_enabled(self) -> bool:
        return all((self.endpoint, self.access_key, self.secret_key, self.bucket, self.region))

    @property
    def provider(self) -> str:
        if self.r2_enabled:
            return "r2"
        if self.b2_enabled:
            return "b2"
        return "local"

    def _get_client(self, provider: str | None = None):
        provider = provider or self.provider
        if provider == "local":
            return None
        if provider in self._clients:
            return self._clients[provider]

        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("boto3 is required for object storage uploads") from error

        if provider == "r2":
            endpoint, access_key, secret_key, bucket, region = (
                self.r2_endpoint, self.r2_access_key, self.r2_secret_key, self.r2_bucket, self.r2_region
            )
        else:
            endpoint, access_key, secret_key, bucket, region = (
                self.endpoint, self.access_key, self.secret_key, self.bucket, self.region
            )

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._clients[provider] = client
        return client

    def put_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        key = key.lstrip("/")
        provider = self.provider
        client = self._get_client(provider)
        if client is not None:
            extra = {"ContentType": content_type} if content_type else {}
            bucket = self.r2_bucket if provider == "r2" else self.bucket
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=content,
                **extra,
            )
            return f"{R2_SCHEME if provider == 'r2' else B2_SCHEME}{key}"

        path = self.local_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def read_bytes(self, reference: str) -> bytes:
        if reference.startswith(R2_SCHEME):
            client = self._get_client("r2")
            if client is None:
                raise RuntimeError("Cloudflare R2 storage reference received but R2 is not configured")
            key = reference[len(R2_SCHEME) :].lstrip("/")
            response = client.get_object(Bucket=self.r2_bucket, Key=key)
            return response["Body"].read()

        if reference.startswith(B2_SCHEME):
            client = self._get_client("b2")
            if client is None:
                raise RuntimeError("Backblaze B2 storage reference received but B2 is not configured")
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

        if reference.startswith(R2_SCHEME):
            client = self._get_client("r2")
            if client is None:
                return
            key = reference[len(R2_SCHEME) :].lstrip("/")
            client.delete_object(Bucket=self.r2_bucket, Key=key)
            return

        if reference.startswith(B2_SCHEME):
            client = self._get_client("b2")
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
        provider = self.provider
        if provider == "local":
            return None

        client = self._get_client(provider)
        if client is None:
            return None

        clean_key = key.lstrip("/")
        bucket = self.r2_bucket if provider == "r2" else self.bucket
        params = {"Bucket": bucket, "Key": clean_key}
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
        if reference.startswith(R2_SCHEME):
            provider = "r2"
            scheme = R2_SCHEME
            bucket = self.r2_bucket
        elif reference.startswith(B2_SCHEME):
            provider = "b2"
            scheme = B2_SCHEME
            bucket = self.bucket
        else:
            return None

        client = self._get_client(provider)
        if client is None:
            return None

        key = reference[len(scheme) :].lstrip("/")
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )


private_storage = PrivateStorage()
