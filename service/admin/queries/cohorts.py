"""SQL for the 3 Cohorts sub-tabs.

Waitlist and beta rows are pre-account records and are counted as rows. A
`person` on this tab is counted only when it is a member (members.py)."""
from service.admin.queries.days import (
    BARBADOS_TODAY, barbados_day, barbados_day_of_naive_utc, barbados_days)
from service.admin.queries.members import member_sql
from service.referrals import REFERRAL_REWARD_TOKENS

_MEMBER = member_sql('person')
_MEMBER_P = member_sql('p')

# Calendar days are Barbados days, as on every tab (days.py). "This week" is
# a duration and stays a plain 7 days back from now.

# ---- WAITLIST -----------------------------------------------------------

Q_WAITLIST_KPIS = f"""
    SELECT
        (SELECT COUNT(*) FROM waitlist_signup) AS total,
        (SELECT COUNT(*) FROM waitlist_signup WHERE answers <> '{{}}'::jsonb) AS complete,
        (SELECT COUNT(*) FROM waitlist_signup WHERE answers = '{{}}'::jsonb) AS empty,
        (SELECT COUNT(*) FROM waitlist_signup
          WHERE {barbados_day('created_at')} = {BARBADOS_TODAY}) AS today,
        (SELECT COUNT(*) FROM waitlist_signup WHERE created_at > NOW() - INTERVAL '7 days') AS this_week
"""

# 30-day signup velocity, stacked across the 3 sources.
Q_WAITLIST_VELOCITY_30D = f"""
    WITH days AS ({barbados_days(30)}
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM waitlist_signup
                   WHERE {barbados_day('created_at')} = days.d), 0) AS waitlist,
        COALESCE((SELECT COUNT(*) FROM beta_signup
                   WHERE {barbados_day('created_at')} = days.d), 0) AS beta,
        COALESCE((SELECT COUNT(*) FROM person
                   WHERE {_MEMBER} AND {barbados_day_of_naive_utc('sign_up_time')} = days.d), 0) AS person
      FROM days
     ORDER BY days.d
"""

# Demographics breakdowns. Each returns label + count rows for a bar chart.
Q_WAITLIST_SEX = """
    SELECT COALESCE(answers->>'sex', '(none)') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE answers <> '{}'::jsonb
     GROUP BY 1 ORDER BY 2 DESC
"""

Q_WAITLIST_INTENT = """
    SELECT jsonb_array_elements_text(answers->'intent') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE jsonb_typeof(answers->'intent') = 'array'
     GROUP BY 1 ORDER BY 2 DESC LIMIT 15
"""

Q_WAITLIST_COUNTRY = """
    SELECT COALESCE(answers->>'country', '(none)') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE answers <> '{}'::jsonb
     GROUP BY 1 ORDER BY 2 DESC LIMIT 10
"""

Q_WAITLIST_ETHNICITY = """
    SELECT COALESCE(answers->>'ethnicity', '(none)') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE answers <> '{}'::jsonb
     GROUP BY 1 ORDER BY 2 DESC LIMIT 10
"""

Q_WAITLIST_ASSEMBLY = """
    SELECT jsonb_array_elements_text(answers->'assembly') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE jsonb_typeof(answers->'assembly') = 'array'
     GROUP BY 1 ORDER BY 2 DESC LIMIT 15
"""

Q_WAITLIST_SOURCE = """
    SELECT COALESCE(answers->>'referral_source', '(none)') AS label, COUNT(*) AS count
      FROM waitlist_signup
     WHERE answers <> '{}'::jsonb
     GROUP BY 1 ORDER BY 2 DESC LIMIT 10
"""

# ---- BETA ---------------------------------------------------------------

# A tester has had the intro when the beta row says so, or when the
# referralintro cron sent it to their member account: the cron records its
# sends in email_send_log and never sets referral_intro_sent_at, so a
# tester it reached read "Never emailed" (TEC-1845 admin audit, Minor 28).
# The per-inviter query below already reads both.
_CRON_INTRO_AT = """(SELECT MIN(l.sent_at)
                       FROM person ip
                       JOIN email_send_log l ON l.person_id = ip.id AND l.campaign = 'referral'
                      WHERE lower(ip.email) = lower(b.email))"""
