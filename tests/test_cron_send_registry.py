"""Every cron that can send is registered, with a record of what it sent
(send safeguards plan, 2 Nov 2026, task 2).

The dormancy cron sent for a month with no record at all. This test builds
the import graph of the repo from source, takes every module
service/cron/__init__.py imports, and follows imports from each. A cron
whose closure reaches a sender must be in service/cron/send_registry.py
SENDING_CRONS, and each entry must name a dedupe or be grandfathered.

Static: no app module is imported, so this runs in the deploy's rules job.
"""
from __future__ import annotations

import ast
import sys
from collections import deque
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from send_rules_ast import ROOT, imports, module_name, parse, py_files  # noqa: E402

REGISTRY = ROOT / 'service' / 'cron' / 'send_registry.py'

# The largest each grandfathered list may be. They may shrink, never grow.
MAX_NO_DEDUPE = frozenset({
    'service.cron.autodeactivate2', 'service.cron.garbagerecords', 'service.cron.profilereporter'})
MAX_NO_SWITCH = frozenset({
    'service.cron.autodeactivate2', 'service.cron.betareengagement', 'service.cron.communityweekly',
    'service.cron.emailoutbox', 'service.cron.garbagerecords', 'service.cron.leadretention',
    'service.cron.notifications', 'service.cron.pendingdeletion', 'service.cron.profilereporter',
    'service.cron.verificationjobrunner'})
MAX_OWNER_ONLY = frozenset({'service.cron.sendguard'})
MAX_GRAPH_STOPS = frozenset({'service.spotlight.storage'})

# The names that send. Importing the module `smtp` itself (or any name but
# `guard`) counts; from service.notifications and the outbox only these.
_NOTIFICATION_SENDERS = frozenset({
    'send_to_user_safe', 'send_to_user_counted', '_send_to_user_blocking', 'notify', 'send_transactional',
    'enqueue_event_email', '_send_one', '_send_event_email_blocking', '_send_transactional_blocking'})
_OUTBOX_SENDERS = frozenset({
    'enqueue', 'enqueue_for_lead', 'enqueue_for_organiser', 'enqueue_for_recommendation',
    'enqueue_for_mentor_link', 'drain'})


def registry() -> dict:
    """The registry's literals, read without importing it."""
    out = {}
    for node in ast.parse(REGISTRY.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def _sends(mod: str, name) -> bool:
    if mod == 'smtp':
        return name != 'guard'
    if mod.startswith('smtp.'):
        return mod != 'smtp.guard'
    if mod == 'service' and name == 'notifications':
        return True
    if mod == 'service.notifications':
        return name is None or name in _NOTIFICATION_SENDERS
    if mod == 'service.campaigns' and name == 'outbox':
        return True
    if mod == 'service.campaigns.outbox':
        return name is None or name in _OUTBOX_SENDERS
    return False


@lru_cache(maxsize=None)
def graph() -> tuple[dict, dict]:
    """(edges, direct senders) over every repo module."""
    mods = {module_name(p): p for p in py_files()}
    edges, direct = {}, {}
    for m, p in mods.items():
        out, why = set(), []
        for mod, name in imports(parse(p), m):
            if _sends(mod, name):
                why.append(f'{mod}.{name}' if name else mod)
            target = f'{mod}.{name}' if name and f'{mod}.{name}' in mods else (mod if mod in mods else None)
            if target and target != m:
                out.add(target)
        edges[m] = out
        if why:
            direct[m] = why
    return edges, direct


def crons() -> list[str]:
    tree = parse(ROOT / 'service' / 'cron' / '__init__.py')
    return sorted({mod for mod, _ in imports(tree, 'service.cron')
                   if mod.startswith('service.cron.') and mod.count('.') == 2})


def reaches_a_sender(cron: str, stops) -> list[str]:
    """The import path from the cron to the first sender, or []."""
    edges, direct = graph()
    prev = {cron: None}
    q = deque([cron])
    while q:
        x = q.popleft()
        if x in direct:
            path = [x]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            return list(reversed(path))
        if x in stops:
            continue
        for y in sorted(edges.get(x, ())):
            if y not in prev:
                prev[y] = x
                q.append(y)
    return []


def test_every_cron_that_reaches_a_sender_is_registered():
    reg = registry()
    stops = set(reg['GRAPH_STOPS'])
    missing = []
    for c in crons():
        path = reaches_a_sender(c, stops)
        if path and c not in reg['SENDING_CRONS']:
            missing.append(f'{c}: ' + ' -> '.join(path))
    assert missing == [], ('Register each in service/cron/send_registry.py with its dedupe and switch:\n'
                           + '\n'.join(missing))


def test_every_registered_cron_is_a_cron():
    assert set(registry()['SENDING_CRONS']) <= set(crons())


def test_every_entry_names_a_dedupe_or_is_grandfathered():
    reg = registry()
    bad = [c for c, e in reg['SENDING_CRONS'].items()
           if not e.get('dedupe') and c not in reg['NO_DEDUPE_GRANDFATHERED']]
    assert bad == [], 'A cron that sends must keep a record of what it sent: ' + ', '.join(bad)


def test_every_entry_names_its_channel():
    assert all(e.get('channel') in ('email', 'push', 'email+push')
               for e in registry()['SENDING_CRONS'].values())


def test_the_grandfathered_lists_only_shrink():
    reg = registry()
    assert set(reg['NO_DEDUPE_GRANDFATHERED']) <= MAX_NO_DEDUPE
    assert set(reg['NO_SWITCH_GRANDFATHERED']) <= MAX_NO_SWITCH
    assert set(reg['OWNER_ONLY']) <= MAX_OWNER_ONLY
    assert set(reg['GRAPH_STOPS']) <= MAX_GRAPH_STOPS


def test_a_graph_stop_is_explained():
    assert all(isinstance(why, str) and why for why in registry()['GRAPH_STOPS'].values())


def test_the_graph_finds_the_dormancy_cron():
    """The cron that caused this: it must be found by the graph, not only by
    being listed."""
    assert reaches_a_sender('service.cron.autodeactivate2', set()) == ['service.cron.autodeactivate2']
