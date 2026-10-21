-- 0075_admin_community.sql
-- Admin, acting on the community (TEC-1897,
-- docs/superpowers/plans/2026-10-18-admin-community-data.md): the records
-- the design needs that the database did not keep. Planned as 0069; 0070
-- to 0074 shipped first, so it takes the next free number. Needs 0072
-- (person_report) applied first.
--
-- Additive. The deploy applies each file once and records its checksum
-- (scripts/apply-deploy-migrations.sh), and stops if an applied file
-- changes: never edit this file once it has shipped; a change is 0076.
-- Idempotent, because the test fixtures apply it at every session start.
--
-- person, photo, person_report and email_send_log are busy tables. Each
-- statement waits at most 5 seconds for its lock rather than queueing every
-- later query behind it; one that times out stops the deploy before the new
-- code starts, and a rerun picks up where it stopped. No backfill: every
-- new column is nullable with no default when it is added, so nothing is
-- rewritten.
SET lock_timeout = '5s';

-- 1. A report's state and outcome, on the report itself. person_report
-- (0072) keeps one row per report filed, keyed by the pair and the skipped
-- row's created_at at the time, so a report made again on the same pair is
-- a new row and starts unresolved. outcome NULL is Unresolved. Recording
-- 'deactivated' does not deactivate anyone; the drawer's Deactivate does.
ALTER TABLE person_report
  ADD COLUMN IF NOT EXISTS outcome           TEXT
      CHECK (outcome IN ('dismissed', 'warned', 'deactivated')),
  ADD COLUMN IF NOT EXISTS note              TEXT CHECK (char_length(note) <= 1000),
  ADD COLUMN IF NOT EXISTS resolved_by_uuid  UUID,
  ADD COLUMN IF NOT EXISTS resolved_by_email TEXT,
  ADD COLUMN IF NOT EXISTS resolved_at       TIMESTAMPTZ;

-- The unresolved count runs on every Overview load (Needs you).
CREATE INDEX IF NOT EXISTS idx__person_report__unresolved
  ON person_report (reported_at) WHERE outcome IS NULL;

-- 2. "Email me when a report arrives" (frame R.2): the switch for the
-- report email that already goes to DUO_REPORT_EMAIL (antiabuse/lodgereport,
-- 21 Oct 2026). The owner's alone, and on unless he turns it off; a rerun
-- never turns it back on. The log is each owner alert's once-only key,
-- written in the transaction that decides to send, before the send, so a
-- repeat cron tick never sends twice.
CREATE TABLE IF NOT EXISTS admin_alert_pref (
  alert      TEXT        PRIMARY KEY CHECK (alert IN ('report')),
  enabled    BOOLEAN     NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by TEXT
);

INSERT INTO admin_alert_pref (alert, enabled) VALUES ('report', TRUE)
ON CONFLICT (alert) DO NOTHING;

CREATE TABLE IF NOT EXISTS admin_alert_log (
  alert     TEXT        NOT NULL,
  alert_key TEXT        NOT NULL,
  sent_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (alert, alert_key)
);

-- 3. Unhandled API errors per route and hour (finding 17). `route` is the
-- Flask rule ("/admin/users/<uuid>"), never the path, so no id or address
-- is stored. Rows older than 30 days are deleted by the adminalerts cron.
CREATE TABLE IF NOT EXISTS api_error_tally (
  route   TEXT        NOT NULL,
  hour    TIMESTAMPTZ NOT NULL,
  n       INT         NOT NULL DEFAULT 0,
  last_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (route, hour)
);

-- 4. The Barbados days a person was online, with the first and last time
-- seen that day. person.last_online_time keeps only the latest moment, so
-- "came back within 7 days of an email" could not be answered. Written with
-- each presence bump from the deploy on; nothing before it exists. Rows
-- older than 120 days are deleted by the adminalerts cron.
CREATE TABLE IF NOT EXISTS member_online_day (
  person_id INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  day       DATE        NOT NULL,
  first_at  TIMESTAMPTZ NOT NULL,
  last_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (person_id, day)
);

-- 5. When a photo was stored, so the photo gate list can say how long a
-- photo has waited for a moderator. Added without a default first, so every
-- photo already stored keeps NULL ("not recorded") instead of today's date;
-- the default then applies to new photos only.
ALTER TABLE photo ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ;
ALTER TABLE photo ALTER COLUMN uploaded_at SET DEFAULT NOW();

-- 6. Run history reads email_send_log by campaign and run id up to 24 times
-- a load; its indexes led with person_id.
CREATE INDEX IF NOT EXISTS email_send_log_campaign_idx
  ON email_send_log (campaign, campaign_id);

RESET lock_timeout;
