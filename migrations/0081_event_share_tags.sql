-- 0081_event_share_tags.sql
-- Which share brought a gathering's page views and RSVPs (TEC-1845;
-- ahavah-web docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 7,
-- measurement, and fix 12).
--
-- A shared gathering link may carry a share tag (?s=):
--   host   the organiser's share kit (link, announcement)
--   guest  "Bring someone with you" on a guest's confirmed page
--   app    "Send to a match", a member's chat
--   feed   Ahavah's own social posts
-- event_view_day keeps every view, as before. event_view_share_day counts
-- the tagged ones again by tag, so the total never changes meaning. An
-- RSVP keeps the tag of the page it was made from in event_rsvp.share_tag.
-- Neither says who anyone is.
--
-- Additive and idempotent: the deploy applies it once
-- (scripts/apply-deploy-migrations.sh) and the test fixtures at every
-- session start. The new table's foreign key and the new column each take
-- a lock on event or event_rsvp, so each statement waits at most 5 seconds
-- for it; if it gives up, the migration stops with an error and can simply
-- be run again. Never edit this file once it has shipped.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS event_view_share_day (
  event_id   BIGINT  NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  day        DATE    NOT NULL,
  share_tag  TEXT    NOT NULL CHECK (share_tag IN ('host', 'guest', 'app', 'feed')),
  views      INT     NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, day, share_tag)
);

ALTER TABLE event_rsvp
  ADD COLUMN IF NOT EXISTS share_tag TEXT CHECK (share_tag IN ('host', 'guest', 'app', 'feed'));

RESET lock_timeout;
