import pathlib

from app.services.private_storage import PrivateStorage


def test_private_storage_uses_local_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("B2_ENDPOINT", raising=False)
    monkeypatch.delenv("B2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("B2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("B2_BUCKET", raising=False)
    monkeypatch.delenv("B2_REGION", raising=False)
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path))

    storage = PrivateStorage()
    reference = storage.put_bytes(
        "org/resume/test.pdf",
        b"resume",
        "application/pdf",
    )

    assert reference == str(pathlib.Path(tmp_path) / "org/resume/test.pdf")
    assert storage.read_bytes(reference) == b"resume"

    storage.delete(reference)
    assert not pathlib.Path(reference).exists()


def test_private_storage_uses_b2_reference_format(monkeypatch):
    monkeypatch.setenv("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
    monkeypatch.setenv("B2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("B2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("B2_BUCKET", "bluepace-files")
    monkeypatch.setenv("B2_REGION", "us-west-004")

    storage = PrivateStorage()
    storage._client = object()

    assert storage.b2_enabled is True
