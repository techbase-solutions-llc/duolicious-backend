"""python -m emails.send_community_weekly [--send] [--campaign-id ID]"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.community_weekly import community_weekly_html, SUBJECT, FROM_ADDR
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.runner import audit_send, run_campaign
from service.campaigns.switches import enabled
from service.campaigns.weekid import week_campaign_id
from service.admin.queries.members import member_sql
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded, count_newcomers_since
from service.unsubscribe import make_url as _unsub_url

UNSUB_SCOPE = 'community'

# The weekly email runs weekly, so a 7-day cap would race its own cadence:
# a run that starts a few hours "late" would find every member inside the
# window and skip the whole list. 6 days leaves the slack.
CAP_DAYS = 6

# Same suppression + scope-unsubscribe filters run_campaign() applies
# per-row (service/campaigns/runner.py), baked in here too so
# recipient_count() never overstates what a real
# run would send.
_Q_RECIPIENTS = f"""
    SELECT p.id AS person_id, p.email, p.name FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
     ORDER BY p.id
"""
# What members read: who joined this week, by first name and country, and how
# many members there are. Members only (service/admin/queries/members.py), so
# a staff account is never introduced to the community as a new member, as
# admin account 126 would have been on 2 Oct (health review, 13 Oct 2026,
# findings 2 and 4). Who RECEIVES this email is the recipient query above,
# which still includes staff until the owner decides otherwise.
_Q_NEW = f"""
    SELECT split_part(name, ' ', 1) AS first_name, country FROM person
     WHERE activated AND sign_up_time > NOW() - interval '7 days' AND lower(email) <> ALL(%(ex)s)
       AND {member_sql('person')}
     ORDER BY sign_up_time DESC
"""
_Q_TOTAL = f"""
    SELECT count(*) AS n FROM person
     WHERE activated AND lower(email) <> ALL(%(ex)s) AND {member_sql('person')}
"""
_Q_RECIPIENT_COUNT = f"""
    SELECT count(*) AS n FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
"""
# The most recently published member_of_week facebook row, within the last 7
# days. Facebook only (not instagram): the two platform rows share the same
# subject and caption, and the curated post the email links out to is the
# facebook one (post_url below).
#
# The three extra conditions are consent and correctness, not tidiness. A row
# stays 'published' forever, so without them the email would keep re-featuring
# a member for a week after they opted out, or after a removal task was filed
# to take the post down; and `post_url` is built from external_post_id, so a
# published row that never recorded one would link to facebook.com/None.
_Q_SPOTLIGHT = """
    SELECT split_part(p.name, ' ', 1) AS first_name,
           date_part('year', age(p.date_of_birth))::int AS age,
           p.country,
           q.image_url,
           q.external_post_id
      FROM publishing_queue q
      JOIN person p ON p.id = q.subject_person_id
     WHERE q.kind = 'member_of_week' AND q.platform = 'facebook' AND q.status = 'published'
       AND q.updated_at > NOW() - interval '7 days'
       AND p.spotlight_opt_in
       AND p.activated AND p.deletion_requested_at IS NULL
       AND q.external_post_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM spotlight_removal_task t WHERE t.queue_id = q.id)
     ORDER BY q.updated_at DESC
     LIMIT 1
"""

def _spotlight_from_row(row) -> dict:
    return dict(first_name=row['first_name'], age=row['age'], country=row['country'],
                image_url=row['image_url'],
                post_url=f"https://www.facebook.com/{row['external_post_id']}")

def _week_context() -> dict:
    with api_tx('read committed') as tx:
        spotlight_row = tx.execute(_Q_SPOTLIGHT).fetchone()
        return dict(new_members=[dict(r) for r in tx.execute(_Q_NEW, dict(ex=_excluded())).fetchall()],
                    total=int(tx.execute(_Q_TOTAL, dict(ex=_excluded())).fetchone()['n']),
                    spotlight=_spotlight_from_row(spotlight_row) if spotlight_row else None)

def recipients() -> list[dict]:
    """Each row carries the week context this run renders. It is computed
    once per call and travelled on the row rather than parked in a module
    global: two runs (or a run and a preview) must never see each other's
    numbers, and a process that lives for weeks must never serve a stale
    week."""
    week = _week_context()
    with api_tx('read committed') as tx:
        return [dict(r, week=week) for r in tx.execute(_Q_RECIPIENTS, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall()]

def recipient_count() -> int:
    """How many rows recipients() would return, without materialising them or
    computing the week context. Opens its own transaction, so never call it
    while holding one (the api connection lock is not reentrant)."""
    with api_tx('read committed') as tx:
        return int(tx.execute(_Q_RECIPIENT_COUNT, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchone()['n'])

# The reader's own counts for the personal line (findings 60 and 76), held
# behind AHAVAH_E2_PERSONAL_ENABLED. Counts only: likes waiting by the rules
# of the Liked you tab (service/decisions Q_LIST_INCOMING_LIKES), unread
# conversations by the inbox's counters (never the messages), and the
# member's invite code.
_Q_PERSONAL = """
    SELECT
      (SELECT count(*) FROM liked l
         JOIN person liker ON liker.id = l.liker_id AND liker.activated
        WHERE l.liked_id = p.id
          AND NOT EXISTS (SELECT 1 FROM liked rev WHERE rev.liker_id = p.id AND rev.liked_id = l.liker_id)
          AND NOT is_blocked_pair(p.id, l.liker_id)
          AND NOT EXISTS (SELECT 1 FROM ahavah_match m
                           WHERE m.user_a_id = LEAST(p.id, l.liker_id)
                             AND m.user_b_id = GREATEST(p.id, l.liker_id))) AS likes,
      (SELECT count(*) FROM inbox i
         JOIN person s ON s.uuid = uuid_or_null(split_part(i.remote_bare_jid, '@', 1))
        WHERE i.luser = p.uuid::text AND i.unread_count > 0
          AND s.activated AND NOT is_blocked_pair(p.id, s.id)) AS unread,
      p.referral_code
      FROM person p WHERE p.id = %(pid)s
