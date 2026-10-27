"""Document ingest shared by all features: pasted text, .txt/.md, .pdf (pypdf), .docx (python-docx) → RawLines."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.core.errors import IngestError

ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md"}
_PAGE_NUM_RE = re.compile(r"^\s*(?:\d+|page \d+(?: of \d+)?)\s*$", re.I)


class RawLine(BaseModel):
    """One extracted line; `style` is "heading" or "list_item" when the document says so (DOCX)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    style: str | None = None
    level: int = 0


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def ingest_text(text: str) -> list[RawLine]:
    return [RawLine(text=t) for t in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def ingest_pdf(data: bytes) -> list[RawLine]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise IngestError(f"unreadable PDF: {e}") from None
    lines = ingest_text("\n".join(pages))
    return [ln for ln in lines if not _PAGE_NUM_RE.match(ln.text)]


def _check_docx_size(data: bytes, max_bytes: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile:
        raise IngestError("not a valid .docx file") from None
    if total > max_bytes:
        raise IngestError("DOCX uncompressed size exceeds limit")


def ingest_docx(data: bytes, max_uncompressed_bytes: int) -> list[RawLine]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_docx_size(data, max_uncompressed_bytes)
    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises a variety of errors on corrupt input
        raise IngestError(f"unreadable DOCX: {e}") from None

    out: list[RawLine] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            try:
                style_name = p.style.name if p.style is not None else ""
            except (KeyError, AttributeError):
                style_name = ""
            ppr = child.pPr
            num_pr = ppr.numPr if ppr is not None else None
            style: str | None = None
            level = 0
            prefix = ""
            if style_name.startswith("Heading") or style_name == "Title":
                style = "heading"
            elif num_pr is not None or style_name.startswith("List"):
                style = "list_item"
                if num_pr is not None and num_pr.ilvl is not None:
                    level = int(num_pr.ilvl.val)
                prefix = "• "
            for part in p.text.split("\n"):
                text = part.strip()
                out.append(RawLine(text=f"{prefix}{text}" if text else "", style=style, level=level))
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    t = " ".join(cell.text.split())
                    if t and (not cells or cells[-1] != t):  # merged cells repeat
                        cells.append(t)
                if cells:
                    out.append(RawLine(text=" | ".join(cells)))
            out.append(RawLine(text=""))
    return out


def ingest_file(filename: str, data: bytes, settings: Settings) -> tuple[list[RawLine], str]:
    ext = Path(filename).suffix.casefold()
    if ext not in ALLOWED_EXTS:
        raise IngestError(f"unsupported file type {ext!r}; allowed: {sorted(ALLOWED_EXTS)}")
    if ext == ".pdf":
        return ingest_pdf(data), "pdf"
    if ext == ".docx":
        return ingest_docx(data, int(settings.MAX_DOCX_UNCOMPRESSED_MB * 1024 * 1024)), "docx"
    return ingest_text(decode_text(data)), ext.lstrip(".")


def text_chars(lines: list[RawLine]) -> int:
    return sum(len(ln.text.strip()) for ln in lines)
