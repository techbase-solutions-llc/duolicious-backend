"""The dormancy cron in dry run (TEC-1607: inactive profiles stay visible).

A dry run hides nobody, so it must email nobody. Until 2 Nov 2026 it still
sent "Your Ahavah profile is resting" to the same 8 members every 10 minutes:
39,055 emails between 4 Oct and 2 Nov.

The job file is loaded on its own with stand-ins for the database, the mail
sender and the template, so this runs with no database or mail server."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from contextlib import asynccontextmanager

from smtp import guard as _real_guard

JOB = pathlib.Path(__file__).resolve().parents[1] / 'service' / 'cron' / 'autodeactivate2' / '__init__.py'


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class _Tx:
    def __init__(self, rows):
        self.rows = rows
        self.params = None
        self.in_no_send = None

    async def execute(self, query, params):
        self.params = params
        self.in_no_send = _real_guard.in_no_send()
        return _Cursor(self.rows)


def _load_job(monkeypatch, tx, sent):
    @asynccontextmanager
    async def api_tx():
        yield tx

    stubs = {
        'database.asyncdatabase': types.SimpleNamespace(api_tx=api_tx),
        'service.cron.autodeactivate2.sql': types.SimpleNamespace(Q_DEACTIVATE='-- query', __all__=['Q_DEACTIVATE']),
        'service.cron.autodeactivate2.template': types.SimpleNamespace(emailtemplate=lambda: '<p>resting</p>'),
        'service.cron.cronutil': types.SimpleNamespace(
            env_int=lambda name, default: default,
            print_stacktrace=None,
            MAX_RANDOM_START_DELAY=0,
        ),
        'smtp': types.SimpleNamespace(aws_smtp=types.SimpleNamespace(send=lambda **kw: sent.append(kw))),
        'smtp.guard': _real_guard,
        'emails.base': types.SimpleNamespace(mask_email=lambda e: e),
    }
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location('autodeactivate2_under_test', JOB)
    assert spec is not None and spec.loader is not None
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    return job


def _run_once(monkeypatch, dry_run: bool):
    sent = []
    tx = _Tx([{'email': 'member@gmail.com'}, {'email': 'other@yahoo.com'}])
    job = _load_job(monkeypatch, tx, sent)
    monkeypatch.setattr(job, 'DRY_RUN', dry_run)
    asyncio.run(job.autodeactivate2_once())
    return sent, tx


def test_dry_run_emails_nobody(monkeypatch):
    sent, tx = _run_once(monkeypatch, dry_run=True)
    assert tx.params == {'dry_run': True}
    assert sent == []


def test_a_real_run_still_emails_each_member_once(monkeypatch):
    sent, tx = _run_once(monkeypatch, dry_run=False)
    assert tx.params == {'dry_run': False}
    assert [s['to_addr'] for s in sent] == ['member@gmail.com', 'other@yahoo.com']
    assert all(s['subject'] == 'Your Ahavah profile is resting' for s in sent)


def test_a_dry_run_runs_inside_the_send_guards_tripwire(monkeypatch):
    """Send safeguards (2 Nov 2026): the whole dry run is inside no_send(),
    so any send it makes raises and alerts, whatever the code does."""
    _, tx = _run_once(monkeypatch, dry_run=True)
    assert tx.in_no_send is True


def test_a_real_run_is_not(monkeypatch):
    _, tx = _run_once(monkeypatch, dry_run=False)
    assert tx.in_no_send is False
