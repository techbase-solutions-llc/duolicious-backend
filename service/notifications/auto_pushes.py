"""The 3 automatic pushes of the push composer plan (TEC-2182; plan
docs/plans/2026-11-19-push-composer.md, "Automatic pushes").

  likes_waiting_push  a member with at least 1 like from a visible member
                      that is 3 days old or more, unanswered (no like back,
                      pass, block or match), that arrived after they were
                      last online and after their last one of these. At most
                      once in 7 days, 10:00 to 20:00 the member's own time.
                      Toggle: likes (push_likes). Tap: /matches?tab=likes,
                      where the existing like push opens.
  newcomers_push      weekly, Thursday from 10:00 the member's own time:
                      how many members they could be shown on the deck
                      (the other gender, activated, an approved photo,
                      visible to them) joined in their country in the last
                      7 days. Never when it is 0. Once a week. Toggle: news
                      and suggestions (push_announcements). Tap: /discover.
  us_game_push        each member of a current match made 2 days ago or
                      more, both active and visible to each other, with no
                      Together session ever between the pair. Once per match
                      per member and at most 1 in 7 days per member. Toggle:
                      matches (push_matches). Tap: the chat with that match
                      (/chat/<their uuid>), where the More menu starts the
                      Us game; never their name. Needs together_live too,
                      since the chat offers the game only then.

Each goes only while its own switch is on (default off), to a member with
its toggle on and a push subscription; never to staff, a member with
deletion requested or deactivated by an admin, an excluded or suppressed
address, or a member who left campaign email. Tester isolation holds: a
tester is told only about testers and a member never about a tester (the
pair rules, is_tester_split_pair through is_deck_suppressed and
is_blocked_pair). Opposite gender and the deck's visibility apply to
everyone counted or pointed to.

In quiet hours (21:00 to 08:00 the member's time) or a rest period
(resting) a member is skipped this tick and tried on the next one inside
the same period. Each is logged in push_send_log under its period's key in
the cron's transaction and sent once it commits (held.after_commit), and
gives its row back when it reached no device. send_to_user_counted only,
never notify(). The returnmail cron runs the 3 jobs hourly.

The words are drafts: the owner approves them on a test device before any
switch goes on. None names a member or carries their words.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from emails.base import suppressed_sql_pattern
from service.campaigns import held, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.switches import enabled
from service.decisions.answered import passed_on_liker_sql
from service.growth.queries import _excluded
from service.man_woman import man_woman_pair_sql, opposite_gender_sql, staff_sql
from service.questions.pushes import quiet, zone
from service.questions.schedule import resting
from service.spotlight.country import display_country
from service.spotlight.restdays import BARBADOS

LIKES_WAITING = 'likes_waiting_push'
NEWCOMERS = 'newcomers_push'
US_GAME = 'us_game_push'
NAMES = (LIKES_WAITING, NEWCOMERS, US_GAME)

SWITCH = {LIKES_WAITING: 'push_likes_waiting', NEWCOMERS: 'push_newcomers', US_GAME: 'push_us_game'}
TAP_SRC = {LIKES_WAITING: 'lwpush', NEWCOMERS: 'nnpush', US_GAME: 'uspush'}
EVENT = {LIKES_WAITING: 'like', NEWCOMERS: 'announcement', US_GAME: 'match'}
LABEL = {LIKES_WAITING: 'Likes waiting', NEWCOMERS: 'New near you', US_GAME: 'The Us game'}

LIKE_AGE = timedelta(days=3)
EVERY_7_DAYS = timedelta(days=7)
LIKES_HOURS = (10, 20)
NEWCOMER_WEEKDAY, NEWCOMER_FROM = 4, 10      # Thursday, from 10:00
NEWCOMER_DAYS = 7
MATCH_AGE = timedelta(days=2)
# The most pushes one job sends in one tick. The rest are due again next
# hour, inside the same period.
RUN_CAP = 200


def missed(name: str) -> str:
    '''push_send_log's campaign for a push of `name` that reached no device
    once in a period: it is tried once more, on a later tick.'''
    return f'{name}:missed'


def failed(name: str) -> str:
    '''... and for one that reached no device twice: not tried again in
    that period.'''
    return f'{name}:failed'


def push_on(name: str) -> bool:
    if not enabled(SWITCH[name]):
        return False
    if name == US_GAME:
        from service.tools import live
        return live()
    return True


def PUSH_READY() -> bool:
    from service.notifications import PUSH_ENABLED
    return PUSH_ENABLED


# ---------------------------------------------------------------------------
# The words (drafts, for the owner's approval)
# ---------------------------------------------------------------------------

def likes_waiting_push() -> dict:
    return dict(title='Someone likes you', body='You have a like waiting. Open Ahavah to see it.',
                url=f'/matches?tab=likes&src={TAP_SRC[LIKES_WAITING]}', tag='likes-waiting')


def newcomers_push(count: int, country: str) -> dict:
    who = '1 new member' if count == 1 else f'{count} new members'
    return dict(title='New on Ahavah near you', body=f'{who} joined in {country} this week.',
                url=f'/discover?src={TAP_SRC[NEWCOMERS]}', tag='newcomers')


def us_game_push(other_uuid: str, match_id: str) -> dict:
    return dict(title='Try the Us game with your match',
                body='Answer the same questions and see where you agree.',
                url=f'/chat/{other_uuid}?src={TAP_SRC[US_GAME]}', tag=f'us-game-{match_id}')


def sample(name: str) -> dict:
    """The push a test send shows the admin: sample values, never a
    member's."""
    if name == LIKES_WAITING:
        return likes_waiting_push()
    if name == NEWCOMERS:
        return newcomers_push(2, 'Barbados')
    return us_game_push('00000000-0000-0000-0000-000000000000', 'sample')


# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------

def _audience(a: str, column: str) -> str:
    return f"""{a}.activated AND {a}.deletion_requested_at IS NULL AND {a}.admin_deactivated_at IS NULL
       AND NOT {staff_sql(a)}
       AND lower({a}.email) <> ALL(%(ex)s)
       AND NOT ({suppressed_predicate_sql(f'{a}.email')})
       AND NOT ({unsubscribed_predicate_sql('campaigns', f'{a}.id')})
       AND COALESCE((SELECT np.{column} FROM notification_preference np WHERE np.person_id = {a}.id),
                    {'FALSE' if column == 'push_likes' else 'TRUE'})
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {a}.id)"""


def _visible(a: str) -> str:
    """The other person is someone members are shown at all."""
    return f"""{a}.activated AND {a}.deletion_requested_at IS NULL AND {a}.admin_deactivated_at IS NULL
       AND NOT {staff_sql(a)} AND lower({a}.email) <> ALL(%(ex)s)"""


def _tz(a: str) -> str:
    return f"""(SELECT ps.tz FROM push_subscription ps
                 WHERE ps.person_id = {a}.id AND ps.tz IS NOT NULL
                 ORDER BY ps.updated_at DESC LIMIT 1) AS tz"""


def _params(**extra) -> dict:
    # Testers stay in (the pair rules keep them with testers), as in
    # service/notifications/activity_pushes.py.
    return dict(ex=_excluded(testers=False), sup=suppressed_sql_pattern(), **extra)


def _week(now: datetime) -> str:
    return held.week_suffix(now.astimezone(BARBADOS))


def _sent_within_sql(a: str, campaign: str, days: int) -> str:
    return f"""EXISTS (SELECT 1 FROM push_send_log x WHERE x.person_id = {a}.id AND x.campaign = '{campaign}'
                      AND x.sent_at > NOW() - make_interval(days => {days}))"""


