"""The matchmaker pairs a man and a woman only (TEC-2039, 11 Nov 2026).

Introductions and the alert counts read a member with no saved gender
preference as open to both genders, so an introducer could be offered two
women, a suggestion of two men went out, the map reach counted the
introducer's own gender, and an alert counted members of the owner's own
gender. "No preference" means the gender opposite the member's own; a
visitor whose alert names no gender counts nobody.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

NOTE = 'Both of you love the feasts and want a big family.'


def _candidates(client, h, who):
    r = client.get(f"/introductions/candidates?for={who['uuid']}", headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {p['uuid'] for p in r.get_json()['people']}


def test_the_picker_offers_only_the_other_gender_to_someone_with_no_preference(
        client, introducer_with_two):
    h, _miriam, daniel, hannah = introducer_with_two()
    leah = introducer_with_two.member('Leah', 'Woman', None)
    ruth = introducer_with_two.member('Ruth', 'Woman', None)
    introducer_with_two.match(hannah, leah)
    introducer_with_two.match(hannah, ruth)
    offered = _candidates(client, h, leah)
    assert ruth['uuid'] not in offered
    assert daniel['uuid'] in offered


def test_two_women_with_no_preference_are_never_introduced(client, introducer_with_two):
    h, _miriam, _daniel, hannah = introducer_with_two()
    leah = introducer_with_two.member('Leah', 'Woman', None)
    ruth = introducer_with_two.member('Ruth', 'Woman', None)
    introducer_with_two.match(hannah, leah)
    introducer_with_two.match(hannah, ruth)
    r = client.post('/introductions', headers=h,
                    json=dict(a_uuid=leah['uuid'], b_uuid=ruth['uuid'], note=NOTE))
    # Answered as a send, so the introducer learns nothing, but kept hidden.
    assert r.status_code == 201 and r.get_json()['state'] == 'sent'
    with api_tx() as tx:
        row = tx.execute('SELECT status, flag_reason FROM introduction WHERE introducer_person_id = %(i)s',
                         dict(i=hannah['id'])).fetchone()
    assert (row['status'], row['flag_reason']) == ('rejected', 'hidden')


def test_the_map_reach_is_the_introducers_other_gender(client, introducer_with_two):
    h, _miriam, daniel, hannah = introducer_with_two()
    with api_tx() as tx:
        tx.execute('DELETE FROM search_preference_gender WHERE person_id = %(i)s', dict(i=hannah['id']))
    on_map = introducer_with_two.member('Mapped', 'Woman', None)
    with api_tx() as tx:
        tx.execute('INSERT INTO visited (subject_person_id, object_person_id) VALUES (%(a)s, %(b)s)',
                   dict(a=hannah['id'], b=on_map['id']))
        tx.execute("""UPDATE person SET show_my_location = TRUE,
                             ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || '{"citySet": true}'::jsonb
                       WHERE id = %(i)s""", dict(i=on_map['id']))
    assert on_map['uuid'] not in _candidates(client, h, daniel)


def _count(owner_id, gender_ids):
    from service.matchmaker.notices import _count as count
    now = datetime.now(timezone.utc)
    with api_tx() as tx:
        return count(tx, {}, gender_ids=gender_ids, since=now - timedelta(hours=1),
                     until=now + timedelta(minutes=1), owner_id=owner_id)


def test_an_alert_with_no_preference_counts_only_the_other_gender(introducer_with_two):
    owner = introducer_with_two.member('Owner', 'Man', None)
    before = _count(owner['id'], [])
    introducer_with_two.member('NewMan', 'Man', None)
    assert _count(owner['id'], []) == before
    introducer_with_two.member('NewWoman', 'Woman', None)
    assert _count(owner['id'], []) == before + 1


def test_a_visitor_alert_with_no_gender_counts_nobody(introducer_with_two):
    introducer_with_two.member('NewWoman', 'Woman', None)
    assert _count(None, []) == 0
