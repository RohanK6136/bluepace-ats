"""Document-understanding service built on Docling with lazy initialization.

The service accepts in-memory uploads so FastAPI does not need to write a second
copy of the file before document conversion. Docling is the preferred engine;
the caller can fall back to the existing pypdf/python-docx path when a local
model or runtime dependency is unavailable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

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
    # One entry per non-empty exported text line. None means that Docling did
    # not provide an exact, unambiguous source-item match for that line.
    source_line_locations: list[dict | None] = field(default_factory=list)


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
                from docling.document_converter import DocumentConverter
            except Exception as error:
                raise DocumentIntelligenceError(f"Docling is unavailable: {error}") from error

            self._converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            )
        return self._converter

    @staticmethod
    def _member(value, name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _docling_source_line_locations(cls, document, raw_text: str) -> list[dict | None]:
        """Map exact exported text lines to Docling item provenance.

        Docling's provenance is attached to document items, not necessarily to
        each individual line in the flattened text export. Exact line matching
        avoids assigning a neighbouring item's page or bounding box to text
        that was reordered or reformatted during export.
        """
        lines = [line for line in str(raw_text or "").splitlines() if line.strip()]
        if not lines:
            return []

        item_locations: dict[str, list[dict]] = {}
        try:
            items = document.iterate_items()
            for entry in items:
                item = entry[0] if isinstance(entry, tuple) else entry
                item_text = cls._member(item, "text", "")
                if not isinstance(item_text, str) or not item_text.strip():
                    continue

                provenance = cls._member(item, "prov", []) or []
                if not provenance:
                    continue
                first_provenance = provenance[0]
                page_number = cls._member(first_provenance, "page_no")
                if not isinstance(page_number, int) or page_number < 1:
                    continue

                location = {
                    "source_type": "docling_item",
                    "page_number": page_number,
                }
                label = cls._member(item, "label")
                label = cls._member(label, "value", label)
                if label:
                    location["item_label"] = str(label)

                bbox = cls._member(first_provenance, "bbox")
                if bbox is not None:
                    bbox_values = {}
                    for coordinate in ("l", "t", "r", "b"):
                        value = cls._member(bbox, coordinate)
                        if isinstance(value, (int, float)):
                            bbox_values[coordinate] = float(value)
                    origin = cls._member(bbox, "coord_origin")
                    origin = cls._member(origin, "value", origin)
                    if origin:
                        bbox_values["coord_origin"] = str(origin)
                    if all(key in bbox_values for key in ("l", "t", "r", "b")):
                        location["bbox"] = bbox_values

                pages = cls._member(document, "pages", {}) or {}
                page_item = pages.get(page_number) if hasattr(pages, "get") else None
                page_size = cls._member(page_item, "size") if page_item is not None else None
                size_width = cls._member(page_size, "width") if page_size is not None else None
                size_height = cls._member(page_size, "height") if page_size is not None else None
                if (
                    isinstance(size_width, (int, float))
                    and not isinstance(size_width, bool)
                    and isinstance(size_height, (int, float))
                    and not isinstance(size_height, bool)
                    and size_width > 0
                    and size_height > 0
                ):
                    location["page_size"] = {
                        "width": float(size_width),
                        "height": float(size_height),
                    }

                for item_line in item_text.splitlines():
                    normalized = " ".join(item_line.split()).casefold()
                    if normalized:
                        item_locations.setdefault(normalized, []).append(location)
        except Exception:
            # A Docling version or item that does not expose the expected
            # structure must not make the document conversion itself fail.
            return [None for _line in lines]

        exported_counts: dict[str, int] = {}
        for line in lines:
            normalized = " ".join(line.split()).casefold()
            exported_counts[normalized] = exported_counts.get(normalized, 0) + 1

        occurrence_indexes: dict[str, int] = {}
        mapped: list[dict | None] = []
        for line in lines:
            normalized = " ".join(line.split()).casefold()
            candidates = item_locations.get(normalized, [])
            occurrence_index = occurrence_indexes.get(normalized, 0)
            occurrence_indexes[normalized] = occurrence_index + 1

            # Repeated text is only mapped when every exported occurrence has
            # a matching Docling item. Otherwise the source is ambiguous.
            if len(candidates) == exported_counts[normalized]:
                mapped.append(dict(candidates[occurrence_index]))
            elif len(candidates) == 1 and exported_counts[normalized] == 1:
                mapped.append(dict(candidates[0]))
            else:
                mapped.append(None)
        return mapped

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
            source_line_locations = self._docling_source_line_locations(
                result.document, text
            )
            if not text:
                raise DocumentIntelligenceError(
                    "Docling did not extract readable text from the document."
                )

            return DocumentIntelligenceResult(
                text=text,
                markdown=markdown,
                engine="docling",
                source_line_locations=source_line_locations,
            )
        except DocumentIntelligenceError:
            raise
        except Exception as error:
            raise DocumentIntelligenceError(f"Docling conversion failed: {error}") from error


document_intelligence_service = DocumentIntelligenceService()
