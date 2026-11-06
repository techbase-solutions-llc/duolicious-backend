"""The pushes that ask members into Community Spotlight (TEC-2113; plan
docs/plans/2026-11-05-spotlight-opt-in-prompts.md).

The owner, 5 Nov 2026: "make his card and send him a push so we can get his
spotlight out now and push to other members and email the rest with push
off so they can opt in at the earliest possible convenience".

Two Growth rows push, each through `run` from the Send button:

  spotlight_push  activated members who are not staff, have push on, have
                  not opted in and have not left campaign email. A tap opens
                  /settings/privacy, where the Spotlight switch is (a push
                  cannot carry E1's single-use confirm link). Once per member
                  per run; the Send button keys a run by ISO week.
  card_push       members whose drawn card waits for their approval and whose
                  card-ready email (E4) has gone. A tap opens the card with a
                  fresh single-use card link. Once per card revision, keyed
                  `<request_key>:<revision id>`, however many runs ask.

The card push also goes by itself: `_enqueue_card_ready`
(service/api/admin/spotlight_routes.py) calls `queue_card_ready_push`
whenever it queues a new E4, inside a `collect_card_pushes()` block that
sends it once the transaction commits. Outside such a block nothing is
logged, so the Growth row can still send it.

Every push here waits out quiet hours (21:00 to 08:00 the member's time). A
push is logged in push_send_log before it is sent, and a push that reached
no device gives its row back, so the next Send tries that member again. A
run sends at most PUSH_CAP pushes; a second Send with the same id carries on
from where it stopped. A dry run counts, writes nothing and runs inside the
send guard's no_send(). The sends run on a thread after the rows are
written, so a full run does not hold the request open; a restart part way
loses the rest of that run's pushes, which stay logged.

The emailed half is emails/send_spotlight_announcement_push_off.py.
"""
from __future__ import annotations

import contextvars
import json
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from emails.base import mask_email, suppressed_sql_pattern
from service.campaigns import suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.switches import enabled
from service.config import WEB_BASE_URL
from service.growth.queries import _excluded
from service.man_woman import staff_sql
from service.questions.pushes import quiet, zone
from service.questions.schedule import resting

OPT_IN = 'spotlight_push'
CARD = 'card_push'
CAMPAIGNS = (OPT_IN, CARD)

# The most pushes one run sends. Another Send with the same id goes on.
PUSH_CAP = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

def opt_in_push() -> dict:
    return dict(title='Be featured on Ahavah',
                body='Turn on Spotlight and you could be our member of the week.',
                url='/settings/privacy', tag='spotlight-opt-in')


def card_push(url: str) -> dict:
    return dict(title='Your Spotlight card is ready',
                body='Open the email from Ahavah and tap Approve to be featured.',
                url=url, tag='spotlight-card-ready')


# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------

def _member_rules(alias: str = 'p') -> str:
    """An activated member who is not staff (admin or mod) or a test address,
    whose address is not suppressed, who has not left campaign email, and who
    has a push subscription."""
    return f"""{alias}.activated AND {alias}.deletion_requested_at IS NULL
       AND NOT {staff_sql(alias)}
       AND lower({alias}.email) <> ALL(%(ex)s)
       AND NOT ({suppressed_predicate_sql(f'{alias}.email')})
       AND NOT ({unsubscribed_predicate_sql('campaigns', f'{alias}.id')})
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {alias}.id)"""


def _tz(alias: str = 'p') -> str:
    return f"""(SELECT ps.tz FROM push_subscription ps
                 WHERE ps.person_id = {alias}.id AND ps.tz IS NOT NULL
                 ORDER BY ps.updated_at DESC LIMIT 1) AS tz"""


_Q_OPT_IN = f"""
    SELECT p.id AS person_id, p.email, {_tz('p')}, NULL::text AS log_id
      FROM person p
     WHERE {_member_rules('p')}
       AND NOT p.spotlight_opt_in
       AND (%(cid)s::text IS NULL OR NOT EXISTS (
             SELECT 1 FROM push_send_log l
              WHERE l.person_id = p.id AND l.campaign = '{OPT_IN}' AND l.campaign_id = %(cid)s))
     ORDER BY p.id
"""

