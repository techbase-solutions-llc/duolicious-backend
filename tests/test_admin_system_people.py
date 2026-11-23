"""Admin > System counts people, not requests (TEC-2144).

The review of 11 Nov 2026 found the System tab's figures counting the wrong
things:

- "Codes nobody entered" read 65 when 17 addresses had never finished: an
  address that asks again has its pending session deleted, and each ask
  was counted. Member sign-ins had the same fault, and counted admins.
- Sign-ups and active users left out admins only, so a moderator, a tester
  or a deactivated account counted, while Overview and testers.py said
  member counts leave testers out.
- FireHOL, Turnstile and unknown-domain refusals were never recorded, and
  event RSVP, visitor alert and tool invite refusals landed in the sign-up
  refusal count.
- "OTP sessions" counted duo_session rows under words that did not match.

Every test reads the real route or the real query against seeded rows.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service.admin.queries import Q_OVERVIEW_KPIS, Q_SYSTEM_HEALTH
from service.admin.queries.overview import (
    Q_OVERVIEW_MEMBER_TOTAL, Q_OVERVIEW_MEMBERS_30D)


@pytest.fixture
def admin_headers(make_person, sign_in):
    p = make_person(name='SystemPeopleAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return sign_in(p)


def _health(client, headers) -> dict:
    r = client.get('/admin/system/health', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _today(client, headers) -> dict:
    return _health(client, headers)['otp_daily'][-1]


def _email(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=person_id)).fetchone()['email']


def _enter(client, email: str, token: str) -> None:
    """Enter the code the session holds, read from the session itself."""
    import hashlib
    with api_tx('read committed') as tx:
        otp = tx.execute(
            'SELECT otp FROM duo_session WHERE session_token_hash = %(h)s',
            dict(h=hashlib.sha512(token.encode()).hexdigest())).fetchone()['otp']
    r = client.post('/check-otp', json=dict(email=email, otp=otp),
                    headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200, r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# One member rule for sign-ups and active users, System and Overview alike
# ---------------------------------------------------------------------------

_SIGN_UPS = ('system_today', 'system_7d', 'system_30d', 'overview_today')
# members_spark is the last point of the Members sparkline, so every case
# below holds it to the card beside it (TEC-1832).
_ACTIVE = ('dau', 'wau', 'mau', 'overview_active', 'member_total', 'members_spark')


def _counts() -> dict:
    from service.growth.queries import _excluded
    with api_tx('read committed') as tx:
        system = dict(tx.execute(Q_SYSTEM_HEALTH).fetchone())
        overview = dict(tx.execute(Q_OVERVIEW_KPIS).fetchone())
        total = tx.execute(Q_OVERVIEW_MEMBER_TOTAL, dict(ex=_excluded())).fetchone()
        spark = tx.execute(Q_OVERVIEW_MEMBERS_30D, dict(ex=_excluded())).fetchall()
    return dict(
        system_today=int(system['signups_today']),
        system_7d=int(system['signups_7d']),
        system_30d=int(system['signups_30d']),
        dau=int(system['dau']), wau=int(system['wau']), mau=int(system['mau']),
        overview_today=int(overview['signups_today']),
        overview_active=int(overview['active_24h']),
        member_total=int(total['member_total']),
        members_spark=int(spark[-1]['total']),
    )


def _joined_and_online(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute(
            """UPDATE person
                  SET sign_up_time = (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 minute',
                      last_online_time = NOW() - INTERVAL '1 minute'
                WHERE id = %(i)s""", dict(i=person_id))


def _restore(person_id: int) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE person SET roles = '{}', activated = TRUE,
                             admin_deactivated_at = NULL WHERE id = %(i)s""",
                   dict(i=person_id))


_STAFF_OR_TESTER = {
    'a moderator': "UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s",
    'a tester': "UPDATE person SET roles = ARRAY['tester']::TEXT[] WHERE id = %(i)s",
    'an admin': "UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
}

_DEACTIVATED = {
    'a deactivated account': "UPDATE person SET activated = FALSE WHERE id = %(i)s",
    'an account an admin deactivated':
        "UPDATE person SET activated = FALSE, admin_deactivated_at = NOW() WHERE id = %(i)s",
}


@pytest.mark.parametrize('who', sorted(_STAFF_OR_TESTER))
def test_staff_and_testers_count_nowhere(who, make_person):
    """Not in sign-ups, active users or the member total, on either tab."""
    p = make_person(name='SystemPeopleStaffCount')
    with api_tx() as tx:
        tx.execute(_STAFF_OR_TESTER[who], dict(i=p['id']))
    before = _counts()
    _joined_and_online(p['id'])
    assert _counts() == before, f'{who} was counted as a member'

    # The same account as an ordinary member is counted everywhere, so the
    # first half cannot pass merely because the fixture was invisible.
    _restore(p['id'])
    assert _counts() == {k: v + 1 for k, v in before.items()}


