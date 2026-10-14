"""SQL for the System tab — operational health snapshot."""
from service.admin.queries.days import (
    BARBADOS_TODAY,
    barbados_day,
    barbados_day_of_naive_utc,
    barbados_days,
)
from service.admin.queries.members import member_sql

_MEMBER = member_sql('person')

# Sign-ups and DAU/WAU/MAU count members (members.py). The `*_total` figures
# below them are raw table sizes, labelled by table name on the tab, and
# stay raw. "Today" is the Barbados day, as on every tab (days.py); the 7
# and 30 day figures are durations and stay in UTC.
Q_SYSTEM_HEALTH = f"""
    SELECT
        (SELECT COUNT(*) FROM person
          WHERE {_MEMBER}
            AND {barbados_day_of_naive_utc('sign_up_time')} = {BARBADOS_TODAY}) AS signups_today,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND sign_up_time > NOW() - INTERVAL '7 days') AS signups_7d,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND sign_up_time > NOW() - INTERVAL '30 days') AS signups_30d,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '24 hours') AS dau,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '7 days') AS wau,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '30 days') AS mau,
        (SELECT COUNT(*) FROM waitlist_signup) AS waitlist_total,
        (SELECT COUNT(*) FROM beta_signup) AS beta_total,
        (SELECT COUNT(*) FROM photo) AS photo_total,
        (SELECT COUNT(*) FROM referral) AS referral_total,
        (SELECT COUNT(*) FROM admin_audit_log) AS admin_actions_total
"""

# Sign-in SESSIONS with recent OTP activity. This counts duo_session rows by
# otp_expiry, which is bumped on every new code AND zeroed on a successful
# sign-in, so a member who asks for three codes on one session counts once.
# It says nothing whatever about whether a code arrived: there is no delivery
# signal for OTP anywhere in the system.
# The System tab used to print a hardcoded "100%" success and a hardcoded
# "0" failures on top of this number. Both are gone. Do not reintroduce a
# rate here without a real provider log behind it.
# Member feedback. Until 2026-09-24 no admin route queried this table at
# all: someone took the trouble to write to the product and nobody had seen
# it. There was one row.
#
# The table (migration 0019) is `id, category, message, email, path,
# user_agent, created_at`. There is NO read or resolved marker, so this
# panel cannot show an unread count and does not pretend to. It shows the
# newest 50 and says that is everything. Inventing a badge would be this
# work's own version of the defect it exists to remove.
#
# `message` is the member's own words and is the point of the panel, so
# unlike the chat archive it is read deliberately. `user_agent` is not: it
# is a debugging field, not something to put on a dashboard.
Q_FEEDBACK_RECENT = """
    SELECT id, category, message, email, path, created_at
      FROM feedback
     ORDER BY created_at DESC
     LIMIT 50
"""

Q_OTP_24H = """
    SELECT COUNT(*) AS sent_24h
      FROM duo_session
     WHERE otp_expiry > NOW() - INTERVAL '24 hours'
"""

# Sign-in codes requested and never entered, per Barbados day for the last
# 30 days, split into new addresses (no account when the code was asked
# for) and existing ones (TEC-1848, item 6). The free bot protection works
# if `new_never_entered` falls. Read from otp_request (migration 0065): one
# row per /request-otp that issued a code, marked entered by /check-otp. A
# resend on the same session is the same row.
#
# `refused` is the requests the server answered as though it had sent a
# code and did not (honeypot, timing stamp, new-address limits,
# undeliverable domain). They are kept off the never-entered line, which
# would otherwise rise with every bot the rules stop.
#
# Today's codes may still be entered: a code lives 10 minutes, so the
# current day's never-entered figure settles shortly after the day ends.
Q_OTP_DAILY = f"""
    WITH days AS ({barbados_days(30)})
    SELECT
        days.d AS day,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND r.new_address)
            AS new_requested,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND r.new_address
                              AND r.entered_at IS NULL)
            AS new_never_entered,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND NOT r.new_address)
            AS existing_requested,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND NOT r.new_address
                              AND r.entered_at IS NULL)
            AS existing_never_entered,
        COUNT(r.id) FILTER (WHERE r.refused IS NOT NULL)
            AS refused
      FROM days
      LEFT JOIN otp_request r
        ON r.requested_at >= NOW() - INTERVAL '31 days'
       AND {barbados_day('r.requested_at')} = days.d
     GROUP BY days.d
     ORDER BY days.d
"""

# Why requests were refused over the same 30 days, most frequent first.
Q_OTP_REFUSALS_30D = """
    SELECT refused AS reason, COUNT(*) AS count
      FROM otp_request
     WHERE refused IS NOT NULL
       AND requested_at > NOW() - INTERVAL '30 days'
     GROUP BY refused
     ORDER BY count DESC, refused
"""

