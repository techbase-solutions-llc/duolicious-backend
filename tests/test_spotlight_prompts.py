"""Spotlight opt-in prompts (TEC-2113; docs/plans/2026-11-05-spotlight-opt-in-prompts.md).

Three Growth rows: `spotlight_push` (members with push on who have not opted
in), `e1_push_off` (the announcement email to members with push off who have
not opted in) and `card_push` (members whose drawn card waits for their
approval). The card push also goes on its own when a drawn card's
card-ready email is queued.

The test database is shared, so audiences are checked for the people each
test makes, never for exact totals. Helpers are copied from
tests/test_spotlight_card_ready_after_render.py: test files here do not
import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from PIL import Image

from database import api_tx
from service.campaigns import log_send
from service.spotlight import prompts
from service.spotlight.queue import set_setting
from service.spotlight.revisions import current_revision, edit_caption

H = {'X-Growth-Cron': 'test-cron-secret'}
NOON = datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)   # 11:00 or 12:00 in New York


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _member(make_person, name, *, push=True, opted_in=False, tz=None, gender='Man'):
    p = make_person(name=name, gender=gender, email=f'{name.lower()}-{uuid.uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        if opted_in:
            tx.execute("UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW() WHERE id = %(i)s",
                       dict(i=p['id']))
        if push:
            tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                          VALUES (%(i)s, 'https://push.test/' || %(i)s::text, 'k', 'a', %(tz)s)""",
                       dict(i=p['id'], tz=tz))
    return p


def _set(person_id, sql):
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET {sql} WHERE id = %(i)s", dict(i=person_id))


def _email(person_id):
    with api_tx('read committed') as tx:
        return tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=person_id)).fetchone()['email']


def _ids(campaign, campaign_id=None):
    with api_tx('read committed') as tx:
        return {r['person_id'] for r in prompts.audience(tx, campaign, campaign_id)}


def _logged(campaign, person_id):
    with api_tx('read committed') as tx:
        return [r['campaign_id'] for r in tx.execute(
            "SELECT campaign_id FROM push_send_log WHERE campaign = %(c)s AND person_id = %(p)s ORDER BY sent_at",
            dict(c=campaign, p=person_id)).fetchall()]


class _Sent(list):
    """The pushes handed to the sender, and how many devices each reaches."""
    devices = {'n': 1}


@pytest.fixture
def pushes(monkeypatch):
    """Every push the code hands the sender, delivered at once (no thread),
    each reaching one device unless the test says otherwise."""
    sent = _Sent()
    sent.devices = devices = {'n': 1}

    def fake(person_id, payload, kind):
        sent.append(dict(person_id=person_id, kind=kind, **payload))
        return devices['n']

    monkeypatch.setattr(prompts, '_push_one', fake)
    monkeypatch.setattr(prompts, '_deliver_later', prompts._deliver)
    monkeypatch.setattr(prompts, '_now', lambda: NOON)
    monkeypatch.setattr(prompts, 'resting', lambda now: False)
    # The automatic card push is switched on here; one test turns it off.
    monkeypatch.setenv('AHAVAH_SPOTLIGHT_CARD_PUSH_ENABLED', '1')
    return sent


def _to(sent, person_id):
    return [s for s in sent if s['person_id'] == person_id]


# ---------------------------------------------------------------------------
# who is asked
# ---------------------------------------------------------------------------

