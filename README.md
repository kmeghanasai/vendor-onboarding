# Vendor onboarding - PS2 case study

A Streamlit workflow that accepts Indian vendor details and text-based evidence PDFs, extracts supported fields with Gemini, and produces an auditable `Approved`, `Pending`, or policy-based `Rejected` decision.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app/)

**Live demo:** [vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app](https://vendor-app-4fdve22vgswexxnsqmknxf.streamlit.app/)

## Decision rules

- `Approved` only when all required fields are valid, GSTIN checksum validation passes, both documents are readable, every extracted value has an exact source excerpt, all comparisons match, no history risk is detected, and no blocking policy applies.
- `Pending` for incomplete or invalid input, unreadable evidence, extraction failures, unsupported fields, document discrepancies, name-review cases, changed bank details for a previously Approved GSTIN, or a verified account previously Approved for another GSTIN.
- `Rejected` only when the submitted GSTIN is checksum-valid, matches the GST document, and exactly matches the explicit synthetic policy in `data/blocked_vendors.json`.
- Company names are normalized for case, punctuation, and whitespace only. Fuzzy matching never auto-approves.
- Approval means internal consistency checks passed. It is not government registration or bank-account verification.

The extraction prompt receives PDF text but never submitted form values. PDF text is treated as untrusted data. Gemini responses are validated with Pydantic, and supporting excerpts are verified deterministically against the actual PyMuPDF text.

## UI, evidence, and audit behavior

The application has three views:

- **Submit vendor** - a two-column form, live seven-stage processing view, decision summary, field comparison, and evidence provenance.
- **Audit dashboard** - status metrics, filters, search, concise primary reasons, masked accounts, and a selected-run review panel.
- **Decision guide** - a plain-language explanation of the workflow, statuses, and current OCR limitation.

History is intentionally session-only for this take-home milestone. Raw account numbers are not stored in history. A one-way fingerprint is retained only to detect changed details or an account already Approved for another GSTIN. Supporting account excerpts are masked before display or audit storage.

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

## Run

```powershell
python -m streamlit run app.py
```

Streamlit normally opens `http://localhost:8501`.

## Tests

```powershell
python -m pytest -q
```

Tests mock Gemini responses and do not require an API key or network access.

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

This milestone intentionally has no persistent database, email sending, OCR, government lookup, or bank verification.
