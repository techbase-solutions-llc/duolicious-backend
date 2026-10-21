"""SQL for GET /admin/overview — the dashboard's top-of-page KPIs +
3 chart series + recent activity feed.

Every count of people here is a count of MEMBERS (members.py): staff
accounts have profiles, photos and Premium too, and counting them put
Overview at 61 persons on 13 Oct 2026 when there were 58 members."""
from service.admin.queries.days import (
    BARBADOS_TODAY, barbados_day, barbados_day_of_naive_utc, barbados_days)
from service.admin.queries.members import counted_member_sql, member_sql

_MEMBER = member_sql('person')
_MEMBER_P = member_sql('p')

# Every date bucket on this tab is a Barbados day (days.py).
_JOINED_ON = barbados_day_of_naive_utc('sign_up_time')


def live_stripe_event(e: str) -> str:
    """A LIVE Stripe event, for the `entitlement_event` row aliased `e`.

    Paying members and Premium adds share this, so a test-mode checkout can
    be a sale on neither. Until 1 Oct 2026 paying members counted any event,
    and every event on file was a test-mode checkout (livemode=false) by the
    owner and a beta tester, so the card said 3 while nobody had paid; the
    Premium adds chart kept counting them until 13 Oct 2026. Stripe sets
    `livemode` at the top of every event; the nested path covers a payload
    stored as the event object itself."""
    return (f"COALESCE({e}.payload->>'livemode', "
            f"{e}.payload->'data'->'object'->>'livemode') = 'true'")

Q_OVERVIEW_KPIS = f"""
    SELECT
        -- Signups are PEOPLE.
        --
        -- This used to count waitlist_signup + beta_signup, which were the
        -- pre-launch funnel: on 2026-09-24 they held zero rows for the
        -- previous week while five real members had joined, and the owner
        -- caught the card reading 0 on a day they had personally received a
        -- signup. The 30 day chart directly below the card already counted
        -- `person`, so the two disagreed on one screen.
        --
        -- Barbados days, not UTC ones, and `person.sign_up_time` is the one
        -- naive column here, so it takes the double conversion (days.py).
        (SELECT COUNT(*) FROM person
          WHERE {_MEMBER} AND {_JOINED_ON} = {BARBADOS_TODAY}) AS signups_today,
        -- A real yesterday to compare against. The card printed the literal
        -- string "vs 0 yesterday" every day, because nothing was sent.
        (SELECT COUNT(*) FROM person
          WHERE {_MEMBER} AND {_JOINED_ON} = {BARBADOS_TODAY} - 1) AS signups_yesterday,
        (SELECT COUNT(*) FROM person
          WHERE {_MEMBER} AND last_online_time > NOW() - INTERVAL '24 hours') AS active_24h,
        -- Named person_total for the admin build that reads it; it counts
        -- members.
        (SELECT COUNT(*) FROM person WHERE {_MEMBER}) AS person_total,
        (SELECT COUNT(*) FROM person WHERE {_MEMBER} AND 'premium' = ANY(entitlements)) AS premium_holders,
        -- "Premium holders" was a tautology on the dashboard: every person
        -- in the database holds premium (51 of 51 on 2026-09-24, all with a
        -- subscription_expires_at), so the card restated "Total persons"
        -- from two cards away. What is worth knowing is how many of them
        -- ever transacted: 3 of the 51.
        --
        -- premium_holders stays in the payload because the Economy tab
        -- reads it; it is just no longer a KPI card.
        -- Paying means a LIVE Stripe event (live_stripe_event above).
        (SELECT COUNT(*) FROM person p
          WHERE {_MEMBER_P}
            AND 'premium' = ANY(p.entitlements)
            AND EXISTS (SELECT 1 FROM entitlement_event e
                         WHERE e.app_user_id = p.id::text
                           AND {live_stripe_event('e')})) AS paying_members,
        -- Every report still waiting for an outcome (migrations 0072, 0075),
        -- including one whose block the reporter has since lifted.
        (SELECT COUNT(*) FROM person_report WHERE outcome IS NULL) AS pending_reports,
        (SELECT COUNT(*) FROM referral WHERE created_at > NOW() - INTERVAL '7 days') AS referral_signups_7d
"""

