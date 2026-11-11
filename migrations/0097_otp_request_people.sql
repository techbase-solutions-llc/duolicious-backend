-- 0097_otp_request_people.sql
-- Admin > System counted sign-in code REQUESTS as though they were people
-- (TEC-2144, review of 11 Nov 2026). "Codes nobody entered" read 65 when
-- 17 addresses had never finished: 48 of the 65 were pending sessions that
-- /request-otp deleted because the same address asked again
-- (Q_PURGE_STALE_UNSIGNED_SESSIONS), and 20 of those finished within 15
-- minutes. The refusal count also mixed in event RSVP, visitor alert and
-- tool invite refusals, and member sign-ins included staff.
--
--   flow         which form asked: 'sign_in' (/request-otp and /resend-otp,
--                sign-up and sign-in alike), 'event_rsvp', 'visitor_alert'
--                or 'tool_invite'. The last three record refusals only.
--   superseded   the same address asked again before entering this code,
--                so its pending session was deleted. The address is then
--                counted by its later request, so a request that is
--                neither entered nor superseded is one address that never
--                finished.
--   staff        the address belonged to an admin, a moderator or a tester
--                when the code was asked for (service/admin/queries/
--                members.py, non_member_role_sql), so member sign-ins can
--                leave them out.
--
-- Still no email address is stored.
--
-- History: a pending session that no longer exists, for a request that was
-- never entered, was deleted by a later request from the same address (an
-- unsigned session otherwise lives for months, past this table's 90 days),
-- so those rows are marked superseded once. Staff is read from the
-- session's person where the session still exists, which is every request
-- that is neither entered nor superseded. Rows written before this file
-- keep flow 'sign_in': on 11 Nov 2026 every refusal on file was a honeypot
-- hit, and none can be told apart now.
--
-- Additive and idempotent: the backfill runs only in the run that adds the
-- columns. Never edit once shipped; a change is the next number.
SET lock_timeout = '5s';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'otp_request' AND column_name = 'superseded'
  ) THEN
    ALTER TABLE otp_request
      ADD COLUMN flow       TEXT    NOT NULL DEFAULT 'sign_in',
      ADD COLUMN superseded BOOLEAN NOT NULL DEFAULT FALSE,
      ADD COLUMN staff      BOOLEAN NOT NULL DEFAULT FALSE;

    UPDATE otp_request r
       SET superseded = TRUE
     WHERE r.refused IS NULL
       AND r.entered_at IS NULL
       AND r.session_token_hash IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM duo_session s
                        WHERE s.session_token_hash = r.session_token_hash);

    UPDATE otp_request r
       SET staff = TRUE
      FROM duo_session s
      JOIN person p ON p.id = s.person_id
     WHERE s.session_token_hash = r.session_token_hash
       AND COALESCE(p.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod', 'tester']::text[];
  END IF;
END $$;
