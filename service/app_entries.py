"""The app_entries switch (TEC-1845): the new in-app entries to Together,
gatherings and the Matchmaker (ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 3, release 2).

The feature switches are on in production, so an entry tied only to its
feature would reach every member the moment it deploys. Each new entry
follows its feature switch and this one, which has 3 settings in
AHAVAH_APP_ENTRIES:

  off    nobody (the default; anything that is not one of the 3 reads as
         off, so a typo fails towards showing nothing)
  owner  only the members in AHAVAH_APP_ENTRIES_ALLOW: a comma-separated
         list of person ids and addresses, an address compared normalised
         as person.normalized_email is
  on     every member

Read on every call, as the other switches are (service/campaigns/
switches.py), so production needs only the variable and a restart. The
allow list never leaves the API: GET /app-entries/status answers a member
with {enabled} alone.
"""
from __future__ import annotations

import os
from typing import Optional

from antiabuse.antispam.signupemail import normalize_email

SETTING_ENV = 'AHAVAH_APP_ENTRIES'
ALLOW_ENV = 'AHAVAH_APP_ENTRIES_ALLOW'
SETTINGS = ('off', 'owner', 'on')


def setting() -> str:
    raw = os.environ.get(SETTING_ENV, '').strip().lower()
    return raw if raw in SETTINGS else 'off'


def _allow() -> tuple[frozenset[int], frozenset[str]]:
    ids: set[int] = set()
    emails: set[str] = set()
    for entry in os.environ.get(ALLOW_ENV, '').split(','):
        entry = entry.strip()
        if not entry:
            continue
        if entry.isdigit():
            ids.add(int(entry))
        elif '@' in entry and ' ' not in entry:
            emails.add(normalize_email(entry.lower()))
    return frozenset(ids), frozenset(emails)


def enabled_for(person_id: Optional[int], email: Optional[str]) -> bool:
    """May this member see the new entries?"""
    mode = setting()
    if mode == 'on':
        return True
    if mode != 'owner':
        return False
    ids, emails = _allow()
    if person_id is not None and person_id in ids:
        return True
    return bool(email) and normalize_email(email.strip().lower()) in emails
