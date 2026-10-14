"""E1's settings link goes through a /s/ campaign link, so its clicks are
counted (finding 90). The confirm link carries a live single-use token, so
it goes straight to the confirm page and is never stored as a campaign
link's target (review of Wave 3, 14 Oct 2026). The consent record is still
written only by the confirm POST."""
import re

import pytest

from database import api_tx
from emails.send_spotlight_announcement import build_for
from emails.send_spotlight_resend import build_for as resend_build_for
from service.config import WEB_BASE_URL


def _member(make_person, name):
    p = make_person(name=name)
    email = f"{name.lower()}-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(e=email, i=p['id']))
    return p, email


def _links(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT key, kind, target_url FROM campaign_link WHERE subject_person_id = %(p)s AND kind = 'e1'",
            dict(p=pid)).fetchall()]


def test_the_settings_link_is_counted_and_the_confirm_link_goes_direct(make_person):
    p, email = _member(make_person, 'Tracked')
    _subject, html = build_for(dict(person_id=p['id'], email=email, name='Tracked'))
    links = _links(p['id'])
    assert [l['target_url'] for l in links] == [f"{WEB_BASE_URL}/settings/privacy"]
    assert f"/s/{links[0]['key']}" in html
    assert f'href="{WEB_BASE_URL}/spotlight/confirm/' in html
    with api_tx('read committed') as tx:
        assert not tx.execute("SELECT spotlight_opt_in FROM person WHERE id = %(p)s",
                              dict(p=p['id'])).fetchone()['spotlight_opt_in']


def _confirm_token(html):
    m = re.search(r'href="[^"]*/spotlight/confirm/([^"]+)"', html)
    assert m, 'no confirm link in the email'
    return m.group(1)


@pytest.mark.parametrize('builder', [build_for, resend_build_for], ids=['e1', 'e1_resend'])
def test_no_campaign_link_holds_a_confirm_token(make_person, builder):
    """/s/ stores its target in campaign_link.target_url in plain text, and
    the confirm token is live and single use: whoever reads that table could
    opt the member in."""
    p, email = _member(make_person, 'NoTokenStored')
    _subject, html = builder(dict(person_id=p['id'], email=email, name='x'))
    token = _confirm_token(html)
    with api_tx('read committed') as tx:
        assert tx.execute(
            """SELECT count(*) AS n FROM campaign_link
                WHERE subject_person_id = %(p)s AND target_url LIKE '%%/spotlight/confirm/%%'""",
            dict(p=p['id'])).fetchone()['n'] == 0
        assert tx.execute("SELECT count(*) AS n FROM campaign_link WHERE strpos(target_url, %(t)s) > 0",
                          dict(t=token)).fetchone()['n'] == 0


def test_a_dry_run_stores_no_link(make_person):
    p, email = _member(make_person, 'DryTracked')
    _subject, html = build_for(dict(person_id=p['id'], email=email, name='DryTracked', dry_run=True))
    assert _links(p['id']) == []
    assert '/s/dry-run' in html
