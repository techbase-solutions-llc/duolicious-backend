"""The two Cohorts charts arrive as no rows when nothing happened, as the
Overview's do, so the admin's empty state can show (TEC-1845 admin audit,
Minor 30). Both are generate_series of days, so they always held 30 and 7
rows and `length === 0` never happened."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='CohortsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


_ZERO_VELOCITY = """SELECT d::text AS day, 0 AS waitlist, 0 AS beta, 0 AS person
                      FROM generate_series(1, 30) d"""
_ZERO_CLICKS = """SELECT d::text AS day, 0 AS mobile, 0 AS desktop, 0 AS bot
                    FROM generate_series(1, 7) d"""


def test_a_chart_with_nothing_in_it_arrives_empty(client, admin_headers, monkeypatch):
    import service.api.admin.cohorts_routes as cr
    monkeypatch.setattr(cr, 'Q_WAITLIST_VELOCITY_30D', _ZERO_VELOCITY)
    monkeypatch.setattr(cr, 'Q_REFERRALS_CLICK_STREAM_7D', _ZERO_CLICKS)
    assert client.get('/admin/cohorts/waitlist', headers=admin_headers).get_json()['velocity_30d'] == []
    assert client.get('/admin/cohorts/referrals', headers=admin_headers).get_json()['click_stream_7d'] == []


def test_a_chart_with_one_value_keeps_every_day(client, admin_headers, monkeypatch):
    import service.api.admin.cohorts_routes as cr
    monkeypatch.setattr(cr, 'Q_REFERRALS_CLICK_STREAM_7D',
                        _ZERO_CLICKS.replace('0 AS bot', 'CASE WHEN d = 3 THEN 1 ELSE 0 END AS bot'))
    assert len(client.get('/admin/cohorts/referrals', headers=admin_headers)
               .get_json()['click_stream_7d']) == 7
