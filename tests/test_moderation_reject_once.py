"""Take down on a photo already taken down changes nothing: no second note to
the member, no second audit row, changed false (TEC-1845 admin audit,
Medium). A double click used to email the member twice."""
from __future__ import annotations

import secrets

import service.api.admin.moderation_routes as moderation_routes
from database import api_tx


def _photo(person_id: int, status: str, position: int = 1) -> str:
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
               VALUES (%(u)s, %(p)s, %(n)s, %(s)s, 'testblurhash', gen_random_uuid()::text)""",
            dict(u=uuid, p=person_id, n=position, s=status))
    return uuid


def _audits(action: str, key: str, value: str) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT actor_email, target_email, target_uuid::text AS target_uuid, metadata
                 FROM admin_audit_log WHERE action = %(a)s AND metadata->>%(k)s = %(v)s""",
            dict(a=action, k=key, v=value)).fetchall()]


def _clean_audits(action: str, key: str, value: str) -> None:
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_audit_log WHERE action = %(a)s AND metadata->>%(k)s = %(v)s",
                   dict(a=action, k=key, v=value))


def test_a_second_take_down_sends_no_second_note(client, make_person, admin_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(moderation_routes, 'send_photo_removed',
                        lambda *a, **k: sent.append(a) or True)
    p = make_person(name='Twice')
    uuid = _photo(p['id'], 'pending')
    try:
        first = client.post(f'/admin/moderation/photos/{uuid}/reject', headers=admin_headers)
        second = client.post(f'/admin/moderation/photos/{uuid}/reject', headers=admin_headers)
        assert first.status_code == second.status_code == 200
        assert first.get_json()['notified'] is True
        assert second.get_json() == {'ok': True, 'notified': False, 'changed': False}
        assert len(sent) == 1
        assert len(_audits('reject_photo', 'photo_uuid', uuid)) == 1
    finally:
        _clean_audits('reject_photo', 'photo_uuid', uuid)


def test_take_down_of_a_missing_photo_is_still_404(client, admin_headers):
    r = client.post(f'/admin/moderation/photos/{secrets.token_hex(32)}/reject', headers=admin_headers)
    assert r.status_code == 404
