-- 0093_support_messages.sql (TEC-2115, docs/plans/2026-11-05-support-messages-in-admin.md)
-- Idempotent: safe to run more than once.
--
--   support_message      one row per message sent to support@ahavah.app,
--                        copied from the mailbox by the supportinbox cron
--                        (service/support_inbox). gmail_message_id is the
--                        idempotency point: a message seen twice is stored
--                        once. person_id is the member whose account email
--                        matches the sender, when exactly one does. Rows are
--                        deleted a year after received_at by the
--                        lead_retention cron.
--   support_inbox_state  the poller's cursor, one row per mailbox: the Gmail
--                        history id it has read up to, the backfill's page
--                        token while the first full read is under way, and
--                        when it last checked. last_error holds an error
--                        class name only, never message content.
BEGIN;

CREATE TABLE IF NOT EXISTS support_message (
  id                BIGSERIAL    PRIMARY KEY,
  gmail_message_id  TEXT         NOT NULL UNIQUE,
  gmail_thread_id   TEXT         NOT NULL,
  from_address      TEXT         NOT NULL,
  from_name         TEXT,
  subject           TEXT         NOT NULL DEFAULT '',
  body_text         TEXT         NOT NULL DEFAULT '',
  received_at       TIMESTAMPTZ  NOT NULL,
  person_id         INT          REFERENCES person(id) ON DELETE SET NULL,
  status            TEXT         NOT NULL DEFAULT 'open',
  handled_by        TEXT,
  handled_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE support_message DROP CONSTRAINT IF EXISTS support_message_status_check;
ALTER TABLE support_message ADD CONSTRAINT support_message_status_check
  CHECK (status IN ('open', 'handled', 'not_for_us'));

ALTER TABLE support_message DROP CONSTRAINT IF EXISTS support_message_body_text_check;
ALTER TABLE support_message ADD CONSTRAINT support_message_body_text_check
  CHECK (char_length(body_text) <= 20000);

CREATE INDEX IF NOT EXISTS support_message_status_received_at_idx
  ON support_message (status, received_at);
CREATE INDEX IF NOT EXISTS support_message_received_at_idx
  ON support_message (received_at);
CREATE INDEX IF NOT EXISTS support_message_person_id_idx
  ON support_message (person_id) WHERE person_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS support_inbox_state (
  mailbox          TEXT         PRIMARY KEY,
  history_id       TEXT,
  backfill_done    BOOLEAN      NOT NULL DEFAULT FALSE,
  backfill_token   TEXT,
  last_checked_at  TIMESTAMPTZ,
  last_ok_at       TIMESTAMPTZ,
  last_error       TEXT
);

COMMIT;
