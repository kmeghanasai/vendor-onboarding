-- Append-only human review events and an atomic resolution function.

create table if not exists public.vendor_review_events (
    id bigint generated always as identity primary key,
    run_id bigint not null unique references public.vendor_runs(id),
    review_status text not null
        check (review_status in ('Approved', 'Rejected', 'Correction requested')),
    reviewer_name text not null,
    reviewer_notes text not null,
    reviewed_at timestamptz not null default now()
);

create index if not exists vendor_review_events_reviewed_at_idx
    on public.vendor_review_events (reviewed_at desc);

alter table public.vendor_review_events enable row level security;
revoke all on table public.vendor_review_events from anon, authenticated;
revoke all on sequence public.vendor_review_events_id_seq from anon, authenticated;
grant all on table public.vendor_review_events to service_role;
grant usage, select on sequence public.vendor_review_events_id_seq to service_role;

create or replace function public.resolve_vendor_run(
    p_run_id bigint,
    p_review_status text,
    p_reviewer_name text,
    p_reviewer_notes text
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    resolved_run public.vendor_runs;
begin
    if p_review_status not in ('Approved', 'Rejected', 'Correction requested') then
        raise exception 'Unsupported reviewer outcome';
    end if;
    if char_length(btrim(p_reviewer_name)) < 2
        or char_length(btrim(p_reviewer_name)) > 80 then
        raise exception 'Reviewer name must contain 2 to 80 characters';
    end if;
    if char_length(btrim(p_reviewer_notes)) < 10
        or char_length(btrim(p_reviewer_notes)) > 1000 then
        raise exception 'Reviewer notes must contain 10 to 1000 characters';
    end if;

    update public.vendor_runs
    set review_status = p_review_status,
        reviewer_name = btrim(p_reviewer_name),
        reviewer_notes = btrim(p_reviewer_notes),
        reviewed_at = now()
    where id = p_run_id
      and automated_status = 'Pending'
      and review_status = 'Not reviewed'
    returning * into resolved_run;

    if not found then
        raise exception 'Run is not Pending, was already resolved, or does not exist';
    end if;

    insert into public.vendor_review_events (
        run_id,
        review_status,
        reviewer_name,
        reviewer_notes,
        reviewed_at
    ) values (
        resolved_run.id,
        resolved_run.review_status,
        resolved_run.reviewer_name,
        resolved_run.reviewer_notes,
        resolved_run.reviewed_at
    );

    return jsonb_build_object(
        'run', resolved_run.id,
        'review_status', resolved_run.review_status,
        'reviewer_name', resolved_run.reviewer_name,
        'reviewer_notes', resolved_run.reviewer_notes,
        'reviewed_at', resolved_run.reviewed_at
    );
end;
$$;

revoke all on function public.resolve_vendor_run(bigint, text, text, text)
    from public, anon, authenticated;
grant execute on function public.resolve_vendor_run(bigint, text, text, text)
    to service_role;
