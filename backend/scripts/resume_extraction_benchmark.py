"""Synthetic, provider-free evaluation of the deterministic resume extractor.

Run from the backend directory:
    APP_ENV=test python scripts/resume_extraction_benchmark.py

The generated CVs contain synthetic contact details only. This harness does not
call hosted AI providers and does not write candidate records or uploaded files.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable

from docx import Document
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    filename: str
    content: bytes
    expected: dict[str, Any]


def _pdf_bytes(columns: list[tuple[int, int, list[str]]]) -> bytes:
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=(595, 842))
    for x, start_y, lines in columns:
        text = page.beginText(x, start_y)
        text.setFont("Helvetica", 10)
        text.setLeading(16)
        for line in lines:
            text.textLine(line)
        page.drawText(text)
    page.save()
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    document = Document()
    document.add_heading("Aarav Mehta", level=1)
    document.add_paragraph("Email: aarav.mehta@example.test")
    document.add_paragraph("Phone: 415-555-0132")
    document.add_heading("Skills", level=2)
    document.add_paragraph("Python, FastAPI, PostgreSQL, React")
    document.add_heading("Experience", level=2)
    experience = document.add_table(rows=1, cols=3)
    experience.cell(0, 0).text = "Software Engineer"
    experience.cell(0, 1).text = "Acme Labs"
    experience.cell(0, 2).text = "Jan 2020 - Dec 2022"
    document.add_heading("Education", level=2)
    education = document.add_table(rows=1, cols=3)
    education.cell(0, 0).text = "Bachelor"
    education.cell(0, 1).text = "State University"
    education.cell(0, 2).text = "2019"
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_benchmark_cases() -> list[BenchmarkCase]:
    """Create a small, deterministic synthetic document corpus."""
    expected = {
        "name": "Aarav Mehta",
        "email": "aarav.mehta@example.test",
        "phone": "415-555-0132",
        "skills": ["Python", "FastAPI", "PostgreSQL", "React"],
        "experience": [
            {
                "title": "Software Engineer",
                "company": "Acme Labs",
                "duration": "Jan 2020 - Dec 2022",
            }
        ],
        "education": [
            {
                "degree": "Bachelor",
                "university": "State University",
                "graduation_year": "2019",
            }
        ],
    }
    single_column = [
        "Aarav Mehta",
        "Email: aarav.mehta@example.test",
        "Phone: 415-555-0132",
        "Skills",
        "Python, FastAPI, PostgreSQL, React",
        "Experience",
        "Software Engineer | Acme Labs | Jan 2020 - Dec 2022",
        "Education",
        "Bachelor | State University | 2019",
    ]
    left_column = [
        "Aarav Mehta",
        "Email: aarav.mehta@example.test",
        "Phone: 415-555-0132",
        "Skills",
        "Python, FastAPI, PostgreSQL, React",
    ]
    right_column = [
        "Experience",
        "Software Engineer | Acme Labs | Jan 2020 - Dec 2022",
        "Education",
        "Bachelor | State University | 2019",
    ]
    return [
        BenchmarkCase(
            name="text_pdf_single_column",
            filename="synthetic-single-column.pdf",
            content=_pdf_bytes([(40, 790, single_column)]),
            expected=expected,
        ),
        BenchmarkCase(
            name="docx_experience_and_education_tables",
            filename="synthetic-tables.docx",
            content=_docx_bytes(),
            expected=expected,
        ),
        BenchmarkCase(
            name="text_pdf_two_column_layout",
            filename="synthetic-two-column.pdf",
            content=_pdf_bytes(
                [(40, 790, left_column), (315, 790, right_column)]
            ),
            expected=expected,
        ),
    ]


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _entity_key(field: str, value: Any) -> str:
    if not isinstance(value, dict):
        return _normalise(value)
    if field == "experience":
        members = ("title", "company", "duration")
    elif field == "education":
        members = ("degree", "university", "graduation_year")
    else:
        members = tuple(sorted(value))
    return "|".join(_normalise(value.get(member)) for member in members)


def _field_items(field: str, value: Any) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, list) else [value]
    return {
        _entity_key(field, item)
        for item in values
        if item is not None and _entity_key(field, item)
    }


def score_field(field: str, expected: Any, actual: Any) -> dict[str, Any]:
    expected_items = _field_items(field, expected)
    actual_items = _field_items(field, actual)
    true_positive = len(expected_items & actual_items)
    false_positive = len(actual_items - expected_items)
    false_negative = len(expected_items - actual_items)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "expected_count": len(expected_items),
        "actual_count": len(actual_items),
    }


def _aggregate_scores(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = {}
    for result in case_results:
        for field, score in result.get("fields", {}).items():
            total = totals.setdefault(
                field,
                {"true_positive": 0, "false_positive": 0, "false_negative": 0},
            )
            for key in total:
                total[key] += int(score[key])

    aggregate = {}
    for field, counts in totals.items():
        tp, fp, fn = (
            counts["true_positive"],
            counts["false_positive"],
            counts["false_negative"],
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        aggregate[field] = {
            **counts,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return aggregate


def run_benchmark(
    extractor_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Run the local pypdf/python-docx path and return aggregate field metrics."""
    environment_keys = (
        "DOCUMENT_EXTRACTION_ENGINE",
        "DOCUMENT_EXTRACTION_FALLBACK_ENGINE",
        "ENABLE_LLM_RESUME_ENRICHMENT",
        "OPENROUTER_API_KEY",
    )
    previous = {key: os.environ.get(key) for key in environment_keys}
    try:
        # Force deterministic local extraction even if a developer's .env file
        # enables Docling or a hosted model.
        os.environ["DOCUMENT_EXTRACTION_ENGINE"] = "legacy"
        os.environ["DOCUMENT_EXTRACTION_FALLBACK_ENGINE"] = "disabled"
        os.environ["ENABLE_LLM_RESUME_ENRICHMENT"] = "false"
        os.environ.pop("OPENROUTER_API_KEY", None)

        if extractor_factory is None:
            from app.services.extractor import DocumentExtractor

            extractor_factory = DocumentExtractor

        extractor = extractor_factory()
        results = []
        for case in build_benchmark_cases():
            started = time.perf_counter()
            try:
                extracted = extractor.extract_to_json(case.content, case.filename)
                elapsed_ms = (time.perf_counter() - started) * 1000
                results.append(
                    {
                        "case": case.name,
                        "status": "extracted",
                        "engine": extracted.get("document_extraction_engine"),
                        "latency_ms": round(elapsed_ms, 2),
                        "fields": {
                            field: score_field(field, expected, extracted.get(field))
                            for field, expected in case.expected.items()
                        },
                    }
                )
            except Exception as error:
                elapsed_ms = (time.perf_counter() - started) * 1000
                results.append(
                    {
                        "case": case.name,
                        "status": "error",
                        "error_type": type(error).__name__,
                        "latency_ms": round(elapsed_ms, 2),
                        "fields": {
                            field: score_field(field, expected, None)
                            for field, expected in case.expected.items()
                        },
                    }
                )

        latency_values = [item["latency_ms"] for item in results]
        return {
            "benchmark": "bluepace_synthetic_resume_extraction_v1",
            "corpus": "synthetic_only",
            "provider_calls": 0,
            "document_count": len(results),
            "aggregate_field_scores": _aggregate_scores(results),
            "latency_ms": {
                "mean": round(statistics.mean(latency_values), 2)
                if latency_values
                else 0.0,
                "max": round(max(latency_values), 2) if latency_values else 0.0,
            },
            "results": results,
            "limitations": [
                "Synthetic fixtures validate deterministic parser behaviour, not real-world CV accuracy.",
                "OCR/scanned PDFs and Docling are not measured by this benchmark.",
                "Timing is local and should not be treated as production latency.",
            ],
        }
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
