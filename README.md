# AI-assisted vendor onboarding

A Streamlit case-study application that turns Indian vendor details and supporting PDFs into an explainable onboarding decision. Gemini extracts evidence independently; deterministic Python rules validate, compare, and decide whether the case is `Approved`, `Pending`, or explicitly policy-based `Rejected`.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app/)

**Live demo:** [vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app](https://vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app/)

**Demo data:** [fictional PDFs and form-value guide](output/pdf/demo_documents/FORM_VALUES_GUIDE.md)

## What this project demonstrates

- Evidence-grounded extraction from real PDF text using PyMuPDF and the official Google Gen AI SDK.
- Structured Gemini responses validated with Pydantic and independently checked against exact source excerpts.
- Conservative, deterministic approval rules with no fuzzy matching or LLM-generated final decisions.
- Persistent, privacy-aware audit history, human review, correction requests, and linked resubmissions using Supabase.
- Operational edge cases including changed bank details, shared accounts across GSTINs, mixed identities, unsupported evidence, and an explicit synthetic blocklist.

## Workflow

```mermaid
flowchart LR
    A[Vendor form + PDFs] --> B[PyMuPDF text extraction]
    B --> C[Gemini structured extraction]
    C --> D[Schema + excerpt verification]
    D --> E[Deterministic comparisons]
    E --> F{Decision}
    F -->|Consistent| G[Approved]
    F -->|Review or correction needed| H[Pending]
    F -->|Explicit policy rule| I[Rejected]
    H --> J[Human review]
    J --> K[Correction request]
    K --> L[Linked revision]
    G --> M[Privacy-safe audit history]
    H --> M
    I --> M
    L --> M
```

The LLM never receives the submitted form values and never makes the final decision. Document text is treated as untrusted input. Python verifies that every claimed excerpt exists in the source text before applying validation, history, and policy rules.

## Technology

| Area | Tools |
| --- | --- |
| Application UI | Python, Streamlit |
| PDF processing | PyMuPDF |
| Structured extraction | Google Gen AI SDK (`google-genai`), Gemini, Pydantic |
| Decision engine | Deterministic Python validation and policy rules |
| Persistent workflow | Supabase/PostgreSQL with Row Level Security and SQL migrations |
| Demo assets and testing | ReportLab, pytest, mocked Gemini responses |

## Decision rules

- `Approved` only when all required fields are valid, GSTIN checksum validation passes, both documents are readable, every extracted value has an exact source excerpt, all comparisons match, the verified GST and bank identities are consistent, no history risk is detected, and no blocking policy applies.
- `Pending` for incomplete or invalid input, unreadable evidence, extraction failures, unsupported fields, document discrepancies, cross-document identity review, changed bank details for a previously Approved GSTIN, or a verified account previously Approved for another GSTIN.
- `Rejected` only when the submitted GSTIN is checksum-valid, matches the GST document, and exactly matches the explicit synthetic policy in `data/blocked_vendors.json`.
- Company names are normalized for case, punctuation, and whitespace only. Fuzzy matching never auto-approves.
- Approval means internal consistency checks passed. It is not government registration or bank-account verification.

The extraction prompt receives PDF text but never submitted form values. PDF text is treated as untrusted data. Gemini responses are validated with Pydantic, and supporting excerpts are verified deterministically against the actual PyMuPDF text.

## UI, evidence, and audit behavior

The application has five views:

- **Submit vendor** - a two-column form, live seven-stage processing view, decision summary, field comparison, evidence provenance, and a generated follow-up action.
- **Track case** - private case lookup using a UUID reference and high-entropy token, with linked correction revisions when requested by a reviewer.
- **My submissions** - status metrics, filters, search, masked accounts, and details for runs created only in the current browser session.
- **Reviewer workspace** - access-code-protected persistent queue, complete evidence review, and a recorded human resolution for automated Pending cases.
- **Decision guide** - a plain-language explanation of the workflow, statuses, and current OCR limitation.

Audit history supports two explicit modes. `session` is the zero-configuration local fallback; `supabase` persists runs across browsers, restarts, and deployments. Persistent history is never displayed in the public session dashboard: only a reviewer with the configured access code can open the global queue. A vendor can retrieve only one authorised case using its reference and private tracking token. The plaintext token is shown once and never stored; only its SHA-256 hash is retained. Tokens are entered through the form rather than placed in URLs or browser history. Raw account numbers, PDF files, and raw PDF text are not stored in either mode. A one-way account fingerprint is retained only to detect changed details or an account already Approved for another GSTIN. Account-like numeric sequences are masked across all evidence excerpts before display or audit storage. If configured persistent history cannot be read or written, the run cannot remain `Approved`. Follow-up text is generated for review; the application does not send email.

## Windows setup

From PowerShell in this project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Gemini configuration

Copy the example and set a real key plus a model available to that key:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

The app verifies `GEMINI_MODEL` through the models API before extraction. It uses a 30-second request timeout and at most three attempts for transient HTTP failures. Never commit or print the API key; the real secrets file is ignored by Git.

To list the models available to your key that support `generateContent`, using the values in your local `.streamlit/secrets.toml` without printing the key:

```powershell
python -c "from pathlib import Path; import tomllib; from google import genai; s=tomllib.loads(Path('.streamlit/secrets.toml').read_text(encoding='utf-8')); c=genai.Client(api_key=s['GEMINI_API_KEY']); print('\n'.join(m.name for m in c.models.list() if 'generateContent' in (m.supported_actions or []))); c.close()"
```

Copy one returned model name exactly into `GEMINI_MODEL` in `.streamlit/secrets.toml`, then restart Streamlit.

## Persistent audit history with Supabase

Session history remains the default so the project runs without external infrastructure. To enable durable history:

1. Create a Supabase project.
2. Open its SQL Editor and execute these migrations in order:
   - `database/migrations/202611090001_create_vendor_runs.sql`
   - `database/migrations/202611090002_add_review_events.sql`
   - `database/migrations/202611100003_add_case_tracking.sql`
3. Add the following values to the local `.streamlit/secrets.toml` and to the deployed app's Streamlit secrets:

```toml
AUDIT_BACKEND = "supabase"
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SECRET_KEY = "YOUR_SERVER_SIDE_SUPABASE_SECRET_KEY"
SUPABASE_AUDIT_TABLE = "vendor_runs"
REVIEWER_ACCESS_CODE = "YOUR_LONG_RANDOM_REVIEWER_ACCESS_CODE"
```

Use a server-side Supabase secret key, never a publishable key for this adapter. Never commit or display that key. Use a random reviewer access code containing at least 12 characters and share it only with the intended evaluator. The migrations enable Row Level Security, remove direct `anon` and `authenticated` access, and grant the server role access. The Streamlit Python process is the only database caller.

After restarting, submit an Approved demo, download its private case-access file, and confirm it appears under **My submissions**. Use **Track case** to retrieve only that case. Sign in through **Reviewer workspace**, then refresh the browser or open a separate reviewer browser and confirm that the persistent run remains visible. An automated Pending case can be resolved once as `Approved`, `Rejected`, or `Correction requested`; its original automated findings remain unchanged and a separate append-only review event records the reviewer, notes, outcome, and timestamp. A correction request allows the token holder to create a linked revision without overwriting the original run. A database configuration or availability failure is displayed and routes the submission to `Pending` rather than silently skipping historical checks.

## Run

```powershell
python -m streamlit run app.py
```

Streamlit normally opens `http://localhost:8501`.

## Repository structure

```text
app.py                    Streamlit entry point
vendor_ui.py              Submission, tracking, review, and dashboard views
document_extraction.py    PyMuPDF document text extraction
gemini_extraction.py      Structured Gemini extraction and evidence schema
validation.py             Deterministic validation and cross-checking
audit_store.py            Session and Supabase audit adapters
case_tracking.py          Private case references and linked revisions
reviewer_access.py        Protected human-review workflow
policy.py                 Explicit synthetic rejection policy
database/migrations/      Supabase schema, review, and case-tracking migrations
output/pdf/demo_documents Fictional PDFs and form-value guide
tests/                    Unit and mocked end-to-end pipeline tests
```

## Tests

```powershell
python -m pytest -q
```

Tests mock Gemini responses and do not require an API key or network access.

## Deployment

The application is deployed from `main` on Streamlit Community Cloud. Configure the same values shown in `.streamlit/secrets.toml.example` through the app's **Settings → Secrets** panel; never upload the real local secrets file. After deployment, enable public access and verify the live URL in a signed-out or incognito browser.

## Synthetic demos

The fictional PDFs and exact form values are documented in `output/pdf/demo_documents/FORM_VALUES_GUIDE.md`. The scenarios cover:

- Matching happy path
- Legitimate trade-name/proprietor-name review
- Mixed-identity evidence
- Changed bank details after a prior approval
- A shared bank account across different GSTINs
- Explicit internal blocklist rejection

Regenerate the PDFs with:

```powershell
python scripts/generate_demo_pdfs.py
```

## Current scope

This is a working case-study workflow rather than an external verification service. It intentionally does not send email, OCR image-only scans, query government registries, or verify ownership with a bank. Those cases are disclosed clearly and routed to `Pending` rather than being presented as verified or approved.
