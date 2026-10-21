"""Suggest two people (TEC-1845, 5b and 5c).

A member suggests two members they can already see (owner decision 6,
option B: their matches, likes either way, members who viewed them, members
on their map and members in a published Spotlight post in the last 8
weeks). "Nobody browses anyone they could not already see as a member."
Each of the two is told privately; they are matched only when both accept,
and nobody is ever told of a no.

Refusals the introducer could learn from (the two are blocked, unmatched or
already matched with each other, one has an open introduction to the
other, one prefers not to be matched with members who share conversations
while the other shares one, or they do not look for each other) answer
exactly as a send. Like a send they count against the week and mark both
as suggested before, so neither the allowance nor a second try says
anything: each is kept as a 'rejected' row with flag_reason 'hidden' and no
note, which no member and no count ever sees.

Limits: 5 pairs a week per introducer (the week from Monday 00:00 UTC) and
each person once ever per introducer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from service.admin.queries.members import member_sql
from service.matchmaker import MatchmakerError, first_name, is_uuid

WEEKLY_LIMIT = 5
OPEN_FOR = timedelta(days=14)

REACH = ('match', 'liked', 'liked_you', 'viewed_you', 'map', 'spotlight')
REACH_LABELS = {
    'match': 'Your match',  # NEW LINE
    'liked': 'You liked them',  # NEW LINE
    'liked_you': 'Liked you',  # NEW LINE
    'viewed_you': 'Viewed your profile',
    'map': 'On the map',
    'spotlight': 'In the weekly Spotlight',
}
SPOTLIGHT_WEEKS = 8


def _reach_sql(intro: str) -> dict[str, str]:
    """Each way the introducer can already see the member p, as SQL."""
    return {
        'match': f"""EXISTS (SELECT 1 FROM ahavah_match m
                      WHERE m.user_a_id = LEAST({intro}, p.id) AND m.user_b_id = GREATEST({intro}, p.id))""",
        'liked': f'EXISTS (SELECT 1 FROM liked l WHERE l.liker_id = {intro} AND l.liked_id = p.id)',
        'liked_you': f'EXISTS (SELECT 1 FROM liked l WHERE l.liker_id = p.id AND l.liked_id = {intro})',
        'viewed_you': f'EXISTS (SELECT 1 FROM profile_view v WHERE v.viewer_id = p.id AND v.viewed_id = {intro})',
        # The map's own predicates (service/search/sql Q_MAP_MARKERS): the
        # introducer's genders, a real city, an approved photo.
        'map': f"""(NOT p.verification_required
                    AND (NOT EXISTS (SELECT 1 FROM search_preference_gender g WHERE g.person_id = {intro})
                         OR p.gender_id IN (SELECT g.gender_id FROM search_preference_gender g
                                             WHERE g.person_id = {intro}))
                    AND p.show_my_location
                    AND COALESCE((p.ahavah_extra->>'showOnMap')::boolean, TRUE)
                    AND COALESCE((p.ahavah_extra->>'citySet')::boolean, FALSE)
                    AND EXISTS (SELECT 1 FROM photo ph WHERE ph.person_id = p.id
                                  AND ph.moderation_status = 'approved'))""",
        'spotlight': f"""(p.spotlight_opt_in AND EXISTS (
                          SELECT 1 FROM publishing_queue q
                           WHERE q.subject_person_id = p.id AND q.status = 'published'
                             AND COALESCE(q.scheduled_for, q.updated_at)
                                 > NOW() - make_interval(weeks => {SPOTLIGHT_WEEKS})))""",
    }


def visible_sql(intro: str) -> str:
    """A boolean on the person row aliased p: someone the introducer
    (`intro`, an SQL expression for their id) can already see."""
    ways = ' OR '.join(f'({s})' for s in _reach_sql(intro).values())
    return f"""(
      p.activated AND {member_sql('p')} AND NOT p.hide_me_from_strangers
      AND p.id <> {intro}
      AND NOT is_blocked_pair({intro}, p.id)
      AND ({ways})
  )"""


def reach_case_sql(intro: str) -> str:
    whens = ' '.join(f"WHEN {s} THEN '{k}'" for k, s in _reach_sql(intro).items())
    return f'(CASE {whens} END)'


def _week_used(tx, introducer_id: int, now: datetime) -> int:
    from service.matchmaker.recommend import week_start
    return int(tx.execute(
        'SELECT count(*) AS n FROM introduction WHERE introducer_person_id = %(i)s AND created_at >= %(w)s',
        dict(i=introducer_id, w=week_start(now))).fetchone()['n'])


def allowance(tx, introducer_id: int, now: Optional[datetime] = None) -> dict:
    from service.matchmaker.recommend import next_week_day
    now = now or datetime.now(timezone.utc)
    return dict(left=max(0, WEEKLY_LIMIT - _week_used(tx, introducer_id, now)), **{'from': next_week_day()})


def _visible_person(tx, introducer_id: int, uuid: str) -> dict:
    """The member by uuid when the introducer can see them; 404 otherwise,
    the same answer as an unknown uuid."""
    if not is_uuid(uuid):
        raise MatchmakerError('not_found', 404)
    row = tx.execute(
        f"""SELECT p.id, p.uuid::text AS uuid, p.name, p.gender_id FROM person p
             WHERE p.uuid = %(u)s::uuid AND {visible_sql('%(me)s')}""",
        dict(u=uuid, me=introducer_id)).fetchone()
    if row is None:
        raise MatchmakerError('not_found', 404)
    return dict(row)


def _escape_like(q: str) -> str:
    return q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


_Q_CANDIDATES = """
    SELECT p.id, p.uuid::text AS uuid, p.name,
           (SELECT EXTRACT(YEAR FROM AGE(p.date_of_birth))::int WHERE p.show_my_age) AS age,
           (SELECT p.location_short_friendly WHERE p.show_my_location) AS place,
           (SELECT ph.uuid FROM photo ph
             WHERE ph.person_id = p.id AND ph.moderation_status = 'approved'
               AND (NOT %(photo_gate)s::boolean OR photos_visible_to(%(me)s, p.id))
             ORDER BY ph.position LIMIT 1) AS photo_uuid,
           {reach} AS reach,
           EXISTS (SELECT 1 FROM introduction i WHERE i.introducer_person_id = %(me)s
                     AND p.id IN (i.a_person_id, i.b_person_id)) AS suggested_before
      FROM person p
     WHERE {visible}
       AND p.id <> %(for)s
       -- Someone the first person could be looking for, who could be
       -- looking for them; an unset preference is open.
       AND (NOT EXISTS (SELECT 1 FROM search_preference_gender g WHERE g.person_id = %(for)s)
            OR p.gender_id IN (SELECT g.gender_id FROM search_preference_gender g WHERE g.person_id = %(for)s))
       AND (NOT EXISTS (SELECT 1 FROM search_preference_gender g WHERE g.person_id = p.id)
            OR %(for_gender)s IN (SELECT g.gender_id FROM search_preference_gender g WHERE g.person_id = p.id))
       AND NOT EXISTS (SELECT 1 FROM ahavah_match m
                        WHERE m.user_a_id = LEAST(%(for)s, p.id) AND m.user_b_id = GREATEST(%(for)s, p.id))
       AND NOT is_unmatched_pair(%(for)s, p.id)
       AND (%(q)s = '' OR p.name ILIKE %(q)s || '%%')
     ORDER BY p.name, p.id
     LIMIT %(limit)s
