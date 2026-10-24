"""Members' private messages never reach Sentry (TEC-1845, report messages
review SEC-4). Sentry records each frame's local variables with an
exception. The route that shows a report's messages holds up to 25 of them
in its locals, so a failure there (a lock timeout at commit, say) would copy
them into a third-party error tracker. The scrubber drops the local
variables of every frame in the modules that read message text."""
from __future__ import annotations

from util.analytics import _scrub_pii


def _event(module: str, function: str) -> dict:
    return {'exception': {'values': [{'stacktrace': {'frames': [
        {'module': 'flask.app', 'function': 'dispatch_request', 'vars': {'rule': '/x'}},
        {'module': module, 'function': function,
         'vars': {'rows': [{'search_body': 'shalom, are you free on sunday'}], 'reporter': 'u'}},
    ]}}]}}


def test_the_report_messages_route_frames_lose_their_locals():
    out = _scrub_pii(_event('service.api.admin.moderation_routes', 'get_report_messages'), {})
    frames = out['exception']['values'][0]['stacktrace']['frames']
    assert 'vars' not in frames[1]
    assert 'shalom' not in repr(out)
    # Other frames keep theirs, for debugging.
    assert frames[0]['vars'] == {'rule': '/x'}


def test_the_message_text_helpers_lose_theirs_too():
    out = _scrub_pii(_event('antiabuse.lodgereport', 'message_text'), {})
    assert 'shalom' not in repr(out)


def test_an_ordinary_frame_keeps_its_locals():
    out = _scrub_pii(_event('service.api.admin.growth_routes', 'get_growth'), {})
    assert 'shalom' in repr(out)


def test_email_is_still_redacted():
    assert _scrub_pii({'user': {'email': 'a@b.c'}}, {}) == {'user': {'email': '[REDACTED]'}}
