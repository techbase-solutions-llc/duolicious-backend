"""The face rule, run again when a member's main photo changes (health
review, 13 Oct 2026, finding 98).

The photo cron applies the face rule once, when it first scores a photo,
and only at position 1 (service/cron/nsfwphotorunner/sql, TEC-946). A
reorder or a delete could then make a photo with no face the main one
without anyone looking. These statements run the rule again for the
member's main photo, the lowest position, after a reorder, a delete and
each scoring pass.

The main photo goes to manual_review, for a person to decide, when all of
these hold:

- it is approved and the detector saw no face in it (face_count = 0);
- no moderator has confirmed it (face_confirmed_at is NULL, finding 97);
- the member has no other approved photo that shows a face. A face count
  above 0 counts, a moderator's confirmation counts, and so does an
  unchecked photo (face_count NULL), because a detector that did not look
  must never hold a photo back.

That last condition is the owner's rule: a photo with no face among photos
where the face shows is left alone, and only a member with no face photo
at all is affected. The rule never rejects, never releases a held photo
and never touches a photo that is not the main one. Each statement returns
the person id of every photo it held.
"""

_Q_RECHECK = """
WITH main AS (
    SELECT DISTINCT ON (ph.person_id)
        ph.person_id,
        ph.position,
        ph.moderation_status,
        ph.face_count,
        ph.face_confirmed_at
    FROM
        photo ph
    WHERE
        ph.person_id IN ({people})
    ORDER BY
        ph.person_id, ph.position
)
UPDATE
    photo
SET
    moderation_status = 'manual_review'::photo_moderation_status,
    moderated_at = NOW()
FROM
    main
WHERE
    photo.person_id = main.person_id
AND
    photo.position = main.position
AND
    main.moderation_status = 'approved'
AND
    main.face_count = 0
AND
    main.face_confirmed_at IS NULL
AND
    NOT EXISTS (
        SELECT 1
        FROM photo other
        WHERE other.person_id = main.person_id
          AND other.position <> main.position
          AND other.moderation_status = 'approved'
          AND (other.face_count IS NULL
               OR other.face_count > 0
               OR other.face_confirmed_at IS NOT NULL)
    )
RETURNING
    photo.person_id
"""

# For the members named in %(person_ids)s (a reorder or a delete).
Q_RECHECK_MAIN_PHOTO_FACE = _Q_RECHECK.format(
    people='SELECT unnest(%(person_ids)s::int[])')

# For the owners of the photos in %(uuids)s (after a scoring pass).
Q_RECHECK_MAIN_PHOTO_FACE_OF_PHOTOS = _Q_RECHECK.format(
    people='SELECT person_id FROM photo WHERE uuid = ANY(%(uuids)s::text[])')
