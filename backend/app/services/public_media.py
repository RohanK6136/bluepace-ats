"""Optional Cloudinary delivery for public careers-site media.

Private candidate/JD documents are intentionally excluded; those belong in R2.
"""
from __future__ import annotations

import os
from io import BytesIO


class PublicMediaError(ValueError):
    pass


class PublicMediaService:
    def __init__(self) -> None:
        self.cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        self.api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
        self.api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
        self.folder = os.getenv("CLOUDINARY_PUBLIC_FOLDER", "careers-site").strip() or "careers-site"

    @property
    def enabled(self) -> bool:
        return bool(self.cloud_name and self.api_key and self.api_secret)

    def upload_public(self, content: bytes, filename: str, content_type: str | None = None) -> dict:
        if not self.enabled:
            raise PublicMediaError("Cloudinary public media is not configured.")
        try:
            import cloudinary
            import cloudinary.uploader
        except Exception as error:
            raise PublicMediaError(f"Cloudinary SDK is unavailable: {error}") from error

        cloudinary.config(
            cloud_name=self.cloud_name,
            api_key=self.api_key,
            api_secret=self.api_secret,
            secure=True,
        )
        resource_type = "auto"
        result = cloudinary.uploader.upload(
            BytesIO(content),
            resource_type=resource_type,
            type="upload",
            folder=self.folder,
            use_filename=True,
            unique_filename=True,
            overwrite=False,
            context={"original_filename": filename},
        )
        return {
            "public_id": result.get("public_id"),
            "resource_type": result.get("resource_type"),
            "format": result.get("format"),
            "secure_url": result.get("secure_url"),
            "bytes": result.get("bytes"),
            "content_type": content_type,
            "filename": filename,
        }


public_media_service = PublicMediaService()
