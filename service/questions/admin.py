"""Admin > Questions (TEC-1845, spec "Screens" 7).

What the owner reads and changes:

  the bank      every question with its options and its counts split by sex
                (counts only, never who). He switches a question on or off
                and edits option wording; keys never change, because answers
                and the launch email's links are keyed on them. An open
                (text) question cannot be switched on in release 1.
  the schedule  the next SCHEDULE_WEEKS weeks, each with its drop day
                (service/questions/schedule.py) and question. An empty week
                ahead is offered the approved order (FIRST_WEEKS), then the
                rest of the bank. He fills, reorders and approves; changing
                an approved week's question takes its approval away. A week
                already under way is not changed here.
  pushes        sent, tapped and switched off, by question week. 2 or more
                switch-offs in a week is the guard rail: move to a
                fortnightly push.
  switches      their state; this tab never flips them.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

import service.spotlight.restdays as rd
from service.admin.queries.members import member_sql
from service.campaigns.switches import enabled
from service.questions.bank import CHOICE_FORMATS, LIVE, live_question
from service.questions.schedule import FIRST_WEEKS, barbados_today, drop_day, week_start

SWITCH_NAMES = ('question_push', 'match_question_push', 'e2_question_line',
                'questions_launch_email', 'questions_launch_push')
LABEL_MAX = 40
GUARD_RAIL_SWITCH_OFFS = 2
SCHEDULE_WEEKS = 6


class QuestionEditRefused(ValueError):
    """'unknown_question', 'not_a_choice_question' or 'bad_labels'."""


class ScheduleRefused(ValueError):
    """'not_a_drop_day', 'already_live', 'not_a_live_question' or
    'nothing_to_propose'."""


def switch_states() -> dict:
    return {name: enabled(name) for name in SWITCH_NAMES}


_Q_BANK = """
    SELECT key, text, category, format, options, active, sort
      FROM prompt_bank ORDER BY sort, key
"""

_Q_SPLIT = f"""
    SELECT a.prompt_key, a.choice_key, COALESCE(lower(g.name), 'unknown') AS sex, count(*) AS n
      FROM prompt_answer a
      JOIN person p ON p.id = a.person_id AND p.activated AND {member_sql('p')}
      LEFT JOIN gender g ON g.id = p.gender_id
     WHERE a.choice_key IS NOT NULL
     GROUP BY 1, 2, 3
"""


def bank_rows(tx) -> list[dict]:
    split: dict = {}
    for r in tx.execute(_Q_SPLIT).fetchall():
        split.setdefault((r['prompt_key'], r['choice_key']), {})[r['sex']] = int(r['n'])
    rows = []
    for b in tx.execute(_Q_BANK).fetchall():
        options = []
        for o in b['options']:
            by_sex = split.get((b['key'], o['key']), {})
            options.append(dict(key=o['key'], label=o['label'], n=sum(by_sex.values()), by_sex=by_sex))
        rows.append(dict(key=b['key'], text=b['text'], category=b['category'], format=b['format'],
                         active=b['active'], sort=b['sort'],
                         answers=sum(o['n'] for o in options), options=options))
    return rows


def update_question(tx, key: str, *, active: Optional[bool] = None,
                    labels: Optional[dict] = None) -> dict:
    row = tx.execute('SELECT key, format, options, active FROM prompt_bank WHERE key = %(k)s FOR UPDATE',
                     dict(k=key)).fetchone()
    if row is None:
        raise QuestionEditRefused('unknown_question')
    if active is True and row['format'] not in CHOICE_FORMATS:
        raise QuestionEditRefused('not_a_choice_question')
    options = [dict(key=o['key'], label=o['label']) for o in row['options']]
    if labels is not None:
        keys = {o['key'] for o in options}
        if not labels or set(labels) - keys:
            raise QuestionEditRefused('bad_labels')
        edited = []
        for o in options:
            label = labels.get(o['key'], o['label'])
            label = label.strip() if isinstance(label, str) else ''
            if not label or len(label) > LABEL_MAX or '\u2014' in label:
                raise QuestionEditRefused('bad_labels')
            edited.append(dict(key=o['key'], label=label))
        options = edited
    tx.execute("""UPDATE prompt_bank SET options = %(o)s::jsonb, active = COALESCE(%(a)s, active)
                   WHERE key = %(k)s""", dict(o=json.dumps(options), a=active, k=key))
    return dict(key=key, active=row['active'] if active is None else active, options=options)


_Q_LIVE_KEYS = f"SELECT b.key FROM prompt_bank b WHERE {LIVE} ORDER BY b.sort, b.key"
_Q_USED_KEYS = "SELECT DISTINCT prompt_key FROM question_drop"


def _proposal_queue(tx) -> list[str]:
    """The approved order first, then the rest of the bank, leaving out any
    question that has had a week."""
    live = [r['key'] for r in tx.execute(_Q_LIVE_KEYS).fetchall()]
    used = {r['prompt_key'] for r in tx.execute(_Q_USED_KEYS).fetchall()}
    first = [k for k in FIRST_WEEKS if k in live and k not in used]
    return first + [k for k in live if k not in used and k not in FIRST_WEEKS]


_Q_DROPS = """
    SELECT d.live_on, d.prompt_key, d.approved_at, b.text
      FROM question_drop d JOIN prompt_bank b ON b.key = d.prompt_key
     WHERE d.live_on >= %(a)s AND d.live_on < %(b)s
