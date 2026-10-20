-- 0071_events.sql
-- Gatherings (TEC-1845, docs/superpowers/plans/2026-10-21-events-release-1.md).
-- 0069 is reserved for TEC-1897 and 0070 is the Unmatch branch's.
--
--   organiser             who may host. Approved once by an admin; later
--                         gatherings publish without review unless flagged.
--   organiser_link        the 7 day magic link, stored as its sha256.
--   event                 a gathering. "ended" is published with ends_at past;
--                         "paused" is paused_at set.
--   event_rsvp            one per address per gathering. A place is held only
--                         once confirmed. Name and email are erased 90 days
--                         after the gathering ends (erased_at).
--   event_view_day        page views per gathering per day.
--   ahavah_invite_request leaders asking Ahavah to come.
--   email_outbox          gains organiser_id: an organiser is neither a member
--                         nor a lead.

CREATE TABLE IF NOT EXISTS organiser (
  id                BIGSERIAL    PRIMARY KEY,
  name              TEXT         NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  kind              TEXT         NOT NULL CHECK (kind IN ('assembly', 'fellowship_leader', 'ministry', 'other', 'ahavah')),
  email             TEXT         NOT NULL,
  normalized_email  TEXT         NOT NULL UNIQUE,
  city              TEXT         CHECK (char_length(city) <= 80),
  country           TEXT         CHECK (char_length(country) <= 80),
  about             TEXT         CHECK (char_length(about) <= 1000),
  verified_at       TIMESTAMPTZ,
  approved_at       TIMESTAMPTZ,
  approved_by       INT          REFERENCES person(id) ON DELETE SET NULL,
  revoked_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organiser_link (
  id            BIGSERIAL    PRIMARY KEY,
  organiser_id  BIGINT       NOT NULL REFERENCES organiser(id) ON DELETE CASCADE,
  token_hash    TEXT         NOT NULL UNIQUE,
  expires_at    TIMESTAMPTZ  NOT NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__organiser_link__expires_at ON organiser_link (expires_at);

CREATE TABLE IF NOT EXISTS event (
  id                BIGSERIAL    PRIMARY KEY,
  slug              TEXT         NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 45),
  organiser_id      BIGINT       NOT NULL REFERENCES organiser(id) ON DELETE CASCADE,
  title             TEXT         NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
  starts_at         TIMESTAMPTZ  NOT NULL,
  ends_at           TIMESTAMPTZ  NOT NULL,
  tz                TEXT         NOT NULL,
  tz_label          TEXT         NOT NULL CHECK (char_length(tz_label) BETWEEN 1 AND 40),
  mode              TEXT         NOT NULL CHECK (mode IN ('in_person', 'online')),
  city              TEXT         CHECK (char_length(city) <= 80),
  country           TEXT         CHECK (char_length(country) <= 80),
  region            TEXT         NOT NULL CHECK (region IN ('africa', 'asia', 'europe', 'north-america',
                                                          'oceania', 'south-america', 'online')),
  venue             TEXT         CHECK (char_length(venue) <= 200),
  venue_visibility  TEXT         NOT NULL DEFAULT 'confirmed' CHECK (venue_visibility IN ('public', 'confirmed')),
  online_url        TEXT         CHECK (online_url ~ '^https://' AND char_length(online_url) <= 500),
  description       TEXT         NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  capacity          INT          CHECK (capacity BETWEEN 1 AND 5000),
  tags              TEXT[]       NOT NULL DEFAULT '{}',
  feast             TEXT         CHECK (feast IN ('passover', 'unleavened_bread', 'firstfruits', 'pentecost',
                                                  'trumpets', 'atonement', 'tabernacles', 'last_great_day')),
  show_going        BOOLEAN      NOT NULL DEFAULT FALSE,
  cover_key         TEXT,
  status            TEXT         NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending', 'published', 'cancelled')),
  flag_reason       TEXT,
  paused_at         TIMESTAMPTZ,
  ahavah_attending  BOOLEAN      NOT NULL DEFAULT FALSE,
  cancel_note       TEXT         CHECK (char_length(cancel_note) <= 500),
  changed_at        TIMESTAMPTZ,
  change_before     JSONB,
  change_after      JSONB,
  published_at      TIMESTAMPTZ,
  cancelled_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (ends_at > starts_at),
  CHECK (mode = 'online' OR (city IS NOT NULL AND country IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx__event__listing ON event (region, starts_at) WHERE status = 'published' AND paused_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__event__organiser ON event (organiser_id);

CREATE TABLE IF NOT EXISTS event_rsvp (
  id                          BIGSERIAL    PRIMARY KEY,
  event_id                    BIGINT       NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  name                        TEXT         CHECK (char_length(name) BETWEEN 1 AND 80),
  email                       TEXT,
  normalized_email            TEXT,
  party_size                  INT          NOT NULL CHECK (party_size BETWEEN 1 AND 10),
  status                      TEXT         NOT NULL DEFAULT 'going' CHECK (status IN ('going', 'cancelled')),
  confirmed_at                TIMESTAMPTZ,
  token_hash                  TEXT         UNIQUE,
  confirm_by                  TIMESTAMPTZ  NOT NULL,
  share_email_with_organiser  BOOLEAN      NOT NULL DEFAULT FALSE,
  marketing_consent           BOOLEAN      NOT NULL DEFAULT FALSE,
  source                      TEXT         NOT NULL,
  person_id                   INT          REFERENCES person(id) ON DELETE SET NULL,
  lead_id                     BIGINT       REFERENCES lead(id) ON DELETE SET NULL,
  new_address                 BOOLEAN      NOT NULL DEFAULT FALSE,
  attended_at                 TIMESTAMPTZ,
  resends                     INT          NOT NULL DEFAULT 0,
  digested_at                 TIMESTAMPTZ,
  cancelled_at                TIMESTAMPTZ,
  erased_at                   TIMESTAMPTZ,
  created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (event_id, normalized_email),
  CHECK (erased_at IS NOT NULL OR (name IS NOT NULL AND email IS NOT NULL AND normalized_email IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx__event_rsvp__normalized_email ON event_rsvp (normalized_email);
CREATE INDEX IF NOT EXISTS idx__event_rsvp__person_id ON event_rsvp (person_id) WHERE person_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_view_day (
  event_id  BIGINT  NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  day       DATE    NOT NULL,
  views     INT     NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, day)
);

CREATE TABLE IF NOT EXISTS ahavah_invite_request (
  id             BIGSERIAL    PRIMARY KEY,
  gathering      TEXT         NOT NULL CHECK (char_length(gathering) BETWEEN 1 AND 200),
  dates          TEXT         NOT NULL CHECK (char_length(dates) BETWEEN 1 AND 120),
  place          TEXT         NOT NULL CHECK (char_length(place) BETWEEN 1 AND 200),
  numbers        INT          CHECK (numbers BETWEEN 1 AND 100000),
  contact_name   TEXT         NOT NULL CHECK (char_length(contact_name) BETWEEN 1 AND 80),
  contact_email  TEXT         NOT NULL,
  status         TEXT         NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'planned', 'declined')),
  notes          TEXT         CHECK (char_length(notes) <= 2000),
  created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS organiser_id BIGINT REFERENCES organiser(id) ON DELETE CASCADE;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id, organiser_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__organiser_run
  ON email_outbox (campaign, campaign_id, organiser_id) WHERE organiser_id IS NOT NULL;
