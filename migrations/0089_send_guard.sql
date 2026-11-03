-- 0089_send_guard.sql
-- The send guard's record (send safeguards plan, 2 Nov 2026, task 1).
-- smtp/guard.py counts and decides in Redis; the sendguard cron moves what
-- it saw here every minute, so the stats route, the watchdog and the owner
-- can read it after a Redis restart.
--
--   send_guard_event  every refusal, halt, alert and clearing the gate
--                     recorded. No address: `recipient` is a hash
--                     (first 16 hex characters of SHA-256 of the
--                     lower-cased address), or p<person id> for a push.
--   send_tally        sends, refusals and failures per hour, channel and
--                     kind.
--   send_guard_halt   every halt, open until the owner clears it. The cron
--                     puts back in Redis any open halt Redis has lost.
--
-- Idempotent: the deploy may run this file more than once.

CREATE TABLE IF NOT EXISTS send_guard_event (
  id         BIGSERIAL    PRIMARY KEY,
  at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  channel    TEXT         NOT NULL,
  event      TEXT         NOT NULL,
  kind       TEXT,
  rule       TEXT,
  recipient  TEXT,
  alert      BOOLEAN      NOT NULL DEFAULT FALSE,
  detail     JSONB        NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS send_guard_event_at_idx ON send_guard_event (at DESC);
CREATE INDEX IF NOT EXISTS send_guard_event_event_at_idx ON send_guard_event (event, at DESC);

CREATE TABLE IF NOT EXISTS send_tally (
  hour     TIMESTAMPTZ  NOT NULL,
  channel  TEXT         NOT NULL,
  kind     TEXT         NOT NULL,
  outcome  TEXT         NOT NULL,
  count    INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (hour, channel, kind, outcome)
);

CREATE TABLE IF NOT EXISTS send_guard_halt (
  id          BIGSERIAL    PRIMARY KEY,
  channel     TEXT         NOT NULL,
  scope       TEXT         NOT NULL CHECK (scope IN ('all', 'kind')),
  kind        TEXT,
  set_at      TIMESTAMPTZ  NOT NULL,
  reason      TEXT,
  cleared_at  TIMESTAMPTZ,
  cleared_by  TEXT,
  CHECK ((scope = 'all') = (kind IS NULL))
);

-- One open halt per channel and kind.
CREATE UNIQUE INDEX IF NOT EXISTS send_guard_halt_open_idx
  ON send_guard_halt (channel, scope, COALESCE(kind, ''))
  WHERE cleared_at IS NULL;
