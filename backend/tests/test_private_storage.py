import pathlib

from app.services.private_storage import PrivateStorage


def test_private_storage_uses_local_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("R2_BUCKET", raising=False)
    monkeypatch.setenv("RESUME_STORAGE_DIR", str(tmp_path))

    storage = PrivateStorage()
    reference = storage.put_bytes("org/resume/test.pdf", b"resume", "application/pdf")

    assert reference == str(pathlib.Path(tmp_path) / "org/resume/test.pdf")
    assert storage.read_bytes(reference) == b"resume"

    storage.delete(reference)
    assert not pathlib.Path(reference).exists()
