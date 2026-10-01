"""The Overview tab's numbers, against seeded rows rather than against the
SQL's text.

Signups count PEOPLE. `waitlist_signup` and `beta_signup` were the pre-launch
funnel and nobody has used them since; on 2026-09-24 they held 0 rows for the
previous week while 5 real members had joined, and the owner caught the card
reading 0 on a day they had personally received a signup. The chart directly
beneath the card already counted `person` correctly, so two numbers from one
route disagreed on one screen.

Every date bucket is a Barbados day. The dashboard is read in Barbados, and
under `CURRENT_DATE` a member who joins after 20:00 local lands on the next
day's number.
"""
from database import api_tx
from service.admin.queries import (
    Q_OVERVIEW_KPIS, Q_OVERVIEW_PREMIUM_30D, Q_OVERVIEW_SIGNUPS_30D,
    Q_OVERVIEW_REFERRAL_CTR_7D)


def _kpis() -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_OVERVIEW_KPIS).fetchone())


def _series(sql: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(sql).fetchall()]


def _set_signup(person_id: int, expr: str) -> None:
    """Move a person's sign_up_time to a Barbados wall-clock moment."""
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET sign_up_time = {expr} WHERE id = %(i)s",
                   dict(i=person_id))


# A Barbados wall-clock time today, converted back to an absolute instant.
_TODAY_AT = ("((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '{t}')"
             " AT TIME ZONE 'America/Barbados'")
_YESTERDAY_AT = ("((NOW() AT TIME ZONE 'America/Barbados')::date - 1 + TIME '{t}')"
                 " AT TIME ZONE 'America/Barbados'")


def test_a_person_who_signed_up_today_is_counted_today(make_person):
    before = _kpis()['signups_today']
    p = make_person(name='SignupToday')
    _set_signup(p['id'], _TODAY_AT.format(t='09:00'))
    assert _kpis()['signups_today'] == before + 1


def test_yesterday_is_a_real_count_not_a_constant(make_person):
    """The card printed the literal string "vs 0 yesterday" every day,
    because the route returned no yesterday figure to compare against."""
    before = _kpis()['signups_yesterday']
    p = make_person(name='SignupYesterday')
    _set_signup(p['id'], _YESTERDAY_AT.format(t='12:00'))
    assert _kpis()['signups_yesterday'] == before + 1


def test_yesterdays_signup_is_not_also_counted_as_today(make_person):
    """Negative control: the two buckets must not overlap."""
    before = _kpis()['signups_today']
    p = make_person(name='NotToday')
    _set_signup(p['id'], _YESTERDAY_AT.format(t='12:00'))
    assert _kpis()['signups_today'] == before


def test_the_day_boundary_is_barbados_not_utc(make_person):
    """22:00 in Barbados is 02:00 the next day in UTC. Under CURRENT_DATE
    that member lands on tomorrow's count, on a dashboard read in Barbados.

    This is the test that fails if anyone reverts a bucket to CURRENT_DATE,
    and it is worth reading twice: it passes trivially unless the conversion
    is present on BOTH sides of the comparison."""
    before = _kpis()['signups_today']
    p = make_person(name='LateEvening')
    _set_signup(p['id'], _TODAY_AT.format(t='22:00'))
    assert _kpis()['signups_today'] == before + 1


def test_the_signups_chart_and_the_signups_card_agree(make_person):
    """The defect the owner found by hand: the card said 0 while the chart
    directly below it would have drawn the member. They read the same source
    now, so a person added must move both."""
    before_card = _kpis()['signups_today']
    before_chart = _series(Q_OVERVIEW_SIGNUPS_30D)[-1]['person']
    p = make_person(name='CardAndChart')
    _set_signup(p['id'], _TODAY_AT.format(t='09:00'))
    assert _kpis()['signups_today'] == before_card + 1
    assert _series(Q_OVERVIEW_SIGNUPS_30D)[-1]['person'] == before_chart + 1


