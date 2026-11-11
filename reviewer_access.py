"""Reviewer access and resolution input validation."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import os


REVIEW_OUTCOMES = ("Approved", "Rejected", "Correction requested")


@dataclass(frozen=True)
class ReviewerSettings:
    access_code: str = ""


def load_reviewer_settings(
    values: dict[str, object] | None = None,
) -> tuple[ReviewerSettings, str | None]:
    values = values or {}
    access_code = os.environ.get("REVIEWER_ACCESS_CODE", "").strip() or str(
        values.get("REVIEWER_ACCESS_CODE", "") or ""
    ).strip()
    settings = ReviewerSettings(access_code=access_code)
    if not access_code:
        return settings, (
            "Reviewer access is not configured. Set REVIEWER_ACCESS_CODE in "
            "Streamlit secrets."
        )
    if len(access_code) < 12:
        return settings, "REVIEWER_ACCESS_CODE must contain at least 12 characters."
    return settings, None


def reviewer_code_matches(candidate: str, configured_code: str) -> bool:
    """Compare access codes without early-exit timing differences."""
    if not candidate or not configured_code:
        return False
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        configured_code.encode("utf-8"),
    )


def validate_resolution(
    review_status: str,
    reviewer_name: str,
    reviewer_notes: str,
) -> str | None:
    if review_status not in REVIEW_OUTCOMES:
        return "Choose a supported reviewer outcome."
    if len(reviewer_name.strip()) < 2:
        return "Enter the reviewer's name."
    if len(reviewer_name.strip()) > 80:
        return "Reviewer name must be 80 characters or fewer."
    if len(reviewer_notes.strip()) < 10:
        return "Enter a specific review reason of at least 10 characters."
    if len(reviewer_notes.strip()) > 1000:
        return "Reviewer notes must be 1,000 characters or fewer."
    return None
