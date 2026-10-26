-- 0086_release_4_push_preferences.sql
-- The 3 member pushes of the in-app plan's release 4 (TEC-1845; ahavah-web
-- docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 9), each with
-- its own toggle in Settings > Notifications:
--
--   push_gathering_reminder  a reminder of a gathering the member is going to
--   push_new_guests          new guests for a gathering the member hosts,
--                            at most once a day
--   push_match_played        the member's match finished the game
--
-- Each defaults on, as push_questions does: each is about something the
-- member did themselves (a place, a gathering they host, a game they
-- started), and each push has its own switch, off until the owner has
-- seen its proof (service/campaigns/switches.py).
--
-- A constant default is stored in the catalogue, so adding a column
-- rewrites nothing; the statement still waits at most 5 seconds for its
-- lock. Idempotent: safe to run again.
SET lock_timeout = '5s';

ALTER TABLE notification_preference
  ADD COLUMN IF NOT EXISTS push_gathering_reminder BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS push_new_guests         BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS push_match_played       BOOLEAN NOT NULL DEFAULT TRUE;

RESET lock_timeout;