# Campaign email delivery, which unlike OTP delivery IS measured: every
# message goes through email_outbox and the drain records what happened to
# it (service/campaigns/outbox.py).
#
# Two deliberate choices here.
#
# `acceptance_unknown` is kept apart from `failed`. They mean opposite
# things to whoever reads them: failed is known-not-sent and safe to retry,
# unknown is the provider may have taken it before we lost the answer, so a
# retry may put a second copy in a member's inbox.
#
# Only `accepted` carries a 24-hour window, because only `accepted` sets a
# timestamp (`sent_at`). A failed row nulls `reserved_at` and writes
# `last_error` with no time of its own, so any window over failures would be
# computed off `created_at`, which is when the message was QUEUED, not when
# it failed.
#
# So ONE of these six numbers is a window and five are all-time totals over a
# table nothing prunes. The card that renders them has to say so, because a
# single stuck row would otherwise put a permanent red warning on the System
# tab, and a warning that never clears is a warning nobody reads. If that
# becomes a real problem the answer is a failure timestamp on the table, not
# a window quietly computed off the wrong column here.
# EVERY state in outbox.STATES gets a column. A message that exists in the
# table and appears on no line is worse than no panel at all: an operator
# reconciling 26 recipients against 20 accepted needs somewhere for the other
# six to be. `skipped` is where the drain puts a message it refused
# (withdrawn, suppressed, unsubscribed, capped), and the cap in particular
# will fill it on the first Monday after any manual send.
Q_OUTBOX_HEALTH = """
    SELECT
      COUNT(*) FILTER (WHERE state = 'queued')             AS queued,
      COUNT(*) FILTER (WHERE state = 'reserved')           AS reserved,
      COUNT(*) FILTER (WHERE state = 'acceptance_unknown') AS acceptance_unknown,
      COUNT(*) FILTER (WHERE state = 'failed')             AS failed,
      COUNT(*) FILTER (WHERE state = 'skipped')            AS skipped,
      COUNT(*) FILTER (WHERE state = 'accepted'
                         AND sent_at > NOW() - INTERVAL '24 hours') AS accepted_24h,
      MIN(created_at) FILTER (WHERE state = 'queued')      AS oldest_queued_at
      FROM email_outbox
"""

# Verification jobs. Nothing in any of the three repos surfaced one of these
# before, so a selfie check that died left the member on a polling screen and
# the operator with no way to know it had happened.
#
#   queued      submitted, not yet picked up. Healthy for about a second.
#   running     in flight and inside its lease. Healthy. A lease is what
#               makes a run healthy, so a row with no lease at all is not
#               counted here: see `stuck`.
#   stuck       running and either past its lease or holding none. This is
#               the number that matters: when the cron is healthy it is
#               zero, and it goes non zero whether the cause is one dead
#               worker or the whole runner being down. A row here is a
#               member waiting with no answer.
#
#               A NULL lease belongs here rather than under `running`.
#               Migration 0053 stamped every row that existed and the claim
#               query always sets one, so it should be unreachable; if it
#               ever is reached, Q_ELIGIBLE_VERIFICATION_JOBS refuses to
#               reap it, so counting it as healthy would make it invisible
#               to the reaper and to the operator at once, which is the
#               worst of the two readings.
#   abandoned   the subset of `stuck` that has burned its retries. The cron
#               ends these and notifies the member, so this is a count of
#               rows waiting for that sweep and reads zero when the runner
#               is up. A number that stays non zero means nothing is
#               running the sweep.
#   failed      checks that did not pass, whether the classifier rejected
#               them or they died more times than they may be retried. Not
#               an error on its own, but a wall of them means the
#               classifier, not the members.
#
# `verification_job` rows are deleted at `expires_at`, which defaults to
# three days after the row is created, so every count here is a rolling
# three day window by design.
Q_VERIFICATION_JOBS = """
    SELECT
        COUNT(*) FILTER (
            WHERE status = 'queued'
        ) AS verification_queued,
        COUNT(*) FILTER (
            WHERE status = 'running'
              AND running_since IS NOT NULL
              AND running_since >= NOW() - make_interval(secs => %(lease_seconds)s)
        ) AS verification_running,
        COUNT(*) FILTER (
            WHERE status = 'running'
              AND (
                  running_since IS NULL
               OR running_since < NOW() - make_interval(secs => %(lease_seconds)s)
              )
        ) AS verification_stuck,
        COUNT(*) FILTER (
            WHERE status = 'running'
              AND running_since IS NOT NULL
              AND running_since < NOW() - make_interval(secs => %(lease_seconds)s)
              AND reap_count >= %(max_reaps)s
        ) AS verification_abandoned,
        COUNT(*) FILTER (
            WHERE status = 'failure'
        ) AS verification_failed
      FROM verification_job
"""
