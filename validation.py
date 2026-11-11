"""Deterministic submission validation and form-to-document cross-checking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re
import unicodedata

from document_extraction import DocumentExtraction
from gemini_extraction import (
    BankDocumentFields,
    EvidenceField,
    ExtractionOutcome,
    GSTDocumentFields,
)


GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ACCOUNT_PATTERN = re.compile(r"^[0-9]{6,18}$")
ACCOUNT_IN_TEXT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:\d[\s-]?){5,17}\d(?![A-Za-z0-9])"
)
BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class Submission:
    legal_name: str
    contact_name: str
    contact_email: str
    country: str
    gstin: str
    beneficiary_name: str
    account_number: str
    ifsc: str
    has_gst_pdf: bool
    has_bank_pdf: bool


@dataclass(frozen=True)
class PriorApproval:
    gstin: str
    account_fingerprint: str
    ifsc: str


@dataclass(frozen=True)
class ComparisonRow:
    field: str
    submitted_value: str | None
    document_value: str | None
    result: str


@dataclass(frozen=True)
class EvidenceRow:
    field: str
    document: str
    extracted_value: str | None
    excerpt: str | None
    result: str


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reasons: tuple[str, ...]
    follow_up: str
    comparisons: tuple[ComparisonRow, ...]
    reason_codes: tuple[str, ...] = ()
    evidence: tuple[EvidenceRow, ...] = ()

    @property
    def primary_code(self) -> str:
        return self.reason_codes[0] if self.reason_codes else "UNCLASSIFIED"


def with_operational_pending(
    result: ValidationResult,
    code: str,
    reason: str,
    action: str,
) -> ValidationResult:
    """Prevent approval when a required operational control could not complete."""
    if code in result.reason_codes:
        return result
    if result.status == "Rejected":
        return result
    if result.status == "Approved":
        reasons = (reason,)
        reason_codes = (code,)
        follow_up = f"Next steps: {action}"
    else:
        reasons = (*result.reasons, reason)
        reason_codes = (*result.reason_codes, code)
        separator = " " if result.follow_up.endswith((".", ":")) else ". "
        follow_up = f"{result.follow_up}{separator}{action}"
    return ValidationResult(
        "Pending",
        reasons,
        follow_up,
        result.comparisons,
        reason_codes,
        result.evidence,
    )


def normalize_name(value: str) -> str:
    """Normalize case, punctuation, and whitespace only; never fuzzy-match."""
    casefolded = value.casefold()
    punctuation_as_space = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in casefolded
    )
    return " ".join(punctuation_as_space.split())


def normalize_gstin(value: str) -> str:
    return "".join(value.split()).upper()


def normalize_account(value: str) -> str:
    return re.sub(r"[\s-]", "", value)


def normalize_ifsc(value: str) -> str:
    return "".join(value.split()).upper()


def account_fingerprint(value: str) -> str:
    """Create a one-way comparison token; raw account numbers are not stored in history."""
    return hashlib.sha256(normalize_account(value).encode("utf-8")).hexdigest()


def mask_account(value: str | None) -> str:
    if not value:
        return "Not available"
    compact = normalize_account(value)
    if len(compact) <= 4:
        return "*" * len(compact)
    return "*" * (len(compact) - 4) + compact[-4:]


def mask_account_text(value: str | None) -> str:
    """Mask account-like digit sequences before evidence text reaches the UI or history."""
    if not value:
        return "Not available"
    return ACCOUNT_IN_TEXT_PATTERN.sub(
        lambda match: mask_account(match.group(0)),
        value,
    )


def is_valid_gstin(value: str) -> bool:
    """Validate the GSTIN structure and base-36 checksum."""
    gstin = normalize_gstin(value)
    if not GSTIN_PATTERN.fullmatch(gstin):
        return False
    factor = 2
    total = 0
    for character in reversed(gstin[:14]):
        product = BASE36.index(character) * factor
        total += product // 36 + product % 36
        factor = 1 if factor == 2 else 2
    expected = BASE36[(36 - total % 36) % 36]
    return gstin[-1] == expected


def _supported_evidence(field: EvidenceField, document_text: str, normalizer) -> bool:
    if field.value is None or field.excerpt is None:
        return False
    if field.excerpt not in document_text:
        return False
    return normalizer(field.value) in normalizer(field.excerpt)


def _comparison_result(comparisons: Sequence[ComparisonRow], field: str) -> str | None:
    return next((row.result for row in comparisons if row.field == field), None)


def validate_submission(
    submission: Submission,
    gst_document: DocumentExtraction | None,
    bank_document: DocumentExtraction | None,
    gst_extraction: ExtractionOutcome | None = None,
    bank_extraction: ExtractionOutcome | None = None,
    *,
    blocked_vendors: Mapping[str, str] | None = None,
    prior_approvals: Sequence[PriorApproval] = (),
) -> ValidationResult:
    """Apply evidence checks, history controls, and explicit local policy rules."""
    reasons: list[str] = []
    reason_codes: list[str] = []
    actions: list[str] = []
    blocked_vendors = blocked_vendors or {}

    def add_finding(code: str, message: str, action: str | None = None) -> None:
        reason_codes.append(code)
        reasons.append(message)
        if action:
            actions.append(action)

    required = {
        "Legal company name": submission.legal_name,
        "Contact name": submission.contact_name,
        "Contact email": submission.contact_email,
        "Country": submission.country,
        "GSTIN": submission.gstin,
        "Bank beneficiary name": submission.beneficiary_name,
        "Bank account number": submission.account_number,
        "IFSC": submission.ifsc,
    }
    missing = [label for label, value in required.items() if not value.strip()]
    for label in missing:
        add_finding(
            "REQUIRED_FIELD_MISSING",
            f"{label} is required.",
            "Complete every required form field.",
        )

    if submission.country and submission.country != "India":
        add_finding(
            "COUNTRY_NOT_SUPPORTED",
            "Country must be India for this milestone.",
            "Select India and resubmit.",
        )
    if submission.contact_email and not EMAIL_PATTERN.fullmatch(submission.contact_email.strip()):
        add_finding(
            "EMAIL_FORMAT_INVALID",
            "Contact email is not in a valid email format.",
            "Correct the invalid form values and resubmit.",
        )
    if submission.gstin:
        gstin = normalize_gstin(submission.gstin)
        if not GSTIN_PATTERN.fullmatch(gstin):
            add_finding(
                "GSTIN_FORMAT_INVALID",
                "GSTIN must use the valid 15-character GSTIN format.",
                "Correct the invalid form values and resubmit.",
            )
        elif not is_valid_gstin(gstin):
            add_finding(
                "GSTIN_CHECKSUM_INVALID",
                "GSTIN checksum is invalid.",
                "Correct the invalid form values and resubmit.",
            )
    if submission.ifsc and not IFSC_PATTERN.fullmatch(normalize_ifsc(submission.ifsc)):
        add_finding(
            "IFSC_FORMAT_INVALID",
            "IFSC must contain four letters, zero, then six letters or digits.",
            "Correct the invalid form values and resubmit.",
        )
    if (
        submission.account_number
        and not ACCOUNT_PATTERN.fullmatch(normalize_account(submission.account_number))
    ):
        add_finding(
            "ACCOUNT_FORMAT_INVALID",
            "Bank account number must contain 6 to 18 digits only.",
            "Correct the invalid form values and resubmit.",
        )

    if not submission.has_gst_pdf:
        add_finding(
            "GST_DOCUMENT_MISSING",
            "GST registration PDF is required.",
            "Upload a text-based GST registration PDF.",
        )
    elif gst_document is None or not gst_document.is_readable:
        detail = gst_document.error if gst_document else "The document was not processed."
        add_finding(
            "GST_DOCUMENT_UNREADABLE",
            f"GST registration PDF is unreadable: {detail}",
            "Replace the GST registration PDF with a readable text-based PDF.",
        )
    if not submission.has_bank_pdf:
        add_finding(
            "BANK_DOCUMENT_MISSING",
            "Bank proof PDF is required.",
            "Upload a text-based bank proof PDF.",
        )
    elif bank_document is None or not bank_document.is_readable:
        detail = bank_document.error if bank_document else "The document was not processed."
        add_finding(
            "BANK_DOCUMENT_UNREADABLE",
            f"Bank proof PDF is unreadable: {detail}",
            "Replace the bank proof PDF with a readable text-based PDF.",
        )

    if gst_document and gst_document.is_readable:
        if gst_extraction is None:
            add_finding(
                "GST_EXTRACTION_NOT_COMPLETED",
                "GST document field extraction was not completed.",
                "Configure Gemini and retry GST document extraction.",
            )
        elif gst_extraction.error:
            add_finding(
                "GST_EXTRACTION_FAILED",
                gst_extraction.error,
                "Resolve the Gemini configuration or service error and resubmit.",
            )
    if bank_document and bank_document.is_readable:
        if bank_extraction is None:
            add_finding(
                "BANK_EXTRACTION_NOT_COMPLETED",
                "Bank document field extraction was not completed.",
                "Configure Gemini and retry bank document extraction.",
            )
        elif bank_extraction.error:
            add_finding(
                "BANK_EXTRACTION_FAILED",
                bank_extraction.error,
                "Resolve the Gemini configuration or service error and resubmit.",
            )

    gst_data = gst_extraction.data if gst_extraction else None
    bank_data = bank_extraction.data if bank_extraction else None
    if gst_data is not None and not isinstance(gst_data, GSTDocumentFields):
        add_finding("GST_SCHEMA_INVALID", "GST extraction returned an unexpected schema.")
        gst_data = None
    if bank_data is not None and not isinstance(bank_data, BankDocumentFields):
        add_finding("BANK_SCHEMA_INVALID", "Bank extraction returned an unexpected schema.")
        bank_data = None

    checks = (
        (
            "Legal company name",
            submission.legal_name,
            gst_data.legal_company_name if gst_data else None,
            gst_document,
            "GST registration",
            normalize_name,
            True,
        ),
        (
            "GSTIN",
            submission.gstin,
            gst_data.gstin if gst_data else None,
            gst_document,
            "GST registration",
            normalize_gstin,
            False,
        ),
        (
            "Bank beneficiary name",
            submission.beneficiary_name,
            bank_data.beneficiary_name if bank_data else None,
            bank_document,
            "Bank proof",
            normalize_name,
            True,
        ),
        (
            "Bank account number",
            submission.account_number,
            bank_data.account_number if bank_data else None,
            bank_document,
            "Bank proof",
            normalize_account,
            False,
        ),
        (
            "IFSC",
            submission.ifsc,
            bank_data.ifsc if bank_data else None,
            bank_document,
            "Bank proof",
            normalize_ifsc,
            False,
        ),
    )
    comparisons: list[ComparisonRow] = []
    evidence_rows: list[EvidenceRow] = []
    for (
        label,
        submitted,
        evidence,
        document,
        document_label,
        normalizer,
        is_name,
    ) in checks:
        if evidence is None or document is None or not document.is_readable:
            comparisons.append(ComparisonRow(label, submitted or None, None, "Not checked"))
            evidence_rows.append(
                EvidenceRow(label, document_label, None, None, "Not available")
            )
            continue
        if evidence.value is None:
            comparisons.append(
                ComparisonRow(label, submitted or None, None, "Missing in document")
            )
            evidence_rows.append(
                EvidenceRow(label, document_label, None, evidence.excerpt, "Missing")
            )
            add_finding(
                "DOCUMENT_FIELD_MISSING",
                f"{label} is missing from the document extraction.",
                f"Provide document evidence that clearly shows the {label.lower()}.",
            )
            continue

        supported = _supported_evidence(evidence, document.text, normalizer)
        evidence_rows.append(
            EvidenceRow(
                label,
                document_label,
                evidence.value,
                evidence.excerpt,
                "Verified excerpt" if supported else "Unsupported excerpt",
            )
        )
        if not supported:
            comparisons.append(
                ComparisonRow(label, submitted or None, None, "Unsupported evidence")
            )
            add_finding(
                "UNSUPPORTED_EVIDENCE",
                f"{label} lacks an exact supporting excerpt from the uploaded document.",
                f"Provide clear document evidence for the {label.lower()}.",
            )
            continue
        if normalizer(submitted) == normalizer(evidence.value):
            comparisons.append(ComparisonRow(label, submitted, evidence.value, "Match"))
            continue

        result = "Human review required" if is_name else "Mismatch"
        comparisons.append(ComparisonRow(label, submitted, evidence.value, result))
        if is_name:
            add_finding(
                "NAME_REVIEW_REQUIRED",
                f"{label} differs after case, punctuation, and whitespace normalization.",
                f"Ask a reviewer to resolve the {label.lower()} discrepancy.",
            )
        else:
            add_finding(
                "FIELD_MISMATCH",
                f"{label} does not match the uploaded document.",
                f"Correct the submitted {label.lower()} or provide a matching document.",
            )

    verified_names_differ = (
        gst_data is not None
        and bank_data is not None
        and _comparison_result(comparisons, "Legal company name") == "Match"
        and _comparison_result(comparisons, "Bank beneficiary name") == "Match"
        and normalize_name(gst_data.legal_company_name.value or "")
        != normalize_name(bank_data.beneficiary_name.value or "")
    )
    if verified_names_differ:
        add_finding(
            "NAME_REVIEW_REQUIRED",
            "The verified GST legal company name and bank beneficiary name differ after "
            "case, punctuation, and whitespace normalization.",
            "Ask a reviewer to confirm a legitimate proprietor, trading-name, or other "
            "documented relationship between the GST and bank identities.",
        )

    verified_gstin = (
        _comparison_result(comparisons, "GSTIN") == "Match"
        and is_valid_gstin(submission.gstin)
    )
    normalized_gstin = normalize_gstin(submission.gstin)
    block_reason = blocked_vendors.get(normalized_gstin) if verified_gstin else None
    if block_reason:
        rejection_reason = f"Verified GSTIN is blocked by explicit internal policy: {block_reason}"
        return ValidationResult(
            "Rejected",
            (rejection_reason, *tuple(reasons)),
            "Do not onboard this vendor. Escalate the exact policy match to the compliance owner; "
            "document correction cannot override this policy decision.",
            tuple(comparisons),
            ("POLICY_BLOCKED_VENDOR", *tuple(reason_codes)),
            tuple(evidence_rows),
        )

    bank_evidence_verified = (
        verified_gstin
        and _comparison_result(comparisons, "Bank account number") == "Match"
        and _comparison_result(comparisons, "IFSC") == "Match"
    )
    if bank_evidence_verified:
        current_account = account_fingerprint(submission.account_number)
        current_ifsc = normalize_ifsc(submission.ifsc)
        bank_changed = any(
            normalize_gstin(previous.gstin) == normalized_gstin
            and (
                previous.account_fingerprint != current_account
                or normalize_ifsc(previous.ifsc) != current_ifsc
            )
            for previous in prior_approvals
        )
        if bank_changed:
            add_finding(
                "BANK_DETAILS_CHANGED",
                "Bank details differ from a previous Approved run for the same GSTIN.",
                "Pause onboarding and verify the bank-detail change through a known vendor contact channel.",
            )

        account_reused = any(
            normalize_gstin(previous.gstin) != normalized_gstin
            and previous.account_fingerprint == current_account
            for previous in prior_approvals
        )
        if account_reused:
            add_finding(
                "BANK_ACCOUNT_REUSED",
                "The verified bank account was previously Approved for a different GSTIN.",
                "Pause onboarding and investigate the shared bank account before making any payment.",
            )

    if reasons:
        return ValidationResult(
            "Pending",
            tuple(reasons),
            "Next steps: " + " ".join(dict.fromkeys(actions)),
            tuple(comparisons),
            tuple(reason_codes),
            tuple(evidence_rows),
        )
    return ValidationResult(
        "Approved",
        ("All required fields are valid, supported by exact document excerpts, and match.",),
        "No correction is required. Approval means only that these internal consistency checks passed; "
        "it is not government registration or bank-account verification.",
        tuple(comparisons),
        ("ALL_CHECKS_PASSED",),
        tuple(evidence_rows),
    )
