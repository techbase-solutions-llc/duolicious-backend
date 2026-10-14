-- 0064_push_send_log.sql
-- A send log for pushes that must go once only: the match and message
-- reminders held for the owner's proof (health review, 13 Oct 2026,
-- finding 61; emails/reminders.py). An email reminder is deduped by the
-- outbox's own key; a push has no outbox, so this row is its key. It is
-- written in the transaction that decides to push, before the push is
-- handed to the sender, so a repeat tick never pushes twice. A crash
-- between the two loses that one push, which is the right way to fail for
-- a reminder.
--
-- Idempotent: the deploy may run this file more than once.

CREATE TABLE IF NOT EXISTS push_send_log (
  person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  campaign     TEXT         NOT NULL,
  campaign_id  TEXT         NOT NULL,
  sent_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (person_id, campaign, campaign_id)
);