def test_the_push_audience_is_members_with_push_on_who_have_not_opted_in(make_person):
    from service.unsubscribe import stamp_unsubscribed
    ok = _member(make_person, 'PushOk')
    opted = _member(make_person, 'PushOpted', opted_in=True)
    admin = _member(make_person, 'PushAdmin')
    mod = _member(make_person, 'PushMod')
    deleted = _member(make_person, 'PushDeleted')
    off = _member(make_person, 'PushDeactivated')
    unsub = _member(make_person, 'PushUnsub')
    suppressed = make_person(name='PushSuppressed')   # the fixture's @example.com address
    nopush = _member(make_person, 'PushNone', push=False)
    unsub_email = _email(unsub['id'])   # its own transaction: api_tx is never nested
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, 'https://push.test/s' || %(i)s::text, 'k', 'a')""", dict(i=suppressed['id']))
        assert stamp_unsubscribed(tx, 'campaigns', unsub_email)
    _set(admin['id'], "roles = ARRAY['admin']::text[]")
    _set(mod['id'], "roles = ARRAY['mod']::text[]")
    _set(deleted['id'], "deletion_requested_at = NOW()")
    _set(off['id'], "activated = FALSE")

    ids = _ids(prompts.OPT_IN)

    assert ok['id'] in ids
    for p in (opted, admin, mod, deleted, off, unsub, suppressed, nopush):
        assert p['id'] not in ids


def test_push_on_gets_the_push_and_push_off_gets_the_email(make_person):
    import emails.send_spotlight_announcement_push_off as e1np
    on = _member(make_person, 'SplitOn')
    off = _member(make_person, 'SplitOff', push=False)
    email_ids = {r['person_id'] for r in e1np.recipients()}
    push_ids = _ids(prompts.OPT_IN)
    assert on['id'] in push_ids and on['id'] not in email_ids
    assert off['id'] in email_ids and off['id'] not in push_ids


def test_the_push_off_email_leaves_out_staff_opted_in_unsubscribed_and_the_already_sent(make_person):
    import emails.send_spotlight_announcement_push_off as e1np
    from service.unsubscribe import stamp_unsubscribed
    ok = _member(make_person, 'MailOk', push=False)
    opted = _member(make_person, 'MailOpted', push=False, opted_in=True)
    mod = _member(make_person, 'MailMod', push=False)
    deleted = _member(make_person, 'MailDeleted', push=False)
    unsub = _member(make_person, 'MailUnsub', push=False)
    suppressed = make_person(name='MailSuppressed')
    sent = _member(make_person, 'MailSent', push=False)
    _set(mod['id'], "roles = ARRAY['mod']::text[]")
    _set(deleted['id'], "deletion_requested_at = NOW()")
    unsub_email = _email(unsub['id'])   # its own transaction: api_tx is never nested
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'campaigns', unsub_email)
        log_send(tx, sent['id'], e1np.CAMPAIGN, 'cmp_2026w45_e1_push_off', 'mid')

    rows = e1np.recipients()
    ids = {r['person_id'] for r in rows}

    assert ok['id'] in ids
    for p in (opted, mod, deleted, unsub, suppressed, sent):
        assert p['id'] not in ids
    assert e1np.recipient_count() == len(rows)


def test_the_push_off_email_is_e1_with_its_own_counted_link(make_person):
    import emails.send_spotlight_announcement_push_off as e1np
    p = _member(make_person, 'MailBuild', push=False)
    subject, html = e1np.build_for(dict(person_id=p['id'], email=_email(p['id']), name='MailBuild'))
    from emails.spotlight_announcement import SUBJECT
    assert subject == SUBJECT
    assert '/spotlight/confirm/' in html
    with api_tx('read committed') as tx:
        kinds = {r['kind'] for r in tx.execute(
            "SELECT kind FROM campaign_link WHERE subject_person_id = %(p)s", dict(p=p['id'])).fetchall()}
    assert kinds == {e1np.CAMPAIGN}


def test_the_push_off_email_counts_as_e1_for_the_resend(make_person):
    import emails.send_spotlight_resend as resend
    import emails.send_spotlight_announcement_push_off as e1np
    p = _member(make_person, 'ResendSees', push=False)
    assert p['id'] in {r['person_id'] for r in resend.recipients()}
    with api_tx() as tx:
        log_send(tx, p['id'], e1np.CAMPAIGN, 'cmp_2026w45_e1_push_off', 'mid')
    assert p['id'] not in {r['person_id'] for r in resend.recipients()}


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def test_a_run_pushes_each_member_once_and_a_rerun_pushes_nobody_twice(make_person, pushes):
    p = _member(make_person, 'RunOnce')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'

    first = prompts.run(prompts.OPT_IN, cid, send=True)
    second = prompts.run(prompts.OPT_IN, cid, send=True)

    mine = _to(pushes, p['id'])
    assert len(mine) == 1
    assert mine[0]['title'] == 'Be featured on Ahavah'
    assert mine[0]['body'] == 'Turn on Spotlight and you could be our member of the week.'
    assert mine[0]['url'] == '/settings/privacy'
    assert mine[0]['kind'] == prompts.OPT_IN
    assert first['queued'] >= 1 and first['dry_run'] is False and first['error'] is None
    assert second['queued'] == 0
    assert _logged(prompts.OPT_IN, p['id']) == [cid]
    # A new run is a new run.
    prompts.run(prompts.OPT_IN, cid + 'b', send=True)
    assert len(_to(pushes, p['id'])) == 2


def test_a_dry_run_sends_nothing_and_writes_nothing(make_person, pushes):
    p = _member(make_person, 'DryRun')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'

    res = prompts.run(prompts.OPT_IN, cid, send=False)

    assert pushes == []
    assert res['dry_run'] is True and res['queued'] == 0 and res['built'] >= 1
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM push_send_log WHERE campaign_id = %(c)s",
                          dict(c=cid)).fetchone()['n'] == 0
    assert p['id'] in _ids(prompts.OPT_IN, cid)


def test_a_dry_run_that_tried_to_push_would_raise(make_person, monkeypatch):
    """The dry run runs inside the send guard's no_send(): a push attempted
    there raises rather than reaching a device."""
    from smtp import guard
    _member(make_person, 'DryGuard')
    seen = []
    monkeypatch.setattr(prompts, '_now', lambda: NOON)
    monkeypatch.setattr(prompts, '_dry_run_probe', lambda: seen.append(guard.in_no_send()))
    prompts.run(prompts.OPT_IN, f'cmp_test_{uuid.uuid4().hex[:8]}', send=False)
    assert seen == [True]


def test_a_run_stops_at_the_cap(make_person, pushes):
    _member(make_person, 'CapA')
    _member(make_person, 'CapB')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'
    eligible = len(_ids(prompts.OPT_IN, cid))

    res = prompts.run(prompts.OPT_IN, cid, send=False, cap=1)

    assert res['built'] == 1
    assert res['skipped_cap'] == eligible - 1 >= 1
    assert prompts.PUSH_CAP == 500


def test_quiet_hours_hold_a_member_back_for_a_later_send(make_person, pushes):
    night = _member(make_person, 'Tokyo', tz='Asia/Tokyo')   # 01:00 there
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'
    res = prompts.run(prompts.OPT_IN, cid, send=True)
    assert _to(pushes, night['id']) == [] and _logged(prompts.OPT_IN, night['id']) == []
    assert res['skipped_quiet'] >= 1


def test_a_push_no_device_took_gives_its_row_back(make_person, pushes):
    p = _member(make_person, 'NoDevice')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'
    pushes.devices['n'] = 0
    prompts.run(prompts.OPT_IN, cid, send=True)
    assert len(_to(pushes, p['id'])) == 1 and _logged(prompts.OPT_IN, p['id']) == []
    pushes.devices['n'] = 1
    prompts.run(prompts.OPT_IN, cid, send=True)
    assert len(_to(pushes, p['id'])) == 2 and _logged(prompts.OPT_IN, p['id']) == [cid]


# ---------------------------------------------------------------------------
# the card push
# ---------------------------------------------------------------------------

_DEFAULTS = dict(approvals_enabled='false', invites_enabled='true')


@pytest.fixture
def switches():
    def _set_switches(**kv):
        with api_tx() as tx:
            for k, v in kv.items():
                set_setting(tx, k, v)
    yield _set_switches
    _set_switches(**_DEFAULTS)


@pytest.fixture
def storage(monkeypatch):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)


def _png(colour='white'):
    buf = io.BytesIO()
    Image.new('RGB', (1080, 1080), colour).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _eligible(make_person, name, *, push=True):
    p = _member(make_person, name, push=push, opted_in=True, gender='Woman')
    with api_tx() as tx:
        tx.execute("""UPDATE person SET ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01'
                       WHERE id = %(id)s""", dict(id=p['id']))
        tx.execute("""INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
                      VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _welcome(client, person_id):
    r = client.post('/admin/growth/spotlight/welcome', json={'person_id': person_id}, headers=H)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['request_key']


