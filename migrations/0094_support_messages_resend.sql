-- 0094_support_messages_resend.sql (TEC-2115,
-- docs/plans/2026-11-05-support-inbox-via-forwarding.md)
-- Idempotent: safe to run more than once.
--
-- Support mail now reaches the API by forwarding: a Gmail filter forwards
-- mail for support@ahavah.app to a Resend receiving address and the
-- supportinbox cron reads it from Resend. No Google key is held.
--
--   support_message.resend_email_id  the Resend received-email id, the new
--                                    idempotency point (unique)
--   support_message.rfc_message_id   the original Message-ID, without its
--                                    angle brackets, for the "Reply in
--                                    Gmail" search link
--   gmail_message_id, gmail_thread_id  no longer required: rows copied
--                                    from Resend have neither
--   support_inbox_state.synced_through  the newest received time of the
--                                    last complete read of the Resend list;
--                                    a later read stops at a page that is
--                                    all older than it (when the list
--                                    comes newest first)
--   support_inbox_state.walk_newest  the newest received time seen so far
--                                    by a read the page limit cut short;
--                                    backfill_token then holds the id it
--                                    carries on from
BEGIN;

ALTER TABLE support_message ADD COLUMN IF NOT EXISTS resend_email_id TEXT;
ALTER TABLE support_message ADD COLUMN IF NOT EXISTS rfc_message_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS support_message_resend_email_id_key
  ON support_message (resend_email_id);

ALTER TABLE support_message ALTER COLUMN gmail_message_id DROP NOT NULL;
ALTER TABLE support_message ALTER COLUMN gmail_thread_id DROP NOT NULL;

ALTER TABLE support_inbox_state ADD COLUMN IF NOT EXISTS synced_through TIMESTAMPTZ;
ALTER TABLE support_inbox_state ADD COLUMN IF NOT EXISTS walk_newest TIMESTAMPTZ;

COMMIT;
