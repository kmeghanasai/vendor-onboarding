"""Session-only, privacy-aware audit records for the Streamlit dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from validation import (
    PriorApproval,
    Submission,
    ValidationResult,
    account_fingerprint,
    mask_account,
    mask_account_text,
)


def _display_value(field: str, value: str | None) -> str:
    if field == "Bank account number":
        return mask_account(value)
    return value or "Not available"


def make_run_record(
    submission: Submission,
    result: ValidationResult,
    run_number: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build an audit record without retaining the raw bank account number."""
    timestamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    comparison_rows = [
        {
            "Field": row.field,
            "Submitted value": _display_value(row.field, row.submitted_value),
            "Document value": _display_value(row.field, row.document_value),
            "Check result": row.result,
        }
        for row in result.comparisons
    ]
    evidence_rows = [
        {
            "Field": row.field,
            "Source": row.document,
            "Extracted value": _display_value(row.field, row.extracted_value),
            "Evidence check": row.result,
            "Supporting excerpt": (
                mask_account_text(row.excerpt)
                if row.field == "Bank account number"
                else row.excerpt or "Not available"
            ),
        }
        for row in result.evidence
    ]
    findings = [
        {"Code": code, "Finding": reason}
        for code, reason in zip(result.reason_codes, result.reasons, strict=False)
    ]
    return {
        "run": run_number,
        "timestamp": timestamp,
        "company": submission.legal_name or "Not provided",
        "gstin": submission.gstin or "Not provided",
        "status": result.status,
        "primary_code": result.primary_code,
        "account_display": mask_account(submission.account_number),
        "account_fingerprint": (
            account_fingerprint(submission.account_number)
            if submission.account_number
            else ""
        ),
        "ifsc": submission.ifsc or "Not provided",
        "reason_codes": list(result.reason_codes),
        "reasons": list(result.reasons),
        "findings": findings,
        "follow_up": result.follow_up,
        "comparisons": comparison_rows,
        "evidence": evidence_rows,
    }


def prior_approvals(records: list[dict[str, Any]]) -> tuple[PriorApproval, ...]:
    """Return only previously Approved identities for deterministic history controls."""
    return tuple(
        PriorApproval(
            gstin=str(record["gstin"]),
            account_fingerprint=str(record["account_fingerprint"]),
            ifsc=str(record["ifsc"]),
        )
        for record in records
        if record.get("status") == "Approved" and record.get("account_fingerprint")
    )
