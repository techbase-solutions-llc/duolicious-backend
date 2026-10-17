"""scripts/send_together_proofs.py (TEC-1845): one proof of each Together
email to the owner's address only. A dry run by default; nothing recorded;
no switch read or changed; no live unsubscribe link."""
import os

import pytest

from database import api_tx
from scripts import send_together_proofs as tp

EXPECTED = {'together_answered', 'together_ready', 'together_invite_game',
            'together_invite_checklist', 'together_summary'}
_TABLES = ('email_outbox', 'email_send_log', 'tool_session', 'lead')


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n'] for t in _TABLES}


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def smtp(monkeypatch, together_schema):
    s = _Smtp()
    monkeypatch.setattr(tp, '_smtp', lambda: s)
    return s


def test_the_plan_covers_every_together_email():
    emails = tp.plan()
    assert {e['name'] for e in emails} == EXPECTED
    assert tp.PROOF_TO == 'harrigan.tennyson@gmail.com'


def test_a_dry_run_sends_nothing(smtp, capsys):
    before = _counts()
    tp.main([])
    assert smtp.sent == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    tp.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == len(EXPECTED)
    assert all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert _counts() == before and dict(os.environ) == env_before


def test_no_proof_carries_a_live_unsubscribe_link():
    from service.config import WEB_BASE_URL
    by_name = {e['name']: e['html'] for e in tp.plan()}
    for name, html in by_name.items():
        assert f'{WEB_BASE_URL.rstrip("/")}/u/' not in html, name
    for name in ('together_answered', 'together_ready'):
        assert f'href="{tp.PROOF_LINK_DISABLED}"' in by_name[name], name
    assert 'Rivka has answered. See how you fit.' in by_name['together_answered']
    assert 'We keep your answers behind a private link' in by_name['together_summary']
