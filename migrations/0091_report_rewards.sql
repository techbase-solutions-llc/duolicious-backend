-- 0091_report_rewards.sql (TEC-2025, report rewards plan of 3 Nov 2026)
-- Idempotent: safe to run more than once.
--
-- 1. feedback gets a status and a link to the member who sent it. Every
--    existing row reads as 'new', which is true: nothing ever marked one
--    handled.
-- 2. member_notice: an in-app notice for one member (the thank-you for a
--    report we fixed is the first kind). One notice per report at most.
-- 3. token_ledger_reason_check gains 'report_reward'. The list is every
--    reason 0072 allowed plus the new one, so existing rows already comply.
BEGIN;

ALTER TABLE feedback
  ADD COLUMN IF NOT EXISTS person_id INT REFERENCES person(id) ON DELETE SET NULL;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new';
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS handled_at TIMESTAMPTZ;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS handled_by TEXT;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS reward_tokens INT NOT NULL DEFAULT 0;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS reward_days INT NOT NULL DEFAULT 0;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS notice_line TEXT;

ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_status_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_status_check
  CHECK (status IN ('new', 'fixed', 'not_a_fault'));

CREATE INDEX IF NOT EXISTS feedback_status_created_at_idx ON feedback (status, created_at);
CREATE INDEX IF NOT EXISTS feedback_person_id_idx ON feedback (person_id) WHERE person_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS member_notice (
  id            BIGSERIAL    PRIMARY KEY,
  person_id     INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  kind          TEXT         NOT NULL CHECK (kind IN ('report_thanks')),
  title         TEXT         NOT NULL,
  body          TEXT         NOT NULL,
  tokens        INT          NOT NULL DEFAULT 0,
  premium_days  INT          NOT NULL DEFAULT 0,
  feedback_id   BIGINT       UNIQUE REFERENCES feedback(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  seen_at       TIMESTAMPTZ,
  dismissed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS member_notice_open_idx
  ON member_notice (person_id) WHERE dismissed_at IS NULL;

ALTER TABLE token_ledger DROP CONSTRAINT IF EXISTS token_ledger_reason_check;

ALTER TABLE token_ledger ADD CONSTRAINT token_ledger_reason_check
  CHECK (reason = ANY (ARRAY[
    'purchase',
    'subscription_stipend',
    'reveal_liker',
    'super_like',
    'day_pass',
    'boost',
    'refund',
    'referral',
    'rewind',
    'admin_credit',
    'admin_debit',
    'report_reward'
  ]::text[]));

COMMIT;
