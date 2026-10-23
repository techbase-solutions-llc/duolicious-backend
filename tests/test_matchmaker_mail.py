"""The matchmaker emails and pushes (TEC-1845): on the brand shell, through
the durable outbox, each behind its switch, with 2 new recipients (a
recommended single and a mentor) that are neither members nor leads."""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx
from service.matchmaker import mail

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')


class _StubSmtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


def _drain_only(row_id: int) -> dict:
    """Drain exactly one outbox row: every other queued row is parked first,
    as tests/conftest.py outbox_drain does for rows of other people."""
    from service.campaigns import outbox
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND id <> %(i)s""", dict(i=row_id))
    smtp = _StubSmtp()
    outbox.drain(api_tx, smtp)
    with api_tx('read committed') as tx:
        row = dict(tx.execute('SELECT * FROM email_outbox WHERE id = %(i)s', dict(i=row_id)).fetchone())
    return dict(row=row, sent=smtp.sent)


@pytest.fixture
def recommendation(make_person):
    made: list[int] = []

    def _make(email: str | None = None) -> dict:
        from service.matchmaker import address_key
        address = email or f'single-{uuid4().hex[:10]}@ahavah-test.invalid'
        sender = make_person(name='Hannah Levi')
        with api_tx() as tx:
            rid = tx.execute(
                """INSERT INTO recommendation (sender_person_id, sender_key, sender_first_name,
                                               recipient_email, recipient_key, note, status)
                   VALUES (%(s)s, %(sk)s, 'Hannah', %(e)s, %(k)s, 'I think of you.', 'queued')
                   RETURNING id""",
                dict(s=sender['id'], sk=address_key(f'sender-{uuid4().hex}@x.invalid'), e=address,
                     k=address_key(address))).fetchone()['id']
        made.append(rid)
        return dict(id=rid, email=address)

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM recommendation WHERE id = ANY(%(i)s)', dict(i=made))


def test_the_email_links_are_web_pages_not_the_api():
    from service.config import API_BASE_URL, WEB_BASE_URL
    for url in (mail.confirm_url('t' * 32), mail.stop_url('t' * 32), mail.mentor_accept_url('t' * 32)):
        assert url.startswith(WEB_BASE_URL) and API_BASE_URL not in url


def test_names_and_notes_are_escaped_in_every_email():
    evil = '<script>x</script>'
    for _, html in (mail.recommend_email(evil, evil, 'https://ahavah.app/i/X'),
                    mail.intro_email(evil, evil, 'https://ahavah.app/m', 'https://ahavah.app/u'),
                    mail.mentor_invite_email(evil, 'she', 'https://ahavah.app/mentor'),
                    mail.visitor_confirm_email('a man aged 26 to 34', 'https://ahavah.app/c', evil),
                    mail.visitor_alert_email(2, evil, 'https://ahavah.app/s')):
        assert '<script>' not in html


def test_the_alert_names_nobody_and_counts():
    subject, html = mail.alert_email(2, 'https://ahavah.app/discover?fits=1', 'https://ahavah.app/alerts/stop/t')
    assert subject == '2 new members fit what you are looking for'
    assert 'We never name anyone in an email.' in html and 'See who joined' in html
    assert mail.alert_email(1, 'u', 's')[0] == '1 new member fits what you are looking for'


def test_the_likes_block_says_one_email_for_both():
    _, html = mail.alert_email(1, 'u', 's', likes=5)
    assert '5 people are also waiting for your answer' in html
    assert 'One email for both, at most once a day.' in html
    _, one = mail.alert_email(1, 'u', 's', likes=1)
    assert '1 person is also waiting for your answer' in one


def test_the_mentor_invitation_says_what_they_see():
    _, she = mail.mentor_invite_email('Rivka', 'she', 'https://ahavah.app/mentor?invite=x')
    assert 'as she sees them, and only the conversations she chooses to share' in she
    _, they = mail.mentor_invite_email('Sam', 'they', 'https://ahavah.app/mentor?invite=x')
    assert 'as they see them, and only the conversations they choose to share' in they


def test_the_pushes():
    # Plan 2026-10-22 fix 11: each push carries its own ?src=, appended to
    # any query the link already has, so a tap on it can be recorded.
    assert mail.alert_push(1)['url'] == '/discover?fits=1&src=mmalert' and mail.alert_push(1)['tag'] == 'mm-alert'
    assert mail.alert_push(3)['body'] != mail.alert_push(1)['body']
    p = mail.intro_push(7, 'Hannah', 'Daniel')
    assert p == dict(title='Ahavah', body='Hannah thinks you and Daniel might be a good fit',
                     url='/matches?intro=7&src=mmintro', tag='mm-intro-7')
    told = mail.introducer_push(7, 'Miriam', 'Daniel')
    assert told['body'] == 'Miriam and Daniel both said yes.'
    assert told['url'] == '/matches?src=mmtold' and told['tag'] == 'mm-told-7'


def test_a_push_source_joins_the_query_the_link_has():
    assert mail.with_src('/matches', 'mmtold') == '/matches?src=mmtold'
    assert mail.with_src('/discover?fits=1', 'mmalert') == '/discover?fits=1&src=mmalert'
    assert mail.without_src('/discover?fits=1&src=mmalert') == '/discover?fits=1'
    assert mail.without_src('/matches?src=mmtold') == '/matches'


def test_a_recommendation_goes_to_its_own_recipient_through_the_outbox(recommendation, outbox_rows):
    from service.campaigns import outbox
    rec = recommendation()
    subject, html = mail.recommend_email('Hannah', 'I think of you.', 'https://ahavah.app/i/X')
    with api_tx() as tx:
        rid = outbox.enqueue_for_recommendation(
            tx, campaign='mm_recommend', campaign_id=str(rec['id']), recommendation_id=rec['id'],
            email=rec['email'], subject=subject, html=html, from_addr=mail.FROM_ADDR)
        again = outbox.enqueue_for_recommendation(
            tx, campaign='mm_recommend', campaign_id=str(rec['id']), recommendation_id=rec['id'],
            email=rec['email'], subject=subject, html=html, from_addr=mail.FROM_ADDR)
    assert rid is not None and again is None
    [row] = [r for r in outbox_rows('mm_recommend') if r['id'] == rid]
    assert row['recommendation_id'] == rec['id'] and row['person_id'] is None and row['lead_id'] is None
    assert row['exempt'] is True and row['payload']['list_unsubscribe'] is None
    out = _drain_only(rid)
    assert out['row']['state'] == 'accepted' and [s['to_addr'] for s in out['sent']] == [rec['email']]


def test_a_switched_off_email_is_skipped_at_send_time(make_person, monkeypatch):
    from service.campaigns import held
    p = make_person(name='Miriam', email=f'miriam-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
        rid = held.queue(tx, campaign='mm_intro', campaign_id=f'test:{uuid4().hex}', person_id=p['id'],
                         email=email, subject='s', html='<p>h</p>', from_addr=mail.FROM_ADDR,
                         unsub_scope='notifications', unsub_url='https://ahavah.app/u')
    monkeypatch.delenv('AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED')
    out = _drain_only(rid)
    assert out['row']['state'] == 'skipped' and out['row']['last_error'] == 'switched_off'
    assert out['sent'] == []


def test_the_master_switch_stops_a_queued_email(recommendation, monkeypatch):
    from service.campaigns import outbox
    rec = recommendation()
    with api_tx() as tx:
        rid = outbox.enqueue_for_recommendation(
            tx, campaign='mm_recommend', campaign_id=str(rec['id']), recommendation_id=rec['id'],
            email=rec['email'], subject='s', html='<p>h</p>', from_addr=mail.FROM_ADDR)
    monkeypatch.delenv('AHAVAH_MATCHMAKER_LIVE_ENABLED')
    assert _drain_only(rid)['row']['last_error'] == 'switched_off'


def test_a_revoked_mentor_link_is_not_mailed(make_person):
    from service.campaigns import outbox
    single = make_person(name='Rivka')
    address = f'ruth-{uuid4().hex[:8]}@ahavah-test.invalid'
    with api_tx() as tx:
        lid = tx.execute(
            """INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email,
                                        relation, invite_expires_at)
               VALUES (%(p)s, %(e)s, %(e)s, 'parent', NOW() + interval '14 days') RETURNING id""",
            dict(p=single['id'], e=address)).fetchone()['id']
        rid = outbox.enqueue_for_mentor_link(
            tx, campaign='mm_mentor_invite', campaign_id=str(lid), mentor_link_id=lid, email=address,
            subject='s', html='<p>h</p>', from_addr=mail.FROM_ADDR)
        tx.execute('UPDATE mentor_link SET revoked_at = NOW() WHERE id = %(i)s', dict(i=lid))
    out = _drain_only(rid)
    assert out['row']['state'] == 'skipped' and out['row']['last_error'] == 'withdrawn'


def test_a_recommended_single_who_joined_is_not_mailed(recommendation, make_person):
    from service.campaigns import outbox
    rec = recommendation()
    with api_tx() as tx:
        rid = outbox.enqueue_for_recommendation(
            tx, campaign='mm_recommend', campaign_id=str(rec['id']), recommendation_id=rec['id'],
            email=rec['email'], subject='s', html='<p>h</p>', from_addr=mail.FROM_ADDR)
    make_person(name='Joined', email=rec['email'])
    out = _drain_only(rid)
    assert out['row']['state'] == 'skipped' and out['row']['last_error'] == 'member_now'


def test_a_suppressed_recommended_address_is_not_mailed(recommendation):
    from service.campaigns import outbox
    rec = recommendation(email=f'single-{uuid4().hex[:8]}@example.com')
    with api_tx() as tx:
        rid = outbox.enqueue_for_recommendation(
            tx, campaign='mm_recommend', campaign_id=str(rec['id']), recommendation_id=rec['id'],
            email=rec['email'], subject='s', html='<p>h</p>', from_addr=mail.FROM_ADDR)
    assert _drain_only(rid)['row']['last_error'] == 'suppressed'


def test_every_email_is_in_the_phone_check():
    from tests.email_samples import SAMPLES
    names = {s['name'] for s in SAMPLES}
    assert {'mm_alert_several', 'mm_alert_one', 'mm_alert_with_likes', 'mm_visitor_confirm',
            'mm_visitor_alert', 'mm_recommend', 'mm_intro', 'mm_mentor_invite'} <= names
    assert not [s for s in SAMPLES if s['name'].startswith('mm_') and s.get('error')]


def test_every_email_uses_a_title_image():
    for name in ('preview_alert_several', 'preview_alert_one', 'preview_alert_with_likes',
                 'preview_visitor_confirm', 'preview_visitor_alert', 'preview_recommend',
                 'preview_intro', 'preview_mentor_invite'):
        _subject, html = getattr(mail, name)('owner@example.com')
        assert 'e-title-light' in html and 'e-title-dark' in html, name