@pytest.mark.parametrize('who', sorted(_DEACTIVATED))
def test_a_deactivated_account_stays_a_sign_up_but_is_not_active(who, make_person):
    """The ruling of 11 Nov 2026 (TEC-2144): sign-ups count everyone who
    signed up in the period but staff and testers, deactivated since or not,
    so past figures never change. Active users and the member total leave
    deactivated accounts out."""
    p = make_person(name='SystemPeopleDeactivated')
    with api_tx() as tx:
        # Joined and last seen long ago, so `before` does not count them.
        tx.execute("""UPDATE person
                         SET sign_up_time = (NOW() AT TIME ZONE 'UTC') - INTERVAL '90 days',
                             last_online_time = NOW() - INTERVAL '90 days'
                       WHERE id = %(i)s""", dict(i=p['id']))
        tx.execute(_DEACTIVATED[who], dict(i=p['id']))
    before = _counts()
    _joined_and_online(p['id'])
    after = _counts()
    for k in _SIGN_UPS:
        assert after[k] == before[k] + 1, f'{k}: a deactivated sign-up left the count'
    for k in _ACTIVE:
        assert after[k] == before[k], f'{k}: {who} was counted'

    _restore(p['id'])
    again = _counts()
    for k in _ACTIVE:
        assert again[k] == before[k] + 1, k


def test_the_members_sparkline_ends_at_the_members_card(make_person):
    """The Members card and its sparkline count the same people (reported
    16 Nov 2026; on 23 Nov the line ended at 106 beside a card of 102, as
    it counted moderators, testers, unactivated accounts and test
    addresses). One of each, plus an ordinary member, and the line's last
    point is still the card's figure."""
    for sql in (*_STAFF_OR_TESTER.values(), *_DEACTIVATED.values(), None):
        p = make_person(name='SparkTie')
        _joined_and_online(p['id'])
        if sql:
            with api_tx() as tx:
                tx.execute(sql, dict(i=p['id']))
    c = _counts()
    assert c['members_spark'] == c['member_total']


def test_system_and_overview_count_the_same_people(make_person):
    """Overview's sign-ups today and active in 24 hours are System's sign-ups
    today and DAU: one rule, so the two tabs cannot disagree."""
    for roles in ("'{}'", "ARRAY['mod']", "ARRAY['tester']"):
        p = make_person(name='SystemPeopleTie')
        with api_tx() as tx:
            tx.execute(f'UPDATE person SET roles = {roles}::TEXT[] WHERE id = %(i)s',
                       dict(i=p['id']))
        _joined_and_online(p['id'])
    c = _counts()
    assert c['overview_today'] == c['system_today']
    assert c['overview_active'] == c['dau']


# ---------------------------------------------------------------------------
# Codes never entered count addresses and members, not requests
# ---------------------------------------------------------------------------

def test_a_new_address_that_asks_three_times_and_never_finishes_counts_once(
        client, admin_headers, signup_env):
    email = signup_env.new_email()
    before = _today(client, admin_headers)
    for _ in range(3):
        assert signup_env.request(email).status_code == 200
    after = _today(client, admin_headers)
    assert after['new_requested'] == before['new_requested'] + 3
    assert after['new_never_entered'] == before['new_never_entered'] + 1


def test_a_new_address_that_asks_again_and_enters_the_code_is_not_counted(
        client, admin_headers, signup_env, make_person):
    # The person is made between the two requests, so the first request
    # was from a new address and the second from a member.
    email = signup_env.new_email()
    before = _today(client, admin_headers)
    signup_env.request(email)
    p = make_person(name='SystemPeopleLate', email=email)
    token = signup_env.request(email).get_json()['session_token']
    _enter(client, email, token)
    after = _today(client, admin_headers)
    assert after['new_requested'] == before['new_requested'] + 1
    assert after['new_never_entered'] == before['new_never_entered']
    assert p['id']


def test_a_member_who_asks_twice_and_never_gets_in_counts_once(
        client, admin_headers, signup_env, make_person):
    email = _email(make_person(name='SystemPeopleStuck')['id'])
    before = _today(client, admin_headers)
    signup_env.request(email)
    signup_env.request(email)
    after = _today(client, admin_headers)
    assert after['existing_requested'] == before['existing_requested'] + 2
    assert after['existing_never_entered'] == before['existing_never_entered'] + 1


