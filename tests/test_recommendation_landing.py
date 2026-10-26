"""The recommended single's landing page (TEC-1845; ahavah-web "Ahavah
In-app Entry Round 2.html" screen 12; the in-app entry plan, section 7,
release 3). The email links to a short page that names who recommended
them, by first name, and shows their note, in place of the sign-up form.
Behind the Matchmaker's introductions and app_entries for the sender."""
from __future__ import annotations

import re
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live', 'mail_allowed', 'no_limits')


@pytest.fixture
def addresses():
    made: list[str] = []

    def _new() -> str:
        a = f'single-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(a)
        return a

    yield _new
    from service.matchmaker import address_key
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE recipient_key = ANY(%(k)s)',
                   dict(k=[address_key(a) for a in made]))


@pytest.fixture
def sender(make_person, sign_in):
    def _make(name: str = 'Hannah Levi') -> dict:
        email = f'hannah-{uuid4().hex[:8]}@ahavah-test.invalid'
        p = make_person(name=name, email=email)
        return dict(p, email=email, headers=sign_in(p))
    return _make


def _html(outbox_rows, email) -> str:
    [row] = [r for r in outbox_rows('mm_recommend') if r['email'] == email]
    return row['payload']['html']


def _token(html: str) -> str:
    m = re.search(r'/recommended/([A-Za-z0-9_-]+)', html)
    assert m, 'no landing link'
    return m.group(1)


def test_the_email_links_to_the_landing_page_with_the_note(client, sender, addresses, outbox_rows,
                                                         monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    me, single = sender(), addresses()
    client.post('/recommendations', headers=me['headers'], json=dict(email=single, note='You keep the feasts.'))
    html = _html(outbox_rows, single)
    assert '/i/' not in html
    r = client.get(f'/recommendations/landing/{_token(html)}')
    assert r.status_code == 200
    body = r.get_json()
    assert body['first_name'] == 'Hannah' and body['note'] == 'You keep the feasts.'
    assert isinstance(body['code'], str) and len(body['code']) == 7
    assert r.headers['Cache-Control'] == 'no-store'


def test_the_default_note_is_no_note(client, sender, addresses, outbox_rows, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    me, single = sender(), addresses()
    client.post('/recommendations', headers=me['headers'], json=dict(email=single))
    body = client.get(f'/recommendations/landing/{_token(_html(outbox_rows, single))}').get_json()
    assert body['note'] is None and body['first_name'] == 'Hannah'


def test_a_visitor_sender_has_no_code(client, addresses, outbox_rows, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    _, headers = tool_visitor()
    single = addresses()
    r = client.post('/recommendations', headers=headers, json=dict(email=single, first_name='Miriam'))
    assert r.status_code == 201
    body = client.get(f'/recommendations/landing/{_token(_html(outbox_rows, single))}').get_json()
    assert body['first_name'] == 'Miriam' and body['code'] is None


def test_while_app_entries_leaves_the_sender_out_the_email_keeps_its_old_link(client, sender, addresses,
                                                                              outbox_rows, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'owner')
    monkeypatch.setenv('AHAVAH_APP_ENTRIES_ALLOW', 'someone-else@ahavah-test.invalid')
    me, single = sender(), addresses()
    client.post('/recommendations', headers=me['headers'], json=dict(email=single))
    html = _html(outbox_rows, single)
    assert '/i/' in html and '/recommended/' not in html


def test_an_unknown_token_or_introductions_off_answers_not_found(client, sender, addresses, outbox_rows,
                                                                monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    assert client.get('/recommendations/landing/' + 'x' * 43).status_code == 404
    me, single = sender(), addresses()
    client.post('/recommendations', headers=me['headers'], json=dict(email=single))
    token = _token(_html(outbox_rows, single))
    monkeypatch.delenv('AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED')
    assert client.get(f'/recommendations/landing/{token}').status_code == 404


def test_an_erased_recommendation_answers_not_found(client, sender, addresses, outbox_rows, monkeypatch):
    monkeypatch.setenv('AHAVAH_APP_ENTRIES', 'on')
    me, single = sender(), addresses()
    client.post('/recommendations', headers=me['headers'], json=dict(email=single))
    token = _token(_html(outbox_rows, single))
    from service.matchmaker import address_key
    with api_tx() as tx:
        tx.execute('UPDATE recommendation SET erased_at = NOW() WHERE recipient_key = %(k)s',
                   dict(k=address_key(single)))
    assert client.get(f'/recommendations/landing/{token}').status_code == 404
