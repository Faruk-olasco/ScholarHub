-- ScholarHub — Supabase schema. Paste this whole file into Supabase → SQL Editor → Run.

create table if not exists scholarships (
  id            text primary key,
  title         text not null,
  url           text not null,
  source        text,
  summary       text,
  published     timestamptz,
  deadline      date,
  countries     text default '',
  regions       text default '',
  levels        text default '',
  fields        text default '',
  funding       text default '',
  tier          text default 'aggregator',
  first_seen    timestamptz default now(),
  last_seen     timestamptz default now()
);
create index if not exists scholarships_deadline_idx on scholarships (deadline);
create index if not exists scholarships_first_seen_idx on scholarships (first_seen desc);
create index if not exists scholarships_tier_idx on scholarships (tier);
create index if not exists scholarships_regions_idx on scholarships using gin (to_tsvector('simple', regions));
create index if not exists scholarships_search_idx on scholarships using gin (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'')));

create table if not exists sources (
  id            bigserial primary key,
  name          text unique not null,
  url           text not null,
  kind          text default 'rss',        -- rss | html | brave
  tier          text default 'aggregator', -- official | aggregator | search
  enabled       boolean default true,
  last_run      timestamptz,
  last_status   text,
  last_count    int default 0,
  etag          text,
  last_modified text,
  checks        int default 0,
  changes       int default 0
);

create table if not exists runs (
  id          bigserial primary key,
  started     timestamptz default now(),
  finished    timestamptz,
  new_items   int default 0,
  total_items int default 0,
  notes       text
);

create table if not exists subscribers (
  id        bigserial primary key,
  channel   text not null,          -- email | telegram
  address   text not null,
  keywords  text default '',
  level     text default '',
  country   text default '',
  created   timestamptz default now(),
  unique (channel, address)
);

-- Row Level Security: the app uses the public "anon" key, so lock everything down except what it needs.
alter table scholarships enable row level security;
alter table sources      enable row level security;
alter table runs         enable row level security;
alter table subscribers  enable row level security;

drop policy if exists "public read scholarships" on scholarships;
create policy "public read scholarships" on scholarships for select using (true);

drop policy if exists "public read runs" on runs;
create policy "public read runs" on runs for select using (true);

drop policy if exists "public subscribe" on subscribers;
create policy "public subscribe" on subscribers for insert with check (true);
-- (sources are written only by the crawler, which uses the service_role key and bypasses RLS)

-- Handy view for the app's stats
create or replace view app_stats as
select
  (select count(*) from scholarships)                                                        as total,
  (select count(*) from scholarships where deadline is null or deadline >= current_date)      as active,
  (select count(*) from scholarships where deadline between current_date and current_date + 14) as closing_soon,
  (select count(*) from scholarships where tier = 'official')                                 as official,
  (select count(distinct source) from scholarships)                                           as publishers,
  (select max(finished) from runs)                                                            as last_run;
grant select on app_stats to anon, authenticated;

-- Auto-delete listings whose deadline passed more than 30 days ago (keeps the table lean). Run by crawler too.
create or replace function purge_expired() returns void language sql as $$
  delete from scholarships where deadline is not null and deadline < current_date - 30;
$$;

-- Links queued from the app (Admin → "Pull from link"); processed by the next crawl / manual run.
create table if not exists pull_requests (
  id             bigserial primary key,
  url            text not null,
  save_as_source boolean default true,
  deep           boolean default false,
  status         text default 'pending',   -- pending | done | error
  found          int, new_items int, error text,
  created        timestamptz default now(),
  processed      timestamptz
);
alter table pull_requests enable row level security;
drop policy if exists "app can queue links" on pull_requests;
create policy "app can queue links" on pull_requests for insert with check (true);
drop policy if exists "app can read queue" on pull_requests;
create policy "app can read queue" on pull_requests for select using (true);
