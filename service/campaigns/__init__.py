"""Campaign email send log, per-member frequency cap, and click links.

Spec 3.5: at most one campaign email per member per 7 days (E4/E5 are
member-triggered and exempt); each send carries a campaign_id so a
retried request cannot send twice. Spec 3.4: every CTA is a /s/<key>
link that counts clicks."""
from __future__ import annotations

import re
import secrets
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from service.config import WEB_BASE_URL

# Hosts a campaign link may target when a caller opts into `external_ok`
# (spec 3.4/3.5, E5): the platforms a Spotlight post can actually live on.
# Never widen this without also confirming the platform's URL shape can't be
# abused as an open redirect (see make_campaign_link's docstring).
ALLOWED_EXTERNAL_HOSTS = ('www.facebook.com', 'www.instagram.com')

# The emails that tell a member something happened to them: a like, a match,
# a message. They go through the outbox and the send log like any campaign
# (health review, 13 Oct 2026, finding 63), but they are not campaign mail:
# they are queued `exempt`, so the cap never holds one back, and the cap
# below never counts one, so a busy week of matches cannot hold back E2.
TRANSACTIONAL_CAMPAIGNS = ('like', 'match', 'message')

# The mail held for the owner's proof in Wave 3 (service/campaigns/held.py),
# and the referral intro. Each keeps its own cadence where it is queued, and
# is queued `exempt`. It neither counts toward nor is held back by E2 and the
# admin-run campaigns' caps: E2 goes to every member every Monday, so
# anything else on a 7 day cap meets it and is skipped (30 referral intros
# were, from 1 Oct). The weekly nudges among them keep a gap between
# themselves instead (held.py); the referral intro's send log keeps it to
# once per member (service/cron/referralintro). The owner's note to the
# Spotlight candidates goes to each member once ever
# (emails/send_spotlight_candidates_note.py), so it neither waits behind E2
# nor holds the next E2 back.
SELF_CAPPED_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                         'match_reminder', 'message_reminder', 'friend_joined',
                         'referral', 'spotlight_note')

_TRANSACTIONAL_SQL = ', '.join(f"'{c}'" for c in TRANSACTIONAL_CAMPAIGNS + SELF_CAPPED_CAMPAIGNS)

# The two send rules, each written once and correlated to `person_ref` (a
# bind or a column), so `can_send` and `count_sendable` cannot drift apart.
def _same_run_sql(person_ref: str) -> str:
    return f"""SELECT 1 FROM email_send_log
     WHERE person_id = {person_ref} AND campaign = %(c)s AND campaign_id = %(cid)s"""

def _recent_send_sql(person_ref: str) -> str:
    return f"""SELECT 1 FROM email_send_log
     WHERE person_id = {person_ref} AND sent_at > NOW() - make_interval(days => %(d)s)
       AND campaign NOT IN ({_TRANSACTIONAL_SQL})"""

_Q_SAME_RUN = _same_run_sql('%(pid)s')
_Q_RECENT = f"{_recent_send_sql('%(pid)s')} LIMIT 1"

_Q_COUNT_SENDABLE = f"""
    SELECT count(*) AS n FROM unnest(%(ids)s::int[]) AS r(pid)
     WHERE NOT EXISTS ({_same_run_sql('r.pid')})
       AND NOT EXISTS ({_recent_send_sql('r.pid')})
"""

def can_send(tx, person_id: int, campaign: str, campaign_id: str, *,
             cap_days: int = 7, exempt: bool = False) -> bool:
    if tx.execute(_Q_SAME_RUN, dict(pid=person_id, c=campaign, cid=campaign_id)).fetchone():
        return False
    if exempt:
        return True
    return tx.execute(_Q_RECENT, dict(pid=person_id, d=cap_days)).fetchone() is None

def count_sendable(tx, person_ids: list[int], campaign: str, campaign_id: Optional[str], *,
                   cap_days: int = 7) -> int:
    """How many of `person_ids` `can_send` would pass right now, in one
    query: the admin's "would reach now" (health review, 13 Oct 2026; the
    Growth tab used to show the cohort before the cap, 59 for an e2 send
    that would have queued nobody). `campaign_id` is the id a send pressed
    now would use, or None for a fresh one, which no member has yet."""
    return int(tx.execute(_Q_COUNT_SENDABLE, dict(
        ids=list(person_ids), c=campaign, cid=campaign_id, d=cap_days)).fetchone()['n'])

