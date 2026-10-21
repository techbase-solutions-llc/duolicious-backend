"""Alerts: "Tell me when someone who fits joins" (TEC-1845).

A member's alert (1.1 to 1.10) is on as soon as it is saved: their address
is proved. A visitor's (3.1 to 3.9) is a lead with source alert:visitor and
waits for the link in its confirm email. Either names nobody: what is kept
is what they are looking for and when we last told them.

The stop token in "Stop these emails" is derived from the alert's id with
the unsubscribe secret, so every notice can carry the same link while only
its hash is stored. A member's link turns the alert's email off; a
visitor's deletes the alert.

Every function takes the caller's transaction.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from service.matchmaker import MatchmakerError
from service.matchmaker.criteria import clean_member_criteria, summary_line

CONFIRM_WINDOW = timedelta(days=7)
MAX_RESENDS = 3


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def stop_token(alert_id: int) -> str:
    """The alert's stop token: 32 URL-safe characters, the same every time."""
    from service.unsubscribe import _secret
    mac = hmac.new(_secret(), f'mm-stop|{alert_id}'.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode()[:32]


def _hash(token: str) -> str:
    from service.leads import token_hash
    return token_hash(token)


# ---------------------------------------------------------------------------
# A member's alert
# ---------------------------------------------------------------------------

def _member_row(tx, person_id: int) -> Optional[dict]:
    row = tx.execute('SELECT * FROM match_alert WHERE person_id = %(p)s', dict(p=person_id)).fetchone()
    return dict(row) if row else None


def _view(row: dict) -> dict:
    return dict(criteria=row['criteria'], notify_push=row['notify_push'],
                notify_email=row['notify_email'], state='on' if row['active'] else 'paused',
                summary=summary_line(row['criteria']))


def member_alert(tx, person_id: int) -> dict:
    """{alert, defaults}: the alert as the sheet shows it, or None, and the
    age band to fill a new one with (1.1: "filled from the member's current
    filters and saved age band"; the web adds the filters it holds)."""
    from service.search import AGE_CEILING, AGE_FLOOR, saved_age_band
    row = _member_row(tx, person_id)
    lo, hi = saved_age_band(tx, person_id)
    return dict(alert=_view(row) if row else None,
                defaults=dict(age_min=lo if lo is not None else AGE_FLOOR,
                              age_max=hi if hi is not None else AGE_CEILING))


def save_member_alert(tx, person_id: int, raw: dict, *, notify_push: bool,
                      notify_email: bool) -> dict:
    """Create or replace the member's alert, on at once. A saved change
    keeps its count window, so nobody is counted twice."""
    criteria = clean_member_criteria(raw)
    row = tx.execute(
        """INSERT INTO match_alert (person_id, criteria, notify_push, notify_email, active,
                                    confirmed_at)
           VALUES (%(p)s, %(c)s::jsonb, %(push)s, %(email)s, TRUE, NOW())
           ON CONFLICT (person_id) WHERE person_id IS NOT NULL DO UPDATE SET
               criteria = EXCLUDED.criteria, notify_push = EXCLUDED.notify_push,
               notify_email = EXCLUDED.notify_email, active = TRUE, paused_at = NULL,
               updated_at = NOW()
           RETURNING id, stop_token_hash""",
        dict(p=person_id, c=json.dumps(criteria), push=bool(notify_push),
             email=bool(notify_email))).fetchone()
    if row['stop_token_hash'] is None:
        tx.execute('UPDATE match_alert SET stop_token_hash = %(h)s WHERE id = %(i)s',
                   dict(h=_hash(stop_token(row['id'])), i=row['id']))
    return member_alert(tx, person_id)


def _set_active(tx, person_id: int, active: bool) -> dict:
    row = tx.execute(
        """UPDATE match_alert SET active = %(a)s,
                  paused_at = CASE WHEN %(a)s THEN NULL ELSE COALESCE(paused_at, NOW()) END,
                  updated_at = NOW()
            WHERE person_id = %(p)s RETURNING id""",
        dict(a=active, p=person_id)).fetchone()
    if row is None:
        raise MatchmakerError('no_alert', 404)
    return member_alert(tx, person_id)


def pause(tx, person_id: int) -> dict:
    """1.10: "Paused. What you are looking for is kept.\""""
    return _set_active(tx, person_id, False)


def resume(tx, person_id: int) -> dict:
    return _set_active(tx, person_id, True)


def delete_member_alert(tx, person_id: int) -> dict:
    tx.execute('DELETE FROM match_alert WHERE person_id = %(p)s', dict(p=person_id))
    return member_alert(tx, person_id)


# ---------------------------------------------------------------------------
# A visitor's alert (3.1 to 3.9): a lead with source alert:visitor
# ---------------------------------------------------------------------------

def _queue_confirm(tx, alert_id: int, lead_id: int, email: str, criteria: dict,
                   first_name: Optional[str], resends: int, token: str) -> Optional[int]:
    from service.campaigns import outbox
    from service.matchmaker import mail
    from service.matchmaker.criteria import visitor_words
    if not mail.campaign_on(mail.CAMPAIGN_VISITOR_CONFIRM):
        return None

    def go():
        subject, body = mail.visitor_confirm_email(visitor_words(criteria), mail.confirm_url(token),
                                                   first_name)
        return outbox.enqueue_for_lead(
            tx, campaign=mail.CAMPAIGN_VISITOR_CONFIRM, campaign_id=f'{alert_id}:{resends}',
            lead_id=lead_id, email=email, subject=subject, html=body, from_addr=mail.FROM_ADDR,
            list_unsubscribe=None, marketing=False)
    return mail.guarded(tx, 'mm_visitor_confirm', go)


def ask(tx, *, email: str, criteria: dict, first_name: Optional[str],
        now: Optional[datetime] = None) -> dict:
    """The landing's form (3.1). Answers {state: 'check_email', email} for a
    new or unconfirmed alert, {state: 'already_on', email} once it is on (the
    new criteria replace the old, 3.5). Asking again while unconfirmed is
    "Send it again": a fresh link, at most MAX_RESENDS more times (3.9). An
    address that belongs to a member writes nothing and answers the same:
    members set alerts in the app."""
    from service.leads import clean_email, new_token, record_lead
    from service.leads.sources import ALERT_VISITOR
    from service.matchmaker.criteria import clean_visitor_criteria
    now = _now(now)
    cleaned = clean_email(email)
    if cleaned is None:
        raise MatchmakerError('bad_email', 400)
    address = cleaned[0]
    c = clean_visitor_criteria(criteria)
    answer = dict(state='check_email', email=address)
    lead_id = record_lead(tx, email=address, source=ALERT_VISITOR)
    if lead_id is None:
        return answer
    row = tx.execute('SELECT * FROM match_alert WHERE lead_id = %(l)s FOR UPDATE',
                     dict(l=lead_id)).fetchone()
    if row is not None and row['confirmed_at'] is not None:
        tx.execute("""UPDATE match_alert SET criteria = %(c)s::jsonb,
                             first_name = COALESCE(%(f)s, first_name), active = TRUE,
                             updated_at = NOW()
                       WHERE id = %(i)s""",
                   dict(c=json.dumps(c), f=first_name, i=row['id']))
        return dict(state='already_on', email=address)
    if row is not None and row['resends'] >= MAX_RESENDS:
        raise MatchmakerError('too_many_tries', 429)
    token, hashed = new_token()
    if row is None:
        row = tx.execute(
            """INSERT INTO match_alert (lead_id, first_name, criteria, notify_push, notify_email,
                                        confirm_token_hash, confirm_by)
               VALUES (%(l)s, %(f)s, %(c)s::jsonb, FALSE, TRUE, %(h)s, %(by)s)
               RETURNING id, resends""",
            dict(l=lead_id, f=first_name, c=json.dumps(c), h=hashed,
                 by=now + CONFIRM_WINDOW)).fetchone()
    else:
        row = tx.execute(
            """UPDATE match_alert SET criteria = %(c)s::jsonb, first_name = %(f)s,
                      confirm_token_hash = %(h)s, confirm_by = %(by)s, resends = resends + 1,
                      updated_at = NOW()
                WHERE id = %(i)s RETURNING id, resends""",
            dict(c=json.dumps(c), f=first_name, h=hashed, by=now + CONFIRM_WINDOW,
                 i=row['id'])).fetchone()
    _queue_confirm(tx, row['id'], lead_id, address, c, first_name, row['resends'], token)
    return answer


def confirm(tx, token: str, now: Optional[datetime] = None) -> dict:
    """The confirm page's call (3.6, 3.7): {state: 'confirmed' | 'already_on',
    stop_token}. A link past its 7 days answers 410 expired. Counting starts
    when the alert is turned on."""
    from service.leads import confirm_lead
    now = _now(now)
    if not isinstance(token, str) or not token:
        raise MatchmakerError('not_found', 404)
    row = tx.execute('SELECT * FROM match_alert WHERE confirm_token_hash = %(h)s FOR UPDATE',
                     dict(h=_hash(token))).fetchone()
    if row is None or row['lead_id'] is None:
        raise MatchmakerError('not_found', 404)
    stop = stop_token(row['id'])
    if row['confirmed_at'] is not None:
        return dict(state='already_on', stop_token=stop)
    if row['confirm_by'] is not None and row['confirm_by'] < now:
        raise MatchmakerError('expired', 410)
    tx.execute("""UPDATE match_alert SET confirmed_at = NOW(), counted_since = NOW(),
                         stop_token_hash = %(s)s, updated_at = NOW()
                   WHERE id = %(i)s""", dict(s=_hash(stop), i=row['id']))
    confirm_lead(tx, row['lead_id'], 'link')
    return dict(state='confirmed', stop_token=stop)


def stop(tx, token: str) -> dict:
    """The "Stop these emails" link. A visitor's alert is deleted at once; a
    member's turns its email off and keeps the rest. An unknown token
    answers the same, so the link says nothing about who has an alert."""
    if isinstance(token, str) and token:
        row = tx.execute('SELECT id, person_id FROM match_alert WHERE stop_token_hash = %(h)s',
                         dict(h=_hash(token))).fetchone()
        if row is not None and row['person_id'] is None:
            tx.execute('DELETE FROM match_alert WHERE id = %(i)s', dict(i=row['id']))
        elif row is not None:
            tx.execute('UPDATE match_alert SET notify_email = FALSE, updated_at = NOW() '
                       'WHERE id = %(i)s', dict(i=row['id']))
    return dict(state='stopped')


def adopt_visitor_alert(tx, person_id: int) -> None:
    """At finish-onboarding, after link_leads_to_person: a confirmed visitor
    alert of a lead now linked to this member becomes the member's alert,
    with push off and email on, unless they already have one. Behind a
    savepoint: it never undoes the sign-up."""
    tx.execute('SAVEPOINT mm_adopt_alert')
    try:
        row = tx.execute(
            """SELECT a.id, a.criteria FROM match_alert a JOIN lead l ON l.id = a.lead_id
                WHERE l.person_id = %(p)s AND a.confirmed_at IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM match_alert m WHERE m.person_id = %(p)s)
                ORDER BY a.created_at DESC LIMIT 1""", dict(p=person_id)).fetchone()
        if row is not None:
            v = row['criteria']
            region = v.get('region')
            c = clean_member_criteria(dict(age_min=v['age_min'], age_max=v['age_max']))
            c['regions'] = [region] if region else []
            tx.execute(
                """UPDATE match_alert SET person_id = %(p)s, lead_id = NULL, criteria = %(c)s::jsonb,
                          notify_push = FALSE, notify_email = TRUE, active = TRUE,
                          confirm_token_hash = NULL, updated_at = NOW()
                    WHERE id = %(i)s""",
                dict(p=person_id, c=json.dumps(c), i=row['id']))
    except Exception:
        import traceback
        print(traceback.format_exc())
        tx.execute('ROLLBACK TO SAVEPOINT mm_adopt_alert')
    else:
        tx.execute('RELEASE SAVEPOINT mm_adopt_alert')
