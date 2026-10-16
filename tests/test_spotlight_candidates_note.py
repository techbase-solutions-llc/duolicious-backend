"""The owner's personal note to the Spotlight candidates (health review,
13 Oct 2026, finding 85; guardrails, finding 87).

A candidate is an activated member, never staff, who passes every Spotlight
eligibility rule except consent, was online in the last 30 days, has not
opted in, and HAS had E1, so nobody gets this note and the E1 resend (which
goes to the members who never had E1). Members who left campaigns, and
suppressed addresses, are left out. Each member gets the note once ever.

The note goes through the campaign outbox like every member email. No mail
leaves the test: the drain hands it to a stub with the Smtp.send signature.
"""
from __future__ import annotations

import secrets

import pytest

from database import api_tx
from emails import send_spotlight_candidates_note as sc


class _StubSmtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


def _candidate(make_person, name='Candidate', gender='Woman'):
    """A member who is a candidate in every respect: verified, adult, with an
    approved photo, online now, not opted in, and sent E1 on 20 Sep."""
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                   spotlight_opt_in = FALSE,
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, last_online_time = NOW()
             WHERE id = %(id)s""",
                   dict(id=p['id'], e=f"{name.split()[0].lower()}-{p['id']}@ahavah-test.invalid"))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'e1', 'e1-20260919-launch', NOW() - interval '26 days')""",
                   dict(p=p['id']))
    return p


def _ids():
    return {r['person_id'] for r in sc.recipients()}


def _email(pid):
    with api_tx('read committed') as tx:
        return tx.execute("SELECT email FROM person WHERE id = %(p)s", dict(p=pid)).fetchone()['email']


@pytest.fixture
def clean_outbox():
    """The suite shares one outbox; remove this test's note rows after it."""
    made: list[int] = []
    yield made
    with api_tx() as tx:
        tx.execute("DELETE FROM email_outbox WHERE campaign = %(c)s AND person_id = ANY(%(p)s)",
                   dict(c=sc.CAMPAIGN, p=made))
        tx.execute("DELETE FROM email_send_log WHERE campaign = %(c)s AND person_id = ANY(%(p)s)",
                   dict(c=sc.CAMPAIGN, p=made))


# --- who gets the note -----------------------------------------------------

def test_a_candidate_who_had_e1_is_a_recipient(make_person):
    p = _candidate(make_person, 'Willing')
    assert p['id'] in _ids()


@pytest.mark.parametrize('sql, why', [
    ("DELETE FROM email_send_log WHERE person_id = %(id)s AND campaign = 'e1'",
     'never had E1: the 19 Oct resend is for them'),
    ("UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW() WHERE id = %(id)s",
     'already opted in'),
    ("UPDATE person SET roles = ARRAY['admin'] WHERE id = %(id)s", 'staff'),
    ("UPDATE person SET activated = FALSE WHERE id = %(id)s", 'not activated'),
    ("UPDATE person SET ahavah_verification_tier = 'none' WHERE id = %(id)s", 'not verified'),
    ("UPDATE person SET date_of_birth = (NOW() - interval '17 years')::date WHERE id = %(id)s",
     'under 18'),
    ("UPDATE person SET deletion_requested_at = NOW() WHERE id = %(id)s", 'pending deletion'),
    ("DELETE FROM photo WHERE person_id = %(id)s", 'no approved photo'),
    ("INSERT INTO spotlight_occurrence (kind, person_id, request_key) "
     "VALUES ('welcome', %(id)s, 'note-cooldown-' || %(id)s)", 'featured recently'),
    ("UPDATE person SET last_online_time = NOW() - interval '31 days' WHERE id = %(id)s",
     'not seen in 30 days'),
    ("UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(id)s", 'left campaigns'),
    ("UPDATE person SET email = 'note-' || %(id)s || '@example.com' WHERE id = %(id)s",
     'suppressed address'),
    ("INSERT INTO email_send_log (person_id, campaign, campaign_id) "
     "VALUES (%(id)s, 'spotlight_note', 'an-earlier-run')", 'already had the note'),
])
def test_who_is_left_out(make_person, sql, why):
    p = _candidate(make_person, 'LeftOut')
    with api_tx() as tx:
        tx.execute(sql, dict(id=p['id']))
    assert p['id'] not in _ids(), why


