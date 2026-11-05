"""The Gmail API, read only, as the support mailbox (TEC-2115).

A Google service account with domain-wide delegation for the single scope
gmail.readonly signs in as the mailbox (`subject`). google-auth makes and
refreshes the access token; the four calls below are plain HTTPS through its
AuthorizedSession. Nothing here can change the mailbox: the scope allows
reading only.

Imported only when the switch is on and the key file exists, so the api and
the tests never load google-auth. Tests never call Google: they pass a fake
client to service.support_inbox.tick.
"""
from __future__ import annotations

from typing import Optional

from service.support_inbox import BACKFILL_QUERY, SCOPE, GmailError, HistoryExpired

BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'
TIMEOUT_SECONDS = 30


class GmailApi:
    def __init__(self, key_path: str, mailbox: str):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=[SCOPE], subject=mailbox)
        self._session = AuthorizedSession(creds)

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        r = self._session.get(f'{BASE}{path}', params=params or {}, timeout=TIMEOUT_SECONDS)
        if r.status_code == 404 and path == '/history':
            raise HistoryExpired()
        if r.status_code != 200:
            raise GmailError(r.status_code)
        return r.json()

    def current_history_id(self) -> str:
        return str(self._get('/profile')['historyId'])

    def list_message_ids(self, page_token: Optional[str]) -> tuple[list[str], Optional[str]]:
        params = dict(q=BACKFILL_QUERY, maxResults=100)
        if page_token:
            params['pageToken'] = page_token
        out = self._get('/messages', params)
        return [str(m['id']) for m in out.get('messages') or []], out.get('nextPageToken')

    def history(self, start_history_id: str,
                page_token: Optional[str]) -> tuple[list[dict], Optional[str], str]:
        params = dict(startHistoryId=start_history_id, historyTypes='messageAdded', maxResults=500)
        if page_token:
            params['pageToken'] = page_token
        out = self._get('/history', params)
        added = [dict(id=str(a['message']['id']), labelIds=a['message'].get('labelIds') or [])
                 for h in out.get('history') or []
                 for a in h.get('messagesAdded') or []]
        return added, out.get('nextPageToken'), str(out.get('historyId') or start_history_id)

    def get_message(self, message_id: str) -> dict:
        return self._get(f'/messages/{message_id}', dict(format='full'))
