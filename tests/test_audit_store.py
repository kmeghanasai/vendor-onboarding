from types import SimpleNamespace

import pytest

from audit_store import (
    AuditSettings,
    AuditStoreError,
    SessionAuditStore,
    SupabaseAuditStore,
    load_audit_settings,
)
from validation import ValidationResult, with_operational_pending


def sample_record(run=1):
    return {
        "run": run,
        "timestamp": "2026-11-09T10:00:00+05:30",
        "company": "Acme Demo Technologies Private Limited",
        "gstin": "27AAPFU0939F1ZV",
        "status": "Approved",
        "primary_code": "ALL_CHECKS_PASSED",
        "account_display": "********7890",
        "account_fingerprint": "one-way-fingerprint",
        "ifsc": "HDFC0001234",
        "reason_codes": ["ALL_CHECKS_PASSED"],
        "reasons": ["All checks passed."],
        "findings": [],
        "follow_up": "No correction is required.",
        "comparisons": [],
        "evidence": [],
    }


class FakeQuery:
    def __init__(self, client):
        self.client = client
        self.payload = None

    def select(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.client.filters.append((column, value))
        return self

    def insert(self, payload):
        self.payload = payload
        self.client.inserted = payload
        return self

    def execute(self):
        if self.client.error:
            raise RuntimeError("database unavailable: secret-value-must-not-leak")
        if self.payload is not None:
            return SimpleNamespace(
                data=[
                    {
                        "id": 41,
                        "created_at": "2026-11-09T04:30:00+00:00",
                        "review_status": "Not reviewed",
                        "case_id": self.payload.get("case_id"),
                        "revision_number": self.payload.get("revision_number", 1),
                        "parent_run_id": self.payload.get("parent_run_id"),
                        "audit_record": self.payload["audit_record"],
                    }
                ]
            )
        return SimpleNamespace(data=self.client.rows)


class FakeClient:
    def __init__(self, rows=None, error=False):
        self.rows = rows or []
        self.error = error
        self.inserted = None
        self.table_name = None
        self.filters = []
        self.rpc_name = None
        self.rpc_params = None

    def table(self, name):
        self.table_name = name
        return FakeQuery(self)

    def rpc(self, name, params):
        self.rpc_name = name
        self.rpc_params = params
        return FakeRpcQuery(self)


class FakeRpcQuery:
    def __init__(self, client):
        self.client = client

    def execute(self):
        if self.client.error:
            raise RuntimeError("provider detail must not leak")
        return SimpleNamespace(
            data={
                "run": self.client.rpc_params["p_run_id"],
                "review_status": self.client.rpc_params["p_review_status"],
                "reviewer_name": self.client.rpc_params["p_reviewer_name"],
                "reviewer_notes": self.client.rpc_params["p_reviewer_notes"],
                "reviewed_at": "2026-11-09T12:00:00+00:00",
            }
        )


def test_session_store_assigns_monotonic_run_ids_and_can_clear():
    records = [sample_record(3)]
    store = SessionAuditStore(records)

    saved = store.append_record(sample_record(1))

    assert saved["run"] == 4
    assert len(store.list_records()) == 2
    store.clear_records()
    assert store.list_records() == []


def test_session_store_resolves_pending_once_without_changing_automated_status():
    record = sample_record()
    record["status"] = "Pending"
    store = SessionAuditStore([record])

    resolved = store.resolve_review(
        1,
        "Approved",
        "Procurement Reviewer",
        "Verified the bank change through the registered contact.",
    )

    assert resolved["status"] == "Pending"
    assert resolved["review_status"] == "Approved"
    with pytest.raises(AuditStoreError, match="already"):
        store.resolve_review(1, "Rejected", "Reviewer", "A second resolution is invalid.")


def test_session_store_does_not_override_automated_final_decision():
    store = SessionAuditStore([sample_record()])

    with pytest.raises(AuditStoreError, match="Only automated Pending"):
        store.resolve_review(1, "Rejected", "Reviewer", "Attempted override is blocked.")


def test_supabase_configuration_requires_both_server_side_values(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    settings, error = load_audit_settings({"AUDIT_BACKEND": "supabase"})

    assert settings.backend == "supabase"
    assert "SUPABASE_URL" in error
    assert "SUPABASE_SECRET_KEY" in error


def test_environment_overrides_non_secret_settings(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKEND", "session")
    settings, error = load_audit_settings({"AUDIT_BACKEND": "supabase"})

    assert error is None
    assert settings.backend == "session"


def test_supabase_insert_persists_only_masked_audit_data():
    client = FakeClient()
    store = SupabaseAuditStore(
        AuditSettings(backend="supabase", table="vendor_runs"),
        client=client,
    )

    saved = store.append_record(
        sample_record(),
        case_id="a3b53d31-59fc-4075-ad91-d8f064983906",
        access_token_hash="hashed-private-token",
    )

    assert saved["run"] == 41
    assert saved["review_status"] == "Not reviewed"
    assert client.table_name == "vendor_runs"
    assert client.inserted["account_display"] == "********7890"
    assert "001234567890" not in repr(client.inserted)
    assert "run" not in client.inserted["audit_record"]
    assert saved["case_id"] == "a3b53d31-59fc-4075-ad91-d8f064983906"
    assert client.inserted["access_token_hash"] == "hashed-private-token"


def test_supabase_list_rehydrates_database_id_and_review_state():
    stored = sample_record()
    stored.pop("run")
    client = FakeClient(
        rows=[
            {
                "id": 9,
                "created_at": "2026-11-09T04:30:00+00:00",
                "review_status": "Correction requested",
                "case_id": "a3b53d31-59fc-4075-ad91-d8f064983906",
                "revision_number": 1,
                "parent_run_id": None,
                "audit_record": stored,
            }
        ]
    )
    store = SupabaseAuditStore(
        AuditSettings(backend="supabase", table="vendor_runs"),
        client=client,
    )

    records = store.list_records()

    assert records[0]["run"] == 9
    assert records[0]["review_status"] == "Correction requested"


def test_case_lookup_filters_by_reference_and_token_hash():
    stored = sample_record()
    stored.pop("run")
    case_id = "a3b53d31-59fc-4075-ad91-d8f064983906"
    client = FakeClient(
        rows=[
            {
                "id": 12,
                "created_at": "2026-11-10T04:30:00+00:00",
                "review_status": "Correction requested",
                "case_id": case_id,
                "revision_number": 1,
                "parent_run_id": None,
                "audit_record": stored,
            }
        ]
    )
    store = SupabaseAuditStore(
        AuditSettings(backend="supabase", table="vendor_runs"),
        client=client,
    )

    records = store.list_case_records(case_id, "token-hash")

    assert records[0]["run"] == 12
    assert ("case_id", case_id) in client.filters
    assert ("access_token_hash", "token-hash") in client.filters


def test_supabase_errors_are_actionable_without_leaking_provider_details():
    store = SupabaseAuditStore(
        AuditSettings(backend="supabase", table="vendor_runs"),
        client=FakeClient(error=True),
    )

    with pytest.raises(AuditStoreError) as caught:
        store.list_records()

    assert "Could not read persistent audit history" in str(caught.value)
    assert "secret-value-must-not-leak" not in str(caught.value)


def test_supabase_resolution_uses_atomic_database_function():
    client = FakeClient()
    store = SupabaseAuditStore(
        AuditSettings(backend="supabase", table="vendor_runs"),
        client=client,
    )

    resolution = store.resolve_review(
        23,
        "Correction requested",
        "Meghana Sai",
        "Request a bank letter showing the current beneficiary name.",
    )

    assert client.rpc_name == "resolve_vendor_run"
    assert client.rpc_params["p_run_id"] == 23
    assert resolution["review_status"] == "Correction requested"


def test_operational_failure_downgrades_approval_but_preserves_evidence():
    approved = ValidationResult(
        "Approved",
        ("All checks passed.",),
        "No correction is required.",
        (),
        ("ALL_CHECKS_PASSED",),
        (),
    )

    result = with_operational_pending(
        approved,
        "AUDIT_SAVE_FAILED",
        "The audit record could not be saved.",
        "Restore persistence and resubmit.",
    )

    assert result.status == "Pending"
    assert result.reason_codes == ("AUDIT_SAVE_FAILED",)
    assert "Restore persistence" in result.follow_up
