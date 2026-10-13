"""Other members' photos are approved photos only, on every surface (health
review, 13 Oct 2026, finding 92).

The Views list took a member's lowest-position photo whatever its
moderation state, so a rejected, held or still-unchecked photo could be the
picture beside their name in someone else's Views tab. Three other picks
did the same: the inbox rows (/inbox-info), the chat header
(/conversation-prospect) and the new-message push. Every pick now skips a
photo that is not approved and falls through to the next approved one, or
to none.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service.chat import Q_IMMEDIATE_CHAT_DATA


@pytest.fixture
def pair(make_person, sign_in):
    viewer = make_person(name='ViewsViewer', gender='Man')
    other = make_person(name='ViewsOther', gender='Woman')
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = TRUE WHERE id = ANY(%(i)s)",
                   dict(i=[viewer['id'], other['id']]))
    return dict(viewer=viewer, other=other, headers=sign_in(viewer))


def _visited_me(viewer_id, visitor_id):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
               VALUES (%(s)s, %(o)s, NOW(), FALSE)""",
            dict(s=visitor_id, o=viewer_id))


def _messaged(a, b):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO messaged (subject_person_id, object_person_id)
               VALUES (%(a)s, %(b)s), (%(b)s, %(a)s) ON CONFLICT DO NOTHING""",
            dict(a=a, b=b))


def _matched(a, b):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id)
               VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))""",
            dict(a=a, b=b))


def _visitor_row(client, headers, uuid):
    r = client.get('/visitors', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    rows = [v for v in r.get_json()['visited_you'] if v['person_uuid'] == uuid]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize('status', ['rejected', 'manual_review', 'pending'])
def test_views_skips_a_photo_that_is_not_approved(client, pair, add_photo, status):
    add_photo(pair['other']['id'], position=1, status=status)
    approved = add_photo(pair['other']['id'], position=2)
    _visited_me(pair['viewer']['id'], pair['other']['id'])

    row = _visitor_row(client, pair['headers'], pair['other']['uuid'])
    assert row['photo_uuid'] == approved
    assert row['photo_blurhash'] == f'blur-{approved[:8]}'


def test_views_shows_no_photo_when_none_is_approved(client, pair, add_photo):
    add_photo(pair['other']['id'], position=1, status='rejected')
    _visited_me(pair['viewer']['id'], pair['other']['id'])

    row = _visitor_row(client, pair['headers'], pair['other']['uuid'])
    assert row['photo_uuid'] is None and row['photo_blurhash'] is None


def test_the_inbox_row_skips_a_photo_that_is_not_approved(client, pair, add_photo):
    add_photo(pair['other']['id'], position=1, status='rejected')
    approved = add_photo(pair['other']['id'], position=2)
    _messaged(pair['viewer']['id'], pair['other']['id'])

    r = client.post('/inbox-info', json=dict(person_uuids=[pair['other']['uuid']]),
                    headers=pair['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    [row] = [x for x in r.get_json() if str(x['person_uuid']) == pair['other']['uuid']]
    assert row['image_uuid'] == approved
    assert row['image_blurhash'] == f'blur-{approved[:8]}'


def test_the_chat_header_skips_a_photo_that_is_not_approved(client, pair, add_photo):
    add_photo(pair['other']['id'], position=1, status='manual_review')
    approved = add_photo(pair['other']['id'], position=2)
    _matched(pair['viewer']['id'], pair['other']['id'])

    r = client.get(f"/conversation-prospect/{pair['other']['uuid']}", headers=pair['headers'])
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['photo_uuid'] == approved


def test_the_message_push_skips_a_photo_that_is_not_approved(pair, add_photo):
    add_photo(pair['other']['id'], position=1, status='rejected')
    approved = add_photo(pair['other']['id'], position=2)
    with api_tx() as tx:
        tx.execute("UPDATE person SET chats_notification = 1 WHERE id = %(i)s",
                   dict(i=pair['viewer']['id']))
        row = tx.execute(Q_IMMEDIATE_CHAT_DATA,
                         dict(to_id=pair['viewer']['id'],
                              from_id=pair['other']['id'])).fetchone()
    assert row['photo_uuid'] == approved


def test_the_message_push_still_goes_with_no_approved_photo(pair, add_photo):
    add_photo(pair['other']['id'], position=1, status='rejected')
    with api_tx() as tx:
        tx.execute("UPDATE person SET chats_notification = 1 WHERE id = %(i)s",
                   dict(i=pair['viewer']['id']))
        row = tx.execute(Q_IMMEDIATE_CHAT_DATA,
                         dict(to_id=pair['viewer']['id'],
                              from_id=pair['other']['id'])).fetchone()
    assert row is not None and row['name'] == 'ViewsOther'
    assert row['photo_uuid'] is None
