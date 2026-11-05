"""TEC-2113 (owner's ruling, 5 Nov 2026): the "your Spotlight card is ready"
email (E4) must not go out until the member's card is drawn.

Creating a welcome or member-of-the-week card no longer queues E4. The image
upload that completes the render queues it, keyed `e4-drawn-<request_key>`,
when approvals and invites are on; otherwise the invite-pending drain sends it
later, and only for a card that has been drawn.

`_make_eligible` and the session helper are copied from
tests/test_spotlight_routes.py on purpose -- test files in this suite do not
import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets

import pytest
from PIL import Image

from database import api_tx
from service.spotlight.queue import create_candidate, set_setting
from service.spotlight.revisions import current_revision, edit_caption

H = {'X-Growth-Cron': 'test-cron-secret'}

_DEFAULTS = dict(approvals_enabled='false', invites_enabled='true')


@pytest.fixture
def switches():
    """Sets the two Spotlight switches for a test and restores the seeded
    defaults afterwards, so a failed assertion never leaks a setting."""
    def _set(**kv):
        with api_tx() as tx:
            for k, v in kv.items():
                set_setting(tx, k, v)
    yield _set
    _set(**_DEFAULTS)


@pytest.fixture
def storage(monkeypatch):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)


def _png(colour='white'):
    buf = io.BytesIO()
    Image.new('RGB', (1080, 1080), colour).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _make_eligible(make_person, name='Elig', gender='Woman'):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL,
                   email = %(e)s
             WHERE id = %(id)s""", dict(id=p['id'], e=f'card-ready-{p["id"]}@ahavah-test.invalid'))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _admin_headers(make_person):
    admin = make_person(name='CardReadyAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=admin['id']))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def _draw(client, rk, colour='white'):
    """What the admin's daily tick does: one render uploaded to every
    platform row of the request, the last of which completes the render."""
    png = _png(colour)
    with api_tx('read committed') as tx:
        platforms = [r['platform'] for r in tx.execute(
            "SELECT platform FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform",
            dict(rk=rk)).fetchall()]
    for platform in platforms:
        r = client.post(f'/admin/growth/queue/{rk}/image', json={'platform': platform, 'png_base64': png},
                        headers=H)
        assert r.status_code == 200, r.get_json()
    with api_tx('read committed') as tx:
        assert current_revision(tx, rk)['asset_hash'] is not None


def _e4_rows(person_id):
    with api_tx('read committed') as tx:
        return [r['campaign_id'] for r in tx.execute(
            "SELECT campaign_id FROM email_outbox WHERE campaign = 'e4' AND person_id = %(p)s ORDER BY id",
            dict(p=person_id)).fetchall()]


def _welcome(client, person_id):
    r = client.post('/admin/growth/spotlight/welcome', json={'person_id': person_id}, headers=H)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['request_key']


@pytest.fixture
def audits(monkeypatch):
    """What the routes audit. A cron-header call logs its audit line rather
    than writing a row, so the helper is captured instead of read back."""
    import service.api.admin.spotlight_routes as sr
    seen = []
    monkeypatch.setattr(sr, '_audit', lambda tx, s, action, **metadata: seen.append((action, metadata)))
    return seen


def test_creating_a_welcome_card_queues_no_e4(client, make_person, switches, audits):
    p = _make_eligible(make_person, name='NoE4Welcome')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    assert _e4_rows(p['id']) == []
    assert audits == [('growth.queue.welcome', dict(person_id=p['id'], request_key=rk, invite_sent=False,
                                                    invite_on_render=True))]


def test_creating_a_member_of_week_card_queues_no_e4(client, make_person, switches, audits):
    A = _admin_headers(make_person)
    p = _make_eligible(make_person, name='NoE4Mow')
    switches(approvals_enabled='true', invites_enabled='true')
    r = client.post('/admin/growth/spotlight/member-of-week', json={'person_id': p['id']}, headers=A)
    assert r.status_code == 200, r.get_json()
    assert _e4_rows(p['id']) == []
    assert audits == [('growth.queue.member_of_week', dict(person_id=p['id'], request_key=r.get_json()['request_key'],
                                                           invite_sent=False, invite_on_render=True))]


def test_drawing_the_card_queues_e4_once(client, make_person, switches, storage, outbox_drain):
    """The render queues exactly one E4; a second render of the same card
    (a caption edit makes a new revision, which the tick draws again) queues
    nothing more."""
    p = _make_eligible(make_person, name='DrawnOnce')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    _draw(client, rk)
    assert _e4_rows(p['id']) == [f'e4-drawn-{rk}']
    with api_tx() as tx:
        edit_caption(tx, rk, 'A new caption', 't')
        assert current_revision(tx, rk)['asset_hash'] is None
    _draw(client, rk, colour='black')
    assert _e4_rows(p['id']) == [f'e4-drawn-{rk}']
    sent = outbox_drain(p['id'])
    assert len(sent) == 1 and '/spotlight/card/' in sent[0]['body']


def test_a_member_of_week_card_gets_e4_when_drawn(client, make_person, switches, storage):
    A = _admin_headers(make_person)
    p = _make_eligible(make_person, name='MowDrawn')
    switches(approvals_enabled='true', invites_enabled='true')
    r = client.post('/admin/growth/spotlight/member-of-week', json={'person_id': p['id']}, headers=A)
    rk = r.get_json()['request_key']
    _draw(client, rk)
    assert _e4_rows(p['id']) == [f'e4-drawn-{rk}']


def test_a_card_emailed_before_it_was_drawn_still_gets_the_drawn_e4(client, make_person, switches, storage):
    """Stewart's case: the old code queued `e4-<rk>` at creation. That row
    must not stop the email the card page promises once the card exists."""
    from emails.spotlight_card_ready import enqueue_card_ready
    p = _make_eligible(make_person, name='EmailedEarly')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        assert enqueue_card_ready(tx, p['id'], rk) is not None    # the old key, as before
    assert _e4_rows(p['id']) == [f'e4-{rk}']
    _draw(client, rk)
    assert _e4_rows(p['id']) == [f'e4-{rk}', f'e4-drawn-{rk}']
    # Drawn again after an edit: still exactly one drawn email.
    with api_tx() as tx:
        edit_caption(tx, rk, 'A new caption', 't')
    _draw(client, rk, colour='black')
    assert _e4_rows(p['id']) == [f'e4-{rk}', f'e4-drawn-{rk}']


def test_a_drawn_card_emailed_under_the_old_flow_is_not_drained(client, make_person, switches):
    """Owner's ruling: a member already emailed about a card that is already
    drawn (their link works) never gets a second "card is ready" email. The
    old `e4-<rk>` row keeps the card out of invite-pending and its count."""
    from emails.spotlight_card_ready import enqueue_card_ready
    from service.api.admin.spotlight_routes import _Q_INVITES_PENDING_PREDICATE
    from service.spotlight.revisions import attach_render
    p = _make_eligible(make_person, name='DrawnAndEmailed')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        assert enqueue_card_ready(tx, p['id'], rk) is not None    # the old key, as before
        # Drawn before this change: the render queued nothing then.
        attach_render(tx, current_revision(tx, rk)['id'], f'hash-{rk}', f'k-{rk}', f'https://cdn/k-{rk}.png')
        pending = {r['request_key'] for r in tx.execute(
            f"SELECT q.request_key FROM publishing_queue q WHERE {_Q_INVITES_PENDING_PREDICATE}").fetchall()}
    assert rk not in pending
    client.post('/admin/growth/spotlight/invite-pending', json={}, headers=H)
    assert _e4_rows(p['id']) == [f'e4-{rk}']


@pytest.mark.parametrize('off', ['approvals_enabled', 'invites_enabled'])
def test_with_approvals_or_invites_off_the_render_queues_none_and_the_drain_sends_it(
        client, make_person, switches, storage, off):
    """Drawn while a switch is off: nothing at render. Once both are on, the
    invite-pending drain queues it once for the drawn card and nothing for a
    card not yet drawn."""
    drawn = _make_eligible(make_person, name='DrawnWhileOff')
    undrawn = _make_eligible(make_person, name='NotDrawnYet', gender='Man')
    switches(approvals_enabled='false', invites_enabled='true')
    drawn_rk = _welcome(client, drawn['id'])
    undrawn_rk = _welcome(client, undrawn['id'])
    switches(**{**dict(approvals_enabled='true', invites_enabled='true'), off: 'false'})
    _draw(client, drawn_rk)
    assert _e4_rows(drawn['id']) == []
    switches(approvals_enabled='true', invites_enabled='true')
    first = client.post('/admin/growth/spotlight/invite-pending', json={}, headers=H).get_json()
    assert first['queued'] >= 1
    second = client.post('/admin/growth/spotlight/invite-pending', json={}, headers=H).get_json()
    assert second['queued'] == 0
    assert _e4_rows(drawn['id']) == [f'e4-drawn-{drawn_rk}']
    assert _e4_rows(undrawn['id']) == []
    with api_tx('read committed') as tx:
        statuses = {r['status'] for r in tx.execute(
            "SELECT status FROM publishing_queue WHERE request_key = %(rk)s", dict(rk=undrawn_rk)).fetchall()}
    assert statuses == {'awaiting_member'}     # left alone, not cancelled
    # Drawn now, with approvals on: the render queues it, and the drain
    # finds nothing left to do.
    _draw(client, undrawn_rk)
    assert _e4_rows(undrawn['id']) == [f'e4-drawn-{undrawn_rk}']


def test_invites_pending_counts_only_drawn_cards(client, make_person, switches, storage):
    p = _make_eligible(make_person, name='PendingCount')
    switches(approvals_enabled='false', invites_enabled='true')
    rk = _welcome(client, p['id'])

    def pending_keys():
        from service.api.admin.spotlight_routes import _Q_INVITES_PENDING_PREDICATE
        with api_tx('read committed') as tx:
            return {r['request_key'] for r in tx.execute(
                f"SELECT q.request_key FROM publishing_queue q WHERE {_Q_INVITES_PENDING_PREDICATE}").fetchall()}

    assert rk not in pending_keys()
    _draw(client, rk)
    assert rk in pending_keys()
    assert client.get('/admin/growth/candidates', headers=H).get_json()['invites_pending'] >= 1


def test_a_roundup_never_queues_e4(client, make_person, switches, storage):
    switches(approvals_enabled='true', invites_enabled='true')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='roundup', subject_person_id=None, caption='c', created_by='t')
    _draw(client, rk)
    with api_tx('read committed') as tx:
        n = tx.execute("SELECT count(*) AS n FROM email_outbox WHERE campaign = 'e4' AND campaign_id LIKE %(k)s",
                       dict(k=f'%{rk}')).fetchone()['n']
        statuses = {r['status'] for r in tx.execute(
            "SELECT status FROM publishing_queue WHERE request_key = %(rk)s", dict(rk=rk)).fetchall()}
    assert n == 0 and statuses == {'review'}


def test_an_e4_failure_at_render_takes_the_render_with_it(client, make_person, switches, storage, monkeypatch):
    """The render and its invite land together or not at all, so a card is
    never left drawn with its invite lost; the revision stays undrawn and the
    tick lists it again."""
    import emails.spotlight_card_ready as card_ready_mod
    p = _make_eligible(make_person, name='E4RenderBoom')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])

    def _boom(*a, **kw):
        raise RuntimeError('template exploded')

    monkeypatch.setattr(card_ready_mod, 'card_ready_html', _boom)
    png = _png()
    with api_tx('read committed') as tx:
        platforms = [r['platform'] for r in tx.execute(
            "SELECT platform FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform",
            dict(rk=rk)).fetchall()]
    for platform in platforms[:-1]:
        assert client.post(f'/admin/growth/queue/{rk}/image', json={'platform': platform, 'png_base64': png},
                           headers=H).status_code == 200
    with pytest.raises(RuntimeError, match='template exploded'):
        client.post(f'/admin/growth/queue/{rk}/image', json={'platform': platforms[-1], 'png_base64': png},
                    headers=H)
    with api_tx('read committed') as tx:
        assert current_revision(tx, rk)['asset_hash'] is None
    assert _e4_rows(p['id']) == []