# Footer unsubscribes are per-scope, and each scope is stamped on a
# different row (see service.unsubscribe._Q_UNSUB). A campaign must honour
# its OWN scope's stamp before the next run, otherwise a member who clicked
# "unsubscribe" in the footer still gets the following week's email.
_Q_UNSUBSCRIBED = {
    # Treated as unsubscribed when every email channel is off, whether via
    # the footer link or the settings toggles; errs toward not emailing.
    'notifications': """
        SELECT 1 FROM notification_preference
         WHERE person_id = %(pid)s
           AND NOT email_messages
           AND NOT email_matches
           AND NOT email_likes
           AND NOT email_verification
           AND NOT email_profile_views
    """,
    'community': """
        SELECT 1 FROM person
         WHERE id = %(pid)s AND community_unsubscribed_at IS NOT NULL
    """,
    # E1, E3, E6, the referral intro, the welcome and the Spotlight emails
    # (finding 62). Their own stamp, or every email channel off: until
    # 13 Oct 2026 these campaigns printed the `notifications` link, so a
    # member who left one then is recorded only that way, and still counts
    # as having left campaigns.
    'campaigns': """
        SELECT 1 FROM person
         WHERE id = %(pid)s AND campaigns_unsubscribed_at IS NOT NULL
        UNION ALL
        SELECT 1 FROM notification_preference
         WHERE person_id = %(pid)s
           AND NOT email_messages
           AND NOT email_matches
           AND NOT email_likes
           AND NOT email_verification
           AND NOT email_profile_views
    """,
}

def campaign_unsubscribed(tx, person_id: int, scope: str) -> bool:
    """True iff this member has unsubscribed from `scope`. Unknown scopes
    (and the scopes that have no member-facing campaign, e.g. `waitlist`)
    are never treated as unsubscribed."""
    q = _Q_UNSUBSCRIBED.get(scope)
    if q is None or not person_id:
        return False
    return tx.execute(q, dict(pid=person_id)).fetchone() is not None

def unsubscribed_predicate_sql(scope: str, person_ref: str) -> str:
    """SQL boolean fragment equivalent to `campaign_unsubscribed(tx, <the
    person `person_ref` names>, scope)`, for splicing directly into a
    recipient / recipient_count query's own WHERE clause -- so the admin
    dashboard's number and the runner's actual per-row behaviour can never
    drift apart. Built from the SAME `_Q_UNSUBSCRIBED[scope]` text
    `campaign_unsubscribed` uses, with `%(pid)s` replaced by `person_ref`.

    `person_ref` must be a raw SQL fragment naming the person id -- e.g. a
    qualified column reference like `p.id` -- NOT a bind parameter. It is
    spliced as text into the query, so it must resolve inside that query's
    own scope (this matters for the `community` scope, whose predicate is
    itself `FROM person`: pass a qualified reference such as `p.id`, never
    a bare `id`, or it will correlate to the wrong table instance)."""
    q = _Q_UNSUBSCRIBED.get(scope)
    if q is None:
        return "FALSE"
    return f"EXISTS ({q.replace('%(pid)s', person_ref)})"

def suppressed_predicate_sql(email_ref: str) -> str:
    """SQL boolean fragment: true iff the email at `email_ref` (a raw SQL
    fragment, e.g. a qualified column reference -- NOT a bind parameter)
    matches one of emails.base's suppressed-domain patterns.

    The caller's query must carry a `sup` bind set to
    `emails.base.suppressed_sql_pattern()`. The pattern is passed as a bind
    rather than spliced into the query text so the '%' each LIKE pattern
    contains never collides with psycopg's own %-style query formatting."""
    return f"lower({email_ref}) LIKE ANY(%(sup)s)"

def log_send(tx, person_id: int, campaign: str, campaign_id: str,
             message_id: Optional[str]) -> None:
    tx.execute(
        """
        INSERT INTO email_send_log (person_id, campaign, campaign_id, message_id)
        VALUES (%(pid)s, %(c)s, %(cid)s, %(mid)s)
        ON CONFLICT (person_id, campaign, campaign_id) DO NOTHING
        """,
        dict(pid=person_id, c=campaign, cid=campaign_id, mid=message_id))

