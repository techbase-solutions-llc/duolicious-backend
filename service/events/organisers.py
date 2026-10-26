"""Organisers (TEC-1845): the request to host, the magic link and Ahavah's
own organiser.

An organiser is not an account. They prove who they are once with a
sign-in code (the request to host) or an admin creates them (Ahavah's
own), and from then on with a magic link: a 32 character token, sent as
X-Organiser-Token, stored only as its sha256, valid LINK_TTL. Approval is
once, by an admin; a revoked organiser's links stop working.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from service.events import EventError
from service.leads import clean_email, new_token, token_hash

LINK_TTL = timedelta(days=7)
PUBLIC_KINDS = ('assembly', 'fellowship_leader', 'ministry', 'other')
_TOKEN_MIN, _TOKEN_MAX = 16, 64


def issue_link(tx, organiser_id: int) -> str:
    """A new magic link token for this organiser. Earlier links keep
    working until they lapse."""
    token, hashed = new_token()
    tx.execute(
        """INSERT INTO organiser_link (organiser_id, token_hash, expires_at)
           VALUES (%(o)s, %(h)s, NOW() + %(ttl)s)""",
        dict(o=organiser_id, h=hashed, ttl=LINK_TTL))
    return token


_Q_ORGANISER_FOR = """
    SELECT o.id, o.name, o.kind, o.email, o.normalized_email, o.city, o.country,
           o.about, o.approved_at, o.approved_at IS NOT NULL AS approved, o.member_person_id
      FROM organiser_link l
      JOIN organiser o ON o.id = l.organiser_id
     WHERE l.token_hash = %(h)s
       AND l.expires_at > NOW()
       AND o.revoked_at IS NULL
