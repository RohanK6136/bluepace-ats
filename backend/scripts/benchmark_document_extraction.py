#!/usr/bin/env python3
"""Benchmark Docling against the legacy pypdf/python-docx text extractor.

Usage:
  python backend/scripts/benchmark_document_extraction.py file1.pdf file2.docx

The script intentionally does not upload files or persist benchmark data.
It reports engine, latency, extracted character count and rough field coverage.
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

from app.services.document_intelligence import DocumentIntelligenceError, document_intelligence_service
from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES, SUPPORTED_DOCUMENT_EXTENSIONS
from app.services.extractor import DocumentExtractor


def legacy_text(content: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    parts: list[str] = []
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages:
            value = page.extract_text()
            if value:
                parts.append(value)
    elif suffix == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(content))
        parts.extend(p.text for p in doc.paragraphs if p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    else:
        raise ValueError(f"Unsupported extension: {suffix}")
    return "\n".join(parts).strip()


def main(paths: list[str]) -> int:
    if not paths:
        print("Provide at least one PDF/DOCX path.", file=sys.stderr)
        return 2

    fallback_parser = DocumentExtractor()
    print("file,engine,latency_ms,characters,email,phone,skills,experience,education")
    for raw_path in paths:
        path = Path(raw_path)
        content = path.read_bytes()
        if len(content) > MAX_DOCUMENT_SIZE_BYTES:
            print(f"{path.name},rejected,0,0,0,0,0,0,0", file=sys.stdout)
            continue
        if path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
            print(f"{path.name},unsupported,0,0,0,0,0,0,0", file=sys.stdout)
            continue

        started = time.perf_counter()
        try:
            result = document_intelligence_service.extract(content, path.name)
            docling_text = result.text
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            parsed = fallback_parser._fallback_parse(docling_text)
            print(
                f"{path.name},docling,{latency_ms},{len(docling_text)},"
                f"{int(bool(parsed.get('email')))},{int(bool(parsed.get('phone')))},"
                f"{len(parsed.get('skills') or [])},{len(parsed.get('experience') or [])},{len(parsed.get('education') or [])}"
            )
        except DocumentIntelligenceError:
            started = time.perf_counter()
            legacy = legacy_text(content, path.name)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            parsed = fallback_parser._fallback_parse(legacy)
            print(
                f"{path.name},legacy_fallback,{latency_ms},{len(legacy)},"
                f"{int(bool(parsed.get('email')))},{int(bool(parsed.get('phone')))},"
                f"{len(parsed.get('skills') or [])},{len(parsed.get('experience') or [])},{len(parsed.get('education') or [])}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