# Members as the Growth tab's Sources panel counts them: activated, not
# staff, not a test address (members.counted_member_sql; bind %(ex)s with
# service.growth.queries._excluded()). person_total above keeps its meaning,
# every non-staff person, which the admin labels as including deactivated
# and test accounts (TEC-1845 admin audit). A separate query because the
# KPI query takes no parameters and is run bare elsewhere.
Q_OVERVIEW_MEMBER_TOTAL = f"""
    SELECT COUNT(*)::int AS member_total FROM person p WHERE {counted_member_sql('p')}
"""

Q_OVERVIEW_SIGNUPS_30D = f"""
    WITH days AS ({barbados_days(30)}
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM waitlist_signup
                   WHERE {barbados_day('created_at')} = days.d), 0) AS waitlist,
        COALESCE((SELECT COUNT(*) FROM beta_signup
                   WHERE {barbados_day('created_at')} = days.d), 0) AS beta,
        COALESCE((SELECT COUNT(*) FROM person
                   WHERE {_MEMBER} AND {_JOINED_ON} = days.d), 0) AS person
      FROM days
     ORDER BY days.d
"""

# The Total persons sparkline: how many members there were by the end of
# each Barbados day. It used to borrow the daily sign-ups series, which
# measures something else. Accounts that have since been deleted are gone
# from `person`, so an earlier day shows the members still here who had
# joined by then.
Q_OVERVIEW_MEMBERS_30D = f"""
    WITH days AS ({barbados_days(30)}
    )
    SELECT
        days.d::text AS day,
        (SELECT COUNT(*) FROM person
          WHERE {_MEMBER} AND {_JOINED_ON} <= days.d) AS total
      FROM days
     ORDER BY days.d
"""

Q_OVERVIEW_REFERRAL_CTR_7D = f"""
    WITH days AS ({barbados_days(7)}
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM referral_link_click
                   WHERE {barbados_day('created_at')} = days.d
                     AND user_agent_class != 'bot'), 0) AS clicks,
        COALESCE((SELECT COUNT(*) FROM referral
                   WHERE {barbados_day('created_at')} = days.d), 0) AS signups
      FROM days
     ORDER BY days.d
"""

# Subscription purchases, from `entitlement_event`: the append-only ledger
# migration 0005 created for exactly this, fed by the Stripe webhook.
#
# This used to count admin_audit_log WHERE action = 'grant_entitlement'. That
# action has never been written once. Audited on 2026-09-24, the only actions
# that table has ever held are admin_map_view, growth.email.send,
# growth.queue.member_of_week and reject_photo, so the chart was structurally
# incapable of a non-zero bar and drew a flat line at zero while 15 checkouts
# had completed.
#
# Only LIVE events that START a paid relationship count here. Renewals,
# updates and cancellations are real, but folding them in would make a churn
# event look like a sale. The event types on file on 2026-09-24 were
# checkout.session.completed (15), customer.subscription.created (8),
# customer.subscription.deleted (8) and customer.subscription.updated (5).
#
# A new subscription is counted once, by its checkout.session.completed with
# session mode 'subscription' (TEC-1845 audit, 20 Oct 2026). The same
# checkout also sends customer.subscription.created, so counting both plotted
# every subscriber as 2 adds; and a token bundle is a checkout.session.
# completed with mode 'payment', which is not Premium at all. The checkout
# event is the one the webhook acts on (service/checkout), so it is the one
# certain to be on file. The nested path is the full event as the webhook
# stores it; the top-level one covers a payload stored as the object itself.
def _subscription_checkout(e: str) -> str:
    return (f"{e}.event_type = 'checkout.session.completed' "
            f"AND COALESCE({e}.payload->'data'->'object'->>'mode', "
            f"{e}.payload->>'mode') = 'subscription'")

