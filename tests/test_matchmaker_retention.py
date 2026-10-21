"""What the matchmaker keeps and for how long (TEC-1845, plan item 31),
deleting with the account, and counting a recommended single who joins."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from antiabuse.antispam.signupemail import normalize_email
from database import api_tx
from service.matchmaker import address_key, retention

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


@pytest.fixture
def sent_recommendation(make_person, sign_in, client):
    keys: list[str] = []

    def _make(single: str | None = None) -> dict:
        single = single or f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
        email = f'hannah-{uuid4().hex[:8]}@ahavah-test.invalid'
        p = make_person(name='Hannah Levi', email=email)
        keys.extend([address_key(email), address_key(single)])
        r = client.post('/recommendations', headers=sign_in(p), json=dict(email=single, note='You would love it.'))
        assert r.status_code == 201
        with api_tx('read committed') as tx:
            row = dict(tx.execute('SELECT * FROM recommendation WHERE recipient_key = %(k)s',
                                  dict(k=address_key(single))).fetchone())
        return dict(row, single=single, sender=p, sender_email=email)

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE recipient_key = ANY(%(k)s) OR sender_key = ANY(%(k)s)',
                   dict(k=keys))


def _settle(rec_id, days_ago=8):
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET state = 'accepted', sent_at = NOW() - make_interval(days => %(d)s)
                       WHERE recommendation_id = %(i)s""", dict(d=days_ago, i=rec_id))


def _rec(rec_id):
    with api_tx('read committed') as tx:
        row = tx.execute('SELECT * FROM recommendation WHERE id = %(i)s', dict(i=rec_id)).fetchone()
    return dict(row) if row else None


def _purge():
    with api_tx() as tx:
        return retention.purge_matchmaker_data(tx)


def test_a_recommended_address_is_erased_7_days_after_sending_and_its_key_stays(sent_recommendation):
    rec = sent_recommendation()
    _settle(rec['id'], days_ago=3)
    _purge()
    assert _rec(rec['id'])['recipient_email'] == rec['single']
    _settle(rec['id'], days_ago=8)
    assert _purge()['recommendations_erased'] >= 1
    after = _rec(rec['id'])
    assert after['recipient_email'] is None and after['note'] is None and after['erased_at'] is not None
    assert after['recipient_key'] == address_key(rec['single'])
    with api_tx('read committed') as tx:
        o = tx.execute('SELECT email, payload FROM email_outbox WHERE recommendation_id = %(i)s',
                       dict(i=rec['id'])).fetchone()
    assert o['email'] != rec['single'] and '*' in o['email'] and o['payload']['html'] == ''


def test_the_key_still_stops_a_second_recommendation_after_erasure(client, sent_recommendation, make_person,
                                                                   sign_in, outbox_rows):
    rec = sent_recommendation()
    _settle(rec['id'])
    _purge()
    ruth = f'ruth-{uuid4().hex[:8]}@ahavah-test.invalid'
    other = make_person(name='Ruth', email=ruth)
    r = client.post('/recommendations', headers=sign_in(other), json=dict(email=rec['single']))
    assert r.get_json() == {'state': 'sent'}
    assert [x for x in outbox_rows('mm_recommend') if x['email'] == rec['single']] == []
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE sender_key = %(k)s', dict(k=address_key(ruth)))


def test_a_recommendation_row_goes_after_12_months(sent_recommendation):
    rec = sent_recommendation()
    with api_tx() as tx:
        tx.execute("UPDATE recommendation SET created_at = NOW() - interval '366 days' WHERE id = %(i)s",
                   dict(i=rec['id']))
    _purge()
    assert _rec(rec['id']) is None


