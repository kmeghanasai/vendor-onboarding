from datetime import datetime, timezone

from document_extraction import DocumentExtraction
from gemini_extraction import BankDocumentFields, EvidenceField, ExtractionOutcome, GSTDocumentFields
from policy import load_blocked_vendors
from run_history import make_run_record, prior_approvals
from validation import (
    PriorApproval,
    Submission,
    account_fingerprint,
    is_valid_gstin,
    validate_submission,
)


def evidence(value, line):
    return EvidenceField(value=value, excerpt=line)


def complete_case(
    *,
    legal_name="Acme Demo Technologies Private Limited",
    gstin="27AAPFU0939F1ZV",
    beneficiary_name="Acme Demo Technologies Private Limited",
    account_number="001234567890",
    ifsc="HDFC0001234",
):
    gst_text = f"Legal Name: {legal_name}\nGSTIN: {gstin}"
    bank_text = (
        f"Beneficiary: {beneficiary_name}\nAccount: {account_number}\nIFSC: {ifsc}"
    )
    submission = Submission(
        legal_name,
        "Meghana Sai",
        "meghana@example.test",
        "India",
        gstin,
        beneficiary_name,
        account_number,
        ifsc,
        True,
        True,
    )
    gst = ExtractionOutcome(data=GSTDocumentFields(
        legal_company_name=evidence(legal_name, gst_text.splitlines()[0]),
        gstin=evidence(gstin, gst_text.splitlines()[1]),
    ))
    bank = ExtractionOutcome(data=BankDocumentFields(
        beneficiary_name=evidence(beneficiary_name, bank_text.splitlines()[0]),
        account_number=evidence(account_number, bank_text.splitlines()[1]),
        ifsc=evidence(ifsc, bank_text.splitlines()[2]),
    ))
    return submission, DocumentExtraction("gst.pdf", gst_text, 1), DocumentExtraction(
        "bank.pdf", bank_text, 1
    ), gst, bank


def decide(case, **kwargs):
    return validate_submission(*case, **kwargs)


def test_gstin_checksum_accepts_demo_ids_and_rejects_wrong_check_digit():
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert is_valid_gstin("29AAPFU0939F1ZR")
    assert is_valid_gstin("27ABCDE1234F1Z0")
    assert is_valid_gstin("07ABCDE1234F1Z2")
    assert not is_valid_gstin("27AAPFU0939F1ZA")


def test_invalid_checksum_is_pending_with_correction():
    result = decide(complete_case(gstin="27AAPFU0939F1ZA"))
    assert result.status == "Pending"
    assert "GSTIN checksum is invalid." in result.reasons
    assert "GSTIN_CHECKSUM_INVALID" in result.reason_codes


def test_exact_document_supported_blocklist_match_is_rejected():
    case = complete_case(
        legal_name="Northstar Demo Supplies Private Limited",
        gstin="29AAPFU0939F1ZR",
        beneficiary_name="Northstar Demo Supplies Private Limited",
        account_number="007700660055",
        ifsc="SBIN0002468",
    )
    result = decide(case, blocked_vendors=load_blocked_vendors())
    assert result.status == "Rejected"
    assert "explicit internal policy" in result.reasons[0]
    assert result.primary_code == "POLICY_BLOCKED_VENDOR"


def test_blocklist_does_not_reject_without_matching_document_evidence():
    form, gst_doc, bank_doc, gst, bank = complete_case(gstin="29AAPFU0939F1ZR")
    mismatched_text = "Legal Name: Acme Demo Technologies Private Limited\nGSTIN: 27AAPFU0939F1ZV"
    gst_doc = DocumentExtraction("gst.pdf", mismatched_text, 1)
    gst = ExtractionOutcome(data=GSTDocumentFields(
        legal_company_name=evidence(form.legal_name, mismatched_text.splitlines()[0]),
        gstin=evidence("27AAPFU0939F1ZV", mismatched_text.splitlines()[1]),
    ))
    result = validate_submission(
        form, gst_doc, bank_doc, gst, bank, blocked_vendors=load_blocked_vendors()
    )
    assert result.status == "Pending"
    assert not any("blocked" in reason.lower() for reason in result.reasons)