Q_OVERVIEW_PREMIUM_30D = f"""
    WITH days AS ({barbados_days(30)}
    )
    SELECT
        days.d::text AS day,
        COALESCE((
            SELECT COUNT(*) FROM entitlement_event e
             WHERE {_subscription_checkout('e')}
               AND {live_stripe_event('e')}
               AND {barbados_day('e.received_at')} = days.d
        ), 0) AS adds
      FROM days
     ORDER BY days.d
"""

_RECENT_BRANCHES = f"""
    SELECT * FROM (
        -- A real member joining. Until 2026-09-24 the feed's only two
        -- signup sources were beta_signup and waitlist_signup, the
        -- pre-launch funnel, so somebody creating an account produced no
        -- line here at all.
        --
        -- Name, not email. The other branches carry emails because waitlist
        -- and beta rows are pre-account records with nothing else to show.
        -- A person row IS an account, and this feed is a glanceable list on
        -- a screen that may be open in a meeting; the uuid rides along as
        -- `object` so the row can open the user drawer instead.
        SELECT 'signup_member' AS kind, name AS subject, uuid::text AS object,
               sign_up_time AT TIME ZONE 'UTC' AS created_at
          FROM person WHERE {_MEMBER} ORDER BY sign_up_time DESC LIMIT 10
    ) sub_person
    UNION ALL SELECT * FROM (
        SELECT 'signup' AS kind, email AS subject, NULL::text AS object,
               created_at FROM beta_signup ORDER BY created_at DESC LIMIT 10
    ) sub_beta
    UNION ALL SELECT * FROM (
        SELECT 'signup_waitlist' AS kind, email AS subject, NULL::text AS object,
               created_at FROM waitlist_signup ORDER BY created_at DESC LIMIT 10
    ) sub_wl
    UNION ALL SELECT * FROM (
        SELECT 'referral_credited' AS kind, inviter_email AS subject, invitee_email AS object,
               credited_at AS created_at FROM referral
         WHERE status = 'credited' AND credited_at IS NOT NULL
         ORDER BY credited_at DESC LIMIT 10
    ) sub_ref
    UNION ALL SELECT * FROM (
        SELECT 'admin_action' AS kind, actor_email AS subject, action AS object,
               created_at FROM admin_audit_log
         -- Scheduled and command-line sends write audit rows as 'cron' and
         -- 'cli' (health review, finding 20). They belong on the Audit tab,
         -- not in a feed of what people did.
         WHERE actor_email NOT IN ('cron', 'cli')
         ORDER BY created_at DESC LIMIT 10
    ) sub_admin
"""

Q_OVERVIEW_RECENT_ACTIVITY = f"""{_RECENT_BRANCHES}    ORDER BY created_at DESC LIMIT 20
"""

# The same feed with reports and live Premium checkouts (TEC-1845 admin
# audit), sent as `recent_activity_all`. Both admins look each kind up in a
# fixed table and fail on one they do not know, so `recent_activity` keeps
# its five kinds and an admin that knows these two reads this instead. A
# report names the reported member and carries their uuid as `object`; a
# Premium row names the member who paid. Never the reason or the reporter.
Q_OVERVIEW_RECENT_ACTIVITY_ALL = f"""{_RECENT_BRANCHES}    UNION ALL SELECT * FROM (
        SELECT 'report' AS kind, reported.name AS subject, reported.uuid::text AS object,
               r.reported_at AT TIME ZONE 'UTC' AS created_at
          FROM person_report r
          JOIN person reported ON reported.id = r.reported_id
         ORDER BY r.reported_at DESC LIMIT 10
    ) sub_report
    UNION ALL SELECT * FROM (
        SELECT 'premium' AS kind, p.name AS subject, p.uuid::text AS object,
               e.received_at AS created_at
          FROM entitlement_event e
          JOIN person p ON p.id::text = e.app_user_id
         WHERE {_subscription_checkout('e')}
           AND {live_stripe_event('e')}
           AND {_MEMBER_P}
         ORDER BY e.received_at DESC LIMIT 10
    ) sub_premium
    ORDER BY created_at DESC LIMIT 20
"""
