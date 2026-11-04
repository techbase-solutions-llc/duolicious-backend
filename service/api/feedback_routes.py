"""Public POST /feedback - general user feedback, stored + emailed to admin.

Sibling module (imported at the bottom of service/api/__init__.py).
Unauthenticated and anonymous-friendly (email is optional). Defence in depth:
  - per-IP rate limit (5/min) via the dedicated shared limiter,
  - a hidden honeypot field (`website`) — bots that fill it are silently dropped,
  - a global daily cap so a distributed flood can't spam the inbox indefinitely.
The submission is written to the `feedback` table BEFORE the email fires, so a
Resend failure never loses it.

Auth is optional (report rewards plan, 3 Nov 2026): a request with a valid
signed-in member's bearer token stores that member's person_id, so a report
we fix can be thanked in the app. A request without one, or with a token that
is invalid or not a signed-in member's, is stored anonymously exactly as
before; it is never refused for its auth.
"""

from __future__ import annotations

from typing import Optional

import duotypes as t
from service.api.decorators import apost, validate, limiter, _is_private_ip
from database import api_tx
from service.feedback import insert as insert_feedback, count_today
from emails.feedback import send_feedback_async

# Global daily cap (all IPs). Generous for a real product, tight enough that a
# botnet can't bury the admin inbox. Tune as traffic grows.
DAILY_CAP = 300

feedback_limit = limiter.shared_limit(
    "5 per minute",
    scope="feedback",
    exempt_when=_is_private_ip,
)


@apost('/feedback', auth='optional', limiter=feedback_limit)
@validate(t.PostFeedback)
def post_feedback(req: t.PostFeedback, s: Optional[t.SessionInfo]):
    # Honeypot: real users never fill `website`. Pretend success, do nothing.
    if req.website:
        return {'ok': True}

    with api_tx() as tx:
        if count_today(tx) >= DAILY_CAP:
            return {'ok': False, 'error': 'daily_limit'}, 429
        insert_feedback(
            tx,
            category=req.category,
            message=req.message,
            email=req.email,
            path=req.path,
            user_agent=req.user_agent,
            person_id=s.person_id if s is not None else None,
        )

    # Row is durable now; the email is best-effort notification on top.
    send_feedback_async(
        category=req.category,
        message=req.message,
        email=req.email,
        path=req.path,
        user_agent=req.user_agent,
    )
    return {'ok': True}
