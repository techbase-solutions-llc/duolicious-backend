"""The inviter hears when a friend joins (finding 75): held behind
AHAVAH_FRIEND_JOINED_ENABLED, queued in the sign-up's own transaction,
and never able to fail the sign-up."""
import pytest

from database import api_tx
from emails import friend_joined as fj
from service.config import WEB_BASE_URL


def _inviter(make_person, name='Inviter'):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid"))
    return p


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, unsub_scope, exempt, payload->>'subject' AS subject,
                      payload->>'html' AS html
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'friend_joined'""",
            dict(p=pid)).fetchall()]


@pytest.fixture
def credits_to(monkeypatch):
    """Make finish-onboarding's referral credit name `inviter` as the
    inviter, as credit_pending_for_invitee does for a real referral."""
    import service.person as person_service

    def _use(inviter):
        monkeypatch.setattr(person_service, 'credit_pending_for_invitee',
                            lambda tx, email: inviter['uuid'])
    return _use


def test_off_by_default(make_person, finish_onboarding, credits_to, monkeypatch):
    monkeypatch.delenv('AHAVAH_FRIEND_JOINED_ENABLED', raising=False)
    inviter = _inviter(make_person, 'OffInviter')
    credits_to(inviter)
    r, pid = finish_onboarding()
    assert r.status_code == 200 and pid
    assert _rows(inviter['id']) == []


def test_the_inviter_is_told_once_without_a_name(make_person, finish_onboarding, credits_to, monkeypatch):
    monkeypatch.setenv('AHAVAH_FRIEND_JOINED_ENABLED', '1')
    inviter = _inviter(make_person, 'TellInviter')
    credits_to(inviter)
    r, pid = finish_onboarding()
    assert r.status_code == 200 and pid
    rows = _rows(inviter['id'])
    assert len(rows) == 1
    row = rows[0]
    assert row['campaign_id'] == f'friend_joined-{pid}'
    assert row['unsub_scope'] == 'campaigns' and row['exempt'] is True
    assert row['subject'] == 'Someone you invited has joined Ahavah'
    assert 'Onboarding Test' not in row['html'] and 'Onboarding' not in row['html']
    assert 'a 30-minute boost on Discover' in row['html'] and '30 days' in row['html']
    with api_tx('read committed') as tx:
        target = tx.execute("SELECT target_url FROM campaign_link WHERE kind = 'friend_joined' AND subject_person_id = %(p)s",
                            dict(p=inviter['id'])).fetchone()['target_url']
    assert target == f'{WEB_BASE_URL}/invite'
    with api_tx() as tx:
        assert fj.queue_for_inviter(tx, inviter['uuid'], pid) is None, 'a replay queued a second email'


def test_a_failure_never_fails_the_sign_up(make_person, finish_onboarding, credits_to, monkeypatch):
    monkeypatch.setenv('AHAVAH_FRIEND_JOINED_ENABLED', '1')
    inviter = _inviter(make_person, 'BrokenInviter')
    credits_to(inviter)
    monkeypatch.setattr(fj, '_Q_INVITER', 'SELECT no_such_column FROM person WHERE uuid = %(u)s')
    r, pid = finish_onboarding()
    assert r.status_code == 200 and pid
    assert _rows(inviter['id']) == []


def test_not_for_an_inviter_who_left_campaigns(make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_FRIEND_JOINED_ENABLED', '1')
    inviter = _inviter(make_person, 'LeftInviter')
    friend = make_person(name='Friend')
    with api_tx() as tx:
        tx.execute("UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s", dict(p=inviter['id']))
        assert fj.queue_for_inviter(tx, inviter['uuid'], friend['id']) is None
    assert _rows(inviter['id']) == []


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = fj.preview('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert subject == 'Someone you invited has joined Ahavah'
