-- 0079_views_man_woman_only.sql
-- Profile views count only between a man and a woman, and never from staff
-- (TEC-1845, owner's report of 26 Oct 2026).
--
-- The API now writes no `visited` row and no `profile_view` row for any
-- other pair (service/man_woman.py, view_counts_sql). This removes the
-- rows already written before that change:
--   - the viewer and the viewed are not one man and one woman (the same
--     gender, or either one neither a man nor a woman, or no gender);
--   - the viewer is staff: `roles` contains 'admin', the admin dashboard's
--     rule (service/admin/queries/members.py).
-- `visited.subject_person_id` and `profile_view.viewer_id` are the viewer.
--
-- Archive first: every row removed is copied, unchanged, into
-- visited_removed_20261026 or profile_view_removed_20261026 with the reason
-- it went, and the DELETE removes only rows identical to their archived
-- copy. To restore, INSERT the archived columns back. An archive row goes
-- when either person's account is deleted, as the original would have.
--
-- Idempotent: a second run finds nothing left to archive or delete. The
-- deploy applies the file once and records its checksum
-- (scripts/apply-deploy-migrations.sh): never edit it once it has shipped.
SET lock_timeout = '5s';

BEGIN;

CREATE TABLE IF NOT EXISTS visited_removed_20261026 (
  subject_person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE ON UPDATE CASCADE,
  object_person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE ON UPDATE CASCADE,
  updated_at         TIMESTAMP    NOT NULL,
  invisible          BOOLEAN      NOT NULL,
  reason             TEXT         NOT NULL CHECK (reason IN ('staff', 'not_man_woman')),
  archived_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (subject_person_id, object_person_id, updated_at)
);

CREATE TABLE IF NOT EXISTS profile_view_removed_20261026 (
  viewer_id         INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  viewed_id         INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  last_notified_at  TIMESTAMPTZ  NOT NULL,
  reason            TEXT         NOT NULL CHECK (reason IN ('staff', 'not_man_woman')),
  archived_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (viewer_id, viewed_id, last_notified_at)
);

-- 1. visited: archive, then delete exactly what was archived.
INSERT INTO visited_removed_20261026
  (subject_person_id, object_person_id, updated_at, invisible, reason)
SELECT v.subject_person_id, v.object_person_id, v.updated_at, v.invisible,
       CASE WHEN 'admin' = ANY(COALESCE(a.roles, ARRAY[]::text[]))
            THEN 'staff' ELSE 'not_man_woman' END
FROM visited v
JOIN person a ON a.id = v.subject_person_id
JOIN person b ON b.id = v.object_person_id
LEFT JOIN gender ga ON ga.id = a.gender_id
LEFT JOIN gender gb ON gb.id = b.gender_id
WHERE 'admin' = ANY(COALESCE(a.roles, ARRAY[]::text[]))
   OR NOT COALESCE((ga.name = 'Man' AND gb.name = 'Woman')
                   OR (ga.name = 'Woman' AND gb.name = 'Man'), FALSE)
ON CONFLICT DO NOTHING;

DELETE FROM visited v
USING visited_removed_20261026 r
WHERE r.subject_person_id = v.subject_person_id
  AND r.object_person_id  = v.object_person_id
  AND r.updated_at        = v.updated_at
  AND r.invisible         = v.invisible;

-- 2. profile_view: the same.
INSERT INTO profile_view_removed_20261026
  (viewer_id, viewed_id, last_notified_at, reason)
SELECT pv.viewer_id, pv.viewed_id, pv.last_notified_at,
       CASE WHEN 'admin' = ANY(COALESCE(a.roles, ARRAY[]::text[]))
            THEN 'staff' ELSE 'not_man_woman' END
FROM profile_view pv
JOIN person a ON a.id = pv.viewer_id
JOIN person b ON b.id = pv.viewed_id
LEFT JOIN gender ga ON ga.id = a.gender_id
LEFT JOIN gender gb ON gb.id = b.gender_id
WHERE 'admin' = ANY(COALESCE(a.roles, ARRAY[]::text[]))
   OR NOT COALESCE((ga.name = 'Man' AND gb.name = 'Woman')
                   OR (ga.name = 'Woman' AND gb.name = 'Man'), FALSE)
ON CONFLICT DO NOTHING;

DELETE FROM profile_view pv
USING profile_view_removed_20261026 r
WHERE r.viewer_id        = pv.viewer_id
  AND r.viewed_id        = pv.viewed_id
  AND r.last_notified_at = pv.last_notified_at;

COMMIT;

RESET lock_timeout;
