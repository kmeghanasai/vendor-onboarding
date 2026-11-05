import pytest

from document_extraction import extract_pdf_text


pymupdf = pytest.importorskip("pymupdf")


def test_extracts_actual_embedded_pdf_text():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "GST registration evidence")
    pdf_bytes = document.tobytes()
    document.close()

    result = extract_pdf_text(pdf_bytes, "gst.pdf")

    assert result.error is None
    assert result.page_count == 1
    assert "GST registration evidence" in result.text


def test_invalid_pdf_is_reported_as_unreadable():
    result = extract_pdf_text(b"not a pdf", "bad.pdf")
    assert not result.is_readable
    assert "not a readable PDF" in result.error
