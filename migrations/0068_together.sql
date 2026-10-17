-- 0068_together.sql
-- Together, release 1 (TEC-1845,
-- docs/superpowers/specs/2026-10-13-couple-tools-design.md; plan
-- docs/superpowers/plans/2026-10-17-together-release-1.md).
--
--   tool_session  one game (me, us, knows_me) or one checklist (couple,
--                 single). The owner's email, account and display name
--                 are set when they save. share_token opens the public
--                 summary (never an answer); invite_token starts a second
--                 player. A deleted session keeps only its tokens and
--                 deleted_at, so a link can say it was deleted.
--   tool_player   the owner and every guest. Only the sha256 of a
--                 player's token is stored. A guest in knows_me gives only
--                 a display name.
--   tool_answer   one answer per player and question, readable only by
--                 the players (service/tools/sessions.py).
--   tool_result   the session's result (player_id NULL) or a knows_me
--                 friend's score.
--
-- No column, mode or area for plural marriage. Deleted 12 months after
-- the last visit, 30 days after creation if never saved, or on request
-- (service/tools/retention.py). Idempotent: the deploy may run this file
-- more than once.

CREATE TABLE IF NOT EXISTS tool_session (
  id                      BIGSERIAL    PRIMARY KEY,
  uuid                    UUID         NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  kind                    TEXT         NOT NULL CHECK (kind IN ('game', 'checklist')),
  mode                    TEXT         NOT NULL,
  owner_email             TEXT,
  owner_normalized_email  TEXT,
  owner_person_id         INT          REFERENCES person(id) ON DELETE CASCADE,
  owner_display           TEXT         CHECK (owner_display IS NULL
                                              OR char_length(owner_display) BETWEEN 1 AND 40),
  share_token             TEXT         UNIQUE,
  invite_token            TEXT         UNIQUE,
  source                  TEXT         NOT NULL CHECK (source IN ('tool:game-me', 'tool:game-us',
                                                                  'tool:knows-me', 'tool:checklist')),
  utm                     JSONB,
  share_opens             INT          NOT NULL DEFAULT 0,
  invite_emails           INT          NOT NULL DEFAULT 0,
  created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  claimed_at              TIMESTAMPTZ,
  completed_at            TIMESTAMPTZ,
  deleted_at              TIMESTAMPTZ,
  last_visit_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK ((kind = 'game' AND mode IN ('me', 'us', 'knows_me'))
      OR (kind = 'checklist' AND mode IN ('couple', 'single')))
);

CREATE INDEX IF NOT EXISTS idx__tool_session__owner_ne
  ON tool_session (owner_normalized_email) WHERE owner_normalized_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__tool_session__last_visit_at ON tool_session (last_visit_at);

CREATE TABLE IF NOT EXISTS tool_player (
  id                BIGSERIAL    PRIMARY KEY,
  session_id        BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  seat              TEXT         NOT NULL CHECK (seat IN ('owner', 'guest')),
  token_hash        TEXT         NOT NULL UNIQUE,
  display           TEXT         CHECK (display IS NULL OR char_length(display) BETWEEN 1 AND 40),
  role              TEXT         CHECK (role IN ('husband', 'wife')),
  email             TEXT,
  normalized_email  TEXT,
  person_id         INT          REFERENCES person(id) ON DELETE CASCADE,
  finished_at       TIMESTAMPTZ,
  removed_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx__tool_player__one_owner
  ON tool_player (session_id) WHERE seat = 'owner';
CREATE INDEX IF NOT EXISTS idx__tool_player__session ON tool_player (session_id);
CREATE INDEX IF NOT EXISTS idx__tool_player__ne
  ON tool_player (normalized_email) WHERE normalized_email IS NOT NULL;

CREATE TABLE IF NOT EXISTS tool_answer (
  session_id    BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  player_id     BIGINT       NOT NULL REFERENCES tool_player(id) ON DELETE CASCADE,
  question_key  TEXT         NOT NULL CHECK (question_key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'
                                             AND char_length(question_key) <= 64),
  answer        JSONB        NOT NULL,
  answered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (player_id, question_key)
);

CREATE INDEX IF NOT EXISTS idx__tool_answer__session ON tool_answer (session_id);

CREATE TABLE IF NOT EXISTS tool_result (
  id           BIGSERIAL    PRIMARY KEY,
  session_id   BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  player_id    BIGINT       REFERENCES tool_player(id) ON DELETE CASCADE,
  score        INT          CHECK (score BETWEEN 0 AND 100),
  breakdown    JSONB        NOT NULL DEFAULT '{}'::jsonb,
  archetype    TEXT,
  computed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx__tool_result__session_player
  ON tool_result (session_id, COALESCE(player_id, 0));
