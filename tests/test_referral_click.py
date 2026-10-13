"""Tests for service.api.referral_click_route.

_classify_ua is pure logic. The inviter lookup and the insert run against
the test database through the real route (health review, 13 Oct 2026,
findings 7, 25 and 73: a click on a member's own code was logged with no
inviter, because the lookup read beta_signup only). Mocking psycopg
cursors is brittle and obscures whether the actual SQL is right, so none
of this mocks the database."""
from __future__ import annotations

import secrets
import uuid

import pytest

from database import api_tx
from service.api.referral_click_route import _classify_ua


@pytest.mark.parametrize("ua, expected", [
    # Empty/missing
    ("", "unknown"),
    (None, "unknown"),
    # Bots / preview crawlers
    ("facebookexternalhit/1.1", "bot"),
    ("Twitterbot/1.0", "bot"),
    ("LinkedInBot/1.0", "bot"),
    ("Slackbot-LinkExpanding 1.0", "bot"),
    ("Discordbot/2.0", "bot"),
    ("TelegramBot (like TwitterBot)", "bot"),
    ("WhatsApp/2.21.4.18", "bot"),
    ("Applebot/0.1", "bot"),
    ("Mozilla/5.0 (compatible; Googlebot/2.1)", "bot"),
    ("Mozilla/5.0 (compatible; bingbot/2.0)", "bot"),
    ("Some Crawler v1.0", "bot"),
    ("WebSpider/1.0", "bot"),
    ("Mozilla/5.0 (LinkPreview)", "bot"),
    # Mobile (the iphone/android/mobile signals)
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "mobile"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8)", "mobile"),
    ("Mozilla/5.0 (Windows Phone 10.0; Mobile)", "mobile"),
    # Desktop fallback
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15", "desktop"),
    ("Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0", "desktop"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/119.0", "desktop"),
])
def test_classify_ua(ua, expected):
    assert _classify_ua(ua) == expected


def test_classify_ua_bot_check_runs_before_mobile_check():
    """A UA that says BOTH 'mobile' and 'bot' classifies as bot.
    Ensures the bot keywords are checked first (more conservative
    for analytics — bot-tinged 'mobile' UAs come from preview
    crawlers and we don't want them inflating the mobile bucket)."""
    # iOS Slackbot variant in the wild
    assert _classify_ua("Mozilla/5.0 (iPhone) Slackbot 1.0") == "bot"


# ---------------------------------------------------------------------------
# The inviter: a member's code (person.referral_code) and a beta code both
# resolve, the member's first, the same order sign-up attribution uses.
# ---------------------------------------------------------------------------

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _code() -> str:
    return ''.join(secrets.choice(_ALPHABET) for _ in range(7))


@pytest.fixture
def member_code(make_person):
    p = make_person(name='Sharer')
    code = _code()
    with api_tx() as tx:
        email = tx.execute(
            "UPDATE person SET referral_code = %(c)s WHERE id = %(i)s RETURNING email",
            dict(c=code, i=p['id'])).fetchone()['email']
    yield code, email
    with api_tx() as tx:
        tx.execute("DELETE FROM referral_link_click WHERE code = %(c)s", dict(c=code))


@pytest.fixture
def beta_code():
    code = _code()
    email = f'beta-{uuid.uuid4().hex[:10]}@example.com'
    with api_tx() as tx:
        tx.execute("INSERT INTO beta_signup (email, referral_code) VALUES (%(e)s, %(c)s)",
                   dict(e=email, c=code))
    yield code, email
    with api_tx() as tx:
        tx.execute("DELETE FROM referral_link_click WHERE code = %(c)s", dict(c=code))
        tx.execute("DELETE FROM beta_signup WHERE email = %(e)s", dict(e=email))


def _click(client, code, well_formed=True):
    r = client.post('/referral-click', json=dict(code=code.lower(), well_formed=well_formed,
                                                 user_agent='Mozilla/5.0 (iPhone)'))
    assert r.status_code == 200


def _inviters(code):
    with api_tx('read committed') as tx:
        return [r['inviter_email'] for r in tx.execute(
            "SELECT inviter_email FROM referral_link_click WHERE code = %(c)s ORDER BY created_at",
            dict(c=code)).fetchall()]


def test_a_click_on_a_members_code_records_the_member(client, member_code):
    code, email = member_code
    _click(client, code)
    assert _inviters(code) == [email]


def test_a_click_on_a_beta_code_still_records_the_beta_inviter(client, beta_code):
    code, email = beta_code
    _click(client, code)
    assert _inviters(code) == [email]


def test_an_unknown_or_malformed_code_records_no_inviter(client, member_code):
    code, _email = member_code
    unknown = _code()
    try:
        _click(client, unknown)
        _click(client, code, well_formed=False)
        assert _inviters(unknown) == [None]
        assert _inviters(code) == [None]
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM referral_link_click WHERE code = %(c)s", dict(c=unknown))


# ---------------------------------------------------------------------------
# scripts/backfill_referral_click_inviter.py: the 87 clicks on member codes
# logged before the fix get their inviter.
# ---------------------------------------------------------------------------

def _insert_click(code, inviter=None, well_formed=True):
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO referral_link_click (code, inviter_email, well_formed, user_agent_class)
               VALUES (%(c)s, %(e)s, %(w)s, 'mobile')""",
            dict(c=code, e=inviter, w=well_formed))


def test_the_backfill_fills_past_clicks_on_member_codes(member_code, beta_code):
    from scripts.backfill_referral_click_inviter import backfill
    code, email = member_code
    bcode, bemail = beta_code
    unknown = _code()
    _insert_click(code)
    _insert_click(code)
    _insert_click(code, well_formed=False)
    _insert_click(bcode, inviter=bemail)
    _insert_click(unknown)
    try:
        with api_tx() as tx:
            dry = backfill(tx, dry_run=True)
        assert dry['member_codes'] >= 2
        assert _inviters(code) == [None, None, None]

        with api_tx() as tx:
            done = backfill(tx)
        assert done['member_codes'] == dry['member_codes']
        # The malformed one is left alone: the route never resolves those.
        assert sorted(_inviters(code), key=str) == sorted([email, email, None], key=str)
        assert _inviters(bcode) == [bemail]
        assert _inviters(unknown) == [None]

        with api_tx() as tx:
            again = backfill(tx)
        assert again['member_codes'] == 0 and again['beta_codes'] == 0
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM referral_link_click WHERE code = %(c)s", dict(c=unknown))
