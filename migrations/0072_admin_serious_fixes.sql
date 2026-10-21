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

-- 3. Reports. A report was only the reporter's skipped row with reported =
--    TRUE, and the block is that same row, so Unblock (DELETE from skipped)
--    took the report out of the admin. person_report keeps every report
--    filed, whatever later happens to the block. A trigger writes it, so
--    every writer of skipped is covered, including an API still running
--    the old code while this deploys. A report is keyed by its pair and the
--    skipped row's created_at at the time (the key TEC-1897's
--    report_resolution plans to use), so a later report on the same pair is
--    a second record. The person rows cascade, as skipped does.
CREATE TABLE IF NOT EXISTS person_report (
  reporter_id  INT       NOT NULL REFERENCES person(id) ON DELETE CASCADE ON UPDATE CASCADE,
  reported_id  INT       NOT NULL REFERENCES person(id) ON DELETE CASCADE ON UPDATE CASCADE,
  reported_at  TIMESTAMP NOT NULL,
  reason       TEXT      NOT NULL DEFAULT '',
  PRIMARY KEY (reporter_id, reported_id, reported_at)
);

CREATE INDEX IF NOT EXISTS idx__person_report__reported_at
  ON person_report (reported_at DESC);

-- A row becomes a report when it is inserted reported, when a pass is
-- escalated, or when a report is made again (the skip upsert moves
-- created_at). A plain pass on a reported pair keeps created_at (antiabuse
-- Q_INSERT_SKIPPED), so it files nothing.
CREATE OR REPLACE FUNCTION trg_skipped_keep_report() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.reported AND (
       TG_OP = 'INSERT'
       OR NOT OLD.reported
       OR NEW.created_at IS DISTINCT FROM OLD.created_at) THEN
    INSERT INTO person_report (reporter_id, reported_id, reported_at, reason)
    VALUES (NEW.subject_person_id, NEW.object_person_id, NEW.created_at, NEW.report_reason)
    ON CONFLICT DO NOTHING;
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE TRIGGER skipped_keep_report
  AFTER INSERT OR UPDATE ON skipped
  FOR EACH ROW EXECUTE FUNCTION trg_skipped_keep_report();

-- Every report already on file.
INSERT INTO person_report (reporter_id, reported_id, reported_at, reason)
SELECT subject_person_id, object_person_id, created_at, report_reason
  FROM skipped
 WHERE reported
ON CONFLICT DO NOTHING;

COMMIT;
