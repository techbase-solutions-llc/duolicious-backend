"""Together on Admin > Growth (TEC-1845): counts only.

Spec: "Answers are only readable by the two players through their tokens,
and by no admin screen except as counts." The queries here read no answer,
display name or address. Deleted sessions are still counted until the
sweep removes them; the sweep's deletions lower the counts, which is the
cost of keeping nothing for longer than the privacy page says.
"""
from __future__ import annotations

MODES = ('me', 'us', 'knows_me', 'couple', 'single')
SOURCES = ('tool:game-me', 'tool:game-us', 'tool:knows-me', 'tool:checklist')

_Q_MODES = """
    SELECT s.mode,
           count(*) AS started,
           count(*) FILTER (WHERE s.completed_at IS NOT NULL) AS completed,
           count(*) FILTER (WHERE s.claimed_at IS NOT NULL) AS saved,
           count(*) FILTER (WHERE s.invite_token IS NOT NULL) AS links,
           COALESCE(sum(s.invite_emails), 0)::int AS invite_emails,
           count(*) FILTER (WHERE g.n > 0) AS joined,
           COALESCE(sum(g.n), 0)::int AS guests,
           COALESCE(sum(s.share_opens), 0)::int AS share_opens
      FROM tool_session s
      LEFT JOIN LATERAL (SELECT count(*) AS n FROM tool_player p
                          WHERE p.session_id = s.id AND p.seat = 'guest') g ON TRUE
     GROUP BY s.mode
"""

_Q_SIGNUPS = """
    SELECT lead_source AS source, count(*)::int AS n FROM person
     WHERE lead_source = ANY(%(src)s) GROUP BY lead_source
"""

_ZERO = dict(started=0, completed=0, saved=0, links=0, invite_emails=0, joined=0, guests=0,
             share_opens=0)


def tool_counts(tx) -> dict:
    by_mode = {r['mode']: {k: int(v) for k, v in dict(r).items() if k != 'mode'}
               for r in tx.execute(_Q_MODES).fetchall()}
    signups = {r['source']: r['n'] for r in tx.execute(_Q_SIGNUPS, dict(src=list(SOURCES))).fetchall()}
    return dict(modes=[dict(mode=m, **by_mode.get(m, _ZERO)) for m in MODES],
                signups={s: signups.get(s, 0) for s in SOURCES})
