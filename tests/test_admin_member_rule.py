"""A staff account is not a member.

The 13 Oct 2026 health review found the three admin-role accounts (ids 18,
23 and 126) counted as members on Overview, System, Economy, Growth and
Moderation: Overview said 61 persons and Growth 60 while there were 58
members, and Growth's Spotlight opt-ins read 2 where members had 1. One rule
now decides who is a member wherever the dashboard counts or lists them
(service/admin/queries/members.py), and this file holds every admin
endpoint to it.

Each test reads every member figure, adds a staff account that does
everything a member can be counted for (joins today, is online, holds and
pays for Premium, has a Stripe customer, opts into Spotlight, has an
approved photo, came through the beta, likes, matches and messages a
member), reads again and expects no change. Then it takes the admin role
away from the same account and expects the figures to move, so the first
half cannot pass merely because the fixture was invisible to the queries.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid

import pytest

from database import api_tx


def _bearer(person_id: int) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=person_id)).fetchone()['email']
        tx.execute(
            """
            INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
            VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')
            """,
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id),
        )
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def admin_headers(make_person):
    p = make_person(name='MemberRuleAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return _bearer(p['id'])


_MAM_SEQ = [0]


def _message(sender_id: int, recipient_id: int) -> None:
    """Both archive copies, as the chat service writes them (see
    tests/test_admin_engagement.py). No content: the body is empty."""
    _MAM_SEQ[0] += 1
    with api_tx() as tx:
        uuids = {r['id']: str(r['uuid']) for r in tx.execute(
            "SELECT id, uuid FROM person WHERE id IN (%(a)s, %(b)s)",
            dict(a=sender_id, b=recipient_id)).fetchall()}
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(s)s AS id",
            dict(s=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'O', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id, pid=sender_id, jid=uuids[recipient_id]))
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'I', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id + 1, pid=recipient_id, jid=uuids[sender_id]))


def _get(client, headers, path) -> dict:
    r = client.get(path, headers=headers)
    assert r.status_code == 200, f'{path} answered {r.status_code}'
    return r.get_json()


def _gender_row(stats: dict, gender: str) -> dict:
    return next((r for r in stats['members_by_gender'] if r['gender'] == gender), {})


def _figures(client, headers) -> dict:
    """Every member figure the admin shows, keyed by where it is read."""
    ov = _get(client, headers, '/admin/overview')
    sysh = _get(client, headers, '/admin/system/health')['health']
    ent = _get(client, headers, '/admin/economy/entitlements?name=premium')['kpis']
    subs = _get(client, headers, '/admin/economy/subscriptions')['kpis']
    beta = _get(client, headers, '/admin/cohorts/beta')
    wl = _get(client, headers, '/admin/cohorts/waitlist')
    mod = _get(client, headers, '/admin/moderation/photos?state=approved')['kpis']
    eng = _get(client, headers, '/admin/engagement')['kpis']
    gr = _get(client, headers, '/admin/growth/stats')
    man = _gender_row(gr, 'Man')

    out = {}
    for k in ('signups_today', 'active_24h', 'person_total', 'premium_holders', 'paying_members'):
        out[f'overview.{k}'] = ov['kpis'][k]
    out['overview.signups_30d.person'] = sum(d['person'] for d in ov['signups_30d'])
    out['overview.members_30d.last'] = ov['members_30d'][-1]['total'] if ov['members_30d'] else 0
    for k in ('signups_today', 'signups_7d', 'signups_30d', 'dau', 'wau', 'mau'):
        out[f'system.{k}'] = sysh[k]
    for k in ('holders', 'expiring_7d', 'expiring_30d'):
        out[f'economy.entitlements.{k}'] = ent[k]
    for k in ('total_stripe_customers', 'active', 'expired'):
        out[f'economy.subscriptions.{k}'] = subs[k]
    out['cohorts.beta.completed_onboarding'] = beta['kpis']['completed_onboarding']
    out['cohorts.funnel.started_onboarding'] = beta['funnel']['started_onboarding']
    out['cohorts.funnel.completed_onboarding'] = beta['funnel']['completed_onboarding']
    out['cohorts.velocity.person'] = sum(d['person'] for d in wl['velocity_30d'])
    for k in ('approved', 'rejected'):
        out[f'moderation.{k}'] = mod[k]
    for k in ('likes_total', 'likes_7d', 'matches_total', 'conversations_total',
              'conversations_answered', 'messages_total', 'messages_7d'):
        out[f'engagement.{k}'] = eng[k]
    for k in ('members', 'new_7d', 'new_30d', 'acted_14d', 'with_photo', 'premium', 'opted_in'):
        out[f'growth.man.{k}'] = man.get(k, 0)
    for k in ('matches', 'matches_30d', 'likes_total', 'likes_7d', 'msgs_7d', 'msgs_30d', 'opted_in'):
        out[f'growth.{k}'] = gr[k]
    return out


def _joined(client, headers) -> set[str]:
    """Who the Overview's activity feed says joined. Compared by uuid, not
    as a list: the feed is the newest 20 rows across every kind, so any new
    row of another kind can push an older join off the end."""
    feed = _get(client, headers, '/admin/overview')['recent_activity']
    return {r['object'] for r in feed if r['kind'] == 'signup_member'}


def _staff_who_does_everything(make_person, member_id: int) -> dict:
    """A man with the admin role, active in every way a member is counted."""
    email = f'member-rule-staff-{uuid.uuid4().hex[:10]}@example.com'
    # The beta row exists before the person does, so it cannot move the
    # beta figures until a person with that address appears.
    with api_tx() as tx:
        tx.execute("INSERT INTO beta_signup (email) VALUES (%(e)s)", dict(e=email))
    staff = make_person(name='MemberRuleStaff', gender='Man', email=email)
    with api_tx() as tx:
        tx.execute(
            """UPDATE person
                  SET roles = ARRAY['admin']::TEXT[],
                      entitlements = ARRAY['premium']::TEXT[],
                      subscription_expires_at = NOW() + interval '5 days',
                      stripe_customer_id = 'cus_member_rule_test',
                      spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW()
                WHERE id = %(i)s""",
            dict(i=staff['id']))
        tx.execute(
            """INSERT INTO photo (person_id, position, uuid, blurhash, hash, moderation_status)
               VALUES (%(p)s, 1, %(u)s, '', %(u)s, 'approved')""",
            dict(p=staff['id'], u=f'member-rule-{uuid.uuid4().hex}'))
        tx.execute(
            """INSERT INTO entitlement_event (event_id, event_type, app_user_id, payload)
               VALUES (%(eid)s, 'checkout.session.completed', %(uid)s, '{"livemode": true}'::jsonb)""",
            dict(eid=f'test-member-rule-{uuid.uuid4()}', uid=str(staff['id'])))
        for a, b in ((staff['id'], member_id), (member_id, staff['id'])):
            tx.execute("INSERT INTO liked (liker_id, liked_id, created_at) VALUES (%(a)s, %(b)s, NOW())",
                       dict(a=a, b=b))
        tx.execute(
            "INSERT INTO ahavah_match (user_a_id, user_b_id) VALUES (LEAST(%(a)s, %(b)s), GREATEST(%(a)s, %(b)s))",
            dict(a=staff['id'], b=member_id))
    _message(staff['id'], member_id)
    _message(member_id, staff['id'])
    return dict(staff, email=email)


@pytest.fixture
def cleanup_beta():
    emails: list[str] = []
    yield emails
    with api_tx() as tx:
        for e in emails:
            tx.execute("DELETE FROM beta_signup WHERE email = %(e)s", dict(e=e))


def test_a_staff_account_changes_no_member_figure(client, admin_headers, make_person, cleanup_beta):
    member = make_person(name='MemberRuleMember', gender='Woman')
    before = _figures(client, admin_headers)
    staff = _staff_who_does_everything(make_person, member['id'])
    cleanup_beta.append(staff['email'])

    after = _figures(client, admin_headers)
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert moved == {}, f'a staff account moved member figures: {moved}'
    assert staff['uuid'] not in _joined(client, admin_headers),         'a staff account joining is not a member joining'

    # Negative control: the same account without the role IS a member, and
    # the figures that describe it must now move.
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = '{}'::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    as_member = _figures(client, admin_headers)
    must_move = (
        'overview.signups_today', 'overview.active_24h', 'overview.person_total',
        'overview.premium_holders', 'overview.paying_members', 'overview.signups_30d.person',
        'overview.members_30d.last',
        'system.signups_today', 'system.dau', 'system.mau',
        'economy.entitlements.holders', 'economy.entitlements.expiring_7d',
        'economy.subscriptions.total_stripe_customers', 'economy.subscriptions.active',
        'cohorts.beta.completed_onboarding', 'cohorts.funnel.started_onboarding',
        'cohorts.funnel.completed_onboarding',
        'cohorts.velocity.person',
        'moderation.approved',
        'engagement.likes_total', 'engagement.matches_total', 'engagement.conversations_total',
        'engagement.conversations_answered', 'engagement.messages_total',
        'growth.man.members', 'growth.man.new_7d', 'growth.man.acted_14d',
        'growth.man.with_photo', 'growth.man.premium', 'growth.man.opted_in',
        'growth.matches', 'growth.likes_total', 'growth.msgs_7d', 'growth.msgs_30d',
        'growth.opted_in',
    )
    still = [k for k in must_move if as_member[k] == after[k]]
    assert still == [], f'these figures did not see the account once it was a member: {still}'
    assert staff['uuid'] in _joined(client, admin_headers)


def test_the_staff_account_is_not_listed_as_a_member(client, admin_headers, make_person, cleanup_beta):
    """Lists, not only counts: the Economy tables name members, and a staff
    row there reads as a customer."""
    member = make_person(name='MemberRuleMember2', gender='Woman')
    staff = _staff_who_does_everything(make_person, member['id'])
    cleanup_beta.append(staff['email'])

    subs = _get(client, admin_headers, '/admin/economy/subscriptions')['rows']
    assert staff['uuid'] not in {r['person_uuid'] for r in subs}
    ent = _get(client, admin_headers, '/admin/economy/entitlements?name=premium&expires_within_days=6')
    assert staff['uuid'] not in {r['person_uuid'] for r in ent['holders']}

    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = '{}'::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    subs = _get(client, admin_headers, '/admin/economy/subscriptions')['rows']
    assert staff['uuid'] in {r['person_uuid'] for r in subs}
    ent = _get(client, admin_headers, '/admin/economy/entitlements?name=premium&expires_within_days=6')
    assert staff['uuid'] in {r['person_uuid'] for r in ent['holders']}


def test_the_rule_is_one_fragment():
    """One definition. A copy pasted into one tab is how the tabs came to
    disagree about how many members there are."""
    from service.admin.queries.members import MEMBER_SQL, member_sql
    assert member_sql('p') == MEMBER_SQL
    assert member_sql('x') == "'admin' <> ALL(COALESCE(x.roles, ARRAY[]::text[]))"
