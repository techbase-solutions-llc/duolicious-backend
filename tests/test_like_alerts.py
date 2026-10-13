"""Like alerts (health review, 13 Oct 2026, findings 32 and 58).

The push banner, E3 and E6 promise "hear when someone likes you", but
turning push on never turned like alerts on: `push_likes` defaults to off
and only the settings switch changed it, so 0 of 58 members had it.

Now:
  1. Subscribing a device turns like push on, unless the member has chosen
     about likes. A choice is a PATCH that carried `push_likes`, recorded in
     `notification_preference.push_likes_chosen_at` (migration 0057); a row
     saved for some other switch is not a choice about likes.
  2. scripts/backfill_like_alerts.py does the same for people who already
     hold a subscription.
  3. A like notification opens Liked you (/matches?tab=likes), push and email.
"""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import pytest

from database import api_tx


def _session(person: dict) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%s, %s, %s, TRUE, '123456')""",
            (hashlib.sha512(tok.encode()).hexdigest(),
             f'like-alerts-{person["id"]}@example.com', person['id']))
    return {'Authorization': f'Bearer {tok}'}


def _subscribe(client, headers) -> None:
    r = client.post('/notifications/subscribe', headers=headers, json=dict(
        endpoint=f'https://push.example.com/{uuid4()}',
        keys=dict(p256dh='p256dh-key', auth='auth-key')))
    assert r.status_code == 200, r.get_data(as_text=True)


def _prefs(client, headers) -> dict:
    r = client.get('/notifications/preferences', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _row(person_id: int):
    with api_tx() as tx:
        return tx.execute(
            "SELECT * FROM notification_preference WHERE person_id = %(p)s",
            dict(p=person_id)).fetchone()


_DEFAULTS = dict(
    push_matches=True, email_matches=True, push_messages=True, email_messages=True,
    push_likes=False, email_likes=False, push_verification=True, email_verification=True,
    push_profile_views=False, email_profile_views=False, push_weekly_digest=False)


# --- 1. Subscribing ---------------------------------------------------------

def test_subscribing_turns_like_push_on_for_a_member_who_never_chose(client, make_person):
    p = make_person(name='NeverChose')
    h = _session(p)
    assert _prefs(client, h)['push_likes'] is False

    _subscribe(client, h)

    assert _prefs(client, h) == dict(_DEFAULTS, push_likes=True)
    # Turned on by default, not by the member: a later subscribe may still
    # act on it, and the backfill treats it the same way.
    assert _row(p['id'])['push_likes_chosen_at'] is None


def test_subscribing_keeps_a_member_who_said_no(client, make_person):
    p = make_person(name='SaidNo')
    h = _session(p)
    assert client.patch('/notifications/preferences', headers=h,
                        json=dict(push_likes=False)).status_code == 204

    _subscribe(client, h)

    assert _prefs(client, h)['push_likes'] is False
    assert _row(p['id'])['push_likes_chosen_at'] is not None


def test_a_saved_choice_about_another_switch_is_not_a_choice_about_likes(client, make_person):
    p = make_person(name='OtherSwitch')
    h = _session(p)
    assert client.patch('/notifications/preferences', headers=h,
                        json=dict(email_likes=True)).status_code == 204
    assert _row(p['id'])['push_likes_chosen_at'] is None

    _subscribe(client, h)

    assert _prefs(client, h) == dict(_DEFAULTS, push_likes=True, email_likes=True)


def test_a_member_who_said_no_after_yes_is_kept(client, make_person):
    p = make_person(name='YesThenNo')
    h = _session(p)
    _subscribe(client, h)
    assert client.patch('/notifications/preferences', headers=h,
                        json=dict(push_likes=False)).status_code == 204

    # A second device, or the resync of the same one.
    _subscribe(client, h)

    assert _prefs(client, h)['push_likes'] is False


# --- 2. The backfill --------------------------------------------------------

def _hold_subscription(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
               VALUES (%(p)s, %(e)s, 'k', 'a')""",
            dict(p=person_id, e=f'https://push.example.com/{uuid4()}'))


def test_the_backfill_turns_like_push_on_for_subscribers_who_never_chose(make_person):
    from scripts.backfill_like_alerts import backfill

    no_row = make_person(name='SubNoRow')
    other_switch = make_person(name='SubOtherSwitch')
    said_no = make_person(name='SubSaidNo')
    no_device = make_person(name='NoDevice')
    for p in (no_row, other_switch, said_no):
        _hold_subscription(p['id'])
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO notification_preference (person_id, email_likes)
               VALUES (%(p)s, TRUE)""", dict(p=other_switch['id']))
        tx.execute(
            """INSERT INTO notification_preference (person_id, push_likes, push_likes_chosen_at)
               VALUES (%(p)s, FALSE, NOW())""", dict(p=said_no['id']))

    with api_tx() as tx:
        dry = backfill(tx, dry_run=True)
    # The shared test database may hold other subscribers; ours are 2.
    assert dry['would_turn_on'] >= 2
    assert _row(no_row['id']) is None, 'a dry run writes nothing'
    assert _row(other_switch['id'])['push_likes'] is False

    with api_tx() as tx:
        done = backfill(tx)
    assert done['turned_on'] >= 2
    assert _row(no_row['id'])['push_likes'] is True
    assert _row(no_row['id'])['push_likes_chosen_at'] is None
    assert _row(other_switch['id'])['push_likes'] is True
    assert _row(other_switch['id'])['email_likes'] is True
    assert _row(said_no['id'])['push_likes'] is False
    assert _row(no_device['id']) is None, 'no subscription, nothing to turn on'

    with api_tx() as tx:
        again = backfill(tx)
    assert again['turned_on'] == 0


# --- 3. Where a like notification opens ------------------------------------

def test_a_like_push_opens_liked_you(client, make_person, monkeypatch):
    import service.notifications as notifications

    liker = make_person(name='Liker', gender='Man')
    liked = make_person(name='Liked', gender='Woman')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = ANY(%(ids)s)",
                   dict(ids=[liker['id'], liked['id']]))
    calls = []
    monkeypatch.setattr(notifications, 'notify',
                        lambda person_id, kind, **kw: calls.append((person_id, kind, kw)))

    r = client.post('/decisions', headers=_session(liker),
                    json=dict(profile_uuid=liked['uuid'], decision='like'))
    assert r.status_code == 200, r.get_data(as_text=True)

    assert [(c[0], c[1]) for c in calls] == [(liked['id'], 'like')]
    assert calls[0][2]['url'] == '/matches?tab=likes'


def test_the_like_email_opens_liked_you():
    from emails.notification import new_like_email
    from service.config import WEB_BASE_URL

    html = new_like_email('https://example.com/u/token')
    assert f'{WEB_BASE_URL}/matches?tab=likes' in html