"""


def schedule_rows(tx, now: Optional[datetime] = None, weeks: int = SCHEDULE_WEEKS) -> list[dict]:
    today = barbados_today(now)
    first = week_start(today)
    drops = {r['live_on']: r for r in tx.execute(
        _Q_DROPS, dict(a=first, b=first + timedelta(weeks=weeks))).fetchall()}
    queue = _proposal_queue(tx)
    out = []
    for i in range(weeks):
        week_of = first + timedelta(weeks=i)
        day = drop_day(week_of)
        d = drops.get(day) if day else None
        proposed = queue.pop(0) if (day and d is None and day > today and queue) else None
        problem = None
        if day is None:
            problem = 'unknown' if week_of + timedelta(days=7) > rd.KNOWN_THROUGH else 'no_free_day'
        out.append(dict(week_of=week_of.isoformat(), live_on=day.isoformat() if day else None,
                        problem=problem, prompt_key=d['prompt_key'] if d else None,
                        text=d['text'] if d else None, approved=bool(d and d['approved_at']),
                        proposed_key=proposed))
    return out


def _check_day(day: date, now: Optional[datetime]) -> None:
    if drop_day(day) != day:
        raise ScheduleRefused('not_a_drop_day')
    if day <= barbados_today(now):
        raise ScheduleRefused('already_live')


_Q_SET_DROP = """
    INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, %(k)s)
    ON CONFLICT (live_on) DO UPDATE
       SET prompt_key = EXCLUDED.prompt_key,
           approved_at = CASE WHEN question_drop.prompt_key = EXCLUDED.prompt_key
                              THEN question_drop.approved_at END
"""


def set_drop(tx, day: date, key: str, now: Optional[datetime] = None) -> None:
    _check_day(day, now)
    if live_question(tx, key) is None:
        raise ScheduleRefused('not_a_live_question')
    tx.execute(_Q_SET_DROP, dict(d=day, k=key))


def clear_drop(tx, day: date, now: Optional[datetime] = None) -> None:
    _check_day(day, now)
    tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=day))


def approve(tx, days: list[date], now: Optional[datetime] = None) -> list[str]:
    """Approve each week, filling an empty one with the next proposal."""
    queue = _proposal_queue(tx)
    done = []
    for day in sorted(days):
        _check_day(day, now)
        if tx.execute('SELECT 1 FROM question_drop WHERE live_on = %(d)s', dict(d=day)).fetchone() is None:
            if not queue:
                raise ScheduleRefused('nothing_to_propose')
            tx.execute('INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, %(k)s)',
                       dict(d=day, k=queue.pop(0)))
        tx.execute('UPDATE question_drop SET approved_at = COALESCE(approved_at, NOW()) WHERE live_on = %(d)s',
                   dict(d=day))
        done.append(day.isoformat())
    return done


# A question week runs from 00:00 Barbados on its drop day to the next
# drop's, or 7 days when there is none yet. The launch push is also logged
# as that week's question push, so weekly_sent takes it back out.
_Q_PUSHES = """
    WITH w AS (
        SELECT live_on,
               live_on::timestamp AT TIME ZONE 'America/Barbados' AS starts,
               COALESCE(LEAD(live_on) OVER (ORDER BY live_on), live_on + 7)::timestamp
                   AT TIME ZONE 'America/Barbados' AS ends
          FROM question_drop WHERE approved_at IS NOT NULL
    )
    SELECT w.live_on,
           (SELECT count(*) FROM push_send_log l
             WHERE l.campaign = 'question' AND l.campaign_id = w.live_on::text) AS question_sent,
           (SELECT count(*) FROM push_send_log l WHERE l.campaign = 'questions_launch'
               AND l.sent_at >= w.starts AND l.sent_at < w.ends) AS launch_sent,
           (SELECT count(*) FROM push_send_log l WHERE l.campaign = 'match_question'
               AND l.sent_at >= w.starts AND l.sent_at < w.ends) AS match_question_sent,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'qpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS qpush,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'mpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS mpush,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'lpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS lpush,
           (SELECT count(*) FROM notification_preference np
             WHERE np.push_questions_off_at >= w.starts AND np.push_questions_off_at < w.ends) AS switched_off
      FROM w
     ORDER BY w.live_on DESC
     LIMIT %(n)s
"""


def push_rows(tx, weeks: int = 8) -> list[dict]:
    out = []
    for r in tx.execute(_Q_PUSHES, dict(n=weeks)).fetchall():
        launch = int(r['launch_sent'])
        off = int(r['switched_off'])
        out.append(dict(live_on=r['live_on'].isoformat(),
                        weekly_sent=int(r['question_sent']) - launch, launch_sent=launch,
                        match_question_sent=int(r['match_question_sent']),
                        taps=dict(qpush=int(r['qpush']), mpush=int(r['mpush']), lpush=int(r['lpush'])),
                        switched_off=off, guard_rail=off >= GUARD_RAIL_SWITCH_OFFS))
    return out