# One row per card (each platform row of a request carries the same subject
# and revision). Drawn: the current revision has an asset. Emailed: an E4
# for the request, under either key, that the drain has not dropped.
_Q_CARD = f"""
    SELECT * FROM (
        SELECT DISTINCT ON (q.request_key)
               p.id AS person_id, p.email, {_tz('p')}, q.request_key,
               q.request_key || ':' || q.current_revision_id::text AS log_id
          FROM publishing_queue q
          JOIN person p ON p.id = q.subject_person_id
         WHERE q.kind IN ('welcome', 'member_of_week')
           AND q.status = 'awaiting_member'
           AND q.cancellation_requested_at IS NULL
           AND (%(rk)s::text IS NULL OR q.request_key = %(rk)s)
           AND EXISTS (SELECT 1 FROM spotlight_revision r
                        WHERE r.id = q.current_revision_id AND r.asset_hash IS NOT NULL)
           AND EXISTS (SELECT 1 FROM email_outbox e
                        WHERE e.campaign = 'e4' AND e.person_id = p.id
                          AND e.campaign_id IN ('e4-' || q.request_key, 'e4-drawn-' || q.request_key)
                          AND e.state NOT IN ('failed', 'skipped'))
           AND p.spotlight_opt_in
           AND {_member_rules('p')}
           AND NOT EXISTS (SELECT 1 FROM push_send_log l
                            WHERE l.person_id = p.id AND l.campaign = '{CARD}'
                              AND l.campaign_id = q.request_key || ':' || q.current_revision_id::text)
         ORDER BY q.request_key, q.id
    ) cards
    ORDER BY person_id, request_key
"""


def audience(tx, campaign: str, campaign_id: Optional[str] = None, *,
             request_key: Optional[str] = None) -> list[dict]:
    """Who a run of `campaign` would push, before quiet hours and the cap.
    With `campaign_id`, the opt-in push leaves out who this run has
    reached; the card push always leaves out revisions already pushed."""
    params = dict(ex=_excluded(), sup=suppressed_sql_pattern(), cid=campaign_id, rk=request_key)
    q = {OPT_IN: _Q_OPT_IN, CARD: _Q_CARD}[campaign]
    return [dict(r) for r in tx.execute(q, params).fetchall()]


def _log_id(campaign: str, row: dict, campaign_id: str) -> str:
    return row['log_id'] if campaign == CARD else campaign_id


def _quiet(row: dict, now: datetime) -> bool:
    return quiet(now.astimezone(zone(row.get('tz'))))


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def _push_one(person_id: int, payload: dict, kind: str) -> int:
    """Send to every device the member has; how many took it."""
    from service.notifications import _send_to_user_blocking
    return _send_to_user_blocking(person_id, payload, kind=kind)


def _unlog(person_id: int, campaign: str, log_id: str) -> None:
    from database import api_tx
    with api_tx() as tx:
        tx.execute("""DELETE FROM push_send_log
                       WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                   dict(p=person_id, c=campaign, cid=log_id))


def _deliver(items: list[dict]) -> int:
    """Push each claimed item, outside any transaction; give back the row of
    one no device took. Returns how many went."""
    went = 0
    for it in items:
        try:
            n = _push_one(it['person_id'], it['push'], it['campaign'])
        except Exception:
            print(traceback.format_exc())
            n = 0
        if n:
            went += 1
        else:
            try:
                _unlog(it['person_id'], it['campaign'], it['log_id'])
            except Exception:
                print(traceback.format_exc())
    if items:
        print('SPOTLIGHT_PUSH ' + json.dumps(dict(campaign=items[0]['campaign'], handed=len(items), went=went)),
              flush=True)
    return went


def _deliver_later(items: list[dict]) -> None:
    from smtp import guard
    guard.spawn(_deliver, items)


def _claim(tx, person_id: int, campaign: str, log_id: str) -> bool:
    return tx.execute(
        """INSERT INTO push_send_log (person_id, campaign, campaign_id)
           VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
        dict(p=person_id, c=campaign, cid=log_id)).fetchone() is not None


def _card_link(tx, request_key: str, email: str) -> Optional[str]:
    """The card page, as a path, with a fresh single-use card link."""
    from service.spotlight.approval import card_url
    url = card_url(tx, request_key, email)
    if url is None:
        return None
    base = WEB_BASE_URL.rstrip('/')
    return url[len(base):] if url.startswith(base) else url


def _build(tx, campaign: str, row: dict) -> Optional[dict]:
    if campaign == OPT_IN:
        return opt_in_push()
    link = _card_link(tx, row['request_key'], row['email'])
    return card_push(link) if link else None


def _dry_run_probe() -> None:
    """A test hook: called once inside a dry run's no_send()."""


