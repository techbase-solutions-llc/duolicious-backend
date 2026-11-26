-- 0102_waiting_note.sql (TEC-2210)
-- "Write to them" on the admin's Waiting on a reply list (plan
-- ahavah-admin/docs/plans/2026-11-26-admin-dead-buttons.md, part 1): the
-- owner writes a short note to one member and it goes by email.
--
--   waiting_note  one row per note sent: who it went to, when, which admin
--       sent it and the note itself (the owner's own words, never anything
--       a member wrote). The latest row for a person holds the 7 day rule.
--       The route writes the row before the send and deletes it if the
--       send fails, so two quick presses send once.
--
-- Additive and idempotent, as the deploy needs. Never edit once shipped; a
-- change is the next number.

-- The key on person takes a lock there: give up rather than queue sign-ins.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS waiting_note (
  id         BIGSERIAL    PRIMARY KEY,
  person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  sent_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  sent_by    TEXT         NOT NULL,
  note       TEXT         NOT NULL CHECK (char_length(note) BETWEEN 1 AND 600)
);

CREATE INDEX IF NOT EXISTS idx__waiting_note__person_id__sent_at
  ON waiting_note (person_id, sent_at DESC);

RESET lock_timeout;