"""


def candidates(tx, introducer_id: int, for_uuid: str, q: str = '', limit: int = 20,
               now: Optional[datetime] = None) -> dict:
    """5b.2: whom the introducer could suggest for the first person."""
    from service.photo_gate import gate_params
    who = _visible_person(tx, introducer_id, for_uuid)
    sql = _Q_CANDIDATES.format(reach=reach_case_sql('%(me)s'), visible=visible_sql('%(me)s'))
    rows = tx.execute(sql, dict(me=introducer_id, **{'for': who['id']}, for_gender=who['gender_id'],
                                q=_escape_like((q or '').strip()[:40]),
                                limit=max(1, min(int(limit), 50)), **gate_params())).fetchall()
    people = []
    for r in rows:
        person = dict(uuid=r['uuid'], first_name=first_name(r['name']), age=r['age'], place=r['place'],
                      reach=r['reach'], reach_label=REACH_LABELS.get(r['reach']),
                      suggested_before=bool(r['suggested_before']))
        if r['photo_uuid']:
            person['photo_uuid'] = r['photo_uuid']
        people.append(person)
    return {'for': dict(first_name=first_name(who['name'])), 'people': people,
            'left': allowance(tx, introducer_id, now)['left']}


def _hidden_refusal(tx, a: dict, b: dict, now: datetime) -> bool:
    """True when the two must not be introduced, for a reason the
    introducer may not learn."""
    row = tx.execute(
        """SELECT is_blocked_pair(%(a)s, %(b)s) AS blocked,
                  EXISTS (SELECT 1 FROM ahavah_match m
                           WHERE m.user_a_id = LEAST(%(a)s::int, %(b)s::int)
                             AND m.user_b_id = GREATEST(%(a)s::int, %(b)s::int)) AS matched,
                  EXISTS (SELECT 1 FROM introduction i
                           WHERE i.status IN ('open', 'held')
                             AND ((i.a_person_id = %(a)s AND i.b_person_id = %(b)s)
                               OR (i.a_person_id = %(b)s AND i.b_person_id = %(a)s))) AS open_intro,
                  ((SELECT no_mentor_shared_matches FROM person WHERE id = %(a)s)
                     AND EXISTS (SELECT 1 FROM shared_conversation s
                                  WHERE s.single_person_id = %(b)s AND s.revoked_at IS NULL))
                  OR ((SELECT no_mentor_shared_matches FROM person WHERE id = %(b)s)
                     AND EXISTS (SELECT 1 FROM shared_conversation s
                                  WHERE s.single_person_id = %(a)s AND s.revoked_at IS NULL)) AS mentor_pref,
                  ((NOT EXISTS (SELECT 1 FROM search_preference_gender g WHERE g.person_id = %(a)s)
                    OR %(bg)s IN (SELECT g.gender_id FROM search_preference_gender g WHERE g.person_id = %(a)s))
                   AND (NOT EXISTS (SELECT 1 FROM search_preference_gender g WHERE g.person_id = %(b)s)
                    OR %(ag)s IN (SELECT g.gender_id FROM search_preference_gender g WHERE g.person_id = %(b)s)))
                  AS could_fit""",
        dict(a=a['id'], b=b['id'], ag=a['gender_id'], bg=b['gender_id'])).fetchone()
    return bool(row['blocked'] or row['matched'] or row['open_intro'] or row['mentor_pref']
                or not row['could_fit'])


def suggest(tx, introducer_id: int, a_uuid: str, b_uuid: str, note: str,
            now: Optional[datetime] = None) -> dict:
    """5b.8: {state: 'sent' | 'held', left}."""
    from service.matchmaker.recommend import clean_note, next_week_day, note_flag
    now = now or datetime.now(timezone.utc)
    text = clean_note(note)
    # Read committed (the route's): after the lock, the count sees what the
    # introducer's other request just committed.
    tx.execute("SELECT pg_advisory_xact_lock(hashtext('mm-intro:' || %(i)s::text))", dict(i=introducer_id))
    a = _visible_person(tx, introducer_id, a_uuid)
    b = _visible_person(tx, introducer_id, b_uuid)
    if a['id'] == b['id']:
        raise MatchmakerError('bad_pair', 400)
    if _week_used(tx, introducer_id, now) >= WEEKLY_LIMIT:
        raise MatchmakerError('limit', 429, {'from': next_week_day()})
    if tx.execute("""SELECT 1 FROM introduction WHERE introducer_person_id = %(i)s
                       AND (a_person_id IN (%(a)s, %(b)s) OR b_person_id IN (%(a)s, %(b)s)) LIMIT 1""",
                  dict(i=introducer_id, a=a['id'], b=b['id'])).fetchone():
        raise MatchmakerError('suggested_before', 409)
    base = dict(i=introducer_id, a=a['id'], b=b['id'], closes=now + OPEN_FOR)
    if _hidden_refusal(tx, a, b, now):
        tx.execute("""INSERT INTO introduction (introducer_person_id, a_person_id, b_person_id, status,
                                                flag_reason, closes_at)
                      VALUES (%(i)s, %(a)s, %(b)s, 'rejected', 'hidden', %(now)s)""", dict(base, now=now))
        return dict(state='sent', left=allowance(tx, introducer_id, now)['left'])
    flag = note_flag(text)
    iid = tx.execute(
        """INSERT INTO introduction (introducer_person_id, a_person_id, b_person_id, note, status,
                                     flag_reason, closes_at, opened_at)
           VALUES (%(i)s, %(a)s, %(b)s, %(n)s, %(st)s, %(f)s, %(closes)s,
                   CASE WHEN %(st)s = 'open' THEN %(now)s::timestamptz END)
           RETURNING id""",
        dict(base, n=text, st='held' if flag else 'open', f=flag, now=now)).fetchone()['id']
    if not flag:
        notify_both(tx, iid)
    return dict(state='held' if flag else 'sent', left=allowance(tx, introducer_id, now)['left'])


def _email_matches_on(tx, person_id: int) -> bool:
    row = tx.execute('SELECT email_matches FROM notification_preference WHERE person_id = %(p)s',
                     dict(p=person_id)).fetchone()
    return True if row is None else bool(row['email_matches'])


def notify_both(tx, intro_id: int) -> None:
    """Tell each of the two, privately: a push (their Matches push setting)
    and an email (their Matches email setting). The note stays in the app."""
    from service.matchmaker import mail
    row = tx.execute(
        """SELECT i.id, i.a_person_id, i.b_person_id, ip.name AS introducer, ap.name AS a_name,
                  bp.name AS b_name, ap.email AS a_email, bp.email AS b_email
             FROM introduction i
             JOIN person ip ON ip.id = i.introducer_person_id
             JOIN person ap ON ap.id = i.a_person_id
             JOIN person bp ON bp.id = i.b_person_id
            WHERE i.id = %(i)s AND i.status = 'open'""", dict(i=intro_id)).fetchone()
    if row is None:
        return
    introducer = first_name(row['introducer'])
    for side, pid, other, email in (('a', row['a_person_id'], row['b_name'], row['a_email']),
                                    ('b', row['b_person_id'], row['a_name'], row['b_email'])):
        other_first = first_name(other)
        mail.push_after_commit(pid, mail.intro_push(intro_id, introducer, other_first),
                               'matchmaker_intro_push', event_kind='match')
        if not _email_matches_on(tx, pid):
            continue
        subject, body = mail.intro_email(introducer, other_first, mail.intro_url(intro_id),
                                         mail.notifications_unsub_url(email))
        mail.guarded(tx, f'mm_intro_{side}', lambda: mail.queue_member(
            tx, campaign=mail.CAMPAIGN_INTRO, campaign_id=f'{intro_id}:{side}', person_id=pid,
            subject=subject, html_=body))


# ---------------------------------------------------------------------------
# The accept-or-decline card (5c)
# ---------------------------------------------------------------------------

def _closes_on(at: datetime) -> str:
    """5c.1's date: "30 October"."""
    d = at.astimezone(timezone.utc)
    return f'{d.day} {d:%B}'


