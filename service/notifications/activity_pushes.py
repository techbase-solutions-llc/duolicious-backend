"""The 3 member pushes of the in-app plan's release 4 (TEC-1845; ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 9).

  gathering_reminder  the day before a gathering the member is going to, in
                      the gathering's own day before, 08:00 to 21:00 its
                      local time, as the reminder email goes; once per place
                      and start time
  new_guests          new confirmed guests for the gatherings a member hosts
                      (an organiser with the member's address), at most once
                      a day, counting the guests confirmed since the last one
  match_played        a member's match finished the Us game the two were
                      playing: to the one who finished first and was
                      waiting; once per game

Each goes only while its own switch is on (default off) and its feature is
live (push_on), to a member with its toggle on (migration 0086, default
on) and a push subscription; never to staff (the member rule), a test or a
suppressed address; never in quiet hours (21:00 to 08:00 the member's
local time, from push_subscription.tz, US Eastern when missing); never in
a rest period or past the last date the owner's calendar is known for
(service/questions/schedule.resting, which reads service/spotlight/
restdays.py). A push held back by quiet hours or a rest period is tried
again on the next hourly tick while its window lasts.

Each is logged in push_send_log in the cron's transaction and sent once it
commits (held.after_commit), and gives its log row back when it reached no
device, as the question pushes do. send_to_user_counted only, never
notify(), which would fall back to email. None counts towards the gap
between the nudges (service/campaigns/held.py): each is about something
the member did.

The returnmail cron runs the 3 jobs hourly (service/cron/returnmail).

PROPOSED COPY, for the owner's proof (scripts/send_proofs.py): every title
and body below is new and waits for /copy-pass and the owner.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from emails.base import suppressed_sql_pattern
from service.admin.queries.members import member_sql
from service.campaigns import held, suppressed_predicate_sql
from service.campaigns.switches import enabled
from service.growth.queries import _excluded
from service.questions.pushes import quiet, zone
from service.questions.schedule import resting

GATHERING_REMINDER = 'gathering_reminder'
NEW_GUESTS = 'new_guests'
MATCH_PLAYED = 'match_played'

# A finished game is pushed about within this window, so a rest period
# (up to 31 hours) or a night of quiet hours delays the push, never loses it.
MATCH_PLAYED_WINDOW = timedelta(days=3)
NEW_GUESTS_LOOKBACK = timedelta(days=1)


def push_on(switch: str) -> bool:
    """A release 4 push may go: its own switch and its feature's."""
    if not enabled(switch):
        return False
    if switch == 'push_gathering_reminder':
        from service.events import live
        return live()
    if switch == 'push_new_guests':
        from service.events import surface_on
        return surface_on('events_hosting')
    if switch == 'push_match_played':
        from service.tools import live as together_live
        return together_live()
    raise KeyError(switch)


def PUSH_READY() -> bool:
    from service.notifications import PUSH_ENABLED
    return PUSH_ENABLED


# ---------------------------------------------------------------------------
# The words (PROPOSED, for the owner's proof)
# ---------------------------------------------------------------------------

def gathering_reminder_push(rsvp_id: int, title: str) -> dict:
    """PROPOSED COPY."""
    return dict(title='Your gathering is tomorrow',
                body=f'{title} is tomorrow. The time and place are in Ahavah.',
                url=f'/profile/gatherings/{rsvp_id}', tag=f'gathering-reminder-{rsvp_id}')


def new_guests_push(guests: int, titles: list[str]) -> dict:
    """PROPOSED COPY. One gathering is named; several are "your gatherings"."""
    who = '1 new guest is' if guests == 1 else f'{guests} new guests are'
    where = titles[0] if len(titles) == 1 else 'your gatherings'
    return dict(title='New guests', body=f'{who} going to {where}.',
                url='/host/gatherings', tag='new-guests')


def match_played_push(session_uuid: str, other_first_name: str) -> dict:
    """PROPOSED COPY."""
    return dict(title='Your result is ready',
                body=f'{other_first_name} has finished the game. See how you answered together.',
                url=f'/together/game?session={session_uuid}', tag=f'match-played-{session_uuid}')


# Sample pushes for the owner's proof, with sample names, never a member's.
def proof_pushes() -> list[dict]:
    return [dict(gathering_reminder_push(1, 'Marriage preparation evening'), kind='gathering_reminder'),
            dict(new_guests_push(3, ['Marriage preparation evening']), kind='new_guests'),
            dict(new_guests_push(1, ['Sabbath fellowship lunch', 'Marriage preparation evening']),
                 kind='new_guests_several'),
            dict(match_played_push('00000000-0000-0000-0000-000000000000', 'Hannah'), kind='match_played')]


