-- Privacy-safe, append-only automated run history.
-- Execute this migration in the Supabase SQL Editor before enabling the backend.

create table if not exists public.vendor_runs (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    company text not null,
    gstin text not null,
    automated_status text not null
        check (automated_status in ('Approved', 'Pending', 'Rejected')),
    primary_code text not null,
    account_display text not null,
    account_fingerprint text not null,
    ifsc text not null,
    audit_record jsonb not null,
    review_status text not null default 'Not reviewed'
        check (review_status in ('Not reviewed', 'Approved', 'Rejected', 'Correction requested')),
    reviewer_name text,
    reviewer_notes text,
    reviewed_at timestamptz,
    parent_run_id bigint references public.vendor_runs(id)
);

create index if not exists vendor_runs_created_at_idx
    on public.vendor_runs (created_at desc);
create index if not exists vendor_runs_gstin_idx
    on public.vendor_runs (gstin);
create index if not exists vendor_runs_account_fingerprint_idx
    on public.vendor_runs (account_fingerprint);
create index if not exists vendor_runs_automated_status_idx
    on public.vendor_runs (automated_status);

alter table public.vendor_runs enable row level security;

-- The Streamlit server uses a secret key. Browser roles receive no direct access.
revoke all on table public.vendor_runs from anon, authenticated;
revoke all on sequence public.vendor_runs_id_seq from anon, authenticated;
grant all on table public.vendor_runs to service_role;
grant usage, select on sequence public.vendor_runs_id_seq to service_role;
