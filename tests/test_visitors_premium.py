"""Who viewed you is Premium on the server too (TEC-2070, 11 Nov 2026).

GET /visitors returned every visitor's name, uuid and photo to free
members; only the web blurred them. A member without the 'premium'
entitlement now gets each "Viewed you" row as a placeholder: the visit's
time, whether it is new and an opaque row key, and no name, age, place,
photo, blurhash or person uuid. The count of rows is the same,
so the locked card still says how many people looked. "You viewed" (the
member's own trail) and Premium members are unchanged.
"""
from __future__ import annotations

import pytest

from database import api_tx


@pytest.fixture
def seen(make_person, add_photo, sign_in):
    me = make_person(name='VisMe', gender='Woman')
    visitor = make_person(name='VisVisitor', gender='Man')
    viewed = make_person(name='VisViewed', gender='Man')
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)',
                   dict(i=[me['id'], visitor['id'], viewed['id']]))
        for a, b in ((visitor, me), (me, viewed)):
            tx.execute("""INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
                          VALUES (%(a)s, %(b)s, NOW(), FALSE)""", dict(a=a['id'], b=b['id']))
    add_photo(visitor['id'])
    add_photo(viewed['id'])
    return me, visitor, viewed, sign_in(me)


def _visitors(client, h):
    r = client.get('/visitors', headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_a_free_member_gets_placeholders_for_who_viewed_them(client, seen):
    me, visitor, viewed, h = seen
    body = _visitors(client, h)
    [row] = body['visited_you']
    assert row['person_uuid'] != visitor['uuid']
    assert (row['name'], row['age'], row['location'], row['photo_uuid'], row['gender']) == \
        (None, None, None, None, None)
    assert row['is_new'] is True and row['time']
    # The blurhash is drawn from the visitor's own photo; the web's locked
    # card does not read it, so it stays on the server too.
    assert row['photo_blurhash'] is None
    assert visitor['uuid'] not in str(body)
    assert 'VisVisitor' not in str(body)
    # Their own trail is theirs to see.
    [mine] = body['you_visited']
    assert (mine['person_uuid'], mine['name']) == (viewed['uuid'], 'VisViewed')


def test_a_premium_member_sees_who_viewed_them(client, seen):
    me, visitor, _viewed, h = seen
    with api_tx() as tx:
        tx.execute("UPDATE person SET entitlements = ARRAY['premium'] WHERE id = %(i)s",
                   dict(i=me['id']))
    [row] = _visitors(client, h)['visited_you']
    assert (row['person_uuid'], row['name']) == (visitor['uuid'], 'VisVisitor')
    assert row['photo_uuid']
