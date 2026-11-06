"""Resend's received mail, read only (TEC-2115,
docs/plans/2026-11-05-support-inbox-via-forwarding.md).

Two calls, plain HTTPS with `requests` (Cloudflare in front of Resend
refuses urllib's TLS fingerprint; see smtp/__init__.py):

  GET https://api.resend.com/emails/receiving?limit=..&after=..   the list
  GET https://api.resend.com/emails/receiving/{id}                one email

Both need a full-access key; a sending-only key answers 401 or 403, raised
as ResendError with the status and nothing else. Resend allows 10 requests a
second per team, shared with the API's own sending, so calls here are
spaced at least MIN_INTERVAL_SECONDS apart.

Tests never call Resend: they pass a fake client to
service.support_inbox.tick, and a fake session to this class.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import quote

from service.support_inbox import ResendError

BASE = 'https://api.resend.com/emails/receiving'
TIMEOUT_SECONDS = 30
USER_AGENT = 'ahavah-backend/1.0 (support inbox)'
MIN_INTERVAL_SECONDS = 0.15


class ResendReceiving:
    def __init__(self, key: str, *, session=None):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._headers = {'Authorization': f'Bearer {key}', 'User-Agent': USER_AGENT,
                         'Accept': 'application/json'}
        self._last = 0.0

    def _get(self, url: str, params: Optional[dict] = None) -> dict:
        wait = self._last + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._session.get(url, params=params, headers=self._headers, timeout=TIMEOUT_SECONDS)
        finally:
            self._last = time.monotonic()
        if r.status_code != 200:
            raise ResendError(r.status_code)
        return r.json()

    def list_received(self, *, limit: int, after: Optional[str] = None) -> dict:
        params: dict = {'limit': max(1, min(100, int(limit)))}
        if after:
            params['after'] = after
        return self._get(BASE, params)

    def get_received(self, email_id: str) -> dict:
        return self._get(f'{BASE}/{quote(email_id, safe="")}')