def _draw(client, rk, colour='white'):
    png = _png(colour)
    with api_tx('read committed') as tx:
        platforms = [r['platform'] for r in tx.execute(
            "SELECT platform FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform",
            dict(rk=rk)).fetchall()]
    for platform in platforms:
        r = client.post(f'/admin/growth/queue/{rk}/image', json={'platform': platform, 'png_base64': png},
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _drawn_and_emailed_before_this_change(client, make_person, switches, name, *, push=True):
    """The 9 Nov case: a card drawn and its email sent, with no push."""
    from emails.spotlight_card_ready import drawn_campaign_id, enqueue_card_ready
    from service.spotlight.revisions import attach_render
    p = _eligible(make_person, name, push=push)
    switches(approvals_enabled='false', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        attach_render(tx, current_revision(tx, rk)['id'], f'hash-{rk}', f'k-{rk}', f'https://cdn/k-{rk}.png')
        assert enqueue_card_ready(tx, p['id'], rk, campaign_id=drawn_campaign_id(rk)) is not None
    return p, rk


def _rev(rk):
    with api_tx('read committed') as tx:
        return current_revision(tx, rk)['id']


def test_a_card_waiting_for_its_member_is_in_the_card_audience(client, make_person, switches, pushes):
    p, rk = _drawn_and_emailed_before_this_change(client, make_person, switches, 'CardWaiting')
    no_push, _ = _drawn_and_emailed_before_this_change(client, make_person, switches, 'CardNoPush', push=False)
    ids = _ids(prompts.CARD)
    assert p['id'] in ids and no_push['id'] not in ids

    res = prompts.run(prompts.CARD, f'cmp_test_{uuid.uuid4().hex[:8]}', send=True)

    mine = _to(pushes, p['id'])
    assert len(mine) == 1 and res['queued'] >= 1
    assert mine[0]['title'] == 'Your Spotlight card is ready'
    assert mine[0]['body'] == 'Open the email from Ahavah and tap Approve to be featured.'
    assert mine[0]['url'].startswith('/spotlight/card/')
    assert _logged(prompts.CARD, p['id']) == [f'{rk}:{_rev(rk)}']
    # Another Send, another week: the same revision is not pushed again.
    prompts.run(prompts.CARD, f'cmp_test_{uuid.uuid4().hex[:8]}', send=True)
    assert len(_to(pushes, p['id'])) == 1


def test_a_card_whose_email_has_not_gone_is_not_pushed(client, make_person, switches, pushes):
    from service.spotlight.revisions import attach_render
    p = _eligible(make_person, 'CardNoEmail')
    switches(approvals_enabled='false', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        attach_render(tx, current_revision(tx, rk)['id'], f'hash-{rk}', f'k-{rk}', f'https://cdn/k-{rk}.png')
    assert p['id'] not in _ids(prompts.CARD)


def test_drawing_a_card_pushes_its_member_with_the_email(client, make_person, switches, storage, pushes):
    p = _eligible(make_person, 'CardAuto')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    _draw(client, rk)
    mine = _to(pushes, p['id'])
    assert len(mine) == 1 and mine[0]['title'] == 'Your Spotlight card is ready'
    assert _logged(prompts.CARD, p['id']) == [f'{rk}:{_rev(rk)}']
    # Redrawn after an edit: no new email, so no new push.
    with api_tx() as tx:
        edit_caption(tx, rk, 'A new caption', 't')
    _draw(client, rk, colour='black')
    assert len(_to(pushes, p['id'])) == 1


def test_with_its_switch_off_drawing_a_card_pushes_nobody(client, make_person, switches, storage, pushes,
                                                         monkeypatch):
    """AHAVAH_SPOTLIGHT_CARD_PUSH_ENABLED is off by default. The card push
    row the owner presses still sends."""
    monkeypatch.delenv('AHAVAH_SPOTLIGHT_CARD_PUSH_ENABLED')
    p = _eligible(make_person, 'CardSwitchOff')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    _draw(client, rk)
    assert _to(pushes, p['id']) == [] and _logged(prompts.CARD, p['id']) == []
    prompts.run(prompts.CARD, f'cmp_test_{uuid.uuid4().hex[:8]}', send=True)
    assert len(_to(pushes, p['id'])) == 1


def test_a_failing_card_push_never_rolls_the_render_back(client, make_person, switches, storage, pushes,
                                                         monkeypatch):
    """A failed query in the card push is held in its savepoint: the card
    is still drawn and its email still queued."""
    def broken(tx, campaign, campaign_id=None, **kw):
        tx.execute("SELECT no_such_column FROM person LIMIT 1")
    monkeypatch.setattr(prompts, 'audience', broken)
    p = _eligible(make_person, 'CardPushFails')
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    _draw(client, rk)
    with api_tx('read committed') as tx:
        assert current_revision(tx, rk)['asset_hash'] is not None
        assert tx.execute("""SELECT 1 FROM email_outbox WHERE campaign = 'e4' AND campaign_id = %(c)s""",
                          dict(c=f'e4-drawn-{rk}')).fetchone() is not None
    assert _to(pushes, p['id']) == []


def test_drawing_a_card_in_quiet_hours_pushes_nobody_yet(client, make_person, switches, storage, pushes,
                                                         monkeypatch):
    p = _eligible(make_person, 'CardQuiet')
    monkeypatch.setattr(prompts, '_now', lambda: datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc))
    switches(approvals_enabled='true', invites_enabled='true')
    rk = _welcome(client, p['id'])
    _draw(client, rk)
    assert _to(pushes, p['id']) == [] and _logged(prompts.CARD, p['id']) == []
    # The Growth row sends it later.
    monkeypatch.setattr(prompts, '_now', lambda: NOON)
    prompts.run(prompts.CARD, f'cmp_test_{uuid.uuid4().hex[:8]}', send=True)
    assert len(_to(pushes, p['id'])) == 1


def test_no_card_push_outside_a_collecting_request(client, make_person, switches, pushes):
    """Logged only where something will send it after the commit."""
    from service.api.admin.spotlight_routes import _enqueue_card_ready
    from service.spotlight.revisions import attach_render
    p = _eligible(make_person, 'CardNoCollector')
    switches(approvals_enabled='false', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        attach_render(tx, current_revision(tx, rk)['id'], f'hash-{rk}', f'k-{rk}', f'https://cdn/k-{rk}.png')
        assert _enqueue_card_ready(tx, p['id'], rk) is not None
    assert _to(pushes, p['id']) == [] and _logged(prompts.CARD, p['id']) == []


def test_the_invite_pending_drain_pushes_with_the_email(client, make_person, switches, pushes):
    from service.spotlight.revisions import attach_render
    p = _eligible(make_person, 'CardDrain')
    switches(approvals_enabled='false', invites_enabled='true')
    rk = _welcome(client, p['id'])
    with api_tx() as tx:
        attach_render(tx, current_revision(tx, rk)['id'], f'hash-{rk}', f'k-{rk}', f'https://cdn/k-{rk}.png')
    switches(approvals_enabled='true', invites_enabled='true')
    r = client.post('/admin/growth/spotlight/invite-pending', headers=H)
    assert r.status_code == 200, r.get_json()
    assert len(_to(pushes, p['id'])) == 1


# ---------------------------------------------------------------------------
# the Growth rows
# ---------------------------------------------------------------------------

def _bearer(person_id: int, email: str) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def admin(make_person):
    p = _member(make_person, 'PromptAdmin')
    with api_tx() as tx:
        email = tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s RETURNING email",
                           dict(i=p['id'])).fetchone()['email']
    return dict(headers=_bearer(p['id'], email), email=email, id=p['id'])


def test_the_growth_table_lists_the_three_rows(client, admin, make_person, pushes):
    p = _member(make_person, 'IndexPush')
    r = client.get('/admin/growth/emails', headers=admin['headers'])
    assert r.status_code == 200
    rows = {c['campaign']: c for c in r.get_json()['campaigns']}
    for key, channel in (('spotlight_push', 'push'), ('card_push', 'push'), ('e1_push_off', 'email'),
                         ('e1', 'email')):
        assert rows[key]['channel'] == channel and rows[key]['system'] is False
        assert isinstance(rows[key]['eligible_now'], int) and isinstance(rows[key]['would_reach_now'], int)
        assert rows[key]['would_reach_now'] <= rows[key]['eligible_now']
    assert rows['spotlight_push']['eligible_now'] >= 1
    assert rows['spotlight_push']['last_run_clicks'] is None


def test_the_send_button_runs_the_push_and_audits_it(client, admin, make_person, pushes, monkeypatch):
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr.campaign_schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(gr.campaign_schedule, 'campaign_beyond_known_now', lambda: False)
    p = _member(make_person, 'SendPush')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'

    dry = client.post('/admin/growth/emails/spotlight_push/send', headers=admin['headers'],
                      json=dict(campaign_id=cid + '_dry', dry_run=True)).get_json()
    assert dry['dry_run'] is True and dry['built'] >= 1 and pushes == []

    res = client.post('/admin/growth/emails/spotlight_push/send', headers=admin['headers'],
                      json=dict(campaign_id=cid, dry_run=False)).get_json()
    assert res['queued'] >= 1 and len(_to(pushes, p['id'])) == 1
    assert _to(pushes, admin['id']) == []   # staff are never in it
    with api_tx('read committed') as tx:
        audit = tx.execute("""SELECT metadata FROM admin_audit_log
                               WHERE action = 'growth.email.send' AND metadata->>'campaign_id' = %(c)s""",
                           dict(c=cid)).fetchone()
    assert audit['metadata']['campaign'] == 'spotlight_push'

    status = client.get(f'/admin/growth/emails/spotlight_push/status/{cid}', headers=admin['headers']).get_json()
    assert status['queued'] == res['queued'] and status['accepted'] == res['queued']
    runs = client.get('/admin/growth/emails/spotlight_push/runs', headers=admin['headers']).get_json()
    assert any(r['campaign_id'] == cid for r in runs['runs'])


def test_preview_pushes_the_admin_only(client, admin, pushes):
    r = client.post('/admin/growth/emails/spotlight_push/preview', headers=admin['headers'],
                    json=dict(to=admin['email']))
    assert r.status_code == 200, r.get_json()
    assert [s['person_id'] for s in pushes] == [admin['id']]
    assert pushes[0]['title'] == 'Be featured on Ahavah'
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM push_send_log WHERE person_id = %(p)s",
                          dict(p=admin['id'])).fetchone()['n'] == 0


def test_preview_to_someone_without_push_says_so(client, admin, make_person, pushes):
    p = _member(make_person, 'PreviewNoPush', push=False)
    r = client.post('/admin/growth/emails/card_push/preview', headers=admin['headers'], json=dict(to=_email(p['id'])))
    assert r.status_code == 409 and r.get_json()['error'] == 'no_push_subscription'
    assert pushes == []


def test_the_push_off_email_row_queues_through_the_outbox(client, admin, make_person, monkeypatch):
    import service.api.admin.growth_routes as gr
    monkeypatch.setattr(gr.campaign_schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(gr.campaign_schedule, 'campaign_beyond_known_now', lambda: False)
    p = _member(make_person, 'SendMail', push=False)
    # Inside E1's 7 day cap: Monday's weekly email does not hold this one back.
    with api_tx() as tx:
        log_send(tx, p['id'], 'e2', f'cmp_test_{uuid.uuid4().hex[:6]}', 'mid')
    cid = f'cmp_test_{uuid.uuid4().hex[:8]}'
    res = client.post('/admin/growth/emails/e1_push_off/send', headers=admin['headers'],
                      json=dict(campaign_id=cid, dry_run=False)).get_json()
    assert res['error'] is None, res
    with api_tx('read committed') as tx:
        row = tx.execute("""SELECT exempt FROM email_outbox
                             WHERE campaign = 'e1_push_off' AND campaign_id = %(c)s AND person_id = %(p)s""",
                         dict(c=cid, p=p['id'])).fetchone()
    assert row is not None and row['exempt'] is True
