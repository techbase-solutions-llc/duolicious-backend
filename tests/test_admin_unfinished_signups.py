"""Unfinished sign-ups (TEC-1897; frames U.1 to U.4): when they started, when
they last saved and the furthest step the server recorded. No address."""
from __future__ import annotations

from collections import Counter
from datetime import date
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from database import api_tx


@pytest.fixture
def onboardee():
    made: list[str] = []

    def _make(*, idle_hours: float = 3, lead_source=None, email=None, **fields) -> str:
        email = email or f'unfinished-{uuid4().hex[:10]}@example.com'
        cols = dict(email=email, lead_source=lead_source, **fields)
        names = ', '.join(cols)
        values = ', '.join(f'%({k})s' for k in cols)
        with api_tx() as tx:
            tx.execute(f"INSERT INTO onboardee ({names}) VALUES ({values})", cols)
            # make_interval's `hours` takes an integer only; `secs` takes the
            # fractional idle times the tests use (0.2 hours).
            tx.execute("""UPDATE onboardee SET created_at = NOW() - make_interval(secs => %(h)s * 7200),
                                               updated_at = NOW() - make_interval(secs => %(h)s * 3600)
                           WHERE email = %(e)s""", dict(h=idle_hours, e=email))
        made.append(email)
        return email

    yield _make
    with api_tx() as tx:
        tx.execute("DELETE FROM onboardee WHERE email = ANY(%(e)s)", dict(e=made))


def _rows(client, headers) -> dict:
    r = client.get('/admin/community/unfinished', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _steps(body) -> Counter:
    """The shared database holds other rows, so tests compare step counts
    before and after rather than reading positions."""
    return Counter(r['furthest_step'] for r in body['rows'])


def test_admins_only(client, make_person, sign_in):
    assert client.get('/admin/community/unfinished',
                      headers=sign_in(make_person(name='UfMember'))).status_code == 403


def test_a_stalled_sign_up_is_listed_with_its_furthest_step(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)
    onboardee(name='Rivka', date_of_birth=date(1990, 1, 1))
    body = _rows(client, admin_bearer)
    assert body['count'] - before['count'] == 1
    assert _steps(body) - _steps(before) == Counter({'date_of_birth': 1})
    assert all(r['started_at'].endswith('+00:00') for r in body['rows'])
    assert 'example.com' not in str(body) and 'Rivka' not in str(body)


def test_steps_follow_the_sign_up_order(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)
    onboardee(name='A', gender_id=1, ahavah_extra=Jsonb({'assembly': ['x']}))
    onboardee()
    after = _rows(client, admin_bearer)
    assert _steps(after) - _steps(before) == Counter({'assembly': 1, 'none': 1})


def test_someone_still_signing_up_is_not_listed(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)['count']
    onboardee(idle_hours=0.2, name='Busy')
    assert _rows(client, admin_bearer)['count'] == before


def test_a_tool_visitor_who_saved_no_step_is_not_listed(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)['count']
    onboardee(lead_source='tool:game-us')
    assert _rows(client, admin_bearer)['count'] == before
    onboardee(lead_source='tool:checklist', name='Started anyway')
    assert _rows(client, admin_bearer)['count'] == before + 1


def test_staff_addresses_and_finished_members_are_not_listed(client, admin_bearer, onboardee, make_person):
    before = _rows(client, admin_bearer)['count']
    try:
        onboardee(email='admin@techbaseltd.com', name='Staff')
    except Exception:  # a real row for the staff address already exists
        pytest.skip('an onboardee row exists for the staff address')
    member = make_person(name='Finished')
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=member['id'])).fetchone()['email']
    onboardee(email=email, name='Finished')
    assert _rows(client, admin_bearer)['count'] == before


def test_the_reminder_date_and_switch_are_listed_and_name_nobody(client, admin_bearer, onboardee, monkeypatch):
    """TEC-2107: each row carries reminded_at (when the reminder was accepted
    for sending, else null) and the response says whether the reminder is
    on. Still no address and no name."""
    monkeypatch.delenv('AHAVAH_UNFINISHED_SIGNUP_REMINDER_ENABLED', raising=False)
    before = _rows(client, admin_bearer)
    assert before['reminder_on'] is False
    reminded = onboardee(idle_hours=30, name='Reminded')
    onboardee(idle_hours=30, name='NotYet')
    with api_tx() as tx:
        tx.execute("""INSERT INTO lead_email_send (email, campaign, message_id, claimed_at, sent_at)
                      VALUES (%(e)s, 'unfinished_signup', 'mid-admin', NOW() - interval '2 hours',
                              NOW() - interval '2 hours')""", dict(e=reminded.lower()))
    try:
        monkeypatch.setenv('AHAVAH_UNFINISHED_SIGNUP_REMINDER_ENABLED', '1')
        body = _rows(client, admin_bearer)
        assert body['reminder_on'] is True
        assert body['count'] - before['count'] == 2
        assert all('reminded_at' in r for r in body['rows'])
        sent = sum(1 for r in body['rows'] if r['reminded_at'])
        assert sent - sum(1 for r in before['rows'] if r['reminded_at']) == 1
        assert all(r['reminded_at'] is None or r['reminded_at'].endswith('+00:00') for r in body['rows'])
        text = str(body)
        assert reminded not in text and 'example.com' not in text
        assert 'Reminded' not in text and 'NotYet' not in text and 'mid-admin' not in text
        assert set(body) == {'count', 'rows', 'reminder_on'}
        assert set(body['rows'][0]) == {'started_at', 'last_saved_at', 'furthest_step', 'reminded_at'}
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM lead_email_send WHERE email = %(e)s", dict(e=reminded.lower()))
