import pytest
from fastapi import HTTPException

from app.main import _validate_resume_manifest_file


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        "../resume.pdf",
        r"..\\resume.pdf",
        "x" * 256 + ".pdf",
    ],
)
def test_bulk_resume_manifest_rejects_invalid_filename(filename):
    with pytest.raises(HTTPException) as error:
        _validate_resume_manifest_file(filename, 1024)

    assert error.value.status_code == 400
    assert "filename" in error.value.detail.lower()


@pytest.mark.parametrize("filename,expected_suffix", [("resume.pdf", ".pdf"), ("resume.docx", ".docx")])
def test_bulk_resume_manifest_accepts_supported_plain_filenames(filename, expected_suffix):
    assert _validate_resume_manifest_file(filename, 1024) == expected_suffix


def test_bulk_resume_manifest_rejects_oversized_file_before_upload():
    with pytest.raises(HTTPException) as error:
        _validate_resume_manifest_file("resume.pdf", 5 * 1024 * 1024 + 1)

    assert error.value.status_code == 413
    assert "5 MB" in error.value.detail