_INTRO_SENT = f"(b.referral_intro_sent_at IS NOT NULL OR {_CRON_INTRO_AT} IS NOT NULL)"

Q_BETA_KPIS = f"""
    SELECT
        (SELECT COUNT(*) FROM beta_signup) AS cohort_size,
        (SELECT COUNT(*) FROM beta_signup b
            WHERE EXISTS (SELECT 1 FROM person p WHERE p.email = b.email AND {_MEMBER_P})) AS completed_onboarding,
        (SELECT COUNT(*) FROM beta_signup WHERE referral_code IS NOT NULL) AS codes_minted,
        (SELECT COUNT(*) FROM beta_signup b WHERE {_INTRO_SENT}) AS intro_sent,
        (SELECT COUNT(*) FROM beta_signup b WHERE NOT {_INTRO_SENT}) AS never_emailed
"""

# referral_intro_sent_at is the beta send, or failing that the cron's first.
Q_BETA_ROWS = f"""
    SELECT
        b.email,
        b.referral_code,
        COALESCE(b.referral_intro_sent_at, {_CRON_INTRO_AT}) AS referral_intro_sent_at,
        b.unsubscribed_at,
        (p.uuid IS NOT NULL) AS has_person,
        p.sign_in_time
      FROM beta_signup b
      LEFT JOIN person p ON p.email = b.email
     ORDER BY b.created_at DESC
     LIMIT 100
"""

# Waitlist, then beta, then started onboarding, then completed it.
#
# started_onboarding is a beta address that has signed in: it has an
# `onboardee` row, which exists from the first sign-in until onboarding
# finishes, or a member's person row, which is written when it finishes.
# completed_onboarding is the person row alone. Until 13 Oct 2026 the funnel
# had no started step: its "Person" and "Completed" steps were the same set
# of email pairs by construction (both columns are unique), so both read 22
# and the funnel could only show 100% between them.
#
# person_from_beta is that old duplicate, equal to completed_onboarding by
# construction. It stays only for the admin build that still reads it.
Q_BETA_FUNNEL = f"""
    SELECT
        (SELECT COUNT(*) FROM waitlist_signup) AS waitlist_total,
        (SELECT COUNT(*) FROM beta_signup) AS beta_total,
        (SELECT COUNT(*) FROM beta_signup b
            WHERE EXISTS (SELECT 1 FROM onboardee o WHERE o.email = b.email)
               OR EXISTS (SELECT 1 FROM person p WHERE p.email = b.email AND {_MEMBER_P})) AS started_onboarding,
        (SELECT COUNT(*) FROM beta_signup b
            WHERE EXISTS (SELECT 1 FROM person p WHERE p.email = b.email AND {_MEMBER_P})) AS person_from_beta,
        (SELECT COUNT(*) FROM person p
            WHERE {_MEMBER_P}
              AND EXISTS (SELECT 1 FROM beta_signup b WHERE b.email = p.email)) AS completed_onboarding
"""

# ---- REFERRALS ----------------------------------------------------------

# A click is a person's: link previews and crawlers (user_agent_class
# 'bot') are left out of every click count on this sub-tab but the
# click-stream chart, which draws them as their own line. The Overview's
# click-through leaves them out the same way. Until 13 Oct 2026 Total clicks
# read 128, of which 48 were bots.
_HUMAN_CLICK = "user_agent_class IS DISTINCT FROM 'bot'"

Q_REFERRALS_KPIS = f"""
    SELECT
        (SELECT COUNT(*) FROM referral_link_click WHERE {_HUMAN_CLICK}) AS total_clicks,
        (SELECT COUNT(DISTINCT code) FROM referral_link_click
          WHERE code IS NOT NULL AND {_HUMAN_CLICK}) AS distinct_codes_clicked,
        (SELECT COUNT(*) FROM referral) AS signups_via_link,
        (SELECT COUNT(*) FROM referral WHERE status = 'credited') AS credits_fired
"""

