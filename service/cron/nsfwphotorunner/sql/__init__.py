Q_50_UNCHECKED_PHOTOS = """
SELECT
    uuid
FROM
    photo
WHERE
    nsfw_score IS NULL
LIMIT
    50
"""

# Verdict rules, and the face rule is deliberately timid (TEC-946).
#
# Nudity, unchanged:
#   score <  0.30           -> approved
#   score >= 0.70           -> rejected
#   0.30 <= score < 0.70    -> manual_review
#   score = -1.0 (download failed) -> left at 'pending' for the next tick.
#
# Face, new: a photo the nudity rule would APPROVE goes to manual_review
# instead when it is the member's primary photo and the detector saw no
# face in it. Never to 'rejected': the detector is good, not perfect, and a
# member who is small in frame, in shadow or turned away must be looked at
# by a person, not hidden by a model. Only the primary photo, position 1,
# because that is the one a member presents themselves with; a second photo
# of a landscape or a meal is ordinary. A NULL face_count (the check did
# not run) changes nothing, so a detector failure can never hold a photo
# back, and the stricter nudity verdicts always win.
Q_SET_NSFW_SCORE = """
UPDATE
    photo
SET
    nsfw_score = %(nsfw_score)s,
    face_count = COALESCE(%(face_count)s::int, face_count),
    face_checked_at = CASE
        WHEN %(face_count)s::int IS NULL THEN face_checked_at
        ELSE NOW()
    END,
    moderation_status = CASE
        WHEN %(nsfw_score)s < 0     THEN moderation_status
        WHEN %(nsfw_score)s >= 0.70 THEN 'rejected'::photo_moderation_status
        WHEN %(nsfw_score)s >= 0.30 THEN 'manual_review'::photo_moderation_status
        WHEN %(face_count)s::int = 0 AND position = 1
                                    THEN 'manual_review'::photo_moderation_status
        ELSE                             'approved'::photo_moderation_status
    END,
    moderated_at = CASE
        WHEN %(nsfw_score)s < 0 THEN moderated_at
        ELSE NOW()
    END
WHERE
    uuid = %(uuid)s
"""
