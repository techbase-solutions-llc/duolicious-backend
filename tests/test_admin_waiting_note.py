"""Write to them (TEC-2210, plan ahavah-admin/docs/plans/2026-11-26-admin-dead-buttons.md
part 1): the owner writes a short note to one member on the Waiting on a
reply list and it goes by email on the member note shell.

Nothing is sent here: emails.member_note.send_member_note is replaced in
every test that reaches it."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from database import api_tx
from service.config import WEB_BASE_URL

NOTE = "Shalom Miriam,\nsomeone on Ahavah would be glad to hear from you.\n\nWith every blessing, Tennyson"


@pytest.fixture(autouse=True)
def _calendar_open(monkeypatch):
    """No rest period and a calendar that is known, whatever day the suite
    runs on. The rest day tests switch these on themselves."""
    from service.campaigns import schedule
    monkeypatch.setattr(schedule, 'campaign_rest_now', lambda: False)
    monkeypatch.setattr(schedule, 'campaign_beyond_known_now', lambda: False)


@pytest.fixture
def sent(monkeypatch):
    """The member note sender, replaced: records each call's arguments.
    `sent.result` is what it returns and `sent.error` what it raises."""
    from emails import member_note

    class _Sent(list):
        result = True
        error: Exception | None = None
        during = None

    calls = _Sent()

    def fake(**kw):
        calls.append(kw)
        if calls.during is not None:
            calls.during()
        if calls.error is not None:
            raise calls.error
        return calls.result

    monkeypatch.setattr(member_note, 'send_member_note', fake)
    return calls


def _member(make_person, name: str = 'Miriam Levi', **kw) -> dict:
    return make_person(name=name, email=kw.get('email') or f'wn-{uuid4()}@ahavah-test.invalid')


def _like(a, b) -> None:
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s) ON CONFLICT DO NOTHING",
                   dict(a=a['id'], b=b['id']))


def _waiting_member(make_person, **kw) -> dict:
    """A member somebody has liked and who has not answered."""
    m = _member(make_person, **kw)
    _like(_member(make_person, name='Liker'), m)
    return m


def _post(client, headers, person, note=NOTE):
    uuid = person if isinstance(person, str) else person['uuid']
    body = {} if note is None else {'note': note}
    return client.post(f'/admin/community/waiting/{uuid}/note', json=body, headers=headers)


def _rows(person) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM waiting_note WHERE person_id = %(p)s ORDER BY sent_at", dict(p=person['id']))]


def _audit(person) -> list[dict]:
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT * FROM admin_audit_log WHERE action = 'waiting_note'
                AND target_uuid = %(u)s::uuid ORDER BY created_at""", dict(u=person['uuid']))]


def _note_at(person, delta: str) -> None:
    """A note already on record, sent at NOW() plus `delta` (an interval)."""
    with api_tx() as tx:
        tx.execute("""INSERT INTO waiting_note (person_id, sent_at, sent_by, note)
                      VALUES (%(p)s, NOW() + %(d)s::interval, 'earlier@ahavah-test.invalid', 'An earlier note')""",
                   dict(p=person['id'], d=delta))


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# The happy path

def test_a_note_goes_to_a_waiting_member(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    r = _post(client, admin_bearer, m)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['sent'] is True
    assert _iso(body['can_note_at']) - _iso(body['note_sent_at']) == timedelta(days=7)

    assert len(sent) == 1
    kw = sent[0]
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=m['id'])).fetchone()['email']
    assert kw['to_addr'] == email
    assert kw['subject'] == 'A note from Ahavah'
    assert kw['paragraphs'] == [
        'Shalom Miriam,<br/>someone on Ahavah would be glad to hear from you.',
        'With every blessing, Tennyson',
    ]
    assert kw['preheader'] == ('Shalom Miriam, someone on Ahavah would be glad to hear from you. '
                               'With every blessing, Tennyson')[:90]
    assert kw['button_label'] == 'Open Ahavah'
    assert kw['button_url'] == f'{WEB_BASE_URL}/matches'
    assert kw['cc_admin'] is True
    assert kw['raise_on_failure'] is True

    rows = _rows(m)
    assert len(rows) == 1 and rows[0]['note'] == NOTE
    assert rows[0]['sent_at'].isoformat() == body['note_sent_at']


