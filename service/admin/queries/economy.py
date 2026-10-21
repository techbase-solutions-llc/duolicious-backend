"""SQL for the Economy tab: token ledger, entitlements, subscriptions.

Entitlement holders and Stripe customers are members only (members.py):
on 13 Oct 2026 the tab read 60 Premium holders for 58 members, and 2 of its
3 Stripe customers were staff. The token ledger is an accounting record of
every account and stays whole."""
from service.admin.queries.days import BARBADOS_TODAY, barbados_day
from service.admin.queries.members import member_sql
from service.admin.queries.overview import _subscription_checkout, live_stripe_event

_MEMBER = member_sql('person')
_MEMBER_P = member_sql('p')

# Ledger explorer: paginated, filter by reason + email + period.
#
# The table and the KPIs above it share ONE period, `days`, where 0 means all
# time (the default). Until 13 Oct 2026 the table was silently held to the
# last 30 days while the KPIs summed every row: the footer read 44 entries
# under totals built from 127, and filtering on "purchase" found nothing
# although 5 purchases existed, all older than the window.
_IN_PERIOD = "(%(days)s = 0 OR tl.created_at > NOW() - make_interval(days => %(days)s))"

Q_LEDGER = f"""
    SELECT
        tl.created_at,
        tl.delta,
        tl.reason,
        tl.metadata,
        p.email,
        p.uuid::text AS person_uuid
      FROM token_ledger tl
      LEFT JOIN person p ON p.uuid = tl.person_id
     WHERE (%(reason)s = '' OR tl.reason = %(reason)s)
       AND (%(email)s = '' OR p.email ILIKE %(email_like)s)
       AND {_IN_PERIOD}
     ORDER BY tl.created_at DESC
     LIMIT %(limit)s OFFSET %(offset)s
"""

Q_LEDGER_COUNT = f"""
    SELECT COUNT(*) AS total
      FROM token_ledger tl
      LEFT JOIN person p ON p.uuid = tl.person_id
     WHERE (%(reason)s = '' OR tl.reason = %(reason)s)
       AND (%(email)s = '' OR p.email ILIKE %(email_like)s)
       AND {_IN_PERIOD}
"""

# Credits and debits cover the table's period. Circulation is the balance of
# every token ever issued, a stock rather than a flow, so it is all time
# whatever the period. "Today net" is the Barbados day (days.py).
Q_LEDGER_KPIS = f"""
    SELECT
        (SELECT COALESCE(SUM(delta), 0)::int FROM token_ledger tl
          WHERE delta > 0 AND {_IN_PERIOD}) AS total_credits,
        (SELECT COALESCE(SUM(delta), 0)::int FROM token_ledger tl
          WHERE delta < 0 AND {_IN_PERIOD}) AS total_debits,
        (SELECT COALESCE(SUM(delta), 0)::int FROM token_ledger) AS circulation,
        (SELECT COALESCE(SUM(delta), 0)::int FROM token_ledger
          WHERE {barbados_day('created_at')} = {BARBADOS_TODAY}) AS today
"""

def _ever_subscribed(alias: str) -> str:
    """The person aliased `alias` has a LIVE Stripe subscription event on
    file: the checkout, a paid renewal, or an update or cancellation of the
    subscription (service/checkout). Test-mode events are not sales
    (overview.live_stripe_event)."""
    return f"""EXISTS (
        SELECT 1 FROM entitlement_event e
         WHERE e.app_user_id = {alias}.id::text
           AND {live_stripe_event('e')}
           AND (({_subscription_checkout('e')})
                OR e.event_type IN ('invoice.payment_succeeded',
                                    'customer.subscription.updated',
                                    'customer.subscription.deleted')))"""


# The early-member Premium every new member gets at sign-up
# (entitlements.grant_founding_member_if_eligible), known by its starter
# stipend, or the founding_member entitlement itself.
def _founding(alias: str) -> str:
    return f"""('founding_member' = ANY(COALESCE({alias}.entitlements, ARRAY[]::text[]))
        OR EXISTS (SELECT 1 FROM token_ledger fl
                    WHERE fl.person_id = {alias}.uuid
                      AND fl.reason = 'subscription_stipend'
                      AND fl.metadata->>'source' = 'founding_member_starter'))"""


