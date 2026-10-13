"""E1's links go through /s/ campaign links, so the funnel between the
email and the confirm page can be counted (finding 90). The consent record
is still written only by the confirm POST."""
from database import api_tx
from emails.send_spotlight_announcement import build_for
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


def test_the_confirm_and_settings_links_are_campaign_links(make_person):
    p, email = _member(make_person, 'Tracked')
    _subject, html = build_for(dict(person_id=p['id'], email=email, name='Tracked'))
    links = _links(p['id'])
    targets = sorted(l['target_url'] for l in links)
    assert len(links) == 2
    assert targets[0] == f"{WEB_BASE_URL}/settings/privacy"
    assert targets[1].startswith(f"{WEB_BASE_URL}/spotlight/confirm/")
    for l in links:
        assert f"/s/{l['key']}" in html
    assert '/spotlight/confirm/' not in html, 'the bare confirm link is still in the email'
    with api_tx('read committed') as tx:
        assert not tx.execute("SELECT spotlight_opt_in FROM person WHERE id = %(p)s",
                              dict(p=p['id'])).fetchone()['spotlight_opt_in']


def test_a_dry_run_stores_no_link(make_person):
    p, email = _member(make_person, 'DryTracked')
    _subject, html = build_for(dict(person_id=p['id'], email=email, name='DryTracked', dry_run=True))
    assert _links(p['id']) == []
    assert '/s/dry-run' in html
