"""A dry run builds every message and writes nothing (health review, 13 Oct
2026, finding 15).

Building a campaign message mints what the real email would carry: a
campaign_link row per CTA for e2, e3 and e6, and a single-use Spotlight
nonce for e1. A dry run built every message, so it wrote all of those for
mail that was never sent. It still builds every message, so a template
that raises is still reported, but the links and nonces it builds are
placeholders that are never stored."""
from __future__ import annotations

import uuid

import pytest

from database import api_tx
import emails.send_community_weekly as e2
import emails.send_notifications_nudge as e6
import emails.send_reinvite as e3
import emails.send_spotlight_announcement as e1
from service.campaigns.runner import run_campaign


def _sendable(person_id: int) -> str:
    """make_person's @example.com address is suppressed, and the runner skips
    a suppressed address before building; this one is not."""
    email = f'dry-{person_id}@ahavah-test.invalid'
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(e=email, i=person_id))
    return email


def _links(person_id: int) -> int:
    with api_tx('read committed') as tx:
        return tx.execute("SELECT count(*) AS n FROM campaign_link WHERE subject_person_id = %(p)s",
                          dict(p=person_id)).fetchone()['n']


def _nonces(person_id: int) -> int:
    with api_tx('read committed') as tx:
        return tx.execute("SELECT count(*) AS n FROM spotlight_token_nonce WHERE person_id = %(p)s",
                          dict(p=person_id)).fetchone()['n']


def _dry_run(mod, key, row):
    return run_campaign(api_tx, key, f'{key}-dry-{uuid.uuid4().hex[:8]}', [row], mod.build_for,
                        send=False, from_addr=mod.FROM_ADDR, unsub_scope=mod.UNSUB_SCOPE,
                        cap_days=getattr(mod, 'CAP_DAYS', 7))


@pytest.mark.parametrize('mod,key', [(e2, 'e2'), (e3, 'e3'), (e6, 'e6')])
def test_a_dry_run_mints_no_campaign_link(make_person, mod, key):
    p = make_person(name='DryLinks')
    email = _sendable(p['id'])
    row = dict(mod.preview_row(email), person_id=p['id'], name='DryLinks')

    res = _dry_run(mod, key, row)

    assert res['built'] == 1 and res['queued'] == 0 and res['error'] is None
    assert _links(p['id']) == 0
    # The same build outside a dry run does mint, so the count above can see
    # a link when there is one.
    mod.build_for(row)
    assert _links(p['id']) >= 1


def test_a_dry_run_of_the_spotlight_invite_mints_no_nonce(make_person):
    p = make_person(name='DryNonce')
    email = _sendable(p['id'])
    row = dict(person_id=p['id'], email=email, name='DryNonce')

    res = _dry_run(e1, 'e1', row)

    assert res['built'] == 1 and res['queued'] == 0 and res['error'] is None
    assert _nonces(p['id']) == 0
    e1.build_for(row)
    assert _nonces(p['id']) == 1


def test_a_dry_run_still_reports_a_recipient_it_cannot_build_for(make_person):
    """The dry run's purpose survives: e1 still refuses to build for an
    address with no activated member behind it."""
    p = make_person(name='DryGone')
    email = _sendable(p['id'])
    with api_tx() as tx:
        tx.execute("UPDATE person SET activated = FALSE WHERE id = %(i)s", dict(i=p['id']))
    res = _dry_run(e1, 'e1', dict(person_id=p['id'], email=email, name='DryGone'))
    assert res['built'] == 0 and res['error'] == 'no_person'


def test_a_dry_run_from_the_send_button_writes_no_link(client, make_person, monkeypatch):
    """Through the admin route, the path the finding describes."""
    import hashlib
    import secrets
    admin = make_person(name='DryAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=admin['id']))
        admin_email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                                 dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=admin_email, p=admin['id']))
    p = make_person(name='DryButton')
    email = _sendable(p['id'])
    monkeypatch.setattr(e6, 'recipients', lambda: [dict(person_id=p['id'], email=email, name='DryButton')])

    r = client.post('/admin/growth/emails/e6/send', headers={'Authorization': f'Bearer {tok}'},
                    json=dict(campaign_id=f'e6-dry-{uuid.uuid4().hex[:8]}', dry_run=True))

    assert r.status_code == 200 and r.get_json()['built'] == 1
    assert _links(p['id']) == 0