_Q_LIKES_WAITING = f"""
    SELECT p.id AS person_id, {_tz('p')}
      FROM person p
     WHERE {_audience('p', 'push_likes')}
       AND NOT {_sent_within_sql('p', LIKES_WAITING, 7)}
       AND NOT EXISTS (SELECT 1 FROM push_send_log x WHERE x.person_id = p.id
                          AND x.campaign IN ('{LIKES_WAITING}', '{LIKES_WAITING}:failed')
                          AND x.campaign_id = %(week)s)
       AND EXISTS (
           SELECT 1 FROM liked l JOIN person liker ON liker.id = l.liker_id
            WHERE l.liked_id = p.id
              AND {_visible('liker')}
              AND l.created_at <= NOW() - make_interval(days => {LIKE_AGE.days})
              AND l.created_at > p.last_online_time
              AND l.created_at > COALESCE((SELECT max(x.sent_at) FROM push_send_log x
                                            WHERE x.person_id = p.id AND x.campaign = '{LIKES_WAITING}'),
                                          '-infinity'::timestamptz)
              AND {man_woman_pair_sql('l.liked_id', 'l.liker_id')}
              AND NOT EXISTS (SELECT 1 FROM liked rev WHERE rev.liker_id = l.liked_id AND rev.liked_id = l.liker_id)
              AND NOT is_blocked_pair(l.liked_id, l.liker_id)
              AND NOT is_tester_split_pair(l.liked_id, l.liker_id)
              AND NOT is_staff_hidden(l.liked_id, l.liker_id)
              AND NOT {passed_on_liker_sql('l.liked_id', 'l.liker_id')}
              AND NOT EXISTS (SELECT 1 FROM ahavah_match m
                               WHERE m.user_a_id = LEAST(l.liker_id, l.liked_id)
                                 AND m.user_b_id = GREATEST(l.liker_id, l.liked_id)))
     ORDER BY p.id
"""


def _newcomer_sql(viewer: str) -> str:
    """Members `viewer` could be shown on the deck who joined in their
    country in the last NEWCOMER_DAYS."""
    return f"""SELECT count(*) FROM person n
         WHERE n.id <> {viewer}.id AND {_visible('n')}
           AND n.sign_up_time > NOW() - make_interval(days => {NEWCOMER_DAYS})
           AND upper(n.country) = upper({viewer}.country)
           AND {opposite_gender_sql('n', f'{viewer}.id')}
           AND NOT n.hide_me_from_strangers AND NOT n.verification_required
           AND EXISTS (SELECT 1 FROM photo ph WHERE ph.person_id = n.id AND ph.moderation_status = 'approved')
           AND NOT is_deck_suppressed({viewer}.id, n.id)
           AND NOT is_blocked_pair({viewer}.id, n.id)"""


_Q_NEWCOMERS = f"""
    SELECT * FROM (
        SELECT p.id AS person_id, p.country, {_tz('p')}, ({_newcomer_sql('p')})::int AS newcomers
          FROM person p
         WHERE {_audience('p', 'push_announcements')}
           AND p.country IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM push_send_log x WHERE x.person_id = p.id
                              AND x.campaign IN ('{NEWCOMERS}', '{NEWCOMERS}:failed')
                              AND x.campaign_id = %(week)s)
    ) c
     WHERE c.newcomers > 0
     ORDER BY c.person_id
"""