_Q_CARDS = """
    SELECT i.id, i.note, i.closes_at, i.a_person_id, i.b_person_id, i.a_response, i.b_response,
           ip.name AS introducer_name,
           o.id AS other_id, o.uuid::text AS other_uuid, o.name AS other_name, o.about,
           (SELECT EXTRACT(YEAR FROM AGE(o.date_of_birth))::int WHERE o.show_my_age) AS age,
           (SELECT o.location_short_friendly WHERE o.show_my_location) AS place,
           COALESCE((SELECT json_agg(ph.uuid ORDER BY ph.position) FROM photo ph
                      WHERE ph.person_id = o.id AND ph.moderation_status = 'approved'
                        AND (NOT %(photo_gate)s::boolean OR photos_visible_to(%(me)s, o.id))),
                    '[]'::json)::jsonb AS photo_uuids
      FROM introduction i
      JOIN person ip ON ip.id = i.introducer_person_id
      JOIN person o ON o.id = CASE WHEN i.a_person_id = %(me)s THEN i.b_person_id ELSE i.a_person_id END
     WHERE i.status = 'open' AND i.closes_at > %(now)s
       AND %(me)s IN (i.a_person_id, i.b_person_id)
       AND o.activated
       AND NOT is_blocked_pair(%(me)s, o.id)
     ORDER BY i.opened_at DESC NULLS LAST, i.id DESC
"""


