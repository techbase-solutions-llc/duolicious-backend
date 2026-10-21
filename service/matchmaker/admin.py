"""Admin > Growth's Alerts, Introductions and Mentors tiles and a member's
Connections (TEC-1845, admin G.2 and 6.1). Counts only: "Nobody, the admin
included, sees who said no." Never a note, a message or a mentor's note.

Refusals kept only so a sender's week counts them (recommendation
flag_reason 'refused', introduction flag_reason 'hidden') are left out of
every count: they are not things anyone did to anyone.
"""
from __future__ import annotations

from typing import Optional

from service.matchmaker import surface_on
from service.matchmaker.criteria import _place_words

_Q_COUNTS = """
    SELECT
      (SELECT count(*) FROM match_alert WHERE person_id IS NOT NULL AND active) AS member_on,
      (SELECT count(*) FROM match_alert WHERE lead_id IS NOT NULL AND confirmed_at IS NOT NULL) AS visitor_confirmed,
      (SELECT count(*) FROM match_alert_notice) AS notices_sent,
      (SELECT count(*) FROM (
          SELECT id FROM person WHERE lead_source = 'alert:visitor'
          UNION
          SELECT person_id FROM lead WHERE source = 'alert:visitor' AND person_id IS NOT NULL) s) AS visitor_signups,
      (SELECT count(*) FROM recommendation WHERE status = 'sent') AS recommendations_sent,
      (SELECT count(DISTINCT joined_person_id) FROM recommendation WHERE joined_person_id IS NOT NULL) AS singles_joined,
      (SELECT count(*) FROM introduction WHERE flag_reason IS DISTINCT FROM 'hidden') AS suggestions_made,
      (SELECT count(*) FROM introduction WHERE status = 'matched') AS accepted_by_both,
      (SELECT count(*) FROM introduction i WHERE i.status = 'matched'
          AND EXISTS (SELECT 1 FROM messaged m WHERE m.subject_person_id = i.a_person_id
                        AND m.object_person_id = i.b_person_id)
          AND EXISTS (SELECT 1 FROM messaged m WHERE m.subject_person_id = i.b_person_id
                        AND m.object_person_id = i.a_person_id)) AS conversations_followed,
      (SELECT count(*) FROM mentor_link) AS invited,
      (SELECT count(*) FROM mentor_link WHERE confirmed_at IS NOT NULL) AS confirmed,
      (SELECT count(DISTINCT a.id) FROM mentor_account a JOIN mentor_link l ON l.mentor_account_id = a.id
        WHERE l.revoked_at IS NULL AND l.confirmed_at IS NOT NULL
          AND a.last_seen_at > NOW() - interval '30 days') AS active,
      (SELECT count(*) FROM mentor_link WHERE confirmed_at IS NOT NULL AND revoked_at IS NOT NULL) AS removed,
      (SELECT count(*) FROM person WHERE no_mentor_shared_matches) AS chose_not_to_match
"""


def mask_email(address: str | None) -> str | None:
    """A mentor's address as staff see it: the first letter of each part and
    the ending, as r••••@g••••.com (export decision 6). The full address
    never leaves the API (review, 21 Oct)."""
    if not address or '@' not in address:
        return None if not address else address[:1] + '••••'
    local, domain = address.split('@', 1)
    name, dot, tld = domain.rpartition('.')
    if not dot:
        name, tld = domain, ''
    return f"{local[:1]}••••@{name[:1]}••••{'.' + tld if tld else ''}"


def counts(tx) -> dict:
    r = {k: int(v) for k, v in tx.execute(_Q_COUNTS).fetchone().items()}
    return dict(
        alerts={k: r[k] for k in ('member_on', 'visitor_confirmed', 'notices_sent', 'visitor_signups')},
        introductions={k: r[k] for k in ('recommendations_sent', 'singles_joined', 'suggestions_made',
                                         'accepted_by_both', 'conversations_followed')},
        mentors={k: r[k] for k in ('invited', 'confirmed', 'active', 'removed', 'chose_not_to_match')},
        live=dict(alerts=surface_on('matchmaker_alerts'),
                  introductions=surface_on('matchmaker_introductions'),
                  mentors=surface_on('matchmaker_mentors')),
    )


def criteria_line(c: dict) -> str:
    """6.1's "Age 26 to 34, anywhere, any relocation"."""
    relocations = c.get('relocations') or []
    if not relocations:
        moving = 'any relocation'
    elif len(relocations) == 1:
        moving = '1 relocation choice'  # NEW LINE
    else:
        moving = f'{len(relocations)} relocation choices'  # NEW LINE
    return f"Age {c['age_min']} to {c['age_max']}, {_place_words(c)}, {moving}"


def connections(tx, person_id: int) -> dict:
    """6.1's three groups, as counts."""
    a = tx.execute(
        """SELECT a.active, a.criteria,
                  (SELECT max(n.created_at) FROM match_alert_notice n WHERE n.alert_id = a.id) AS last_notice_at
             FROM match_alert a WHERE a.person_id = %(p)s""", dict(p=person_id)).fetchone()
    alert: Optional[dict] = None
    if a is not None:
        alert = dict(on=bool(a['active']), criteria_line=criteria_line(a['criteria']),
                     last_notice_at=a['last_notice_at'].isoformat() if a['last_notice_at'] else None)
    i = tx.execute(
        """SELECT
             count(*) FILTER (WHERE introducer_person_id = %(p)s) AS made,
             count(*) FILTER (WHERE introducer_person_id = %(p)s AND status = 'matched') AS accepted_by_both,
             count(*) FILTER (WHERE introducer_person_id = %(p)s AND status = 'closed') AS not_taken_further,
             count(*) FILTER (WHERE %(p)s IN (a_person_id, b_person_id)
                                AND status IN ('open', 'matched', 'closed')) AS received
             FROM introduction
            WHERE flag_reason IS DISTINCT FROM 'hidden'
              AND (introducer_person_id = %(p)s OR %(p)s IN (a_person_id, b_person_id))""",
        dict(p=person_id)).fetchone()
    m = tx.execute(
        """SELECT l.confirmed_at, l.mentor_email,
                  (SELECT count(*) FROM shared_conversation s WHERE s.mentor_link_id = l.id
                     AND s.revoked_at IS NULL) AS shared
             FROM mentor_link l
            WHERE l.single_person_id = %(p)s AND l.revoked_at IS NULL AND l.confirmed_at IS NOT NULL""",
        dict(p=person_id)).fetchone()
    mentor = None
    if m is not None:
        mentor = dict(since=m['confirmed_at'].date().isoformat(), email=mask_email(m['mentor_email']),
                      conversations_shared=int(m['shared']))
    return dict(alert=alert, introductions={k: int(i[k]) for k in i.keys()}, mentor=mentor)
