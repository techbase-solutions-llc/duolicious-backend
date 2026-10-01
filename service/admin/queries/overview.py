"""SQL for GET /admin/overview — the dashboard's top-of-page KPIs +
3 chart series + recent activity feed."""

Q_OVERVIEW_KPIS = """
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
        -- Barbados, not UTC. The dashboard is read in Barbados, and under
        -- CURRENT_DATE a member who joins after 20:00 local lands on the
        -- next day's number. The conversion has to be on BOTH sides of the
        -- comparison; one side alone is an off-by-one that only shows near
        -- midnight.
        --
        -- The DOUBLE conversion is not redundant. `person.sign_up_time` is
        -- `timestamp WITHOUT time zone`, alone among the timestamps this
        -- file touches (waitlist_signup, beta_signup, referral,
        -- referral_link_click and entitlement_event are all timestamptz).
        -- On a naive column, `AT TIME ZONE 'America/Barbados'` READS the
        -- value as Barbados local, which is backwards: the column stores
        -- UTC. `AT TIME ZONE 'UTC'` first marks it as UTC, and only then
        -- does the second conversion mean what it says. Getting this wrong
        -- puts every evening signup on the wrong day in the direction that
        -- looks plausible.
        (SELECT COUNT(*) FROM person
          WHERE (sign_up_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Barbados')::date
                = (NOW() AT TIME ZONE 'America/Barbados')::date) AS signups_today,
        -- A real yesterday to compare against. The card printed the literal
        -- string "vs 0 yesterday" every day, because nothing was sent.
        (SELECT COUNT(*) FROM person
          WHERE (sign_up_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Barbados')::date
                = (NOW() AT TIME ZONE 'America/Barbados')::date - 1) AS signups_yesterday,
        (SELECT COUNT(*) FROM person WHERE last_online_time > NOW() - INTERVAL '24 hours') AS active_24h,
        (SELECT COUNT(*) FROM person) AS person_total,
        (SELECT COUNT(*) FROM person WHERE 'premium' = ANY(entitlements)) AS premium_holders,
        -- "Premium holders" was a tautology on the dashboard: every person
        -- in the database holds premium (51 of 51 on 2026-09-24, all with a
        -- subscription_expires_at), so the card restated "Total persons"
        -- from two cards away. What is worth knowing is how many of them
        -- ever transacted: 3 of the 51.
        --
        -- premium_holders stays in the payload because the Economy tab
        -- reads it; it is just no longer a KPI card.
        -- Paying means a LIVE Stripe event. Until 1 Oct 2026 this counted
        -- any entitlement_event, and every event on file was a test-mode
        -- checkout (livemode=false) by the owner and a beta tester, so the
        -- card said 3 while nobody had paid. Stripe sets `livemode` at the
        -- top of every event; the nested path covers a payload stored as
        -- the event object itself.
        (SELECT COUNT(*) FROM person p
          WHERE 'premium' = ANY(p.entitlements)
            AND EXISTS (SELECT 1 FROM entitlement_event e
                         WHERE e.app_user_id = p.id::text
                           AND COALESCE(e.payload->>'livemode',
                                        e.payload->'data'->'object'->>'livemode') = 'true')) AS paying_members,
        (SELECT COUNT(*) FROM skipped WHERE reported = TRUE) AS pending_reports,
        (SELECT COUNT(*) FROM referral WHERE created_at > NOW() - INTERVAL '7 days') AS referral_signups_7d
"""

# Every date bucket on this tab is a BARBADOS day, because that is where the
# dashboard is read. `CURRENT_DATE` is UTC, and after 20:00 in Barbados the
# UTC date is already tomorrow, so a series bounded by it ends a day ahead of
# the dashboard's own sense of today and puts evening activity on the wrong
# bar. The conversion belongs on both the series bounds and the per-day
# comparison; one without the other is an off-by-one that only shows near
# midnight.
#
# Durations stay in UTC. Retention windows and expiry arithmetic are lengths
# of time, not calendar days, and a timezone would be wrong there.
_BARBADOS_TODAY = "(NOW() AT TIME ZONE 'America/Barbados')::date"

Q_OVERVIEW_SIGNUPS_30D = f"""
    WITH days AS (
        SELECT generate_series(
            ({_BARBADOS_TODAY} - INTERVAL '29 days')::date,
            {_BARBADOS_TODAY},
            INTERVAL '1 day'
        )::date AS d
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM waitlist_signup
                   WHERE (created_at AT TIME ZONE 'America/Barbados')::date = days.d), 0) AS waitlist,
        COALESCE((SELECT COUNT(*) FROM beta_signup
                   WHERE (created_at AT TIME ZONE 'America/Barbados')::date = days.d), 0) AS beta,
        COALESCE((SELECT COUNT(*) FROM person
                   WHERE (sign_up_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Barbados')::date = days.d), 0) AS person
      FROM days
     ORDER BY days.d
"""

Q_OVERVIEW_REFERRAL_CTR_7D = f"""
    WITH days AS (
        SELECT generate_series(
            ({_BARBADOS_TODAY} - INTERVAL '6 days')::date,
            {_BARBADOS_TODAY},
            INTERVAL '1 day'
        )::date AS d
    )
    SELECT
        days.d::text AS day,
        COALESCE((SELECT COUNT(*) FROM referral_link_click
                   WHERE (created_at AT TIME ZONE 'America/Barbados')::date = days.d
                     AND user_agent_class != 'bot'), 0) AS clicks,
        COALESCE((SELECT COUNT(*) FROM referral
                   WHERE (created_at AT TIME ZONE 'America/Barbados')::date = days.d), 0) AS signups
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
# Only the events that START a paid relationship count here. Renewals,
# updates and cancellations are real, but folding them in would make a churn
# event look like a sale. The live event types on 2026-09-24 were
# checkout.session.completed (15), customer.subscription.created (8),
# customer.subscription.deleted (8) and customer.subscription.updated (5).
_PURCHASE_EVENTS = ('checkout.session.completed', 'customer.subscription.created')

Q_OVERVIEW_PREMIUM_30D = f"""
    WITH days AS (
        SELECT generate_series(
            ({_BARBADOS_TODAY} - INTERVAL '29 days')::date,
            {_BARBADOS_TODAY},
            INTERVAL '1 day'
        )::date AS d
    )
    SELECT
        days.d::text AS day,
        COALESCE((
            SELECT COUNT(*) FROM entitlement_event
             WHERE event_type IN {_PURCHASE_EVENTS}
               AND (received_at AT TIME ZONE 'America/Barbados')::date = days.d
        ), 0) AS adds
      FROM days
     ORDER BY days.d
"""

Q_OVERVIEW_RECENT_ACTIVITY = """
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
          FROM person ORDER BY sign_up_time DESC LIMIT 10
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
               created_at FROM admin_audit_log ORDER BY created_at DESC LIMIT 10
    ) sub_admin
    ORDER BY created_at DESC LIMIT 20
"""
