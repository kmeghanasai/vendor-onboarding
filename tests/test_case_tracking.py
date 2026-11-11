from case_tracking import (
    create_case_credentials,
    hash_access_token,
    normalize_case_id,
    tracking_credentials_valid,
)


def test_case_credentials_use_uuid_and_high_entropy_token():
    first = create_case_credentials()
    second = create_case_credentials()

    assert normalize_case_id(first.case_id) == first.case_id
    assert len(first.access_token) >= 32
    assert first.access_token != second.access_token
    assert first.token_hash == hash_access_token(first.access_token)


def test_tracking_token_hash_is_deterministic_without_storing_plaintext():
    token = "private-token-that-is-long-enough-123456"
    digest = hash_access_token(token)

    assert len(digest) == 64
    assert token not in digest
    assert digest == hash_access_token(token)


def test_tracking_credentials_reject_invalid_reference_or_short_token():
    valid_case = "a3b53d31-59fc-4075-ad91-d8f064983906"

    assert tracking_credentials_valid(valid_case, "x" * 32)
    assert not tracking_credentials_valid("not-a-uuid", "x" * 32)
    assert not tracking_credentials_valid(valid_case, "too-short")
