"""scripts/send_proofs.py: one proof of each held email to the owner and
one push of each held push to his account (18) only. A dry run by
default; nothing recorded against any member; no switch read or changed."""
import os

import pytest

from database import api_tx
from scripts import send_proofs as sp

EXPECTED_EMAILS = {
    'likes_waiting', 'match_reminder', 'message_reminder', 'profile_views', 'one_photo',
    'e2_personal', 'referral_member', 'friend_joined', 'e1_spotlight', 'e4_card_ready',
    'e2_gatherings', 'e2_gatherings_online', 'welcome_gatherings',
}

_TABLES = ('campaign_link', 'email_outbox', 'email_send_log', 'push_send_log',
           'spotlight_token_nonce', 'admin_audit_log')


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f"SELECT count(*) AS n FROM {t}").fetchone()['n'] for t in _TABLES}


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def capture(monkeypatch):
    smtp = _Smtp()
    pushes = []
    subs_asked = []
    monkeypatch.setattr(sp, '_smtp', lambda: smtp)
    monkeypatch.setattr(sp, '_subscriptions', lambda pid: subs_asked.append(pid) or [
        dict(endpoint='https://push.test/a', p256dh='k', auth='a')])
    monkeypatch.setattr(sp, '_push_one', lambda sub, payload: pushes.append((sub['endpoint'], payload)))
    return smtp, pushes, subs_asked


def test_the_plan_covers_every_held_email_and_push():
    emails, pushes = sp.plan()
    assert {e['name'] for e in emails} == EXPECTED_EMAILS
    assert all(e['subject'].startswith('[PROOF] ') for e in emails)
    assert [p['title'] for p in pushes] == ['Say hello to your match', 'A message is waiting for you',
                                            # Release 4 of the in-app plan (TEC-1845).
                                            'Your gathering is tomorrow', 'New guests', 'New guests',
                                            'Your result is ready']
    assert sp.PROOF_TO == 'harrigan.tennyson@gmail.com' and sp.PUSH_PERSON_ID == 18


def test_a_dry_run_sends_nothing(capture, capsys):
    smtp, pushes, subs_asked = capture
    before = _counts()
    sp.main([])
    assert smtp.sent == [] and pushes == [] and subs_asked == []
    assert _counts() == before
    out = capsys.readouterr().out
    assert 'DRY RUN' in out and 'harrigan.tennyson@gmail.com' in out


def test_send_goes_to_the_owner_only_and_records_nothing(capture, monkeypatch):
    smtp, pushes, subs_asked = capture
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before = dict(os.environ)
    before = _counts()
    sp.main(['--send'])
    assert len(smtp.sent) == len(EXPECTED_EMAILS)
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert subs_asked == [18]
    assert len(pushes) == 6
    assert _counts() == before, 'a proof wrote to the database'
    assert dict(os.environ) == env_before, 'a proof changed a switch'


def test_the_proofs_use_the_held_copy():
    by_name = {e['name']: e for e in sp.plan()[0]}
    assert 'main profile photo' in by_name['e1_spotlight']['html']
    assert 'main profile photo' in by_name['e4_card_ready']['html']
    assert 'a 30-minute boost on Discover' in by_name['referral_member']['html']
    assert 'Share your invite link' in by_name['e2_personal']['html']


def test_no_proof_carries_a_live_unsubscribe_or_turn_off_link(capture):
    """The proofs go to the owner's own address: a real /u/<token> link
    ("Unsubscribe", "Turn off notification emails", "Stop the weekly email")
    would change his own settings if he clicked it. Each is an inert
    placeholder, and the copy around it is the real email's."""
    from service.config import WEB_BASE_URL
    from service.unsubscribe import _SCOPES, make_token
    assert sp.PROOF_LINK_DISABLED == 'https://ahavah.app/proof-link-disabled'
    tokens = [make_token(scope, sp.PROOF_TO) for scope in _SCOPES]
    for e in sp.plan()[0]:
        html = e['html']
        assert f'{WEB_BASE_URL.rstrip("/")}/u/' not in html, f"{e['name']} carries a live unsubscribe link"
        assert not [t for t in tokens if t in html], f"{e['name']} carries the owner's unsubscribe token"
        assert f'href="{sp.PROOF_LINK_DISABLED}"' in html, f"{e['name']} lost its unsubscribe link"
    by_name = {e['name']: e['html'] for e in sp.plan()[0]}
    assert 'Turn off notification emails' in by_name['match_reminder']
    assert 'Stop the weekly email' in by_name['e2_personal']
    smtp, _pushes, _subs = capture
    sp.main(['--send'])
    assert all(not s.get('list_unsubscribe') for s in smtp.sent)


def test_the_gatherings_proofs_wait_for_their_images(capture, monkeypatch, capsys):
    """While a gatherings title image is missing from emails/assets, plan()
    leaves those 3 proofs out and main() says which images it waits for;
    the other proofs go as before."""
    assert sp.missing_titles() == []
    monkeypatch.setattr(sp, 'missing_titles', lambda: ['subhead-gather-community'])
    emails, _ = sp.plan()
    assert {e['name'] for e in emails} == EXPECTED_EMAILS - {'e2_gatherings', 'e2_gatherings_online',
                                                          'welcome_gatherings'}
    sp.main([])
    assert 'waiting for title images: subhead-gather-community' in capsys.readouterr().out


def test_the_gatherings_proofs_carry_no_live_link():
    emails, _ = sp.plan()
    by_name = {e['name']: e for e in emails}
    for name in ('e2_gatherings', 'e2_gatherings_online', 'welcome_gatherings'):
        html = by_name[name]['html']
        assert '/s/' not in html and sp.PROOF_LINK_DISABLED in html
