"""scripts/send_question_proofs.py (TEC-1845): one proof of each quick
question email and push, to the owner's address and his account (18) only.
A dry run by default; nothing recorded against any member, not even a push
tap; no switch read or changed."""
import os

import pytest

from database import api_tx
from scripts import send_question_proofs as sq

EXPECTED_EMAILS = {'e2_question_line', 'questions_launch'}
_TABLES = ('campaign_link', 'email_outbox', 'email_send_log', 'push_send_log', 'push_tap')


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
def capture(monkeypatch, questions_schema):
    smtp, pushes, asked = _Smtp(), [], []
    monkeypatch.setattr(sq, '_smtp', lambda: smtp)
    monkeypatch.setattr(sq, '_subscriptions', lambda pid: asked.append(pid) or [
        dict(endpoint='https://push.test/a', p256dh='k', auth='a')])
    monkeypatch.setattr(sq, '_push_one', lambda sub, payload: pushes.append(payload))
    return smtp, pushes, asked


def test_the_plan_covers_every_question_proof():
    emails, pushes = sq.plan()
    assert {e['name'] for e in emails} == EXPECTED_EMAILS
    assert [p['title'] for p in pushes] == ["This week's question", 'An easy first line',
                                           'New on Ahavah: quick questions']
    assert not [p for p in pushes if 'src=' in p['url']], 'a proof tap would count as a member tap'
    assert sq.PROOF_TO == 'harrigan.tennyson@gmail.com' and sq.PUSH_PERSON_ID == 18


def test_a_dry_run_sends_nothing(capture, capsys):
    smtp, pushes, asked = capture
    before = _counts()
    sq.main([])
    assert smtp.sent == [] and pushes == [] and asked == []
    assert _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(capture, monkeypatch):
    smtp, pushes, asked = capture
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    sq.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == len(EXPECTED_EMAILS)
    assert all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert asked == [18] and len(pushes) == 3
    assert all(p['title'].startswith('[Proof] ') for p in pushes)
    assert [p['tag'] for p in pushes] == ['question:proof', 'match:proof', 'question:proof']
    assert _counts() == before and dict(os.environ) == env_before


def test_no_proof_carries_a_live_unsubscribe_link():
    from service.config import WEB_BASE_URL
    for e in sq.plan()[0]:
        assert f'{WEB_BASE_URL.rstrip("/")}/u/' not in e['html'], e['name']
        assert f'href="{sq.PROOF_LINK_DISABLED}"' in e['html'], e['name']
    by_name = {e['name']: e['html'] for e in sq.plan()[0]}
    assert "This week's question: mountains or the sea? Answer in the app." in by_name['e2_question_line']


def test_the_launch_proof_answer_buttons_are_inert():
    """A tap on a proof button would save the owner's own answer to a real
    question, so each one goes to PROOF_LINK_DISABLED."""
    from service.config import WEB_BASE_URL
    html = {e['name']: e['html'] for e in sq.plan()[0]}['questions_launch']
    assert f'{WEB_BASE_URL.rstrip("/")}/q/' not in html
    assert html.count(f'href="{sq.PROOF_LINK_DISABLED}"') >= 3  # 2 answers and the unsubscribe
    assert '>Mountains<' in html and '>The sea<' in html