"""


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def invite_target(code: str) -> str:
    """Where the invite button leads: the share page, as the referral email's
    button does. Never /i/<code>, which is the friend's way in: opened by
    the member it sets their own referral cookie, sends them to sign-up and
    counts a click against their own code (review of Wave 3, 14 Oct 2026)."""
    return f"{WEB_BASE_URL}/share/{code}"


def personal_parts(likes: int, unread: int, fits: int) -> dict:
    """The one strongest reason, in this order: likes waiting, unread
    messages, newcomers who fit. Returns subject, line, cta_label, target."""
    if likes:
        return dict(
            subject=_plural(likes, 'This week on Ahavah: 1 like is waiting for you',
                            'This week on Ahavah: {n} likes are waiting for you'),
            line=_plural(likes, '1 person has liked you and is waiting for an answer.',
                         '{n} people have liked you and are waiting for an answer.'),
            cta_label='See who likes you', target=f"{WEB_BASE_URL}/matches?tab=likes")
    if unread:
        return dict(subject=SUBJECT,
                    line=_plural(unread, 'You have an unread message from 1 person.',
                                 'You have unread messages from {n} people.'),
                    cta_label='Read your messages', target=f"{WEB_BASE_URL}/inbox")
    line = None
    if fits:
        line = _plural(fits, '1 new person who fits what you are looking for joined this week.',
                       '{n} new people who fit what you are looking for joined this week.')
    return dict(subject=SUBJECT, line=line, cta_label='Open Discover', target=f"{WEB_BASE_URL}/discover")


def _build_personal(row: dict) -> tuple[str, str]:
    week = row['week']
    dry = row.get('dry_run', False)
    pid = row['person_id']
    with api_tx() as tx:
        r = tx.execute(_Q_PERSONAL, dict(pid=pid)).fetchone()
        fits = count_newcomers_since(tx, pid, datetime.now(timezone.utc) - timedelta(days=7))
        parts = personal_parts(int(r['likes']), int(r['unread']), int(fits))
        cta = make_campaign_link(tx, 'e2', parts['target'], pid, dry_run=dry)
        invite = (make_campaign_link(tx, 'e2', invite_target(r['referral_code']), pid, dry_run=dry)
                  if r['referral_code'] else None)
    return parts['subject'], community_weekly_html(
        week['new_members'], week['total'], week['spotlight'], cta,
        _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
        personal_line=parts['line'], invite_url=invite, cta_label=parts['cta_label'])


def build_for(row: dict) -> tuple[str, str]:
    week = row['week']
    if enabled('e2_personal') and row.get('person_id'):
        return _build_personal(row)
    with api_tx() as tx:
        cta = make_campaign_link(tx, 'e2', f"{WEB_BASE_URL}/discover", row['person_id'] or None,
                                 dry_run=row.get('dry_run', False))
    return SUBJECT, community_weekly_html(week['new_members'], week['total'], week['spotlight'], cta,
                                          _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL))


def preview_personal(to: str) -> tuple[str, str]:
    """The proof of the personal E2: 2 likes waiting, sample newcomers, the
    invite button built by `invite_target` from a sample code, as the real
    send builds it. Reads nothing per member and stores nothing."""
    parts = personal_parts(2, 0, 0)
    return parts['subject'], community_weekly_html(
        [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB')], 58, None,
        parts['target'], _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        personal_line=parts['line'], invite_url=invite_target('YOURCODE'), cta_label=parts['cta_label'])

def preview_row(to: str) -> dict:
    return dict(person_id=0, email=to, name='Preview', week=_week_context())

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true'); ap.add_argument('--campaign-id', default=None)
    a = ap.parse_args()
    # The week's id, the SAME one the cron and the admin Send button compute.
    #
    # This used to mint `e2-<random hex>`, which could never collide with
    # anything. An operator running this on a Monday afternoon, not knowing
    # the cron had already sent at 12:00, enqueued a second full cohort, and
    # the only thing between the member and two copies was the 6-day cap,
    # which is exactly what someone reaching for this script is often about
    # to override. Sharing the id makes the second run a no-op instead.
    cid = a.campaign_id or week_campaign_id(datetime.now(timezone.utc), 'e2')
    res = run_campaign(api_tx, 'e2', cid, recipients(), build_for, send=a.send, from_addr=FROM_ADDR,
                       unsub_scope=UNSUB_SCOPE, cap_days=CAP_DAYS,
                       list_unsubscribe=lambda e: f"<mailto:support@ahavah.app?subject=Unsubscribe>, <{_unsub_url(UNSUB_SCOPE, e, WEB_BASE_URL)}>")
    # A real send leaves an audit row, as the Send button's does.
    if a.send:
        with api_tx() as tx:
            audit_send(tx, 'cli', 'e2', res)
    print(res)

if __name__ == '__main__':
    main()
