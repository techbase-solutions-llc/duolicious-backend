"""The first of the two members (TEC-1845; in-app entry plan, release 3;
round 2, screen 13, "Choose 2 members"): everyone the introducer can
already see, by first name, never anyone else. The second is chosen with
/introductions/candidates, as from a profile."""
import pytest

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')


def test_lists_everyone_the_introducer_can_already_see(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    stranger = introducer_with_two.member('Stranger', 'Man', 'Woman')
    r = client.get('/introductions/people', headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    people = {p['uuid']: p for p in body['people']}
    assert set(people) == {miriam['uuid'], daniel['uuid']}
    assert people[daniel['uuid']]['first_name'] == 'Daniel' and people[daniel['uuid']]['reach'] == 'match'
    assert people[daniel['uuid']]['reach_label'] == 'Your match'
    assert stranger['uuid'] not in people and hannah['uuid'] not in people
    assert body['left'] == 5


def test_finds_by_first_name(client, introducer_with_two):
    h, miriam, _daniel, _ = introducer_with_two()
    people = client.get('/introductions/people?q=Mir', headers=h).get_json()['people']
    assert [p['uuid'] for p in people] == [miriam['uuid']]


def test_is_not_found_while_introductions_are_off(client, introducer_with_two, monkeypatch):
    h, *_ = introducer_with_two()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED')
    assert client.get('/introductions/people', headers=h).status_code == 404
