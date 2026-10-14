"""Free bot protection for sign-in codes sent to new addresses.

TEC-1848, docs/superpowers/plans/2026-10-13-free-signup-bot-protection.md.
In the 30 days to 13 Oct 2026, 151 sign-up codes went to addresses that
never entered them, 61 of them from 3 IP addresses. Codes mailed to
strangers draw spam complaints, and complaints hurt the delivery of the
codes members are waiting for.

Every rule here applies only to an address with no account. A member
signing in, admins included, goes through /request-otp exactly as before.

A request the server refuses gets the same answer as a real send (a
session token, status 200) and no email, so a refused caller learns
nothing. It is logged and counted in `otp_request`, apart from the codes
that were issued, which is what Admin > System reads.
"""
from __future__ import annotations

import ipaddress
import secrets
import traceback
from typing import Optional

from database import api_tx


def network_of(ip: Optional[str]) -> Optional[str]:
    """The network an address belongs to for counting: the IPv4 /24 or the
    IPv6 /64. An IPv4-mapped IPv6 address counts as its IPv4 address. None
    for anything that does not parse."""
    try:
        addr = ipaddress.ip_address(ip or '')
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f'{addr}/{prefix}', strict=False))


_Q_HAS_ACCOUNT = """
    SELECT 1 FROM person WHERE normalized_email = %(normalized_email)s LIMIT 1
"""

_Q_RECORD = """
    INSERT INTO otp_request (new_address, refused, session_token_hash)
    VALUES (%(new_address)s, %(refused)s, %(session_token_hash)s)
"""

_Q_ENTERED = """
    UPDATE otp_request
       SET entered_at = NOW(),
           session_token_hash = NULL
     WHERE session_token_hash = %(session_token_hash)s
       AND entered_at IS NULL
"""


def has_account(normalized_email: str) -> bool:
    """True when a person row holds this address. Matched on the
    normalised address, as /request-otp matches the session to its person."""
    with api_tx('read committed') as tx:
        row = tx.execute(
            _Q_HAS_ACCOUNT, dict(normalized_email=normalized_email)).fetchone()
    return row is not None


def decoy() -> dict:
    """The answer a refused request gets: the shape of a real send, with a
    token no session holds."""
    return dict(session_token=secrets.token_hex(64))


def _write(query: str, params: dict) -> None:
    """Counting is best-effort in its own transaction: a failure here must
    never fail a sign-in or the code request it is counting."""
    try:
        with api_tx() as tx:
            tx.execute(query, params)
    except Exception:
        print('signupguard: could not record:')
        print(traceback.format_exc())


def record_issued(session_token_hash: str, new_address: bool) -> None:
    _write(_Q_RECORD, dict(
        new_address=new_address, refused=None,
        session_token_hash=session_token_hash))


def record_entered(session_token_hash: str) -> None:
    _write(_Q_ENTERED, dict(session_token_hash=session_token_hash))


def record_refusal(reason: str, new_address: bool, email: str,
                   ip: Optional[str]) -> None:
    from emails.base import mask_email
    print(
        f'signupguard: refused {reason}, new_address={new_address}, '
        f'to {mask_email(email)} from network {network_of(ip) or "<unknown>"}'
    )
    _write(_Q_RECORD, dict(
        new_address=new_address, refused=reason, session_token_hash=None))
