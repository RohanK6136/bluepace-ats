#!/usr/bin/env python3
"""Compare Docling and the existing pypdf/python-docx extraction path.

Usage:
  python backend/scripts/benchmark_document_extraction.py samples/*.pdf samples/*.docx

The input set should include representative normal, multi-column, table-heavy,
and scanned/image-only documents. For scanned PDFs, Docling must have an OCR
engine available in the runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.document_intelligence import document_intelligence_service
from app.services.extractor import DocumentExtractionError, extractor_service


def run_engine(content: bytes, filename: str, engine: str) -> dict:
    previous_engine = document_intelligence_service.engine
    previous_converter = document_intelligence_service._converter
    document_intelligence_service.engine = engine
    document_intelligence_service._converter = None
    started = time.perf_counter()
    try:
        parsed = extractor_service.extract_to_json(content, filename)
        elapsed = time.perf_counter() - started
        return {
            "status": "success",
            "seconds": round(elapsed, 3),
            "chars": len(str(parsed.get("raw_text") or "")),
            "engine": parsed.get("document_extraction_engine", engine),
        }
    except (DocumentExtractionError, Exception) as error:
        elapsed = time.perf_counter() - started
        return {
            "status": "error",
            "seconds": round(elapsed, 3),
            "chars": 0,
            "engine": engine,
            "error": str(error),
        }
    finally:
        document_intelligence_service.engine = previous_engine
        document_intelligence_service._converter = previous_converter


def benchmark(path: Path) -> dict:
    content = path.read_bytes()
    docling = run_engine(content, path.name, "docling")
    legacy = run_engine(content, path.name, "fallback")
    return {
        "file": str(path),
        "size_bytes": len(content),
        "docling": docling,
        "legacy": legacy,
        "char_delta": docling["chars"] - legacy["chars"],
        "speed_ratio_legacy_over_docling": (
            round(legacy["seconds"] / docling["seconds"], 2)
            if docling["seconds"] > 0
            else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    results = []
    for path in args.files:
        if not path.is_file():
            print(f"Skipping missing file: {path}", file=sys.stderr)
            continue
        results.append(benchmark(path))

    if not results:
        print("No benchmark inputs were found.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    header = f"{'File':40} {'Bytes':>10} {'Docling s':>10} {'Legacy s':>10} {'Doc chars':>10} {'Legacy chars':>12} {'Status':>12}"
    print(header)
    print("-" * len(header))
    for item in results:
        print(
            f"{item['file'][:40]:40} "
            f"{item['size_bytes']:10d} "
            f"{item['docling']['seconds']:10.3f} "
            f"{item['legacy']['seconds']:10.3f} "
            f"{item['docling']['chars']:10d} "
            f"{item['legacy']['chars']:12d} "
            f"{item['docling']['status']:>12}"
        )

    print("\nInterpretation:")
    print("- More extracted characters are not automatically better; review structure and semantic completeness.")
    print("- Table-heavy and multi-column files should be checked for reading-order and cell preservation.")
    print("- Scanned PDFs should extract meaningful text through Docling OCR; legacy pypdf may return little or no text.")
    print("- Keep the legacy path as fallback when Docling initialization or conversion fails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
