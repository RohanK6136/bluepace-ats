"""Private document storage with Backblaze B2 and local fallback.

B2 is accessed through its S3-compatible API. When all B2 connection
settings are present, uploaded documents are stored in B2 and references are
returned as b2://.... When B2 is not configured, Railway deployments with
a mounted volume default to that persistent volume; development keeps the
local private_uploads directory.
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
        # Respect explicit storage settings first. Older records may still use
        # the original local directory, so keep that path for legacy reads.
        configured_root = (
            os.getenv("RESUME_STORAGE_DIR", "").strip()
            or os.getenv("RESUME_QUEUE_STORAGE_DIR", "").strip()
        )
        self.legacy_local_root = Path(configured_root or "./private_uploads")

        if configured_root:
            self.local_root = self.legacy_local_root
        else:
            volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
            self.local_root = (
                Path(volume_mount) / "private_uploads"
                if volume_mount
                else self.legacy_local_root
            )

        self.endpoint = os.getenv("B2_ENDPOINT", "").strip()
        self.access_key = os.getenv("B2_ACCESS_KEY_ID", "").strip()
        self.secret_key = os.getenv("B2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("B2_BUCKET", "").strip()
        self.region = os.getenv("B2_REGION", "").strip()
        self._client = None

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Accept only relative POSIX storage keys without traversal segments."""
        if not isinstance(key, str) or not key or key.startswith("/"):
            raise ValueError("Invalid storage key.")
        if "\\" in key or "\x00" in key:
            raise ValueError("Invalid storage key.")
        segments = key.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("Invalid storage key.")
        return "/".join(segments)

    @staticmethod
    def _checked_local_path(key: str, root: Path) -> Path:
        """Refuse paths that resolve outside the configured storage root."""
        clean_key = PrivateStorage._normalize_key(key)
        root_path = Path(root)
        candidate = root_path.joinpath(*clean_key.split("/"))
        resolved_root = root_path.resolve()
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_root) or resolved_candidate == resolved_root:
            raise ValueError("Storage path escapes the configured root.")
        return candidate

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
        key = self._normalize_key(key)
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

        path = self._checked_local_path(key, self.local_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def read_bytes(self, reference: str) -> bytes:
        if reference.startswith(B2_SCHEME):
            key = self._normalize_key(reference[len(B2_SCHEME) :])
            client = self._get_client()
            if client is None:
                raise RuntimeError(
                    "Backblaze B2 storage reference received but B2 is not configured"
                )
            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        if reference.startswith(LOCAL_SCHEME):
            key = self._normalize_key(reference[len(LOCAL_SCHEME) :])
            current_path = self._checked_local_path(key, self.local_root)
            if current_path.is_file():
                return current_path.read_bytes()

            # Compatibility for files created before local storage defaulted
            # to a Railway volume.
            legacy_path = self._checked_local_path(key, self.legacy_local_root)
            if legacy_path != current_path and legacy_path.is_file():
                return legacy_path.read_bytes()
            return current_path.read_bytes()

        # Older releases stored local references as direct filesystem paths.
        return Path(reference).read_bytes()

    def delete(self, reference: str) -> None:
        if not reference:
            return

        if reference.startswith(B2_SCHEME):
            key = self._normalize_key(reference[len(B2_SCHEME) :])
            client = self._get_client()
            if client is None:
                return
            client.delete_object(Bucket=self.bucket, Key=key)
            return

        if reference.startswith(LOCAL_SCHEME):
            key = self._normalize_key(reference[len(LOCAL_SCHEME) :])
            current_path = self._checked_local_path(key, self.local_root)
            current_path.unlink(missing_ok=True)
            legacy_path = self._checked_local_path(key, self.legacy_local_root)
            if legacy_path != current_path:
                legacy_path.unlink(missing_ok=True)
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

        clean_key = self._normalize_key(key)
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

        key = self._normalize_key(reference[len(B2_SCHEME) :])
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )


private_storage = PrivateStorage()
