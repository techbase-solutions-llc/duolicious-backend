"""The accept-or-decline card (TEC-1845, 5c): a match only from two yeses,
the introducer told only of a match, and nobody ever told of a no."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

NOTE = 'Both of you love the feasts.'


@pytest.fixture
def open_intro(client, introducer_with_two, sign_in):
    """open_intro() -> (intro_id, headers_a, headers_b): Task 9's pair, one
    suggestion posted. The people are on open_intro.people."""
    def _make():
        h, miriam, daniel, hannah = introducer_with_two()
        r = client.post('/introductions', headers=h,
                        json=dict(a_uuid=miriam['uuid'], b_uuid=daniel['uuid'], note=NOTE))
        assert r.status_code == 201 and r.get_json()['state'] == 'sent', r.get_data(as_text=True)
        with api_tx('read committed') as tx:
            iid = tx.execute('SELECT id FROM introduction WHERE introducer_person_id = %(i)s',
                             dict(i=hannah['id'])).fetchone()['id']
        _make.people = dict(h=h, a=miriam, b=daniel, introducer=hannah)
        return iid, sign_in(miriam), sign_in(daniel)
    return _make


def _accept(h, iid):
    from service.api.decorators import app
    with app.test_client() as c:
        return c.post(f'/introductions/{iid}/accept', headers=h)


def _match_count(open_intro):
    p = open_intro.people
    with api_tx('read committed') as tx:
        return tx.execute('SELECT count(*) AS n FROM ahavah_match WHERE user_a_id = LEAST(%(a)s::int, %(b)s::int) '
                          'AND user_b_id = GREATEST(%(a)s::int, %(b)s::int)',
                          dict(a=p['a']['id'], b=p['b']['id'])).fetchone()['n']


def test_the_card_says_who_introduced_them_and_when_it_closes(client, open_intro):
    iid, ha, _hb = open_intro()
    body = client.get('/introductions/pending', headers=ha).get_json()
    [card] = body['pending']
    assert card['id'] == iid and card['introducer_first_name'] == 'Hannah' and card['note'] == NOTE
    assert card['other']['first_name'] == 'Daniel' and card['other']['uuid'] == open_intro.people['b']['uuid']
    closes = datetime.now(timezone.utc) + timedelta(days=14)
    assert card['closes_on'] == f'{closes.day} {closes:%B}'
    assert body['waiting'] == []


def test_both_accepting_makes_a_match_and_tells_the_introducer(client, open_intro, monkeypatch):
    from service.matchmaker import mail
    pushes = []
    monkeypatch.setattr(mail, '_send_push', lambda pid, push, kind: pushes.append((pid, push['body'])))
    iid, ha, hb = open_intro()
    p = open_intro.people
    first = client.post(f'/introductions/{iid}/accept', headers=ha)
    assert first.status_code == 200 and first.get_json() == {'state': 'waiting'}
    assert client.get('/introductions/pending', headers=ha).get_json()['waiting'][0]['other_first_name'] == 'Daniel'
    assert client.get('/introductions/told', headers=p['h']).get_json() == {'told': []}
    second = client.post(f'/introductions/{iid}/accept', headers=hb).get_json()
    assert second['state'] == 'matched' and second['other_uuid'] == p['a']['uuid'] and second['match_id']
    assert _match_count(open_intro) == 1
    assert client.get('/introductions/told', headers=p['h']).get_json() == \
        {'told': [{'id': iid, 'a_first_name': 'Miriam', 'b_first_name': 'Daniel'}]}
    assert client.get('/introductions/told', headers=p['h']).get_json() == {'told': []}
    assert (p['introducer']['id'], 'Miriam and Daniel both said yes.') in pushes
    matches = client.get('/matches', headers=ha).get_json()['matches']
    [m] = [m for m in matches if m['with_profile']['id'] == p['b']['uuid']]
    assert m['introduced_by'] == {'first_name': 'Hannah'}
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT count(*) AS n FROM liked WHERE (liker_id, liked_id) IN ((%(a)s, %(b)s), (%(b)s, %(a)s))',
                          dict(a=p['a']['id'], b=p['b']['id'])).fetchone()['n'] == 2


def test_a_decline_tells_nobody(client, open_intro, outbox_rows, monkeypatch):
    from service.matchmaker import mail
    pushes = []
    monkeypatch.setattr(mail, '_send_push', lambda pid, push, kind: pushes.append(pid))
    iid, ha, hb = open_intro()
    p = open_intro.people
    client.post(f'/introductions/{iid}/accept', headers=ha)
    before = len(outbox_rows('mm_intro'))
    pushes.clear()
    r = client.post(f'/introductions/{iid}/decline', headers=hb)
    assert r.status_code == 200 and r.get_json() == {'state': 'gone'}
    a_view = client.get('/introductions/pending', headers=ha).get_json()
    assert a_view == {'pending': [], 'waiting': []}
    assert client.get('/introductions/told', headers=p['h']).get_json() == {'told': []}
    assert len(outbox_rows('mm_intro')) == before and pushes == []
    assert _match_count(open_intro) == 0


def test_both_accepting_at_once_makes_one_match(client, open_intro):
    intro, ha, hb = open_intro()
    with ThreadPoolExecutor(2) as ex:
        states = sorted(f.result().get_json()['state'] for f in
                        [ex.submit(_accept, ha, intro), ex.submit(_accept, hb, intro)])
    assert states == ['matched', 'waiting'] and _match_count(open_intro) == 1


@pytest.mark.parametrize('how', ['lapsed', 'blocked', 'unmatched'])
def test_accepting_a_closed_or_blocked_introduction_matches_nobody(client, open_intro, how):
    iid, ha, hb = open_intro()
    p = open_intro.people
    client.post(f'/introductions/{iid}/accept', headers=ha)
    with api_tx() as tx:
        if how == 'lapsed':
            tx.execute("UPDATE introduction SET closes_at = NOW() - interval '1 minute' WHERE id = %(i)s", dict(i=iid))
        elif how == 'blocked':
            tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) VALUES (%(a)s, %(b)s, TRUE)',
                       dict(a=p['a']['id'], b=p['b']['id']))
        else:
            tx.execute('INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by) '
                       'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int), %(a)s)',
                       dict(a=p['a']['id'], b=p['b']['id']))
    r = client.post(f'/introductions/{iid}/accept', headers=hb)
    assert r.status_code == 410 and r.get_json() == {'error': 'closed'}
    assert _match_count(open_intro) == 0
    assert client.get('/introductions/pending', headers=hb).get_json()['pending'] == []


def test_the_card_shows_the_gradient_to_a_viewer_held_by_the_photo_gate(client, open_intro, monkeypatch):
    iid, ha, _hb = open_intro()
    p = open_intro.people
    monkeypatch.setenv('AHAVAH_PHOTO_GATE_ENABLED', '1')
    with api_tx() as tx:
        tx.execute('UPDATE photo SET face_count = 0 WHERE person_id = %(i)s', dict(i=p['a']['id']))
        held = tx.execute('SELECT can_view_photos(%(i)s) AS ok', dict(i=p['a']['id'])).fetchone()['ok']
    [card] = client.get('/introductions/pending', headers=ha).get_json()['pending']
    if held:
        pytest.skip('the photo gate does not hold this viewer in this database')
    assert card['other']['photo_uuids'] == [] and card['other']['gradient_seed'] == 'Daniel'
    monkeypatch.delenv('AHAVAH_PHOTO_GATE_ENABLED')
    [card] = client.get('/introductions/pending', headers=ha).get_json()['pending']
    assert len(card['other']['photo_uuids']) == 1


def test_lapsed_introductions_close_silently(open_intro, outbox_rows):
    from service.matchmaker.introductions import close_lapsed
    iid, _ha, _hb = open_intro()
    before = len(outbox_rows('mm_intro'))
    with api_tx() as tx:
        tx.execute("UPDATE introduction SET closes_at = NOW() - interval '1 minute' WHERE id = %(i)s", dict(i=iid))
        assert close_lapsed(tx, datetime.now(timezone.utc)) >= 1
        assert tx.execute('SELECT status FROM introduction WHERE id = %(i)s', dict(i=iid)).fetchone()['status'] == 'closed'
    assert len(outbox_rows('mm_intro')) == before


def test_someone_else_cannot_answer(client, open_intro, make_person, sign_in):
    iid, _ha, _hb = open_intro()
    other = sign_in(make_person(name='Nosy'))
    assert client.post(f'/introductions/{iid}/accept', headers=other).status_code == 404
    assert client.post('/introductions/999999999/accept', headers=other).status_code == 404


def test_the_chat_context_line(client, open_intro):
    iid, ha, hb = open_intro()
    p = open_intro.people
    assert client.get(f"/introductions/with/{p['b']['uuid']}", headers=ha).status_code == 404
    client.post(f'/introductions/{iid}/accept', headers=ha)
    client.post(f'/introductions/{iid}/accept', headers=hb)
    r = client.get(f"/introductions/with/{p['b']['uuid']}", headers=ha)
    assert r.get_json() == {'introducer_first_name': 'Hannah', 'note': NOTE}
    assert client.get(f"/introductions/with/{p['a']['uuid']}", headers=hb).get_json()['note'] == NOTE


def test_the_close_job_runs_in_the_cron():
    from service.cron.returnmail import JOBS
    assert 'mm_intro_close' in [n for n, _ in JOBS]


def test_the_match_push_from_an_introduction_has_no_exclamation_mark(client, open_intro, monkeypatch):
    """House copy has no exclamation marks; the generic match push keeps its
    own title (review, 21 Oct)."""
    import service.notifications as notifications
    sent = []
    monkeypatch.setattr(notifications, 'notify', lambda pid, kind, **kw: sent.append((pid, kind, kw)))
    iid, ha, hb = open_intro()
    p = open_intro.people
    client.post(f'/introductions/{iid}/accept', headers=ha)
    assert client.post(f'/introductions/{iid}/accept', headers=hb).get_json()['state'] == 'matched'
    [(pid, kind, kw)] = [s for s in sent if s[1] == 'match']
    assert pid == p['a']['id'] and kw['title'] == "It's a match" and kw['body'] == 'Daniel likes you back'
