"""Every admin route that changes something writes an audit row (TEC-2091).

On 4 Nov 2026 the audit log held no ban, deactivation or token adjustment,
and nobody could say whether that meant none had happened or none had been
recorded. The owner asked for the log to be the whole record of what admins
did, kept so by a test rather than by memory.

This walks the Flask URL map, so a mutating /admin route added later is
checked without anyone listing it. For each POST, PUT, PATCH or DELETE rule
under /admin it finds the route's own function beneath the decorators and
follows its calls into Ahavah's own code (service.*) until it reaches
`record_audit` or `record_system_audit`. A route that reaches neither fails,
unless it is in `_CHANGES_NOTHING` with the reason it is allowed.

What a static walk cannot check is that the audit row shares the change's
transaction. Every route found on 4 Nov does, with one documented exception:
a campaign send runs one transaction per recipient and audits the run after
it (service/api/admin/growth_routes.py). Review keeps the rest.

The second test holds the other half of the contract: an admin GET route
that writes an audit row is a view, and its action must be one of
VIEW_ONLY_ACTIONS, which the Overview feed leaves out.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import textwrap
import types

import pytest

_MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}

# Mutating /admin routes allowed to write no audit row, each with the reason.
# Empty on 4 Nov 2026: every one of them changes something. A route belongs
# here only if it changes nothing at all, not because auditing it is awkward.
_CHANGES_NOTHING: dict[str, str] = {}

# How far to follow calls from a route into helpers. The deepest path on
# 4 Nov is the emailed ban link: route, person.post_admin_ban,
# delete_or_ban_account, _audit_email_link_bans, record_system_audit.
_MAX_DEPTH = 6


@pytest.fixture(scope='module')
def flask_app():
    import service.api  # noqa: F401  registers every route module
    from service.api.decorators import app
    return app


def _own_function(view):
    """The route's own function under the decorators. None of them use
    functools.wraps, but each keeps the function it wraps in a closure cell
    (flask-limiter's keep it as __wrapped__). The route's own function is
    the one defined at module level outside service.api.decorators."""
    seen, stack = set(), [view]
    while stack:
        f = stack.pop()
        if id(f) in seen:
            continue
        seen.add(id(f))
        if type(f) is types.FunctionType:
            if (f.__module__ != 'service.api.decorators'
                    and f.__module__.startswith('service.')
                    and f.__qualname__ == f.__name__):
                return f
            for cell in f.__closure__ or ():
                try:
                    stack.append(cell.cell_contents)
                except ValueError:
                    pass
        wrapped = getattr(f, '__wrapped__', None)
        if wrapped is not None:
            stack.append(wrapped)
    return None


def _namespace(fn, tree) -> dict:
    """The names a function's calls can mean: its module's globals, its
    closure, and anything it imports inside its own body (a common pattern
    here, to keep imports off the start-up path)."""
    ns = dict(vars(builtins))
    ns.update(fn.__globals__)
    for name, cell in zip(fn.__code__.co_freevars, fn.__closure__ or ()):
        try:
            ns[name] = cell.cell_contents
        except ValueError:
            pass
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    ns[a.asname] = importlib.import_module(a.name)
                else:
                    top = a.name.split('.')[0]
                    ns[top] = importlib.import_module(top)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mod = importlib.import_module(node.module)
            for a in node.names:
                try:
                    ns[a.asname or a.name] = getattr(mod, a.name)
                except AttributeError:
                    ns[a.asname or a.name] = importlib.import_module(f'{node.module}.{a.name}')
    return ns


def _resolve(expr, ns):
    if isinstance(expr, ast.Name):
        return ns.get(expr.id)
    if isinstance(expr, ast.Attribute):
        base = _resolve(expr.value, ns)
        if base is None:
            return None
        # `request.args` and the like are proxies that raise outside a
        # request; they are never an audit call, so anything that raises is
        # simply not followed.
        try:
            return getattr(base, expr.attr, None)
        except Exception:
            return None
    return None


def _audit_actions(fn, depth=0, seen=None) -> list:
    """The audit calls `fn` reaches, as the action each names (a string, or
    None when it is not a literal). Empty when it reaches none."""
    from service.admin import record_audit, record_system_audit
    seen = set() if seen is None else seen
    if depth > _MAX_DEPTH or fn.__code__ in seen:
        return []
    seen.add(fn.__code__)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return []
    ns = _namespace(fn, tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _resolve(node.func, ns)
        if target is record_audit or target is record_system_audit:
            action = next((k.value for k in node.keywords if k.arg == 'action'),
                          node.args[2] if len(node.args) > 2 else None)
            found.append(action.value if isinstance(action, ast.Constant) else None)
        # type(), not isinstance(): a werkzeug proxy answers isinstance by
        # looking up the object it stands for, which raises here.
        elif (type(target) is types.FunctionType
              and (target.__module__ or '').startswith('service.')):
            found += _audit_actions(target, depth + 1, seen)
    return found


def _admin_rules(app, methods):
    for r in app.url_map.iter_rules():
        if r.rule.startswith('/admin') and r.methods & methods:
            yield r


def test_every_mutating_admin_route_writes_an_audit_row(flask_app):
    rules = list(_admin_rules(flask_app, _MUTATING))
    # The walk found the routes at all (61 on 4 Nov 2026).
    assert len(rules) > 50
    missing = []
    for r in sorted(rules, key=lambda r: r.rule):
        if r.rule in _CHANGES_NOTHING:
            continue
        fn = _own_function(flask_app.view_functions[r.endpoint])
        if fn is None:
            missing.append(f'{r.rule}: could not find the route function under its decorators')
        elif not _audit_actions(fn):
            missing.append(f'{sorted(r.methods & _MUTATING)} {r.rule} ({fn.__module__}.{fn.__name__})')
    assert missing == [], (
        'These admin routes change something and write no audit row. Call '
        'record_audit in the transaction that makes the change, or, if the '
        'route changes nothing, add it to _CHANGES_NOTHING with the reason:\n'
        + '\n'.join(missing))


def test_an_admin_get_route_audits_only_view_actions(flask_app):
    from service.admin.queries.overview import VIEW_ONLY_ACTIONS
    wrong = []
    for r in _admin_rules(flask_app, {'GET'}):
        fn = _own_function(flask_app.view_functions[r.endpoint])
        if fn is None:
            continue
        for action in _audit_actions(fn):
            if action not in VIEW_ONLY_ACTIONS:
                wrong.append(f'{r.rule}: {action!r}')
    assert wrong == [], (
        'An admin GET route audits an action the Overview feed does not know '
        'is a view. Add it to VIEW_ONLY_ACTIONS (service/admin/queries/'
        'overview.py) so it stays out of Recent activity:\n' + '\n'.join(wrong))


def test_the_walk_sees_an_audit_call_and_misses_a_route_without_one():
    """The walk itself: a route that audits through a helper is seen, and a
    route that changes something without auditing is not."""
    from service.api.admin import events_routes, system_routes
    assert _audit_actions(_own_function(events_routes.post_admin_event_pause)) == [None]
    assert 'mail_guard.clear' in _audit_actions(_own_function(system_routes.post_mail_guard_clear))

    def changes_but_never_audits():
        from service import sendguard
        sendguard.clear_halt('email', None, by='nobody')
    assert _audit_actions(changes_but_never_audits) == []