def _mine(row: dict, me: int) -> tuple[Optional[str], Optional[str]]:
    """(my answer, the other's answer)."""
    if row['a_person_id'] == me:
        return row['a_response'], row['b_response']
    return row['b_response'], row['a_response']


def pending(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    """{pending, waiting}: the open introductions the member has not
    answered (5c.1) and the ones they accepted that wait for the other
    person (5c.2). A viewer the photo gate holds gets no photos and the
    seed of the name gradient (owner decision 9)."""
    from service.photo_gate import gate_params
    now = now or datetime.now(timezone.utc)
    rows = tx.execute(_Q_CARDS, dict(me=person_id, now=now, **gate_params())).fetchall()
    out: dict = dict(pending=[], waiting=[])
    for r in rows:
        mine, _theirs = _mine(r, person_id)
        other_first = first_name(r['other_name'])
        if mine is None:
            other = dict(uuid=r['other_uuid'], first_name=other_first, place=r['place'],
                         photo_uuids=r['photo_uuids'], about=r['about'], gradient_seed=other_first)
            if r['age'] is not None:
                other['age'] = r['age']
            out['pending'].append(dict(id=r['id'], introducer_first_name=first_name(r['introducer_name']),
                                       other=other, note=r['note'], closes_on=_closes_on(r['closes_at'])))
        elif mine == 'accepted':
            out['waiting'].append(dict(id=r['id'], other_first_name=other_first,
                                       closes_on=_closes_on(r['closes_at'])))
    return out


def respond(tx, person_id: int, intro_id: int, answer: str, now: Optional[datetime] = None) -> dict:
    """Accept or not for me. Under the introduction's row lock, so two
    acceptances at once make one match. A no tells nobody."""
    from service.matchmaker import mail
    now = now or datetime.now(timezone.utc)
    if answer not in ('accept', 'decline'):
        raise MatchmakerError('bad_answer', 400)
    row = tx.execute('SELECT * FROM introduction WHERE id = %(i)s FOR UPDATE', dict(i=intro_id)).fetchone()
    if row is None or person_id not in (row['a_person_id'], row['b_person_id']) or row['status'] in ('held', 'rejected'):
        raise MatchmakerError('not_found', 404)
    side = 'a' if row['a_person_id'] == person_id else 'b'
    other_id = row['b_person_id'] if side == 'a' else row['a_person_id']
    mine, theirs = _mine(row, person_id)
    if row['status'] == 'matched' and mine == 'accepted':
        return _matched_answer(tx, person_id, other_id)
    if mine == 'declined':
        return dict(state='gone')
    blocked = tx.execute('SELECT is_blocked_pair(%(a)s, %(b)s) AS b', dict(a=person_id, b=other_id)).fetchone()['b']
    if row['status'] != 'open' or row['closes_at'] <= now or blocked:
        raise MatchmakerError('closed', 410)
    if mine == 'accepted' and answer == 'accept':
        return dict(state='waiting')
    if answer == 'decline':
        tx.execute(f"""UPDATE introduction SET {side}_response = 'declined', {side}_responded_at = %(now)s,
                              status = 'closed' WHERE id = %(i)s""", dict(now=now, i=intro_id))
        return dict(state='gone')
    tx.execute(f"""UPDATE introduction SET {side}_response = 'accepted', {side}_responded_at = %(now)s
                    WHERE id = %(i)s""", dict(now=now, i=intro_id))
    if theirs != 'accepted':
        return dict(state='waiting')
    # Both said yes: likes both ways and the match, in this transaction.
    tx.execute("""INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s), (%(b)s, %(a)s)
                  ON CONFLICT DO NOTHING""", dict(a=person_id, b=other_id))
    created = tx.execute(
        """INSERT INTO ahavah_match (user_a_id, user_b_id)
           VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))
           ON CONFLICT (user_a_id, user_b_id) DO NOTHING RETURNING match_id::text AS match_id""",
        dict(a=person_id, b=other_id)).fetchone()
    tx.execute("UPDATE introduction SET status = 'matched', matched_at = %(now)s WHERE id = %(i)s",
               dict(now=now, i=intro_id))
    answer_ = _matched_answer(tx, person_id, other_id)
    names = {r['id']: first_name(r['name']) for r in tx.execute(
        'SELECT id, name FROM person WHERE id IN (%(a)s, %(b)s, %(c)s)',
        dict(a=person_id, b=other_id, c=row['introducer_person_id'])).fetchall()}
    if created is not None:
        match_id = created['match_id']
        my_name = names.get(person_id, 'Someone')
        mail.after_commit(lambda: _match_notice(other_id, my_name, match_id))
    a_name, b_name = names.get(row['a_person_id'], 'Someone'), names.get(row['b_person_id'], 'Someone')
    mail.push_after_commit(row['introducer_person_id'], mail.introducer_push(intro_id, a_name, b_name),
                           'matchmaker_intro_push', event_kind='match')
    return answer_


def _matched_answer(tx, person_id: int, other_id: int) -> dict:
    m = tx.execute("""SELECT m.match_id::text AS match_id, p.uuid::text AS uuid FROM ahavah_match m
                        JOIN person p ON p.id = %(o)s
                       WHERE m.user_a_id = LEAST(%(a)s::int, %(o)s::int)
                         AND m.user_b_id = GREATEST(%(a)s::int, %(o)s::int)""",
                   dict(a=person_id, o=other_id)).fetchone()
    return dict(state='matched', match_id=m['match_id'] if m else None,
                other_uuid=m['uuid'] if m else None)


def _match_notice(person_id: int, other_first_name: str, match_id: str) -> None:
    """The usual match notice, to the one who accepted first. Its title has
    no exclamation mark, unlike the generic match push's."""
    from emails.notification import new_match_email
    from service.notifications import notify
    # NEW LINE: the title, waiting for /copy-pass.
    notify(person_id, 'match', title="It's a match", body=f'{other_first_name} likes you back',
           url='/matches', tag=f'match:{match_id}', email_subject='You have a new match on Ahavah',
           email_html_factory=new_match_email, email_event_id=f'match-{match_id}')


def close_lapsed(tx, now: datetime) -> int:
    """Open introductions past their date close, silently."""
    return tx.execute("UPDATE introduction SET status = 'closed' WHERE status = 'open' AND closes_at <= %(now)s",
                      dict(now=now)).rowcount


def told(tx, person_id: int) -> list[dict]:
    """5c.8: the matches this introducer has not been shown, marked shown."""
    rows = tx.execute(
        """UPDATE introduction i SET introducer_told_at = NOW()
             FROM person a, person b
            WHERE i.introducer_person_id = %(p)s AND i.status = 'matched' AND i.introducer_told_at IS NULL
              AND a.id = i.a_person_id AND b.id = i.b_person_id
        RETURNING i.id, a.name AS a_name, b.name AS b_name""", dict(p=person_id)).fetchall()
    return [dict(id=r['id'], a_first_name=first_name(r['a_name']), b_first_name=first_name(r['b_name']))
            for r in sorted(rows, key=lambda r: r['id'])]


def context(tx, person_id: int, other_uuid: str) -> Optional[dict]:
    """5c.7: the introducer and the note, for the top of the pair's chat."""
    if not is_uuid(other_uuid):
        return None
    row = tx.execute(
        """SELECT ip.name, i.note FROM introduction i
             JOIN person o ON o.uuid = %(u)s::uuid
             JOIN person ip ON ip.id = i.introducer_person_id
            WHERE i.status = 'matched' AND i.note_erased_at IS NULL AND i.note IS NOT NULL
              AND ((i.a_person_id = %(me)s AND i.b_person_id = o.id)
                OR (i.b_person_id = %(me)s AND i.a_person_id = o.id))
              AND NOT is_blocked_pair(%(me)s, o.id)
            ORDER BY i.matched_at DESC LIMIT 1""", dict(me=person_id, u=other_uuid)).fetchone()
    if row is None:
        return None
    return dict(introducer_first_name=first_name(row['name']), note=row['note'])
