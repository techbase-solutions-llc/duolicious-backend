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
}

_ON = frozenset({'1', 'true', 'yes', 'on'})


def enabled(name: str) -> bool:
    """True only when the switch's variable is explicitly on. An unknown
    name raises: that is a typo in code, not in the environment."""
    env = SWITCHES[name]
    return os.environ.get(env, '').strip().lower() in _ON
