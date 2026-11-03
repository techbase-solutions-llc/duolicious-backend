-- 0090_carousel_slides.sql
-- Carousel posts on Facebook and Instagram (TEC-1845; ahavah-admin
-- docs/plans/2026-11-02-carousel-posts.md). The first is the 7-slide
-- Families carousel, Fri 13 Nov 2026.
--
--   publishing_queue.slide_count  how many pictures the post carries, 2 to
--                   10 (Meta's limits for a carousel). NULL is a single
--                   image, which is every row before this file.
--   publishing_queue_slide        one row per slide of a carousel row, by
--                   position from 1. The queue row's own image_key,
--                   image_url and image_sha256 hold slide 1, so the
--                   thumbnail, the render completion and dispatch_check
--                   read a carousel exactly as they read a single image.
--
-- A slide goes with its queue row when the row is deleted. Its stored
-- object is deleted by the cleanup batch, as the row's own is.
--
-- Adding a nullable column rewrites nothing; the statement waits at most 5
-- seconds for its lock on publishing_queue. claim_spotlight_posts returns
-- SETOF publishing_queue, so it carries the new column without a change.
-- Additive and idempotent: safe to run again. Never edit this file once it
-- has shipped.
SET lock_timeout = '5s';

ALTER TABLE publishing_queue
  ADD COLUMN IF NOT EXISTS slide_count SMALLINT
    CHECK (slide_count IS NULL OR slide_count BETWEEN 2 AND 10);

CREATE TABLE IF NOT EXISTS publishing_queue_slide (
  queue_id      UUID         NOT NULL REFERENCES publishing_queue(id) ON DELETE CASCADE,
  position      SMALLINT     NOT NULL CHECK (position BETWEEN 1 AND 10),
  image_key     TEXT,
  image_url     TEXT,
  image_sha256  TEXT,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (queue_id, position)
);

-- The cleanup batch and the reference check look slides up by key.
CREATE INDEX IF NOT EXISTS publishing_queue_slide_image_key_idx
  ON publishing_queue_slide (image_key) WHERE image_key IS NOT NULL;

RESET lock_timeout;