# What a dry run's CTA points at. Never stored, and a dry run sends nothing,
# so nobody is ever handed it.
DRY_RUN_LINK_KEY = 'dry-run'

def make_campaign_link(tx, kind: str, target_url: str,
                       subject_person_id: Optional[int] = None, *,
                       external_ok: bool = False, dry_run: bool = False) -> str:
    """Mint a /s/<key> link. `target_url` must stay on our own web app by
    default: /s/<key> redirects to whatever is stored here, so accepting a
    foreign target would turn every campaign email into an open redirect.

    Compared by scheme + netloc (urlparse), not a bare `startswith`: a bare
    prefix match would let `https://ahavah.app.evil.example/x` through
    whenever WEB_BASE_URL is `https://ahavah.app`, since the string
    literally starts with that prefix even though the host is a different,
    attacker-controlled domain.

    `external_ok=True` (E5 only, spec 3.4/3.5: the share CTA must point at
    the actual Facebook/Instagram post) additionally accepts an `https`
    target whose netloc is one of `ALLOWED_EXTERNAL_HOSTS`, checked the same
    scheme+netloc way for the same subdomain-spoofing reason -- never a bare
    `startswith` or substring match. Every other target still raises
    `ValueError`, exactly as when `external_ok` is left False.

    `dry_run=True` (a campaign dry run, see service/campaigns/runner.py)
    checks the target the same way and returns a placeholder link without
    storing a row."""
    target = urlparse(str(target_url))
    base = urlparse(WEB_BASE_URL)
    on_web_base = (target.scheme, target.netloc) == (base.scheme, base.netloc)
    on_allowed_external = (external_ok and target.scheme == 'https'
                           and target.netloc in ALLOWED_EXTERNAL_HOSTS)
    if not (on_web_base or on_allowed_external):
        raise ValueError(f"campaign link target must start with {WEB_BASE_URL.rstrip('/')}")
    if dry_run:
        return f"{WEB_BASE_URL.rstrip('/')}/s/{DRY_RUN_LINK_KEY}"
    key = secrets.token_urlsafe(6)
    tx.execute(
        """
        INSERT INTO campaign_link (key, kind, target_url, subject_person_id)
        VALUES (%(k)s, %(kind)s, %(url)s, %(pid)s)
        """,
        dict(k=key, kind=kind, url=target_url, pid=subject_person_id))
    return f"{WEB_BASE_URL.rstrip('/')}/s/{key}"

def _ua_class(ua: str) -> str:
    """Bucket a click's User-Agent for `record_click` (F10).

    Empty or whitespace-only counts as `bot` (Wave 3c task 1), not
    `unknown`: the web forwarder sends `req.headers.get("user-agent") ?? ""`,
    so a script that omits the header entirely arrives here as the empty
    string, and used to earn a creditable receipt exactly like a real
    browser -- the fraud gate an agentless request was supposed to fail.
    Consequence accepted: such a click is still recorded (so it stays in the
    table for `post_stats` to count against) but excluded from that count,
    same as any other bot, and mints no receipt."""
    u = (ua or '').strip().lower()
    if not u:
        return 'bot'
    if 'facebookexternalhit' in u or 'bot' in u or 'crawler' in u:
        return 'bot'
    if 'mobile' in u or 'android' in u or 'iphone' in u:
        return 'mobile'
    return 'desktop'

# Named platforms a Spotlight click's `?p=` query param may claim (F10).
# Anything else is stored as null rather than trusted verbatim into the
# column -- the platform is metadata for reporting, not something that
# should silently grow new values just because a URL was crafted with one.
#
# This tuple is the source of truth for the whole dimension: `record_click`
# below decides what may be stored from it, `with_platform` stamps a link
# with it, and `service.growth.queries.post_stats` derives its buckets from
# it rather than repeating the names. Adding a platform here is the one edit
# a third platform needs on the reporting side.
PLATFORMS = ('facebook', 'instagram')


