import csv
import io
import json

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app import config
from app.graph.errors import SourceUnreadable
from app.graph.text import clean

ROWS_PER_BLOCK = 20
KINDS = {
    ".pdf": "pdf",
    ".csv": "csv",
    ".json": "json",
    ".md": "text",
    ".markdown": "text",
    ".txt": "text",
}


def detect_kind(filename: str) -> str:
    dot = filename.rfind(".")
    kind = KINDS.get(filename[dot:].lower()) if dot >= 0 else None
    if not kind:
        raise SourceUnreadable("Unsupported file type")
    return kind


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SourceUnreadable("File is not valid UTF-8 text")


def _rows_to_text(rows: list[dict]) -> str:
    lines = [
        "; ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, ""))
        for row in rows
    ]
    blocks = [
        "\n".join(lines[i : i + ROWS_PER_BLOCK])
        for i in range(0, len(lines), ROWS_PER_BLOCK)
    ]
    return "\n\n".join(blocks)


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise SourceUnreadable("PDF is encrypted")
        if len(reader.pages) > config.MAX_PDF_PAGES:
            raise SourceUnreadable("PDF has too many pages")
        return "\n\n".join(p.extract_text() or "" for p in reader.pages)
    except SourceUnreadable:
        raise
    except (PyPdfError, ValueError, KeyError, OSError):
        raise SourceUnreadable("PDF could not be read")


def parse(filename: str, data: bytes) -> tuple[str, str]:
    """Returns (kind, text). Raises SourceUnreadable."""
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise SourceUnreadable("File is too large")
    kind = detect_kind(filename)
    if kind == "pdf":
        text = _pdf_text(data)
    elif kind == "csv":
        rows = list(csv.DictReader(io.StringIO(_decode(data))))
        text = _rows_to_text(rows)
    elif kind == "json":
        try:
            rows = json.loads(_decode(data))
        except ValueError:
            raise SourceUnreadable("File is not valid JSON")
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not all(
            isinstance(r, dict) for r in rows
        ):
            raise SourceUnreadable("JSON must be a list of objects")
        text = _rows_to_text(rows)
    else:
        text = _decode(data)
    text = clean(text).strip()
    if not text:
        raise SourceUnreadable("File has no readable text")
    return kind, text
