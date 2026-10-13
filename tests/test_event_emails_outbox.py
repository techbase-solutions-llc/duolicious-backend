"""Like, match and message emails go through the outbox (health review,
13 Oct 2026, finding 63).

notify() and the message cron spoke to SMTP directly, so these emails left
no email_send_log row and nobody could say how many went out or whether
they brought anyone back. They now queue an email_outbox row (campaign
`like`, `match` or `message`) and the drain writes the send log on
acceptance, as every campaign does. The templates are unchanged.

They are not campaign mail: the campaign frequency cap never holds one
back, and one never counts toward the cap a campaign checks.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets

from database import api_tx
from service.campaigns import can_send, count_sendable


def _mailable(make_person, name: str, gender: str = 'Man') -> dict:
    p = make_person(name=name, gender=gender)
    email = f"{name.lower()}-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s, activated = TRUE "
                   "WHERE id = %(i)s", dict(e=email, i=p['id']))
    return dict(p, email=email)


def _session(person: dict) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%s, %s, %s, TRUE, '123456')""",
            (hashlib.sha512(tok.encode()).hexdigest(), person['email'], person['id']))
    return {'Authorization': f'Bearer {tok}'}


def _like(client, liker: dict, liked: dict) -> dict:
    r = client.post('/decisions', headers=_session(liker),
                    json=dict(profile_uuid=liked['uuid'], decision='like'))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _outbox(person_id: int) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE person_id = %(p)s ORDER BY id",
            dict(p=person_id)).fetchall()]


def _send_log(person_id: int) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            "SELECT campaign, campaign_id FROM email_send_log WHERE person_id = %(p)s ORDER BY id",
            dict(p=person_id)).fetchall()]


def _likes_email_on(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute("INSERT INTO notification_preference (person_id, email_likes) VALUES (%(p)s, TRUE)",
                   dict(p=person_id))


def _sent_campaign_mail_yesterday(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
               VALUES (%(p)s, 'e2', 'cap-test', NOW() - interval '1 day')""", dict(p=person_id))


def test_a_like_email_is_queued_then_logged_on_acceptance(client, make_person, outbox_drain):
    liker = _mailable(make_person, 'EvLiker')
    liked = _mailable(make_person, 'EvLiked', 'Woman')
    _likes_email_on(liked['id'])

    _like(client, liker, liked)

    rows = _outbox(liked['id'])
    assert [(r['campaign'], r['campaign_id'], r['state']) for r in rows] == [
        ('like', f"like-{liker['id']}", 'queued')]
    assert rows[0]['unsub_scope'] == 'notifications'
    assert rows[0]['exempt'] is True
    assert '/matches?tab=likes' in rows[0]['payload']['html']

    sent = outbox_drain(liked['id'])
    assert len(sent) == 1
    assert sent[0]['subject'] == 'Someone likes you on Ahavah'
    assert '/u/notifications.' in sent[0]['list_unsubscribe']
    assert _send_log(liked['id']) == [dict(campaign='like', campaign_id=f"like-{liker['id']}")]


def test_a_match_email_is_queued_and_logged(client, make_person, outbox_drain):
    a = _mailable(make_person, 'EvMatchA')
    b = _mailable(make_person, 'EvMatchB', 'Woman')
    _like(client, b, a)    # a has like emails off, the default: nothing queued
    match = _like(client, a, b)['match']
    assert match is not None

    assert _outbox(a['id']) == []
    rows = _outbox(b['id'])
    assert [(r['campaign'], r['campaign_id']) for r in rows] == [('match', f"match-{match['match_id']}")]
    assert outbox_drain(b['id'])[0]['subject'] == 'You have a new match on Ahavah'
    assert _send_log(b['id']) == [dict(campaign='match', campaign_id=f"match-{match['match_id']}")]


def test_a_message_email_is_queued_and_logged(make_person, outbox_drain):
    import service.cron.notifications as n

    m = _mailable(make_person, 'EvMessage')
    row = n.PersonNotification(
        person_uuid=m['uuid'], last_intro_notification_seconds=0,
        last_chat_notification_seconds=0, last_intro_seconds=0,
        last_chat_seconds=2_000_000_000, has_intro=False, has_chat=True, name='EvMessage',
        email=m['email'], chats_drift_seconds=0, intros_drift_seconds=0, has_live_push=False,
        push_messages=True, email_messages=True, person_id=m['id'])

    asyncio.run(n.send_notification(row))
    asyncio.run(n.send_notification(row))    # the same unread state again

    rows = _outbox(m['id'])
    assert [(r['campaign'], r['campaign_id']) for r in rows] == [('message', 'message-0-2000000000')]
    sent = outbox_drain(m['id'])
    assert sent[0]['subject'] == 'You have a new message on Ahavah'
    assert '/update-notifications' in sent[0]['list_unsubscribe']
    assert _send_log(m['id']) == [dict(campaign='message', campaign_id='message-0-2000000000')]


def test_the_campaign_cap_never_holds_one_back(client, make_person, outbox_drain):
    liker = _mailable(make_person, 'CapLiker')
    liked = _mailable(make_person, 'CapLiked', 'Woman')
    _likes_email_on(liked['id'])
    _sent_campaign_mail_yesterday(liked['id'])

    _like(client, liker, liked)

    assert len(outbox_drain(liked['id'])) == 1


def test_one_never_counts_toward_the_campaign_cap(make_person):
    m = _mailable(make_person, 'CapCount')
    with api_tx() as tx:
        for kind in ('like', 'match', 'message'):
            tx.execute(
                """INSERT INTO email_send_log (person_id, campaign, campaign_id)
                   VALUES (%(p)s, %(c)s, 'today')""", dict(p=m['id'], c=kind))
        assert can_send(tx, m['id'], 'e6', 'e6-next', cap_days=7)
        assert count_sendable(tx, [m['id']], 'e6', None, cap_days=7) == 1

        tx.execute(
            """INSERT INTO email_send_log (person_id, campaign, campaign_id)
               VALUES (%(p)s, 'e3', 'today')""", dict(p=m['id']))
        assert not can_send(tx, m['id'], 'e6', 'e6-next', cap_days=7), 'campaigns still cap'


def test_a_suppressed_address_queues_nothing(client, make_person):
    liker = make_person(name='SupLiker')        # @example.com: suppressed
    liked = make_person(name='SupLiked', gender='Woman')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = ANY(%(ids)s)",
                   dict(ids=[liker['id'], liked['id']]))
    _likes_email_on(liked['id'])
    liker_with_email = dict(liker, email=f"sup-{liker['id']}@example.com")

    _like(client, liker_with_email, liked)

    assert _outbox(liked['id']) == []
