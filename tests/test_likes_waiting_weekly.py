"""The weekly likes-waiting email (findings 57 and 64): held behind its own
switch, a count only, through the outbox, with the new-fit line."""
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import likes_waiting_weekly as lw
from service.campaigns import can_send
from service.config import WEB_BASE_URL

THURSDAY = datetime(2026, 10, 15, 13, tzinfo=timezone.utc)   # ISO 2026 week 42
WEDNESDAY = datetime(2026, 10, 14, 13, tzinfo=timezone.utc)


def _person(make_person, name, gender='Woman', offline_days=5, email_likes=True):
    """`email_likes` None leaves the member with no preference row, which
    reads as the column's default (off)."""
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      last_online_time = NOW() - make_interval(days => %(d)s)
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", d=offline_days))
        if email_likes is not None:
            tx.execute("""INSERT INTO notification_preference (person_id, email_likes)
                          VALUES (%(p)s, %(v)s)
                          ON CONFLICT (person_id) DO UPDATE SET email_likes = %(v)s""",
                       dict(p=p['id'], v=email_likes))
    return p


def _sent_before(person, days_ago):
    """A likes-waiting email the drain accepted `days_ago` days ago."""
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'likes_waiting', %(c)s, NOW() - make_interval(days => %(d)s))""",
                   dict(p=person['id'], c=f"likes_waiting-old-{days_ago}", d=days_ago))


def _like(liker, liked, hours_ago=24):
    with api_tx() as tx:
        tx.execute("""INSERT INTO liked (liker_id, liked_id, created_at)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(hours => %(h)s))""",
                   dict(a=liker['id'], b=liked['id'], h=hours_ago))


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign, campaign_id, unsub_scope, exempt, payload->>'html' AS html,
                      payload->>'subject' AS subject
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'likes_waiting'""",
            dict(p=pid)).fetchall()]


def _run(now=THURSDAY):
    with api_tx() as tx:
        return lw.queue_due(tx, now)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_LIKES_WAITING_ENABLED', '1')