_Q_US_GAME = f"""
    WITH m AS (
        SELECT match_id::text AS match_id, user_a_id, user_b_id FROM ahavah_match
         WHERE created_at <= NOW() - make_interval(days => {MATCH_AGE.days})
           AND NOT is_unmatched_pair(user_a_id, user_b_id)
           AND NOT is_blocked_pair(user_a_id, user_b_id)
           AND NOT is_tester_split_pair(user_a_id, user_b_id)
           AND NOT EXISTS (
               SELECT 1 FROM tool_session s
                WHERE (s.owner_person_id = user_a_id AND (s.chat_person_id = user_b_id OR EXISTS (
                         SELECT 1 FROM tool_player g WHERE g.session_id = s.id AND g.person_id = user_b_id)))
                   OR (s.owner_person_id = user_b_id AND (s.chat_person_id = user_a_id OR EXISTS (
                         SELECT 1 FROM tool_player g WHERE g.session_id = s.id AND g.person_id = user_a_id))))
    ), sides AS (
        SELECT match_id, user_a_id AS pid, user_b_id AS other FROM m
        UNION ALL
        SELECT match_id, user_b_id, user_a_id FROM m
    )
    SELECT s.match_id, p.id AS person_id, o.uuid::text AS other_uuid, {_tz('p')}
      FROM sides s
      JOIN person p ON p.id = s.pid
      JOIN person o ON o.id = s.other
     WHERE {_audience('p', 'push_matches')}
       AND {_visible('o')}
       AND {man_woman_pair_sql('p.id', 'o.id')}
       AND NOT is_staff_hidden(p.id, o.id)
       AND NOT {_sent_within_sql('p', US_GAME, 7)}
       AND NOT EXISTS (SELECT 1 FROM push_send_log x WHERE x.person_id = p.id
                          AND x.campaign IN ('{US_GAME}', '{US_GAME}:failed')
                          AND x.campaign_id = s.match_id)
     ORDER BY p.id, s.match_id
"""


def _local(now: datetime, tz: Optional[str]) -> datetime:
    return now.astimezone(zone(tz))


def _likes_window(local: datetime) -> bool:
    return LIKES_HOURS[0] <= local.hour < LIKES_HOURS[1]


def _newcomers_window(local: datetime) -> bool:
    return local.isoweekday() == NEWCOMER_WEEKDAY and local.hour >= NEWCOMER_FROM and not quiet(local)


def candidates(tx, name: str, now: datetime) -> list[dict]:
    """Everyone due this period, before the hour and quiet-hour checks:
    {person_id, tz, cid, push}. A dry run reads this too."""
    week = _week(now)
    out: list[dict] = []
    if name == LIKES_WAITING:
        for r in tx.execute(_Q_LIKES_WAITING, _params(week=week)).fetchall():
            out.append(dict(person_id=r['person_id'], tz=r['tz'], cid=week, push=likes_waiting_push()))
    elif name == NEWCOMERS:
        for r in tx.execute(_Q_NEWCOMERS, _params(week=week)).fetchall():
            country = display_country(r['country'])
            if not country:
                continue
            out.append(dict(person_id=r['person_id'], tz=r['tz'], cid=week,
                            push=newcomers_push(int(r['newcomers']), country)))
    elif name == US_GAME:
        seen: set[int] = set()
        for r in tx.execute(_Q_US_GAME, _params()).fetchall():
            # 1 Us game push per member a tick, whatever their matches: the
            # 7 day rule then holds the rest.
            if r['person_id'] in seen:
                continue
            seen.add(r['person_id'])
            out.append(dict(person_id=r['person_id'], tz=r['tz'], cid=r['match_id'],
                            push=us_game_push(r['other_uuid'], r['match_id'])))
    else:
        raise KeyError(name)
    return out


def _in_window(name: str, local: datetime) -> bool:
    if name == LIKES_WAITING:
        return _likes_window(local)
    if name == NEWCOMERS:
        return _newcomers_window(local)
    return True


# ---------------------------------------------------------------------------
# The send
# ---------------------------------------------------------------------------

def _push(person_id: int, push: dict, name: str) -> int:
    from service.notifications import send_to_user_counted
    return send_to_user_counted(person_id, push['title'], push['body'], push['url'], push['tag'],
                                event_kind=EVENT[name], kind=name)  # type: ignore[arg-type]


def _unlog(person_id: int, campaign: str, cid: str) -> None:
    '''A push that reached no device gives its row back. The first time in
    a period it is noted as missed and tried again on a later tick; the
    second time it is noted as failed and not tried again that period.'''
    from database import api_tx
    with api_tx() as tx:
        tx.execute("""DELETE FROM push_send_log
                       WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                   dict(p=person_id, c=campaign, cid=cid))
        again = tx.execute("""DELETE FROM push_send_log
                                WHERE person_id = %(p)s AND campaign = %(m)s AND campaign_id = %(cid)s
                            RETURNING 1""", dict(p=person_id, m=missed(campaign), cid=cid)).fetchone()
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id)
                       VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING""",
                   dict(p=person_id, c=failed(campaign) if again else missed(campaign), cid=cid))