def test_a_reported_member_is_left_out(make_person):
    p = _candidate(make_person, 'Reported')
    reporter = make_person(name='Reporter', gender='Man')
    with api_tx() as tx:
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
                      VALUES (%(a)s, %(b)s, TRUE, 'spam')""", dict(a=reporter['id'], b=p['id']))
    assert p['id'] not in _ids()


def test_the_rules_are_spotlight_eligibility_less_consent(make_person):
    """The recipient query uses the eligibility rules themselves, so a
    candidate who opts in is eligible to be featured."""
    from service.spotlight.eligibility import eligibility
    p = _candidate(make_person, 'Consents')
    with api_tx() as tx:
        assert eligibility(tx, p['id']) == (False, 'not_opted_in')
        tx.execute("UPDATE person SET spotlight_opt_in = TRUE WHERE id = %(id)s", dict(id=p['id']))
        assert eligibility(tx, p['id']) == (True, '')


def test_a_member_already_queued_is_not_a_recipient_again(make_person, clean_outbox):
    p = _candidate(make_person, 'Queued')
    clean_outbox.append(p['id'])
    email = _email(p['id'])
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload, unsub_scope)
                      VALUES ('spotlight_note', 'an-earlier-run', %(p)s, %(e)s, '{}'::jsonb, 'campaigns')""",
                   dict(p=p['id'], e=email))
    assert p['id'] not in _ids()


def test_the_count_matches_the_list(make_person):
    _candidate(make_person, 'Counted')
    assert sc.recipient_count() == len(sc.recipients())


def test_the_first_name_is_the_first_word_of_the_name(make_person):
    p = _candidate(make_person, 'Hannah Levi')
    row = next(r for r in sc.recipients() if r['person_id'] == p['id'])
    assert row['first_name'] == 'Hannah'


# --- the note itself -------------------------------------------------------

_PARAGRAPHS = (
    "We are starting to introduce a few members on Ahavah’s Facebook and Instagram, "
    "so believers who have not heard of us can see real people here. Each post is your main "
    "profile photo, your first name, age and country, and nothing else.",
    "Nothing is posted unless you approve that exact card, and you can say no to any card or "
    "switch it off at any time. If you would rather not, that is completely fine and changes "
    "nothing for you.",
    "If you are willing, turn on Spotlight in Settings, under Privacy, and we will send you a "
    "card to look at first.",
)


def test_the_note_carries_the_approved_wording():
    from emails.spotlight_candidates_note import SUBJECT, note_html, note_text
    assert SUBJECT == 'Would you help us introduce Ahavah?'
    for body in (note_html('Ruth', 'https://x/u/t'), note_text('Ruth', 'https://x/u/t')):
        flat = ' '.join(body.replace('&rsquo;', '’').replace('&#x27;', "'").split())
        assert 'Shalom Ruth,' in flat
        for paragraph in _PARAGRAPHS:
            assert paragraph in flat
        assert 'one photo of you' not in flat
        assert 'Ehud' in flat
        assert '—' not in body, 'no em dash in the note'
        assert 'dating' not in body.lower()


def test_the_greeting_falls_back_to_shalom_with_no_name():
    from emails.spotlight_candidates_note import note_html, note_text
    assert 'Shalom,' in note_html(None, 'https://x/u/t')
    assert 'Shalom,' in note_text(None, 'https://x/u/t')
    assert 'Shalom ,' not in note_text(None, 'https://x/u/t')


def test_a_name_is_escaped_in_the_html():
    from emails.spotlight_candidates_note import note_html
    html = note_html('<b>Eve</b>', 'https://x/u/t')
    assert '<b>Eve</b>' not in html and '&lt;b&gt;Eve&lt;/b&gt;' in html