def test_off_by_default_nothing_is_queued(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_LIKES_WAITING_ENABLED', raising=False)
    her = _person(make_person, 'OffHer')
    _like(make_person(name='OffLiker', gender='Man'), her)
    assert _run() == 0
    assert _rows(her['id']) == []


def test_a_member_away_with_a_new_like_gets_a_count_only(make_person, on):
    her = _person(make_person, 'Waiting')
    liker = make_person(name='Zebulunliker', gender='Man')
    _like(liker, her)
    _run()
    rows = _rows(her['id'])
    assert len(rows) == 1
    r = rows[0]
    assert r['campaign_id'] == 'likes_waiting-2026w42'
    assert r['unsub_scope'] == 'campaigns' and r['exempt'] is True
    assert r['subject'] == 'Someone likes you on Ahavah'
    assert '1 person has liked your profile' in r['html']
    assert 'Zebulunliker' not in r['html'], 'the email named the liker'
    assert f'{WEB_BASE_URL}/s/' in r['html']
    with api_tx('read committed') as tx:
        target = tx.execute(
            "SELECT target_url FROM campaign_link WHERE kind = 'likes_waiting' AND subject_person_id = %(p)s",
            dict(p=her['id'])).fetchone()['target_url']
    assert target == f'{WEB_BASE_URL}/matches?tab=likes'


def test_the_count_says_how_many(make_person, on):
    her = _person(make_person, 'Several')
    for i in range(3):
        _like(make_person(name=f'Liker{i}', gender='Man'), her)
    _run()
    r = _rows(her['id'])[0]
    assert r['subject'] == '3 people like you on Ahavah'
    assert '3 people have liked your profile' in r['html']


def test_not_for_a_member_online_since_the_like_or_recently(make_person, on):
    seen_since = _person(make_person, 'SeenSince', offline_days=0)
    _like(make_person(name='L1', gender='Man'), seen_since, hours_ago=200)
    recent = _person(make_person, 'Recent', offline_days=1)
    _like(make_person(name='L2', gender='Man'), recent, hours_ago=48)
    _run()
    assert _rows(seen_since['id']) == [] and _rows(recent['id']) == []


def test_not_for_a_like_already_answered(make_person, on):
    her = _person(make_person, 'Answered')
    him = make_person(name='Answeredhim', gender='Man')
    _like(him, her)
    _like(her, him, hours_ago=200)
    _run()
    assert _rows(her['id']) == []


def test_only_in_its_window_and_once_a_week(make_person, on):
    her = _person(make_person, 'Window')
    _like(make_person(name='WinLiker', gender='Man'), her)
    assert _run(WEDNESDAY) == 0
    _run()
    _run()
    assert len(_rows(her['id'])) == 1
    with api_tx('read committed') as tx:
        n = tx.execute("SELECT count(*) AS n FROM campaign_link WHERE kind = 'likes_waiting' AND subject_person_id = %(p)s",
                       dict(p=her['id'])).fetchone()['n']
    assert n == 1, 'a repeat tick minted another link'


def test_the_new_fit_line_counts_newcomers_she_is_looking_for(make_person, on):
    her = _person(make_person, 'Fit')
    with api_tx() as tx:
        tx.execute("DELETE FROM search_preference_gender WHERE person_id = %(p)s", dict(p=her['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) VALUES (%(p)s, 1)", dict(p=her['id']))
    _like(make_person(name='FitLiker', gender='Man'), her)
    newcomer = make_person(name='FitNew', gender='Man')
    with api_tx() as tx:
        tx.execute("UPDATE person SET sign_up_time = NOW() - interval '1 day' WHERE id = %(p)s", dict(p=newcomer['id']))
    _run()
    html = _rows(her['id'])[0]['html']
    assert 'who fit what you are looking for' in html
    assert 'FitNew' not in html


def test_no_new_fit_line_when_nobody_fits(make_person, on):
    her = _person(make_person, 'NoFit')
    with api_tx() as tx:
        tx.execute("DELETE FROM search_preference_gender WHERE person_id = %(p)s", dict(p=her['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) VALUES (%(p)s, 10)", dict(p=her['id']))
    _like(make_person(name='NoFitLiker', gender='Man'), her)
    _run()
    assert 'who fit what you are looking for' not in _rows(her['id'])[0]['html']


def test_it_neither_holds_back_nor_is_held_back_by_the_weekly_email(make_person, on, outbox_drain):
    her = _person(make_person, 'NoCapClash')
    _like(make_person(name='CapLiker', gender='Man'), her)
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'e2', 'cmp_test_comm', NOW() - interval '3 days')""", dict(p=her['id']))
    _run()
    sent = outbox_drain(her['id'])
    assert [s['subject'] for s in sent] == ['Someone likes you on Ahavah']
    with api_tx('read committed') as tx:
        assert can_send(tx, her['id'], 'e2', 'cmp_next_comm', cap_days=6) is False  # the e2 three days ago
        tx.execute("DELETE FROM email_send_log WHERE person_id = %(p)s AND campaign = 'e2'", dict(p=her['id']))
        assert can_send(tx, her['id'], 'e2', 'cmp_next_comm', cap_days=6) is True


def test_a_member_who_left_campaigns_is_not_queued(make_person, on):
    her = _person(make_person, 'LeftCampaigns')
    _like(make_person(name='LeftLiker', gender='Man'), her)
    with api_tx() as tx:
        tx.execute("UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s", dict(p=her['id']))
    _run()
    assert _rows(her['id']) == []


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = lw.preview('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        after = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    assert after == before
    assert subject == '2 people like you on Ahavah' and 'who fit what you are looking for' in html


def test_not_again_until_someone_new_likes_them(make_person, on):
    """A member who stays away is not told about the same likes every week:
    10 of the 16 due on 14 Oct had been away 60 days or more."""
    her = _person(make_person, 'LongAway', offline_days=70)
    _like(make_person(name='OldLiker', gender='Man'), her, hours_ago=24 * 30)
    _sent_before(her, 7)
    _run()
    assert _rows(her['id']) == []
    _like(make_person(name='NewLiker', gender='Man'), her, hours_ago=2)
    _run()
    rows = _rows(her['id'])
    assert len(rows) == 1
    assert rows[0]['subject'] == '2 people like you on Ahavah', 'the count still covers every like waiting'


def test_a_member_with_like_emails_off_gets_none(make_person, on):
    off = _person(make_person, 'LikeMailOff', email_likes=False)
    _like(make_person(name='OffMailLiker', gender='Man'), off)
    unset = _person(make_person, 'LikeMailUnset', email_likes=None)
    _like(make_person(name='UnsetMailLiker', gender='Man'), unset)
    _run()
    assert _rows(off['id']) == []
    assert _rows(unset['id']) == [], 'the switch defaults off, and the settings page shows it off'
