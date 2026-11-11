-- 0098_see_passes_reason.sql (11 Nov 2026)
-- Idempotent: safe to run more than once. Never edit once shipped; a
-- change is the next number.
--
-- "See passes again" was written to token_ledger as reason 'rewind', the
-- reason of the single-profile Rewind, with metadata kind 'see_passes'. It
-- gets its own reason:
-- 1. token_ledger_reason_check gains 'see_passes'. The list is every reason
--    0091 allowed plus the new one, so existing rows already comply.
-- 2. Rows already written as 'rewind' with metadata kind 'see_passes' take
--    the new reason, so the ledger reads the same before and after.
BEGIN;

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
    'report_reward',
    'see_passes'
  ]::text[]));

UPDATE token_ledger
   SET reason = 'see_passes'
 WHERE reason = 'rewind'
   AND metadata->>'kind' = 'see_passes';

COMMIT;
