-- Supabase schema for saving lotto draw results.
-- Run this in the Supabase SQL editor.
-- Intended for server-side inserts from a Vercel API route or server function.

create extension if not exists pgcrypto;

create table if not exists public.lotto_draws (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  birth_date date not null,
  zodiac text not null,
  numbers int[] not null,
  seed bigint not null,
  reply text not null,
  disclaimer text not null default '별자리와 로또 해석은 오락용입니다.',
  selection_basis text not null,
  source text not null default 'OpenAI',
  client_ip text,
  user_agent text
);

grant usage on schema public to service_role;
grant select, insert, update, delete on table public.lotto_draws to service_role;

create index if not exists lotto_draws_created_at_idx
  on public.lotto_draws (created_at desc);

create index if not exists lotto_draws_birth_date_idx
  on public.lotto_draws (birth_date);

create index if not exists lotto_draws_zodiac_idx
  on public.lotto_draws (zodiac);

alter table public.lotto_draws enable row level security;

do $$
begin
  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'lotto_draws'
      and policyname = 'allow service role full access'
  ) then
    create policy "allow service role full access"
      on public.lotto_draws
      for all
      to service_role
      using (true)
      with check (true);
  end if;
end $$;

comment on table public.lotto_draws is
  'Stores lotto draw results generated from a birth date, zodiac sign, and AI explanation.';
