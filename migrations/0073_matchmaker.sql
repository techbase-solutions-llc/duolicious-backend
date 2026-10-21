-- 0073_matchmaker.sql
-- Matchmaker, release 1 (TEC-1845, docs/superpowers/plans/2026-10-21-matchmaker-release-1.md).
-- 0069 is reserved for TEC-1897, 0070 is Unmatch, 0071 is Events and 0072
-- is the admin fixes branch's. Needs 0066 (lead) and 0071
-- (email_outbox.organiser_id) applied first.
--
--   match_alert          "Tell me when someone fits": a member's (person_id)
--                        or a visitor's (lead_id, source alert:visitor).
--                        active FALSE is paused. Names nobody.
--   match_alert_notice   one row per notice sent: a count, never who.
--   recommendation       "Introduce a single to Ahavah". The single's address
--                        and the note are erased 7 days after the email
--                        settles; recipient_key (HMAC of the normalised
--                        address) stays 12 months so they hear from us once.
--   introduction         "Suggest two people". A match only if both accept.
--   mentor_account       a role, not a person: no profile, never in search.
--   mentor_link          a single's one mentor, invited by email.
--   mentor_session       a mentor's sign-in, stored as its sha256.
--   shared_conversation  one conversation a single shares, read only. Rows
--                        are revoked, not deleted, so the chat can say when
--                        sharing stopped.
--   mentor_note          a mentor's private note to the single about a match.
--   person.no_mentor_shared_matches   Privacy, Matching (owner decision 12).
--   email_outbox         gains recommendation_id and mentor_link_id: neither
--                        recipient is a member or a lead.
--
-- person and email_outbox are busy tables. Each statement waits at most 5
-- seconds for its lock rather than queueing every later query behind it;
-- one that times out stops the deploy before the new code starts, and a
-- rerun picks up where it stopped, since every statement is idempotent.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS match_alert (
  id                  BIGSERIAL    PRIMARY KEY,
  person_id           INT          REFERENCES person(id) ON DELETE CASCADE,
  lead_id             BIGINT       REFERENCES lead(id) ON DELETE CASCADE,
  first_name          TEXT         CHECK (char_length(first_name) BETWEEN 1 AND 40),
  criteria            JSONB        NOT NULL,
  notify_push         BOOLEAN      NOT NULL DEFAULT TRUE,
  notify_email        BOOLEAN      NOT NULL DEFAULT TRUE,
  active              BOOLEAN      NOT NULL DEFAULT TRUE,
  confirmed_at        TIMESTAMPTZ,
  confirm_token_hash  TEXT         UNIQUE,
  confirm_by          TIMESTAMPTZ,
  resends             INT          NOT NULL DEFAULT 0,
  stop_token_hash     TEXT         UNIQUE,
  counted_since       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  last_sent_at        TIMESTAMPTZ,
  likes_told_at       TIMESTAMPTZ,
  paused_at           TIMESTAMPTZ,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (num_nonnulls(person_id, lead_id) = 1),
  CHECK (person_id IS NULL OR confirmed_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__match_alert__person ON match_alert (person_id) WHERE person_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx__match_alert__lead ON match_alert (lead_id) WHERE lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__match_alert__due ON match_alert (last_sent_at) WHERE active AND confirmed_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS match_alert_notice (
  id            BIGSERIAL    PRIMARY KEY,
  alert_id      BIGINT       REFERENCES match_alert(id) ON DELETE SET NULL,
  audience      TEXT         NOT NULL CHECK (audience IN ('member', 'visitor')),
  members       INT          NOT NULL CHECK (members >= 1),
  window_start  TIMESTAMPTZ  NOT NULL,
  window_end    TIMESTAMPTZ  NOT NULL,
  by_push       BOOLEAN      NOT NULL DEFAULT FALSE,
  by_email      BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__match_alert_notice__alert ON match_alert_notice (alert_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recommendation (
  id                 BIGSERIAL    PRIMARY KEY,
  sender_person_id   INT          REFERENCES person(id) ON DELETE SET NULL,
  sender_key         TEXT         NOT NULL,
  sender_first_name  TEXT         CHECK (char_length(sender_first_name) BETWEEN 1 AND 40),
  recipient_email    TEXT,
  recipient_key      TEXT         NOT NULL,
  note               TEXT         CHECK (char_length(note) BETWEEN 1 AND 500),
  referral_code      TEXT,
  status             TEXT         NOT NULL CHECK (status IN ('held', 'queued', 'sent', 'rejected')),
  flag_reason        TEXT,
  joined_person_id   INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_by        INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_at        TIMESTAMPTZ,
  sent_at            TIMESTAMPTZ,
  erased_at          TIMESTAMPTZ,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (status NOT IN ('held', 'queued') OR recipient_email IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__recommendation__recipient ON recommendation (recipient_key) WHERE status <> 'rejected';
CREATE INDEX IF NOT EXISTS idx__recommendation__sender ON recommendation (sender_key, created_at);

CREATE TABLE IF NOT EXISTS introduction (
  id                    BIGSERIAL    PRIMARY KEY,
  introducer_person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  a_person_id           INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  b_person_id           INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  note                  TEXT         CHECK (char_length(note) <= 500),
  status                TEXT         NOT NULL DEFAULT 'open' CHECK (status IN ('held', 'open', 'matched', 'closed', 'rejected')),
  flag_reason           TEXT,
  a_response            TEXT         CHECK (a_response IN ('accepted', 'declined')),
  b_response            TEXT         CHECK (b_response IN ('accepted', 'declined')),
  a_responded_at        TIMESTAMPTZ,
  b_responded_at        TIMESTAMPTZ,
  closes_at             TIMESTAMPTZ  NOT NULL,
  opened_at             TIMESTAMPTZ,
  matched_at            TIMESTAMPTZ,
  introducer_told_at    TIMESTAMPTZ,
  reviewed_by           INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_at           TIMESTAMPTZ,
  note_erased_at        TIMESTAMPTZ,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (a_person_id <> b_person_id),
  CHECK (introducer_person_id NOT IN (a_person_id, b_person_id))
);
CREATE INDEX IF NOT EXISTS idx__introduction__a_open ON introduction (a_person_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx__introduction__b_open ON introduction (b_person_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx__introduction__introducer ON introduction (introducer_person_id, created_at);

CREATE TABLE IF NOT EXISTS mentor_account (
  id                BIGSERIAL    PRIMARY KEY,
  email             TEXT         NOT NULL,
  normalized_email  TEXT         NOT NULL UNIQUE,
  last_seen_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mentor_link (
  id                       BIGSERIAL    PRIMARY KEY,
  single_person_id         INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  mentor_email             TEXT         NOT NULL,
  mentor_normalized_email  TEXT         NOT NULL,
  relation                 TEXT         NOT NULL CHECK (relation IN ('parent', 'elder', 'mentor', 'friend')),
  mentor_account_id        BIGINT       REFERENCES mentor_account(id) ON DELETE SET NULL,
  invite_token_hash        TEXT         UNIQUE,
  invite_expires_at        TIMESTAMPTZ  NOT NULL,
  confirmed_at             TIMESTAMPTZ,
  revoked_at               TIMESTAMPTZ,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (confirmed_at IS NULL OR mentor_account_id IS NOT NULL OR revoked_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__mentor_link__single_live ON mentor_link (single_person_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__mentor_link__mentor_email ON mentor_link (mentor_normalized_email) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS mentor_session (
  token_hash         TEXT         PRIMARY KEY,
  mentor_account_id  BIGINT       NOT NULL REFERENCES mentor_account(id) ON DELETE CASCADE,
  expires_at         TIMESTAMPTZ  NOT NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__mentor_session__expires ON mentor_session (expires_at);

CREATE TABLE IF NOT EXISTS shared_conversation (
  id                 BIGSERIAL    PRIMARY KEY,
  single_person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  other_person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  other_person_uuid  UUID         NOT NULL,
  mentor_link_id     BIGINT       NOT NULL REFERENCES mentor_link(id) ON DELETE CASCADE,
  shared_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  revoked_at         TIMESTAMPTZ,
  CHECK (single_person_id <> other_person_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__shared_conversation__live ON shared_conversation (single_person_id, other_person_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__shared_conversation__other ON shared_conversation (other_person_id);

CREATE TABLE IF NOT EXISTS mentor_note (
  id                 BIGSERIAL    PRIMARY KEY,
  mentor_account_id  BIGINT       NOT NULL REFERENCES mentor_account(id) ON DELETE CASCADE,
  single_person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  about_person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  note               TEXT         NOT NULL CHECK (char_length(note) BETWEEN 1 AND 1000),
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (mentor_account_id, single_person_id, about_person_id)
);

ALTER TABLE person ADD COLUMN IF NOT EXISTS no_mentor_shared_matches BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS recommendation_id BIGINT REFERENCES recommendation(id) ON DELETE CASCADE;
ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS mentor_link_id BIGINT REFERENCES mentor_link(id) ON DELETE CASCADE;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id, organiser_id, recommendation_id, mentor_link_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__recommendation_run
  ON email_outbox (campaign, campaign_id, recommendation_id) WHERE recommendation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__mentor_link_run
  ON email_outbox (campaign, campaign_id, mentor_link_id) WHERE mentor_link_id IS NOT NULL;

RESET lock_timeout;
