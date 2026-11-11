"""Privacy-aware audit storage for vendor-onboarding runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any, Protocol


DEFAULT_TABLE = "vendor_runs"


class AuditStoreError(RuntimeError):
    """Raised when configured audit storage cannot complete an operation."""


class AuditStore(Protocol):
    mode: str
    persistent: bool

    def list_records(self) -> list[dict[str, Any]]: ...

    def append_record(
        self,
        record: dict[str, Any],
        *,
        case_id: str | None = None,
        access_token_hash: str | None = None,
        parent_run_id: int | None = None,
        revision_number: int = 1,
    ) -> dict[str, Any]: ...

    def list_case_records(
        self,
        case_id: str,
        access_token_hash: str,
    ) -> list[dict[str, Any]]: ...

    def resolve_review(
        self,
        run_id: int,
        review_status: str,
        reviewer_name: str,
        reviewer_notes: str,
    ) -> dict[str, Any]: ...

    def clear_records(self) -> None: ...


@dataclass(frozen=True)
class AuditSettings:
    backend: str = "session"
    supabase_url: str = ""
    supabase_secret_key: str = ""
    table: str = DEFAULT_TABLE


def _configured_value(values: dict[str, object], name: str) -> str:
    environment_value = os.environ.get(name, "").strip()
    if environment_value:
        return environment_value
    return str(values.get(name, "") or "").strip()


def load_audit_settings(
    values: dict[str, object] | None = None,
) -> tuple[AuditSettings, str | None]:
    """Load audit configuration without ever returning secret values in errors."""
    values = values or {}
    backend = _configured_value(values, "AUDIT_BACKEND").casefold() or "session"
    table = _configured_value(values, "SUPABASE_AUDIT_TABLE") or DEFAULT_TABLE

    if backend not in {"session", "supabase"}:
        return AuditSettings(backend=backend, table=table), (
            "AUDIT_BACKEND must be either 'session' or 'supabase'."
        )

    settings = AuditSettings(
        backend=backend,
        supabase_url=_configured_value(values, "SUPABASE_URL"),
        supabase_secret_key=_configured_value(values, "SUPABASE_SECRET_KEY"),
        table=table,
    )
    if backend == "supabase" and (
        not settings.supabase_url or not settings.supabase_secret_key
    ):
        return settings, (
            "Persistent audit storage is selected but SUPABASE_URL and "
            "SUPABASE_SECRET_KEY are not both configured."
        )
    return settings, None


class SessionAuditStore:
    """Mutable session-backed store used for local fallback and tests."""

    mode = "session"
    persistent = False

    def __init__(self, records: list[dict[str, Any]]):
        self._records = records

    def list_records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def append_record(
        self,
        record: dict[str, Any],
        *,
        case_id: str | None = None,
        access_token_hash: str | None = None,
        parent_run_id: int | None = None,
        revision_number: int = 1,
    ) -> dict[str, Any]:
        stored = dict(record)
        existing_runs = [
            int(item.get("run", 0))
            for item in self._records
            if str(item.get("run", "")).isdigit()
        ]
        stored["run"] = max(existing_runs, default=0) + 1
        stored["case_id"] = case_id or "Session only"
        stored["revision_number"] = revision_number
        stored["parent_run_id"] = parent_run_id
        self._records.append(stored)
        return stored

    def list_case_records(
        self,
        case_id: str,
        access_token_hash: str,
    ) -> list[dict[str, Any]]:
        raise AuditStoreError("Secure case tracking requires persistent audit storage.")

    def clear_records(self) -> None:
        self._records.clear()

    def resolve_review(
        self,
        run_id: int,
        review_status: str,
        reviewer_name: str,
        reviewer_notes: str,
    ) -> dict[str, Any]:
        for index, record in enumerate(self._records):
            if int(record.get("run", 0)) != run_id:
                continue
            if record.get("status") != "Pending":
                raise AuditStoreError("Only automated Pending cases can be resolved.")
            if record.get("review_status", "Not reviewed") != "Not reviewed":
                raise AuditStoreError("This case already has a reviewer resolution.")
            resolved = {
                **record,
                "review_status": review_status,
                "reviewer_name": reviewer_name,
                "reviewer_notes": reviewer_notes,
                "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._records[index] = resolved
            return resolved
        raise AuditStoreError("The selected audit run was not found.")


class SupabaseAuditStore:
    """Append-only Supabase Data API adapter for masked audit records."""

    mode = "supabase"
    persistent = True
    record_columns = (
        "id,created_at,case_id,revision_number,parent_run_id,review_status,"
        "reviewer_name,reviewer_notes,reviewed_at,audit_record"
    )

    def __init__(self, settings: AuditSettings, *, client: Any | None = None):
        self._table = settings.table
        if client is not None:
            self._client = client
            return

        try:
            from supabase import create_client
            from supabase.client import ClientOptions

            self._client = create_client(
                settings.supabase_url,
                settings.supabase_secret_key,
                options=ClientOptions(
                    postgrest_client_timeout=10,
                    storage_client_timeout=10,
                    schema="public",
                ),
            )
        except Exception as exc:
            raise AuditStoreError(
                "Could not initialize persistent audit storage. Verify the Supabase "
                "configuration and installed dependencies."
            ) from exc

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> dict[str, Any]:
        audit_record = row.get("audit_record")
        if not isinstance(audit_record, dict):
            raise AuditStoreError("Persistent audit storage returned a malformed record.")
        record = dict(audit_record)
        record["run"] = int(row["id"])
        record["timestamp"] = str(row.get("created_at") or record.get("timestamp", ""))
        record["review_status"] = str(row.get("review_status") or "Not reviewed")
        record["reviewer_name"] = str(row.get("reviewer_name") or "")
        record["reviewer_notes"] = str(row.get("reviewer_notes") or "")
        record["reviewed_at"] = str(row.get("reviewed_at") or "")
        record["case_id"] = str(row.get("case_id") or "")
        record["revision_number"] = int(row.get("revision_number") or 1)
        record["parent_run_id"] = row.get("parent_run_id")
        return record

    @staticmethod
    def _insert_payload(
        record: dict[str, Any],
        *,
        case_id: str | None,
        access_token_hash: str | None,
        parent_run_id: int | None,
        revision_number: int,
    ) -> dict[str, Any]:
        audit_record = {key: value for key, value in record.items() if key != "run"}
        return {
            "company": str(record.get("company", "Not provided")),
            "gstin": str(record.get("gstin", "Not provided")),
            "automated_status": str(record.get("status", "Pending")),
            "primary_code": str(record.get("primary_code", "UNCLASSIFIED")),
            "account_display": str(record.get("account_display", "Not available")),
            "account_fingerprint": str(record.get("account_fingerprint", "")),
            "ifsc": str(record.get("ifsc", "Not provided")),
            "audit_record": audit_record,
            "case_id": case_id,
            "access_token_hash": access_token_hash,
            "parent_run_id": parent_run_id,
            "revision_number": revision_number,
        }

    def list_records(self) -> list[dict[str, Any]]:
        try:
            response = (
                self._client.table(self._table)
                .select(self.record_columns)
                .order("id", desc=False)
                .execute()
            )
            rows = response.data
            if not isinstance(rows, list):
                raise AuditStoreError(
                    "Persistent audit storage returned an unexpected response."
                )
            return [self._record_from_row(row) for row in rows]
        except AuditStoreError:
            raise
        except Exception as exc:
            raise AuditStoreError(
                "Could not read persistent audit history. Retry, then verify the "
                "Supabase table and credentials."
            ) from exc

    def append_record(
        self,
        record: dict[str, Any],
        *,
        case_id: str | None = None,
        access_token_hash: str | None = None,
        parent_run_id: int | None = None,
        revision_number: int = 1,
    ) -> dict[str, Any]:
        try:
            response = (
                self._client.table(self._table)
                .insert(
                    self._insert_payload(
                        record,
                        case_id=case_id,
                        access_token_hash=access_token_hash,
                        parent_run_id=parent_run_id,
                        revision_number=revision_number,
                    )
                )
                .select(self.record_columns)
                .execute()
            )
            rows = response.data
            if not isinstance(rows, list) or len(rows) != 1:
                raise AuditStoreError(
                    "Persistent audit storage did not confirm the saved run."
                )
            return self._record_from_row(rows[0])
        except AuditStoreError:
            raise
        except Exception as exc:
            raise AuditStoreError(
                "Could not save the audit run. Retry, then verify the Supabase "
                "table and credentials."
            ) from exc

    def list_case_records(
        self,
        case_id: str,
        access_token_hash: str,
    ) -> list[dict[str, Any]]:
        try:
            response = (
                self._client.table(self._table)
                .select(self.record_columns)
                .eq("case_id", case_id)
                .eq("access_token_hash", access_token_hash)
                .order("revision_number", desc=False)
                .execute()
            )
            rows = response.data
            if not isinstance(rows, list):
                raise AuditStoreError(
                    "Persistent audit storage returned an unexpected case response."
                )
            return [self._record_from_row(row) for row in rows]
        except AuditStoreError:
            raise
        except Exception as exc:
            raise AuditStoreError(
                "Could not load that case. Retry, then verify the case reference and token."
            ) from exc

    def resolve_review(
        self,
        run_id: int,
        review_status: str,
        reviewer_name: str,
        reviewer_notes: str,
    ) -> dict[str, Any]:
        try:
            response = self._client.rpc(
                "resolve_vendor_run",
                {
                    "p_run_id": run_id,
                    "p_review_status": review_status,
                    "p_reviewer_name": reviewer_name,
                    "p_reviewer_notes": reviewer_notes,
                },
            ).execute()
            resolution = response.data
            if not isinstance(resolution, dict):
                raise AuditStoreError(
                    "Persistent audit storage did not confirm the reviewer resolution."
                )
            return resolution
        except AuditStoreError:
            raise
        except Exception as exc:
            raise AuditStoreError(
                "Could not save the reviewer resolution. Confirm that the case is still "
                "Pending and has not already been resolved."
            ) from exc

    def clear_records(self) -> None:
        raise AuditStoreError(
            "Persistent audit history is append-only and cannot be cleared from the app."
        )
