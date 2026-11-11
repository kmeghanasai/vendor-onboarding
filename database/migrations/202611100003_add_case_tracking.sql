-- Private vendor case tracking and linked submission revisions.

alter table public.vendor_runs
    add column if not exists case_id uuid,
    add column if not exists revision_number integer not null default 1,
    add column if not exists access_token_hash text;

-- Existing runs receive references for internal consistency, but no public token.
update public.vendor_runs
set case_id = gen_random_uuid()
where case_id is null;

alter table public.vendor_runs
    alter column case_id set default gen_random_uuid(),
    alter column case_id set not null;

alter table public.vendor_runs
    drop constraint if exists vendor_runs_revision_number_check;
alter table public.vendor_runs
    add constraint vendor_runs_revision_number_check
        check (revision_number > 0);
alter table public.vendor_runs
    drop constraint if exists vendor_runs_access_token_hash_check;
alter table public.vendor_runs
    add constraint vendor_runs_access_token_hash_check
        check (
            access_token_hash is null
            or access_token_hash ~ '^[0-9a-f]{64}$'
        );

create unique index if not exists vendor_runs_case_revision_idx
    on public.vendor_runs (case_id, revision_number);
create index if not exists vendor_runs_case_token_idx
    on public.vendor_runs (case_id, access_token_hash);
create index if not exists vendor_runs_parent_run_idx
    on public.vendor_runs (parent_run_id);

-- A revision must point to an earlier run in the same case and reuse its token hash.
create or replace function public.validate_vendor_revision()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    parent_case public.vendor_runs;
begin
    if new.access_token_hash is null
        or new.access_token_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'New submissions require a valid tracking-token hash';
    end if;
    if new.parent_run_id is null then
        if new.revision_number <> 1 then
            raise exception 'An original submission must have revision number 1';
        end if;
        return new;
    end if;

    select * into parent_case
    from public.vendor_runs
    where id = new.parent_run_id;

    if not found then
        raise exception 'Parent run does not exist';
    end if;
    if parent_case.case_id <> new.case_id then
        raise exception 'Revision case does not match its parent';
    end if;
    if parent_case.access_token_hash is distinct from new.access_token_hash then
        raise exception 'Revision token does not match its parent';
    end if;
    if new.revision_number <> parent_case.revision_number + 1 then
        raise exception 'Revision number must follow its parent';
    end if;
    if parent_case.review_status <> 'Correction requested' then
        raise exception 'Parent run does not have an active correction request';
    end if;
    return new;
end;
$$;

drop trigger if exists validate_vendor_revision_trigger on public.vendor_runs;
create trigger validate_vendor_revision_trigger
before insert on public.vendor_runs
for each row execute function public.validate_vendor_revision();

revoke all on function public.validate_vendor_revision() from public, anon, authenticated;
grant execute on function public.validate_vendor_revision() to service_role;
