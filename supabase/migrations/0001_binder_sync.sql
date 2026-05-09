-- Binder collection sync schema.
--
-- Personal-sync model: no auth, no email, no accounts. The user picks a
-- passphrase they'll remember on both devices. Every sync:
--   1. Client computes key_hash = SHA-256("binder-sync-v1:" + passphrase)
--   2. Client AES-GCM encrypts local state with a PBKDF2-derived key
--      (also derived from the passphrase)
--   3. Client upserts the ciphertext into the row at key_hash
--   4. Pull is the same key lookup; client decrypts locally
--
-- The server only ever sees opaque ciphertext and an opaque hash. There's
-- nothing here that identifies a person, even if the database leaked.
--
-- Run this once in Supabase → SQL Editor → New query → paste → Run.

create table if not exists public.binder_sync (
  key_hash    text        primary key,
  ciphertext  text        not null,
  updated_at  timestamptz not null default now()
);

alter table public.binder_sync enable row level security;

-- Anonymous full access. Security comes from client-side encryption +
-- the unguessable key_hash, not row-level scoping. This is a deliberate
-- tradeoff for the no-auth model — see the file header.
drop policy if exists "anon all access" on public.binder_sync;
create policy "anon all access"
  on public.binder_sync
  for all
  to anon
  using (true)
  with check (true);

-- Optional: prune rows untouched for a year so abandoned passphrases
-- don't accumulate forever. Run manually or via pg_cron when desired.
-- delete from public.binder_sync where updated_at < now() - interval '1 year';