def _intro(client, introducer_with_two, sign_in):
    h, miriam, daniel, hannah = introducer_with_two()
    client.post('/introductions', headers=h, json=dict(a_uuid=miriam['uuid'], b_uuid=daniel['uuid'],
                                                      note='You both love the feasts.'))
    with api_tx('read committed') as tx:
        iid = tx.execute('SELECT id FROM introduction WHERE introducer_person_id = %(i)s',
                         dict(i=hannah['id'])).fetchone()['id']
    return iid, sign_in(miriam), sign_in(daniel)


def _note(iid):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT note FROM introduction WHERE id = %(i)s', dict(i=iid)).fetchone()['note']


def test_an_unmatched_introductions_note_goes_30_days_after_it_closes(client, introducer_with_two, sign_in):
    iid, _ha, hb = _intro(client, introducer_with_two, sign_in)
    client.post(f'/introductions/{iid}/decline', headers=hb)
    _purge()
    assert _note(iid) == 'You both love the feasts.'
    with api_tx() as tx:
        tx.execute("UPDATE introduction SET b_responded_at = NOW() - interval '31 days', "
                   "a_responded_at = NULL WHERE id = %(i)s", dict(i=iid))
    _purge()
    assert _note(iid) is None


def test_a_matched_introductions_note_stays(client, introducer_with_two, sign_in):
    iid, ha, hb = _intro(client, introducer_with_two, sign_in)
    client.post(f'/introductions/{iid}/accept', headers=ha)
    client.post(f'/introductions/{iid}/accept', headers=hb)
    with api_tx() as tx:
        tx.execute("UPDATE introduction SET closes_at = NOW() - interval '60 days' WHERE id = %(i)s", dict(i=iid))
    _purge()
    assert _note(iid) == 'You both love the feasts.'


def test_an_unconfirmed_visitor_alert_goes(client):
    email = f'visitor-{uuid4().hex[:8]}@ahavah-test.invalid'
    client.post('/alerts', json=dict(email=email, looking_for='man', age_min=26, age_max=34))
    with api_tx() as tx:
        tx.execute("""UPDATE match_alert SET confirm_by = NOW() - interval '2 days'
                       WHERE lead_id = (SELECT id FROM lead WHERE email = %(e)s)""", dict(e=email))
    _purge()
    with api_tx() as tx:
        assert tx.execute("SELECT 1 FROM match_alert a JOIN lead l ON l.id = a.lead_id WHERE l.email = %(e)s",
                          dict(e=email)).fetchone() is None
        tx.execute('DELETE FROM lead WHERE email = %(e)s', dict(e=email))


def test_a_lapsed_mentor_session_goes(single_with_mentor):
    from service.matchmaker.mentor_view import _issue, mentor_for
    single, _m, _hs, _hm = single_with_mentor()
    with api_tx() as tx:
        token = _issue(tx, single['mentor_account_id'], NOW() - timedelta(days=32))['token']
    _purge()
    from service.leads import token_hash
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM mentor_session WHERE token_hash = %(h)s',
                          dict(h=token_hash(token))).fetchone() is None


def test_an_invitation_never_accepted_ends(make_person, client, sign_in):
    p = make_person(name='Rivka')
    h = sign_in(p)
    client.post('/mentor/invite', headers=h, json=dict(email='ruth@ahavah-test.invalid', relation='parent'))
    with api_tx() as tx:
        tx.execute("UPDATE mentor_link SET invite_expires_at = NOW() - interval '2 days' WHERE single_person_id = %(p)s",
                   dict(p=p['id']))
    _purge()
    assert client.get('/mentor', headers=h).get_json()['state'] == 'none'


def test_a_mentor_account_serving_nobody_goes_after_30_days(single_with_mentor, client):
    single, _m, h_single, _hm = single_with_mentor()
    client.delete('/mentor', headers=h_single)
    _purge()
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM mentor_account WHERE id = %(i)s',
                          dict(i=single['mentor_account_id'])).fetchone() is not None
    with api_tx() as tx:
        tx.execute("UPDATE mentor_link SET revoked_at = NOW() - interval '31 days' WHERE id = %(i)s",
                   dict(i=single['link_id']))
    _purge()
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM mentor_account WHERE id = %(i)s',
                          dict(i=single['mentor_account_id'])).fetchone() is None