def test_a_late_evening_signup_lands_on_todays_bar_in_the_chart(make_person):
    """Same boundary rule, applied to the 30 day series rather than the KPI.
    Missing the conversion on either side of a series comparison gives an
    off-by-one that only shows near midnight."""
    before = _series(Q_OVERVIEW_SIGNUPS_30D)[-1]['person']
    p = make_person(name='LateChart')
    _set_signup(p['id'], _TODAY_AT.format(t='22:00'))
    assert _series(Q_OVERVIEW_SIGNUPS_30D)[-1]['person'] == before + 1


def test_the_series_end_on_the_barbados_day_not_the_utc_one():
    """After 20:00 in Barbados the UTC date is already tomorrow, so a series
    bounded by CURRENT_DATE would end a day ahead of the dashboard's own
    sense of today."""
    with api_tx('read committed') as tx:
        today = tx.execute(
            "SELECT (NOW() AT TIME ZONE 'America/Barbados')::date::text AS d"
        ).fetchone()['d']
    for sql in (Q_OVERVIEW_SIGNUPS_30D, Q_OVERVIEW_REFERRAL_CTR_7D,
                Q_OVERVIEW_PREMIUM_30D):
        assert _series(sql)[-1]['day'] == today


# ---------------------------------------------------------------------------
# Premium. Two defects, both about the same thing being reported wrongly.
# ---------------------------------------------------------------------------

def test_the_premium_series_reads_the_entitlement_ledger():
    """A cheap standing guard. The real test is the one below; this one
    exists so the reason is written down next to the assertion.

    entitlement_event is the append-only ledger migration 0005 created for
    exactly this. admin_audit_log has never carried the action the old query
    filtered on, so the chart was structurally incapable of a non-zero bar.
    """
    assert 'entitlement_event' in Q_OVERVIEW_PREMIUM_30D
    assert 'grant_entitlement' not in Q_OVERVIEW_PREMIUM_30D


def test_a_purchase_today_appears_on_todays_bar(make_person):
    """The weight-bearing one. A query can name the right table and still
    bucket wrongly, which a grep of the SQL would never catch."""
    import uuid as _uuid
    p = make_person(name='Buyer')
    before = _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds']
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event
                 (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s, '{}'::jsonb,
                       ((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '09:00')
                       AT TIME ZONE 'America/Barbados')""",
            dict(eid=f'test-{_uuid.uuid4()}', uid=str(p['id'])))
    assert _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds'] == before + 1


def test_a_cancellation_is_not_counted_as_a_sale(make_person):
    """Negative control. Folding every event type in would make churn look
    like growth, which is the opposite of what this chart is for."""
    import uuid as _uuid
    p = make_person(name='Churner')
    before = _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds']
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event
                 (event_id, event_type, app_user_id, payload, received_at)
               VALUES (%(eid)s, 'customer.subscription.deleted', %(uid)s, '{}'::jsonb, NOW())""",
            dict(eid=f'test-{_uuid.uuid4()}', uid=str(p['id'])))
    assert _series(Q_OVERVIEW_PREMIUM_30D)[-1]['adds'] == before


def test_paying_members_counts_only_people_who_transacted(make_person):
    """"Premium holders" restated "Total persons" two cards away: every
    person in the database holds premium. Paying members is the figure with
    information in it."""
    import uuid as _uuid
    p = make_person(name='PayingOne')
    with api_tx() as tx:
        tx.execute("UPDATE person SET entitlements = ARRAY['premium']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    before = _kpis()
    # Holding premium alone must NOT make someone a paying member.
    assert before['paying_members'] < before['premium_holders'] or before['premium_holders'] == 0

    # A Stripe TEST-mode checkout is not a payment. Until 1 Oct 2026 this
    # counted it, and the card said 3 paying members while nobody had paid.
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event
                 (event_id, event_type, app_user_id, payload)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s, '{"livemode": false}'::jsonb)""",
            dict(eid=f'test-{_uuid.uuid4()}', uid=str(p['id'])))
    assert _kpis()['paying_members'] == before['paying_members'], 'a test-mode checkout counted as paying'

    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event
                 (event_id, event_type, app_user_id, payload)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s, '{"livemode": true}'::jsonb)""",
            dict(eid=f'test-{_uuid.uuid4()}', uid=str(p['id'])))
    assert _kpis()['paying_members'] == before['paying_members'] + 1


