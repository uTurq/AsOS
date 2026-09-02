"""
Document parsing.

Extracts raw text from a file into a list of (unit_label, text) pairs —
one per page (PDF), slide (PPTX), or paragraph-group (DOCX/plain text).
This module only extracts text; chunking (asos.documents.chunking) and
embedding (asos.documents.embeddings) are separate steps so each is
independently testable and swappable.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass
class ParsedUnit:
    label: str | None  # e.g. "page 3", "slide 7"; None if not applicable
    text: str


class UnsupportedDocumentTypeError(ValueError):
    pass


def parse_document(path: Path) -> list[ParsedUnit]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix == ".pptx":
        return _parse_pptx(path)
    if suffix in (".txt", ".md"):
        return _parse_plain_text(path)
    raise UnsupportedDocumentTypeError(f"Don't know how to parse '{suffix}' files (path: {path.name})")


def _parse_pdf(path: Path) -> list[ParsedUnit]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    units = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            units.append(ParsedUnit(label=f"page {i}", text=text))
    return units


def _parse_docx(path: Path) -> list[ParsedUnit]:
    import docx

    document = docx.Document(str(path))
    # Group paragraphs into ~10-paragraph units rather than one unit per
    # paragraph — keeps unit count sane for long documents while still
    # giving chunking meaningful boundaries to work with.
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    units = []
    group_size = 10
    for i in range(0, len(paragraphs), group_size):
        group = paragraphs[i : i + group_size]
        units.append(ParsedUnit(label=f"paragraphs {i + 1}-{i + len(group)}", text="\n".join(group)))
    return units


def _parse_pptx(path: Path) -> list[ParsedUnit]:
    from pptx import Presentation

    presentation = Presentation(str(path))
    units = []
    for i, slide in enumerate(presentation.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    texts.append(text)
        if texts:
            units.append(ParsedUnit(label=f"slide {i}", text="\n".join(texts)))
    return units


def _parse_plain_text(path: Path) -> list[ParsedUnit]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [ParsedUnit(label=None, text=text)] if text else []