def test_the_note_is_escaped_and_split_into_paragraphs(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    note = 'Ruth & Boaz said "hello",\r\nit\'s true.\n \n\n\nSecond one.\n\nThird   one.  '
    assert _post(client, admin_bearer, m, note).status_code == 200
    kw = sent[0]
    assert kw['paragraphs'] == [
        'Ruth &amp; Boaz said &quot;hello&quot;,<br/>it&#x27;s true.',
        'Second one.',
        'Third   one.',
    ]
    assert kw['preheader'] == 'Ruth &amp; Boaz said &quot;hello&quot;, it&#x27;s true. Second one. Third one.'


def test_the_preheader_is_the_first_90_characters(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    note = 'Shalom\n\n' + 'word ' * 40
    assert _post(client, admin_bearer, m, note).status_code == 200
    assert sent[0]['preheader'] == ('Shalom ' + 'word ' * 40)[:90].rstrip()
    assert len(sent[0]['preheader']) == 90

    other = _waiting_member(make_person)
    assert _post(client, admin_bearer, other, 'x' * 89 + ' ' + 'y' * 20).status_code == 200
    assert sent[1]['preheader'] == 'x' * 89  # the 90th character was a space


def test_a_member_waiting_on_an_opener_only_can_be_written_to(client, admin_bearer, make_person, sent):
    """Waiting is the list's own rule (the waits CTE), not likes alone."""
    a, b = _member(make_person, name='Opener'), _member(make_person)
    with api_tx() as tx:
        mam_id = tx.execute("SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 AS id").fetchone()['id']
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'O', convert_to('hi', 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id, p=a['id'], j=b['uuid']))
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'I', convert_to('hi', 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id + 1, p=b['id'], j=a['uuid']))
    assert _post(client, admin_bearer, b).status_code == 200


# ---------------------------------------------------------------------------
# 400 bad_note

@pytest.mark.parametrize('note', [
    None, '', '   \n\n  ', 'x' * 601,
    'See http://example.org', 'Look at HTTPS links', 'Go to www.ahavah.app',
    'A <b>bold</b> note', 'Less than <', 'Greater than >',
])
def test_a_bad_note_is_refused_and_nothing_is_sent(client, admin_bearer, make_person, sent, note):
    m = _waiting_member(make_person)
    r = _post(client, admin_bearer, m, note)
    assert r.status_code == 400
    body = r.get_json()
    assert body['error'] == 'bad_note' and body['detail']
    assert '—' not in body['detail'] and '!' not in body['detail']
    assert sent == [] and _rows(m) == [] and _audit(m) == []


