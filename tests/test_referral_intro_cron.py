"""The referral intro runs itself a week after a member joins (TEC-1613)."""
from datetime import datetime, timezone

from database import api_tx
from emails.referral_intro import referral_intro_html
from service.cron.referralintro import campaign_id, queue_due

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _member(make_person, name, joined_days_ago=10, code='ABC123', roles=None):
    p = make_person(name=name)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      sign_up_time = NOW() - make_interval(days => %(d)s),
                      referral_code = %(c)s, roles = COALESCE(%(r)s::text[], roles)
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid",
                 d=joined_days_ago, c=f"{code}{p['id']}" if code else None, r=roles))
    return p


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT campaign, campaign_id, state FROM email_outbox WHERE person_id = %(p)s",
            dict(p=pid)).fetchall()]


def _run():
    with api_tx() as tx:
        return queue_due(tx, NOW)


def test_a_member_a_week_in_is_queued_once(make_person):
    p = _member(make_person, 'Due')
    _run()
    rows = _rows(p['id'])
    assert [r['campaign'] for r in rows] == ['referral']
    assert rows[0]['campaign_id'] == campaign_id(p['id'], NOW) == f"referral-{p['id']}-2026w40"
    _run()
    assert len(_rows(p['id'])) == 1, 'a second tick in the same week queued again'


def test_too_new_staff_and_codeless_members_are_not(make_person):
    fresh = _member(make_person, 'Fresh', joined_days_ago=2)
    staff = _member(make_person, 'Staff', roles=['admin'])
    codeless = _member(make_person, 'Codeless', code=None)
    _run()
    for p in (fresh, staff, codeless):
        assert _rows(p['id']) == []


def test_a_beta_member_who_had_the_intro_is_not(make_person):
    p = _member(make_person, 'Beta')
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=p['id'])).fetchone()['email']
        tx.execute("""INSERT INTO beta_signup (email, referral_intro_sent_at) VALUES (%(e)s, NOW())
                      ON CONFLICT (email) DO UPDATE SET referral_intro_sent_at = NOW()""", dict(e=email))
    _run()
    assert _rows(p['id']) == []


def test_an_accepted_send_stops_every_future_tick(make_person):
    p = _member(make_person, 'Sent')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'referral', 'referral-old', NOW() - interval '30 days')""",
                   dict(p=p['id']))
    _run()
    assert _rows(p['id']) == []


def test_a_cap_skip_is_retried_the_following_week(make_person):
    p = _member(make_person, 'Skipped')
    _run()
    with api_tx() as tx:
        tx.execute("UPDATE email_outbox SET state = 'skipped' WHERE person_id = %(p)s", dict(p=p['id']))
    later = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    with api_tx() as tx:
        assert queue_due(tx, later) >= 1
    ids = sorted(r['campaign_id'] for r in _rows(p['id']))
    assert ids == [f"referral-{p['id']}-2026w40", f"referral-{p['id']}-2026w41"]


def test_the_member_variant_has_the_member_footer():
    html = referral_intro_html('m@ahavah-test.invalid', 'CODE1', member=True)
    assert "because you're a member of Ahavah" in html
    assert 'opted into the Ahavah beta' not in html
    assert '/u/' in html or 'Unsubscribe' in html
    beta = referral_intro_html('m@ahavah-test.invalid', 'CODE1')
    assert 'opted into the Ahavah beta' in beta
