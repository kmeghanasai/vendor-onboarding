"""Streamlit user interface for the PS2 vendor-onboarding workflow."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from document_extraction import extract_pdf_text
from gemini_extraction import ExtractionOutcome, GeminiDocumentExtractor, load_gemini_settings
from policy import load_blocked_vendors
from run_history import make_run_record, prior_approvals
from validation import (
    Submission,
    ValidationResult,
    mask_account,
    mask_account_text,
    validate_submission,
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
    "UNCLASSIFIED": "Review required",
}


def _streamlit_secrets() -> dict[str, object]:
    try:
        return {name: st.secrets.get(name, "") for name in ("GEMINI_API_KEY", "GEMINI_MODEL")}
    except Exception:
        return {}


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
            "Supporting excerpt": (
                mask_account_text(row.excerpt)
                if row.field == "Bank account number"
                else row.excerpt or "Not available"
            ),
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


def render_dashboard() -> None:
    history = st.session_state.run_history
    heading, clear_column = st.columns([5, 1])
    with heading:
        st.subheader("Run history")
        st.caption(
            "Session-only audit trail. Account numbers are masked, and raw account numbers "
            "are never stored in history."
        )
    with clear_column:
        if history and st.button("Clear history", type="secondary", use_container_width=True):
            st.session_state.run_history = []
            st.rerun()

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
        )
    with search_column:
        search_text = st.text_input(
            "Search",
            placeholder="Company name or GSTIN",
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
        detail_columns = st.columns(4)
        detail_columns[0].metric("Run", record["run"])
        detail_columns[1].metric("Decision", record["status"])
        detail_columns[2].metric("Account", record["account_display"])
        detail_columns[3].metric("IFSC", record["ifsc"])
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
) -> None:
    extractor = None
    gst_structured = None
    bank_structured = None
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
            prior_approvals=prior_approvals(st.session_state.run_history),
        )

        st.write("7/7 - Recording a privacy-safe session audit entry")
        run_number = len(st.session_state.run_history) + 1
        record = make_run_record(submission, result, run_number)
        st.session_state.run_history.append(record)
        status.update(label=f"Run {run_number} complete", state="complete", expanded=False)

    render_result(result, run_number)
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

    st.title("Vendor onboarding")
    st.caption("PS2 | Submission-to-decision workflow for Indian vendors")
    with st.container(border=True):
        st.markdown("**Evidence-first review**")
        st.write(
            "Gemini independently extracts fields from untrusted PDF text. Deterministic rules "
            "then verify excerpts, compare identities, review approved-history signals, and apply "
            "explicit policy."
        )

    submission_tab, dashboard_tab, guide_tab = st.tabs(
        ["Submit vendor", "Audit dashboard", "Decision guide"]
    )
    with submission_tab:
        st.subheader("New vendor submission")
        st.caption("Fields marked with * are required. Country support is currently limited to India.")
        with st.form("vendor_submission"):
            identity_column, bank_column = st.columns(2, gap="large")
            with identity_column:
                st.markdown("#### Company and contact")
                legal_name = st.text_input(
                    "Legal company name *",
                    placeholder="Name shown on the GST registration",
                )
                contact_name = st.text_input(
                    "Contact name *",
                    placeholder="Primary vendor contact",
                )
                contact_email = st.text_input(
                    "Contact email *",
                    placeholder="name@company.com",
                )
                country = st.selectbox("Country *", ["India"], disabled=True)
                gstin = st.text_input(
                    "GSTIN *",
                    placeholder="15-character GST identification number",
                    help="The format and base-36 checksum are validated.",
                )

            with bank_column:
                st.markdown("#### Payment details")
                beneficiary_name = st.text_input(
                    "Bank beneficiary name *",
                    placeholder="Name shown on the bank proof",
                )
                account_number = st.text_input(
                    "Bank account number *",
                    type="password",
                    placeholder="6 to 18 digits",
                    help="The full account number is never displayed or stored in run history.",
                )
                ifsc = st.text_input(
                    "IFSC *",
                    placeholder="Example: HDFC0001234",
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
                "Run onboarding checks",
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
            process_submission(submission, gst_pdf, bank_pdf, blocked_vendors)

    with dashboard_tab:
        render_dashboard()

    with guide_tab:
        render_decision_guide()


if __name__ == "__main__":
    main()