def test_600_characters_is_allowed(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    assert _post(client, admin_bearer, m, '  ' + 'x' * 600 + '\n').status_code == 200


# ---------------------------------------------------------------------------
# 403 and 404

def test_a_member_cannot_send_a_note(client, make_person, sign_in, sent):
    m = _waiting_member(make_person)
    r = _post(client, sign_in(_member(make_person, name='NotAdmin')), m)
    assert r.status_code == 403
    assert sent == [] and _rows(m) == []


@pytest.mark.parametrize('uuid', [lambda: str(uuid4()), lambda: 'not-a-uuid'])
def test_no_such_member_is_404(client, admin_bearer, sent, uuid):
    r = _post(client, admin_bearer, uuid())
    assert r.status_code == 404
    assert sent == []


# ---------------------------------------------------------------------------
# 409

def _refused(r, code: str) -> dict:
    assert r.status_code == 409, r.get_data(as_text=True)
    body = r.get_json()
    assert body['error'] == code
    return body


def test_a_member_nobody_waits_on_is_not_waiting(client, admin_bearer, make_person, sent):
    m = _member(make_person)
    _refused(_post(client, admin_bearer, m), 'not_waiting')
    assert sent == [] and _rows(m) == []


def test_a_note_in_the_last_7_days_is_too_soon(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    _note_at(m, "-7 days + 1 minute")
    body = _refused(_post(client, admin_bearer, m), 'too_soon')
    earlier = _rows(m)[0]['sent_at']
    assert _iso(body['can_note_at']) == earlier + timedelta(days=7)
    assert sent == [] and len(_rows(m)) == 1


def test_a_note_just_over_7_days_ago_allows_another(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    _note_at(m, "-7 days - 1 minute")
    assert _post(client, admin_bearer, m).status_code == 200
    assert len(sent) == 1 and len(_rows(m)) == 2


def test_two_notes_in_a_row_send_once(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    first = _post(client, admin_bearer, m)
    assert first.status_code == 200
    body = _refused(_post(client, admin_bearer, m), 'too_soon')
    assert body['can_note_at'] == first.get_json()['can_note_at']
    assert len(sent) == 1 and len(_rows(m)) == 1 and len(_audit(m)) == 1


def test_a_second_press_while_the_first_is_sending_is_too_soon(app, client, admin_bearer, make_person, sent):
    """The row is claimed before the send, so a press that lands while the
    mail server is still answering finds it."""
    import threading
    m = _waiting_member(make_person)
    seen = []

    def second_press():
        # Its own thread and client: a request inside a request is not
        # something the test client can do on one thread.
        def go():
            with app.test_client() as other:
                seen.append(_post(other, admin_bearer, m))
        th = threading.Thread(target=go)
        th.start()
        th.join(30)

    sent.during = lambda: second_press() if not seen else None
    assert _post(client, admin_bearer, m).status_code == 200
    assert len(seen) == 1
    _refused(seen[0], 'too_soon')
    assert len(sent) == 1 and len(_rows(m)) == 1


@pytest.mark.parametrize('which', ['campaign_rest_now', 'campaign_beyond_known_now'])
def test_a_rest_period_or_an_unknown_day_is_refused(client, admin_bearer, make_person, sent, monkeypatch, which):
    from service.campaigns import schedule
    monkeypatch.setattr(schedule, which, lambda: True)
    m = _waiting_member(make_person)
    _refused(_post(client, admin_bearer, m), 'rest_day')
    assert sent == [] and _rows(m) == []


def test_an_unsubscribed_member_is_refused(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    with api_tx() as tx:
        tx.execute("UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(i)s", dict(i=m['id']))
    _refused(_post(client, admin_bearer, m), 'unsubscribed')
    assert sent == [] and _rows(m) == []


def test_every_email_channel_off_counts_as_unsubscribed(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    with api_tx() as tx:
        tx.execute("""INSERT INTO notification_preference
                        (person_id, email_messages, email_matches, email_likes, email_verification, email_profile_views)
                      VALUES (%(i)s, FALSE, FALSE, FALSE, FALSE, FALSE)
                      ON CONFLICT (person_id) DO UPDATE SET email_messages = FALSE, email_matches = FALSE,
                        email_likes = FALSE, email_verification = FALSE, email_profile_views = FALSE""",
                   dict(i=m['id']))
    _refused(_post(client, admin_bearer, m), 'unsubscribed')


def test_a_suppressed_address_is_refused(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person, email=f'wn-{uuid4()}@example.com')
    _refused(_post(client, admin_bearer, m), 'unsubscribed')
    assert sent == [] and _rows(m) == []


def test_a_send_the_mailer_suppresses_records_nothing(client, admin_bearer, make_person, sent):
    sent.result = False
    m = _waiting_member(make_person)
    _refused(_post(client, admin_bearer, m), 'unsubscribed')
    assert len(sent) == 1 and _rows(m) == [] and _audit(m) == []


@pytest.mark.parametrize('change', [
    "UPDATE person SET activated = FALSE WHERE id = %(i)s",
    "UPDATE person SET admin_deactivated_at = NOW() WHERE id = %(i)s",
    "UPDATE person SET deletion_requested_at = NOW() WHERE id = %(i)s",
    "UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
    "UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s",
    "UPDATE person SET roles = ARRAY['tester']::TEXT[] WHERE id = %(i)s",
])
def test_an_account_that_cannot_be_reached_is_refused(client, admin_bearer, make_person, sent, change):
    m = _waiting_member(make_person)
    with api_tx() as tx:
        tx.execute(change, dict(i=m['id']))
    _refused(_post(client, admin_bearer, m), 'not_reachable')
    assert sent == [] and _rows(m) == []


def test_a_test_account_address_is_not_reachable(client, admin_bearer, make_person, sent, monkeypatch):
    m = _waiting_member(make_person)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=m['id'])).fetchone()['email']
    monkeypatch.setenv('AHAVAH_TEST_ACCOUNT_EMAILS', email.upper())
    _refused(_post(client, admin_bearer, m), 'not_reachable')
    assert sent == []


# ---------------------------------------------------------------------------
# 502

def test_a_refused_send_is_502_and_records_nothing(client, admin_bearer, make_person, sent):
    from smtp import guard
    m = _waiting_member(make_person)
    sent.error = guard.SendFailed('waiting_note: every attempt failed')
    r = _post(client, admin_bearer, m)
    assert r.status_code == 502 and r.get_json() == {'error': 'send_failed'}
    assert _rows(m) == [] and _audit(m) == []

    sent.error = guard.MailGuardRefused('halt', 'waiting_note')
    assert _post(client, admin_bearer, m).status_code == 502
    assert _rows(m) == []

    sent.error = None  # it can be tried again
    assert _post(client, admin_bearer, m).status_code == 200
    assert len(_rows(m)) == 1 and len(_audit(m)) == 1


# ---------------------------------------------------------------------------
# The audit row

def test_each_send_writes_an_audit_row_without_the_text(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    assert _post(client, admin_bearer, m).status_code == 200
    rows = _audit(m)
    assert len(rows) == 1
    meta = rows[0]['metadata']
    meta = meta if isinstance(meta, dict) else json.loads(meta)
    assert meta == {'member': m['uuid'], 'note_length': len(NOTE)}
    assert 'Shalom' not in json.dumps(meta)


# ---------------------------------------------------------------------------
# GET /admin/community/waiting gains note_sent_at and can_note_at

def _row(client, headers, person):
    r = client.get('/admin/community/waiting', headers=headers)
    assert r.status_code == 200
    return next(m for m in r.get_json()['members'] if m['uuid'] == person['uuid'])


def test_the_list_shows_when_a_note_went_and_when_another_is_allowed(client, admin_bearer, make_person, sent):
    m = _waiting_member(make_person)
    row = _row(client, admin_bearer, m)
    assert row['note_sent_at'] is None and row['can_note_at'] is None

    body = _post(client, admin_bearer, m).get_json()
    row = _row(client, admin_bearer, m)
    assert row['note_sent_at'] == body['note_sent_at']
    assert row['can_note_at'] == body['can_note_at']


def test_an_old_note_shows_its_date_and_allows_another(client, admin_bearer, make_person):
    m = _waiting_member(make_person)
    _note_at(m, "-10 days")
    _note_at(m, "-8 days")
    row = _row(client, admin_bearer, m)
    assert row['note_sent_at'] == _rows(m)[-1]['sent_at'].isoformat()
    assert row['can_note_at'] is None


# ---------------------------------------------------------------------------
# send_member_note's strict mode

def test_send_member_note_raises_on_a_failed_member_send_when_asked(monkeypatch):
    import smtp
    from emails import member_note

    calls = []

    class _Mailer:
        def send(self, **kw):
            calls.append(kw)
            return None

    monkeypatch.setattr(smtp, 'make_aws_smtp', lambda: _Mailer())
    assert member_note.send_member_note(
        to_addr='miriam@ahavah-test.invalid', subject='A note from Ahavah', preheader='p',
        paragraphs=['x'], kind='waiting_note', raise_on_failure=True) is True
    member, admin = calls
    assert member['to_addr'] == 'miriam@ahavah-test.invalid'
    assert member['raise_on_failure'] is True and member['raise_on_refusal'] is True
    assert member['kind'] == 'waiting_note' and admin['kind'] == 'waiting_note'
    assert admin['to_addr'] == member_note.ADMIN_COPY_ADDR
    assert not admin.get('raise_on_failure') and not admin.get('raise_on_refusal')

    calls.clear()
    member_note.send_member_note(to_addr='miriam@ahavah-test.invalid', subject='s', preheader='p',
                                 paragraphs=['x'], cc_admin=False)
    assert len(calls) == 1
    assert not calls[0].get('raise_on_failure') and calls[0].get('kind') is None