"""


def organiser_for(tx, token: Optional[str]) -> dict:
    """The organiser a magic link names. A missing, unknown, lapsed or
    revoked token raises expired (401), export 4.9."""
    if not isinstance(token, str) or not _TOKEN_MIN <= len(token) <= _TOKEN_MAX:
        raise EventError('expired', 401)
    row = tx.execute(_Q_ORGANISER_FOR, dict(h=token_hash(token))).fetchone()
    if row is None:
        raise EventError('expired', 401)
    return dict(row)


def kit_on(organiser: dict) -> bool:
    """Whether the organiser share kit is offered to this organiser (round 2,
    screens 9 and 10): hosting and app_entries, which an organiser passes
    through the member who made it or through its address, as a member
    would (ahavah-web docs/plans/2026-10-22-in-app-entry-and-sign-up.md,
    section 7, the kit's switches). The images themselves follow events_live."""
    from service.app_entries import enabled_for
    from service.events import live, surface_on
    return (live() and surface_on('events_hosting')
            and enabled_for(organiser.get('member_person_id'), organiser.get('email')))


def me(organiser: dict) -> dict:
    return dict(name=organiser['name'], kind=organiser['kind'],
                approved=bool(organiser['approved']), email=organiser['email'])


def request_host(tx, *, email: str, name: str, kind: str, city: Optional[str],
                 country: Optional[str], about: Optional[str],
                 member_person_id: Optional[int] = None) -> dict:
    """The request to host, from a session whose address a sign-in code has
    just proved, or a member's own (release 3, hosting from the app).
    {state, token}: 'created' (new, verified now, waiting for approval),
    'pending' (already waiting, export 4.5) or 'approved'. The token is a
    fresh link in every state. `member_person_id` names the member who asked
    (migration 0080); an organiser that already names one keeps it."""
    if kind not in PUBLIC_KINDS:
        raise EventError('bad_kind', 400)
    cleaned = clean_email(email)
    if cleaned is None:
        raise EventError('bad_email', 400)
    address, normalised = cleaned
    row = tx.execute(
        """SELECT id, approved_at, revoked_at FROM organiser
            WHERE normalized_email = %(ne)s FOR UPDATE""",
        dict(ne=normalised)).fetchone()
    if row is not None:
        if row['revoked_at'] is not None:
            raise EventError('revoked', 403)
        state = 'approved' if row['approved_at'] is not None else 'pending'
        if member_person_id is not None:
            tx.execute(
                """UPDATE organiser SET member_person_id = COALESCE(member_person_id, %(m)s)
                    WHERE id = %(i)s""", dict(m=member_person_id, i=row['id']))
        return dict(state=state, token=issue_link(tx, row['id']))
    oid = tx.execute(
        """INSERT INTO organiser (name, kind, email, normalized_email, city, country,
                                  about, verified_at, member_person_id)
           VALUES (%(n)s, %(k)s, %(e)s, %(ne)s, %(c)s, %(co)s, %(a)s, NOW(), %(m)s)
           RETURNING id""",
        dict(n=name, k=kind, e=address, ne=normalised, c=city, co=country, a=about,
             m=member_person_id),
    ).fetchone()['id']
    return dict(state='created', token=issue_link(tx, oid))


_Q_MEMBER_ORGANISERS = """
    SELECT o.id, o.name, o.kind, o.email, o.normalized_email, o.city, o.country,
           o.about, o.approved_at, o.approved_at IS NOT NULL AS approved, o.member_person_id
      FROM organiser o
     WHERE o.revoked_at IS NULL
       AND (o.normalized_email = %(ne)s OR o.member_person_id = %(p)s)
     ORDER BY o.approved_at IS NULL, o.id
"""


def member_organisers(tx, person_id: int, email: str) -> list[dict]:
    """The organisers a member's session opens (release 3, hosting from the
    app): the one under the member's own address and any the member made
    under another, approved ones first. A revoked one opens nothing."""
    cleaned = clean_email(email)
    normalised = cleaned[1] if cleaned else None
    return [dict(r) for r in tx.execute(_Q_MEMBER_ORGANISERS, dict(ne=normalised, p=person_id)).fetchall()]


def send_new_link(tx, email: str) -> None:
    """"Send me a new link" (export 4.9): a fresh link by email for a
    non-revoked organiser with this address; nothing otherwise. The caller
    answers the same either way."""
    from service.events import mail
    cleaned = clean_email(email)
    if cleaned is None:
        return
    row = tx.execute(
        """SELECT id FROM organiser
            WHERE normalized_email = %(ne)s AND revoked_at IS NULL""",
        dict(ne=cleaned[1])).fetchone()
    if row is None:
        return
    mail.queue_manage_link(tx, row['id'], issue_link(tx, row['id']))


def create_organiser(tx, *, name: str, email: str, kind: str, admin_person_id: int) -> dict:
    """An organiser an admin adds (Ahavah's own, kind 'ahavah'): verified
    and approved now. An address that already hosts is approved and keeps
    its row."""
    from service.events.fields import KINDS
    if kind not in KINDS:
        raise EventError('bad_kind', 400)
    cleaned = clean_email(email)
    if cleaned is None:
        raise EventError('bad_email', 400)
    address, normalised = cleaned
    row = tx.execute(
        """INSERT INTO organiser (name, kind, email, normalized_email, verified_at,
                                  approved_at, approved_by)
           VALUES (%(n)s, %(k)s, %(e)s, %(ne)s, NOW(), NOW(), %(a)s)
           ON CONFLICT (normalized_email) DO UPDATE SET
               name = EXCLUDED.name, kind = EXCLUDED.kind,
               verified_at = COALESCE(organiser.verified_at, NOW()),
               approved_at = COALESCE(organiser.approved_at, NOW()),
               approved_by = COALESCE(organiser.approved_by, EXCLUDED.approved_by),
               revoked_at = NULL
           RETURNING id, name, kind, email""",
        dict(n=name, k=kind, e=address, ne=normalised, a=admin_person_id)).fetchone()
    return dict(row)