def _deliver(tx, person_id: int, name: str, cid: str, push: dict) -> bool:
    if tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id)
                     VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
                  dict(p=person_id, c=name, cid=cid)).fetchone() is None:
        return False

    def send() -> None:
        if not _push(person_id, push, name):
            _unlog(person_id, name, cid)

    held.after_commit(send, on_failure=lambda: _unlog(person_id, name, cid))
    return True


def _queue(name: str) -> Callable:
    def job(tx, now: datetime) -> int:
        if not push_on(name) or not PUSH_READY() or resting(now):
            return 0
        n = 0
        for c in candidates(tx, name, now):
            if n >= RUN_CAP:
                break
            local = _local(now, c['tz'])
            if quiet(local) or not _in_window(name, local):
                continue
            if _deliver(tx, c['person_id'], name, c['cid'], c['push']):
                n += 1
        return n
    job.__name__ = f'queue_{name}'
    return job


queue_likes_waiting = _queue(LIKES_WAITING)
queue_newcomers = _queue(NEWCOMERS)
queue_us_game = _queue(US_GAME)


def _dry_run_probe() -> None:
    """A test hook: called once inside a dry run's no_send()."""


def dry_run(name: str, now: Optional[datetime] = None) -> dict:
    """What a tick would do now, whichever way the switch is set. Writes
    nothing and runs inside the send guard's no_send()."""
    from database import api_tx
    from smtp import guard
    if name not in NAMES:
        raise KeyError(name)
    now = now or datetime.now(timezone.utc)
    with guard.no_send():
        _dry_run_probe()
        with api_tx('read committed') as tx:
            rows = candidates(tx, name, now)
    rest = resting(now)
    would = held_quiet = outside = 0
    for c in rows:
        local = _local(now, c['tz'])
        if rest:
            continue
        if quiet(local):
            held_quiet += 1
        elif not _in_window(name, local):
            outside += 1
        else:
            would += 1
    return dict(dry_run=True, name=name, switch_on=push_on(name), due=len(rows), would_send_now=would,
                held=dict(quiet=held_quiet, resting=len(rows) if rest else 0, outside_window=outside))


def test_send(name: str, admin_person_id: int) -> Optional[str]:
    """The sample to the signed-in admin's own devices. None when it went,
    else why not. Works while the switch is off; nothing is logged."""
    from database import api_tx
    from service.notifications import PUSH_ENABLED, _send_to_user_blocking
    if name not in NAMES:
        raise KeyError(name)
    if not PUSH_ENABLED:
        return 'vapid_missing'
    with api_tx('read committed') as tx:
        if tx.execute("SELECT 1 FROM push_subscription WHERE person_id = %(p)s LIMIT 1",
                      dict(p=admin_person_id)).fetchone() is None:
            return 'no_push_subscription'
    return None if _send_to_user_blocking(admin_person_id, sample(name), kind=f'{name}_test') else 'not_delivered'


_Q_ROW = """
    SELECT (SELECT count(*) FROM push_send_log
             WHERE campaign = %(c)s AND sent_at > NOW() - interval '7 days')::int AS sent_7d,
           (SELECT count(*) FROM push_tap
             WHERE src = %(src)s AND tapped_at > NOW() - interval '7 days')::int AS tapped_7d
"""


def growth_rows(tx) -> list[dict]:
    """The push and tiers card's rows: on or off, sent and tapped in the
    last 7 days. Counts only."""
    out = []
    for name in NAMES:
        r = tx.execute(_Q_ROW, dict(c=name, src=TAP_SRC[name])).fetchone()
        out.append(dict(name=name, label=LABEL[name], switch=SWITCH[name], enabled=push_on(name),
                        sent_7d=r['sent_7d'], tapped_7d=r['tapped_7d']))
    return out
