"""Admin, the matchmaker (TEC-1845): held notes, the counts and a member's
connections. Counts only; never who said no, a recipient, a mentor's note
or a message. The shared database has other rows, so counts are compared
before and after."""
from __future__ import annotations

from service.matchmaker.admin import mask_email
import json
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')

NOTE = 'You both love the feasts.'


def _counts(client, admin_headers):
    r = client.get('/admin/matchmaker', headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _suggest(client, h, a, b, note=NOTE):
    return client.post('/introductions', headers=h, json=dict(a_uuid=a['uuid'], b_uuid=b['uuid'], note=note))


@pytest.fixture
def recommender(make_person, sign_in):
    from service.matchmaker import address_key
    keys: list[str] = []

    def _make():
        email = f'hannah-{uuid4().hex[:8]}@ahavah-test.invalid'
        p = make_person(name='Hannah Levi', email=email)
        keys.append(address_key(email))
        return dict(p, headers=sign_in(p))

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE sender_key = ANY(%(k)s)', dict(k=keys))


def test_the_counts_are_counts(client, admin_headers, make_person, sign_in):
    before = _counts(client, admin_headers)
    assert set(before) == {'alerts', 'introductions', 'mentors', 'live'}
    assert set(before['alerts']) == {'member_on', 'visitor_confirmed', 'notices_sent', 'visitor_signups',
                                     'push_taps'}
    assert set(before['introductions']) == {'recommendations_sent', 'singles_joined', 'suggestions_made',
                                            'accepted_by_both', 'conversations_followed',
                                            'intro_push_taps', 'told_push_taps'}
    assert set(before['mentors']) == {'invited', 'confirmed', 'active', 'removed', 'chose_not_to_match'}
    assert all(isinstance(v, int) for g in ('alerts', 'introductions', 'mentors') for v in before[g].values())
    assert before['live'] == {'alerts': True, 'introductions': True, 'mentors': True}
    h = sign_in(make_person(name='Counted'))
    client.put('/matchmaker/alert', headers=h, json=dict(criteria=dict(age_min=26, age_max=34)))
    assert _counts(client, admin_headers)['alerts']['member_on'] == before['alerts']['member_on'] + 1


def test_the_counts_work_while_dark(client, admin_headers, monkeypatch):
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert _counts(client, admin_headers)['live'] == {'alerts': False, 'introductions': False, 'mentors': False}


def test_a_hidden_refusal_is_not_counted(client, admin_headers, introducer_with_two):
    h, miriam, daniel, _ = introducer_with_two()
    with api_tx() as tx:
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) VALUES (%(a)s, %(b)s, TRUE)',
                   dict(a=miriam['id'], b=daniel['id']))
    before = _counts(client, admin_headers)['introductions']['suggestions_made']
    _suggest(client, h, miriam, daniel)
    assert _counts(client, admin_headers)['introductions']['suggestions_made'] == before


def test_nobody_sees_who_said_no(client, admin_headers, introducer_with_two, sign_in):
    h, miriam, daniel, hannah = introducer_with_two()
    _suggest(client, h, miriam, daniel)
    with api_tx('read committed') as tx:
        iid = tx.execute('SELECT id FROM introduction WHERE introducer_person_id = %(i)s',
                         dict(i=hannah['id'])).fetchone()['id']
    client.post(f'/introductions/{iid}/decline', headers=sign_in(daniel))
    r = client.get(f"/admin/users/{hannah['id']}/connections", headers=admin_headers)
    body = r.get_json()
    assert body['introductions'] == {'made': 1, 'accepted_by_both': 0, 'not_taken_further': 1, 'received': 0}
    text = json.dumps(body)
    for p in (miriam, daniel):
        assert p['uuid'] not in text and str(p['id']) not in text
    assert 'Miriam' not in text and 'Daniel' not in text
    assert client.get(f"/admin/users/{hannah['uuid']}/connections", headers=admin_headers).get_json() == body
    assert client.get(f"/admin/users/{miriam['id']}/connections", headers=admin_headers).get_json()[
        'introductions']['received'] == 1


