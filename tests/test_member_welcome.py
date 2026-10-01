"""Render smoke test for the evergreen member welcome.

The full send path (grant latch -> async send) is exercised implicitly
by test_referral_rewards.py (the latch) and by the live catch-up
runner; here we pin the personalized facts into the rendered HTML so a
refactor can't silently drop the date, the invite link, or the token
stipend from the copy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from emails.member_welcome import member_welcome_html, SUBJECT


def test_welcome_html_contains_personalized_facts():
    html = member_welcome_html(
        datetime(2027, 2, 9, tzinfo=timezone.utc),
        "https://ahavah.app/i/737TGEG",
        "https://ahavah.app/unsub-test",
    )
    assert "February 9, 2027" in html
    assert "https://ahavah.app/i/737TGEG" in html
    assert "ahavah.app/i/737TGEG" in html          # visible link text
    assert "30 tokens" in html
    assert "6 months" in html
    assert "https://ahavah.app/unsub-test" in html
    assert "title-member-welcome" in html
    # No em dashes anywhere in member-facing copy.
    assert "—" not in html


def test_subject_has_no_em_dash():
    assert "—" not in SUBJECT


# ---------------------------------------------------------------------------
# The welcome goes through the outbox, so it leaves a record (TEC-1613).
# ---------------------------------------------------------------------------

def _granted(make_person, name, code=True):
    from database import api_tx
    p = make_person(name=name)
    email = f"{name.lower()}-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      subscription_expires_at = NOW() + interval '180 days',
                      referral_code = %(c)s
                WHERE id = %(i)s""",
            dict(i=p['id'], e=email, c=f"W{p['id']}" if code else None))
    return p, email


def _outbox(pid):
    from database import api_tx
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT campaign, campaign_id, state FROM email_outbox WHERE person_id = %(p)s",
            dict(p=pid)).fetchall()]


def test_a_granted_member_gets_one_queued_welcome_and_only_one(make_person):
    from emails.member_welcome import send_member_welcome
    p, email = _granted(make_person, 'Welcomed')
    assert send_member_welcome(email) is True
    rows = _outbox(p['id'])
    assert rows == [dict(campaign='welcome', campaign_id=f"welcome-{p['id']}", state='queued')]
    # An onboarding replay must never queue a second welcome.
    assert send_member_welcome(email) is False
    assert len(_outbox(p['id'])) == 1


def test_a_member_without_a_code_is_not_welcomed_yet(make_person):
    from emails.member_welcome import send_member_welcome
    p, email = _granted(make_person, 'Codeless', code=False)
    assert send_member_welcome(email) is False
    assert _outbox(p['id']) == []
