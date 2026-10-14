"""The weekly profile-views email (finding 65): the Email switch for profile
views finally sends something, a count only, held behind its own switch."""
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import profile_views_weekly as pv
from service.config import WEB_BASE_URL

WEDNESDAY = datetime(2026, 10, 14, 13, tzinfo=timezone.utc)   # ISO week 42
THURSDAY = datetime(2026, 10, 15, 13, tzinfo=timezone.utc)


def _person(make_person, name, gender='Woman', email_views=True):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s WHERE id = %(i)s",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid"))
        if email_views is not None:
            tx.execute("""INSERT INTO notification_preference (person_id, email_profile_views)
                          VALUES (%(p)s, %(v)s)
                          ON CONFLICT (person_id) DO UPDATE SET email_profile_views = %(v)s""",
                       dict(p=p['id'], v=email_views))
    return p


def _visit(visitor, visited, days_ago=1, invisible=False):
    with api_tx() as tx:
        tx.execute("""INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s), %(i)s)""",
                   dict(a=visitor['id'], b=visited['id'], d=days_ago, i=invisible))


def _rows(pid):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, unsub_scope, payload->>'html' AS html, payload->>'subject' AS subject
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'profile_views'""",
            dict(p=pid)).fetchall()]


def _run(now=WEDNESDAY):
    with api_tx() as tx:
        return pv.queue_due(tx, now)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_PROFILE_VIEW_EMAIL_ENABLED', '1')


def test_off_by_default(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_PROFILE_VIEW_EMAIL_ENABLED', raising=False)
    her = _person(make_person, 'OffViews')
    _visit(make_person(name='OffVisitor', gender='Man'), her)
    assert _run() == 0 and _rows(her['id']) == []


def test_a_member_who_asked_gets_the_week_count_without_names(make_person, on):
    her = _person(make_person, 'Viewed')
    for i in range(2):
        _visit(make_person(name=f'Nathanvisitor{i}', gender='Man'), her)
    _run()
    rows = _rows(her['id'])
    assert len(rows) == 1
    r = rows[0]
    assert r['campaign_id'] == 'profile_views-2026w42'
    assert r['unsub_scope'] == 'notifications'
    assert r['subject'] == '2 people viewed your profile this week'
    assert 'Nathanvisitor' not in r['html']
    with api_tx('read committed') as tx:
        target = tx.execute("SELECT target_url FROM campaign_link WHERE kind = 'profile_views' AND subject_person_id = %(p)s",
                            dict(p=her['id'])).fetchone()['target_url']
    assert target == f'{WEB_BASE_URL}/views'
    _run()
    assert len(_rows(her['id'])) == 1


def test_not_for_a_member_who_did_not_ask(make_person, on):
    default = _person(make_person, 'DefaultViews', email_views=None)
    off = _person(make_person, 'OffEmailViews', email_views=False)
    for p in (default, off):
        _visit(make_person(name='V', gender='Man'), p)
    _run()
    assert _rows(default['id']) == [] and _rows(off['id']) == []


def test_old_invisible_staff_and_blocked_visits_do_not_count(make_person, on):
    her = _person(make_person, 'NotCounted')
    _visit(make_person(name='Old', gender='Man'), her, days_ago=9)
    _visit(make_person(name='Invisible', gender='Man'), her, invisible=True)
    staff = make_person(name='StaffVisitor', gender='Man')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(p)s", dict(p=staff['id']))
    _visit(staff, her)
    _run()
    assert _rows(her['id']) == []


def test_only_on_wednesday(make_person, on):
    her = _person(make_person, 'NotThursday')
    _visit(make_person(name='TV', gender='Man'), her)
    assert _run(THURSDAY) == 0


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = pv.preview('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert subject == '3 people viewed your profile this week'


def test_the_copy_is_true_for_every_member():
    """The member turned on profile view emails, not a weekly count; and
    Views is Premium-locked for free members, so nothing promises who."""
    html = pv.profile_views_html(3, 'https://ahavah.app/x', 'https://ahavah.app/u/x')
    assert ('You get this because profile view emails are on in your settings. '
            'Turn them off any time in Settings, Notifications.') in html
    assert 'You asked for this weekly count' not in html
    assert 'Views shows who they are' not in html
