"""Every cron that can send email or push, with how it avoids sending twice
and the switch that turns it on (send safeguards plan, 2 Nov 2026, tasks 2
and 5A).

tests/test_cron_send_registry.py builds the import graph of the repo and
fails the deploy when a cron that reaches a sender is missing here, or names
no dedupe and is not in NO_DEDUPE_GRANDFATHERED.
tests/test_send_switches_default_off.py fails it when a cron here names no
switch from service/campaigns/switches.py SWITCHES (unless it is in
NO_SWITCH_GRANDFATHERED or OWNER_ONLY), or when docker-compose.production.yml
does not pass that switch to the cron container as ${VAR:-0}. So a new cron
that sends cannot deploy without a record of what it sent and a switch that
is off until someone sets it on the droplet.

This file is read by those tests as a literal (ast.literal_eval), never
imported by them: keep every value below a plain literal.

The three grandfathered tuples may shrink, never grow. The tests hold the
largest each may be.
"""

# module -> {channel, dedupe, switch, note}
#   channel  'email', 'push' or 'email+push'
#   dedupe   the table, column or key that stops a second send, or None
#   switch   a name in SWITCHES, a tuple of names, or None
SENDING_CRONS = {
    'service.cron.adminalerts': {
        'channel': 'email', 'dedupe': 'admin_alert_log (alert, alert_key)',
        'switch': ('admin_alerts_cron', 'stale_post_alert'),
        'note': 'owner only; sends straight through the mailer'},
    'service.cron.autodeactivate2': {
        'channel': 'email', 'dedupe': None, 'switch': None,
        'note': 'dry run only since 1 Oct 2026; a dry run sends nothing and runs inside guard.no_send()'},
    'service.cron.betareengagement': {
        'channel': 'email', 'dedupe': 'beta_signup.reengagement_sent_at', 'switch': None,
        'note': 'claims the row before the send'},
    'service.cron.communityweekly': {
        'channel': 'email', 'dedupe': 'email_outbox (campaign, campaign_id, person_id), week id',
        'switch': None, 'note': 'off unless DUO_CRON_COMMUNITY_WEEKLY_ENABLED=1'},
    'service.cron.emailoutbox': {
        'channel': 'email', 'dedupe': 'email_outbox.state (reserved once, then accepted, failed or skipped)',
        'switch': None, 'note': 'the drain of queued mail'},
    'service.cron.garbagerecords': {
        'channel': 'email', 'dedupe': None, 'switch': None,
        'note': 'relies on DELETE ... RETURNING (service/cron/garbagerecords/sql)'},
    'service.cron.leadretention': {
        'channel': 'email', 'dedupe': 'email_outbox (campaign, campaign_id, organiser_id)', 'switch': None,
        'note': 'queues a gathering cancellation when an organiser is erased'},
    'service.cron.notifications': {
        'channel': 'email', 'dedupe': 'email_outbox message-<unread state>', 'switch': None,
        'note': 'the message email fallback'},
    'service.cron.nsfwphotorunner': {
        'channel': 'email', 'dedupe': 'email_outbox photo_removed-<photo uuid>',
        'switch': 'auto_photo_removed_email', 'note': 'the note to a member whose photo was rejected'},
    'service.cron.pendingdeletion': {
        'channel': 'email', 'dedupe': 'email_outbox (campaign, campaign_id, organiser_id)', 'switch': None,
        'note': 'queues a gathering cancellation when an organiser account is deleted'},
    'service.cron.profilereporter': {
        'channel': 'email', 'dedupe': None, 'switch': None,
        'note': 'report rows are deleted only after the loop (service/cron/profilereporter)'},
    'service.cron.referralintro': {
        'channel': 'email', 'dedupe': 'email_send_log and email_outbox referral-<week>',
        'switch': 'referral_member', 'note': 'also DUO_CRON_REFERRAL_INTRO_ENABLED, on by default'},
    'service.cron.returnmail': {
        'channel': 'email+push', 'dedupe': 'email_outbox keys and push_send_log',
        'switch': ('likes_waiting', 'match_reminder', 'message_reminder', 'profile_views', 'one_photo',
                'matchmaker_alert_email', 'matchmaker_visitor_alert_email', 'question_push',
                'match_question_push', 'questions_launch_push', 'questions_launch_email',
                'events_reminder_email', 'events_digest_email', 'events_join_invite_email',
                'push_gathering_reminder', 'push_new_guests', 'push_match_played'),
        'note': 'every job behind its own switch'},
    'service.cron.sendguard': {
        'channel': 'email+push', 'dedupe': 'sg:events trimmed only after Postgres has them; 20 alerts a day',
        'switch': None, 'note': 'the send guard alert, to the owner only'},
    'service.cron.verificationjobrunner': {
        'channel': 'email+push', 'dedupe': 'verification_job status and lease', 'switch': None,
        'note': 'tells a member the outcome of their verification once'},
}

# Crons that send with no record of what they sent. Each needs a follow-up
# to add one, in loop-risk order.
NO_DEDUPE_GRANDFATHERED = (
    'service.cron.autodeactivate2',
    'service.cron.garbagerecords',
    'service.cron.profilereporter',
)

# Crons that sent before the switch rule of 2 Nov 2026 and have no switch in
# SWITCHES (some have their own DUO_CRON_*_ENABLED variable).
NO_SWITCH_GRANDFATHERED = (
    'service.cron.autodeactivate2',
    'service.cron.betareengagement',
    'service.cron.communityweekly',
    'service.cron.emailoutbox',
    'service.cron.garbagerecords',
    'service.cron.leadretention',
    'service.cron.notifications',
    'service.cron.pendingdeletion',
    'service.cron.profilereporter',
    'service.cron.verificationjobrunner',
)

# Crons that write only to the owner, never to a member, and must not be
# switched off by default: the send guard's own alert.
OWNER_ONLY = (
    'service.cron.sendguard',
)

# Where the import graph stops, each because the edge it would follow does
# not send. Keep this short and say why.
GRAPH_STOPS = {
    # Imports only the R2 bucket settings from service.person (which also
    # sends sign-in codes). The spotlight crons reach service.person only
    # through here.
    'service.spotlight.storage': 'imports R2 settings from service.person, never a sender',
}
