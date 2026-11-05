"""Text extraction for uploaded PDF evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentExtraction:
    filename: str
    text: str = ""
    page_count: int = 0
    error: str | None = None

    @property
    def is_readable(self) -> bool:
        return self.error is None and bool(self.text.strip())


def extract_pdf_text(pdf_bytes: bytes, filename: str) -> DocumentExtraction:
    """Extract real embedded text from PDF bytes with PyMuPDF.

    Scanned/image-only PDFs intentionally produce no text and are treated as
    unreadable for this text-only milestone. No OCR or inferred values are used.
    """
    if not pdf_bytes:
        return DocumentExtraction(filename=filename, error="The uploaded file is empty.")

    try:
        import pymupdf
    except ImportError:
        return DocumentExtraction(
            filename=filename,
            error="PyMuPDF is not installed. Install the dependencies and try again.",
        )

    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            page_count = document.page_count
            text = "\n".join(page.get_text("text") for page in document).strip()
    except Exception as exc:
        return DocumentExtraction(
            filename=filename,
            error=f"The file is not a readable PDF ({type(exc).__name__}).",
        )

    if page_count == 0:
        return DocumentExtraction(filename=filename, error="The PDF has no pages.")
    if not text:
        return DocumentExtraction(
            filename=filename,
            page_count=page_count,
            error="No embedded text was found. Upload a text-based PDF; image-only scans are not supported yet.",
        )
    return DocumentExtraction(filename=filename, text=text, page_count=page_count)
