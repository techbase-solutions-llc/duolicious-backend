"""What each email achieved (TEC-1897; frames G.1, G.2 and G.4).

"Came back counts anyone online since the send. The email may not have
caused it." A recipient came back when person.last_online_time is later
than their send. Within 7 days reads member_online_day (migration 0075),
which starts on its deploy day, so a run sent before the record began has
no 7 day figure. Push turned on is the notifications email's own measure.
"""
from __future__ import annotations

from typing import Optional

from service.campaigns.runner import SEND_AUDIT_ACTION

PUSH_CAMPAIGN = 'e6'

# What one run achieved. `reached` is the members its mail was accepted for
# (the drain writes the send log on acceptance). `clicks` counts clicks on
# the /s/ links that run's own mail carried, found in the outbox payload,
# with bots left out as service.growth.queries.post_stats leaves them out.
# A campaign mints its CTA links under its own key as the link kind and with
# the recipient as the link's subject (each module's build_for), so each
# outbox row is only searched for its own member's few links. Matching on
# kind alone searched every link the campaign ever minted in every mail of
# the run, about 53 more e2 links a week. `links` is 0 when the mail carried
# no tracked link (an e1 run before 13 Oct 2026, when its confirm link was
# bare, or a run from before the outbox), and
# then there is no click figure to give.
Q_RUN_RESULTS = """
    WITH run_links AS (
        SELECT DISTINCT l.key
          FROM email_outbox o
          JOIN campaign_link l
            ON l.kind = o.campaign
           AND l.subject_person_id = o.person_id
           AND strpos(o.payload->>'html', '/s/' || l.key) > 0
         WHERE o.campaign = %(c)s AND o.campaign_id = %(cid)s
    )
    SELECT (SELECT count(*) FROM email_send_log
             WHERE campaign = %(c)s AND campaign_id = %(cid)s) AS reached,
           (SELECT count(*) FROM run_links) AS links,
           (SELECT count(*) FROM campaign_click c JOIN run_links r ON r.key = c.link_key
             WHERE c.ua_class <> 'bot') AS clicks
"""


def run_results(tx, campaign: str, campaign_id: str | None) -> tuple[int | None, int | None]:
    if not campaign_id:
        return None, None
    r = tx.execute(Q_RUN_RESULTS, dict(c=campaign, cid=campaign_id)).fetchone()
    return int(r['reached']), (int(r['clicks']) if r['links'] else None)


_Q_RUN_OUTCOMES = """
    SELECT count(*) FILTER (WHERE p.last_online_time > l.sent_at)::int AS came_back,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM member_online_day d
                WHERE d.person_id = l.person_id
                  AND d.last_at > l.sent_at
                  AND d.first_at < l.sent_at + INTERVAL '7 days'))::int AS came_back_7d,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM push_subscription ps
                WHERE ps.person_id = l.person_id AND ps.created_at > l.sent_at))::int AS push_turned_on,
           min(l.sent_at) AS first_sent_at,
           (SELECT min(first_at) FROM member_online_day) AS recording_since
      FROM email_send_log l
      JOIN person p ON p.id = l.person_id
     WHERE l.campaign = %(c)s AND l.campaign_id = %(cid)s
"""

_Q_STARTED_BY = """
    SELECT actor_email FROM admin_audit_log
     WHERE action = %(action)s
       AND metadata->>'campaign' = %(c)s
       AND metadata->>'campaign_id' = %(cid)s
       AND COALESCE((metadata->>'dry_run')::boolean, FALSE) = FALSE
     ORDER BY created_at
     LIMIT 1
"""

_Q_RUNS = """
    SELECT campaign_id, min(sent_at) AS sent_at, count(*)::int AS reached
      FROM email_send_log
     WHERE campaign = %(c)s
     GROUP BY campaign_id
     ORDER BY min(sent_at) DESC
     LIMIT %(lim)s
"""

_Q_LAST_30 = """
    WITH s AS (
        SELECT l.person_id, min(l.sent_at) AS first_at, count(*) AS n
          FROM email_send_log l
         WHERE l.campaign = %(c)s AND l.sent_at > NOW() - INTERVAL '30 days'
         GROUP BY l.person_id
    )
    SELECT COALESCE(sum(s.n), 0)::int AS sends,
           count(*)::int AS people,
           count(*) FILTER (WHERE p.last_online_time > s.first_at)::int AS came_back
      FROM s JOIN person p ON p.id = s.person_id
"""

_Q_CAME_BACK_ALL = """
    SELECT count(*)::int AS n
      FROM (SELECT l.person_id, min(l.sent_at) AS first_at
              FROM email_send_log l WHERE l.campaign = %(c)s GROUP BY l.person_id) s
      JOIN person p ON p.id = s.person_id
     WHERE p.last_online_time > s.first_at
"""


def run_outcomes(tx, campaign: str, campaign_id: Optional[str]) -> dict:
    if not campaign_id:
        return dict(came_back=None, came_back_7d=None, push_turned_on=None)
    r = tx.execute(_Q_RUN_OUTCOMES, dict(c=campaign, cid=campaign_id)).fetchone()
    measured_7d = (r['recording_since'] is not None and r['first_sent_at'] is not None
                   and r['recording_since'] <= r['first_sent_at'])
    return dict(came_back=r['came_back'],
                came_back_7d=r['came_back_7d'] if measured_7d else None,
                push_turned_on=r['push_turned_on'] if campaign == PUSH_CAMPAIGN else None)


def started_by(actor_email: Optional[str]) -> Optional[str]:
    if actor_email is None:
        return None
    return {'cron': 'schedule', 'cli': 'command_line'}.get(actor_email, 'send_button')


def run_history(tx, campaign: str, limit: int = 12) -> list[dict]:
    out = []
    for r in tx.execute(_Q_RUNS, dict(c=campaign, lim=limit)).fetchall():
        cid = r['campaign_id']
        _, clicks = run_results(tx, campaign, cid)
        o = run_outcomes(tx, campaign, cid)
        actor = tx.execute(_Q_STARTED_BY, dict(action=SEND_AUDIT_ACTION, c=campaign, cid=cid)).fetchone()
        out.append(dict(campaign_id=cid, sent_at=r['sent_at'].isoformat(),
                        started_by=started_by(actor['actor_email'] if actor else None),
                        reached=r['reached'], clicks=clicks,
                        came_back=o['came_back'], came_back_7d=o['came_back_7d']))
    return out


def last_30_days(tx, campaign: str) -> dict:
    return dict(tx.execute(_Q_LAST_30, dict(c=campaign)).fetchone())


def came_back_all_time(tx, campaign: str) -> int:
    return tx.execute(_Q_CAME_BACK_ALL, dict(c=campaign)).fetchone()['n']
