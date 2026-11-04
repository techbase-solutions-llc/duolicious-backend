"""A trial run sends nothing (send safeguards plan, 2 Nov 2026, task 2).

The dormancy cron's dry run emailed the same members every 10 minutes for a
month. This file has one test per trial-run flag in the code: each runs
with the flag on and the provider, the push sender and the outbox replaced
by recorders, and asserts nothing reached any of them.

A scan finds every module-level DRY_RUN, every environment variable whose
name contains DRY_RUN, DRYRUN or SHADOW, and every argparse --dry-run or
--dry flag. The set must equal FLAGS below, so a new flag without a test
here fails. A trial mode spelt some other way (a ?dry=1 query string, say)
gets past the scan; the send guard's limits are the backstop there
(docs/runbooks/mail-guard.md).

Extends tests/test_autodeactivate2_dry_run.py and
tests/test_campaign_dry_run.py rather than replacing them."""
from __future__ import annotations

import ast
import asyncio
import importlib
import re
import runpy
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from send_rules_ast import ROOT, calls, call_name, parse, py_files, rel  # noqa: E402

_FLAG_NAME = re.compile(r'DRY_?RUN|SHADOW')

# Every trial-run flag the scan finds: (what, file, name). Each has a test
# below, or a note saying why it is not a trial run of a sender.
FLAGS = {
    ('module', 'service/cron/autodeactivate2/__init__.py', 'DRY_RUN'),
    ('module', 'service/cron/photocleaner/__init__.py', 'DRY_RUN'),
    ('module', 'service/cron/audiocleaner/__init__.py', 'DRY_RUN'),
    ('module', 'service/cron/checkphotos/__init__.py', 'DRY_RUN'),
    ('env', 'service/cron/autodeactivate2/__init__.py', 'DUO_CRON_AUTODEACTIVATE2_DRY_RUN'),
    ('env', 'service/cron/photocleaner/__init__.py', 'DUO_CRON_PHOTO_CLEANER_DRY_RUN'),
    ('env', 'service/cron/audiocleaner/__init__.py', 'DUO_CRON_AUDIO_CLEANER_DRY_RUN'),
    ('env', 'service/cron/checkphotos/__init__.py', 'DUO_CRON_CHECK_PHOTOS_DRY_RUN'),
    # The send guard's own trial week for its global ceilings: not a trial
    # run of a sender. tests/test_send_guard.py covers it.
    ('env', 'smtp/guard.py', 'AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL'),
    # Placeholders a campaign dry run builds with (run_campaign(send=False)):
    # never stored, never sent. tests/test_campaign_dry_run.py covers them.
    ('module', 'service/campaigns/__init__.py', 'DRY_RUN_LINK_KEY'),
    ('module', 'service/spotlight/__init__.py', 'DRY_RUN_NONCE'),
    ('argparse', 'emails/send_spotlight_candidates_note.py', '--dry-run'),
    ('argparse', 'emails/send_warm_leads_note.py', '--dry-run'),
    ('argparse', 'scripts/backfill_like_alerts.py', '--dry-run'),
    ('argparse', 'scripts/backfill_referral_click_inviter.py', '--dry-run'),
    ('argparse', 'scripts/mint_missing_referral_codes.py', '--dry-run'),
    ('argparse', 'scripts/push_reactivation.py', '--dry-run'),
    ('argparse', 'scripts/reactivate_dormant.py', '--dry-run'),
    ('argparse', 'scripts/regenerate_roundup.py', '--dry-run'),
}

_ENV_READERS = ('environ.get', 'getenv', 'env_int', 'env_bool', 'environ.setdefault')


def scan() -> set[tuple[str, str, str]]:
    found = set()
    for path in py_files():
        r = rel(path)
        tree = parse(path)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and _FLAG_NAME.search(t.id) and t.id.isupper():
                        found.add(('module', r, t.id))
        for call in calls(tree):
            n = call_name(call)
            if any(n.endswith(e) for e in _ENV_READERS) and call.args:
                a = call.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and _FLAG_NAME.search(a.value):
                    found.add(('env', r, a.value))
            if n.endswith('add_argument'):
                for a in call.args:
                    if isinstance(a, ast.Constant) and a.value in ('--dry-run', '--dry'):
                        found.add(('argparse', r, a.value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str) and _FLAG_NAME.search(node.slice.value)
                    and call_name(ast.Call(func=node.value, args=[], keywords=[])).endswith('environ')):
                found.add(('env', r, node.slice.value))
    return found


def test_every_trial_run_flag_has_a_test_here():
    assert scan() == FLAGS


# ---------------------------------------------------------------------------
# the recorders
# ---------------------------------------------------------------------------