def test_a_member_who_gets_in_on_the_second_code_is_not_counted(
        client, admin_headers, signup_env, make_person):
    email = _email(make_person(name='SystemPeopleSecond')['id'])
    before = _today(client, admin_headers)
    signup_env.request(email)
    token = signup_env.request(email).get_json()['session_token']
    _enter(client, email, token)
    after = _today(client, admin_headers)
    assert after['existing_never_entered'] == before['existing_never_entered']


@pytest.mark.parametrize('role', ['admin', 'mod', 'tester'])
def test_member_sign_ins_leave_out_staff_and_testers(
        role, client, admin_headers, signup_env, make_person):
    p = make_person(name='SystemPeopleStaff')
    with api_tx() as tx:
        tx.execute('UPDATE person SET roles = ARRAY[%(r)s]::TEXT[] WHERE id = %(i)s',
                   dict(r=role, i=p['id']))
    before = _today(client, admin_headers)
    signup_env.request(_email(p['id']))
    after = _today(client, admin_headers)
    assert after['existing_requested'] == before['existing_requested']
    assert after['existing_never_entered'] == before['existing_never_entered']
    assert after['new_requested'] == before['new_requested']


def test_the_never_finished_bars_add_up_to_the_addresses(client, admin_headers, signup_env):
    """Each address is on one day at most, so the headline, which sums the
    bars, is a count of addresses."""
    with api_tx() as tx:
        rows = tx.execute(
            """SELECT COUNT(*) AS n FROM otp_request
                WHERE flow = 'sign_in' AND refused IS NULL AND new_address
                  AND entered_at IS NULL AND NOT superseded
                  AND requested_at >= NOW() - INTERVAL '31 days'
                  AND (requested_at AT TIME ZONE 'America/Barbados')::date
                      >= (NOW() AT TIME ZONE 'America/Barbados')::date - 29"""
        ).fetchone()
    days = _health(client, admin_headers)['otp_daily']
    assert sum(d['new_never_entered'] for d in days) == rows['n']


# ---------------------------------------------------------------------------
# Not measured is not zero
# ---------------------------------------------------------------------------

def test_days_before_the_first_request_are_not_measured(client, admin_headers, signup_env):
    signup_env.request(signup_env.new_email())
    days = _health(client, admin_headers)['otp_daily']
    with api_tx('read committed') as tx:
        first = tx.execute(
            """SELECT (MIN(requested_at) AT TIME ZONE 'America/Barbados')::date AS d
                 FROM otp_request WHERE flow = 'sign_in'""").fetchone()['d']
    for d in days:
        assert d['measured'] == (d['day'] >= first.isoformat()), d['day']
    assert days[-1]['measured'] is True


# ---------------------------------------------------------------------------
# Refusals: every sign-up refusal recorded, other forms kept apart
# ---------------------------------------------------------------------------

def _reasons(body) -> dict:
    return {r['reason']: r['count'] for r in body['otp_refusals_30d']}


def test_a_turnstile_refusal_is_recorded(client, admin_headers, signup_env, monkeypatch):
    import service.antibot as antibot
    monkeypatch.setattr(antibot, 'verify_turnstile', lambda *a, **k: False)
    before = _health(client, admin_headers)
    r = signup_env.request(signup_env.new_email())
    assert r.status_code == 403
    after = _health(client, admin_headers)
    assert after['otp_daily'][-1]['refused'] == before['otp_daily'][-1]['refused'] + 1
    assert _reasons(after).get('turnstile', 0) == _reasons(before).get('turnstile', 0) + 1
    assert signup_env.sent == []


def test_a_firehol_refusal_is_recorded(client, admin_headers, signup_env, monkeypatch):
    import service.person as person
    monkeypatch.setattr(person, '_ip_blocked', lambda _email: True)
    before = _health(client, admin_headers)
    r = signup_env.request(signup_env.new_email())
    assert r.status_code == 460
    after = _health(client, admin_headers)
    assert after['otp_daily'][-1]['refused'] == before['otp_daily'][-1]['refused'] + 1
    assert _reasons(after).get('firehol', 0) == _reasons(before).get('firehol', 0) + 1


def test_an_unknown_domain_refusal_is_recorded(client, admin_headers, signup_env):
    before = _health(client, admin_headers)
    # On neither the good nor the bad domain list: the 400 path.
    r = signup_env.request(signup_env.new_email(domain='unknown-domain-tec2144.com'))
    assert r.status_code == 400
    after = _health(client, admin_headers)
    assert after['otp_daily'][-1]['refused'] == before['otp_daily'][-1]['refused'] + 1
    assert _reasons(after).get('disposable', 0) == _reasons(before).get('disposable', 0) + 1


