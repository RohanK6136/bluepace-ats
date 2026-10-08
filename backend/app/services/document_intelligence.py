"""Document-understanding service built on Docling with lazy initialization.

The service accepts in-memory uploads so FastAPI does not need to write a second
copy of the file before document conversion. Docling is the preferred engine;
the caller can fall back to the existing pypdf/python-docx path when a local
model or runtime dependency is unavailable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from io import BytesIO

from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES, SUPPORTED_DOCUMENT_EXTENSIONS

load_dotenv()


class DocumentIntelligenceError(ValueError):
    """Raised when Docling cannot convert an uploaded document."""


@dataclass(frozen=True)
class DocumentIntelligenceResult:
    text: str
    markdown: str
    engine: str


class DocumentIntelligenceService:
    def __init__(self) -> None:
        configured = os.getenv("DOCUMENT_EXTRACTION_ENGINE", "docling").strip().lower()
        self.engine = configured or "docling"
        self._converter = None

    @property
    def enabled(self) -> bool:
        return self.engine not in {"legacy", "fallback", "pypdf", "python-docx", "disabled", "off"}

    def _get_converter(self):
        if self._converter is None:
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import HeadingHierarchyOptions, PdfPipelineOptions
                from docling.document_converter import DocumentConverter, PdfFormatOption
            except Exception as error:
                raise DocumentIntelligenceError(f"Docling is unavailable: {error}") from error

            pipeline_options = PdfPipelineOptions(
                do_ocr=os.getenv("DOCLING_DO_OCR", "true").strip().lower() == "true",
                do_table_structure=os.getenv("DOCLING_DO_TABLE_STRUCTURE", "true").strip().lower() == "true",
                use_reading_order_separators=os.getenv("DOCLING_READING_ORDER_SEPARATORS", "true").strip().lower() == "true",
            )
            try:
                pipeline_options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
            except Exception:
                pass

            self._converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                },
            )
        return self._converter

    def extract(self, file_content: bytes, filename: str) -> DocumentIntelligenceResult:
        if not self.enabled:
            raise DocumentIntelligenceError("Docling extraction is disabled by configuration.")

        if len(file_content) > MAX_DOCUMENT_SIZE_BYTES:
            raise DocumentIntelligenceError("Document exceeds the 5 MB upload limit.")

        suffix = os.path.splitext(filename or "")[1].lower()
        if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise DocumentIntelligenceError("Only PDF and DOCX documents are supported.")

        try:
            from docling.datamodel.base_models import DocumentStream

            converter = self._get_converter()
            source = DocumentStream(name=filename or f"document{suffix}", stream=BytesIO(file_content))
            result = converter.convert(
                source,
                raises_on_error=True,
                max_file_size=MAX_DOCUMENT_SIZE_BYTES,
            )
            if result.document is None:
                raise DocumentIntelligenceError("Docling returned no document.")

            text = (result.document.export_to_text() or "").strip()
            markdown = (result.document.export_to_markdown() or "").strip()
            if not text:
                raise DocumentIntelligenceError(
                    "Docling did not extract readable text from the document."
                )

            return DocumentIntelligenceResult(
                text=text,
                markdown=markdown,
                engine="docling",
            )
        except DocumentIntelligenceError:
            raise
        except Exception as error:
            raise DocumentIntelligenceError(f"Docling conversion failed: {error}") from error


document_intelligence_service = DocumentIntelligenceService()
