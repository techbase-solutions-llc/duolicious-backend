"""SQL for the System tab — operational health snapshot."""
from service.admin.queries.days import (
    BARBADOS_TODAY,
    barbados_day,
    barbados_day_of_naive_utc,
    barbados_days,
)
from service.admin.queries.members import (
    current_member_sql, signed_up_member_sql)

_SIGNED_UP = signed_up_member_sql('person')
_MEMBER = current_member_sql('person')

# Sign-ups count everyone who signed up except staff and testers, deactivated
# since or not, so a past period never changes (signed_up_member_sql);
# DAU/WAU/MAU leave out deactivated accounts too (current_member_sql). The
# same rules as Overview's sign-ups and active members (TEC-2144).
# The `*_total` figures
# below them are raw table sizes, labelled by table name on the tab, and
# stay raw. "Today" is the Barbados day, as on every tab (days.py); the 7
# and 30 day figures are durations and stay in UTC.
Q_SYSTEM_HEALTH = f"""
    SELECT
        (SELECT COUNT(*) FROM person
          WHERE {_SIGNED_UP}
            AND {barbados_day_of_naive_utc('sign_up_time')} = {BARBADOS_TODAY}) AS signups_today,
        (SELECT COUNT(*) FROM person WHERE {_SIGNED_UP} AND sign_up_time > NOW() - INTERVAL '7 days') AS signups_7d,
        (SELECT COUNT(*) FROM person WHERE {_SIGNED_UP} AND sign_up_time > NOW() - INTERVAL '30 days') AS signups_30d,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '24 hours') AS dau,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '7 days') AS wau,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '30 days') AS mau,
        (SELECT COUNT(*) FROM waitlist_signup) AS waitlist_total,
        (SELECT COUNT(*) FROM beta_signup) AS beta_total,
        (SELECT COUNT(*) FROM photo) AS photo_total,
        (SELECT COUNT(*) FROM referral) AS referral_total,
        (SELECT COUNT(*) FROM admin_audit_log) AS admin_actions_total
"""

# Sign-in and sign-up code requests that sent a code in the last 24 hours,
# from otp_request: one row per /request-otp that issued a code, so asking
# again counts again and a resend on the same request does not. Refused
# requests sent nothing and are left out, as are the event, visitor alert
# and tool invite forms (flow). Staff are included: it is a count of codes.
#
# Until 11 Nov 2026 this counted duo_session rows by otp_expiry, under a
# comment that said a sign-in zeroed it (it sets it to the sign-in time)
# and a card that said three codes on one session counted once (a new
# request deletes the old session, so it counted again). TEC-2144.
#
# It says nothing whatever about whether a code arrived: there is no
# delivery signal for OTP anywhere in the system. The System tab used to
# print a hardcoded "100%" success and a hardcoded "0" failures on top of
# this number. Both are gone. Do not reintroduce a rate here without a real
# provider log behind it.
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
      FROM otp_request
     WHERE flow = 'sign_in'
       AND refused IS NULL
       AND requested_at > NOW() - INTERVAL '24 hours'
"""

# Sign-in codes per Barbados day for the last 30 days, split into new
# addresses (no account when the code was asked for) and members signing
# in (TEC-1848, item 6). Read from otp_request (migrations 0065, 0097): one
# row per /request-otp that issued a code, marked entered by /check-otp. A
# resend on the same session is the same row.
#
# The never-finished columns count PEOPLE, not requests (TEC-2144). When an
# address asks again, /request-otp deletes its pending session and marks
# the earlier request `superseded`; the address is then counted by its
# latest request alone. So a request that is neither entered nor superseded
# is one address that never entered any code since, and each address
# appears on one day at most: the bars add up to the distinct addresses
# over the window. Until 11 Nov 2026 these counted every request, and read
# 65 for 17 addresses.
#
# Member columns leave out staff and testers (`staff`, recorded when the
# code was asked for with members.non_member_role_sql).
#
# `refused` is sign-up requests (new addresses, the sign-in form only) the
# server refused: the quiet refusals answered as a send (honeypot, timing
# stamp, new-address limits, undeliverable domain) and the ones it answers
# with an error (FireHOL blocklist, Turnstile, unknown domain). Event RSVP,
# visitor alert and tool invite refusals share the table under their own
# `flow` and are not sign-up codes. Refusals are kept off the never-finished
# line, which would otherwise rise with every bot the rules stop.
#
# `measured` is false for a day before the first request on file: the table
# began on 15 Oct 2026, and an unmeasured day is not a day with no codes.
#
# Today's codes may still be entered: a code lives 10 minutes, so the
# current day's figure settles shortly after the day ends.
Q_OTP_DAILY = f"""
    WITH days AS ({barbados_days(30)}),
    first AS (
        SELECT {barbados_day('MIN(requested_at)')} AS d
          FROM otp_request
         WHERE flow = 'sign_in'
    )
    SELECT
        days.d AS day,
        COALESCE(days.d >= (SELECT d FROM first), FALSE) AS measured,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND r.new_address)
            AS new_requested,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND r.new_address
                              AND r.entered_at IS NULL AND NOT r.superseded)
            AS new_never_entered,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND NOT r.new_address
                              AND NOT r.staff)
            AS existing_requested,
        COUNT(r.id) FILTER (WHERE r.refused IS NULL AND NOT r.new_address
                              AND NOT r.staff
                              AND r.entered_at IS NULL AND NOT r.superseded)
            AS existing_never_entered,
        COUNT(r.id) FILTER (WHERE r.refused IS NOT NULL AND r.new_address)
            AS refused
      FROM days
      LEFT JOIN otp_request r
        ON r.requested_at >= NOW() - INTERVAL '31 days'
       AND r.flow = 'sign_in'
       AND {barbados_day('r.requested_at')} = days.d
     GROUP BY days.d
     ORDER BY days.d
"""

# Why sign-up requests were refused over the same 30 Barbados days and the
# same rows as Q_OTP_DAILY's `refused`, most frequent first. It read a
# rolling NOW() - 30 days, so a refusal late on the day before the series
# began counted here and not in the refused total (TEC-1845 admin audit,
# Minor 14). The requested_at bound only lets the index narrow the scan.
Q_OTP_REFUSALS_30D = f"""
    SELECT refused AS reason, COUNT(*) AS count
      FROM otp_request
     WHERE refused IS NOT NULL
       AND flow = 'sign_in'
       AND new_address
       AND requested_at >= NOW() - INTERVAL '31 days'
       AND {barbados_day('requested_at')} >= {BARBADOS_TODAY} - 29
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