@pytest.mark.parametrize('flow', ['event_rsvp', 'visitor_alert', 'tool_invite'])
def test_other_forms_refusals_are_not_sign_up_refusals(flow, client, admin_headers, signup_env):
    from service import signupguard
    before = _health(client, admin_headers)
    signupguard.record_refusal('honeypot', new_address=True,
                               email='other-form@example.com', ip='10.0.0.1', flow=flow)
    try:
        after = _health(client, admin_headers)
        assert after['otp_daily'][-1]['refused'] == before['otp_daily'][-1]['refused']
        assert _reasons(after) == _reasons(before)
        with api_tx('read committed') as tx:
            n = tx.execute('SELECT COUNT(*) AS n FROM otp_request WHERE flow = %(f)s',
                           dict(f=flow)).fetchone()['n']
        assert n >= 1
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM otp_request WHERE flow = %(f)s', dict(f=flow))


def test_an_unknown_flow_is_refused_loudly():
    from service import signupguard
    with pytest.raises(ValueError):
        signupguard.record_refusal('honeypot', new_address=True,
                                   email='x@example.com', ip=None, flow='typo')


# ---------------------------------------------------------------------------
# Codes sent in 24 hours
# ---------------------------------------------------------------------------

def test_codes_sent_counts_each_request_that_sent_a_code(
        client, admin_headers, signup_env):
    email = signup_env.new_email()
    before = _health(client, admin_headers)['otp']['sent_24h']
    signup_env.request(email)
    signup_env.request(email)
    # A refused request sent nothing.
    signup_env.request(signup_env.new_email(), website='https://spam.example')
    assert _health(client, admin_headers)['otp']['sent_24h'] == before + 2


# ---------------------------------------------------------------------------
# Recording a refusal never changes the answer (TEC-2144 review)
# ---------------------------------------------------------------------------

@pytest.fixture
def broken_db_for_counting(monkeypatch):
    """Every database call signupguard makes raises, as an exhausted pool
    would during a flood."""
    import service.signupguard as guard

    def boom(*_a, **_k):
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(guard, 'api_tx', boom)


def test_a_firehol_refusal_is_460_when_counting_fails(
        signup_env, monkeypatch, broken_db_for_counting):
    import service.person as person
    monkeypatch.setattr(person, '_ip_blocked', lambda _email: True)
    assert signup_env.request(signup_env.new_email()).status_code == 460


def test_a_turnstile_refusal_is_403_when_counting_fails(
        signup_env, monkeypatch, broken_db_for_counting):
    import service.antibot as antibot
    monkeypatch.setattr(antibot, 'verify_turnstile', lambda *a, **k: False)
    assert signup_env.request(signup_env.new_email()).status_code == 403


def test_a_honeypot_refusal_is_the_decoy_when_counting_fails(
        signup_env, broken_db_for_counting):
    r = signup_env.request(signup_env.new_email(), website='https://spam.example')
    assert r.status_code == 200 and len(r.get_json()['session_token']) == 128


def test_a_resend_firehol_refusal_is_460_when_counting_fails(
        client, monkeypatch, broken_db_for_counting):
    import service.person as person
    from types import SimpleNamespace
    monkeypatch.setattr(person, '_ip_blocked', lambda _email: True)
    from service.api.decorators import app
    with app.test_request_context('/resend-otp', environ_base={'REMOTE_ADDR': '10.0.0.9'}):
        out = person.post_resend_otp(SimpleNamespace(email='x@example.com'))
    assert out == ('IP address blocked', 460)


def test_a_refusal_is_recorded_in_one_write(signup_env, monkeypatch):
    """The address is looked up inside the write, not in a read before it."""
    import service.signupguard as guard
    calls = []
    real = guard.api_tx

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(guard, 'api_tx', counting)
    import service.antibot as antibot
    monkeypatch.setattr(antibot, 'verify_turnstile', lambda *a, **k: False)
    assert signup_env.request(signup_env.new_email()).status_code == 403
    assert len(calls) == 1
    assert signup_env.refusals()[-1] == 'turnstile'


def test_no_client_address_is_not_called_a_blocklist_hit(signup_env):
    r = signup_env.request(signup_env.new_email(), ip='')
    assert r.status_code == 460
    assert signup_env.refusals()[-1] == 'no_address'