def test_the_drawer_never_carries_a_note_or_a_message(client, admin_headers, single_with_mentor):
    single, match, h_single, _h = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    client.put('/matchmaker/alert', headers=h_single, json=dict(criteria=dict(age_min=26, age_max=34)))
    with api_tx() as tx:
        tx.execute("""INSERT INTO mentor_note (mentor_account_id, single_person_id, about_person_id, note)
                      VALUES (%(m)s, %(s)s, %(a)s, 'Ask about his family.')""",
                   dict(m=single['mentor_account_id'], s=single['id'], a=match['id']))
    body = client.get(f"/admin/users/{single['id']}/connections", headers=admin_headers).get_json()
    assert 'Ask about' not in json.dumps(body)
    assert body['mentor']['conversations_shared'] == 1 and body['mentor']['email'] != single['mentor_email']
    assert body['mentor']['email'] == mask_email(single['mentor_email'])
    assert '••••@' in body['mentor']['email']
    assert body['alert'] == {'on': True, 'criteria_line': 'Age 26 to 34, anywhere, any relocation',
                             'last_notice_at': None}


def test_nothing_yet_is_empty(client, admin_headers, make_person):
    p = make_person(name='Quiet')
    assert client.get(f"/admin/users/{p['id']}/connections", headers=admin_headers).get_json() == dict(
        alert=None, introductions=dict(made=0, accepted_by_both=0, not_taken_further=0, received=0), mentor=None)
    assert client.get('/admin/users/999999999/connections', headers=admin_headers).status_code == 404


def _held(client, admin_headers, kind):
    return [x for x in client.get('/admin/moderation/text', headers=admin_headers).get_json()['held']
            if x['kind'] == kind]


def test_approving_a_held_recommendation_sends_it(client, admin_headers, recommender, outbox_rows):
    me = recommender()
    single = f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
    client.post('/recommendations', headers=me['headers'], json=dict(email=single, note='Call 246 555 0123'))
    [item] = [x for x in _held(client, admin_headers, 'recommendation') if x['author_person_id'] == me['id']]
    assert item['note'] == 'Call 246 555 0123' and item['flag_reason'] == 'contact'
    assert item['author_first_name'] == 'Hannah'
    r = client.post(f"/admin/moderation/text/recommendation/{item['id']}/approve", headers=admin_headers)
    assert r.status_code == 200
    assert [row for row in outbox_rows('mm_recommend') if row['email'] == single]
    assert client.post(f"/admin/moderation/text/recommendation/{item['id']}/approve",
                       headers=admin_headers).status_code == 404


def test_approving_a_held_introduction_opens_it_and_tells_both(client, admin_headers, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    _suggest(client, h, miriam, daniel, note='Text him on 246 555 0123')
    [item] = [x for x in _held(client, admin_headers, 'introduction') if x['author_person_id'] == hannah['id']]
    client.post(f"/admin/moderation/text/introduction/{item['id']}/approve", headers=admin_headers)
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT status, closes_at, opened_at, reviewed_by FROM introduction WHERE id = %(i)s',
                         dict(i=item['id'])).fetchone()
        sent = tx.execute("SELECT count(*) AS n FROM email_outbox WHERE campaign = 'mm_intro' "
                          "AND campaign_id LIKE %(c)s", dict(c=f"{item['id']}:%")).fetchone()['n']
    assert row['status'] == 'open' and row['opened_at'] is not None and row['reviewed_by'] is not None
    assert sent == 2