def test_changed_bank_details_after_prior_approval_are_pending():
    prior = PriorApproval(
        gstin="27AAPFU0939F1ZV",
        account_fingerprint=account_fingerprint("001234567890"),
        ifsc="HDFC0001234",
    )
    result = decide(
        complete_case(account_number="009999888877", ifsc="ICIC0005678"),
        prior_approvals=(prior,),
    )
    assert result.status == "Pending"
    assert "BANK_DETAILS_CHANGED" in result.reason_codes
    assert any("previous Approved run" in reason for reason in result.reasons)


def test_unchanged_bank_details_after_prior_approval_remain_approved():
    prior = PriorApproval(
        gstin="27AAPFU0939F1ZV",
        account_fingerprint=account_fingerprint("001234567890"),
        ifsc="HDFC0001234",
    )
    result = decide(complete_case(), prior_approvals=(prior,))
    assert result.status == "Approved"
    assert result.primary_code == "ALL_CHECKS_PASSED"


def test_account_approved_for_different_gstin_requires_fraud_review():
    prior = PriorApproval(
        gstin="27AAPFU0939F1ZV",
        account_fingerprint=account_fingerprint("001234567890"),
        ifsc="HDFC0001234",
    )
    current = complete_case(
        legal_name="Bluebird Demo Services Private Limited",
        gstin="07ABCDE1234F1Z2",
        beneficiary_name="Bluebird Demo Services Private Limited",
        account_number="001234567890",
        ifsc="HDFC0001234",
    )
    result = decide(current, prior_approvals=(prior,))
    assert result.status == "Pending"
    assert result.primary_code == "BANK_ACCOUNT_REUSED"
    assert any("different GSTIN" in reason for reason in result.reasons)
    assert all(row.result == "Match" for row in result.comparisons)


def test_evidence_provenance_is_verified_for_every_happy_path_field():
    result = decide(complete_case())
    assert len(result.evidence) == 5
    assert all(row.result == "Verified excerpt" for row in result.evidence)
    assert {row.document for row in result.evidence} == {
        "GST registration",
        "Bank proof",
    }


def test_history_masks_account_and_rehydrates_only_approved_records():
    case = complete_case()
    result = decide(case)
    record = make_run_record(
        case[0], result, 1, datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    )
    assert record["account_display"] == "********7890"
    assert record["primary_code"] == "ALL_CHECKS_PASSED"
    assert "001234567890" not in repr(record)
    account_evidence = next(
        row for row in record["evidence"] if row["Field"] == "Bank account number"
    )
    assert "********7890" in account_evidence["Supporting excerpt"]
    approvals = prior_approvals([record])
    assert len(approvals) == 1
    assert approvals[0].account_fingerprint == account_fingerprint("001234567890")


def test_history_masks_account_number_embedded_in_any_evidence_excerpt():
    case = complete_case()
    submission, gst_doc, _, gst, _ = case
    bank_text = (
        "Beneficiary: Acme Demo Technologies Private Limited, Account: 001234567890\n"
        "Account: 001234567890\nIFSC: HDFC0001234"
    )
    bank_doc = DocumentExtraction("bank.pdf", bank_text, 1)
    bank = ExtractionOutcome(data=BankDocumentFields(
        beneficiary_name=evidence(
            "Acme Demo Technologies Private Limited", bank_text.splitlines()[0]
        ),
        account_number=evidence("001234567890", bank_text.splitlines()[1]),
        ifsc=evidence("HDFC0001234", bank_text.splitlines()[2]),
    ))
    result = validate_submission(submission, gst_doc, bank_doc, gst, bank)
    record = make_run_record(
        submission, result, 1, datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    )

    beneficiary_evidence = next(
        row for row in record["evidence"] if row["Field"] == "Bank beneficiary name"
    )
    assert "001234567890" not in beneficiary_evidence["Supporting excerpt"]
    assert "********7890" in beneficiary_evidence["Supporting excerpt"]
    ifsc_evidence = next(
        row for row in record["evidence"] if row["Field"] == "IFSC"
    )
    assert ifsc_evidence["Supporting excerpt"] == "IFSC: HDFC0001234"