# Click stream by UA class, 7d. The same Barbados days as the Overview's
# referral chart, which reads the same table.
_CLICKED_ON = barbados_day('created_at')

Q_REFERRALS_CLICK_STREAM_7D = f"""
    WITH days AS ({barbados_days(7)}
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM referral_link_click WHERE {_CLICKED_ON} = days.d AND user_agent_class = 'mobile'), 0) AS mobile,
        COALESCE((SELECT COUNT(*) FROM referral_link_click WHERE {_CLICKED_ON} = days.d AND user_agent_class = 'desktop'), 0) AS desktop,
        COALESCE((SELECT COUNT(*) FROM referral_link_click WHERE {_CLICKED_ON} = days.d AND user_agent_class = 'bot'), 0) AS bot
      FROM days
     ORDER BY days.d
"""

# One row per person who holds an invite code: a member's own
# (person.referral_code, every member since migration 0037) or a beta-era one
# (beta_signup.referral_code), grouped by address, so a beta tester who became
# a member is one row. The code shown is the member's, the link they share
# now; clicks on either code count.
#
# Until 13 Oct 2026 (health review findings 7, 25 and 73) this was built from
# beta_signup rows with the beta intro sent, joined to clicks on the address
# the logger stored. The logger stored no address for a member's code, and
# the referralintro cron's intro is in email_send_log, not beta_signup, so the
# 32 members sent the intro since 1 Oct could never appear and 87 of 128
# clicks were counted against nobody. Clicks are now counted on the code, so
# the figure does not wait on the logger or its backfill.
#
# The pending balance is the reward per pending or graduated referral, in
# tokens. It multiplied by a literal 5 (TEC-1845 admin audit, Minor 31).
#
# A holder is listed once the intro has gone to them (either kind) or their
# link has a click or a sign-up. Clicks are well-formed and not bots, as the
# logger only resolves well-formed codes. Staff accounts are listed like
# anyone else: this is who shared a link, not a count of members.
Q_REFERRALS_PER_INVITER = f"""
    WITH code_holder AS (
        SELECT lower(p.email) AS email, p.referral_code AS code, 0 AS beta,
               EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = 'referral') AS intro_sent
          FROM person p
         WHERE p.referral_code IS NOT NULL
        UNION ALL
        SELECT lower(b.email), b.referral_code, 1,
               b.referral_intro_sent_at IS NOT NULL
          FROM beta_signup b
         WHERE b.referral_code IS NOT NULL OR b.referral_intro_sent_at IS NOT NULL
    ),
    inviter AS (
        SELECT email,
               (array_agg(code ORDER BY beta))[1] AS referral_code,
               array_agg(code) FILTER (WHERE code IS NOT NULL) AS codes,
               bool_or(intro_sent) AS intro_sent
          FROM code_holder
         GROUP BY email
    ),
    counted AS (
        SELECT i.email AS inviter,
               i.referral_code,
               i.intro_sent,
               (SELECT COUNT(*) FROM referral_link_click rc
                 WHERE rc.code = ANY(i.codes) AND rc.well_formed
                   AND {_HUMAN_CLICK}) AS clicks,
               (SELECT COUNT(*) FROM referral r
                 WHERE lower(r.inviter_email) = i.email) AS signups,
               (SELECT COUNT(*) FROM referral r
                 WHERE lower(r.inviter_email) = i.email
                   AND r.status = 'credited') AS credited,
               (SELECT COUNT(*) FROM referral r
                 WHERE lower(r.inviter_email) = i.email
                   AND r.status IN ('pending','graduated')) * {REFERRAL_REWARD_TOKENS}
                   AS pending_token_balance
          FROM inviter i
    )
    SELECT inviter, referral_code, clicks, signups, credited, pending_token_balance
      FROM counted
     WHERE intro_sent OR clicks > 0 OR signups > 0
     ORDER BY clicks DESC, signups DESC, inviter
     LIMIT 50
"""
