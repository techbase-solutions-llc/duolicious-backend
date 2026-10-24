"""The app_entries switch (TEC-1845, in-app entry plan, section 3 and
release 2): the new in-app entries to Together, gatherings and the
Matchmaker show only while it allows the member. 3 settings in
AHAVAH_APP_ENTRIES: off (the default, and anything unknown), owner (only
the person ids or addresses in AHAVAH_APP_ENTRIES_ALLOW) and on. The web
asks through a member-only request, which never shows the list."""
import pathlib

import pytest

from service import app_entries

ENVS = ('AHAVAH_APP_ENTRIES', 'AHAVAH_APP_ENTRIES_ALLOW')


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for env in ENVS:
        monkeypatch.delenv(env, raising=False)


@pytest.mark.parametrize('env,default', [('AHAVAH_APP_ENTRIES', 'off'), ('AHAVAH_APP_ENTRIES_ALLOW', '')])
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env, default):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-{default}}}') == 2


def test_off_by_default():
    assert app_entries.setting() == 'off'
    assert not app_entries.enabled_for(1, 'owner@ahavah-test.invalid')


@pytest.mark.parametrize('raw,want', [('on', 'on'), (' ON ', 'on'), ('owner', 'owner'), ('Owner', 'owner'),
                                      ('off', 'off'), ('', 'off'), ('1', 'off'), ('yes', 'off'),
                                      ('owner-only', 'off'), ('maybe', 'off')])
def test_only_the_3_settings_count_and_anything_else_is_off(monkeypatch, raw, want):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', raw)
    assert app_entries.setting() == want


def test_on_lets_every_member_in(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    assert app_entries.enabled_for(1, 'a@ahavah-test.invalid')
    assert app_entries.enabled_for(99999, None)


def test_owner_lets_in_only_the_listed_ids_and_addresses(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', ' 126 , Owner.Name+ahavah@Gmail.com,,  bad entry ')
    assert app_entries.enabled_for(126, 'someone@ahavah-test.invalid')
    # Addresses are compared normalised, as person.normalized_email is.
    assert app_entries.enabled_for(5, 'ownername@gmail.com')
    assert app_entries.enabled_for(5, 'OWNER.NAME@gmail.com')
    assert not app_entries.enabled_for(5, 'other@gmail.com')
    assert not app_entries.enabled_for(1260, None)
    assert not app_entries.enabled_for(None, None)


def test_owner_with_no_list_lets_nobody_in(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    assert not app_entries.enabled_for(1, 'a@ahavah-test.invalid')


def test_the_list_counts_only_while_the_setting_is_owner(monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', '7')
    assert not app_entries.enabled_for(7, None)
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    assert app_entries.enabled_for(7, None)


def test_the_status_route_answers_a_member(client, make_person, sign_in, monkeypatch):
    p = make_person(name='Entries')
    headers = sign_in(p)
    r = client.get('/app-entries/status', headers=headers)
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'enabled': False}
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', f"424242424,{p['id']}")
    r = client.get('/app-entries/status', headers=headers)
    assert r.get_json() == {'enabled': True}
    # The list never leaves the API.
    assert '424242424' not in r.get_data(as_text=True)
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', '424242424')
    assert client.get('/app-entries/status', headers=headers).get_json() == {'enabled': False}
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    assert client.get('/app-entries/status', headers=headers).get_json() == {'enabled': True}


def test_the_status_route_is_for_members_only(client, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    # No session (the decorator answers a missing header with 400), and a
    # visitor who confirmed an address but is not a member.
    _, visitor = tool_visitor()
    for headers in ({}, visitor):
        r = client.get('/app-entries/status', headers=headers)
        assert r.status_code in (400, 401, 403)
        assert 'enabled' not in r.get_data(as_text=True)
