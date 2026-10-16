"""Spotlight eligibility (spec 3.2): one SQL statement, first failing reason wins.

Staff accounts are never featured (health review, 13 Oct 2026, finding 88):
the only member card ever published was a welcome for an admin-role
account. `staff` is the member predicate of service/admin/queries/members.py
read the other way round, so every caller (the candidate list, the
suggestions, card creation, the publish-time check and the roundup) leaves
them out with no rule of its own."""
from __future__ import annotations
from typing import Optional
from service.admin.queries.members import member_sql
from service.config import USER_IMAGES_BASE_URL

REASONS = ('not_activated', 'staff', 'not_opted_in', 'not_verified', 'under_18', 'reported',
           'pending_deletion', 'featured_recently', 'no_photo', 'photo_missing')

def _columns(a: str, xrk: str) -> dict[str, str]:
    """Each rule as a SQL boolean on the person aliased `a`. `xrk` is the
    request key a card being re-checked may ignore its own occurrence for
    (a bind, or NULL for none). Written once, so the per-member check below
    and `featurable_sql` cannot drift apart."""
    return {
        'activated': f"{a}.activated",
        'staff': f"NOT ({member_sql(a)})",
        'spotlight_opt_in': f"{a}.spotlight_opt_in",
        'verified': (f"({a}.ahavah_verification_tier IS NOT NULL"
                     f" AND {a}.ahavah_verification_tier::text <> 'none')"),
        'adult': (f"({a}.date_of_birth IS NOT NULL"
                  f" AND {a}.date_of_birth <= (NOW() - interval '18 years')::date)"),
        'reported': f"EXISTS (SELECT 1 FROM skipped s WHERE s.object_person_id = {a}.id AND s.reported = TRUE)",
        'pending_deletion': f"({a}.deletion_requested_at IS NOT NULL)",
        'featured_recently': (f"EXISTS (SELECT 1 FROM spotlight_occurrence o WHERE o.person_id = {a}.id"
                              f" AND o.created_at > NOW() - interval '30 days'"
                              f" AND ({xrk}::text IS NULL OR o.request_key <> {xrk}::text))"),
        'has_photo': (f"EXISTS (SELECT 1 FROM photo ph WHERE ph.person_id = {a}.id"
                      f" AND ph.moderation_status = 'approved')"),
    }


# The columns above that are true when the member FAILS the rule.
_TRUE_FAILS = ('staff', 'reported', 'pending_deletion', 'featured_recently')

_Q = ("SELECT " + ",\n           ".join(f"{sql} AS {name}" for name, sql in _columns('p', '%(xrk)s').items())
      + "\n      FROM person p WHERE p.id = %(pid)s")


def featurable_sql(alias: str = 'p') -> str:
    """SQL boolean: the person aliased `alias` passes every rule above except
    consent, so they could be featured if they opted in. For the owner's
    note to the Spotlight candidates (emails/send_spotlight_candidates_note.py).
    A fragment, not a bind: it adds no parameters to the query it joins."""
    return " AND ".join(f"NOT ({sql})" if name in _TRUE_FAILS else f"({sql})"
                        for name, sql in _columns(alias, 'NULL').items()
                        if name != 'spotlight_opt_in')


def eligibility(tx, person_id: int, photo_uuid: Optional[str] = None, *,
                 exclude_request_key: Optional[str] = None) -> tuple[bool, str]:
    r = tx.execute(_Q, dict(pid=person_id, xrk=exclude_request_key)).fetchone()
    if not r:
        return False, 'not_activated'
    if photo_uuid is not None:
        # A specific photo was chosen (the one a rendered card actually
        # shows), so its own presence, ownership and moderation status is
        # what matters here -- a different approved photo on the same
        # person does not save a card whose chosen photo is gone.
        photo_reason = 'photo_missing'
        photo_failed = tx.execute(
            """SELECT 1 FROM photo WHERE uuid::text = %(u)s AND person_id = %(pid)s
                AND moderation_status = 'approved'""",
            dict(u=photo_uuid, pid=person_id)).fetchone() is None
    else:
        photo_reason = 'no_photo'
        photo_failed = not r['has_photo']
    checks = [
        ('not_activated', not r['activated']),
        ('staff', r['staff']),
        ('not_opted_in', not r['spotlight_opt_in']),
        ('not_verified', not r['verified']),
        ('under_18', not r['adult']),
        ('reported', r['reported']),
        ('pending_deletion', r['pending_deletion']),
        ('featured_recently', r['featured_recently']),
        (photo_reason, photo_failed),
    ]
    for reason, failed in checks:
        if failed:
            return False, reason
    return True, ''


def primary_photo_uuid(tx, person_id: int) -> Optional[str]:
    r = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(pid)s AND moderation_status = 'approved' ORDER BY position LIMIT 1", dict(pid=person_id)).fetchone()
    return r['u'] if r else None


def photo_url(uuid: str, size: Optional[int] = None) -> str:
    return f"{USER_IMAGES_BASE_URL}/{size or 'original'}-{uuid}.jpg"