def run(campaign: str, campaign_id: str, *, send: bool, cap: int = PUSH_CAP,
        now: Optional[datetime] = None) -> dict:
    """One run from the Growth tab's Send button (or its dry run). The
    answer has the email runner's keys, so the admin reads it the same way:
    `queued` is pushes handed to the sender, `built` is pushes a dry run
    would send, `skipped_cap` is members past the cap, `skipped_quiet` those
    in quiet hours."""
    from database import api_tx
    from smtp import guard
    if campaign not in CAMPAIGNS:
        raise KeyError(campaign)
    now = now or _now()
    with api_tx('read committed') as tx:
        rows = audience(tx, campaign, campaign_id)
    built = skipped_cap = skipped_quiet = already = 0
    claimed: list[dict] = []
    failed_email = error = None
    with guard.dry_run(not send):
        if not send:
            _dry_run_probe()
        for r in rows:
            if _quiet(r, now):
                skipped_quiet += 1
                continue
            if built >= cap:
                skipped_cap += 1
                continue
            if not send:
                built += 1
                continue
            log_id = _log_id(campaign, r, campaign_id)
            try:
                with api_tx() as tx:
                    if not _claim(tx, r['person_id'], campaign, log_id):
                        already += 1
                        continue
                    push = _build(tx, campaign, r)
                    if push is None:
                        # No activated person for the card link: roll the
                        # claim back with the transaction.
                        raise ValueError('no_person')
            except ValueError as e:
                error, failed_email = str(e), mask_email(r['email'])
                continue
            built += 1
            claimed.append(dict(person_id=r['person_id'], campaign=campaign, log_id=log_id, push=push))
    if claimed:
        _deliver_later(claimed)
    res = dict(queued=len(claimed), built=built, skipped_cap=skipped_cap, skipped_quiet=skipped_quiet,
               skipped_already=already, skipped_suppressed=0, skipped_unsubscribed=0,
               dry_run=not send, campaign_id=campaign_id, channel='push',
               error=error, failed_email=failed_email)
    print('SPOTLIGHT_PUSH_RUN ' + json.dumps(dict(campaign=campaign, **res)), flush=True)
    return res


def preview(campaign: str, to_email: str) -> Optional[str]:
    """Push the sample to the member with this address (the admin pressing
    Preview). Nothing is logged. None when it went, else why not."""
    from database import api_tx
    if campaign not in CAMPAIGNS:
        raise KeyError(campaign)
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT p.id FROM person p
                WHERE lower(p.email) = lower(%(e)s) AND p.activated
                  AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id)""",
            dict(e=to_email.strip())).fetchone()
    if row is None:
        return 'no_push_subscription'
    push = opt_in_push() if campaign == OPT_IN else card_push('/')
    return None if _push_one(row['id'], push, f'{campaign}_preview') else 'not_delivered'


# ---------------------------------------------------------------------------
# The card push that goes with a new card-ready email
# ---------------------------------------------------------------------------

_PENDING: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar('spotlight_card_pushes', default=None)


@contextmanager
def collect_card_pushes():
    """Wrap a request's transaction: the card pushes it decides go once it
    has committed, and none goes if it raises. Put it OUTSIDE api_tx:
    `with collect_card_pushes(), api_tx() as tx:`."""
    pending: list = []
    token = _PENDING.set(pending)
    try:
        yield
    except BaseException:
        pending.clear()
        raise
    finally:
        _PENDING.reset(token)
    if pending:
        _deliver_later(list(pending))


def queue_card_ready_push(tx, request_key: str) -> bool:
    """In the transaction that queued a new card-ready email: log the card
    push for the current revision and hand it to the collecting block. Not
    outside such a block, in quiet hours or a rest period: then nothing is
    logged and the Growth row's Send can push it later."""
    if not enabled('spotlight_card_push'):
        return False
    pending = _PENDING.get()
    if pending is None:
        return False
    # Everything from here runs inside a savepoint. The email matters more
    # than its push: nothing the push does, a failed query included, may
    # roll back the render or the drain that queued the email.
    tx.execute('SAVEPOINT card_push')
    try:
        item = _card_push_item(tx, request_key)
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT card_push')
        print(traceback.format_exc())
        return False
    tx.execute('RELEASE SAVEPOINT card_push')
    if item is None:
        return False
    pending.append(item)
    return True


def _card_push_item(tx, request_key: str) -> Optional[dict]:
    """Claim and build the card push for this request, or None when it is
    not to go now. Raises to the savepoint in queue_card_ready_push."""
    now = _now()
    if resting(now):
        return None
    rows = audience(tx, CARD, request_key=request_key)
    if not rows or _quiet(rows[0], now):
        return None
    r = rows[0]
    if not _claim(tx, r['person_id'], CARD, r['log_id']):
        return None
    push = _build(tx, CARD, r)
    if push is None:
        raise ValueError('no_person')
    return dict(person_id=r['person_id'], campaign=CARD, log_id=r['log_id'], push=push)


# ---------------------------------------------------------------------------
# The Growth table
# ---------------------------------------------------------------------------

