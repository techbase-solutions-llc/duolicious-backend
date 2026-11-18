-- 0100_exit_answer.sql (TEC-2158)
-- The owner, 16 Nov 2026: a member who deletes their account may say why.
-- One optional question in the delete box; the answer is kept without the
-- member's name or email.
--
-- person_id is there only for the 7 days the deletion can still be undone,
-- so the row can be marked kept if the member comes back. It is cleared
-- when the member keeps the account (kept_at set) and by the key when the
-- person row is hard-deleted. After that nothing links the row to anyone:
-- gender, a band for time as a member (never the days) and whether they
-- had Premium are all it carries besides the answer.
--
--   waiting  person_id set,  kept_at NULL   (inside the 7 days; admins see
--                                            only how many)
--   deleted  person_id NULL, kept_at NULL
--   kept     kept_at set (person_id NULL)
--
-- One open row a person: the partial unique index. The code closes any
-- open row before it writes a new one.
--
-- Additive and idempotent, as the deploy needs. Never edit once shipped; a
-- change is the next number.

-- The key on person takes a lock there: give up rather than queue sign-ins.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS exit_answer (
  id          BIGSERIAL PRIMARY KEY,
  person_id   INT REFERENCES person(id) ON DELETE SET NULL,
  reason      TEXT NOT NULL CHECK (reason IN
              ('met_here', 'met_elsewhere', 'few_people', 'not_expected', 'break', 'other')),
  note        TEXT CHECK (note IS NULL OR char_length(note) <= 300),
  gender      TEXT,
  member_band TEXT CHECK (member_band IS NULL OR member_band IN
              ('under_1_month', '1_to_6_months', 'over_6_months')),
  had_premium BOOLEAN,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  kept_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS exit_answer_created_idx
  ON exit_answer (created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS exit_answer_open_person_idx
  ON exit_answer (person_id)
  WHERE person_id IS NOT NULL AND kept_at IS NULL;

-- Serves the key's ON DELETE SET NULL when a person row is hard-deleted.
CREATE INDEX IF NOT EXISTS exit_answer_person_idx
  ON exit_answer (person_id);

RESET lock_timeout;
