"""Recommend Ahavah to a single (TEC-1845, 5a): one email, once per address
whoever sends it, nothing shared about them, and every refusal a sender
could learn from answered exactly as a send."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')


@pytest.fixture
def addresses():
    made: list[str] = []

    def _new(prefix: str = 'single') -> str:
        a = f'{prefix}-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(a)
        return a

    yield _new
    from service.matchmaker import address_key
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE recipient_key = ANY(%(k)s)',
                   dict(k=[address_key(a) for a in made]))


@pytest.fixture
def sender(make_person, sign_in):
    """A member, signed in, whose recommendations go afterwards."""
    from service.matchmaker import address_key
    keys: list[str] = []

    def _make(name: str = 'Hannah Levi') -> dict:
        email = f'hannah-{uuid4().hex[:8]}@ahavah-test.invalid'
        p = make_person(name=name, email=email)
        keys.append(address_key(email))
        return dict(p, email=email, headers=sign_in(p))

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE sender_key = ANY(%(k)s)', dict(k=keys))


def _rows(campaign_rows, email):
    return [r for r in campaign_rows('mm_recommend') if r['email'] == email]


def _recs(sender_email):
    from service.matchmaker import address_key
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM recommendation WHERE sender_key = %(k)s ORDER BY id',
            dict(k=address_key(sender_email))).fetchall()]


def _send(client, headers, email, **body):
    return client.post('/recommendations', headers=headers, json=dict(email=email, **body))


def test_a_member_recommends_a_single_with_their_invite_link(client, sender, addresses, outbox_rows):
    me = sender()
    single = addresses()
    r = _send(client, me['headers'], single, note='You would love the feasts here.')
    assert r.status_code == 201 and r.get_json() == {'state': 'sent'}
    [row] = _rows(outbox_rows, single)
    assert row['recommendation_id'] is not None and row['person_id'] is None
    html = row['payload']['html']
    assert '/i/' in html and '“You would love the feasts here.”' in html
    assert 'Hannah thinks Ahavah could be right for you.' in html
    assert row['payload']['subject'] == 'Hannah thinks Ahavah could be right for you'
    [rec] = _recs(me['email'])
    assert rec['status'] == 'sent' and rec['sender_first_name'] == 'Hannah' and rec['referral_code']


def test_the_default_note(client, sender, addresses, outbox_rows):
    me = sender()
    single = addresses()
    _send(client, me['headers'], single)
    assert '“I think you would be a good fit for Ahavah.”' in _rows(outbox_rows, single)[0]['payload']['html']


def test_every_refusal_answers_as_a_send(client, sender, addresses, make_person, outbox_rows):
    member = addresses('member')
    make_person(email=member)
    me = sender()
    single = addresses()
    bodies = [_send(client, me['headers'], e).get_json() for e in (member, single, single, me['email'])]
    assert bodies == [{'state': 'sent'}] * 4
    assert len(_rows(outbox_rows, single)) == 1
    assert _rows(outbox_rows, member) == [] and _rows(outbox_rows, me['email']) == []
    # Each counts against the week, as a send would, so the allowance says
    # nothing either.
    assert client.get('/recommendations/allowance', headers=me['headers']).get_json() == \
        {'left': 1, 'from': 'Monday'}


def test_an_address_hears_from_us_once_whoever_sends(client, sender, addresses, outbox_rows):
    single = addresses()
    a, b = sender('Hannah Levi'), sender('Ruth Cohen')
    assert _send(client, a['headers'], single).get_json() == {'state': 'sent'}
    assert _send(client, b['headers'], single.upper()).get_json() == {'state': 'sent'}
    assert len(_rows(outbox_rows, single)) == 1


def test_the_sixth_in_a_week_is_refused_until_monday(client, sender, addresses):
    me = sender()
    for _ in range(5):
        assert _send(client, me['headers'], addresses()).status_code == 201
    r = _send(client, me['headers'], addresses())
    assert r.status_code == 429 and r.get_json() == {'error': 'limit', 'from': 'Monday'}
    assert client.get('/recommendations/allowance', headers=me['headers']).get_json() == \
        {'left': 0, 'from': 'Monday'}


def test_last_weeks_do_not_count(client, sender, addresses):
    me = sender()
    for _ in range(5):
        _send(client, me['headers'], addresses())
    with api_tx() as tx:
        tx.execute("UPDATE recommendation SET created_at = created_at - interval '8 days' "
                   "WHERE sender_key = (SELECT sender_key FROM recommendation ORDER BY id DESC LIMIT 1)")
    assert _send(client, me['headers'], addresses()).status_code == 201


@pytest.mark.parametrize('note,reason', [
    ('Call me on 246 555 0123 first.', 'contact'),
    ('See www.example.com for my photos.', 'contact'),
    ('Write to me at ruth@example.com', 'contact'),
])
def test_a_flagged_note_waits_and_sends_nothing(client, sender, addresses, outbox_rows, note, reason):
    me = sender()
    single = addresses()
    r = _send(client, me['headers'], single, note=note)
    assert r.status_code == 201 and r.get_json() == {'state': 'sent'}
    [rec] = _recs(me['email'])
    assert rec['status'] == 'held' and rec['flag_reason'] == reason
    assert _rows(outbox_rows, single) == []


def test_a_visitor_recommends_after_the_code_step(client, tool_visitor, addresses, outbox_rows):
    from service.matchmaker import address_key
    email, h = tool_visitor()
    single = addresses()
    r = _send(client, h, single, first_name='Ruth')
    assert r.status_code == 201 and r.get_json() == {'state': 'sent'}
    [row] = _rows(outbox_rows, single)
    assert 'Ruth thinks Ahavah could be right for you.' in row['payload']['html']
    assert '/i/' not in row['payload']['html']
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE sender_key = %(k)s', dict(k=address_key(email)))


def test_a_visitor_must_give_a_first_name(client, tool_visitor, addresses):
    _email, h = tool_visitor()
    r = _send(client, h, addresses())
    assert r.status_code == 400 and r.get_json()['error'] == 'bad_first_name'


def test_a_refused_address_is_answered_as_a_send(client, sender, addresses, outbox_rows, monkeypatch):
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: 'honeypot')
    me = sender()
    single = addresses()
    assert _send(client, me['headers'], single, website='x').get_json() == {'state': 'sent'}
    assert _rows(outbox_rows, single) == [] and _recs(me['email']) == []


def test_closed_until_its_switch(client, sender, addresses, monkeypatch):
    me = sender()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED')
    assert _send(client, me['headers'], addresses()).status_code == 404
    assert client.get('/recommendations/allowance', headers=me['headers']).status_code == 404


def test_the_week_starts_on_monday():
    from service.matchmaker.recommend import week_start
    assert week_start(datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    assert week_start(datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)


def test_the_note_flags():
    from service.matchmaker.recommend import note_flag
    assert note_flag('You would love it here.') is None
    assert note_flag('My number is 07700 900123') == 'contact'
    assert note_flag('Send me money urgently via western union, my bank froze my account') == 'scam'


def test_closed_while_its_email_is_off_and_nothing_is_kept(client, sender, addresses, outbox_rows, monkeypatch):
    """A recommendation made with the email off would wait as 'queued' with
    the single's address for up to 12 months, so it is refused up front
    (review, 21 Oct)."""
    me = sender()
    single = addresses()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED')
    assert _send(client, me['headers'], single).status_code == 404
    assert client.get('/recommendations/allowance', headers=me['headers']).status_code == 404
    assert _recs(me['email']) == [] and _rows(outbox_rows, single) == []


def test_the_service_refuses_too_while_the_email_is_off(sender, monkeypatch):
    from service.matchmaker import MatchmakerError, address_key
    from service.matchmaker.recommend import recommend
    me = sender()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED')
    with pytest.raises(MatchmakerError) as e, api_tx('read committed') as tx:
        recommend(tx, sender=dict(person_id=me['id'], first_name='Hannah', key=address_key(me['email']),
                                  normalized_email=me['email']),
                  email='nobody-kept@ahavah-test.invalid', note=None)
    assert e.value.status == 404