_Q_LAST = """
    SELECT max(sent_at) AS at,
           (array_agg(campaign_id ORDER BY sent_at DESC))[1] AS cid,
           count(DISTINCT person_id)::int AS people,
           count(*)::int AS n
      FROM push_send_log WHERE campaign = %(c)s
"""

_Q_RUN = """
    SELECT count(*)::int AS reached,
           count(*) FILTER (WHERE p.last_online_time > l.sent_at)::int AS came_back
      FROM push_send_log l JOIN person p ON p.id = l.person_id
     WHERE l.campaign = %(c)s AND l.campaign_id = %(cid)s
"""

_Q_HANDED = """
    SELECT COALESCE(sum((metadata->>'queued')::int), 0)::int AS n FROM admin_audit_log
     WHERE action = %(action)s AND metadata->>'campaign' = %(c)s AND metadata->>'campaign_id' = %(cid)s
       AND COALESCE((metadata->>'dry_run')::boolean, FALSE) = FALSE
"""


def index_row(tx, campaign: str, now: datetime, next_id: str) -> dict:
    """The row the Growth tab's Emails table shows, in the email rows'
    shape. Reached is pushes logged (a push no device took gives its row
    back); clicks are not measured."""
    everyone = audience(tx, campaign)
    left = everyone if campaign == CARD else audience(tx, campaign, next_id)
    reach = min(PUSH_CAP, sum(1 for r in left if not _quiet(r, now)))
    last = tx.execute(_Q_LAST, dict(c=campaign)).fetchone()
    reached = came_back = None
    if campaign == OPT_IN and last['cid']:
        run = tx.execute(_Q_RUN, dict(c=campaign, cid=last['cid'])).fetchone()
        reached, came_back = run['reached'], run['came_back']
    return dict(campaign=campaign, channel='push', recipients=len(everyone),
                eligible_now=len(everyone), would_reach_now=reach,
                last_run_reached=reached, last_run_clicks=None,
                last_run_came_back=came_back, last_run_came_back_7d=None,
                last_run_push_turned_on=None, came_back=None,
                people_reached=last['people'],
                last_sent_at=last['at'].isoformat() if last['at'] else None,
                last_campaign_id=last['cid'], system=False, schedule=None)


def status(tx, campaign: str, campaign_id: str) -> dict:
    """What the row shows after a Send. `queued` is pushes the run handed
    to the sender (from its audit row). `accepted` is the opt-in run's rows
    still logged, which drops as pushes no device took give theirs back; a
    card push is logged per card, not per run, so it repeats `queued`."""
    from service.campaigns.runner import SEND_AUDIT_ACTION
    handed = tx.execute(_Q_HANDED, dict(action=SEND_AUDIT_ACTION, c=campaign, cid=campaign_id)).fetchone()['n']
    if campaign == OPT_IN:
        accepted = tx.execute(_Q_RUN, dict(c=campaign, cid=campaign_id)).fetchone()['reached']
    else:
        accepted = handed
    return dict(campaign=campaign, campaign_id=campaign_id, queued=handed, accepted=accepted,
                acceptance_unknown=0, failed=0, skipped=0, reserved=0)


_Q_RUNS = """
    SELECT l.campaign_id, min(l.sent_at) AS sent_at, count(*)::int AS reached,
           count(*) FILTER (WHERE p.last_online_time > l.sent_at)::int AS came_back
      FROM push_send_log l JOIN person p ON p.id = l.person_id
     WHERE l.campaign = %(c)s
     GROUP BY l.campaign_id
     ORDER BY min(l.sent_at) DESC
     LIMIT %(lim)s
"""

_Q_LAST_30 = """
    WITH s AS (
        SELECT l.person_id, min(l.sent_at) AS first_at, count(*) AS n
          FROM push_send_log l
         WHERE l.campaign = %(c)s AND l.sent_at > NOW() - INTERVAL '30 days'
         GROUP BY l.person_id
    )
    SELECT COALESCE(sum(s.n), 0)::int AS sends,
           count(*)::int AS people,
           count(*) FILTER (WHERE p.last_online_time > s.first_at)::int AS came_back
      FROM s JOIN person p ON p.id = s.person_id
"""


def run_history(tx, campaign: str, limit: int = 12) -> list[dict]:
    """The email rows' run history shape. A card push's "run" is one card
    revision."""
    return [dict(campaign_id=r['campaign_id'], sent_at=r['sent_at'].isoformat(),
                 started_by=None, reached=r['reached'], clicks=None,
                 came_back=r['came_back'], came_back_7d=None)
            for r in tx.execute(_Q_RUNS, dict(c=campaign, lim=limit)).fetchall()]


def last_30_days(tx, campaign: str) -> dict:
    return dict(tx.execute(_Q_LAST_30, dict(c=campaign)).fetchone())

