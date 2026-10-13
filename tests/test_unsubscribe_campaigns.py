"""Campaigns get their own unsubscribe scope (health review, 13 Oct 2026,
finding 62).

E1, E3, E6, the referral intro, the welcome and the Spotlight emails all
printed a `notifications` unsubscribe link, and that scope turns off every
email_* channel. So leaving a campaign also silenced match, message and
like emails: person 99 has no channel left that can tell them about a match.

Now those emails carry the `campaigns` scope, which stamps
`person.campaigns_unsubscribed_at` (migration 0058) and touches no
notification preference. A member who left through an old link keeps that
meaning for campaigns: every email channel off still counts as unsubscribed
from campaigns. E2 keeps its own `community` scope.
"""
from __future__ import annotations

import re
import secrets

import pytest

from database import api_tx
from service.campaigns import campaign_unsubscribed, outbox
from service.unsubscribe import make_token, parse_token, stamp_unsubscribed


def _mailable(make_person, name: str) -> dict:
    p = make_person(name=name)
    email = f"{name.lower()}-{p['id']}@ahavah-test.invalid"
    with api_tx() as tx:
        tx.execute("UPDATE person SET email = %(e)s, normalized_email = %(e)s, activated = TRUE "
                   "WHERE id = %(i)s", dict(e=email, i=p['id']))
    return dict(p, email=email)


def _token_in(html: str) -> tuple[str, str]:
    m = re.search(r'/u/([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)', html)
    assert m, 'no unsubscribe link in the mail'
    return parse_token(m.group(1))


def _email_prefs(person_id: int):
    with api_tx() as tx:
        return tx.execute(
            """SELECT email_messages, email_matches, email_likes, email_verification,
                      email_profile_views
                 FROM notification_preference WHERE person_id = %(p)s""",
            dict(p=person_id)).fetchone()


# --- Which scope each email prints -----------------------------------------

def test_every_campaign_prints_the_campaigns_scope():
    import emails.send_community_weekly as e2
    import emails.send_notifications_nudge as e6
    import emails.send_reinvite as e3
    import emails.send_spotlight_announcement as e1
    import emails.spotlight_card_live as e5
    import emails.spotlight_card_ready as e4
    import service.cron.referralintro as referral

    for mod in (e1, e3, e4, e5, e6, referral):
        assert mod.UNSUB_SCOPE == 'campaigns', mod.__name__
    assert e2.UNSUB_SCOPE == 'community'


def test_the_e6_footer_link_is_a_campaigns_link(make_person):
    from emails.send_notifications_nudge import build_for

    m = _mailable(make_person, 'NudgeFooter')
    _, html = build_for(dict(person_id=m['id'], email=m['email'], name='Nudge', dry_run=True))

    assert _token_in(html) == ('campaigns', m['email'])


def test_the_member_referral_intro_is_a_campaigns_link():
    from emails.referral_intro import referral_intro_html

    html = referral_intro_html('member@ahavah-test.invalid', 'ABCDEFG', member=True)

    assert _token_in(html) == ('campaigns', 'member@ahavah-test.invalid')


def test_the_welcome_is_a_campaigns_link(make_person):
    from emails.member_welcome import send_member_welcome

    m = _mailable(make_person, 'WelcomeFooter')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET subscription_expires_at = NOW() + interval '180 days',
                      referral_code = %(c)s
                WHERE id = %(i)s""", dict(i=m['id'], c=secrets.token_hex(4)[:7].upper()))
    assert send_member_welcome(m['email'])
    with api_tx() as tx:
        row = tx.execute(
            """SELECT unsub_scope, payload FROM email_outbox
                WHERE campaign = 'welcome' AND person_id = %(i)s""", dict(i=m['id'])).fetchone()
        tx.execute("DELETE FROM email_outbox WHERE person_id = %(i)s", dict(i=m['id']))

    assert row['unsub_scope'] == 'campaigns'
    assert _token_in(row['payload']['html']) == ('campaigns', m['email'])


# --- What a campaigns unsubscribe does -------------------------------------

def test_a_campaign_unsubscribe_stops_campaigns(client, make_person, outbox_drain):
    from emails.send_notifications_nudge import recipients

    m = _mailable(make_person, 'LeavesCampaigns')
    assert m['id'] in [r['person_id'] for r in recipients()], 'E6 would reach them before'
    with api_tx() as tx:
        outbox.enqueue(tx, campaign='e6', campaign_id='unsub-scope-e6', person_id=m['id'],
                       email=m['email'], subject='S', html='<p>x</p>',
                       from_addr='hello@ahavah.app', unsub_scope='campaigns')

    r = client.post(f"/u/{make_token('campaigns', m['email'])}")
    assert r.status_code == 200

    with api_tx() as tx:
        assert campaign_unsubscribed(tx, m['id'], 'campaigns')
        assert tx.execute("SELECT campaigns_unsubscribed_at FROM person WHERE id = %(i)s",
                          dict(i=m['id'])).fetchone()['campaigns_unsubscribed_at'] is not None
    assert m['id'] not in [r['person_id'] for r in recipients()]
    assert outbox_drain(m['id']) == [], 'the queued campaign mail is skipped'
    with api_tx() as tx:
        state = tx.execute("SELECT state, last_error FROM email_outbox WHERE person_id = %(i)s",
                           dict(i=m['id'])).fetchone()
        tx.execute("DELETE FROM email_outbox WHERE person_id = %(i)s", dict(i=m['id']))
    assert (state['state'], state['last_error']) == ('skipped', 'unsubscribed')


def test_a_campaign_unsubscribe_leaves_match_message_and_like_emails_on(client, make_person):
    from service.notifications import _email_allowed_for_event

    m = _mailable(make_person, 'KeepsAlerts')
    with api_tx() as tx:
        tx.execute("INSERT INTO notification_preference (person_id, email_likes) "
                   "VALUES (%(i)s, TRUE)", dict(i=m['id']))

    assert client.post(f"/u/{make_token('campaigns', m['email'])}").status_code == 200

    assert _email_prefs(m['id']) == dict(
        email_messages=True, email_matches=True, email_likes=True,
        email_verification=True, email_profile_views=False)
    for kind in ('match', 'message', 'like'):
        assert _email_allowed_for_event(m['id'], kind), kind
    with api_tx() as tx:
        assert not campaign_unsubscribed(tx, m['id'], 'notifications')


def test_a_campaign_unsubscribe_does_not_stop_e2(client, make_person):
    m = _mailable(make_person, 'KeepsWeekly')
    assert client.post(f"/u/{make_token('campaigns', m['email'])}").status_code == 200
    with api_tx() as tx:
        assert not campaign_unsubscribed(tx, m['id'], 'community')


# --- Unsubscribes from before this change ----------------------------------

def test_a_member_who_left_through_an_old_campaign_link_stays_off_campaigns(make_person):
    """The old footer stamped every email channel off. That still means
    "no campaigns"; their notification choices are left as they are."""
    m = _mailable(make_person, 'OldLink')
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'notifications', m['email'])
        assert campaign_unsubscribed(tx, m['id'], 'campaigns')
    assert _email_prefs(m['id']) == dict(
        email_messages=False, email_matches=False, email_likes=False,
        email_verification=False, email_profile_views=False)


def test_a_notifications_unsubscribe_still_turns_notification_emails_off(client, make_person):
    m = _mailable(make_person, 'LeavesAlerts')
    assert client.post(f"/u/{make_token('notifications', m['email'])}").status_code == 200
    assert _email_prefs(m['id'])['email_matches'] is False
