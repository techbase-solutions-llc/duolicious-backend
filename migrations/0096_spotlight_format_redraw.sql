-- 0096_spotlight_format_redraw.sql
-- Format-only redraw of an approved Spotlight member card (TEC-2113,
-- docs/plans/2026-11-06-spotlight-format-redraw.md). The owner, 6 Nov 2026:
-- member cards move to 4:5, and an approved card is redrawn without asking
-- the member again.
--
-- A row carrying `format_redraw_requested_at` is held: its new artwork has
-- been asked for and has not landed on every platform row yet. The publish
-- run must not claim it, with the old square artwork or with one platform
-- redrawn and the other not, so `claim_spotlight_posts` skips it. Its status
-- and `scheduled_for` are never touched; clearing the column is what returns
-- it to the run, which claims it at once if its slot has already passed.
--
-- Additive and idempotent (ADD COLUMN IF NOT EXISTS, CREATE OR REPLACE), as
-- the deploy and the test fixture both need. Never edit once shipped; a
-- change is the next number. Every later redefinition of
-- claim_spotlight_posts must keep the hold.
SET lock_timeout = '5s';

ALTER TABLE publishing_queue
  ADD COLUMN IF NOT EXISTS format_redraw_requested_at TIMESTAMPTZ;

-- The tick's listing of held rows reads this; almost every row is NULL.
CREATE INDEX IF NOT EXISTS publishing_queue_format_redraw_idx
  ON publishing_queue (request_key) WHERE format_redraw_requested_at IS NOT NULL;

-- Migration 0044's definition with one added condition: the hold.
CREATE OR REPLACE FUNCTION claim_spotlight_posts(max_rows int)
RETURNS SETOF publishing_queue
LANGUAGE sql
AS $$
  UPDATE publishing_queue q
     SET status = 'processing',
         delivery_state = 'attempting',
         lease_token = encode(gen_random_bytes(16), 'hex'),
         lease_until = NOW() + interval '10 minutes',
         attempts = attempts + 1,
         error = NULL,
         updated_at = NOW()
   WHERE q.id IN (
     SELECT id FROM publishing_queue
      WHERE scheduled_for <= NOW()
        AND cancellation_requested_at IS NULL
        AND format_redraw_requested_at IS NULL
        AND (status = 'scheduled' OR (status = 'failed' AND attempts < 3))
      ORDER BY scheduled_for
      FOR UPDATE SKIP LOCKED
      LIMIT max_rows)
  RETURNING q.*;
$$;

RESET lock_timeout;
