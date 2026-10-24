"""python -m emails.send_community_weekly [--send] [--campaign-id ID]"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional
from database import api_tx
from emails.base import suppressed_sql_pattern
from emails.community_weekly import community_weekly_html, SUBJECT, FROM_ADDR
from service.campaigns import make_campaign_link, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.runner import audit_send, run_campaign
from service.campaigns.switches import enabled
from service.campaigns.weekid import week_campaign_id
from service.admin.queries.members import member_sql
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded, count_newcomers_since, newcomers_since
from service.questions.member import e2_question_line
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
    SELECT p.id AS person_id, p.email, p.name, p.country FROM person p
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

def _week_gatherings(tx, now: datetime) -> dict:
    """Gatherings near you (TEC-1845), every region's list read once for
    the run, or {} while AHAVAH_E2_GATHERINGS_ENABLED (or the events live
    and list switches) is off, which leaves the section out of every
    email."""
    from service.events import member_email_on, public
    if not member_email_on('e2_gatherings'):
        return {}
    return public.gatherings_for_members(tx, now=now)


def _week_context(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with api_tx('read committed') as tx:
        spotlight_row = tx.execute(_Q_SPOTLIGHT).fetchone()
        return dict(new_members=[dict(r) for r in tx.execute(_Q_NEW, dict(ex=_excluded())).fetchall()],
                    total=int(tx.execute(_Q_TOTAL, dict(ex=_excluded())).fetchone()['n']),
                    spotlight=_spotlight_from_row(spotlight_row) if spotlight_row else None,
                    gatherings=_week_gatherings(tx, now))

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


def newcomers_for(tx, person_id: int, week: dict) -> list[dict]:
    """The week's newcomers this reader is looking for, by the gender and
    age rule `count_newcomers_since` counts with (16 Oct 2026: every reader
    used to see everyone, so a man looking for a woman read the list of men
    who had joined). When none fit, the week's full list, as every reader
    saw it before: the email still says who joined and claims no match. A
    row with no person (a preview) gets the full list too."""
    if not person_id:
        return week['new_members']
    fits = newcomers_since(tx, person_id, datetime.now(timezone.utc) - timedelta(days=7), limit=None)
    return [dict(first_name=r['first_name'], country=r['country']) for r in fits] or week['new_members']


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
            cta_label='Open your likes', target=f"{WEB_BASE_URL}/matches?tab=likes")
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


def _gathering_parts(tx, row: dict, week: dict, dry: bool) -> dict:
    """The reader's Gatherings near you, as community_weekly_html's keyword
    arguments: their region's list (online only with no country), the
    see-all link to /events on their region and one link per card, each
    minted as an E2 campaign link so the click counts for E2 and never as
    an event:{slug} lead. {} when the week has no lists (the switch is off)
    or the reader has no gathering whose card can be drawn: nothing is
    minted then. The switch is read again here, but it is the environment
    the container started with, so it changes only when the container is
    recreated; the rows a run has already queued are cleared of the
    section by the drain (service/campaigns/outbox.py _send_html), which
    reads the switch again at the send."""
    from service.events import member_email_on, public
    from service.matchmaker.regions import region_of
    from emails.community_weekly import renderable
    lists = week.get('gatherings')
    if not lists or not member_email_on('e2_gatherings'):
        return {}
    country = row.get('country') if row.get('person_id') else None
    cards, online_only = public.for_member(lists, country)
    cards = renderable(cards)
    if not cards:
        return {}
    pid = row.get('person_id') or None
    region = region_of(country)
    see_all = f"{WEB_BASE_URL}/events?region={region}" if region else f"{WEB_BASE_URL}/events"
    return dict(
        gatherings=cards, gatherings_online_only=online_only,
        gatherings_see_all_url=make_campaign_link(tx, 'e2', see_all, pid, dry_run=dry),
        gathering_url=lambda slug: make_campaign_link(tx, 'e2', f"{WEB_BASE_URL}/e/{slug}", pid, dry_run=dry))


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
        new_members = newcomers_for(tx, pid, week)
        question_line = e2_question_line(tx, pid, datetime.now(timezone.utc))
        # Built inside the transaction: the card links are minted as the
        # block is built.
        return parts['subject'], community_weekly_html(
            new_members, week['total'], week['spotlight'], cta,
            _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
            personal_line=parts['line'], invite_url=invite, cta_label=parts['cta_label'],
            question_line=question_line, **_gathering_parts(tx, row, week, dry))


def build_for(row: dict) -> tuple[str, str]:
    week = row['week']
    if enabled('e2_personal') and row.get('person_id'):
        return _build_personal(row)
    with api_tx() as tx:
        cta = make_campaign_link(tx, 'e2', f"{WEB_BASE_URL}/discover", row['person_id'] or None,
                                 dry_run=row.get('dry_run', False))
        new_members = newcomers_for(tx, row['person_id'], week)
        question_line = (e2_question_line(tx, row['person_id'], datetime.now(timezone.utc))
                         if row.get('person_id') else None)
        return SUBJECT, community_weekly_html(new_members, week['total'], week['spotlight'], cta,
                                              _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
                                              question_line=question_line,
                                              **_gathering_parts(tx, row, week, row.get('dry_run', False)))


def preview_personal(to: str) -> tuple[str, str]:
    """The proof of the personal E2: 2 likes waiting, sample newcomers, the
    invite button built by `invite_target` from a sample code, as the real
    send builds it. Reads nothing per member and stores nothing."""
    parts = personal_parts(2, 0, 0)
    return parts['subject'], community_weekly_html(
        [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB')], 58, None,
        parts['target'], _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        personal_line=parts['line'], invite_url=invite_target('YOURCODE'), cta_label=parts['cta_label'])


def preview_question_line(to: str) -> tuple[str, str]:
    """The proof of the question line (TEC-1845): E2 as every member gets
    it, with the line for the sample question. Reads nothing per member and
    stores nothing; the button goes straight to Discover."""
    from service.questions.copy import SAMPLE_QUESTION, e2_line
    return SUBJECT, community_weekly_html(
        [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB')], 58, None,
        f"{WEB_BASE_URL}/discover", _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        question_line=e2_line(SAMPLE_QUESTION))


# The sample gatherings of Ahavah Gatherings in Member Emails.html (GS and
# ON in pages/p20-member-emails.js), as gatherings_for_members returns them,
# for the proof and the phone check. Sample data only. W.1 draws the first 3.
SAMPLE_GATHERINGS = [
    dict(slug='marriage-preparation-evening', title='Marriage preparation evening', mode='in_person',
         city='Dallas', country='United States', region='north-america',
         organiser=dict(name='Grace Fellowship', kind='assembly'), ahavah_attending=True,
         date=('Sat', '7', 'Nov')),
    dict(slug='fellowship-meal-for-singles', title='Fellowship meal for singles', mode='in_person',
         city='Atlanta', country='United States', region='north-america',
         organiser=dict(name='Living Waters Assembly', kind='assembly'), ahavah_attending=False,
         date=('Sat', '21', 'Nov')),
    dict(slug='sabbath-afternoon-study-and-tea', title='Sabbath afternoon study and tea', mode='in_person',
         city='Hamilton', country='Canada', region='north-america',
         organiser=dict(name='Hamilton Torah Fellowship', kind='fellowship_leader'), ahavah_attending=False,
         date=('Sat', '28', 'Nov')),
]

# Host text with long unbroken words (a web address as the organiser, a
# title holding one), for the phone check: each must wrap inside its card.
SAMPLE_GATHERINGS_LONG_WORDS = [
    dict(slug='www-torahsingles-org-evening', title='Evening at https://www.torahsingles.org/gatherings/winter',
         mode='in_person', city='Dallas', country='United States', region='north-america',
         organiser=dict(name='www.torahsingles.org', kind='fellowship_leader'), ahavah_attending=True,
         date=('Sat', '7', 'Nov')),
    dict(slug='hebrew-roots-fellowship-meal', title='Fellowship meal', mode='in_person',
         city='Austin', country='United States', region='north-america',
         organiser=dict(name='HebrewRootsFellowshipOfTexas', kind='assembly'), ahavah_attending=False,
         date=('Sat', '14', 'Nov')),
]

# W.3: every card online, for a member with a region.
SAMPLE_GATHERINGS_ONLINE = [
    dict(slug='preparing-for-marriage-a-talk', title='Preparing for marriage: a talk and questions',
         mode='online', city=None, country=None, region='online',
         organiser=dict(name='Ahavah', kind='ahavah'), ahavah_attending=False, date=('Thu', '12', 'Nov')),
    dict(slug='reading-ruth-together', title='Reading Ruth together: a study for singles',
         mode='online', city=None, country=None, region='online',
         organiser=dict(name='Fellowship of the Way', kind='fellowship_leader'), ahavah_attending=False,
         date=('Sun', '15', 'Nov')),
]


def _preview_gatherings(to: str, gatherings: list[dict], online_only: bool) -> tuple[str, str]:
    """E2 as every member gets it, with sample gatherings. Reads nothing per
    member and stores nothing. The sample slugs are not real gatherings, so
    every card opens North America's list, as See all gatherings does,
    rather than a page that answers 404."""
    region_list = f"{WEB_BASE_URL}/events?region=north-america"
    return SUBJECT, community_weekly_html(
        [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB')], 58, None,
        f"{WEB_BASE_URL}/discover", _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        gatherings=gatherings, gatherings_online_only=online_only, gatherings_see_all_url=region_list,
        gathering_url=lambda slug: region_list)


def preview_gatherings(to: str) -> tuple[str, str]:
    """The proof of Gatherings near you (TEC-1845), W.1's 3 sample gatherings."""
    return _preview_gatherings(to, SAMPLE_GATHERINGS, False)


def preview_gatherings_online(to: str) -> tuple[str, str]:
    """The proof of W.3: every card online, with "Nothing near you yet.
    These are online." above them."""
    return _preview_gatherings(to, SAMPLE_GATHERINGS_ONLINE, True)


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
