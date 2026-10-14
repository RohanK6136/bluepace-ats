import pathlib

from app.services.private_storage import PrivateStorage


def clear_storage_env(monkeypatch):
    for name in (
        "B2_ENDPOINT",
        "B2_ACCESS_KEY_ID",
        "B2_SECRET_ACCESS_KEY",
        "B2_BUCKET",
        "B2_REGION",
        "RESUME_STORAGE_DIR",
        "RESUME_QUEUE_STORAGE_DIR",
        "RAILWAY_VOLUME_MOUNT_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_private_storage_uses_local_fallback(tmp_path, monkeypatch):
    clear_storage_env(monkeypatch)
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


def test_railway_volume_is_default_local_storage_when_no_path_is_configured(
    tmp_path, monkeypatch
):
    clear_storage_env(monkeypatch)
    volume_path = tmp_path / "volume"
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(volume_path))

    storage = PrivateStorage()
    reference = storage.put_bytes("org/resume/test.pdf", b"persistent")

    expected_root = volume_path / "private_uploads"
    assert storage.local_root == expected_root
    assert reference == str(expected_root / "org/resume/test.pdf")
    assert storage.read_bytes(reference) == b"persistent"


def test_legacy_local_scheme_references_remain_readable(tmp_path, monkeypatch):
    clear_storage_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "volume"))

    legacy_root = tmp_path / "private_uploads"
    legacy_root.mkdir()
    (legacy_root / "older-resume.pdf").write_bytes(b"legacy")

    storage = PrivateStorage()
    assert storage.local_root != storage.legacy_local_root
    assert storage.read_bytes("local://older-resume.pdf") == b"legacy"

    storage.delete("local://older-resume.pdf")
    assert not (legacy_root / "older-resume.pdf").exists()


def test_private_storage_uses_b2_reference_format(monkeypatch):
    monkeypatch.setenv("B2_ENDPOINT", "https://s3.us-west-004.backblazeb2.com")
    monkeypatch.setenv("B2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("B2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("B2_BUCKET", "bluepace-files")
    monkeypatch.setenv("B2_REGION", "us-west-004")

    storage = PrivateStorage()
    storage._client = object()

    assert storage.b2_enabled is True