@pytest.fixture
def reached(monkeypatch):
    """Everything that would have left the system."""
    import smtp
    from service import notifications
    from service.campaigns import outbox
    hits: list[str] = []
    monkeypatch.setattr(smtp.Smtp, '_try_send', lambda self, **kw: hits.append(f"email {kw.get('subject')}"))
    monkeypatch.setattr(notifications, '_send_one', lambda *a, **k: hits.append('push'))
    for name in ('enqueue', 'enqueue_for_lead', 'enqueue_for_organiser', 'enqueue_for_recommendation',
                 'enqueue_for_mentor_link', 'enqueue_for_onboardee'):
        if hasattr(outbox, name):
            monkeypatch.setattr(outbox, name, lambda *a, _n=name, **k: hits.append(f'outbox {_n}'))
    return hits


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class _Tx:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, *a, **k):
        return _Cursor(self.rows)

    async def executemany(self, *a, **k):
        return None


def _fake_api_tx(rows):
    @asynccontextmanager
    async def api_tx(*a, **k):
        yield _Tx(rows)
    return api_tx


_MEMBERS = [dict(email=f'dry{i}@ahavah-test.invalid', uuid=f'00000000-0000-0000-0000-00000000000{i}', id=i)
            for i in range(3)]


# ---------------------------------------------------------------------------
# the crons
# ---------------------------------------------------------------------------

def _cron(monkeypatch, module):
    mod = importlib.import_module(module)
    monkeypatch.setattr(mod, 'DRY_RUN', True)
    monkeypatch.setattr(mod, 'api_tx', _fake_api_tx(_MEMBERS))
    return mod


def test_the_dormancy_dry_run_sends_nothing(monkeypatch, reached):
    mod = _cron(monkeypatch, 'service.cron.autodeactivate2')
    asyncio.run(mod.autodeactivate2_once())
    assert reached == []


@pytest.mark.parametrize('module,once,deleter', [
    ('service.cron.photocleaner', 'clean_photos_once', 'delete_images_from_object_store'),
    ('service.cron.audiocleaner', 'clean_audio_once', 'delete_audio_from_object_store'),
])
def test_a_cleaner_dry_run_sends_nothing(monkeypatch, reached, module, once, deleter):
    mod = _cron(monkeypatch, module)
    deleted = []

    async def _delete(**kw):
        deleted.append(kw)

    monkeypatch.setattr(mod, deleter, _delete)
    asyncio.run(getattr(mod, once)())
    assert reached == []
    assert deleted and deleted[0]['dry_run'] is True


def test_the_photo_check_dry_run_sends_nothing(monkeypatch, reached):
    mod = _cron(monkeypatch, 'service.cron.checkphotos')
    uuids = [m['uuid'] for m in _MEMBERS]

    async def _resolve(chunk):
        return chunk, []

    async def _download(chunk):
        return []

    async def _delete(*a, **k):
        return None

    monkeypatch.setattr(mod, 'list_uuids_in_object_store', lambda: iter([uuids]))
    monkeypatch.setattr(mod, 'resolve_uuids', _resolve)
    monkeypatch.setattr(mod, 'download_450_images', _download)
    monkeypatch.setattr(mod, 'compute_blurhashes', lambda images: ['h'] * len(uuids))
    monkeypatch.setattr(mod, 'delete_images_from_object_store', _delete)
    asyncio.run(mod.check_photos_once())
    assert reached == []


# ---------------------------------------------------------------------------
# the scripts, run as their operators run them, against the test database
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('module,argv', [
    ('emails.send_spotlight_candidates_note', ['--dry-run']),
    ('emails.send_warm_leads_note', ['--dry-run']),
])
def test_a_campaign_script_dry_run_sends_nothing(reached, module, argv):
    importlib.import_module(module).main(argv)
    assert reached == []


@pytest.mark.parametrize('module,argv', [
    ('scripts.backfill_like_alerts', ['--dry-run']),
    ('scripts.backfill_referral_click_inviter', ['--dry-run']),
    ('scripts.mint_missing_referral_codes', ['--dry-run']),
    ('scripts.regenerate_roundup', ['--week', '2026-W01', '--dry-run']),
])
def test_a_backfill_dry_run_sends_nothing(monkeypatch, reached, module, argv):
    """main() takes no argv here; it reads sys.argv."""
    monkeypatch.setattr(sys, 'argv', [module, *argv])
    try:
        importlib.import_module(module).main()
    except SystemExit as e:
        assert e.code in (None, 0) or isinstance(e.code, str)   # a refusal message, not a crash
    assert reached == []


@pytest.mark.parametrize('path,argv', [
    ('scripts/push_reactivation.py', ['--dry-run']),
    ('scripts/reactivate_dormant.py', ['--dry-run']),
])
def test_an_inline_script_dry_run_sends_nothing(monkeypatch, reached, path, argv):
    """These have no main(): they run as __main__, as an operator runs them."""
    monkeypatch.setattr(sys, 'argv', [path, *argv])
    runpy.run_path(str(ROOT / path), run_name='__main__')
    assert reached == []
