"""The referral email's links go through /s/ campaign links of kind
'referral', so opens of the share page and the invite link from the email
can be counted (finding 74)."""
from datetime import datetime, timezone

from database import api_tx
from emails.referral_intro import referral_intro_html
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
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", c=f"TRK{p['id']}"))
    return p


def test_the_cron_queues_the_intro_with_counted_links(make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_REFERRAL_MEMBER_BODY_ENABLED', '1')
    p = _member(make_person, 'RefTrack')
    code = f"TRK{p['id']}"
    with api_tx() as tx:
        queue_due(tx, NOW)
    with api_tx('read committed') as tx:
        html = tx.execute("SELECT payload->>'html' AS h FROM email_outbox WHERE person_id = %(p)s AND campaign = 'referral'",
                          dict(p=p['id'])).fetchone()['h']
        links = [dict(r) for r in tx.execute(
            "SELECT key, target_url FROM campaign_link WHERE kind = 'referral' AND subject_person_id = %(p)s",
            dict(p=p['id'])).fetchall()]
    assert sorted(l['target_url'] for l in links) == [f"{WEB_BASE_URL}/i/{code}", f"{WEB_BASE_URL}/share/{code}"]
    for l in links:
        assert f'href="{WEB_BASE_URL}/s/{l["key"]}"' in html
    assert f'href="{WEB_BASE_URL}/share/{code}"' not in html
    # The address a member copies by hand is still their own invite link.
    assert f">{WEB_BASE_URL}/i/{code}</a>" in html


def test_without_tracked_links_the_template_links_straight_through():
    html = referral_intro_html('a@ahavah-test.invalid', 'PLAIN1', member=True)
    assert f'href="{WEB_BASE_URL}/share/PLAIN1"' in html


def test_a_second_tick_in_the_week_mints_no_more_links(make_person, monkeypatch):
    monkeypatch.setenv('AHAVAH_REFERRAL_MEMBER_BODY_ENABLED', '1')
    p = _member(make_person, 'RefTwice')
    for _ in range(2):
        with api_tx() as tx:
            queue_due(tx, NOW)
    with api_tx('read committed') as tx:
        n = tx.execute("SELECT count(*) AS n FROM campaign_link WHERE kind = 'referral' AND subject_person_id = %(p)s",
                       dict(p=p['id'])).fetchone()['n']
    assert n == 2
