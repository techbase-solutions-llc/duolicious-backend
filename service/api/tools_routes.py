"""Together, the public routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as questions_routes is.
Playing needs no account: a player proves who they are with the
X-Tool-Token header the device keeps. Saving uses the onboardee or member
session /check-otp already issues. Every route but /tools/status answers
404 while together_live is off.
"""
from __future__ import annotations

from service.api.decorators import get


@get('/tools/status')
def get_tools_status():
    """What the web needs before it shows Together: whether it is live, and
    whether the invite email may be offered."""
    from service.tools import live, switch_on
    return (dict(live=live(), invite_email=switch_on('together_invite_email')),
            200, {'Cache-Control': 'no-store'})
