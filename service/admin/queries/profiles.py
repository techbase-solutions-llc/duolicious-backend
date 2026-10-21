"""Verification tiers, profile gaps, the photo gate list and approved photos
with no face (TEC-1897; frames G.1, P.1, P.2 and P.3).

CONTENT IS NEVER READ: the gate list counts a member's sent messages from
mam_message's id, direction and person only.
"""
from __future__ import annotations

from service.admin.queries.members import counted_member_sql, member_sql

TIERS = ('none', 'bronze', 'silver', 'gold')

Q_VERIFICATION_TIERS = f"""
    SELECT t.tier, count(p.id)::int AS members
      FROM unnest(ARRAY['none', 'bronze', 'silver', 'gold']) WITH ORDINALITY AS t(tier, ord)
      LEFT JOIN person p
        ON p.ahavah_verification_tier::text = t.tier AND {counted_member_sql('p')}
     GROUP BY t.tier, t.ord
     ORDER BY t.ord
"""


# One row per counted member with their photo tallies. can_view_photos() is
# the photo gate's own rule: an approved photo showing a face.
_MEMBER_PHOTOS = f"""
    SELECT p.id, p.uuid::text AS uuid, p.name, p.ahavah_verification_tier::text AS tier,
           count(ph.uuid) AS photos,
           count(ph.uuid) FILTER (WHERE ph.moderation_status::text = 'approved') AS approved,
           count(ph.uuid) FILTER (WHERE ph.moderation_status::text = 'rejected') AS rejected,
           can_view_photos(p.id) AS has_face_photo
      FROM person p
      LEFT JOIN photo ph ON ph.person_id = p.id
     WHERE {counted_member_sql('p')}
     GROUP BY p.id
"""

_GAP = """
    CASE WHEN photos = 0 THEN 'no_photo'
         WHEN rejected = photos THEN 'only_declined'
         WHEN approved = 0 THEN 'only_pending'
         WHEN NOT has_face_photo THEN 'no_face'
    END
"""

Q_PROFILE_GAP_KPIS = f"""
    WITH m AS ({_MEMBER_PHOTOS})
    SELECT count(*) FILTER (WHERE tier = 'none')::int                     AS not_verified,
           count(*) FILTER (WHERE photos > 0 AND rejected = photos)::int  AS only_declined,
           count(*) FILTER (WHERE photos = 0)::int                        AS no_photo,
           count(*) FILTER (WHERE NOT has_face_photo)::int                AS no_face_photo
      FROM m
"""

Q_PROFILE_GAPS = f"""
    WITH m AS ({_MEMBER_PHOTOS})
    SELECT uuid, name, tier, gap
      FROM (SELECT m.*, {_GAP} AS gap FROM m) g
     WHERE gap IS NOT NULL
     ORDER BY array_position(ARRAY['no_photo', 'only_declined', 'only_pending', 'no_face'], gap), name
     LIMIT 500
"""

# The people Q_PHOTO_GATE_KPIS counts (members, activated), so the Needs you
# tile and this list agree. Activity over the last 30 days. Messages are
# counted from mam_message's id, direction and person only.
Q_PHOTO_GATE_MEMBERS = f"""
    SELECT p.uuid::text AS uuid, p.name, p.last_online_time AS last_online_at,
           (SELECT count(*) FROM liked l
             WHERE l.liker_id = p.id AND l.created_at > NOW() - INTERVAL '30 days')::int AS likes_sent_30d,
           (SELECT count(*) FROM liked l
             WHERE l.liked_id = p.id AND l.created_at > NOW() - INTERVAL '30 days')::int AS likes_received_30d,
           (SELECT count(*) FROM ahavah_match am
             WHERE p.id IN (am.user_a_id, am.user_b_id)
               AND am.created_at > NOW() - INTERVAL '30 days')::int AS matches_30d,
           (SELECT count(*) FROM mam_message mm
             WHERE mm.person_id = p.id AND mm.direction = 'O'
               AND to_timestamp(mm.id / 1000000 / 256) > NOW() - INTERVAL '30 days')::int AS messages_30d,
           (SELECT count(*) FROM visited v
             WHERE v.object_person_id = p.id AND v.subject_person_id <> p.id
               AND v.updated_at > NOW() - INTERVAL '30 days')::int AS profile_views_30d,
           w.uuid IS NOT NULL AS has_waiting_photo,
           w.uuid AS waiting_photo_uuid,
           w.uploaded_at AS photo_waiting_since
      FROM person p
      LEFT JOIN LATERAL (
          SELECT ph.uuid, ph.uploaded_at FROM photo ph
           WHERE ph.person_id = p.id AND ph.moderation_status::text IN ('pending', 'manual_review')
           ORDER BY ph.uploaded_at NULLS FIRST, ph.position
           LIMIT 1) w ON TRUE
     WHERE {member_sql('p')} AND p.activated AND NOT can_view_photos(p.id)
     ORDER BY p.last_online_time DESC
     LIMIT 200
"""
