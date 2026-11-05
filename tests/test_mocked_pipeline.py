"""End-to-end decision tests driven by mocked Gemini API responses."""

from types import SimpleNamespace

import pytest

from document_extraction import DocumentExtraction
from gemini_extraction import GeminiDocumentExtractor, GeminiSettings
from validation import Submission, validate_submission


class MockModels:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error

    def get(self, *, model):
        return SimpleNamespace(name=model)

    def generate_content(self, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(parsed=self.responses.pop(0), text=None)


def run_mocked(gst_text, bank_text, gst_response=None, bank_response=None, error=None):
    client = SimpleNamespace(models=MockModels([gst_response, bank_response], error=error))
    service = GeminiDocumentExtractor(
        GeminiSettings("placeholder-test-key", "mock-model"), client=client
    )
    gst_outcome = service.extract_gst(gst_text)
    bank_outcome = service.extract_bank(bank_text)
    form = Submission(
        "Acme Demo Technologies Private Limited", "Meghana Sai", "ananya@example.test",
        "India", "27AAPFU0939F1ZV", "Acme Demo Technologies Private Limited",
        "001234567890", "HDFC0001234", True, True,
    )
    return validate_submission(
        form,
        DocumentExtraction("gst.pdf", gst_text, 1),
        DocumentExtraction("bank.pdf", bank_text, 1),
        gst_outcome,
        bank_outcome,
    )


GST_TEXT = "Legal Name: Acme Demo Technologies Private Limited\nGSTIN: 27AAPFU0939F1ZV"
BANK_TEXT = "Beneficiary: Acme Demo Technologies Private Limited\nAccount: 001234567890\nIFSC: HDFC0001234"
GST_MATCH = {
    "legal_company_name": {"value": "Acme Demo Technologies Private Limited", "excerpt": GST_TEXT.splitlines()[0]},
    "gstin": {"value": "27AAPFU0939F1ZV", "excerpt": GST_TEXT.splitlines()[1]},
}
BANK_MATCH = {
    "beneficiary_name": {"value": "Acme Demo Technologies Private Limited", "excerpt": BANK_TEXT.splitlines()[0]},
    "account_number": {"value": "001234567890", "excerpt": BANK_TEXT.splitlines()[1]},
    "ifsc": {"value": "HDFC0001234", "excerpt": BANK_TEXT.splitlines()[2]},
}


def test_mocked_api_approval_and_leading_zero_identifier():
    result = run_mocked(GST_TEXT, BANK_TEXT, GST_MATCH, BANK_MATCH)
    assert result.status == "Approved"
    account = next(row for row in result.comparisons if row.field == "Bank account number")
    assert account.document_value == "001234567890"


@pytest.mark.parametrize(
    ("gst_response", "bank_response", "expected_result"),
    [
        (
            {**GST_MATCH, "gstin": {"value": "29AAPFU0939F1ZR", "excerpt": GST_TEXT.splitlines()[1]}},
            BANK_MATCH,
            "Unsupported evidence",
        ),
        (
            {**GST_MATCH, "gstin": {"value": None, "excerpt": None}},
            BANK_MATCH,
            "Missing in document",
        ),
        (
            {**GST_MATCH, "gstin": {"value": "27AAPFU0939F1ZV", "excerpt": "not verbatim"}},
            BANK_MATCH,
            "Unsupported evidence",
        ),
    ],
)
def test_mocked_api_non_approval_cases(gst_response, bank_response, expected_result):
    result = run_mocked(GST_TEXT, BANK_TEXT, gst_response, bank_response)
    assert result.status == "Pending"
    assert expected_result in {row.result for row in result.comparisons}


def test_mocked_api_identifier_and_name_mismatches():
    gst_text = "Legal Name: Acme Demo Systems Private Limited\nGSTIN: 29AAPFU0939F1ZR"
    gst_response = {
        "legal_company_name": {"value": "Acme Demo Systems Private Limited", "excerpt": gst_text.splitlines()[0]},
        "gstin": {"value": "29AAPFU0939F1ZR", "excerpt": gst_text.splitlines()[1]},
    }
    result = run_mocked(gst_text, BANK_TEXT, gst_response, BANK_MATCH)
    assert result.status == "Pending"
    checks = {row.field: row.result for row in result.comparisons}
    assert checks["Legal company name"] == "Human review required"
    assert checks["GSTIN"] == "Mismatch"


def test_mocked_api_failure_is_pending():
    result = run_mocked(GST_TEXT, BANK_TEXT, error=TimeoutError("simulated timeout"))
    assert result.status == "Pending"
    assert any("Gemini could not extract" in reason for reason in result.reasons)
