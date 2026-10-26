"""GET and PUT /discover-filters: a member's Discover filters (TEC-1845).

Owner, 25 Oct: "my filters dont work or stay persistent". The web app kept
the filters only in the browser and removed them at sign-out, so a member
who signed in again or used another device found them gone. They are now
kept with the account: what one session saves, any later session reads.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from database import api_tx


@pytest.fixture(scope='module', autouse=True)
def discover_filters_schema():
    # Migration 0078 is idempotent, so applying it here is what the deploy does.
    path = Path(__file__).resolve().parent.parent / 'migrations' / '0078_discover_filters.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


SAVED = {
    'ageMin': 28,
    'ageMax': 40,
    'assemblies': ['messianic', 'torah-observant'],
    'torahLevels': ['experienced'],
    'maritalStatuses': ['never-married'],
    'hasChildrenBuckets': ['none'],
    'country': ['BB', 'JM'],
    'verifiedOnly': True,
}


def test_nothing_saved_reads_as_null(client, make_person, sign_in):
    r = client.get('/discover-filters', headers=sign_in(make_person(name='DfNone')))
    assert r.status_code == 200
    assert r.get_json() == {'filters': None}
    assert r.headers['Cache-Control'] == 'no-store'


def test_another_session_reads_what_one_saved(client, make_person, sign_in):
    member = make_person(name='DfSaved')
    phone = sign_in(member)
    r = client.put('/discover-filters', headers=phone, json={'filters': SAVED})
    assert r.status_code == 200
    assert r.get_json() == {'filters': SAVED}

    # Signed in again, or on another device: a new session, same account.
    laptop = sign_in(member)
    r = client.get('/discover-filters', headers=laptop)
    assert r.get_json() == {'filters': SAVED}

    # Reset all: the next save replaces the whole set.
    r = client.put('/discover-filters', headers=laptop, json={'filters': {'verifiedOnly': False}})
    assert r.get_json() == {'filters': {}}
    assert client.get('/discover-filters', headers=phone).get_json() == {'filters': {}}


def test_a_member_reads_only_their_own(client, make_person, sign_in):
    a = sign_in(make_person(name='DfA'))
    b = sign_in(make_person(name='DfB'))
    client.put('/discover-filters', headers=a, json={'filters': {'calendars': ['enoch']}})
    assert client.get('/discover-filters', headers=b).get_json() == {'filters': None}


def test_kept_tidy(client, make_person, sign_in):
    headers = sign_in(make_person(name='DfTidy'))
    r = client.put('/discover-filters', headers=headers, json={'filters': {
        'assemblies': ['messianic', 'messianic'],
        'intents': [],
        'mapLens': False,
        'somethingNewer': ['x'],
    }})
    assert r.status_code == 200
    assert r.get_json() == {'filters': {'assemblies': ['messianic']}}


@pytest.mark.parametrize('filters, field', [
    ({'ageMin': 17}, 'ageMin'),
    ({'ageMax': 81}, 'ageMax'),
    ({'ageMin': 40, 'ageMax': 30}, 'ageMin'),
    ({'ageMin': True}, 'ageMin'),
    ({'assemblies': 'messianic'}, 'assemblies'),
    ({'assemblies': ['<script>']}, 'assemblies'),
    ({'country': ['BB'] * 301}, 'country'),
    ({'verifiedOnly': 'yes'}, 'verifiedOnly'),
])
def test_refuses_what_the_sheet_cannot_send(client, make_person, sign_in, filters, field):
    headers = sign_in(make_person(name='DfBad'))
    r = client.put('/discover-filters', headers=headers, json={'filters': filters})
    assert r.status_code == 400
    assert r.get_json() == {'error': 'bad_filters', 'field': field}
    assert client.get('/discover-filters', headers=headers).get_json() == {'filters': None}


def test_signed_out_is_refused(client):
    # The auth decorator answers 400 with no bearer and 401 with a dead one.
    assert client.get('/discover-filters').status_code == 400
    assert client.put('/discover-filters', json={'filters': {}}).status_code == 400
    dead = {'Authorization': 'Bearer ' + '0' * 64}
    assert client.get('/discover-filters', headers=dead).status_code == 401
    assert client.put('/discover-filters', headers=dead, json={'filters': {}}).status_code == 401


def test_the_row_goes_with_the_member(client, make_person, sign_in):
    member = make_person(name='DfGone')
    client.put('/discover-filters', headers=sign_in(member), json={'filters': {'calendars': ['enoch']}})
    with api_tx() as tx:
        tx.execute('DELETE FROM person WHERE id = %(p)s', dict(p=member['id']))
        left = tx.execute('SELECT 1 FROM discover_filters WHERE person_id = %(p)s',
                          dict(p=member['id'])).fetchone()
    assert left is None