@pytest.mark.parametrize('shape', ['admin_hard_delete', 'pending_deletion'])
def test_deleting_an_account_deletes_its_matchmaker_data(client, single_with_mentor,
                                                         make_person, sign_in, shape):
    # The leaving member was recommended, sends recommendations and has a mentor.
    single, match, h_single, _ = single_with_mentor()
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=single['id'])).fetchone()['email']
    # A recommendation sent to her address before she joined.
    with api_tx() as tx:
        to_them = tx.execute(
            """INSERT INTO recommendation (sender_key, sender_first_name, recipient_key, status, sent_at)
               VALUES ('k-' || md5(random()::text), 'Ruth', %(k)s, 'sent', NOW()) RETURNING id""",
            dict(k=address_key(normalize_email(email)))).fetchone()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    friend = f'friend-{uuid4().hex[:8]}@ahavah-test.invalid'
    mine = client.post('/recommendations', headers=h_single, json=dict(email=friend, note='From Rivka'))
    assert mine.status_code == 201
    # A mentor account with the same address as another leaving person.
    leaving_mentor = single['mentor_email']
    emails = [email] if shape == 'admin_hard_delete' else [email, leaving_mentor]
    nes = [normalize_email(e) for e in emails]
    with api_tx() as tx:
        tx.execute(retention.Q_DELETE_MATCHMAKER_DATA_OF,
                   dict(nes=nes, ids=[single['id']], keys=retention.matchmaker_keys(nes)))
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM recommendation WHERE id = %(i)s', dict(i=to_them['id'])).fetchone() is None
        assert tx.execute('SELECT 1 FROM mentor_link WHERE single_person_id = %(s)s',
                          dict(s=single['id'])).fetchone() is None
        assert tx.execute('SELECT 1 FROM shared_conversation WHERE single_person_id = %(s)s',
                          dict(s=single['id'])).fetchone() is None
        sent = tx.execute("SELECT * FROM recommendation WHERE note = 'From Rivka'").fetchall()
        assert sent == []
        gone = tx.execute('SELECT 1 FROM mentor_account WHERE id = %(i)s',
                          dict(i=single['mentor_account_id'])).fetchone() is None
    assert gone is (shape == 'pending_deletion')
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE recipient_key = %(k)s', dict(k=address_key(friend)))


def test_an_account_with_no_address_binds_empty_lists():
    with api_tx() as tx:
        assert tx.execute(retention.Q_DELETE_MATCHMAKER_DATA_OF,
                          dict(nes=[], ids=[], keys=[])).fetchone()['n'] == 0


def test_the_three_deletion_callers_run_it():
    root = Path(__file__).resolve().parent.parent
    for path in ('service/hard_delete.py', 'service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        assert 'Q_DELETE_MATCHMAKER_DATA_OF' in (root / path).read_text(encoding='utf-8'), path


def test_a_recommended_single_who_joins_is_counted(sent_recommendation, finish_onboarding):
    single = f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
    rec = sent_recommendation(single=single)
    r, pid = finish_onboarding(email=single)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _rec(rec['id'])['joined_person_id'] == pid
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM person WHERE id = %(i)s', dict(i=pid)).fetchone()['lead_source'] == 'intro'


def test_first_touch_wins_over_intro(sent_recommendation, finish_onboarding):
    single = f'single-{uuid4().hex[:8]}@ahavah-test.invalid'
    rec = sent_recommendation(single=single)
    _r, pid = finish_onboarding(email=single, lead_source='referral:HANNAH7K')
    assert _rec(rec['id'])['joined_person_id'] == pid
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                          dict(i=pid)).fetchone()['lead_source'] == 'referral:HANNAH7K'
