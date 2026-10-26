-- 0080_organiser_member.sql
-- The member who made an organiser in the app (TEC-1845; ahavah-web
-- docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 4, the
-- owner's choice of the suggested option on 22 Oct 2026).
--
-- A member who hosts from the app under another address (a church or
-- ministry address, proved with the usual code) has nothing tying that
-- organiser to them, so its gatherings would not appear under Hosting on
-- another device. member_person_id names the member who made it. It is
-- read only by the member's own session (POST /organiser/member) and
-- never shown to the organiser or to guests. An organiser under the
-- member's own address is matched by address and needs no link, though
-- the request from the app records it too.
--
-- When the member's account is deleted the link goes and the organiser
-- stays, as it was made for the assembly.
--
-- Additive and idempotent: the deploy applies it once
-- (scripts/apply-deploy-migrations.sh) and the test fixtures at every
-- session start. Adding a column with no default and its foreign key takes
-- locks on organiser and person, so each statement waits at most 5 seconds
-- for them; if it gives up, the migration stops with an error and can
-- simply be run again. Never edit this file once it has shipped.
SET lock_timeout = '5s';

ALTER TABLE organiser
  ADD COLUMN IF NOT EXISTS member_person_id INT REFERENCES person(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx__organiser__member_person_id
  ON organiser (member_person_id) WHERE member_person_id IS NOT NULL;

RESET lock_timeout;
