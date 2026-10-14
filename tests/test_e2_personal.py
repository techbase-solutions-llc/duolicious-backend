"""E2's personal line and the member's own invite link (findings 60 and
76), held behind AHAVAH_E2_PERSONAL_ENABLED. With the switch off, E2 is
exactly what it was."""
import pytest

from database import api_tx
from emails import send_community_weekly as e2
from emails.community_weekly import SUBJECT
from service.config import WEB_BASE_URL


def _person(make_person, name, gender='Woman', code=True):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                             referral_code = CASE WHEN %(c)s THEN %(code)s ELSE NULL END
                       WHERE id = %(i)s""",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid",
                        c=code, code=f"E2P{p['id']}"))
    return p


def _row(p):
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=p['id'])).fetchone()['email']
    return dict(person_id=p['id'], email=email, name='x', week=dict(new_members=[], total=40, spotlight=None))


def _links(pid):
    with api_tx('read committed') as tx:
        return sorted(r['target_url'] for r in tx.execute(
            "SELECT target_url FROM campaign_link WHERE kind = 'e2' AND subject_person_id = %(p)s",
            dict(p=pid)).fetchall())


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_PERSONAL_ENABLED', '1')


def test_off_the_email_is_unchanged(make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_E2_PERSONAL_ENABLED', raising=False)
    p = _person(make_person, 'E2Off')
    subject, html = e2.build_for(_row(p))
    assert subject == SUBJECT
    assert _links(p['id']) == [f'{WEB_BASE_URL}/discover']
    assert 'invite link' in html.lower() and '/i/' not in html


def test_likes_waiting_lead_the_email(make_person, on):
    p = _person(make_person, 'E2Likes')
    for i in range(2):
        liker = make_person(name=f'E2Liker{i}', gender='Man')
        with api_tx() as tx:
            tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)", dict(a=liker['id'], b=p['id']))
    subject, html = e2.build_for(_row(p))
    assert subject == 'This week on Ahavah: 2 likes are waiting for you'
    assert '2 people have liked you and are waiting for an answer.' in html
    assert 'E2Liker' not in html
    assert 'See who likes you' in html
    assert _links(p['id']) == sorted([f'{WEB_BASE_URL}/matches?tab=likes', f"{WEB_BASE_URL}/share/E2P{p['id']}"])


def test_with_nothing_personal_the_invite_link_still_comes_every_week(make_person, on):
    p = _person(make_person, 'E2Plain')
    with api_tx() as tx:
        tx.execute("DELETE FROM search_preference_gender WHERE person_id = %(p)s", dict(p=p['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) VALUES (%(p)s, 10)", dict(p=p['id']))
    subject, html = e2.build_for(_row(p))
    assert subject == SUBJECT
    assert 'Open Discover' in html
    assert 'Share your invite link' in html
    assert _links(p['id']) == sorted([f'{WEB_BASE_URL}/discover', f"{WEB_BASE_URL}/share/E2P{p['id']}"])
    assert 'Your invite link is in your profile' not in html


def test_newcomers_who_fit_make_the_line_when_nothing_else_does(make_person, on):
    p = _person(make_person, 'E2Fits')
    with api_tx() as tx:
        tx.execute("DELETE FROM search_preference_gender WHERE person_id = %(p)s", dict(p=p['id']))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) VALUES (%(p)s, 1)", dict(p=p['id']))
    make_person(name='E2NewMan', gender='Man')
    _subject, html = e2.build_for(_row(p))
    assert ('who fit what you are looking for joined this week' in html
            or 'who fits what you are looking for joined this week' in html)


def test_a_member_with_no_code_gets_no_invite_block(make_person, on):
    p = _person(make_person, 'E2NoCode', code=False)
    _subject, html = e2.build_for(_row(p))
    assert 'Share your invite link' not in html


def test_a_dry_run_stores_no_link(make_person, on):
    p = _person(make_person, 'E2Dry')
    e2.build_for(dict(_row(p), dry_run=True))
    assert _links(p['id']) == []


def test_the_personal_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n']
    subject, html = e2.preview_personal('owner@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM campaign_link").fetchone()['n'] == before
    assert subject == 'This week on Ahavah: 2 likes are waiting for you'
    assert 'Share your invite link' in html


def test_the_invite_button_opens_the_share_page_not_the_members_own_invite():
    """/i/<code> sets the reader's own referral cookie, sends them to sign-up
    and counts a click against their own code; /share/<code> is the page the
    referral email's button opens. The proof's button is built the same way."""
    assert e2.invite_target('ABC') == f'{WEB_BASE_URL}/share/ABC'
    _subject, html = e2.preview_personal('owner@ahavah-test.invalid')
    assert f'href="{WEB_BASE_URL}/share/YOURCODE"' in html
    assert '/i/' not in html and f'{WEB_BASE_URL}/invite"' not in html
