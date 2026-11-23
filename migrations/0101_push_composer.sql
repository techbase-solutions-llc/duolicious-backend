-- 0101_push_composer.sql (TEC-2182)
-- The push composer and the 3 automatic pushes (plan
-- docs/plans/2026-11-19-push-composer.md).
--
--   notification_preference.push_announcements  the member's "Ahavah news
--       and suggestions" toggle, default on; push_announcements_off_at is
--       stamped when it is turned off, as push_questions_off_at is.
--   push_composer_send       one row per composed push: a draft, then the
--       frozen send. The text, url and filters never change once the row
--       has left draft or tested. The counts are recomputed from
--       push_composer_recipient after every pass.
--   push_composer_recipient  the audience, frozen at the send's first pass:
--       one row per member and the state they reached, so nobody leaves a
--       send without being counted (held, capped, expired, failed, sent,
--       released by a cancel, or skipped because they left the audience).
--   push_tap                 the src check gains apush (the composer) and
--       lwpush, nnpush and uspush (the automatic pushes); send_id ties a
--       composer tap to its send.
--
-- Additive and idempotent, as the deploy needs. Never edit once shipped; a
-- change is the next number.

-- The constraint swap on push_tap and the key on person take locks: give
-- up rather than queue sign-ins.
SET lock_timeout = '5s';

ALTER TABLE notification_preference
  ADD COLUMN IF NOT EXISTS push_announcements BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS push_announcements_off_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS push_composer_send (
  id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  title              TEXT         NOT NULL CHECK (char_length(title) BETWEEN 1 AND 50),
  body               TEXT         NOT NULL CHECK (char_length(body) BETWEEN 1 AND 120),
  url                TEXT         NOT NULL,
  filters            JSONB        NOT NULL DEFAULT '{}'::jsonb,
  testers_only       BOOLEAN      NOT NULL DEFAULT FALSE,
  content_hash       TEXT         NOT NULL,
  idempotency_key    TEXT         UNIQUE,
  state              TEXT         NOT NULL DEFAULT 'draft' CHECK (state IN
                     ('draft', 'tested', 'scheduled', 'sending', 'sent', 'cancelled', 'failed')),
  scheduled_for      TIMESTAMPTZ,
  mode               TEXT         CHECK (mode IS NULL OR mode IN ('barbados', 'member_local')),
  -- member_local only: the wall-clock time each member gets it at.
  local_at           TIMESTAMP,
  hold_until         TIMESTAMPTZ,
  test_delivered_at  TIMESTAMPTZ,
  tested_hash        TEXT,
  test_result        TEXT,
  halt_reason        TEXT,
  created_by         TEXT,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  started_at         TIMESTAMPTZ,
  finished_at        TIMESTAMPTZ,
  cancelled_at       TIMESTAMPTZ,
  audience           INT,
  sent               INT          NOT NULL DEFAULT 0,
  held               INT          NOT NULL DEFAULT 0,
  capped             INT          NOT NULL DEFAULT 0,
  failed             INT          NOT NULL DEFAULT 0,
  expired            INT          NOT NULL DEFAULT 0,
  released           INT          NOT NULL DEFAULT 0,
  skipped            INT          NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS push_composer_send_due_idx
  ON push_composer_send (scheduled_for)
  WHERE state IN ('scheduled', 'sending');

CREATE INDEX IF NOT EXISTS push_composer_send_created_idx
  ON push_composer_send (created_at DESC);

CREATE TABLE IF NOT EXISTS push_composer_recipient (
  send_id     UUID         NOT NULL REFERENCES push_composer_send(id) ON DELETE CASCADE,
  person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  state       TEXT         NOT NULL DEFAULT 'pending' CHECK (state IN
              ('pending', 'held', 'claimed', 'sent', 'capped', 'failed', 'expired', 'released', 'skipped')),
  reason      TEXT,
  attempts    INT          NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (send_id, person_id)
);

-- Serves the key's ON DELETE CASCADE when a person row is hard-deleted.
CREATE INDEX IF NOT EXISTS push_composer_recipient_person_idx
  ON push_composer_recipient (person_id);

ALTER TABLE push_tap ADD COLUMN IF NOT EXISTS send_id UUID;

ALTER TABLE push_tap
  DROP CONSTRAINT IF EXISTS push_tap_src_check,
  ADD CONSTRAINT push_tap_src_check
    CHECK (src IN ('qpush', 'mpush', 'lpush', 'mmalert', 'mmintro', 'mmtold',
                   'apush', 'lwpush', 'nnpush', 'uspush'));

CREATE INDEX IF NOT EXISTS idx__push_tap__send
  ON push_tap (send_id, person_id)
  WHERE send_id IS NOT NULL;

RESET lock_timeout;
