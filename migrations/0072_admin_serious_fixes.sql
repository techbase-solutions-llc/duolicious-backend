-- 0072_admin_serious_fixes.sql (TEC-1845, admin audit of 20 Oct 2026)
-- Idempotent: the deploy may run this file more than once.
-- Deploy it before the API that reads it.
--
-- 1. Adjust tokens. POST /admin/users/<uuid>/tokens writes ledger reasons
--    'admin_credit' and 'admin_debit', which token_ledger_reason_check never
--    allowed, so every manual credit or debit raised a CheckViolation and
--    returned 500. Drop and re-add the constraint with the full allowed set:
--    every reason 0028 allowed plus the two admin reasons (a superset, so
--    existing rows already comply).
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
    'admin_debit'
  ]::text[]));

-- 2. Deactivate. The admin action set activated = FALSE only, and the next
--    successful sign-in set it back to TRUE. admin_deactivated_at is the
--    admin block: Deactivate stamps it, Reactivate clears it, and the
--    sign-in queries refuse a person who has it. activated alone stays what
--    it was (a member's own deactivation and the inactivity cron still end
--    at the next sign-in). Nullable with no default, so adding it does not
--    rewrite the table.
ALTER TABLE person ADD COLUMN IF NOT EXISTS admin_deactivated_at TIMESTAMPTZ;

COMMIT;
