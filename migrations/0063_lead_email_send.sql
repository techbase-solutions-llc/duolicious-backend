-- 0063_lead_email_send.sql
-- A send log for one-off emails to leads: waitlist and beta addresses that
-- have no `person` row, so email_send_log (keyed by person_id) cannot hold
-- them. First user: the owner's personal note to the warm leads (health
-- review, 13 Oct 2026, finding 48; emails/send_warm_leads_note.py).
--
-- One row per address per campaign. The sender inserts the row BEFORE it
-- calls the mailer (claimed_at) and fills message_id and sent_at once the
-- mailer accepts, so a re-run, a crash or two operators at once can never
-- email the same address twice. A row with sent_at NULL is a send whose
-- outcome is unknown; it is deliberately not retried.
--
-- email is stored lower-cased, as both lead tables store it.
-- Idempotent: the deploy may run this file more than once.

CREATE TABLE IF NOT EXISTS lead_email_send (
  email       TEXT         NOT NULL,
  campaign    TEXT         NOT NULL,
  message_id  TEXT,
  claimed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  sent_at     TIMESTAMPTZ,
  PRIMARY KEY (email, campaign)
);
