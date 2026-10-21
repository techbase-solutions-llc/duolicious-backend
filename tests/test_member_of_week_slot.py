"""Member of the week refuses an explicit slot that slot_problem refuses
(past, a rest day, or past the read calendar), as brand posts do (TEC-1845
admin audit, Medium). Approval does not check rest days for member kinds, so
such a card came back to review or posted the moment it was approved."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from database import api_tx


def _admin(make_person) -> dict:
    p = make_person(name='GrowthAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _eligible(make_person, name='Miriam Levi'):
    p = make_person(name=name, gender='Woman')
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL
             WHERE id = %(id)s""", dict(id=p['id']))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def test_member_of_the_week_refuses_a_slot_that_has_passed(client, make_person):
    headers = _admin(make_person)
    p = _eligible(make_person)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post('/admin/growth/spotlight/member-of-week',
                    json={'person_id': p['id'], 'scheduled_for': past}, headers=headers)
    assert r.status_code == 409
    assert r.get_json() == {'error': 'slot_unavailable', 'reason': 'past'}
    with api_tx() as tx:
        assert tx.execute("SELECT 1 FROM publishing_queue WHERE subject_person_id = %(p)s",
                          dict(p=p['id'])).fetchone() is None


def test_member_of_the_week_refuses_a_rest_day(client, make_person, monkeypatch):
    import service.spotlight.restdays as rd
    day = (datetime.now(timezone.utc) + timedelta(days=3)).date()
    monkeypatch.setattr(rd, 'REST_DAYS', (day,))
    headers = _admin(make_person)
    p = _eligible(make_person)
    slot = datetime(day.year, day.month, day.day, 16, tzinfo=timezone.utc).isoformat()
    r = client.post('/admin/growth/spotlight/member-of-week',
                    json={'person_id': p['id'], 'scheduled_for': slot}, headers=headers)
    assert r.status_code == 409
    assert r.get_json()['reason'] == 'rest_day'


def test_member_of_the_week_keeps_a_valid_slot(client, make_person):
    headers = _admin(make_person)
    p = _eligible(make_person)
    slot = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    r = client.post('/admin/growth/spotlight/member-of-week',
                    json={'person_id': p['id'], 'scheduled_for': slot.isoformat()}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
