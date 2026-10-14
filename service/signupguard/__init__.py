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
import hmac
import ipaddress
import os
import re
import secrets
import time
import traceback
from typing import Optional, Union

from database import api_tx


# The page stamp (item 4). The sign-up page asks GET /signup-stamp for one
# when it loads and sends it back with /request-otp. A new address sent
# under STAMP_MIN_AGE_SECONDS after its stamp, or with a forged stamp, or
# with one older than STAMP_MAX_AGE_SECONDS, is refused.
#
# A MISSING stamp is refused only when AHAVAH_SIGNUP_STAMP_REQUIRED is on.
# The API deploys before the web that sends the stamp, so it stays off
# until the new web is live; a forged or too-fast stamp is refused either
# way. Existing accounts never reach this check.
#
# Signed with a key derived from SESSION_TOKEN_SECRET, the HMAC secret the
# unsubscribe and spotlight links already use. If it is unset, no stamp is
# issued and none is checked (fails open), with a log line.
STAMP_MIN_AGE_SECONDS = 2.0
STAMP_MAX_AGE_SECONDS = 86400.0
STAMP_REQUIRED: bool = os.environ.get(
    'AHAVAH_SIGNUP_STAMP_REQUIRED', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
_STAMP_LABEL = b'ahavah-signup-stamp-v1'
_STAMP_SHAPE = re.compile(r'^([0-9]{1,16})\.([0-9a-f]{64})$')
_warned_no_secret = False


# New-address limits (item 1). Fixed windows on the UTC clock hour and UTC
# day, the strategy Flask-Limiter uses for the existing OTP limits.
NEW_PER_CLIENT_HOUR = 5
NEW_PER_CLIENT_DAY = 10
NEW_PER_NETWORK_DAY = 20

# Distinct new addresses one network may ask codes for in a UTC day (item 2).
NEW_ADDRESSES_PER_NETWORK_DAY = 5

# Undeliverable domains (item 5). A DNS answer is kept for a day; a lookup
# that does not answer in time lets the code through and is not kept.
MAIL_DOMAIN_CACHE_SECONDS = 86400
DNS_LIFETIME_SECONDS = 2.0
# Never mailed (service.person._send_otp returns early), so never looked up:
# in real DNS example.com has a null MX, and the local and test sign-ups
# that use it would otherwise lose their 000000 code.
_NEVER_MAILED = frozenset({'example.com'})

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


def _stamp_key() -> Optional[bytes]:
    global _warned_no_secret
    secret = os.environ.get('SESSION_TOKEN_SECRET', '')
    if not secret:
        if not _warned_no_secret:
            print('signupguard: SESSION_TOKEN_SECRET is unset, so sign-up '
                  'stamps are neither issued nor checked')
            _warned_no_secret = True
        return None
    # A key of its own, so a stamp can never be read as any other signed
    # value made with the same secret.
    return hmac.new(secret.encode(), _STAMP_LABEL, hashlib.sha256).digest()


def _sign(key: bytes, issued_ms: str) -> str:
    return hmac.new(key, issued_ms.encode(), hashlib.sha256).hexdigest()


def issue_stamp() -> Optional[str]:
    """`<milliseconds since the epoch>.<HMAC-SHA256 hex>`, or None when no
    secret is configured."""
    key = _stamp_key()
    if key is None:
        return None
    issued_ms = str(int(_now() * 1000))
    return f'{issued_ms}.{_sign(key, issued_ms)}'


def _stamp_refusal(stamp: Optional[str]) -> Optional[str]:
    key = _stamp_key()
    if key is None:
        return None
    if not stamp:
        return 'stamp_missing' if STAMP_REQUIRED else None
    match = _STAMP_SHAPE.match(stamp)
    if match is None:
        return 'stamp_forged'
    issued_ms, signature = match.groups()
    if not hmac.compare_digest(signature.encode(), _sign(key, issued_ms).encode()):
        return 'stamp_forged'
    age = _now() - int(issued_ms) / 1000
    if age < STAMP_MIN_AGE_SECONDS:
        return 'stamp_too_fast'
    if age > STAMP_MAX_AGE_SECONDS:
        return 'stamp_expired'
    return None


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


_Q_ON_BAD_DOMAIN_LIST = """
    SELECT 1 FROM bad_email_domain WHERE domain = %(domain)s LIMIT 1
"""


def on_bad_domain_list(email: str) -> bool:
    """True when the address's domain is in bad_email_domain (loaded from
    email-domains-bad.sql). The domain is read as the existing disposable
    check reads it: everything after the last @, lower-cased."""
    domain = (email or '').strip().rpartition('@')[2].lower()
    with api_tx('read committed') as tx:
        row = tx.execute(_Q_ON_BAD_DOMAIN_LIST, dict(domain=domain)).fetchone()
    return row is not None


def _resolve_mail_domain(domain: str) -> Optional[bool]:
    """True when the domain can take mail: it has an MX record, or no MX and
    an A or AAAA record to fall back on (RFC 5321). False when it cannot: no
    such domain, a null MX (RFC 7505, the single exchange "."), or no
    record at all. None when DNS did not answer (time-out, server failure),
    which the caller treats as deliverable."""
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = DNS_LIFETIME_SECONDS
    try:
        answer = resolver.resolve(domain, 'MX')
        exchanges = [str(record.exchange).rstrip('.') for record in answer]
        return any(exchanges)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass
    except Exception:
        return None
    for rdtype in ('A', 'AAAA'):
        try:
            resolver.resolve(domain, rdtype)
            return True
        except dns.resolver.NXDOMAIN:
            return False
        except dns.resolver.NoAnswer:
            continue
        except Exception:
            return None
    return False


def _domain_refusal(normalized_email: str) -> Optional[str]:
    domain = normalized_email.rpartition('@')[2]
    if not domain or domain in _NEVER_MAILED:
        return None
    key = f'signupguard:mx:{domain}'
    try:
        cached = _redis().get(key)
    except Exception:
        cached = None
    if cached is not None:
        return None if cached == '1' else 'no_mx'
    takes_mail = _resolve_mail_domain(domain)
    if takes_mail is None:
        print(f'signupguard: DNS did not answer for {domain}, sending the code')
        return None
    try:
        _redis().set(key, '1' if takes_mail else '0', ex=MAIL_DOMAIN_CACHE_SECONDS)
    except Exception:
        pass
    return None if takes_mail else 'no_mx'


def new_address_refusal(*, normalized_email: str,
                        ip: Optional[str],
                        stamp: Optional[str] = None,
                        listed_bad: bool = False) -> Optional[str]:
    """Why a code for an address with no account should not be sent, or None
    to send it. The caller answers a refusal with `decoy()` and records it.
    Never called for an existing account.

    In order: the stamp, which costs nothing, so a request it refuses uses
    up no limit; the limits, so a source cycling through bad domains still
    spends its allowance; then the domain, `listed_bad` meaning it is on the
    bad-domain list, and last the DNS lookup."""
    return (
        _stamp_refusal(stamp)
        or _limit_refusal(ip)
        or _distinct_address_refusal(ip, normalized_email)
        or ('bad_domain' if listed_bad else None)
        or _domain_refusal(normalized_email)
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
