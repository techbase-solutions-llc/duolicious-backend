-- migrations/0056_photo_face_check.sql
--
-- A profile photo has to show the member (TEC-946), task 2.
--
-- The photo cron already scores every upload for nudity. It now also asks
-- whether it can see a face, and records the answer here. Both columns are
-- nullable because every existing row is unchecked; NULL means "not looked
-- at yet", which is different from 0, "looked and saw nobody".
--
--   face_count        how many faces the detector saw in the 450px render.
--   face_checked_at   when it looked.

ALTER TABLE photo
  ADD COLUMN IF NOT EXISTS face_count      INT,
  ADD COLUMN IF NOT EXISTS face_checked_at TIMESTAMP;
