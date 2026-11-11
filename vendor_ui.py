"""Streamlit user interface for the PS2 vendor-onboarding workflow."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from audit_store import (
    AuditSettings,
    AuditStore,
    AuditStoreError,
    SessionAuditStore,
    SupabaseAuditStore,
    load_audit_settings,
)
from case_tracking import (
    RevisionContext,
    create_case_credentials,
    hash_access_token,
    normalize_case_id,
    tracking_credentials_valid,
)
from document_extraction import extract_pdf_text
from gemini_extraction import ExtractionOutcome, GeminiDocumentExtractor, load_gemini_settings
from policy import load_blocked_vendors
from reviewer_access import (
    REVIEW_OUTCOMES,
    load_reviewer_settings,
    reviewer_code_matches,
    validate_resolution,
)
from run_history import make_run_record, prior_approvals
from validation import (
    Submission,
    ValidationResult,
    mask_account,
    mask_account_text,
    validate_submission,
    with_operational_pending,
)


st.set_page_config(page_title="Vendor onboarding", page_icon="V", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1500px;
        padding-top: 1.6rem;
        padding-bottom: 3rem;
    }
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.28);
        border-radius: 0.65rem;
        padding: 0.85rem 1rem;
    }
    div[data-testid="stForm"] {
        border: 1px solid rgba(128, 128, 128, 0.28);
        border-radius: 0.75rem;
        padding: 1.25rem;
    }
    div[data-testid="stExpander"] {
        border-radius: 0.65rem;
    }
    /*
       Streamlit fades previously rendered elements during a long rerun. The
       workflow must remain readable while Gemini is processing, even though
       its widgets correctly remain non-interactive until the rerun finishes.
       Streamlit 1.45 applies the fade both to stale element containers and to
       nested tab/form components, so cover both layers explicitly.
    */
    div[data-testid="stElementContainer"][data-stale="true"],
    div[data-testid="stTabs"],
    div[data-testid="stTabs"] [role="tablist"],
    div[data-testid="stTabs"] [role="tabpanel"],
    div[data-testid="stForm"],
    div[data-testid="stForm"] * {
        opacity: 1 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


REASON_LABELS = {
    "ALL_CHECKS_PASSED": "All consistency checks passed",
    "REQUIRED_FIELD_MISSING": "Required information is missing",
    "COUNTRY_NOT_SUPPORTED": "Country is not supported",
    "EMAIL_FORMAT_INVALID": "Email format is invalid",
    "GSTIN_FORMAT_INVALID": "GSTIN format is invalid",
    "GSTIN_CHECKSUM_INVALID": "GSTIN checksum is invalid",
    "IFSC_FORMAT_INVALID": "IFSC format is invalid",
    "ACCOUNT_FORMAT_INVALID": "Account-number format is invalid",
    "GST_DOCUMENT_MISSING": "GST evidence is missing",
    "BANK_DOCUMENT_MISSING": "Bank evidence is missing",
    "GST_DOCUMENT_UNREADABLE": "GST evidence is unreadable",
    "BANK_DOCUMENT_UNREADABLE": "Bank evidence is unreadable",
    "GST_EXTRACTION_NOT_COMPLETED": "GST extraction did not run",
    "BANK_EXTRACTION_NOT_COMPLETED": "Bank extraction did not run",
    "GST_EXTRACTION_FAILED": "GST extraction failed",
    "BANK_EXTRACTION_FAILED": "Bank extraction failed",
    "GST_SCHEMA_INVALID": "GST extraction schema is invalid",
    "BANK_SCHEMA_INVALID": "Bank extraction schema is invalid",
    "DOCUMENT_FIELD_MISSING": "A required document field is missing",
    "UNSUPPORTED_EVIDENCE": "The extracted value lacks exact evidence",
    "NAME_REVIEW_REQUIRED": "A name discrepancy needs human review",
    "FIELD_MISMATCH": "A submitted identifier does not match",
    "BANK_DETAILS_CHANGED": "Bank details changed after approval",
    "BANK_ACCOUNT_REUSED": "Bank account is linked to another GSTIN",
    "POLICY_BLOCKED_VENDOR": "Vendor matches a blocking policy",
    "AUDIT_HISTORY_UNAVAILABLE": "Persistent history could not be checked",
    "AUDIT_SAVE_FAILED": "The audit record could not be saved",
    "UNCLASSIFIED": "Review required",
}


def _streamlit_secrets() -> dict[str, object]:
    try:
        names = (
            "GEMINI_API_KEY",
            "GEMINI_MODEL",
            "AUDIT_BACKEND",
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY",
            "SUPABASE_AUDIT_TABLE",
            "REVIEWER_ACCESS_CODE",
        )
        return {name: st.secrets.get(name, "") for name in names}
    except Exception:
        return {}


@st.cache_resource(show_spinner=False)
def _persistent_store(url: str, secret_key: str, table: str) -> SupabaseAuditStore:
    return SupabaseAuditStore(
        AuditSettings(
            backend="supabase",
            supabase_url=url,
            supabase_secret_key=secret_key,
            table=table,
        )
    )


def _load_audit_store() -> tuple[AuditStore, str | None]:
    settings, config_error = load_audit_settings(_streamlit_secrets())
    session_store = SessionAuditStore(st.session_state.run_history)
    if config_error:
        return session_store, config_error
    if settings.backend == "session":
        return session_store, None
    try:
        return (
            _persistent_store(
                settings.supabase_url,
                settings.supabase_secret_key,
                settings.table,
            ),
            None,
        )
    except AuditStoreError as exc:
        return session_store, str(exc)


def _display_value(field: str, value: str | None) -> str:
    return mask_account(value) if field == "Bank account number" else value or "Not available"


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return value


def _comparison_rows(result: ValidationResult) -> list[dict[str, str]]:
    return [
        {
            "Field": row.field,
            "Submitted value": _display_value(row.field, row.submitted_value),
            "Document value": _display_value(row.field, row.document_value),
            "Check result": row.result,
        }
        for row in result.comparisons
    ]


def _evidence_rows(result: ValidationResult) -> list[dict[str, str]]:
    return [
        {
            "Field": row.field,
            "Source": row.document,
            "Extracted value": _display_value(row.field, row.extracted_value),
            "Evidence check": row.result,
            "Supporting excerpt": mask_account_text(row.excerpt),
        }
        for row in result.evidence
    ]


def _render_findings(reason_codes: list[str] | tuple[str, ...], reasons) -> None:
    for index, reason in enumerate(reasons):
        code = reason_codes[index] if index < len(reason_codes) else "UNCLASSIFIED"
        with st.container(border=True):
            st.markdown(f"**{REASON_LABELS.get(code, code.replace('_', ' ').title())}**")
            st.caption(code)
            st.write(reason)


def _render_status_banner(status: str, text: str) -> None:
    message = f"{status}: {text}"
    if status == "Approved":
        st.success(message)
    elif status == "Rejected":
        st.error(message)
    else:
        st.warning(message)


def render_result(result: ValidationResult, run_number: int) -> None:
    st.divider()
    st.subheader(f"Decision - Run {run_number}")
    headline = {
        "Approved": "the submitted details and supported document fields are internally consistent.",
        "Pending": "one or more findings require correction or human review.",
        "Rejected": "an explicit document-supported blocking policy applies.",
    }[result.status]
    _render_status_banner(result.status, headline)

    matches = sum(row.result == "Match" for row in result.comparisons)
    review_items = len(result.reasons) if result.status != "Approved" else 0
    summary_columns = st.columns(3)
    summary_columns[0].metric("Decision", result.status)
    summary_columns[1].metric("Field matches", f"{matches} / {len(result.comparisons)}")
    summary_columns[2].metric("Review findings", review_items)

    findings_column, action_column = st.columns([1.55, 1], gap="large")
    with findings_column:
        st.markdown("#### Findings")
        _render_findings(result.reason_codes, result.reasons)
    with action_column:
        st.markdown("#### Recommended action")
        st.info(result.follow_up)
        st.caption("Generated for review and follow-up; this application does not send email.")
        st.caption(
            "Approval confirms internal consistency only. It is not government registration "
            "or bank-account verification."
        )

    comparison_tab, evidence_tab = st.tabs(
        ["Field comparison", "Evidence provenance"]
    )
    with comparison_tab:
        st.dataframe(
            _comparison_rows(result),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Field": st.column_config.TextColumn(width="medium"),
                "Submitted value": st.column_config.TextColumn(width="large"),
                "Document value": st.column_config.TextColumn(width="large"),
                "Check result": st.column_config.TextColumn(width="medium"),
            },
        )
    with evidence_tab:
        st.caption(
            "Gemini supplies each value and excerpt. The application verifies that the excerpt "
            "exists in the actual PyMuPDF text before using the value."
        )
        st.dataframe(
            _evidence_rows(result),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Field": st.column_config.TextColumn(width="medium"),
                "Source": st.column_config.TextColumn(width="small"),
                "Extracted value": st.column_config.TextColumn(width="large"),
                "Evidence check": st.column_config.TextColumn(width="medium"),
                "Supporting excerpt": st.column_config.TextColumn(width="large"),
            },
        )


def _record_findings(record: dict) -> list[dict[str, str]]:
    findings = record.get("findings")
    if findings:
        return findings
    codes = record.get("reason_codes", [])
    return [
        {
            "Code": codes[index] if index < len(codes) else "UNCLASSIFIED",
            "Finding": reason,
        }
        for index, reason in enumerate(record.get("reasons", []))
    ]


def _render_review_resolution(record: dict, store: AuditStore) -> None:
    st.markdown("#### Human resolution")
    review_status = record.get("review_status", "Not reviewed")
    if review_status != "Not reviewed":
        st.success(f"Reviewer outcome: {review_status}")
        st.write(record.get("reviewer_notes") or "No reviewer notes were recorded.")
        reviewer = record.get("reviewer_name") or "Unknown reviewer"
        reviewed_at = _format_timestamp(record.get("reviewed_at", ""))
        st.caption(f"Recorded by {reviewer} on {reviewed_at}")
        return
    if record.get("status") != "Pending":
        st.info(
            "Only automated Pending cases enter human resolution. Approved and policy-based "
            "Rejected decisions remain read-only."
        )
        return

    with st.form(f"resolve_run_{record['run']}"):
        outcome = st.selectbox("Reviewer outcome", REVIEW_OUTCOMES)
        reviewer_name = st.text_input(
            "Reviewer name",
            placeholder="Name recorded in the audit event",
            autocomplete="off",
        )
        reviewer_notes = st.text_area(
            "Verification notes",
            placeholder="Describe what was independently verified and why this outcome is appropriate.",
            max_chars=1000,
        )
        submitted = st.form_submit_button(
            "Record reviewer resolution",
            type="primary",
            use_container_width=True,
        )
    if not submitted:
        return
    if error := validate_resolution(outcome, reviewer_name, reviewer_notes):
        st.error(error)
        return
    try:
        store.resolve_review(
            int(record["run"]),
            outcome,
            reviewer_name.strip(),
            reviewer_notes.strip(),
        )
    except AuditStoreError as exc:
        st.error(str(exc))
        return
    st.session_state.review_notice = (
        f"Run {record['run']} was resolved as {outcome}. The automated decision and "
        "evidence remain unchanged."
    )
    st.rerun()


def render_dashboard(
    history: list[dict],
    store: AuditStore,
    storage_error: str | None = None,
    *,
    reviewer_mode: bool = False,
) -> None:
    widget_scope = "reviewer" if reviewer_mode else "session"
    heading, clear_column = st.columns([5, 1])
    with heading:
        st.subheader("Reviewer audit queue" if reviewer_mode else "My session history")
        if reviewer_mode:
            st.caption(
                "Protected persistent audit trail. Automated decisions and human resolutions "
                "are shown separately; raw account numbers and PDF contents are not stored."
            )
        else:
            st.caption(
                "Only submissions made in this browser session are shown. Account numbers are "
                "masked, and raw account numbers are never stored in this view."
            )
    with clear_column:
        if (
            history
            and not reviewer_mode
            and st.button(
                "Clear history",
                type="secondary",
                use_container_width=True,
                key=f"{widget_scope}_clear_history",
            )
        ):
            store.clear_records()
            st.rerun()

    if storage_error:
        st.error(storage_error)

    if not history:
        st.info("No runs yet. Complete a vendor submission to populate the dashboard.")
        return

    status_counts = {
        status: sum(record["status"] == status for record in history)
        for status in ("Approved", "Pending", "Rejected")
    }
    metric_columns = st.columns(4)
    metric_columns[0].metric("Total runs", len(history))
    metric_columns[1].metric("Approved", status_counts["Approved"])
    metric_columns[2].metric("Pending", status_counts["Pending"])
    metric_columns[3].metric("Rejected", status_counts["Rejected"])

    st.markdown("#### Find a run")
    filter_column, search_column = st.columns([1, 2])
    with filter_column:
        selected_statuses = st.multiselect(
            "Decision",
            ["Approved", "Pending", "Rejected"],
            default=["Approved", "Pending", "Rejected"],
            key=f"{widget_scope}_decision_filter",
        )
    with search_column:
        search_text = st.text_input(
            "Search",
            placeholder="Company name or GSTIN",
            key=f"{widget_scope}_search",
        ).strip().casefold()

    filtered = [
        record
        for record in reversed(history)
        if record.get("status") in selected_statuses
        and (
            not search_text
            or search_text in str(record.get("company", "")).casefold()
            or search_text in str(record.get("gstin", "")).casefold()
        )
    ]
    if not filtered:
        st.info("No runs match the selected filters.")
        return

    summary_rows = [
        {
            "Run": record["run"],
            "Time": _format_timestamp(record["timestamp"]),
            "Vendor": record["company"],
            "GSTIN": record["gstin"],
            "Decision": record["status"],
            **(
                {"Review state": record.get("review_status", "Not reviewed")}
                if reviewer_mode
                else {}
            ),
            "Account": record["account_display"],
            "IFSC": record["ifsc"],
            "Primary reason": REASON_LABELS.get(
                record.get("primary_code", "UNCLASSIFIED"),
                record.get("primary_code", "Review required"),
            ),
        }
        for record in filtered
    ]
    st.dataframe(
        summary_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Run": st.column_config.NumberColumn(width="small"),
            "Time": st.column_config.TextColumn(width="medium"),
            "Vendor": st.column_config.TextColumn(width="large"),
            "GSTIN": st.column_config.TextColumn(width="medium"),
            "Decision": st.column_config.TextColumn(width="small"),
            "Review state": st.column_config.TextColumn(width="medium"),
            "Account": st.column_config.TextColumn(width="medium"),
            "IFSC": st.column_config.TextColumn(width="medium"),
            "Primary reason": st.column_config.TextColumn(width="large"),
        },
    )

    st.markdown("#### Review run details")
    run_by_number = {record["run"]: record for record in filtered}
    selected_run = st.selectbox(
        "Run",
        options=list(run_by_number),
        format_func=lambda number: (
            f"Run {number} - {run_by_number[number]['status']} - "
            f"{run_by_number[number]['company']}"
        ),
        label_visibility="collapsed",
        key=f"{widget_scope}_selected_run",
    )
    record = run_by_number[selected_run]
    with st.container(border=True):
        _render_status_banner(
            record["status"],
            REASON_LABELS.get(
                record.get("primary_code", "UNCLASSIFIED"),
                "Review the detailed findings below.",
            ),
        )
        detail_columns = st.columns(5 if reviewer_mode else 4)
        detail_columns[0].metric("Run", record["run"])
        detail_columns[1].metric("Automated decision", record["status"])
        detail_columns[2].metric("Account", record["account_display"])
        detail_columns[3].metric("IFSC", record["ifsc"])
        if reviewer_mode:
            detail_columns[4].metric(
                "Human review",
                record.get("review_status", "Not reviewed"),
            )
        st.caption(
            f"{record['company']} | GSTIN {record['gstin']} | "
            f"{_format_timestamp(record['timestamp'])}"
        )

        comparison_tab, evidence_tab, findings_tab = st.tabs(
            ["Comparison", "Evidence", "Findings and action"]
        )
        with comparison_tab:
            st.dataframe(
                record.get("comparisons", []),
                use_container_width=True,
                hide_index=True,
            )
        with evidence_tab:
            evidence = record.get("evidence", [])
            if evidence:
                st.dataframe(evidence, use_container_width=True, hide_index=True)
            else:
                st.info("Evidence provenance was not recorded for this earlier run.")
        with findings_tab:
            findings = _record_findings(record)
            _render_findings(
                [finding["Code"] for finding in findings],
                [finding["Finding"] for finding in findings],
            )
            st.info(record["follow_up"])
            st.caption("Generated for review and follow-up; this application does not send email.")

        if reviewer_mode:
            _render_review_resolution(record, store)


def render_reviewer_workspace(
    store: AuditStore,
    persistent_history: list[dict],
    storage_error: str | None,
) -> None:
    st.subheader("Reviewer workspace")
    st.caption(
        "Persistent cross-session history and resolution controls are restricted to an "
        "authorised reviewer."
    )
    if storage_error:
        st.error(storage_error)
        return
    if not store.persistent:
        st.info(
            "Persistent review is not enabled. The public submission workflow and session "
            "history remain available."
        )
        return

    settings, config_error = load_reviewer_settings(_streamlit_secrets())
    if config_error:
        st.warning(config_error)
        return

    if not st.session_state.get("reviewer_authenticated", False):
        with st.form("reviewer_login"):
            access_code = st.text_input(
                "Reviewer access code",
                type="password",
                autocomplete="off",
            )
            submitted = st.form_submit_button(
                "Open reviewer workspace",
                type="primary",
                use_container_width=True,
            )
        if submitted:
            if reviewer_code_matches(access_code, settings.access_code):
                st.session_state.reviewer_authenticated = True
                st.session_state.reviewer_login_error = ""
                st.rerun()
            else:
                st.session_state.reviewer_login_error = "Access code was not accepted."
        if message := st.session_state.get("reviewer_login_error"):
            st.error(message)
        return

    action_column, logout_column = st.columns([5, 1])
    with action_column:
        st.success("Reviewer access active for this browser session.")
    with logout_column:
        if st.button("Sign out", type="secondary", use_container_width=True):
            st.session_state.reviewer_authenticated = False
            st.session_state.reviewer_login_error = ""
            st.rerun()

    if notice := st.session_state.pop("review_notice", None):
        st.success(notice)
    render_dashboard(
        persistent_history,
        store,
        reviewer_mode=True,
    )


def _render_vendor_case(records: list[dict], access_token: str) -> None:
    latest = records[-1]
    metric_columns = st.columns(4)
    metric_columns[0].metric("Case revisions", len(records))
    metric_columns[1].metric("Latest automated decision", latest["status"])
    metric_columns[2].metric(
        "Human review",
        latest.get("review_status", "Not reviewed"),
    )
    metric_columns[3].metric("Latest run", latest["run"])

    for record in reversed(records):
        revision = record.get("revision_number", 1)
        with st.expander(
            f"Revision {revision} · Run {record['run']} · {record['status']}",
            expanded=record is latest,
        ):
            _render_status_banner(
                record["status"],
                REASON_LABELS.get(
                    record.get("primary_code", "UNCLASSIFIED"),
                    "Review the case findings.",
                ),
            )
            st.dataframe(
                record.get("comparisons", []),
                use_container_width=True,
                hide_index=True,
            )
            findings = _record_findings(record)
            _render_findings(
                [finding["Code"] for finding in findings],
                [finding["Finding"] for finding in findings],
            )
            st.info(record["follow_up"])
            review_status = record.get("review_status", "Not reviewed")
            if review_status != "Not reviewed":
                st.markdown(f"**Reviewer outcome: {review_status}**")
                st.write(record.get("reviewer_notes") or "No reviewer notes were recorded.")
                st.caption(
                    f"Recorded by {record.get('reviewer_name') or 'Unknown reviewer'} · "
                    f"{_format_timestamp(record.get('reviewed_at', ''))}"
                )

    if latest.get("review_status") != "Correction requested":
        return
    st.warning(
        "A reviewer requested corrected information. Starting a revision preserves this "
        "original run and links the replacement submission to the same case."
    )
    if st.button(
        "Prepare corrected submission",
        type="primary",
        use_container_width=True,
        key="prepare_case_revision",
    ):
        st.session_state.active_revision_context = RevisionContext(
            case_id=latest["case_id"],
            access_token=access_token,
            parent_run_id=int(latest["run"]),
            revision_number=int(latest.get("revision_number", 1)) + 1,
        )
        st.rerun()


def render_case_tracker(
    store: AuditStore,
    storage_error: str | None,
) -> None:
    st.subheader("Track a case")
    st.caption(
        "Use the private case reference and tracking token issued at submission. The token "
        "is never stored in plaintext."
    )
    if storage_error:
        st.error(storage_error)
        return
    if not store.persistent:
        st.info("Secure case tracking is available when persistent audit storage is enabled.")
        return

    authentication = st.session_state.get("tracked_case_auth")
    if not authentication:
        with st.form("track_case_login"):
            case_id = st.text_input(
                "Case reference",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                autocomplete="off",
            )
            access_token = st.text_input(
                "Tracking token",
                type="password",
                autocomplete="off",
            )
            submitted = st.form_submit_button(
                "Open case",
                type="primary",
                use_container_width=True,
            )
        if submitted:
            normalized_case_id = normalize_case_id(case_id)
            if not tracking_credentials_valid(case_id, access_token):
                st.error("The case reference or tracking token is invalid.")
                return
            try:
                records = store.list_case_records(
                    normalized_case_id or "",
                    hash_access_token(access_token.strip()),
                )
            except AuditStoreError as exc:
                st.error(str(exc))
                return
            if not records:
                st.error("The case reference or tracking token is invalid.")
                return
            st.session_state.tracked_case_auth = {
                "case_id": normalized_case_id,
                "access_token": access_token.strip(),
            }
            st.rerun()
        return

    case_id = str(authentication["case_id"])
    access_token = str(authentication["access_token"])
    heading, forget_column = st.columns([5, 1])
    with heading:
        st.markdown(f"**Case reference:** `{case_id}`")
    with forget_column:
        if st.button("Close case", type="secondary", use_container_width=True):
            st.session_state.pop("tracked_case_auth", None)
            st.session_state.pop("active_revision_context", None)
            st.rerun()
    try:
        records = store.list_case_records(case_id, hash_access_token(access_token))
    except AuditStoreError as exc:
        st.error(str(exc))
        return
    if not records:
        st.session_state.pop("tracked_case_auth", None)
        st.error("The case could no longer be accessed with these credentials.")
        return
    _render_vendor_case(records, access_token)


def render_decision_guide() -> None:
    st.subheader("How the decision is made")
    st.caption("Gemini extracts. Deterministic Python rules decide.")

    stages = [
        ("1. Read", "PyMuPDF extracts actual embedded PDF text."),
        ("2. Extract", "Gemini returns typed fields with exact supporting excerpts."),
        ("3. Verify", "The application checks each excerpt against the source text."),
        ("4. Compare", "Identifiers and conservatively normalized names are cross-checked."),
        ("5. Decide", "History controls and explicit policy produce the final status."),
    ]
    columns = st.columns(len(stages))
    for column, (title, description) in zip(columns, stages, strict=False):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.caption(description)

    st.markdown("#### Status definitions")
    st.dataframe(
        [
            {
                "Status": "Approved",
                "Meaning": "Every required field is valid, supported, and internally consistent.",
            },
            {
                "Status": "Pending",
                "Meaning": "Correction, stronger evidence, or human review is required.",
            },
            {
                "Status": "Rejected",
                "Meaning": "An exact, document-supported blocking policy applies.",
            },
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.warning(
        "Current limitation: image-only scans are not OCR processed. They return Pending with "
        "instructions to upload a readable text-based PDF."
    )


def process_submission(
    submission: Submission,
    gst_pdf,
    bank_pdf,
    blocked_vendors,
    store: AuditStore,
    history: list[dict],
    storage_error: str | None = None,
    revision_context: RevisionContext | None = None,
) -> None:
    extractor = None
    gst_structured = None
    bank_structured = None
    case_credentials = None
    case_id = None
    case_token = None
    case_token_hash = None
    parent_run_id = None
    revision_number = 1
    if store.persistent:
        if revision_context:
            case_id = revision_context.case_id
            case_token = revision_context.access_token
            case_token_hash = revision_context.token_hash
            parent_run_id = revision_context.parent_run_id
            revision_number = revision_context.revision_number
        else:
            case_credentials = create_case_credentials()
            case_id = case_credentials.case_id
            case_token = case_credentials.access_token
            case_token_hash = case_credentials.token_hash
    with st.status("Processing vendor submission", expanded=True) as status:
        st.write("1/7 - Captured submitted form fields")
        st.write("2/7 - Reading embedded PDF text with PyMuPDF")
        gst_document = extract_pdf_text(gst_pdf.getvalue(), gst_pdf.name) if gst_pdf else None
        bank_document = extract_pdf_text(bank_pdf.getvalue(), bank_pdf.name) if bank_pdf else None

        st.write("3/7 - Loading Gemini configuration and checking model availability")
        settings, config_error = load_gemini_settings(_streamlit_secrets())
        if config_error:
            gst_structured = ExtractionOutcome(error=config_error)
            bank_structured = ExtractionOutcome(error=config_error)
        elif settings:
            extractor = GeminiDocumentExtractor(settings)
            if model_error := extractor.check_model():
                gst_structured = ExtractionOutcome(error=model_error)
                bank_structured = ExtractionOutcome(error=model_error)

        try:
            st.write("4/7 - Extracting GST fields into the validated schema")
            if gst_structured is None and gst_document and gst_document.is_readable and extractor:
                gst_structured = extractor.extract_gst(gst_document.text)

            st.write("5/7 - Extracting bank fields into the validated schema")
            if bank_structured is None and bank_document and bank_document.is_readable and extractor:
                bank_structured = extractor.extract_bank(bank_document.text)
        finally:
            if extractor:
                extractor.close()

        st.write("6/7 - Applying evidence, format, history, and policy checks")
        result = validate_submission(
            submission,
            gst_document,
            bank_document,
            gst_structured,
            bank_structured,
            blocked_vendors=blocked_vendors,
            prior_approvals=prior_approvals(history),
        )

        if storage_error:
            result = with_operational_pending(
                result,
                "AUDIT_HISTORY_UNAVAILABLE",
                "Persistent audit history could not be loaded, so previous approvals and bank-risk signals were not fully checked.",
                "Restore the Supabase connection and resubmit before approval.",
            )

        storage_label = "persistent" if store.persistent else "session"
        st.write(f"7/7 - Recording a privacy-safe {storage_label} audit entry")
        provisional_run = max(
            (int(record.get("run", 0)) for record in history),
            default=0,
        ) + 1
        record = make_run_record(submission, result, provisional_run)
        try:
            stored_record = store.append_record(
                record,
                case_id=case_id,
                access_token_hash=case_token_hash,
                parent_run_id=parent_run_id,
                revision_number=revision_number,
            )
        except AuditStoreError as exc:
            storage_error = str(exc)
            result = with_operational_pending(
                result,
                "AUDIT_SAVE_FAILED",
                "The automated checks completed, but the required persistent audit record could not be saved.",
                "Restore the Supabase connection and resubmit before approval.",
            )
            fallback = SessionAuditStore(st.session_state.run_history)
            stored_record = fallback.append_record(
                make_run_record(submission, result, provisional_run)
            )

        run_number = int(stored_record["run"])
        if store.persistent and not storage_error:
            st.session_state.run_history.append(stored_record)
            st.session_state.tracked_case_auth = {
                "case_id": case_id,
                "access_token": case_token,
            }
            if revision_context:
                st.session_state.pop("active_revision_context", None)
        status.update(label=f"Run {run_number} complete", state="complete", expanded=False)

    if storage_error:
        st.error(storage_error)
    render_result(result, run_number)
    if store.persistent and not storage_error and case_id and case_token:
        with st.container(border=True):
            if case_credentials:
                st.markdown("#### Save your private case access")
                st.warning(
                    "The tracking token is shown only for this submission. Save it now; "
                    "the application stores only its one-way hash."
                )
                st.markdown(f"**Case reference:** `{case_id}`")
                st.markdown("**Tracking token:**")
                st.code(case_token, language=None)
                st.download_button(
                    "Download case access",
                    data=(
                        "Vendor onboarding case access\n"
                        f"Case reference: {case_id}\n"
                        f"Tracking token: {case_token}\n"
                        "Keep this file private.\n"
                    ),
                    file_name=f"vendor-case-{case_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    key=f"download_case_access_{run_number}",
                )
            else:
                st.success(
                    f"Revision {revision_number} was linked to case {case_id}. The earlier "
                    "submission remains preserved in the case history."
                )
    with st.expander("Processing diagnostics"):
        for label, document in (
            ("GST registration", gst_document),
            ("Bank proof", bank_document),
        ):
            st.markdown(f"**{label}**")
            if document is None:
                st.write("No file supplied.")
            elif document.error:
                st.write(f"Could not read document: {document.error}")
            else:
                st.write(
                    f"Read {document.page_count} page(s) and extracted "
                    f"{len(document.text)} text character(s)."
                )
        st.caption(
            "Account-number evidence is masked in every visible result and audit record."
        )


def main() -> None:
    if "run_history" not in st.session_state:
        st.session_state.run_history = []
    blocked_vendors = load_blocked_vendors()
    session_store = SessionAuditStore(st.session_state.run_history)
    store, storage_error = _load_audit_store()
    persistent_history: list[dict] = []
    if store.persistent:
        try:
            persistent_history = store.list_records()
            history_for_checks = persistent_history
        except AuditStoreError as exc:
            storage_error = str(exc)
            store = session_store
            history_for_checks = session_store.list_records()
    else:
        history_for_checks = session_store.list_records()

    st.title("Vendor onboarding")
    st.caption("PS2 | Submission-to-decision workflow for Indian vendors")
    with st.container(border=True):
        st.markdown("**Evidence-first review**")
        st.write(
            "Gemini independently extracts fields from untrusted PDF text. Deterministic rules "
            "then verify excerpts, compare identities, review approved-history signals, and apply "
            "explicit policy."
        )

    submission_tab, tracking_tab, dashboard_tab, reviewer_tab, guide_tab = st.tabs(
        [
            "Submit vendor",
            "Track case",
            "My submissions",
            "Reviewer workspace",
            "Decision guide",
        ]
    )
    with submission_tab:
        st.subheader("New vendor submission")
        st.caption("Fields marked with * are required. Country support is currently limited to India.")
        revision_context = st.session_state.get("active_revision_context")
        if revision_context:
            with st.container(border=True):
                st.warning(
                    f"Preparing revision {revision_context.revision_number} for case "
                    f"{revision_context.case_id}. Enter all fields again and upload the corrected PDFs."
                )
                if st.button(
                    "Cancel correction",
                    type="secondary",
                    key="cancel_active_revision",
                ):
                    st.session_state.pop("active_revision_context", None)
                    st.rerun()
        with st.form("vendor_submission"):
            identity_column, bank_column = st.columns(2, gap="large")
            with identity_column:
                st.markdown("#### Company and contact")
                legal_name = st.text_input(
                    "Legal company name *",
                    placeholder="Name shown on the GST registration",
                    autocomplete="off",
                )
                contact_name = st.text_input(
                    "Contact name *",
                    placeholder="Primary vendor contact",
                    autocomplete="off",
                )
                contact_email = st.text_input(
                    "Contact email *",
                    placeholder="name@company.com",
                    autocomplete="off",
                )
                country = st.selectbox("Country *", ["India"], disabled=True)
                gstin = st.text_input(
                    "GSTIN *",
                    placeholder="15-character GST identification number",
                    help="The format and base-36 checksum are validated.",
                    autocomplete="off",
                )

            with bank_column:
                st.markdown("#### Payment details")
                beneficiary_name = st.text_input(
                    "Bank beneficiary name *",
                    placeholder="Name shown on the bank proof",
                    autocomplete="off",
                )
                account_number = st.text_input(
                    "Bank account number *",
                    type="password",
                    placeholder="6 to 18 digits",
                    help=(
                        "Account numbers are masked in comparison and audit views and are "
                        "not stored raw in run history."
                    ),
                    autocomplete="off",
                )
                ifsc = st.text_input(
                    "IFSC *",
                    placeholder="Example: HDFC0001234",
                    autocomplete="off",
                )
                st.info(
                    "A verified bank change after approval, or a bank account previously approved "
                    "for another GSTIN, is routed to manual review."
                )

            st.divider()
            st.markdown("#### Supporting documents")
            st.caption(
                "Upload text-based PDFs. Image-only scans are detected and returned as Pending; "
                "OCR is intentionally outside the current reliable demo path."
            )
            gst_upload_column, bank_upload_column = st.columns(2, gap="large")
            with gst_upload_column:
                gst_pdf = st.file_uploader(
                    "GST registration PDF *",
                    type=["pdf"],
                    help="Must clearly show the legal name and GSTIN.",
                )
            with bank_upload_column:
                bank_pdf = st.file_uploader(
                    "Bank proof PDF *",
                    type=["pdf"],
                    help="Must clearly show the beneficiary, account number, and IFSC.",
                )

            submitted = st.form_submit_button(
                (
                    "Submit corrected revision"
                    if revision_context
                    else "Run onboarding checks"
                ),
                type="primary",
                use_container_width=True,
            )

        if submitted:
            submission = Submission(
                legal_name,
                contact_name,
                contact_email,
                country,
                gstin,
                beneficiary_name,
                account_number,
                ifsc,
                gst_pdf is not None,
                bank_pdf is not None,
            )
            process_submission(
                submission,
                gst_pdf,
                bank_pdf,
                blocked_vendors,
                store,
                history_for_checks,
                storage_error,
                revision_context,
            )

    with tracking_tab:
        render_case_tracker(store, storage_error)

    with dashboard_tab:
        render_dashboard(
            session_store.list_records(),
            session_store,
        )

    with reviewer_tab:
        render_reviewer_workspace(store, persistent_history, storage_error)

    with guide_tab:
        render_decision_guide()


if __name__ == "__main__":
    main()
