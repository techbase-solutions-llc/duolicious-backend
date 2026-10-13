"""Spotlight: staff accounts are never featured (finding 88), and a card
that lapses unanswered is no longer silent (finding 78)."""
import secrets

import pytest

from database import api_tx
from service.spotlight.eligibility import REASONS, eligibility
from service.spotlight.queue import create_candidate


def _eligible(make_person, name='Lapse', roles=None):
    p = make_person(name=name, gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                      ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                      roles = COALESCE(%(r)s::text[], roles)
                WHERE id = %(id)s""", dict(id=p['id'], r=roles))
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
               VALUES (%(u)s, %(id)s, 1, 'approved', 'blur', gen_random_uuid()::text)""",
            dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _cleanup(person_id):
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE subject_person_id = %(p)s", dict(p=person_id))


def test_a_staff_account_is_not_eligible(make_person):
    p = _eligible(make_person, 'Staffer', roles=['admin'])
    with api_tx('read committed') as tx:
        assert eligibility(tx, p['id']) == (False, 'staff')
    assert 'staff' in REASONS


def test_a_member_with_the_same_profile_is(make_person):
    p = _eligible(make_person, 'Member')
    with api_tx('read committed') as tx:
        assert eligibility(tx, p['id']) == (True, '')


def test_no_card_can_be_created_for_staff(make_person):
    p = _eligible(make_person, 'StaffCard', roles=['admin'])
    with api_tx() as tx, pytest.raises(ValueError, match='staff'):
        create_candidate(tx, kind='member_of_week', subject_person_id=p['id'],
                         caption='x', created_by='test')


def test_a_withheld_invite_for_staff_is_cancelled_not_retried():
    from service.api.admin.spotlight_routes import TERMINAL_INVITE_REASONS
    assert 'staff' in TERMINAL_INVITE_REASONS


# --- finding 78: a lapsed card is no longer silent ---------------------------

H = {'X-Growth-Cron': 'test-cron-secret'}


@pytest.fixture
def settings_on():
    """Turn approvals and invites on for the test and put them back as they
    were: other tests read the shared settings rows."""
    keys = ('approvals_enabled', 'invites_enabled')
    with api_tx() as tx:
        saved = {r['key']: r['value'] for r in tx.execute(
            "SELECT key, value FROM spotlight_setting WHERE key = ANY(%(k)s)", dict(k=list(keys))).fetchall()}
        tx.execute("UPDATE spotlight_setting SET value = 'true' WHERE key = ANY(%(k)s)", dict(k=list(keys)))
    yield
    with api_tx() as tx:
        for k, v in saved.items():
            tx.execute("UPDATE spotlight_setting SET value = %(v)s WHERE key = %(k)s", dict(k=k, v=v))


def _offer(person_id, days_ago=8):
    with api_tx() as tx:
        rk = create_candidate(tx, kind='member_of_week', subject_person_id=person_id,
                              caption='Member of the week', created_by='test')
        tx.execute("UPDATE publishing_queue SET created_at = NOW() - make_interval(days => %(d)s) "
                   "WHERE request_key = %(rk)s", dict(d=days_ago, rk=rk))
    return rk


def test_expiry_names_each_lapsed_card_once(make_person):
    from service.spotlight.offers import expire_lapsed
    p = _eligible(make_person, 'Lapsing')
    rk = _offer(p['id'])
    try:
        with api_tx() as tx:
            lapsed, rows = expire_lapsed(tx)
        mine = [x for x in lapsed if x['request_key'] == rk]
        assert rows >= 2, 'both platform rows are cancelled'
        assert mine == [dict(request_key=rk, person_id=p['id'], kind='member_of_week')]
    finally:
        _cleanup(p['id'])


def test_last_offer_reads_open_then_lapsed(make_person):
    from service.spotlight.offers import expire_lapsed, last_offers
    p = _eligible(make_person, 'LastOffer')
    rk = _offer(p['id'])
    try:
        with api_tx('read committed') as tx:
            assert last_offers(tx, [p['id']])[p['id']]['outcome'] == 'open'
        with api_tx() as tx:
            expire_lapsed(tx)
        with api_tx('read committed') as tx:
            last = last_offers(tx, [p['id']])[p['id']]
        assert last['outcome'] == 'lapsed' and last['kind'] == 'member_of_week'
        assert last['at'] is not None
    finally:
        _cleanup(p['id'])


def test_a_member_never_offered_has_no_last_offer(make_person):
    from service.spotlight.offers import last_offers
    p = _eligible(make_person, 'NeverOffered')
    with api_tx('read committed') as tx:
        assert last_offers(tx, [p['id']]) == {}


def test_the_expiry_route_reports_and_audits_who_lapsed(client, make_person, settings_on):
    p = _eligible(make_person, 'RouteLapse')
    rk = _offer(p['id'])
    try:
        body = client.post('/admin/growth/queue/expire-approvals', headers=H).get_json()
        assert body['cancelled'] >= 2  # one row per platform, as before
        assert dict(request_key=rk, person_id=p['id'], kind='member_of_week') in body['lapsed']
        with api_tx('read committed') as tx:
            row = tx.execute(
                """SELECT actor_email, metadata FROM admin_audit_log
                    WHERE action = 'growth.queue.expire_approvals'
                      AND strpos(metadata::text, %(rk)s) > 0""", dict(rk=rk)).fetchone()
        assert row is not None, 'a lapse from the tick left no audit row'
        assert row['actor_email'] == 'cron'
        assert rk in [x['request_key'] for x in row['metadata']['lapsed']]
    finally:
        _cleanup(p['id'])


def test_candidates_count_cards_that_lapsed_in_the_last_30_days(client, make_person, settings_on):
    p = _eligible(make_person, 'CountLapse')
    _offer(p['id'])
    try:
        before = client.get('/admin/growth/candidates', headers=H).get_json()['lapsed_30_days']
        client.post('/admin/growth/queue/expire-approvals', headers=H)
        after = client.get('/admin/growth/candidates', headers=H).get_json()['lapsed_30_days']
        assert after == before + 1, 'a lapse counts once per card, not once per platform row'
    finally:
        _cleanup(p['id'])


def test_suggestions_skip_a_member_whose_card_is_still_open():
    from service.spotlight.offers import suggestable
    assert suggestable(None) and suggestable(dict(outcome='lapsed'))
    assert not suggestable(dict(outcome='open'))