def test_rejecting_sends_nothing_and_tells_nobody(client, admin_headers, introducer_with_two, monkeypatch):
    from service.matchmaker import mail
    pushes = []
    monkeypatch.setattr(mail, '_send_push', lambda pid, push, kind: pushes.append(pid))
    h, miriam, daniel, hannah = introducer_with_two()
    _suggest(client, h, miriam, daniel, note='Text him on 246 555 0123')
    [item] = [x for x in _held(client, admin_headers, 'introduction') if x['author_person_id'] == hannah['id']]
    client.post(f"/admin/moderation/text/introduction/{item['id']}/reject", headers=admin_headers)
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT status FROM introduction WHERE id = %(i)s',
                          dict(i=item['id'])).fetchone()['status'] == 'rejected'
        assert tx.execute("SELECT count(*) AS n FROM email_outbox WHERE campaign = 'mm_intro' "
                          "AND campaign_id LIKE %(c)s", dict(c=f"{item['id']}:%")).fetchone()['n'] == 0
    assert pushes == []
    assert client.get('/introductions/pending', headers=h).get_json() == {'pending': [], 'waiting': []}


def test_the_text_queue_never_shows_a_recipient(client, admin_headers, recommender, introducer_with_two):
    me = recommender()
    single = f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
    client.post('/recommendations', headers=me['headers'], json=dict(email=single, note='See www.example.com'))
    h, miriam, daniel, _ = introducer_with_two()
    _suggest(client, h, miriam, daniel, note='Text him on 246 555 0123')
    text = client.get('/admin/moderation/text', headers=admin_headers).get_data(as_text=True)
    assert single not in text and 'Miriam' not in text and 'Daniel' not in text
    assert miriam['uuid'] not in text and daniel['uuid'] not in text


ROUTES = [('get', '/admin/matchmaker'), ('get', '/admin/users/1/connections'), ('get', '/admin/moderation/text'),
          ('post', '/admin/moderation/text/introduction/1/approve'),
          ('post', '/admin/moderation/text/recommendation/1/reject')]


def test_every_route_needs_an_admin(client, make_person, sign_in):
    headers = sign_in(make_person(name='Member'))
    for method, path in ROUTES:
        r = getattr(client, method)(path, headers=headers)
        assert r.status_code == 403, (method, path, r.status_code)


def test_every_change_is_audited(client, admin_headers, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    _suggest(client, h, miriam, daniel, note='Text him on 246 555 0123')
    [item] = [x for x in _held(client, admin_headers, 'introduction') if x['author_person_id'] == hannah['id']]
    client.post(f"/admin/moderation/text/introduction/{item['id']}/reject", headers=admin_headers)
    with api_tx('read committed') as tx:
        actions = [r['action'] for r in tx.execute(
            """SELECT action FROM admin_audit_log WHERE action LIKE 'matchmaker.%%'
                 AND metadata->>'id' = %(i)s AND metadata->>'kind' = 'introduction'""",
            dict(i=str(item['id']))).fetchall()]
    assert actions == ['matchmaker.note.reject']


def test_a_mentor_address_is_masked_to_its_first_letters():
    assert mask_email('rivka.levi@gmail.com') == 'r••••@g••••.com'
    assert mask_email('a@b') == 'a••••@b••••'
    assert mask_email(None) is None


def test_the_matchmaker_push_taps_are_counted(client, admin_headers, make_person, sign_in):
    """Fix 11 recorded taps on the alert, introduction and both-said-yes
    pushes (mmalert, mmintro, mmtold) but nothing read them (23 Oct 2026
    review, GAP-1). Each now counts where the push belongs."""
    before = _counts(client, admin_headers)
    h = sign_in(make_person(name='Tapped'))
    for src in ('mmalert', 'mmintro', 'mmtold'):
        r = client.post('/push-taps', headers=h, json=dict(src=src))
        assert r.status_code == 204, r.get_data(as_text=True)
    after = _counts(client, admin_headers)
    assert after['alerts']['push_taps'] == before['alerts']['push_taps'] + 1
    assert after['introductions']['intro_push_taps'] == before['introductions']['intro_push_taps'] + 1
    assert after['introductions']['told_push_taps'] == before['introductions']['told_push_taps'] + 1
