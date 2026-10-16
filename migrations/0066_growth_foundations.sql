-- 0066_growth_foundations.sql
-- The shared groundwork for the growth features (TEC-1845,
-- docs/superpowers/plans/2026-10-16-growth-foundations.md). The couple
-- tools, profile prompts, gatherings and the matchmaker all read or write
-- these.
--
--   lead          one row per address and source for someone who gave
--                 Ahavah an email before joining: a tool player who saved a
--                 result, a gathering RSVP, a visitor alert. Marketing
--                 consent is per row, with the key of the exact wording
--                 shown. A tick that arrives after the address unsubscribed
--                 waits in consent_pending_* until a confirm link issued
--                 after it is tapped. A member's address is never a lead
--                 (service/leads). Deleted 12 months after last_seen_at, 8
--                 days after creation if never confirmed, or on request.
--   email_outbox  may now hold mail for a lead (lead_id) instead of a
--                 member (person_id); exactly one of the two.
--   prompt_bank   the prompts members answer. Created here because the
--                 weekly "Question of the week" post reads it; seeded by the
--                 profile prompts plan once the owner has the wording.
--   publishing_queue.kind  gains event, prompt and tool.
--   lead_source   existing values moved onto one taxonomy
--                 (service/leads/sources.py). Only values in the old shapes
--                 match, so a second run changes nothing.
--
-- First-party only, never shared. Idempotent: the deploy may run this file
-- more than once.

CREATE TABLE IF NOT EXISTS lead (
  id                        BIGSERIAL    PRIMARY KEY,
  email                     TEXT         NOT NULL,
  normalized_email          TEXT         NOT NULL,
  source                    TEXT         NOT NULL,
  marketing_consent         BOOLEAN      NOT NULL DEFAULT FALSE,
  consent_wording           TEXT,
  consented_at              TIMESTAMPTZ,
  unsubscribed_at           TIMESTAMPTZ,
  consent_pending_wording   TEXT,
  consent_pending_at        TIMESTAMPTZ,
  confirmed_at              TIMESTAMPTZ,
  confirmed_via             TEXT         CHECK (confirmed_via IN ('otp', 'link')),
  confirm_token_hash        TEXT,
  confirm_token_expires_at  TIMESTAMPTZ,
  person_id                 INT          REFERENCES person(id) ON DELETE CASCADE,
  converted_at              TIMESTAMPTZ,
  last_seen_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (normalized_email, source),
  CHECK (NOT marketing_consent OR consent_wording IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx__lead__email ON lead (email);
CREATE INDEX IF NOT EXISTS idx__lead__person_id ON lead (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__lead__last_seen_at ON lead (last_seen_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx__lead__confirm_token_hash
  ON lead (confirm_token_hash) WHERE confirm_token_hash IS NOT NULL;

-- Lead mail. A lead has no person row, so the outbox names one or the other.
ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS lead_id BIGINT REFERENCES lead(id) ON DELETE CASCADE;
ALTER TABLE email_outbox ALTER COLUMN person_id DROP NOT NULL;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__lead_run
  ON email_outbox (campaign, campaign_id, lead_id) WHERE lead_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS prompt_bank (
  key       TEXT     PRIMARY KEY CHECK (key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  text      TEXT     NOT NULL CHECK (char_length(text) BETWEEN 1 AND 120),
  category  TEXT     NOT NULL,
  active    BOOLEAN  NOT NULL DEFAULT TRUE,
  sort      INT      NOT NULL DEFAULT 0
);

-- Dropped and re-added under the name 0055 left, so the next migration can
-- do the same.
ALTER TABLE publishing_queue DROP CONSTRAINT IF EXISTS publishing_queue_kind_check;
ALTER TABLE publishing_queue ADD CONSTRAINT publishing_queue_kind_check
  CHECK (kind IN ('welcome', 'roundup', 'member_of_week', 'highlight', 'brand',
                  'event', 'prompt', 'tool'));

-- lead_source on one taxonomy. The writers change in the same release
-- (service/person/attribution.py, service/person/__init__.py).
UPDATE person    SET lead_source = 'tool:checklist' WHERE lead_source = 'marriage_checklist';
UPDATE onboardee SET lead_source = 'tool:checklist' WHERE lead_source = 'marriage_checklist';

UPDATE person
   SET lead_source = CASE WHEN COALESCE(btrim(first_touch->>'code'), '') <> ''
                          THEN 'referral:' || upper(btrim(first_touch->>'code'))
                          ELSE 'referral' END
 WHERE lead_source = 'invite';

UPDATE person
   SET lead_source = 'utm:' || lead_source
                     || COALESCE('/' || lower(NULLIF(btrim(first_touch->>'utm_campaign'), '')), '')
 WHERE strpos(lead_source, ':') = 0
   AND lead_source = lower(btrim(first_touch->>'utm_source'));

UPDATE person
   SET lead_source = 'site:' || lead_source
 WHERE strpos(lead_source, ':') = 0
   AND lead_source = lower(btrim(first_touch->>'referrer_host'));
