"""Rules the code cannot break (send safeguards plan, 2 Nov 2026, task 2).

Pure source scans: these import no app module, so the deploy's `rules` job
runs them on a bare GitHub runner (pytest and pyyaml only, --noconftest)
and a failure stops the deploy. They also run in the container suite.

Every email must end in smtp.Smtp.send and every web push in
service.notifications._send_one, where the send guard sits. These tests
refuse code that goes around either."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from send_rules_ast import (ROOT, call_name, calls, files, imports, module_name,  # noqa: E402
                            names_used, parse, py_files, rel)

SMTP_INIT = 'smtp/__init__.py'
NOTIFICATIONS = 'service/notifications/__init__.py'
NOTIFY = 'notify/__init__.py'

# Callers of _send_one outside service/notifications. Frozen: it may shrink,
# never grow. send_proofs sends the owner's push proofs; _send_one itself
# runs the guard's tripwire and global push ceiling.
SEND_ONE_ALLOWED = frozenset({'scripts/send_proofs.py'})

# What a module imports that makes it a sender, for the thread rule.
SENDING_MODULES = ('smtp', 'service.notifications', 'service.campaigns.outbox')


def _outside(path: Path, *allowed: str) -> bool:
    r = rel(path)
    return r not in allowed and not r.startswith('smtp/')


def test_nothing_outside_the_mailer_talks_to_a_mail_provider():
    bad = []
    for path in py_files():
        if not _outside(path, SMTP_INIT):
            continue
        tree = parse(path)
        for mod, _ in imports(tree, module_name(path)):
            if mod == 'smtplib' or mod.startswith('smtplib.'):
                bad.append(f'{rel(path)} imports smtplib')
        for name in names_used(tree):
            if name in ('_try_send', '_try_send_resend_api', 'RESEND_API_URL'):
                bad.append(f'{rel(path)} uses {name}')
        for call in calls(tree):
            if call_name(call).split('.')[-1] == 'Smtp':
                bad.append(f'{rel(path)} constructs Smtp(); use smtp.make_aws_smtp() or aws_smtp')
    assert bad == [], 'Send through smtp.Smtp.send, where the send guard is:\n' + '\n'.join(sorted(set(bad)))


def test_no_file_of_any_kind_calls_the_resend_api_but_the_mailer():
    bad = [rel(p) for p in files(('.py', '.sh', '.js', '.mjs', '.ts'))
           if rel(p) != SMTP_INIT and 'api.resend.com' in p.read_text(encoding='utf-8', errors='replace')]
    assert bad == [], 'api.resend.com outside smtp/__init__.py: ' + ', '.join(bad)


def test_nothing_outside_notifications_pushes_to_a_device():
    bad = []
    for path in py_files():
        r = rel(path)
        if r == NOTIFICATIONS:
            continue
        tree = parse(path)
        for mod, name in imports(tree, module_name(path)):
            if mod.split('.')[0] == 'pywebpush':
                bad.append(f'{r} imports pywebpush')
            if mod == 'service.notifications' and name == '_send_one' and r not in SEND_ONE_ALLOWED:
                bad.append(f'{r} imports _send_one')
        for call in calls(tree):
            n = call_name(call)
            if n == 'webpush' or n.endswith('.webpush'):
                bad.append(f'{r} calls webpush()')
            if n.endswith('notifications._send_one') and r not in SEND_ONE_ALLOWED:
                bad.append(f'{r} calls notifications._send_one')
    assert bad == [], 'Push through service.notifications, where the send guard is:\n' + '\n'.join(sorted(set(bad)))


def test_the_send_one_allow_list_only_shrinks():
    assert SEND_ONE_ALLOWED <= frozenset({'scripts/send_proofs.py'})


def test_expo_push_is_reached_only_through_enqueue_mobile_notification():
    bad = []
    for path in py_files():
        r = rel(path)
        if r == NOTIFY:
            continue
        tree = parse(path)
        for mod, name in imports(tree, module_name(path)):
            if mod == 'notify' and name in ('process_notification_batch', '_batcher'):
                bad.append(f'{r} imports notify.{name}')
        if 'process_notification_batch' in set(names_used(tree)):
            bad.append(f'{r} uses process_notification_batch')
    assert bad == [], 'Expo push goes around the send guard; do not add callers:\n' + '\n'.join(sorted(set(bad)))


def _is_sending_module(tree: ast.AST, modname: str) -> bool:
    for mod, name in imports(tree, modname):
        if mod in SENDING_MODULES or any(mod.startswith(m + '.') for m in SENDING_MODULES):
            return True
        if mod == 'service' and name == 'notifications':
            return True
        if mod == 'service.campaigns' and name == 'outbox':
            return True
    return False


def test_a_module_that_sends_starts_its_threads_through_guard_spawn():
    """A bare threading.Thread does not carry context variables, so the
    dry-run tripwire would not reach a send made on it."""
    bad = []
    for path in py_files():
        r = rel(path)
        if r.startswith('smtp/'):
            continue        # smtp/guard.py is the one allowed caller
        tree = parse(path)
        if not _is_sending_module(tree, module_name(path)):
            continue
        thread_names = {'threading.Thread'}
        for mod, name in imports(tree, module_name(path)):
            if mod == 'threading' and name == 'Thread':
                thread_names.add('Thread')
        for call in calls(tree):
            if call_name(call) in thread_names:
                bad.append(f'{r}:{call.lineno}')
    assert bad == [], 'Use smtp.guard.spawn in a module that sends:\n' + '\n'.join(bad)


def test_every_send_otp_call_names_its_kind():
    bad = []
    for path in py_files():
        tree = parse(path)
        for call in calls(tree):
            if call_name(call).split('.')[-1] == '_send_otp':
                if 'kind' not in {k.arg for k in call.keywords}:
                    bad.append(f'{rel(path)}:{call.lineno}')
    assert bad == [], '_send_otp needs kind=sign_in_code or kind=change_email_code:\n' + '\n'.join(bad)


def test_send_otp_hands_its_kind_to_the_mailer():
    tree = parse(ROOT / 'service' / 'person' / '__init__.py')
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_send_otp')
    sends = [c for c in calls(fn) if call_name(c).endswith('.send')]
    assert sends and all(any(k.arg == 'kind' and isinstance(k.value, ast.Name) and k.value.id == 'kind'
                             for k in c.keywords) for c in sends)


def test_these_rule_tests_import_nothing_but_the_standard_library_pytest_and_yaml():
    """The deploy's rules job has only pytest and pyyaml. A rule test that
    imports app code would quietly stop working there."""
    here = Path(__file__).resolve().parent
    allowed_roots = set(sys.stdlib_module_names) | {'pytest', 'yaml', 'send_rules_ast', 'test_cron_send_registry', '__future__'}
    bad = []
    for name in ('test_send_rules_static.py', 'test_cron_send_registry.py',
                 'test_send_switches_default_off.py', 'send_rules_ast.py'):
        tree = ast.parse((here / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                roots = [(node.module or '').split('.')[0]]
            else:
                continue
            bad += [f'{name} imports {r}' for r in roots if r not in allowed_roots]
    assert bad == [], '\n'.join(bad)


# Kinds that pass every halt and ceiling (smtp/guard.py ESSENTIAL_KINDS and
# GUARD_ALERT_KIND). Any caller could name one and go around the guard, so
# only these files may (review, 2 Nov 2026). The lists may shrink.
PRIVILEGED_KINDS = {
    'sign_in_code': frozenset({'smtp/guard.py', 'service/person/__init__.py', 'service/your_ahavah/__init__.py'}),
    'change_email_code': frozenset({'smtp/guard.py', 'service/person/__init__.py'}),
    'guard_alert': frozenset({'smtp/guard.py'}),
}
PRIVILEGED_NAMES = {
    'GUARD_ALERT_KIND': frozenset({'smtp/guard.py', 'service/sendguard/__init__.py'}),
    'ESSENTIAL_KINDS': frozenset({'smtp/guard.py'}),
}


def test_only_the_code_and_alert_senders_name_a_kind_that_passes_every_halt():
    bad = []
    for path in py_files():
        r = rel(path)
        tree = parse(path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in PRIVILEGED_KINDS and r not in PRIVILEGED_KINDS[node.value]):
                bad.append(f'{r}:{node.lineno} names {node.value!r}')
        for name in names_used(tree):
            if name in PRIVILEGED_NAMES and r not in PRIVILEGED_NAMES[name]:
                bad.append(f'{r} uses {name}')
        for mod, name in imports(tree, module_name(path)):
            if name in PRIVILEGED_NAMES and r not in PRIVILEGED_NAMES[name]:
                bad.append(f'{r} imports {name}')
    assert bad == [], 'A kind that passes every halt, named outside its sender:\n' + '\n'.join(sorted(set(bad)))


def test_the_privileged_kind_lists_only_shrink():
    assert PRIVILEGED_KINDS['sign_in_code'] <= {'smtp/guard.py', 'service/person/__init__.py',
                                                'service/your_ahavah/__init__.py'}
    assert PRIVILEGED_KINDS['change_email_code'] <= {'smtp/guard.py', 'service/person/__init__.py'}
    assert PRIVILEGED_KINDS['guard_alert'] <= {'smtp/guard.py'}
    assert PRIVILEGED_NAMES['GUARD_ALERT_KIND'] <= {'smtp/guard.py', 'service/sendguard/__init__.py'}
    assert PRIVILEGED_NAMES['ESSENTIAL_KINDS'] <= {'smtp/guard.py'}
