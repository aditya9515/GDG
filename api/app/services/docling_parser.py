from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedDocument:
    markdown: str
    structured: dict
    warnings: list[str] = field(default_factory=list)
    detected_languages: list[str] = field(default_factory=list)
    ocr_used: bool = False


class DoclingParserService:
    """Optional Docling adapter with graceful fallback for local/dev reliability."""

    def parse_text(self, text: str, source_kind: str = "MANUAL_TEXT") -> ParsedDocument:
        return ParsedDocument(
            markdown=text.strip(),
            structured={"source_kind": source_kind, "chunks": [{"type": "text", "text": text.strip()}]},
            detected_languages=[self._infer_language(text)],
            ocr_used=False,
        )

    def parse_bytes(self, filename: str, content_type: str, content: bytes) -> ParsedDocument:
        try:
            from docling.document_converter import DocumentConverter  # type: ignore
        except Exception as exc:
            text = self._decode_fallback(content, filename, content_type)
            return ParsedDocument(
                markdown=text,
                structured={"filename": filename, "content_type": content_type, "fallback": True},
                warnings=[f"Docling unavailable; used fallback parser: {type(exc).__name__}: {exc}"],
                detected_languages=[self._infer_language(text)],
                ocr_used=False,
            )

        try:
            converter = DocumentConverter()
            suffix = Path(filename).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                result = converter.convert(str(tmp_path))
            finally:
                tmp_path.unlink(missing_ok=True)
            document = result.document
            markdown = document.export_to_markdown()
            structured = json.loads(document.export_to_json())
            return ParsedDocument(
                markdown=markdown,
                structured=structured,
                warnings=[],
                detected_languages=[self._infer_language(markdown)],
                ocr_used=content_type.startswith("image/") or content_type == "application/pdf",
            )
        except Exception as exc:
            text = self._decode_fallback(content, filename, content_type)
            return ParsedDocument(
                markdown=text,
                structured={"filename": filename, "content_type": content_type, "fallback": True},
                warnings=[f"Docling parse failed; used fallback parser: {type(exc).__name__}: {exc}"],
                detected_languages=[self._infer_language(text)],
                ocr_used=False,
            )

    def _decode_fallback(self, content: bytes, filename: str, content_type: str) -> str:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return f"{filename} ({content_type}) could not be decoded as text. Use Docling/OCR runtime for full parsing."

    def _infer_language(self, value: str) -> str:
        for char in value:
            if "\u0900" <= char <= "\u097F":
                return "hi"
        return "en"
