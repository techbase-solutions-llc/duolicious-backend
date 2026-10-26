-- 0078_discover_filters.sql
-- A member's Discover filters, kept with the account (TEC-1845).
--
-- The web app kept the filters only in the browser, and removed them at
-- sign-out so the next person on a shared device does not get them. A
-- member who signed in again, or opened Ahavah on another device, found
-- them gone (owner, 25 Oct: "my filters don't ... stay persistent").
-- GET and PUT /discover-filters read and write this row; the browser's
-- copy is only a cache of it.
--
-- One row per member, removed with the member. `filters` is what
-- PUT /discover-filters accepted (service/discover_filters), never more
-- than the keys and values it allows.
-- Idempotent: safe to run again.
SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS discover_filters (
  person_id   INT          PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
  filters     JSONB        NOT NULL,
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

RESET lock_timeout;
