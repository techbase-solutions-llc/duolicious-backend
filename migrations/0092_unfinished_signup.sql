-- 0092_unfinished_signup.sql
-- The unfinished sign-up reminder (TEC-2107, ahavah-web
-- docs/plans/2026-11-04-unfinished-sign-up-reminder.md).
--
--   email_outbox.onboardee_email   the recipient of a reminder to someone
--                                  who started sign-up and stopped: an
--                                  onboardee is neither a member nor a lead,
--                                  and its row is deleted after a week, so
--                                  the address (lower-cased) is the key, with
--                                  no foreign key. Its own partial unique
--                                  index is the outbox's idempotency point.
--                                  The lead_retention cron deletes these rows
--                                  30 days after they settle.
--   lead_email_send.unsubscribed_at
--                                  stamped by the `signup` unsubscribe link,
--                                  so leaving works for an address with no
--                                  account and no lead row.
--
-- The reminder's claim in lead_email_send (campaign unfinished_signup) holds
-- a keyed hash of the address in `email`, never the address
-- (service.admin.queries.signups.claim_key).
--
-- email_outbox is a busy table. Each statement waits at most 5 seconds for
-- its lock rather than queueing every later query behind it; one that times
-- out stops the deploy before the new code starts, and a rerun picks up
-- where it stopped, since every statement is idempotent. The check is added
-- NOT VALID (a brief lock, no scan) and validated on its own, which scans
-- the table without blocking writes.
--
-- The unique index is built plainly, not CONCURRENTLY: the deploy's runner
-- (scripts/apply-deploy-migrations.sh) does not wrap a file in a
-- transaction, but the test suite applies this file inside one, where
-- CONCURRENTLY is refused, and a CONCURRENTLY build that fails leaves an
-- invalid index that IF NOT EXISTS would then skip for good. The build
-- reads the table once, holding off writes meanwhile; the column is new and
-- NULL on every row, so the index it writes is empty.
SET lock_timeout = '5s';

ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS onboardee_email TEXT;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id, organiser_id, recommendation_id, mentor_link_id, onboardee_email) = 1)
  NOT VALID;
ALTER TABLE email_outbox VALIDATE CONSTRAINT email_outbox_one_recipient_check;
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__onboardee_run
  ON email_outbox (campaign, campaign_id, onboardee_email) WHERE onboardee_email IS NOT NULL;

ALTER TABLE lead_email_send ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ;

RESET lock_timeout;
