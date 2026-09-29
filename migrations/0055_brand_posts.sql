-- migrations/0055_brand_posts.sql
--
-- Scheduled social posting (TEC-945), task 1. A brand post is a queue row.
--
-- Ahavah's own posts, the ones made from the Claude Design sets rather than
-- from a member's card, go through the same queue the member cards use. That
-- is the point: they inherit the operator approval, the one publisher and the
-- removal path that already exist, instead of growing a second of each.
--
-- A brand row has no subject, like a roundup, so it starts in
-- `awaiting_render` and moves to `review` once its artwork is attached
-- through the existing image route. Nothing about the status machine
-- changes; only the list of kinds does.
--
-- The constraint is dropped and re-added under the name Postgres gave the
-- inline CHECK in 0041 (`publishing_queue_kind_check`, confirmed against
-- production on 2026-09-29), so the migration is idempotent and leaves the
-- same name behind for the next one.

ALTER TABLE publishing_queue DROP CONSTRAINT IF EXISTS publishing_queue_kind_check;
ALTER TABLE publishing_queue ADD CONSTRAINT publishing_queue_kind_check
  CHECK (kind IN ('welcome', 'roundup', 'member_of_week', 'highlight', 'brand'));