def test_a_live_event_stored_as_the_object_itself_still_counts(make_person):
    """Some payloads keep the Stripe event whole, some keep only its data
    object; `livemode` is read from either place."""
    import uuid as _uuid
    p = make_person(name='PayingNested')
    with api_tx() as tx:
        tx.execute("UPDATE person SET entitlements = ARRAY['premium']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    before = _kpis()['paying_members']
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO entitlement_event
                 (event_id, event_type, app_user_id, payload)
               VALUES (%(eid)s, 'customer.subscription.created', %(uid)s,
                       '{"data": {"object": {"livemode": true}}}'::jsonb)""",
            dict(eid=f'test-{_uuid.uuid4()}', uid=str(p['id'])))
    assert _kpis()['paying_members'] == before + 1


def test_the_naive_column_really_does_need_both_conversions(make_person):
    """`person.sign_up_time` is `timestamp WITHOUT time zone`, alone among
    the timestamps this tab reads. On a naive column,
    `AT TIME ZONE 'America/Barbados'` READS the value as Barbados local,
    which is backwards: the column stores UTC.

    This runs both forms against one 22:00 row and asserts they disagree, so
    nobody can "simplify" the double conversion away and watch the tests
    still pass. The wrong form is off in the direction that looks plausible,
    which is why it needs a test rather than a comment.
    """
    p = make_person(name='ConversionTrap')
    _set_signup(p['id'], _TODAY_AT.format(t='22:00'))
    right = ("(sign_up_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Barbados')::date")
    wrong = ("(sign_up_time AT TIME ZONE 'America/Barbados')::date")
    with api_tx('read committed') as tx:
        row = tx.execute(
            f"SELECT {right} AS good, {wrong} AS bad FROM person WHERE id = %(i)s",
            dict(i=p['id'])).fetchone()
        today = tx.execute(
            "SELECT (NOW() AT TIME ZONE 'America/Barbados')::date AS d").fetchone()['d']
    assert row['good'] == today
    assert row['bad'] != row['good']


# ---------------------------------------------------------------------------
# The activity feed. Its only two signup sources were the dead funnel, so a
# real member joining produced no line.
# ---------------------------------------------------------------------------

def _activity() -> list[dict]:
    from service.admin.queries import Q_OVERVIEW_RECENT_ACTIVITY
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(Q_OVERVIEW_RECENT_ACTIVITY).fetchall()]


def test_a_real_member_joining_appears_in_the_feed(make_person):
    p = make_person(name='FeedMember')
    _set_signup(p['id'], _TODAY_AT.format(t='09:00'))
    rows = _activity()
    mine = [r for r in rows if r['kind'] == 'signup_member' and r['subject'] == 'FeedMember']
    assert mine, f"no signup_member row for the new person; kinds seen: {sorted({r['kind'] for r in rows})}"
    assert mine[0]['object'] == str(p['uuid']), 'the uuid must ride along so the row can open the drawer'


def test_the_feed_never_prints_a_members_email(make_person):
    """The other branches carry emails because they are pre-account records.
    A person row is an account, and this feed is a glanceable list that may
    be open in front of other people."""
    p = make_person(name='FeedPrivacy')
    _set_signup(p['id'], _TODAY_AT.format(t='09:00'))
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=p['id'])).fetchone()['email']
    for row in _activity():
        assert row['subject'] != email
        assert row['object'] != email