# Entitlement holders.
#
# time_left is whole SECONDS, negative once lapsed, NULL with no expiry. It
# used to be the raw interval, which psycopg returns as a Python timedelta
# and Flask's JSON provider cannot encode, so every load with a dated holder
# (all 60 in production) answered 500 until 13 Oct 2026.
Q_ENTITLEMENT_HOLDERS = f"""
    SELECT
        p.email,
        p.uuid::text AS person_uuid,
        p.subscription_expires_at,
        EXTRACT(EPOCH FROM (p.subscription_expires_at - NOW()))::bigint AS time_left,
        COALESCE(p.entitlements, ARRAY[]::text[]) AS entitlements,
        -- The design's Founding toggle and Source column (TEC-1845 admin
        -- audit). Source is where this entitlement most likely came from:
        -- a live Stripe subscription (Premium only), a grant from the
        -- drawer, the early-member grant at sign-up, else unknown.
        {_founding('p')} AS founding,
        CASE
            WHEN %(name)s = 'premium' AND {_ever_subscribed('p')} THEN 'stripe'
            WHEN EXISTS (SELECT 1 FROM admin_audit_log a
                          WHERE a.action = 'grant_entitlement'
                            AND a.target_uuid = p.uuid
                            AND a.metadata->>'name' = %(name)s) THEN 'admin'
            WHEN %(name)s = 'premium' AND {_founding('p')} THEN 'signup'
            ELSE 'unknown'
        END AS source
      FROM person p
     WHERE {_MEMBER_P}
       AND %(name)s = ANY(p.entitlements)
       -- Expiring means not yet lapsed: between expiry and the nightly
       -- strip a lapsed holder still holds it (TEC-1845 admin audit, Minor
       -- 32). The unfiltered list (0) still shows them.
       AND (%(expires_within_days)s = 0
            OR (p.subscription_expires_at > NOW()
                AND p.subscription_expires_at < NOW() + (%(expires_within_days)s || ' days')::INTERVAL))
     ORDER BY p.subscription_expires_at NULLS LAST
     LIMIT 200
"""

Q_ENTITLEMENT_KPIS = f"""
    SELECT
        COUNT(*) AS holders,
        COUNT(*) FILTER (WHERE subscription_expires_at > NOW()
                           AND subscription_expires_at < NOW() + INTERVAL '7 days') AS expiring_7d,
        COUNT(*) FILTER (WHERE subscription_expires_at > NOW()
                           AND subscription_expires_at < NOW() + INTERVAL '30 days') AS expiring_30d
      FROM person
     WHERE {_MEMBER}
       AND %(name)s = ANY(entitlements)
"""

# Subscriptions — keyed on person.stripe_customer_id + subscription_expires_at.
# No separate Stripe subs table exists in this codebase, so we infer state from person.
#
# Expired (TEC-1845 admin audit): expire_stale nulls subscription_expires_at
# once it passes, so `expires < NOW()` could only catch a row in the gap
# before the nightly cron, and a lapsed subscriber read 'never'. A member
# with a live subscription event on file who is not active now is expired;
# the old rule is kept alongside it for that gap.
_EXPIRED = (f"((person.subscription_expires_at < NOW() AND person.stripe_customer_id IS NOT NULL)"
            f" OR ({_ever_subscribed('person')}"
            f" AND (person.subscription_expires_at IS NULL OR person.subscription_expires_at <= NOW())))")

Q_SUBSCRIPTIONS_KPIS = f"""
    SELECT
        COUNT(*) FILTER (WHERE stripe_customer_id IS NOT NULL) AS total_stripe_customers,
        COUNT(*) FILTER (WHERE subscription_expires_at > NOW()) AS active,
        COUNT(*) FILTER (WHERE {_EXPIRED}) AS expired
      FROM person
     WHERE {_MEMBER}
"""

Q_SUBSCRIPTIONS_ROWS = f"""
    SELECT
        p.email,
        p.uuid::text AS person_uuid,
        p.stripe_customer_id,
        p.subscription_expires_at,
        COALESCE(p.entitlements, ARRAY[]::text[]) AS entitlements,
        {_ever_subscribed('p')} AS ever_subscribed,
        CASE
            WHEN p.subscription_expires_at > NOW() THEN 'active'
            WHEN p.subscription_expires_at IS NOT NULL THEN 'expired'
            WHEN {_ever_subscribed('p')} THEN 'expired'
            ELSE 'never'
        END AS status
      FROM person p
     WHERE {_MEMBER_P}
       AND (p.stripe_customer_id IS NOT NULL OR p.subscription_expires_at IS NOT NULL)
     ORDER BY p.subscription_expires_at DESC NULLS LAST
     LIMIT 200
"""
