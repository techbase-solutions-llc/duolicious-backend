-- 0062_photo_gate.sql
-- The photo gate's predicate (health review, 13 Oct 2026, finding 91).
--
-- A member who has no photo of themselves can browse every other member's
-- photos. The gate takes other members' photos out of the API's answers
-- for that member, and these two functions are the one definition every
-- query uses. The queries apply them only while the API runs with
-- AHAVAH_PHOTO_GATE_ENABLED on (service/photo_gate.py), which stays off
-- until the prompt that tells a gated member why ships (W8). With it off,
-- nothing reads these functions except the admin's count of gated members.
--
-- can_view_photos(viewer): the member may see other members' photos.
--   True for the admin role. Otherwise true when the member has at least
--   one approved photo that shows a face: the detector saw one
--   (face_count > 0), a moderator confirmed it (face_confirmed_at, 0061),
--   or the detector never looked (face_count NULL, the TEC-946 rule that a
--   detector failure never holds a photo back). Any approved photo counts,
--   not only the main one.
--
-- photos_visible_to(viewer, owner): the viewer may see this owner's
--   photos. True for an anonymous viewer (a public profile, unchanged),
--   for the owner's own photos, when can_view_photos(viewer), and when the
--   pair is matched or either has messaged the other. Matches and
--   conversations keep their photos whatever the gate says.
--
-- Idempotent: CREATE OR REPLACE.

CREATE OR REPLACE FUNCTION can_view_photos(viewer INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT
        EXISTS (
            SELECT 1
            FROM person
            WHERE id = viewer
              AND 'admin' = ANY(COALESCE(roles, ARRAY[]::text[]))
        )
        OR EXISTS (
            SELECT 1
            FROM photo
            WHERE person_id = viewer
              AND moderation_status = 'approved'
              AND (face_count IS NULL
                   OR face_count > 0
                   OR face_confirmed_at IS NOT NULL)
        );
$$;

CREATE OR REPLACE FUNCTION photos_visible_to(viewer INT, owner INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT
        viewer IS NULL
        OR viewer = owner
        OR can_view_photos(viewer)
        OR EXISTS (
            SELECT 1
            FROM ahavah_match
            WHERE user_a_id = LEAST(viewer, owner)
              AND user_b_id = GREATEST(viewer, owner)
        )
        OR EXISTS (
            SELECT 1
            FROM messaged
            WHERE (subject_person_id = viewer AND object_person_id = owner)
               OR (subject_person_id = owner AND object_person_id = viewer)
        );
$$;
