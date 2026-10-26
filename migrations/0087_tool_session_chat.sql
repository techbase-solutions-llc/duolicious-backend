-- 0087_tool_session_chat.sql
-- Together from a chat (TEC-1845; ahavah-web docs/plans/2026-10-22-in-app-
-- entry-and-sign-up.md, section 3, release 4): the marriage checklist, and
-- the Us game, started with a match from Chat > More.
--
--   chat_person_id  the match the owner started it with, from the chat. The
--                   API checks the two are matched when it starts, and the
--                   member's list of past results names the chat it
--                   belongs to. NULL for every session started elsewhere.
--                   A member's deletion leaves the session to its other
--                   rules (service/hard_delete) and clears this.
--
-- Also an index for the member's past results (GET /tools/mine), which
-- reads the sessions an account owns.
--
-- Adding a nullable column rewrites nothing; each statement waits at most
-- 5 seconds for its lock. tool_session is small, so the plain index build
-- is brief. Idempotent: safe to run again.
SET lock_timeout = '5s';

ALTER TABLE tool_session
  ADD COLUMN IF NOT EXISTS chat_person_id INT REFERENCES person(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx__tool_session__owner_person
  ON tool_session (owner_person_id) WHERE owner_person_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx__tool_player__person
  ON tool_player (person_id) WHERE person_id IS NOT NULL;

RESET lock_timeout;
