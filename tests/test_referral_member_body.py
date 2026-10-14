"""The members' referral email (finding 68): its own body, no beta, no
launch, the reward as /invite states it and a Boost called a 30-minute
boost on Discover. The referral cron waits for AHAVAH_REFERRAL_MEMBER_BODY_ENABLED."""
from datetime import datetime, timezone

from database import api_tx
from emails import referral_intro as ri
from service.config import WEB_BASE_URL
from service.cron.referralintro import queue_due

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def _member(make_person, name):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      sign_up_time = NOW() - interval '10 days', referral_code = %(c)s
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", c=f"MB{p['id']}"))
    return p


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT payload->>'subject' AS subject, payload->>'html' AS html FROM email_outbox "
            "WHERE person_id = %(p)s AND campaign = 'referral'", dict(p=pid)).fetchall()]


def test_the_member_body_says_what_the_app_says():
    html = ri.referral_intro_html('m@ahavah-test.invalid', 'CODE9', member=True)
    lower = html.lower()
    for word in ('beta', 'launch', 'spotlight', 'dating', 'founding'):
        assert word not in lower, f'the member body says {word!r}'
    assert 'a 30-minute boost on Discover' in html
    assert '30 days' in html and '5 tokens' in html
    assert ri.MEMBER_SHARE_TEXT in html
    assert f'{WEB_BASE_URL}/i/CODE9' in html
    assert chr(0x2014) not in html


def test_the_share_text_matches_the_web_share_sheet():
    assert ri.MEMBER_SHARE_TEXT == ("I’m on Ahavah, marriage-minded matchmaking for "
                                    "Torah-observant believers. Join me with my link.")


def test_the_cron_waits_for_the_switch(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_REFERRAL_MEMBER_BODY_ENABLED', raising=False)
    p = _member(make_person, 'RefWaits')
    with api_tx() as tx:
        assert queue_due(tx, NOW) == 0
    assert _rows(p['id']) == []


def test_with_the_switch_on_the_cron_sends_the_member_body(make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_REFERRAL_MEMBER_BODY_ENABLED', '1')
    p = _member(make_person, 'RefMember')
    with api_tx() as tx:
        queue_due(tx, NOW)
    rows = _rows(p['id'])
    assert len(rows) == 1
    assert rows[0]['subject'] == ri.MEMBER_SUBJECT
    assert 'a 30-minute boost on Discover' in rows[0]['html'] and 'beta' not in rows[0]['html'].lower()


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = ri.preview_member('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert subject == ri.MEMBER_SUBJECT and 'a 30-minute boost on Discover' in html
