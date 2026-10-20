-- 0070_unmatch.sql
-- Unmatch (TEC-1845). The chat menu's Unmatch promises, in the design's
-- words (ahavah-web Claude Design/handoff/copy/15-together-follow-ups.md,
-- 6.2): "The match and your conversation are removed for both of you, and
-- you will not see each other in Discover."
--
-- Additive. The deploy applies each file once and records its checksum
-- (scripts/apply-deploy-migrations.sh), and stops if an applied file
-- changes: never edit this file once it has shipped; a change is the next
-- number. Idempotent, because the test fixtures apply it at every session
-- start.

-- 1. The pair, for good. One row per pair, the lower person id first, as in
-- ahavah_match. matched_at keeps when the match was made, so Growth still
-- counts a match that happened. The row goes with either person's account.
CREATE TABLE IF NOT EXISTS unmatched_pair (
  user_a_id     INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  user_b_id     INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  unmatched_by  INT         NOT NULL,
  matched_at    TIMESTAMPTZ,
  unmatched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_a_id, user_b_id),
  CHECK (user_a_id < user_b_id),
  CHECK (unmatched_by IN (user_a_id, user_b_id))
);

CREATE INDEX IF NOT EXISTS idx__unmatched_pair__user_b ON unmatched_pair (user_b_id);

-- 2. The conversation, out of sight. Both archives' copies move here from
-- mam_message in the unmatch's own transaction, so no member surface, chat
-- history or data export can show them. They are read only by the report
-- email (antiabuse/sql Q_LAST_MESSAGES) and deleted at held_until by the
-- daily retention cron (service/cron/leadretention), or with either
-- person's account. Translations are not kept.
CREATE TABLE IF NOT EXISTS unmatched_message (
  person_id        INT           NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  id               BIGINT        NOT NULL,
  remote_bare_jid  VARCHAR(250)  NOT NULL,
  direction        mam_direction NOT NULL,
  message          BYTEA         NOT NULL,
  search_body      TEXT,
  audio_uuid       TEXT,
  held_until       TIMESTAMPTZ   NOT NULL,
  PRIMARY KEY (person_id, id)
);

CREATE INDEX IF NOT EXISTS idx__unmatched_message__held_until
  ON unmatched_message (held_until);

-- 3. The named predicate (the 0035 pattern: a caller picks a meaning by
-- name instead of hand-rolling a clause and forgetting one).
CREATE OR REPLACE FUNCTION is_unmatched_pair(a INT, b INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM unmatched_pair
        WHERE user_a_id = LEAST(a, b)
          AND user_b_id = GREATEST(a, b)
    );
$$;

-- 4. The hard barrier now has two causes: a report either way (0035), or an
-- unmatch. Every surface that hides a reported pair hides an unmatched pair,
-- in both directions: profile, Views, map, likes, matches, chat, presence and
-- the member emails. The blocked list and report counts read
-- skipped.reported directly and are not touched.
CREATE OR REPLACE FUNCTION is_blocked_pair(a INT, b INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM skipped
        WHERE reported
          AND (
                (subject_person_id = a AND object_person_id = b)
             OR (subject_person_id = b AND object_person_id = a)
          )
    )
    OR is_unmatched_pair(a, b);
$$;

-- 5. Discover. The 0059 body, plus an unmatch, both ways and for good.
CREATE OR REPLACE FUNCTION is_deck_suppressed(searcher INT, prospect INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM skipped
        WHERE (
                -- The searcher's own pass or report.
                subject_person_id = searcher
                AND object_person_id = prospect
                AND (reported OR created_at > NOW() - INTERVAL '30 days')
          )
          OR (
                -- The prospect's action only counts when it is a report.
                subject_person_id = prospect
                AND object_person_id = searcher
                AND reported
          )
    )
    OR is_unmatched_pair(searcher, prospect);
$$;
