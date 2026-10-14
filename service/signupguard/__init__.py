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

import hashlib
import ipaddress
import os
import secrets
import time
import traceback
from typing import Optional, Union

from database import api_tx


# New-address limits (item 1). Fixed windows on the UTC clock hour and UTC
# day, the strategy Flask-Limiter uses for the existing OTP limits.
NEW_PER_CLIENT_HOUR = 5
NEW_PER_CLIENT_DAY = 10
NEW_PER_NETWORK_DAY = 20

# Distinct new addresses one network may ask codes for in a UTC day (item 2).
NEW_ADDRESSES_PER_NETWORK_DAY = 5

_REDIS_HOST = os.environ.get('DUO_REDIS_HOST', 'redis')
_REDIS_PORT = int(os.environ.get('DUO_REDIS_PORT', 6379))
_redis_client = None


def _redis():
    """The Redis the API's rate limits already live in. Short timeouts: a
    slow Redis must not hold up a sign-in."""
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.Redis(
            host=_REDIS_HOST,
            port=_REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    return _redis_client


def _now() -> float:
    return time.time()


_Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _address(ip: Optional[str]) -> Optional[_Address]:
    """The client address, with an IPv4-mapped IPv6 address read as its
    IPv4 address. None for anything that does not parse."""
    try:
        addr = ipaddress.ip_address(ip or '')
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        return addr.ipv4_mapped
    return addr


def network_of(ip: Optional[str]) -> Optional[str]:
    """The network an address belongs to for counting: the IPv4 /24 or the
    IPv6 /64. None for anything that does not parse."""
    addr = _address(ip)
    if addr is None:
        return None
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f'{addr}/{prefix}', strict=False))


def _limits_exempt(ip: Optional[str]) -> bool:
    """Private and loopback addresses are exempt, as they are from the shared
    OTP limits in service/api/decorators.py (local runs and CI), and so is
    everything when the test/input switch that turns IP limits off is set."""
    from service.api import decorators
    if decorators.disable_ip_rate_limit():
        return True
    addr = _address(ip)
    return addr is not None and (addr.is_private or addr.is_loopback)


def _limit_refusal(ip: Optional[str]) -> Optional[str]:
    """Count one new-address request against its client address and its
    network, and name the first limit it goes over. Fails open: if Redis
    cannot be reached, nobody is refused for it."""
    if _limits_exempt(ip):
        return None
    addr = _address(ip)
    network = network_of(ip)
    if addr is None or network is None:
        return None
    t = _now()
    hour, day = int(t // 3600), int(t // 86400)
    counters = (
        (f'signupguard:client:{addr}:h{hour}', 3600, NEW_PER_CLIENT_HOUR, 'ip_hour'),
        (f'signupguard:client:{addr}:d{day}', 86400, NEW_PER_CLIENT_DAY, 'ip_day'),
        (f'signupguard:network:{network}:d{day}', 86400, NEW_PER_NETWORK_DAY, 'network_day'),
    )
    try:
        pipe = _redis().pipeline()
        for key, window, _, _ in counters:
            pipe.incr(key)
            pipe.expire(key, window + 60)
        counts = pipe.execute()[0::2]
    except Exception:
        print('signupguard: Redis unreachable, new-address limits not applied:')
        print(traceback.format_exc())
        return None
    for (_, _, limit, reason), count in zip(counters, counts):
        if int(count) > limit:
            return reason
    return None


def _distinct_address_refusal(ip: Optional[str],
                              normalized_email: str) -> Optional[str]:
    """Hold one network to NEW_ADDRESSES_PER_NETWORK_DAY different new
    addresses a day. An address already among them may ask again; a refused
    one is not kept, so it takes no place. The set holds a hash of each
    address, never the address. Fails open, like the limits."""
    if _limits_exempt(ip):
        return None
    network = network_of(ip)
    if network is None:
        return None
    day = int(_now() // 86400)
    key = f'signupguard:addresses:{network}:d{day}'
    member = hashlib.sha256(normalized_email.encode()).hexdigest()[:32]
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.sadd(key, member)
        pipe.scard(key)
        pipe.expire(key, 86400 + 60)
        added, size, _ = pipe.execute()
        if int(added) and int(size) > NEW_ADDRESSES_PER_NETWORK_DAY:
            r.srem(key, member)
            return 'network_addresses'
    except Exception:
        print('signupguard: Redis unreachable, distinct-address rule not applied:')
        print(traceback.format_exc())
    return None


def new_address_refusal(*, email: str, normalized_email: str,
                        ip: Optional[str]) -> Optional[str]:
    """Why a code for an address with no account should not be sent, or None
    to send it. The caller answers a refusal with `decoy()` and records it.
    Never called for an existing account."""
    return (
        _limit_refusal(ip)
        or _distinct_address_refusal(ip, normalized_email)
    )


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
