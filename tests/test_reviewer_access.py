from reviewer_access import (
    load_reviewer_settings,
    reviewer_code_matches,
    validate_resolution,
)


def test_reviewer_code_uses_exact_match(monkeypatch):
    monkeypatch.delenv("REVIEWER_ACCESS_CODE", raising=False)
    settings, error = load_reviewer_settings(
        {"REVIEWER_ACCESS_CODE": "correct-horse-battery-staple"}
    )

    assert error is None
    assert reviewer_code_matches(
        "correct-horse-battery-staple", settings.access_code
    )
    assert not reviewer_code_matches("Correct-Horse-Battery-Staple", settings.access_code)
    assert not reviewer_code_matches("", settings.access_code)


def test_short_or_missing_reviewer_code_is_rejected(monkeypatch):
    monkeypatch.delenv("REVIEWER_ACCESS_CODE", raising=False)
    _, missing_error = load_reviewer_settings({})
    _, short_error = load_reviewer_settings({"REVIEWER_ACCESS_CODE": "too-short"})

    assert "not configured" in missing_error
    assert "at least 12" in short_error


def test_resolution_requires_specific_identity_and_notes():
    assert validate_resolution("Approved", "M", "too short") is not None
    assert validate_resolution("Unsupported", "Meghana", "A valid detailed reason.") is not None
    assert (
        validate_resolution(
            "Correction requested",
            "Meghana Sai",
            "The beneficiary relationship requires supporting documentation.",
        )
        is None
    )
