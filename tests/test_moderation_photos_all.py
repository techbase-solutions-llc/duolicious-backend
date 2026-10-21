"""Moderation > Photos: state=all lists every status (TEC-1845 admin audit,
Medium). An empty state is read as pending, so the admin had no way to ask."""
from __future__ import annotations

import secrets

from database import api_tx


def _photo(person_id: int, status: str, position: int = 1) -> str:
    uuid = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
               VALUES (%(u)s, %(p)s, %(n)s, %(s)s, 'testblurhash', gen_random_uuid()::text)""",
            dict(u=uuid, p=person_id, n=position, s=status))
    return uuid


def test_state_all_lists_every_status(make_person):
    from service.admin.queries import Q_PHOTOS_LIST
    assert 'LIMIT 100' in Q_PHOTOS_LIST
    unlimited = Q_PHOTOS_LIST.replace('LIMIT 100', 'LIMIT 1000000')
    p = make_person(name='Photos')
    approved, rejected = _photo(p['id'], 'approved'), _photo(p['id'], 'rejected', 2)
    with api_tx() as tx:
        listed = {r['photo_uuid'] for r in tx.execute(unlimited, dict(state='all')).fetchall()}
    assert {approved, rejected} <= listed
