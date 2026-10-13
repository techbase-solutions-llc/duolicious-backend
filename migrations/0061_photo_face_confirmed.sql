-- 0061_photo_face_confirmed.sql
-- A moderator's face confirmation is kept on the photo (health review,
-- 13 Oct 2026, finding 97).
--
-- The face rule (0056, TEC-946) sends a main photo in which the detector
-- saw no face to a person. When a moderator approves it, the approve route
-- set only moderation_status and moderated_at, so nothing on the photo said
-- that a person had looked and accepted it. The decision was in the audit
-- log alone.
--
--   face_confirmed_at   when a moderator approved this photo although the
--                       detector saw no face in it (face_count = 0). NULL
--                       for every other photo.
--
-- A confirmed photo counts as a photo that shows the member: the face rule
-- never holds it again, and the photo gate (finding 91) lets its owner see
-- members' photos.
--
-- Backfill: none. On 13 Oct 2026 production had 6 approved photos with
-- face_count 0 and no approve_photo audit row for any of them, so no past
-- moderator decision is lost.

ALTER TABLE photo
  ADD COLUMN IF NOT EXISTS face_confirmed_at TIMESTAMPTZ;
