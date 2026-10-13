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

# Verdict rules (TEC-946):
#   score <  0.30           -> approved
#   score >= 0.70           -> rejected
#   0.30 <= score < 0.70    -> manual_review
#   score = -1.0 (download failed) -> left at 'pending' for the next tick.
#
# This statement records the face count but does not apply the face rule.
# The rule lives in one place, service/photo_rules.py, and the cron runs it
# (Q_RECHECK_MAIN_PHOTO_FACE_OF_PHOTOS) straight after this statement in the
# same transaction. It follows the owner's rule: a main photo with no face
# is left alone when the member has another photo that shows a face; only a
# member with no face photo at all has it sent to manual_review, never to
# 'rejected', because the detector is good, not perfect. A NULL face_count
# (the check did not run) holds nothing back, and the stricter nudity
# verdicts always win, since the rule only ever touches an approved photo.
# Before the review fix (health review, 13 Oct 2026) this CASE held every
# position 1 photo with no face, even beside a face photo.
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
        ELSE                             'approved'::photo_moderation_status
    END,
    moderated_at = CASE
        WHEN %(nsfw_score)s < 0 THEN moderated_at
        ELSE NOW()
    END
WHERE
    uuid = %(uuid)s
"""