def test_the_note_is_plain_inside_the_brand_shell():
    """As the warm leads note: the dark band with the white logo and the
    footer, plain paragraphs, no title image, chip or button."""
    from emails.base import LIME, LOGO_WHITE_URL
    from emails.spotlight_candidates_note import note_html
    html = note_html('Ruth', 'https://x/u/t')
    assert LOGO_WHITE_URL in html
    assert html.count('<img') == 1
    assert f'bgcolor="{LIME}"' not in html, 'no button'
    assert 'e-chip' not in html, 'no chip'
    assert 'Torah-observant believers' in html


def test_the_unsubscribe_link_is_in_both_parts_with_the_campaigns_scope(make_person):
    from service.unsubscribe import parse_token
    p = _candidate(make_person, 'UnsubLink')
    email = _email(p['id'])
    msg = sc.build_message(email, 'Ruth')
    token = msg['unsubscribe_url'].rsplit('/u/', 1)[1]
    assert parse_token(token) == ('campaigns', email)
    assert f'href="{msg["unsubscribe_url"]}"' in msg['html']
    assert msg['unsubscribe_url'] in msg['text']
    assert f"<{msg['unsubscribe_url']}>" in msg['list_unsubscribe']
    assert 'mailto:' in msg['list_unsubscribe']


# --- send ------------------------------------------------------------------

def test_send_queues_each_candidate_once_and_the_drain_sends_it_from_ehud(
        make_person, clean_outbox, outbox_drain):
    p = _candidate(make_person, 'Leah')
    clean_outbox.append(p['id'])
    first = sc.run(send=True, only_ids=[p['id']])
    assert first['queued'] == 1

    with api_tx('read committed') as tx:
        row = tx.execute("""SELECT campaign, campaign_id, unsub_scope, exempt FROM email_outbox
                             WHERE person_id = %(p)s AND campaign = %(c)s""",
                         dict(p=p['id'], c=sc.CAMPAIGN)).fetchone()
    assert dict(row) == dict(campaign='spotlight_note', campaign_id=sc.CAMPAIGN_ID,
                             unsub_scope='campaigns', exempt=True)

    again = sc.run(send=True, only_ids=[p['id']])
    assert again['queued'] == 0, 'a second --send queues nobody'

    sent = [s for s in outbox_drain(p['id']) if s['to_addr'] == _email(p['id'])]
    assert len(sent) == 1
    s = sent[0]
    assert s['subject'] == 'Would you help us introduce Ahavah?'
    assert 'Shalom Leah,' in s['body'] and 'Shalom Leah,' in s['text_body']
    assert s['from_addr'] == sc.FROM_ADDR == 'support@ahavah.app'
    assert s['from_name'] == sc.FROM_NAME == 'Ehud at Ahavah'
    assert s['reply_to'] == 'support@ahavah.app'
    assert s['list_unsubscribe'] and '/u/' in s['list_unsubscribe']
    assert p['id'] not in _ids(), 'sent once ever'


def test_the_note_is_not_held_back_by_the_weekly_email_and_does_not_hold_it_back(
        make_person, clean_outbox):
    """E2 goes to every member every Monday. The note keeps its own cadence
    (once ever) and is queued exempt, as the other self-capped mail is."""
    from service.campaigns import SELF_CAPPED_CAMPAIGNS, can_send, log_send
    assert 'spotlight_note' in SELF_CAPPED_CAMPAIGNS
    p = _candidate(make_person, 'AfterWeekly')
    clean_outbox.append(p['id'])
    with api_tx() as tx:
        log_send(tx, p['id'], 'e2', 'e2-note-test-week', None)
    assert sc.run(send=True, only_ids=[p['id']])['queued'] == 1
    with api_tx() as tx:
        # Next week: last week's E2 is out of the window, and the note just
        # went out.
        tx.execute("DELETE FROM email_send_log WHERE person_id = %(p)s AND campaign = 'e2'",
                   dict(p=p['id']))
        log_send(tx, p['id'], sc.CAMPAIGN, sc.CAMPAIGN_ID, 'mid-x')
        assert can_send(tx, p['id'], 'e2', 'e2-note-test-next-week', cap_days=6)