# ---------------------------------------------------------------------------
# Who may get one, and the send
# ---------------------------------------------------------------------------

def _audience(alias: str, column: str) -> str:
    return f"""{alias}.activated AND {alias}.deletion_requested_at IS NULL
       AND {member_sql(alias)}
       AND lower({alias}.email) <> ALL(%(ex)s)
       AND NOT ({suppressed_predicate_sql(f'{alias}.email')})
       AND COALESCE((SELECT np.{column} FROM notification_preference np
                      WHERE np.person_id = {alias}.id), TRUE)
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {alias}.id)"""


def _tz(alias: str) -> str:
    return f"""(SELECT ps.tz FROM push_subscription ps
                 WHERE ps.person_id = {alias}.id AND ps.tz IS NOT NULL
                 ORDER BY ps.updated_at DESC LIMIT 1) AS tz"""


def _params(**extra) -> dict:
    return dict(ex=_excluded(), sup=suppressed_sql_pattern(), **extra)


def _push(person_id: int, push: dict, event_kind: str) -> int:
    """Send now and return how many devices took it."""
    from service.notifications import send_to_user_counted
    return send_to_user_counted(person_id, push['title'], push['body'], push['url'], push['tag'],
                                event_kind=event_kind)  # type: ignore[arg-type]


def _unlog(person_id: int, campaign: str, cid: str) -> None:
    """In its own transaction, from held.run_after_commit."""
    from database import api_tx
    with api_tx() as tx:
        tx.execute("""DELETE FROM push_send_log
                       WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                   dict(p=person_id, c=campaign, cid=cid))


def _already(tx, person_id: int, campaign: str, cid: str) -> bool:
    return tx.execute("""SELECT 1 FROM push_send_log
                          WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                      dict(p=person_id, c=campaign, cid=cid)).fetchone() is not None


