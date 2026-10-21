"""Leaders asking Ahavah to come to their gathering (TEC-1845, "Invite
Ahavah"). No email is sent: the request waits in Admin > Events. Deleted
12 months after its last change (service/events/retention.py).

Takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from typing import Optional

from service.events import EventError


def record_request(tx, body: dict) -> int:
    from service.events.fields import clean_text
    from service.leads import clean_email

    def text(key: str, max_len: int) -> str:
        try:
            return clean_text(body.get(key), max_len)
        except EventError:
            raise EventError(f'bad_{key}', 400)

    cleaned = clean_email(body.get('contact_email'))
    if cleaned is None:
        raise EventError('bad_email', 400)
    numbers: Optional[int] = body.get('numbers')
    if numbers is not None and (isinstance(numbers, bool) or not isinstance(numbers, int)
                                or not 1 <= numbers <= 100000):
        raise EventError('bad_numbers', 400)
    return tx.execute(
        """INSERT INTO ahavah_invite_request (gathering, dates, place, numbers, contact_name, contact_email)
           VALUES (%(g)s, %(d)s, %(p)s, %(n)s, %(cn)s, %(ce)s) RETURNING id""",
        dict(g=text('gathering', 200), d=text('dates', 120), p=text('place', 200), n=numbers,
             cn=text('contact_name', 80), ce=cleaned[0])).fetchone()['id']