def test_a_dry_run_builds_every_message_writes_nothing_and_prints_no_address(
        make_person, capsys, monkeypatch):
    p = _candidate(make_person, 'DryRun')

    def _no_mail(*a, **kw):
        raise AssertionError('a dry run must not reach the mailer')

    monkeypatch.setattr(sc, '_mailer', _no_mail)
    sc.main([])
    out = capsys.readouterr().out
    assert 'DRY RUN' in out
    assert '@' not in out.replace('support@ahavah.app', '')
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT count(*) AS n FROM email_outbox WHERE person_id = %(p)s",
                          dict(p=p['id'])).fetchone()['n'] == 0


def test_a_preview_sends_one_proof_and_records_nothing(make_person, monkeypatch):
    """The proof goes where the operator points it, usually a staff inbox
    the bulk send suppresses. It carries the sample name, and an inert link
    in place of the unsubscribe link, as every proof does (9134cb8)."""
    p = _candidate(make_person, 'NotThePreview')
    smtp = _StubSmtp()
    monkeypatch.setattr(sc, '_mailer', lambda: smtp)
    with api_tx('read committed') as tx:
        before = tx.execute("""SELECT (SELECT count(*) FROM email_outbox)
                                    + (SELECT count(*) FROM email_send_log)
                                    + (SELECT count(*) FROM campaign_link) AS n""").fetchone()['n']
    sc.main(['--preview', 'admin@techbaseltd.com'])
    with api_tx('read committed') as tx:
        after = tx.execute("""SELECT (SELECT count(*) FROM email_outbox)
                                   + (SELECT count(*) FROM email_send_log)
                                   + (SELECT count(*) FROM campaign_link) AS n""").fetchone()['n']
    assert after == before
    assert [s['to_addr'] for s in smtp.sent] == ['admin@techbaseltd.com']
    s = smtp.sent[0]
    assert f'Shalom {sc.SAMPLE_FIRST_NAME},' in s['body']
    assert s['from_name'] == 'Ehud at Ahavah' and s['reply_to'] == 'support@ahavah.app'
    assert s['text_body']
    assert '/u/' not in s['body'] and '/u/' not in s['text_body']
    assert sc.PROOF_LINK_DISABLED in s['body']
    assert not s.get('list_unsubscribe')
    assert p['id'] in _ids(), 'a proof must not use up a candidate'


# --- the outbox carries the personal-note fields --------------------------

def test_the_drain_passes_a_display_name_reply_to_and_text_only_when_queued(
        make_person, outbox_drain):
    from service.campaigns import outbox
    plain_to = f'plain-{secrets.token_hex(4)}@ahavah-test.invalid'
    personal_to = f'personal-{secrets.token_hex(4)}@ahavah-test.invalid'
    plain = make_person(name='PlainRow', email=plain_to)
    personal = make_person(name='PersonalRow', email=personal_to)
    with api_tx() as tx:
        outbox.enqueue(tx, campaign='like', campaign_id='note-fields-plain', person_id=plain['id'],
                       email=plain_to, subject='s', html='<p>h</p>', from_addr=None,
                       unsub_scope='notifications', exempt=True)
        outbox.enqueue(tx, campaign='like', campaign_id='note-fields-personal', person_id=personal['id'],
                       email=personal_to, subject='s', html='<p>h</p>', from_addr=None,
                       unsub_scope='notifications', exempt=True,
                       text='h', from_name='Ehud at Ahavah', reply_to='support@ahavah.app')
    sent = {s['to_addr']: s for s in outbox_drain(plain['id'], personal['id'])}
    assert not {'from_name', 'reply_to', 'text_body'} & set(sent[plain_to])
    got = sent[personal_to]
    assert (got['from_name'], got['reply_to'], got['text_body']) == ('Ehud at Ahavah', 'support@ahavah.app', 'h')