def _deliver(tx, person_id: int, campaign: str, cid: str, push: dict) -> bool:
    """Log the key, then push after the commit. False when the key is
    already taken (a repeat tick, or another tick got there)."""
    if tx.execute(
            """INSERT INTO push_send_log (person_id, campaign, campaign_id)
               VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
            dict(p=person_id, c=campaign, cid=cid)).fetchone() is None:
        return False

    def send() -> None:
        if not _push(person_id, push, campaign):
            _unlog(person_id, campaign, cid)

    held.after_commit(send, on_failure=lambda: _unlog(person_id, campaign, cid))
    return True


def _may_send(switch: str, now: datetime) -> bool:
    return push_on(switch) and PUSH_READY() and not resting(now)


# ---------------------------------------------------------------------------
# A reminder of a gathering the member is going to
# ---------------------------------------------------------------------------

_Q_GOING_SOON = f"""
    SELECT r.id AS rsvp_id, e.title, e.starts_at, e.tz AS event_tz, p.id AS person_id, {_tz('p')}
      FROM event_rsvp r
      JOIN event e ON e.id = r.event_id
      JOIN person p ON p.id = r.person_id
     WHERE e.status = 'published' AND e.paused_at IS NULL
       AND e.starts_at > %(now)s AND e.starts_at <= %(until)s
       AND r.status = 'going' AND r.confirmed_at IS NOT NULL AND r.erased_at IS NULL
       AND {_audience('p', 'push_gathering_reminder')}
     ORDER BY e.starts_at, r.id
"""


def queue_gathering_reminders(tx, now: datetime) -> int:
    from service.events.jobs import _REMINDER_LOOKAHEAD, _reminder_due
    from service.events.mail import reminder_campaign_id
    if not _may_send('push_gathering_reminder', now):
        return 0
    n = 0
    for r in tx.execute(_Q_GOING_SOON, _params(now=now, until=now + _REMINDER_LOOKAHEAD)).fetchall():
        if not _reminder_due(r['starts_at'], r['event_tz'], now) or quiet(now.astimezone(zone(r['tz']))):
            continue
        cid = reminder_campaign_id(r['rsvp_id'], r['starts_at'])
        if _already(tx, r['person_id'], GATHERING_REMINDER, cid):
            continue
        if _deliver(tx, r['person_id'], GATHERING_REMINDER, cid,
                    gathering_reminder_push(r['rsvp_id'], r['title'])):
            n += 1
    return n


# ---------------------------------------------------------------------------
# New guests for a gathering the member hosts, at most once a day
# ---------------------------------------------------------------------------

# Guests (party sizes) confirmed since the member's last new-guests push,
# or in the last day, on each published gathering still to end that an
# organiser with the member's address hosts.
_Q_NEW_GUESTS = f"""
    SELECT p.id AS person_id, {_tz('p')}, e.id AS event_id, e.title,
           SUM(r.party_size)::int AS guests
      FROM person p
      JOIN organiser o ON o.normalized_email = p.normalized_email AND o.revoked_at IS NULL
      JOIN event e ON e.organiser_id = o.id AND e.status = 'published' AND e.paused_at IS NULL
                  AND e.ends_at > %(now)s
      JOIN event_rsvp r ON r.event_id = e.id AND r.status = 'going' AND r.erased_at IS NULL
                       AND r.confirmed_at IS NOT NULL
     WHERE {_audience('p', 'push_new_guests')}
       AND r.confirmed_at > GREATEST(%(since)s, COALESCE(
             (SELECT max(l.sent_at) FROM push_send_log l
               WHERE l.person_id = p.id AND l.campaign = '{NEW_GUESTS}'), '-infinity'::timestamptz))
       AND (r.person_id IS NULL OR r.person_id <> p.id)
     GROUP BY p.id, e.id
     ORDER BY p.id, e.starts_at, e.id
"""


def _day_key(now: datetime) -> str:
    from service.spotlight.restdays import BARBADOS
    return now.astimezone(BARBADOS).date().isoformat()


def queue_new_guests(tx, now: datetime) -> int:
    if not _may_send('push_new_guests', now):
        return 0
    by_member: dict[int, list[dict]] = defaultdict(list)
    for r in tx.execute(_Q_NEW_GUESTS, _params(now=now, since=now - NEW_GUESTS_LOOKBACK)).fetchall():
        by_member[r['person_id']].append(dict(r))
    day = _day_key(now)
    n = 0
    for person_id, rows in by_member.items():
        if quiet(now.astimezone(zone(rows[0]['tz']))) or _already(tx, person_id, NEW_GUESTS, day):
            continue
        push = new_guests_push(sum(r['guests'] for r in rows), [r['title'] for r in rows])
        if _deliver(tx, person_id, NEW_GUESTS, day, push):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Your match finished the game
# ---------------------------------------------------------------------------

# Us games finished in the window by two members who are matched (and not
# blocked): the player who finished first was waiting, and hears.
_Q_PLAYED = f"""
    WITH done AS (
        SELECT s.uuid::text AS session_uuid, s.owner_person_id AS owner_id, g.person_id AS guest_id,
               (o.finished_at <= g.finished_at) AS owner_first
          FROM tool_session s
          JOIN tool_player o ON o.session_id = s.id AND o.seat = 'owner'
          JOIN tool_player g ON g.session_id = s.id AND g.seat = 'guest' AND g.removed_at IS NULL
         WHERE s.mode = 'us' AND s.deleted_at IS NULL
           AND s.completed_at > %(since)s
           AND o.finished_at IS NOT NULL AND g.finished_at IS NOT NULL
           AND s.owner_person_id IS NOT NULL AND g.person_id IS NOT NULL
           AND s.owner_person_id <> g.person_id
    ), pairs AS (
        SELECT session_uuid,
               CASE WHEN owner_first THEN owner_id ELSE guest_id END AS pid,
               CASE WHEN owner_first THEN guest_id ELSE owner_id END AS other_id
          FROM done
    )
    SELECT x.session_uuid, p.id AS person_id, {_tz('p')}, other.name AS other_name
      FROM pairs x
      JOIN person p ON p.id = x.pid
      JOIN person other ON other.id = x.other_id
                       AND other.activated AND other.deletion_requested_at IS NULL
     WHERE {_audience('p', 'push_match_played')}
       AND EXISTS (SELECT 1 FROM ahavah_match m
                    WHERE m.user_a_id = LEAST(x.pid, x.other_id) AND m.user_b_id = GREATEST(x.pid, x.other_id))
       AND NOT is_blocked_pair(x.pid, x.other_id)
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{MATCH_PLAYED}'
                          AND l.campaign_id = x.session_uuid)
     ORDER BY x.session_uuid
"""


def queue_match_played(tx, now: datetime) -> int:
    from service.matchmaker import first_name
    if not _may_send('push_match_played', now):
        return 0
    n = 0
    for r in tx.execute(_Q_PLAYED, _params(since=now - MATCH_PLAYED_WINDOW)).fetchall():
        if quiet(now.astimezone(zone(r['tz']))):
            continue
        if _deliver(tx, r['person_id'], MATCH_PLAYED, r['session_uuid'],
                    match_played_push(r['session_uuid'], first_name(r['other_name']))):
            n += 1
    return n


def queue_all(tx, now: Optional[datetime] = None) -> dict:
    """For a test or a manual run: every job once."""
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    return dict(gathering_reminder=queue_gathering_reminders(tx, now),
                new_guests=queue_new_guests(tx, now), match_played=queue_match_played(tx, now))
