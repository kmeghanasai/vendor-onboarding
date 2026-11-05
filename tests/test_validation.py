from document_extraction import DocumentExtraction
from gemini_extraction import (
    BankDocumentFields,
    EvidenceField,
    ExtractionOutcome,
    GSTDocumentFields,
)
from validation import Submission, mask_account, validate_submission


GST_TEXT = "Legal Name: Acme Demo Technologies Private Limited\nGSTIN: 27AAPFU0939F1ZV"
BANK_TEXT = (
    "Beneficiary Name: Acme Demo Technologies Private Limited\n"
    "Account Number: 001234567890\nIFSC: HDFC0001234"
)


def submission(**overrides):
    values = {
        "legal_name": "Acme Demo Technologies Private Limited",
        "contact_name": "Meghana Sai",
        "contact_email": "ananya@example.test",
        "country": "India",
        "gstin": "27AAPFU0939F1ZV",
        "beneficiary_name": "Acme Demo Technologies Private Limited",
        "account_number": "001234567890",
        "ifsc": "HDFC0001234",
        "has_gst_pdf": True,
        "has_bank_pdf": True,
    }
    values.update(overrides)
    return Submission(**values)


def document(name, text):
    return DocumentExtraction(filename=name, text=text, page_count=1)


def field(value, excerpt):
    return EvidenceField(value=value, excerpt=excerpt)


def outcomes(gst_text=GST_TEXT, bank_text=BANK_TEXT):
    gst = GSTDocumentFields(
        legal_company_name=field("Acme Demo Technologies Private Limited", gst_text.splitlines()[0]),
        gstin=field("27AAPFU0939F1ZV", gst_text.splitlines()[1]),
    )
    bank = BankDocumentFields(
        beneficiary_name=field("Acme Demo Technologies Private Limited", bank_text.splitlines()[0]),
        account_number=field("001234567890", bank_text.splitlines()[1]),
        ifsc=field("HDFC0001234", bank_text.splitlines()[2]),
    )
    return ExtractionOutcome(data=gst), ExtractionOutcome(data=bank)


def validate(gst_outcome=None, bank_outcome=None, form=None, gst_text=GST_TEXT, bank_text=BANK_TEXT):
    if gst_outcome is None or bank_outcome is None:
        default_gst, default_bank = outcomes(gst_text, bank_text)
        gst_outcome = gst_outcome or default_gst
        bank_outcome = bank_outcome or default_bank
    return validate_submission(
        form or submission(), document("gst.pdf", gst_text), document("bank.pdf", bank_text),
        gst_outcome, bank_outcome,
    )


def test_matching_supported_fields_are_approved():
    result = validate()
    assert result.status == "Approved"
    assert all(row.result == "Match" for row in result.comparisons)
    assert "not government registration" in result.follow_up


def test_name_and_identifier_mismatches_are_pending():
    gst_text = "Legal Name: Acme Demo Systems Private Limited\nGSTIN: 29AAPFU0939F1ZR"
    gst = GSTDocumentFields(
        legal_company_name=field("Acme Demo Systems Private Limited", gst_text.splitlines()[0]),
        gstin=field("29AAPFU0939F1ZR", gst_text.splitlines()[1]),
    )
    result = validate(ExtractionOutcome(data=gst), outcomes()[1], gst_text=gst_text)
    assert result.status == "Pending"
    checks = {row.field: row.result for row in result.comparisons}
    assert checks["Legal company name"] == "Human review required"
    assert checks["GSTIN"] == "Mismatch"


def test_null_extracted_field_is_pending():
    gst, bank = outcomes()
    bank_data = bank.data.model_copy(
        update={"ifsc": EvidenceField(value=None, excerpt=None)}
    )
    result = validate(gst, ExtractionOutcome(data=bank_data))
    assert result.status == "Pending"
    assert next(row for row in result.comparisons if row.field == "IFSC").result == "Missing in document"


def test_non_verbatim_excerpt_is_unsupported_and_pending():
    gst, bank = outcomes()
    gst_data = gst.data.model_copy(
        update={"gstin": field("27AAPFU0939F1ZV", "GSTIN claimed without verbatim source")}
    )
    result = validate(ExtractionOutcome(data=gst_data), bank)
    assert result.status == "Pending"
    assert next(row for row in result.comparisons if row.field == "GSTIN").result == "Unsupported evidence"


def test_leading_zero_account_number_is_preserved_and_masked():
    result = validate()
    account = next(row for row in result.comparisons if row.field == "Bank account number")
    assert account.document_value == "001234567890"
    assert account.result == "Match"
    assert mask_account(account.document_value) == "********7890"


def test_api_failure_can_never_approve():
    result = validate(ExtractionOutcome(error="Gemini API failed; retry."), outcomes()[1])
    assert result.status == "Pending"
    assert any("Gemini API failed" in reason for reason in result.reasons)


def test_invalid_input_format_is_pending_not_rejected():
    result = validate(form=submission(contact_email="invalid", gstin="invalid", ifsc="invalid"))
    assert result.status == "Pending"
    assert "Correct the invalid form values" in result.follow_up
