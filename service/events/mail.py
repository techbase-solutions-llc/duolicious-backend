"""Every gathering email (TEC-1845). Stubs until plan Task 9 fills them;
the two link builders are real from now."""
from __future__ import annotations

from typing import Optional

from service.config import WEB_BASE_URL


def confirm_url(token: str) -> str:
    """The web page that confirms by a script call, so a mail scanner
    opening the link confirms nothing."""
    return f'{WEB_BASE_URL}/rsvp/confirm/{token}'


def manage_url(token: str) -> str:
    return f'{WEB_BASE_URL}/host/gatherings?t={token}'


def queue_manage_link(tx, organiser_id: int, token: str, *, note: Optional[str] = None) -> Optional[int]:
    return None


def queue_confirm(tx, rsvp_id: int, token: str) -> Optional[int]:
    return None


def queue_change(tx, event_id: int) -> int:
    return 0


def queue_cancelled(tx, event_id: int) -> int:
    return 0