def with_platform(link: str, platform: Optional[str]) -> str:
    """Stamp a `/s/<key>` campaign link with the platform it is published
    on, so the click it earns is attributable to that platform rather than
    landing under 'unknown'.

    Fix wave I1: the `?p=` parameter, the `campaign_click.platform` column
    and `post_stats`' split all shipped in Wave 3b task 4, but nothing ever
    emitted the parameter, so the dimension was inert and every real click
    read as 'unknown'. This is the one place a link is stamped; callers
    (`service.spotlight.queue.create_candidate`,
    `service.spotlight.revisions.edit_caption`,
    `emails.spotlight_card_live.enqueue_card_live`) pass the platform of the
    row they are writing.

    An unrecognised or missing platform returns the link untouched rather
    than inventing a parameter `record_click` would drop anyway."""
    if platform not in PLATFORMS:
        return link
    return f"{link}?p={platform}"


# Instagram shows a link in a caption as plain text nobody can tap (owner,
# 13 Oct 2026: "dont post links in IG posts, they dont work"), so its rows
# carry the caption alone. Its clicks come from the profile link instead.
LINKLESS_PLATFORMS = ('instagram',)


def caption_for_platform(text: str, link: Optional[str], platform: Optional[str]) -> str:
    """The caption one platform row publishes: the text, then the request's
    campaign link stamped with that platform, except on a platform where a
    caption link does not work, which gets the text alone."""
    if link is None or platform in LINKLESS_PLATFORMS:
        return text
    stamped = with_platform(link, platform)
    return f"{text} {stamped}" if text else stamped


# A page on the web app a post may land on: a path of letters, digits,
# hyphens, underscores and slashes, nothing else (TEC-1845). No query and no
# host, so a post's link can only ever point at our own site.
_TARGET_PATH_RE = re.compile(r'^/[A-Za-z0-9/_-]*$')


def valid_target_path(path: object) -> bool:
    return (isinstance(path, str) and bool(_TARGET_PATH_RE.match(path))
            and not path.startswith('//'))


def post_target_url(path: str, campaign: str, content: str) -> str:
    """Where a post's link lands, tagged so first-touch capture credits it
    (growth spec, Scheduler: utm_campaign is the kind, utm_content the slug).
    utm_source is added per click by `with_utm_source`, since both platform
    rows share one link key."""
    if not valid_target_path(path):
        raise ValueError('bad_target_path')
    query = urlencode({'utm_campaign': campaign, 'utm_content': content})
    return f"{WEB_BASE_URL.rstrip('/')}{path}?{query}"


def with_utm_source(target: str, platform: Optional[str]) -> str:
    """A click on a tagged post link from a named platform lands with
    utm_source set to it, first. Anything else (no platform, an unknown one,
    a link that is not a post's, a target that already names a source) is
    returned untouched."""
    if platform not in PLATFORMS:
        return target
    parts = urlsplit(target)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = {k for k, _ in pairs}
    if 'utm_campaign' not in keys or 'utm_source' in keys:
        return target
    return urlunsplit(parts._replace(query=urlencode([('utm_source', platform), *pairs])))


def record_click(tx, key: str, user_agent: str,
                 platform: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Record a click on `/s/<key>` and, for a non-bot click, mint the
    per-click receipt a later task will use as the sole basis for sign-up
    attribution (F10). Returns `(target_url, receipt)`; both are None when
    the key is unknown, and `receipt` alone is None for a bot click -- the
    row is still recorded (so post_stats keeps counting it) but no receipt
    is ever handed to a crawler.

    `receipt = secrets.token_urlsafe(24)` is exactly 32 characters, the
    same wire limit duotypes.PostFinishOnboarding.spotlight_ref and
    service.spotlight.attribution.MAX_REF_LEN both enforce."""
    row = tx.execute("SELECT target_url FROM campaign_link WHERE key = %(k)s",
                     dict(k=key)).fetchone()
    if not row:
        return None, None
    ua_class = _ua_class(user_agent)
    receipt = None if ua_class == 'bot' else secrets.token_urlsafe(24)
    stored_platform = platform if platform in PLATFORMS else None
    tx.execute(
        """
        INSERT INTO campaign_click (link_key, ua_class, receipt, platform)
        VALUES (%(k)s, %(u)s, %(r)s, %(p)s)
        """,
        dict(k=key, u=ua_class, r=receipt, p=stored_platform))
    return row['target_url'], receipt
