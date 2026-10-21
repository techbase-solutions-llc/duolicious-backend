"""SQL for Moderation tab — photos + rude messages.

Reports sub-tab continues to use the existing /admin/reports surface
from service/api/moderation_routes.py — we DON'T reimplement here."""
from service.admin.queries.members import member_sql

_MEMBER_P = member_sql('p')

Q_PHOTOS_LIST = f"""
    SELECT
        ph.uuid AS photo_uuid,
        ph.position,
        ph.moderation_status::text AS moderation_status,
        ph.nsfw_score,
        ph.face_count,
        ph.face_checked_at,
        ph.moderated_at,
        ph.uploaded_at,
        p.email AS owner_email,
        p.uuid::text AS owner_uuid,
        NOT ({_MEMBER_P}) AS owner_is_staff
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
     -- 'queue' is everything waiting on a person: pending AND manual_review.
     -- The Photos tab used to ask for 'pending' alone, so a photo the cron
     -- had sent for a human decision was never shown to anyone (TEC-946).
     -- 'approved_no_face' (TEC-1897, finding 9): approved photos the
     -- detector saw no face in and no moderator has confirmed.
     WHERE (%(state)s = ''
            OR ph.moderation_status::text = %(state)s
            OR (%(state)s = 'queue'
                AND ph.moderation_status::text IN ('pending', 'manual_review'))
            OR (%(state)s = 'approved_no_face'
                AND ph.moderation_status::text = 'approved'
                AND ph.face_count = 0
                AND ph.face_confirmed_at IS NULL))
     ORDER BY ph.moderated_at DESC NULLS FIRST
     LIMIT 100
"""

# Two kinds of number. Pending and manual review are the WORK queue, the
# rows the list above shows, so they count every photo waiting for a
# decision: a staff profile is shown to members like any other and its
# photos are moderated the same way. Approved and rejected describe the
# community, so they count members' photos only (members.py); on 13 Oct
# 2026 Approved read 164, 4 of them on staff accounts.
Q_PHOTOS_KPIS = f"""
    SELECT
        COUNT(*) FILTER (WHERE ph.moderation_status::text = 'pending') AS pending,
        COUNT(*) FILTER (WHERE ph.moderation_status::text = 'manual_review') AS manual_review,
        COUNT(*) FILTER (WHERE ph.moderation_status::text = 'approved' AND {_MEMBER_P}) AS approved,
        COUNT(*) FILTER (WHERE ph.moderation_status::text = 'rejected' AND {_MEMBER_P}) AS rejected
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
"""

# Frame P.3's line, "6 photos, 5 people: 4 members and 1 staff account".
Q_APPROVED_NO_FACE_KPIS = f"""
    SELECT count(*)::int AS photos,
           count(DISTINCT ph.person_id)::int AS people,
           count(DISTINCT ph.person_id) FILTER (WHERE {_MEMBER_P})::int AS members,
           count(DISTINCT ph.person_id) FILTER (WHERE NOT ({_MEMBER_P}))::int AS staff
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
     WHERE ph.moderation_status::text = 'approved'
       AND ph.face_count = 0
       AND ph.face_confirmed_at IS NULL
"""

# The photo gate (findings 91 and 99): how many members can_view_photos()
# (migration 0062) holds, whether or not the switch is on, so the owner can
# see the effect before turning it on. Activated members only. A gated
# member keeps photos with matches and conversations, so the third count
# says how many of them that exemption reaches.
Q_PHOTO_GATE_KPIS = f"""
    SELECT
        COUNT(*) AS gated_members,
        COUNT(*) FILTER (
            WHERE p.last_online_time > NOW() - INTERVAL '30 days'
        ) AS gated_seen_30_days,
        COUNT(*) FILTER (
            WHERE EXISTS (SELECT 1 FROM ahavah_match am
                           WHERE p.id IN (am.user_a_id, am.user_b_id))
               OR EXISTS (SELECT 1 FROM messaged ms
                           WHERE p.id IN (ms.subject_person_id, ms.object_person_id))
        ) AS gated_with_match_or_conversation
      FROM person p
     WHERE {_MEMBER_P}
       AND p.activated
       AND NOT can_view_photos(p.id)
"""

# rude_message schema (init-api.sql:1675):
#   person_id INT, created_at TIMESTAMP, message TEXT
# This is the *sender's* flagged outgoing message — no recipient is stored.
# We surface sender email + message snippet so the admin can see what got
# blocked. The FE shape uses sender_email + a single "recipient" column
# left empty (the table has no recipient).
Q_RUDE_MESSAGES = """
    SELECT
        rm.created_at,
        p.email AS sender_email,
        ''::text AS recipient_email,
        rm.message AS snippet
      FROM rude_message rm
      JOIN person p ON p.id = rm.person_id
     ORDER BY rm.created_at DESC
     LIMIT 100
"""
