"""E1 once more, with fresh tokens and the new copy, to members who never
received it (finding 80). Held: a real send is refused until
AHAVAH_E1_RESEND_ENABLED is on."""
import pytest

from database import api_tx
from emails import send_spotlight_resend as rs


def _member(make_person, name):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid"))
    return p


def _ids():
    return {r['person_id'] for r in rs.recipients()}


def test_only_members_who_never_had_e1_and_have_not_opted_in(make_person):
    never = _member(make_person, 'NeverE1')
    had = _member(make_person, 'HadE1')
    opted = _member(make_person, 'OptedE1')
    left = _member(make_person, 'LeftE1')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id)
                      VALUES (%(p)s, 'e1', 'e1-20260919-launch')""", dict(p=had['id']))
        tx.execute("UPDATE person SET spotlight_opt_in = TRUE WHERE id = %(p)s", dict(p=opted['id']))
        tx.execute("UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s", dict(p=left['id']))
    ids = _ids()
    assert never['id'] in ids
    assert not ids & {had['id'], opted['id'], left['id']}
    assert rs.recipient_count() == len(rs.recipients())


def test_each_email_carries_a_fresh_token_and_the_new_copy(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_SPOTLIGHT_COPY_ENABLED', raising=False)
    p = _member(make_person, 'FreshToken')
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(p)s", dict(p=p['id'])).fetchone()['email']
    subject, html = rs.build_for(dict(person_id=p['id'], email=email, name='x'))
    assert subject == rs.SUBJECT
    assert 'main profile photo, first name, age and country, and nothing else' in html
    assert 'photo you choose' not in html
    with api_tx('read committed') as tx:
        nonces = tx.execute("SELECT count(*) AS n FROM spotlight_token_nonce WHERE person_id = %(p)s AND purpose = 'confirm'",
                            dict(p=p['id'])).fetchone()['n']
        kinds = [r['kind'] for r in tx.execute("SELECT kind FROM campaign_link WHERE subject_person_id = %(p)s",
                                               dict(p=p['id'])).fetchall()]
    assert nonces == 1 and kinds == ['e1', 'e1']


def test_a_real_send_is_refused_while_the_switch_is_off(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_E1_RESEND_ENABLED', raising=False)
    p = _member(make_person, 'RefusedResend')
    res = rs.run(send=True, campaign_id='e1-resend-test-off')
    assert res == dict(error='switch_off', queued=0)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM email_outbox WHERE person_id = %(p)s",
                          dict(p=p['id'])).fetchone()['n'] == 0


def test_a_dry_run_writes_nothing(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_E1_RESEND_ENABLED', raising=False)
    p = _member(make_person, 'DryResend')
    res = rs.run(send=False, campaign_id='e1-resend-test-dry', only_ids=[p['id']])
    assert res['built'] == 1 and res['queued'] == 0
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM spotlight_token_nonce WHERE person_id = %(p)s",
                          dict(p=p['id'])).fetchone()['n'] == 0


def test_with_the_switch_on_it_queues_through_the_outbox(make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_E1_RESEND_ENABLED', '1')
    p = _member(make_person, 'QueuedResend')
    res = rs.run(send=True, campaign_id='e1-resend-test-on', only_ids=[p['id']], cap_days=0)
    assert res['queued'] == 1
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT campaign, unsub_scope FROM email_outbox WHERE person_id = %(p)s",
                         dict(p=p['id'])).fetchone()
    assert dict(row) == dict(campaign='e1', unsub_scope='campaigns')


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT (SELECT count(*) FROM campaign_link) + (SELECT count(*) FROM spotlight_token_nonce) AS n").fetchone()['n']
    subject, html = rs.preview('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        after = tx.execute("SELECT (SELECT count(*) FROM campaign_link) + (SELECT count(*) FROM spotlight_token_nonce) AS n").fetchone()['n']
    assert after == before
    assert 'main profile photo' in html
