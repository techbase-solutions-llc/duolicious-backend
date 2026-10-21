"""Every Ahavah email, built with plain sample data, for the tests that check
how mail renders (tests/test_email_renders_on_a_phone.py).

Ported from the 18 Oct 2026 email audit (docs/superpowers/plans/
2026-10-18-email-phone-fit.md). Nothing is sent and nothing touches the
database: every builder is called with sample values, and the two helpers
that build and send in one call run against a capturing fake mailer.

SAMPLES is a list of dicts: name, source, audience (member, lead or staff),
sent_now, html (the body as the mailer ships it) or error. Add a row here
whenever a new email is added, so the phone check covers it.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from service.config import API_BASE_URL, WEB_BASE_URL  # noqa: E402
from service.unsubscribe import make_token, make_url as unsub_url  # noqa: E402
import smtp  # noqa: E402

TO = 'miriam.levi@gmail.com'
FIRST = 'Miriam'
CODE = 'MIRIAM7K'
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
PREMIUM_UNTIL = NOW + timedelta(days=183)
TOK = 'eyJlIjoibWlyaWFtLmxldmlAZ21haWwuY29tIiwibiI6IjNmOWEyYyJ9.Qk3x9vZr2mT8pL0aYw4nHc1sEu7dJf5gXo6bRi'
S_LINK = f'{WEB_BASE_URL}/s/k7Hq2mXp9RtZ'

SAMPLES: list[dict] = []


def _ship(html: str) -> str:
    """The body the mailer actually sends (smtp/__init__.py)."""
    body, _parts = smtp._prepare_inline_body(html)
    return body


def add(name: str, source: str, audience: str, sent_now: str, build, from_addr=None):
    row = dict(name=name, source=source, audience=audience, sent_now=sent_now, from_addr=from_addr)
    try:
        out = build()
        subject, html = out if isinstance(out, tuple) else (None, out)
        row.update(subject=subject, html=_ship(html))
    except Exception as e:  # recorded; the test fails on it
        row.update(error=f'{type(e).__name__}: {e}')
    SAMPLES.append(row)


def unsub(scope: str) -> str:
    return unsub_url(scope, TO, WEB_BASE_URL)


# ---------------------------------------------------------------------------
# A capturing mailer for the helpers that build and send in one call.
class _Capture:
    sent: list[dict] = []

    def send(self, **kw):
        _Capture.sent.append(kw)
        return 'captured'


def _captured(fn):
    _Capture.sent = []
    real = smtp.make_aws_smtp
    smtp.make_aws_smtp = lambda: _Capture()
    try:
        fn()
    finally:
        smtp.make_aws_smtp = real
    if not _Capture.sent:
        raise RuntimeError('nothing captured')
    m = _Capture.sent[0]
    return m['subject'], m['body']


SWITCH_NOTE = ('compose default 0; production .env value not readable from the repo')

# ===========================================================================
# 1. Account and sign-in (service/person, cron)
from service.person.template import otp_template  # noqa: E402
from service.person.deletion_email import deletion_pending_template  # noqa: E402
from service.cron.autodeactivate2.template import emailtemplate as resting_template  # noqa: E402
from service.config import PRODUCT_NAME  # noqa: E402

add('otp_sign_in', 'service/person/template/__init__.py otp_template', 'member',
    'LIVE: every POST /request-otp (service/person/__init__.py _send_otp), direct via aws_smtp, from support@',
    lambda: (f'Sign in to {PRODUCT_NAME}', otp_template('482913')), 'support@ahavah.app')
add('account_deletion_pending', 'service/person/deletion_email/__init__.py deletion_pending_template', 'member',
    'LIVE: DELETE /account (service/person/__init__.py _send_deletion_pending_email), direct via aws_smtp, default sender',
    lambda: ('Sorry to see you go', deletion_pending_template(name='Miriam Levi', purge_iso='Sun, October 25, 2026')))
add('profile_resting_autodeactivate', 'service/cron/autodeactivate2/template/__init__.py emailtemplate', 'member',
    'DORMANT in practice: cron autodeactivate2 sends only when DUO_CRON_AUTODEACTIVATE2_DRY_RUN is false; '
    'production compose defaults it to true (docstring: production runs it in DRY RUN)',
    lambda: (f'Your {PRODUCT_NAME} profile is resting', resting_template()))

# ===========================================================================
# 2. Event notifications (emails/notification.py)
from emails import notification as N  # noqa: E402
from service.cron.notifications.template import big_part, frequency_url  # noqa: E402

notif_unsub = f"{API_BASE_URL}/u/{make_token('notifications', TO)}"
add('new_message', 'emails/notification.py new_message_email', 'member',
    'LIVE: cron notifications (email fallback after 10 min offline with unread) -> outbox campaign "message"',
    lambda: ('You have a new message on Ahavah', N.new_message_email(
        headline=big_part(False, True), open_url=f'{WEB_BASE_URL}/inbox',
        unsubscribe_url=frequency_url(TO, 'Every', 'Never'))))
add('new_match', 'emails/notification.py new_match_email', 'member',
    'LIVE: service/decisions on a new mutual like, via notify(); email only when no live push subscription and email_matches on -> outbox "match"',
    lambda: ('You have a new match on Ahavah', N.new_match_email(notif_unsub)))
add('new_like', 'emails/notification.py new_like_email', 'member',
    'LIVE: service/decisions on a new like, via notify(); email only when the member turned like emails on (default off) and has no push -> outbox "like"',
    lambda: ('Someone likes you on Ahavah', N.new_like_email(notif_unsub)))
add('verification_approved', 'emails/notification.py new_verification_email', 'member',
    'LIVE: cron verificationjobrunner (bronze/silver) and service/identity_verification (gold), via notify(), direct send',
    lambda: ("You're verified on Ahavah", N.new_verification_email('Silver', notif_unsub)))
add('verification_basics_only', 'emails/notification.py verification_basics_only_email', 'member',
    'LIVE: cron verificationjobrunner, success without a tier, via notify(), direct send',
    lambda: ('We could not match your selfie to your photos', N.verification_basics_only_email(notif_unsub)))
add('verification_not_passed', 'emails/notification.py verification_not_passed_email', 'member',
    'LIVE: cron verificationjobrunner, failure, via notify(), direct send',
    lambda: ('Your verification check did not pass', N.verification_not_passed_email(notif_unsub)))
add('verification_id_check_retry', 'emails/notification.py verification_id_check_retry_email', 'member',
    'LIVE: Stripe Identity requires_input webhook (service/identity_verification), via notify(), direct send',
    lambda: ('Your ID check needs another try', N.verification_id_check_retry_email(notif_unsub)))

# ===========================================================================
# 3. Receipts (emails/purchase.py)
from emails.purchase import premium_started_email, tokens_purchased_email  # noqa: E402

add('receipt_tokens', 'emails/purchase.py tokens_purchased_email', 'member',
    'LIVE: Stripe checkout webhook on a token credit (service/checkout), send_transactional, direct',
    lambda: ('Your Ahavah purchase is confirmed', tokens_purchased_email(count=10, amount_label='$4.99')))
add('receipt_premium', 'emails/purchase.py premium_started_email', 'member',
    'LIVE: Stripe checkout webhook on a new subscription (service/checkout), send_transactional, direct',
    lambda: ('Welcome to Ahavah Premium', premium_started_email(tier_key='quart', stipend=12, amount_label='$29.99')))

# ===========================================================================
# 4. Onboarding and lifecycle
from emails import member_welcome  # noqa: E402

add('member_welcome', 'emails/member_welcome.py member_welcome_html', 'member',
    'LIVE: /finish-onboarding when Premium is granted (service/person send_member_welcome_async) -> outbox "welcome". '
    'Also CLI emails/send_member_welcome.py',
    lambda: (member_welcome.SUBJECT, member_welcome.member_welcome_html(
        PREMIUM_UNTIL, f'https://ahavah.app/i/{CODE}', unsub('campaigns'))),
    member_welcome.FROM_ADDR)

from emails.photo_removed import send_photo_removed  # noqa: E402
add('photo_removed', 'emails/photo_removed.py send_photo_removed (emails/member_note.py member_note_html)', 'member',
    'LIVE: admin moderation delete-photo with notify (service/api/admin/moderation_routes.py), direct send',
    lambda: _captured(lambda: send_photo_removed(TO, 'Miriam Levi')), 'support@ahavah.app')

from emails.marriage_checklist import SUBJECT as CL_SUBJECT, checklist_results_html  # noqa: E402
_CL_SAMPLE = [
    dict(section='biblical', ref='Genesis 2:18-24', importance=5, stance='agree',
         comment='We leave and cleave, and build our own home.'),
    dict(section='biblical', ref='Ephesians 5:22-33', importance=4, stance='discuss',
         comment='We want to talk about what headship looks like day to day.'),
    dict(section='nice-to-have', title='We pray together every evening', importance=5, frequency='daily'),
    dict(section='nice-to-have', title='Shabbat dinner with family', importance=3, frequency='weekly'),
]
add('marriage_checklist_results', 'emails/marriage_checklist.py checklist_results_html(stored=False)', 'member+spouse (spouse may be anyone)',
    'LIVE: POST /marriage-checklist/send (service/person post_marriage_checklist_send), to the member and the spouse address, direct send',
    lambda: (CL_SUBJECT, checklist_results_html('wife', _CL_SAMPLE, stored=False)))

# ===========================================================================
# 5. Leads (waitlist / beta)
from emails import waitlist_welcome, beta_welcome, reengagement  # noqa: E402
add('waitlist_welcome', 'emails/waitlist_welcome.py waitlist_welcome_html', 'lead',
    'LIVE: POST /waitlist (service/api/waitlist_routes.py), direct send. Also CLI emails/send_waitlist_welcome.py',
    lambda: (waitlist_welcome.SUBJECT, waitlist_welcome.waitlist_welcome_html(TO)), waitlist_welcome.FROM_ADDR)
add('beta_welcome', 'emails/beta_welcome.py beta_welcome_html', 'lead',
    'LIVE: POST beta opt-in (service/api/beta_routes.py), direct send',
    lambda: (beta_welcome.SUBJECT, beta_welcome.beta_welcome_html(TO)), beta_welcome.FROM_ADDR)
add('beta_reengagement', 'emails/reengagement.py reengagement_html', 'lead',
    'LIVE: cron betareengagement every 6 h (beta testers 7+ days with no waitlist answers and no account). Also CLI emails/send_reengagement.py',
    lambda: (reengagement.SUBJECT, reengagement.reengagement_html(TO)), reengagement.FROM_ADDR)

# ===========================================================================
# 6. Growth campaigns (admin Growth tab Send + cron)
from emails import spotlight_announcement as e1mod  # noqa: E402
_confirm = f'{WEB_BASE_URL}/spotlight/confirm/{TOK}'
add('e1_spotlight_announcement_old_copy', 'emails/spotlight_announcement.py spotlight_announcement_html(new_copy=False)', 'member',
    'OPERATOR-RUN: admin Growth > Emails Send for e1 (service/api/admin/growth_routes.py) -> outbox. Old copy while AHAVAH_SPOTLIGHT_COPY_ENABLED is off (' + SWITCH_NOTE + ')',
    lambda: (e1mod.SUBJECT, e1mod.spotlight_announcement_html(_confirm, S_LINK, unsub('campaigns'), new_copy=False)),
    e1mod.FROM_ADDR)
add('e1_spotlight_announcement_new_copy', 'emails/spotlight_announcement.py spotlight_announcement_html(new_copy=True)', 'member',
    'SCHEDULED: E1 resend (emails/send_spotlight_resend.py, droplet timer ahavah-e1-resend-2026-10-19, Mon 19 Oct) always uses the new copy; '
    'also e1 Send when AHAVAH_SPOTLIGHT_COPY_ENABLED is on',
    lambda: (e1mod.SUBJECT, e1mod.spotlight_announcement_html(_confirm, S_LINK, unsub('campaigns'), new_copy=True)),
    e1mod.FROM_ADDR)

from emails import community_weekly as e2mod  # noqa: E402
from emails import send_community_weekly as e2send  # noqa: E402
_newcomers = [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB'),
              dict(first_name='Abigail', country='BB'), dict(first_name='Jonathan', country='CA')]
_spot = dict(first_name='Hannah', age=29, country='US', post_url='https://www.facebook.com/61560000000001_122100000000000001',
             image_url='https://ahavah-spotlight.nyc3.cdn.digitaloceanspaces.com/cards/2026/10/3f9a2c1e7b.jpg')
add('e2_community_weekly', 'emails/community_weekly.py community_weekly_html', 'member',
    'LIVE: admin Growth Send for e2, and cron communityweekly (Monday 12:00 UTC) when DUO_CRON_COMMUNITY_WEEKLY_ENABLED=1 (' + SWITCH_NOTE + ') -> outbox',
    lambda: (e2mod.SUBJECT, e2mod.community_weekly_html(_newcomers, 58, _spot, S_LINK, unsub('campaigns'))),
    e2mod.FROM_ADDR)
add('e2_community_weekly_personal', 'emails/community_weekly.py community_weekly_html(personal_line, invite_url)', 'member',
    'HELD: e2 with AHAVAH_E2_PERSONAL_ENABLED on (' + SWITCH_NOTE + ')',
    lambda: (lambda p: (p['subject'], e2mod.community_weekly_html(
        _newcomers, 58, _spot, S_LINK, unsub('campaigns'), personal_line=p['line'],
        invite_url=S_LINK, cta_label=p['cta_label'])))(e2send.personal_parts(2, 0, 0)),
    e2mod.FROM_ADDR)


def _e2_question():
    from service.questions.copy import SAMPLE_QUESTION, e2_line
    return e2mod.SUBJECT, e2mod.community_weekly_html(
        _newcomers, 58, None, S_LINK, unsub('campaigns'), question_line=e2_line(SAMPLE_QUESTION))


add('e2_community_weekly_question_line', 'emails/community_weekly.py community_weekly_html(question_line)', 'member',
    'HELD: e2 with AHAVAH_E2_QUESTION_LINE_ENABLED and AHAVAH_QUESTIONS_LIVE_ENABLED on (quick questions launch week of 20 Oct)',
    _e2_question, e2mod.FROM_ADDR)

from emails import reinvite as e3mod  # noqa: E402
add('e3_reinvite_quiet', 'emails/reinvite.py reinvite_html(state=quiet)', 'member',
    'OPERATOR-RUN: admin Growth Send for e3 -> outbox',
    lambda: (e3mod.subject_for('quiet'), e3mod.reinvite_html(FIRST, 5, S_LINK, unsub('campaigns'),
                                                             gender_label='men', state='quiet', notifications_url=S_LINK)),
    e3mod.FROM_ADDR)
add('e3_reinvite_paused', 'emails/reinvite.py reinvite_html(state=paused)', 'member',
    'OPERATOR-RUN: admin Growth Send for e3 -> outbox',
    lambda: (e3mod.subject_for('paused'), e3mod.reinvite_html(FIRST, 10, S_LINK, unsub('campaigns'),
                                                              gender_label='men', state='paused', notifications_url=S_LINK)),
    e3mod.FROM_ADDR)
add('e3_reinvite_unmatched', 'emails/reinvite.py reinvite_html(matched=False)', 'member',
    'OPERATOR-RUN: admin Growth Send for e3 -> outbox',
    lambda: (e3mod.subject_for('quiet'), e3mod.reinvite_html(FIRST, 16, S_LINK, unsub('campaigns'),
                                                             gender_label='people', state='quiet',
                                                             notifications_url=S_LINK, matched=False)),
    e3mod.FROM_ADDR)

from emails import notifications_nudge as e6mod  # noqa: E402
add('e6_notifications_nudge', 'emails/notifications_nudge.py notifications_nudge_html', 'member',
    'OPERATOR-RUN: admin Growth Send for e6 -> outbox',
    lambda: (e6mod.SUBJECT, e6mod.notifications_nudge_html(FIRST, S_LINK, unsub('campaigns'))), e6mod.FROM_ADDR)

from emails import spotlight_card_ready as e4mod  # noqa: E402
_card = f'{WEB_BASE_URL}/spotlight/card/{TOK}'
add('e4_spotlight_card_ready_old_copy', 'emails/spotlight_card_ready.py card_ready_html(new_copy=False)', 'member',
    'LIVE when Spotlight approvals run: admin spotlight routes (enqueue_card_ready) -> outbox "e4"; old copy while AHAVAH_SPOTLIGHT_COPY_ENABLED is off',
    lambda: (e4mod.SUBJECT, e4mod.card_ready_html(FIRST, 'member of the week', _card, 7, unsub('campaigns'), new_copy=False)),
    e4mod.FROM_ADDR)
add('e4_spotlight_card_ready_new_copy', 'emails/spotlight_card_ready.py card_ready_html(new_copy=True)', 'member',
    'HELD: as above with AHAVAH_SPOTLIGHT_COPY_ENABLED on',
    lambda: (e4mod.SUBJECT, e4mod.card_ready_html(FIRST, 'member of the week', _card, 7, unsub('campaigns'), new_copy=True)),
    e4mod.FROM_ADDR)

from emails import spotlight_card_live as e5mod  # noqa: E402
_post = 'https://www.facebook.com/61560000000001_122100000000000001'
add('e5_spotlight_card_live', 'emails/spotlight_card_live.py card_live_html', 'member',
    'LIVE when Spotlight publishes: admin spotlight publish receipt (enqueue_card_live) -> outbox "e5"',
    lambda: (e5mod.SUBJECT, e5mod.card_live_html(FIRST, _spot['image_url'], _post, S_LINK, unsub('campaigns'))),
    e5mod.FROM_ADDR)

# ===========================================================================
# 7. Held return mail (cron returnmail) and referral
from emails import likes_waiting_weekly, one_photo_nudge, profile_views_weekly, reminders, friend_joined, referral_intro, questions_launch  # noqa: E402,E501

add('likes_waiting_weekly', 'emails/likes_waiting_weekly.py likes_waiting_weekly_html', 'member',
    'HELD: cron returnmail Thursday, AHAVAH_LIKES_WAITING_ENABLED (' + SWITCH_NOTE + ')',
    lambda: (likes_waiting_weekly.subject_for(2), likes_waiting_weekly.likes_waiting_weekly_html(2, 3, S_LINK, unsub('notifications'))),
    likes_waiting_weekly.FROM_ADDR)
add('match_reminder', 'emails/reminders.py match_reminder_html', 'member',
    'LIVE (switched on in production 14 Oct per docs/superpowers/specs/2026-10-13-profile-prompts-design.md): cron returnmail, AHAVAH_MATCH_REMINDER_ENABLED',
    lambda: (reminders.MATCH_SUBJECT, reminders.match_reminder_html(3, S_LINK, unsub('notifications'))), reminders.FROM_ADDR)
add('message_reminder', 'emails/reminders.py message_reminder_html', 'member',
    'LIVE (switched on in production 14 Oct, same source): cron returnmail, AHAVAH_MESSAGE_REMINDER_ENABLED',
    lambda: (reminders.message_subject(2), reminders.message_reminder_html(2, S_LINK, unsub('notifications'))), reminders.FROM_ADDR)
add('profile_views_weekly', 'emails/profile_views_weekly.py profile_views_html', 'member',
    'HELD: cron returnmail Wednesday, AHAVAH_PROFILE_VIEW_EMAIL_ENABLED (' + SWITCH_NOTE + ')',
    lambda: (profile_views_weekly.subject_for(3), profile_views_weekly.profile_views_html(3, S_LINK, unsub('notifications'))),
    profile_views_weekly.FROM_ADDR)
add('one_photo_nudge', 'emails/one_photo_nudge.py one_photo_html', 'member',
    'HELD: cron returnmail Tuesday, AHAVAH_ONE_PHOTO_NUDGE_ENABLED (' + SWITCH_NOTE + ')',
    lambda: (one_photo_nudge.SUBJECT, one_photo_nudge.one_photo_html(S_LINK, unsub('campaigns'))), one_photo_nudge.FROM_ADDR)
add('friend_joined', 'emails/friend_joined.py friend_joined_html', 'member',
    'HELD: /finish-onboarding queue_for_inviter, AHAVAH_FRIEND_JOINED_ENABLED (' + SWITCH_NOTE + ')',
    lambda: (friend_joined.SUBJECT, friend_joined.friend_joined_html(S_LINK, unsub('campaigns'))), friend_joined.FROM_ADDR)
add('referral_intro_member', 'emails/referral_intro.py referral_intro_html(member=True)', 'member',
    'HELD: cron referralintro daily (DUO_CRON_REFERRAL_INTRO_ENABLED default 1) queues nothing until AHAVAH_REFERRAL_MEMBER_BODY_ENABLED is on',
    lambda: (referral_intro.MEMBER_SUBJECT, referral_intro.referral_intro_html(TO, CODE, member=True, share_href=S_LINK, link_href=S_LINK)),
    referral_intro.FROM_ADDR)


def _ql():
    q = questions_launch.SAMPLE_QUESTION
    links = [(o['label'], f"{WEB_BASE_URL}/q/{q['key']}/{o['key']}?t={TOK[:40]}") for o in q['options']]
    return questions_launch.SUBJECT, questions_launch.launch_html(q, links, unsub('campaigns'))


add('questions_launch', 'emails/questions_launch.py launch_html', 'member',
    'SCHEDULED: cron returnmail on a drop day with AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED; droplet timer ahavah-qq-launch Tue 20 Oct 11:30 UTC turns it on',
    _ql, questions_launch.FROM_ADDR)

# ===========================================================================
# 8. Together (service/tools/mail.py), all behind switches, launch pending
from service.tools import mail as T  # noqa: E402
_sess = '7c1e4b2a-9d3f-4e8a-b6c5-1f2a3b4c5d6e'
add('together_answered_game', 'service/tools/mail.py answered_html (game)', 'member or lead',
    'HELD: AHAVAH_TOGETHER_LIVE_ENABLED + AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED, off until launch',
    lambda: (T.answered_subject('Rivka'), T.answered_html('Rivka', T.result_url('game', _sess), unsub('notifications'))),
    T.FROM_ADDR)
add('together_ready_checklist', 'service/tools/mail.py answered_html (checklist)', 'member or lead',
    'HELD: AHAVAH_TOGETHER_READY_EMAIL_ENABLED, off until launch',
    lambda: (T.answered_subject('Rivka', 'checklist'), T.answered_html('Rivka', T.result_url('checklist', _sess), unsub('notifications'), seat='guest', kind='checklist')),
    T.FROM_ADDR)
add('together_invite_game', 'service/tools/mail.py invite_html (game)', 'anyone (address typed by a player)',
    'HELD: AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED, off until launch',
    lambda: (T.invite_subject('game'), T.invite_html('game', 'Rivka', T.invite_url(TOK[:43]))), T.FROM_ADDR)
add('together_invite_checklist', 'service/tools/mail.py invite_html (checklist)', 'anyone (address typed by a player)',
    'HELD: AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED, off until launch',
    lambda: (T.invite_subject('checklist'), T.invite_html('checklist', 'Rivka', T.invite_url(TOK[:43]))), T.FROM_ADDR)
add('together_checklist_summary', 'emails/marriage_checklist.py checklist_results_html(stored=True) via service/tools/mail.py queue_summary', 'member or lead',
    'HELD: AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED, off until launch',
    lambda: (CL_SUBJECT, checklist_results_html('wife', _CL_SAMPLE, stored=True)), T.FROM_ADDR)

# ===========================================================================
# 8b. Gatherings (service/events/mail.py, TEC-1845), all behind switches and
# AHAVAH_EVENTS_LIVE_ENABLED, launch pending
from service.events import mail as EV  # noqa: E402
_EV_HELD = 'HELD: AHAVAH_EVENTS_LIVE_ENABLED + {}, off until launch'
for _name, _src, _aud, _switch, _build in (
        ('event_confirm', 'confirm_email (in person)', 'member or lead', 'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED', EV.preview_confirm),
        ('event_confirm_online', 'confirm_email (online)', 'member or lead', 'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED', EV.preview_confirm_online),
        ('event_reminder', 'reminder_email (in person)', 'member or lead', 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED', EV.preview_reminder),
        ('event_reminder_online', 'reminder_email (online)', 'member or lead', 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED', EV.preview_reminder_online),
        ('event_change', 'change_email', 'member or lead', 'AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED', EV.preview_change),
        ('event_cancelled', 'cancelled_email', 'member or lead', 'AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED', EV.preview_cancelled),
        ('event_digest', 'digest_email', 'organiser', 'AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED', EV.preview_digest),
        ('event_manage', 'manage_email', 'organiser', 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED', EV.preview_manage),
        ('event_approved', 'manage_email (approved note)', 'organiser', 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED', EV.preview_approved),
        ('event_live', 'manage_email (live note)', 'organiser', 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED', EV.preview_live)):
    add(_name, f'service/events/mail.py {_src}', _aud, _EV_HELD.format(_switch),
        (lambda b: lambda: b(TO))(_build), EV.FROM_ADDR)

# ===========================================================================
# 8c. Matchmaker (service/matchmaker/mail.py, TEC-1845), all behind switches
# and AHAVAH_MATCHMAKER_LIVE_ENABLED, launch pending
from service.matchmaker import mail as MM  # noqa: E402
_MM_HELD = 'HELD: AHAVAH_MATCHMAKER_LIVE_ENABLED + {}, off until launch'
for _name, _src, _aud, _switch, _build in (
        ('mm_alert_several', 'alert_email (several)', 'member', 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED', MM.preview_alert_several),
        ('mm_alert_one', 'alert_email (1)', 'member', 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED', MM.preview_alert_one),
        ('mm_alert_with_likes', 'alert_email (with the likes block)', 'member', 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED', MM.preview_alert_with_likes),
        ('mm_visitor_confirm', 'visitor_confirm_email', 'lead', 'AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED', MM.preview_visitor_confirm),
        ('mm_visitor_alert', 'visitor_alert_email', 'lead', 'AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED', MM.preview_visitor_alert),
        ('mm_recommend', 'recommend_email', 'lead', 'AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED', MM.preview_recommend),
        ('mm_intro', 'intro_email', 'member', 'AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED', MM.preview_intro),
        ('mm_mentor_invite', 'mentor_invite_email', 'lead', 'AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED', MM.preview_mentor_invite)):
    add(_name, f'service/matchmaker/mail.py {_src}', _aud, _MM_HELD.format(_switch),
        (lambda b: lambda: b(TO))(_build), MM.FROM_ADDR)

# ===========================================================================
# 9. Personal notes (one-off CLI, sent once in Oct 2026)
from emails import spotlight_candidates_note, warm_leads_note  # noqa: E402
add('spotlight_candidates_note', 'emails/spotlight_candidates_note.py note_html', 'member',
    'ONE-OFF CLI: emails/send_spotlight_candidates_note.py --send (campaign spotlight-note-2026-10, once ever per member)',
    lambda: (spotlight_candidates_note.SUBJECT, spotlight_candidates_note.note_html(FIRST, unsub('campaigns'))),
    'support@ahavah.app')
add('warm_leads_note', 'emails/warm_leads_note.py note_html', 'lead',
    'ONE-OFF CLI: emails/send_warm_leads_note.py --send (warm_leads_note_2026_10, once per lead)',
    lambda: (warm_leads_note.SUBJECT, warm_leads_note.note_html(FIRST, 58, unsub('waitlist'))), 'support@ahavah.app')

# ===========================================================================
# 10. Beta-era and one-off blasts (manual CLI only; no cron or route calls them)
from emails import (beta_launch, beta_premium_reminder, chat_fix, comeback, community_invite, digest,  # noqa: E402
                    first_match_announcement, launch, likes_waiting, marriage_checklist_launch,
                    new_features, onboarding_nudge, premium_referral, profile_nudge,
                    reengagement_reminder, referral_community)

CLI = 'MANUAL CLI ONLY: python -m emails.{m}; no cron, route or timer in the repo calls it (beta-era or one-off blast)'
add('beta_launch', 'emails/beta_launch.py beta_launch_html', 'lead', CLI.format(m='send_beta_launch'),
    lambda: (beta_launch.SUBJECT, beta_launch.beta_launch_html(TO)), beta_launch.FROM_ADDR)
add('beta_premium_reminder', 'emails/beta_premium_reminder.py beta_premium_html', 'member', CLI.format(m='send_beta_premium_reminder'),
    lambda: (beta_premium_reminder.SUBJECT, beta_premium_reminder.beta_premium_html(TO)), beta_premium_reminder.FROM_ADDR)
add('chat_fix', 'emails/chat_fix.py chat_fix_html', 'member', CLI.format(m='send_chat_fix'),
    lambda: (chat_fix.SUBJECT, chat_fix.chat_fix_html(TO)), chat_fix.FROM_ADDR)
add('comeback', 'emails/comeback.py comeback_html', 'member', CLI.format(m='send_comeback'),
    lambda: (comeback.SUBJECT, comeback.comeback_html(unsub('campaigns'))), comeback.FROM_ADDR)
add('community_invite', 'emails/community_invite.py community_invite_html', 'lead', CLI.format(m='send_community_invite'),
    lambda: (community_invite.SUBJECT, community_invite.community_invite_html(TO)), community_invite.FROM_ADDR)
add('digest_legacy', 'emails/digest.py digest_html (replaced by E2)', 'member', CLI.format(m='send_digest'),
    lambda: (digest.subject_for(3), digest.digest_html(['Rivka', 'Daniel', 'Abigail'], 58, 4, unsub('campaigns'))),
    digest.FROM_ADDR)
add('first_match_announcement', 'emails/first_match_announcement.py first_match_html', 'member', CLI.format(m='send_first_match_announcement'),
    lambda: (first_match_announcement.SUBJECT, first_match_announcement.first_match_html(TO)), first_match_announcement.FROM_ADDR)
add('launch', 'emails/launch.py launch_html', 'lead', CLI.format(m='send_launch'),
    lambda: (launch.SUBJECT, launch.launch_html(TO, f'{WEB_BASE_URL}/claim/{TOK}')), launch.FROM_ADDR)
add('likes_waiting_legacy', 'emails/likes_waiting.py likes_waiting_html (replaced by likes_waiting_weekly)', 'member', CLI.format(m='send_likes_waiting'),
    lambda: (likes_waiting.subject_for(3), likes_waiting.likes_waiting_html(3, unsub('notifications'))), likes_waiting.FROM_ADDR)
add('marriage_checklist_launch', 'emails/marriage_checklist_launch.py launch_checklist_html', 'member', CLI.format(m='send_marriage_checklist_launch'),
    lambda: (marriage_checklist_launch.SUBJECT, marriage_checklist_launch.launch_checklist_html(TO)), marriage_checklist_launch.FROM_ADDR)
add('new_features', 'emails/new_features.py new_features_html', 'member', CLI.format(m='send_new_features'),
    lambda: (new_features.SUBJECT, new_features.new_features_html(TO)), new_features.FROM_ADDR)
add('onboarding_nudge', 'emails/onboarding_nudge.py onboarding_nudge_html', 'member', CLI.format(m='send_onboarding_nudge'),
    lambda: (onboarding_nudge.SUBJECT, onboarding_nudge.onboarding_nudge_html(FIRST, unsub('campaigns'))), onboarding_nudge.FROM_ADDR)
add('premium_referral_welcome', 'emails/premium_referral.py welcome_html', 'member', CLI.format(m='send_premium_referral'),
    lambda: (premium_referral.SUBJECT_WELCOME, premium_referral.welcome_html(PREMIUM_UNTIL, f'https://ahavah.app/i/{CODE}', unsub('campaigns'))),
    premium_referral.FROM_ADDR)
add('premium_referral_reminder', 'emails/premium_referral.py reminder_html', 'member', CLI.format(m='send_premium_referral'),
    lambda: (premium_referral.SUBJECT_REMINDER, premium_referral.reminder_html(PREMIUM_UNTIL, f'https://ahavah.app/i/{CODE}', unsub('campaigns'))),
    premium_referral.FROM_ADDR)
add('profile_nudge', 'emails/profile_nudge.py profile_nudge_html', 'member', CLI.format(m='send_profile_nudge'),
    lambda: (profile_nudge.SUBJECT, profile_nudge.profile_nudge_html(TO, ['city', 'intent', 'children'])), profile_nudge.FROM_ADDR)
add('reengagement_reminder', 'emails/reengagement_reminder.py reengagement_reminder_html', 'lead', CLI.format(m='send_reengagement_reminder'),
    lambda: (reengagement_reminder.SUBJECT, reengagement_reminder.reengagement_reminder_html(TO)), reengagement_reminder.FROM_ADDR)
add('referral_community', 'emails/referral_community.py referral_community_html', 'member', CLI.format(m='send_referral_community'),
    lambda: (referral_community.SUBJECT, referral_community.referral_community_html(TO, CODE)), referral_community.FROM_ADDR)
add('referral_intro_beta', 'emails/referral_intro.py referral_intro_html(member=False)', 'member', CLI.format(m='send_referral_intro'),
    lambda: (referral_intro.SUBJECT, referral_intro.referral_intro_html(TO, CODE)), referral_intro.FROM_ADDR)

# ===========================================================================
# 11. Staff-only (never reach a member)
from emails import feedback, waitlist_admin  # noqa: E402
_ans = dict(first_name='Miriam', gender='Woman', age=29, country='United States', city='Austin',
            denomination='Messianic', looking_for=['Marriage'], heard_from='Instagram')
add('STAFF_feedback', 'emails/feedback.py feedback_html', 'staff',
    'LIVE, STAFF: POST feedback (service/api/feedback_routes.py) to the feedback inbox',
    lambda: ('Ahavah feedback: Problem', feedback.feedback_html('problem', 'The discover page froze after I liked someone.\nOn iPhone.',
                                                        TO, '/discover', 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)')),
    feedback.FROM_ADDR)
add('STAFF_waitlist_new_signup', 'emails/waitlist_admin.py new_signup_html(mode=signup)', 'staff',
    'LIVE, STAFF: POST /waitlist and account sign-up (service/person) notify the owner',
    lambda: ('New Ahavah signup 💜', waitlist_admin.new_signup_html(TO, _ans, 412, mode='signup', beta=False)), waitlist_admin.FROM_ADDR)
add('STAFF_waitlist_completed', 'emails/waitlist_admin.py new_signup_html(mode=completed)', 'staff',
    'LIVE, STAFF: waitlist answers completed',
    lambda: ('Ahavah onboarding completed', waitlist_admin.new_signup_html(TO, _ans, None, mode='completed', beta=True)), waitlist_admin.FROM_ADDR)
add('STAFF_beta_optin', 'emails/waitlist_admin.py new_signup_html(mode=beta)', 'staff',
    'LIVE, STAFF: beta opt-in (service/api/beta_routes.py)',
    lambda: ('New Ahavah beta tester', waitlist_admin.new_signup_html(TO, None, 87, mode='beta')), waitlist_admin.FROM_ADDR)


def _nsfw():
    from service.cron.garbagerecords import _nsfw_admin_notice_html
    return 'NSFW auto-removal: 1 photo(s)', _nsfw_admin_notice_html(
        [dict(person_name='Miriam Levi', uuid='3f9a2c1e-7b6d-4e5f-8a9b-0c1d2e3f4a5b', score=0.913)])


add('STAFF_nsfw_removed', 'service/cron/garbagerecords/__init__.py _nsfw_admin_notice_html', 'staff',
    'LIVE, STAFF: cron garbagerecords after an NSFW auto-removal', _nsfw, waitlist_admin.FROM_ADDR)


def _report():
    from antiabuse.lodgereport import report_subject, report_template
    report = dict(reporter_id=101, reporter_uuid='3f9a2c1e-7b6d-4e5f-8a9b-0c1d2e3f4a5b',
                  reporter_name='Miriam Levi', reported_id=202,
                  reported_uuid='9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d', reported_name='Samuel Cohen',
                  message_count=14, reported_at=NOW)
    reason = 'harassment: He kept messaging after I said I was not interested, and it got rude.'
    return report_subject(reason, False), report_template(report=report, reason=reason)


add('STAFF_report', 'antiabuse/lodgereport/__init__.py report_template', 'staff',
    'LIVE, STAFF: a member report to DUO_REPORT_EMAIL, from support@ (TEC-1845)', _report,
    'support@ahavah.app')
