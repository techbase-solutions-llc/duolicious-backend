"""The switches for the mail held for the owner's proof (health review,
13 Oct 2026, Wave 3).

Nothing new reaches members before a proof reaches the owner and he
confirms it. So each new or changed email ships behind its own switch, and
every switch is OFF unless its variable is set to 1, true, yes or on in the
environment of the container that sends it (docker-compose.production.yml
passes each one through, defaulting to 0). Anything else, a typo included,
reads as off: a switch that fails must fail towards sending nothing, and
some of these are read inside a member's own request (finishing sign-up),
which must never break over a setting.

Read on every call, as the photo gate is (service/photo_gate.py), so a test
can flip one and production needs only the variable and a restart.

`scripts/send_proofs.py` reads none of them and changes none of them: a
proof goes to the owner whichever way a switch is set.
"""
from __future__ import annotations

import os

# Name used in code -> environment variable. One place, so the proof script,
# the cron and the tests agree on what exists.
SWITCHES = {
    # Weekly count of likes waiting, with the new-fit line (findings 57, 64).
    'likes_waiting': 'AHAVAH_LIKES_WAITING_ENABLED',
    # Reminders for a silent match and an unanswered message (finding 61).
    'match_reminder': 'AHAVAH_MATCH_REMINDER_ENABLED',
    'message_reminder': 'AHAVAH_MESSAGE_REMINDER_ENABLED',
    # Weekly count of profile views for members who asked for it (65).
    'profile_views': 'AHAVAH_PROFILE_VIEW_EMAIL_ENABLED',
    # Members with exactly one approved photo (38).
    'one_photo': 'AHAVAH_ONE_PHOTO_NUDGE_ENABLED',
    # E2's personal line and the member's own invite link (60, 76).
    'e2_personal': 'AHAVAH_E2_PERSONAL_ENABLED',
    # The members' referral body; the referral cron waits for it (68).
    'referral_member': 'AHAVAH_REFERRAL_MEMBER_BODY_ENABLED',
    # The inviter hears when a friend joins (75).
    'friend_joined': 'AHAVAH_FRIEND_JOINED_ENABLED',
    # E1 once more, with fresh tokens, to members who never had it (80).
    'e1_resend': 'AHAVAH_E1_RESEND_ENABLED',
    # E1 and E4 say "your main profile photo" (web lane copy, 79 and 82).
    'spotlight_copy': 'AHAVAH_SPOTLIGHT_COPY_ENABLED',
    # Quick questions (TEC-1845), the master switch: until launch day the
    # app shows members no question and takes no answer, and nothing below
    # sends, whichever way its own switch is set. Admin > Questions works
    # either way, so the schedule can be approved beforehand.
    'questions_live': 'AHAVAH_QUESTIONS_LIVE_ENABLED',
    # Quick questions (TEC-1845): the weekly question push and the
    # silent-match push, the question line in E2, and the launch email and
    # push. Off until the owner has seen each proof on his own device, and
    # each needs questions_live as well (service.questions.switch_on).
    'question_push': 'AHAVAH_QUESTION_PUSH_ENABLED',
    'match_question_push': 'AHAVAH_MATCH_QUESTION_PUSH_ENABLED',
    'e2_question_line': 'AHAVAH_E2_QUESTION_LINE_ENABLED',
    'questions_launch_email': 'AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED',
    'questions_launch_push': 'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED',
    # Together (TEC-1845), the master switch: until launch every /tools
    # route but /tools/status answers 404, /together is not found and the
    # marriage checklist stays as it was. Nothing below sends while it is
    # off, whichever way its own switch is set (service.tools.switch_on).
    'together_live': 'AHAVAH_TOGETHER_LIVE_ENABLED',
    # Together's emails, each off until the owner has seen its proof: the
    # invite a player sends, the note that the other person has answered
    # (game), the note that the comparison is ready (checklist) and the
    # checklist summary a player gets when they finish.
    'together_invite_email': 'AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED',
    'together_answered_email': 'AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED',
    'together_ready_email': 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
    'together_summary_email': 'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED',
    # Gatherings (TEC-1845), the master switch: until launch every /events,
    # /e, /rsvp, /organiser, /host-requests and /invite-ahavah route but
    # /events/status answers 404, and nothing below opens or sends,
    # whichever way its own switch is set (service.events.switch_on).
    # Admin > Events works either way, so the owner can prepare.
    'events_live': 'AHAVAH_EVENTS_LIVE_ENABLED',
    # The surfaces opened after launch, in the spec's rollout order: the
    # public request to host, the /events list and the landing section, and
    # the leaders' /invite-ahavah page. Each needs events_live.
    'events_hosting': 'AHAVAH_EVENTS_HOSTING_ENABLED',
    'events_list': 'AHAVAH_EVENTS_LIST_ENABLED',
    'events_invite': 'AHAVAH_EVENTS_INVITE_ENABLED',
    # The gathering emails, each off until the owner has seen its proof
    # (scripts/send_event_proofs.py): the guest's confirm link, the reminder
    # the day before, a change, a cancellation, the organiser's daily digest
    # and the organiser's manage link (with its approved and live notes).
    'events_confirm_email': 'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED',
    'events_reminder_email': 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED',
    'events_change_email': 'AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED',
    'events_cancel_email': 'AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED',
    'events_digest_email': 'AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED',
    'events_manage_email': 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED',
    # Inviting gathering guests who are not members to join (TEC-1845): the
    # block on the confirmed page and in the confirm and reminder emails,
    # and the one invitation the day after; each off until the owner has
    # seen its proof, each needs events_live.
    'events_join_block': 'AHAVAH_EVENTS_JOIN_BLOCK_ENABLED',
    'events_join_invite_email': 'AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED',
    # Matchmaker (TEC-1845), the master switch: until launch every
    # /matchmaker, /alerts, /introductions, /recommendations, /mentor and
    # /conversations/<uuid>/share route but /matchmaker/status answers 404,
    # and nothing below opens or sends, whichever way its own switch is set
    # (service.matchmaker.switch_on). Admin > Growth and Moderation > Text
    # work either way.
    'matchmaker_live': 'AHAVAH_MATCHMAKER_LIVE_ENABLED',
    # The surfaces, in the spec's rollout order: members' alerts, visitors'
    # alerts, introductions (recommend and suggest) and mentors (mentors,
    # sharing and /families). Each needs matchmaker_live.
    'matchmaker_alerts': 'AHAVAH_MATCHMAKER_ALERTS_ENABLED',
    'matchmaker_visitor_alerts': 'AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED',
    'matchmaker_introductions': 'AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED',
    'matchmaker_mentors': 'AHAVAH_MATCHMAKER_MENTORS_ENABLED',
    # The matchmaker emails and pushes, each off until the owner has seen
    # its proof (scripts/send_matchmaker_proofs.py): a member's alert, a
    # visitor's confirm link and alert, a recommendation, an introduction
    # and a mentor's invitation; the alert push and the introduction push.
    'matchmaker_alert_email': 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED',
    'matchmaker_visitor_confirm_email': 'AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED',
    'matchmaker_visitor_alert_email': 'AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED',
    'matchmaker_recommend_email': 'AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED',
    'matchmaker_intro_email': 'AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED',
    'matchmaker_mentor_invite_email': 'AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED',
    'matchmaker_alert_push': 'AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED',
    'matchmaker_intro_push': 'AHAVAH_MATCHMAKER_INTRO_PUSH_ENABLED',
    # Owner alerts (TEC-1897), to the owner alone, never to a member. The
    # adminalerts cron does nothing while its switch is off; the daily list
    # of posts in review for more than 24 hours needs its own switch as
    # well, once the owner has seen its proof
    # (scripts/send_admin_alert_proofs.py). The report email has no switch
    # here: it is live, and the owner's "Email me when a report arrives"
    # preference (admin_alert_pref) turns it off.
    'admin_alerts_cron': 'AHAVAH_ADMIN_ALERTS_CRON_ENABLED',
    'stale_post_alert': 'AHAVAH_STALE_POST_ALERT_ENABLED',
    # The note to a member whose photo the NSFW cron rejected (TEC-1845
    # admin audit): the same "About one of your photos" an admin's Take
    # down sends, queued through the outbox by the cron. Off until the
    # owner decides automatic takedowns should be announced.
    'auto_photo_removed_email': 'AHAVAH_AUTO_PHOTO_REMOVED_EMAIL_ENABLED',
    # The gatherings section in E2 and the welcome's mention (TEC-1845),
    # each off until the owner has seen its proof; each needs events_live
    # and events_list, since both link to /events
    # (service.events.member_email_on).
    'e2_gatherings': 'AHAVAH_E2_GATHERINGS_ENABLED',
    'welcome_gatherings': 'AHAVAH_WELCOME_GATHERINGS_ENABLED',
    # Release 4 of the in-app plan (TEC-1845; ahavah-web docs/plans/
    # 2026-10-22-in-app-entry-and-sign-up.md, section 9). "Your Ahavah",
    # the light sign-in: every /your-ahavah route answers 404 until it is
    # on, and it counts only once matchmaker_live is on too, since
    # /matchmaker/status reports it (service/your_ahavah).
    'light_sign_in': 'AHAVAH_LIGHT_SIGN_IN_ENABLED',
    # The 3 member pushes, each off until the owner has seen its proof
    # (scripts/send_proofs.py) and each needing its feature as well
    # (service/notifications/activity_pushes.py): a reminder of a gathering
    # the member is going to (events_live), new guests for a gathering the
    # member hosts (events_live and events_hosting) and "your match
    # finished the game" (together_live).
    'push_gathering_reminder': 'AHAVAH_PUSH_GATHERING_REMINDER_ENABLED',
    'push_new_guests': 'AHAVAH_PUSH_NEW_GUESTS_ENABLED',
    'push_match_played': 'AHAVAH_PUSH_MATCH_PLAYED_ENABLED',
}

_ON = frozenset({'1', 'true', 'yes', 'on'})


def enabled(name: str) -> bool:
    """True only when the switch's variable is explicitly on. An unknown
    name raises: that is a typo in code, not in the environment."""
    env = SWITCHES[name]
    return os.environ.get(env, '').strip().lower() in _ON
