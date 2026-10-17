"""Together sessions: play, save, share and delete (TEC-1845).

docs/superpowers/specs/2026-10-13-couple-tools-design.md and
docs/superpowers/plans/2026-10-17-together-release-1.md.

A session is one game (me, us, knows_me) or one checklist (couple,
single). Each player holds a token the device keeps; only its sha256 is
stored (service.leads.new_token). A player who saved may also come back
with a signed-in session for the address they saved with. Answers are
read only by the players, through their token or that session: the view
carries the player's own answers and, once both have finished a couple
checklist, the comparison the two of them share. No admin route reads
them (service/tools/admin.py counts only). The share token opens the
public summary, which never carries an answer.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid as _uuid
from typing import Any, Optional

from antiabuse.antispam.signupemail import normalize_email
from service.leads import new_token, token_hash
from service.tools import checklist, questions, results, scoring

SOURCE = {'me': 'tool:game-me', 'us': 'tool:game-us', 'knows_me': 'tool:knows-me',
          'couple': 'tool:checklist', 'single': 'tool:checklist'}
MODES = {'game': ('me', 'us', 'knows_me'), 'checklist': ('couple', 'single')}
TWO_PLAYER = ('us', 'couple')
WITH_INVITE = ('us', 'knows_me', 'couple')
MAX_ANSWERS = 60
KNOWS_ME_MAX_FRIENDS = 200
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')


class ToolError(Exception):
    """A refusal the route answers as {'error': reason} with its status."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def clean_display(value: object) -> str:
    """A first name or initials as a player chose to show it: spaces
    collapsed, 1 to 40 characters, no control characters and no angle
    brackets, since it reaches boards, share images and emails."""
    if not isinstance(value, str) or any(ord(c) < 32 or c in '<>' for c in value):
        raise ToolError('bad_display')
    text = ' '.join(value.split())
    if not 1 <= len(text) <= 40:
        raise ToolError('bad_display')
    return text


def new_link_token() -> str:
    """A share or invite token: 22 URL-safe characters, stored as it is so
    the owner can send it again."""
    return secrets.token_urlsafe(16)


_Q_START = """
    INSERT INTO tool_session (kind, mode, source, utm, owner_person_id, owner_email,
                              owner_normalized_email)
    VALUES (%(k)s, %(m)s, %(src)s, %(utm)s::jsonb, %(pid)s, %(e)s, %(ne)s)
    RETURNING id, uuid::text AS uuid
"""


def new_player(tx, session_pk: int, seat: str, **fields: Any) -> str:
    """Adds a player and returns its token. `fields` are tool_player
    columns named in code, never by a caller's input."""
    token, hashed = new_token()
    cols = dict(session_id=session_pk, seat=seat, token_hash=hashed, **fields)
    names = ', '.join(cols)
    values = ', '.join(f'%({c})s' for c in cols)
    tx.execute(f'INSERT INTO tool_player ({names}) VALUES ({values})', cols)
    return token


def start(tx, *, kind: str, mode: str, member=None, utm: Optional[dict] = None) -> dict:
    """A new session and its owner's token. `member` is the signed-in
    member's SessionInfo, or None for a visitor."""
    if mode not in MODES.get(kind, ()):
        raise ToolError('bad_mode')
    email = member.email if member is not None else None
    row = tx.execute(_Q_START, dict(
        k=kind, m=mode, src=SOURCE[mode], utm=json.dumps(utm) if utm else None,
        pid=member.person_id if member is not None else None, e=email,
        ne=normalize_email(email) if email else None)).fetchone()
    token = new_player(tx, row['id'], 'owner')
    return dict(session_id=row['uuid'], player_token=token)


_COLS = """s.id AS session_id, s.uuid::text AS session_uuid, s.kind, s.mode, s.source,
           s.deleted_at, s.claimed_at, s.completed_at, s.owner_display, s.owner_email,
           s.owner_person_id, s.owner_normalized_email, s.share_token, s.invite_token,
           p.id AS player_id, p.seat, p.role, p.display, p.email, p.person_id,
           p.normalized_email, p.finished_at, p.removed_at"""

_Q_BY_TOKEN = f"""
    SELECT {_COLS} FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.uuid = %(sid)s::uuid AND p.token_hash = %(h)s
"""

# A saved seat, for a signed-in session of the same address or account.
_Q_BY_ACCOUNT = f"""
    SELECT {_COLS} FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.uuid = %(sid)s::uuid
       AND ((p.seat = 'owner'
             AND ((%(pid)s::int IS NOT NULL AND s.owner_person_id = %(pid)s)
                  OR (s.claimed_at IS NOT NULL AND s.owner_normalized_email = %(ne)s)))
         OR (p.seat = 'guest' AND p.removed_at IS NULL
             AND ((%(pid)s::int IS NOT NULL AND p.person_id = %(pid)s)
                  OR p.normalized_email = %(ne)s)))
     ORDER BY (p.seat = 'owner') DESC, p.id
     LIMIT 1
"""


def _session_uuid(value: object) -> str:
    try:
        return str(_uuid.UUID(str(value)))
    except ValueError:
        raise ToolError('not_found', 404)


def player_for(tx, session_id: object, token: Optional[str], s=None) -> dict:
    sid = _session_uuid(session_id)
    row = None
    if isinstance(token, str) and _TOKEN_RE.match(token):
        row = tx.execute(_Q_BY_TOKEN, dict(sid=sid, h=token_hash(token))).fetchone()
    if row is None and s is not None and s.signed_in:
        row = tx.execute(_Q_BY_ACCOUNT, dict(sid=sid, pid=s.person_id,
                                             ne=normalize_email(s.email))).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    tx.execute('UPDATE tool_session SET last_visit_at = NOW() WHERE id = %(i)s',
               dict(i=row['session_id']))
    return dict(row)


_Q_ANSWERS = 'SELECT question_key, answer FROM tool_answer WHERE player_id = %(p)s'

_Q_UPSERT_ANSWER = """
    INSERT INTO tool_answer (session_id, player_id, question_key, answer)
    VALUES (%(s)s, %(p)s, %(k)s, %(a)s::jsonb)
    ON CONFLICT (player_id, question_key) DO UPDATE
       SET answer = EXCLUDED.answer, answered_at = NOW()
"""


def answers_of(tx, player_id: int) -> dict:
    return {r['question_key']: r['answer']
            for r in tx.execute(_Q_ANSWERS, dict(p=player_id)).fetchall()}


def save_answers(tx, player: dict, answers: list[dict], role: Optional[str] = None) -> int:
    """Saves or removes each answer; an answer of None removes it ("Skip
    this one"). Refused once the player has finished."""
    if player['finished_at'] is not None:
        raise ToolError('finished', 409)
    if player['kind'] == 'checklist' and role is not None:
        tx.execute('UPDATE tool_player SET role = %(r)s WHERE id = %(p)s',
                   dict(r=role, p=player['player_id']))
        player['role'] = role
    saved = 0
    for item in answers:
        key, raw = item['question_key'], item.get('answer')
        if raw is None:
            tx.execute('DELETE FROM tool_answer WHERE player_id = %(p)s AND question_key = %(k)s',
                       dict(p=player['player_id'], k=key))
            continue
        try:
            clean = (questions.clean_game_answer(key, raw) if player['kind'] == 'game'
                     else checklist.clean_checklist_answer(key, raw, player['role']))
        except ValueError as e:
            raise ToolError(str(e))
        tx.execute(_Q_UPSERT_ANSWER, dict(s=player['session_id'], p=player['player_id'], k=key,
                                          a=json.dumps(clean)))
        saved += 1
    n = tx.execute('SELECT count(*) AS n FROM tool_answer WHERE player_id = %(p)s',
                   dict(p=player['player_id'])).fetchone()['n']
    if n > MAX_ANSWERS:
        raise ToolError('too_many')
    return saved


_Q_PLAYERS = """
    SELECT id, seat, display, email, normalized_email, person_id, role, finished_at, removed_at
      FROM tool_player WHERE session_id = %(s)s ORDER BY id
"""

_Q_SAVE_RESULT = """
    INSERT INTO tool_result (session_id, player_id, score, breakdown, archetype)
    VALUES (%(s)s, %(p)s, %(score)s, %(b)s::jsonb, %(a)s)
    ON CONFLICT (session_id, COALESCE(player_id, 0)) DO UPDATE
       SET score = EXCLUDED.score, breakdown = EXCLUDED.breakdown,
           archetype = EXCLUDED.archetype, computed_at = NOW()
"""


def players_of(tx, session_pk: int) -> list[dict]:
    return [dict(r) for r in tx.execute(_Q_PLAYERS, dict(s=session_pk)).fetchall()]


def _save_result(tx, session_pk: int, player_id: Optional[int], score: Optional[int],
                 breakdown: dict, archetype: Optional[str]) -> None:
    tx.execute(_Q_SAVE_RESULT, dict(s=session_pk, p=player_id, score=score,
                                    b=json.dumps(breakdown), a=archetype))


def _complete(tx, session_pk: int) -> None:
    tx.execute('UPDATE tool_session SET completed_at = COALESCE(completed_at, NOW()) WHERE id = %(i)s',
               dict(i=session_pk))


def finish(tx, player: dict) -> dict:
    """The player has answered. Me and single get their result now; Us
    and couple when the second player finishes, computed once (the session
    row is locked, so two players finishing together cannot both compute
    it); a knows-me friend gets their guess score. Run it in a read
    committed transaction, so the second of two players finishing at once
    waits for the lock and then sees the first one's finish."""
    sid = player['session_id']
    tx.execute('SELECT id FROM tool_session WHERE id = %(i)s FOR UPDATE', dict(i=sid))
    if player['seat'] == 'guest' and player['removed_at'] is not None:
        raise ToolError('not_found', 404)
    tx.execute('UPDATE tool_player SET finished_at = COALESCE(finished_at, NOW()) WHERE id = %(p)s',
               dict(p=player['player_id']))
    mode = player['mode']
    event = None
    if mode == 'me':
        key, why = results.archetype_for(answers_of(tx, player['player_id']))
        _save_result(tx, sid, None, None, dict(why=why), key)
        _complete(tx, sid)
    elif mode == 'single':
        top = checklist.top_items(answers_of(tx, player['player_id']))
        _save_result(tx, sid, None, None, dict(top=len(top)), None)
        _complete(tx, sid)
    elif mode in TWO_PLAYER:
        players = [p for p in players_of(tx, sid) if p['removed_at'] is None]
        owner = next((p for p in players if p['seat'] == 'owner'), None)
        guest = next((p for p in players if p['seat'] == 'guest'), None)
        completed = tx.execute('SELECT completed_at FROM tool_session WHERE id = %(i)s',
                               dict(i=sid)).fetchone()['completed_at']
        if owner and guest and owner['finished_at'] and guest['finished_at'] and completed is None:
            oa, ga = answers_of(tx, owner['id']), answers_of(tx, guest['id'])
            if mode == 'us':
                r = scoring.us_result(oa, ga)
                _save_result(tx, sid, None, r['score'],
                             {k: r[k] for k in ('areas', 'align', 'talk', 'bars')}, None)
            else:
                c = checklist.compare(oa, ga)
                _save_result(tx, sid, None, None, dict(agree=c['agree'], total=c['total']), None)
            _complete(tx, sid)
            first = owner if owner['finished_at'] <= guest['finished_at'] else guest
            if first['id'] != player['player_id']:
                event = dict(notify_player_id=first['id'])
    elif mode == 'knows_me' and player['seat'] == 'guest':
        owner = next(p for p in players_of(tx, sid) if p['seat'] == 'owner')
        right, total = results.guess_score(answers_of(tx, owner['id']),
                                           answers_of(tx, player['player_id']))
        _save_result(tx, sid, player['player_id'], right, dict(right=right, total=total), None)
    from service.tools import mail
    mail.after_finish(tx, player, event)
    return dict(view=view(tx, sid, player['player_id']), event=event)


_Q_SESSION = """
    SELECT id, uuid::text AS uuid, kind, mode, owner_display, owner_person_id, share_token,
           invite_token, claimed_at, completed_at
      FROM tool_session WHERE id = %(i)s
"""

_Q_RESULT = """
    SELECT score, breakdown, archetype FROM tool_result
     WHERE session_id = %(s)s AND COALESCE(player_id, 0) = COALESCE(%(p)s::bigint, 0)
"""

_Q_BOARD = """
    SELECT p.id AS player_id, p.display, p.finished_at, p.removed_at, r.score AS right,
           (r.breakdown->>'total')::int AS total
      FROM tool_player p JOIN tool_result r ON r.player_id = p.id
     WHERE p.session_id = %(s)s AND p.seat = 'guest'
"""


def _result_row(tx, session_pk: int, player_id: Optional[int]) -> Optional[dict]:
    row = tx.execute(_Q_RESULT, dict(s=session_pk, p=player_id)).fetchone()
    return dict(row) if row else None


def _board(tx, session_pk: int, *, for_owner: bool, me_id: int) -> list[dict]:
    rows = [dict(r) for r in tx.execute(_Q_BOARD, dict(s=session_pk)).fetchall()]
    ranked = results.board_order([r for r in rows if r['removed_at'] is None])
    if for_owner:
        removed = results.board_order([r for r in rows if r['removed_at'] is not None])
        return [dict(player_id=r['player_id'], display=r['display'], right=r['right'],
                     total=r['total'], removed=r['removed_at'] is not None)
                for r in ranked + removed]
    return [dict(display=r['display'], right=r['right'], total=r['total'],
                 me=r['player_id'] == me_id) for r in ranked]


def _result(tx, s: dict, me: dict, owner: dict, guest: Optional[dict], mine: dict):
    mode = s['mode']
    if mode == 'me':
        r = _result_row(tx, s['id'], None)
        return dict(archetype=r['archetype'], why=r['breakdown'].get('why', [])) if r else None
    if mode == 'single':
        return dict(top=checklist.top_items(mine))
    if mode == 'us':
        r = _result_row(tx, s['id'], None)
        return dict(score=r['score'], **r['breakdown']) if r else None
    if mode == 'couple':
        return checklist.compare(answers_of(tx, owner['id']), answers_of(tx, guest['id']))
    if me['seat'] == 'owner':
        return None
    r = _result_row(tx, s['id'], me['id'])
    if not r:
        return None
    board = _board(tx, s['id'], for_owner=False, me_id=me['id'])
    place = next((i + 1 for i, b in enumerate(board) if b['me']), None)
    return dict(right=r['breakdown']['right'], total=r['breakdown']['total'], place=place)


def view(tx, session_pk: int, player_id: int) -> dict:
    """What one player sees: their own answers, the state, the result once
    there is one and, in knows-me, the board. Never the other player's
    answers, except in the comparison two checklist players share."""
    s = dict(tx.execute(_Q_SESSION, dict(i=session_pk)).fetchone())
    players = players_of(tx, session_pk)
    me = next(p for p in players if p['id'] == player_id)
    owner = next(p for p in players if p['seat'] == 'owner')
    guest = next((p for p in players if p['seat'] == 'guest' and p['removed_at'] is None), None)
    mode = s['mode']
    mine = answers_of(tx, player_id)
    if me['finished_at'] is None:
        state = 'playing'
    elif mode in TWO_PLAYER:
        state = 'ready' if s['completed_at'] else 'waiting'
    else:
        state = 'ready'
    is_owner = me['seat'] == 'owner'
    claimed = s['claimed_at'] is not None if is_owner else me['email'] is not None
    out = dict(
        session_id=s['uuid'], kind=s['kind'], mode=mode, seat=me['seat'], role=me['role'],
        state=state, claimed=claimed,
        member=(s['owner_person_id'] is not None) if is_owner else (me['person_id'] is not None),
        share_token=s['share_token'] if claimed and s['claimed_at'] else None,
        invite_token=s['invite_token'] if is_owner else None,
        owner_display=s['owner_display'],
        guest_display=guest['display'] if mode in TWO_PLAYER and guest else None,
        my_display=s['owner_display'] if is_owner else me['display'],
        my_answers=mine, result=None, board=None,
    )
    if state == 'ready':
        out['result'] = _result(tx, s, me, owner, guest, mine)
    if mode == 'knows_me':
        out['board'] = _board(tx, session_pk, for_owner=is_owner, me_id=player_id)
    return out


_Q_BY_INVITE = """
    SELECT id, uuid::text AS uuid, kind, mode, owner_display, owner_person_id,
           owner_normalized_email, deleted_at
      FROM tool_session WHERE invite_token = %(t)s
"""


def _by_invite(tx, invite_token: object, *, lock: bool = False) -> dict:
    if not isinstance(invite_token, str) or not _TOKEN_RE.match(invite_token):
        raise ToolError('not_found', 404)
    row = tx.execute(_Q_BY_INVITE + (' FOR UPDATE' if lock else ''),
                     dict(t=invite_token)).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    return dict(row)


def _seat_state(tx, sess: dict) -> str:
    players = players_of(tx, sess['id'])
    owner = next(p for p in players if p['seat'] == 'owner')
    guests = [p for p in players if p['seat'] == 'guest' and p['removed_at'] is None]
    if sess['mode'] in TWO_PLAYER and guests:
        return 'full'
    if sess['mode'] == 'knows_me':
        if owner['finished_at'] is None:
            return 'not_ready'
        if len(guests) >= KNOWS_ME_MAX_FRIENDS:
            return 'full'
    return 'open'


def invite_info(tx, invite_token: object) -> dict:
    """What the second player's start shows. Already played is the web's
    to tell: the device that played keeps its token."""
    sess = _by_invite(tx, invite_token)
    return dict(kind=sess['kind'], mode=sess['mode'], owner_display=sess['owner_display'],
                state=_seat_state(tx, sess))


def _is_owner(sess: dict, s) -> bool:
    if s.person_id is not None and sess['owner_person_id'] == s.person_id:
        return True
    return sess['owner_normalized_email'] == normalize_email(s.email)


def join(tx, invite_token: object, *, display: object, s=None) -> dict:
    """A guest takes a seat. A signed-in guest (a member from the chat, or
    a visitor who confirmed an address before) is saved at once, with no
    email step, except in knows-me, where friends give only a name."""
    sess = _by_invite(tx, invite_token, lock=True)
    signed_in = s is not None and s.signed_in
    if signed_in and _is_owner(sess, s):
        raise ToolError('own_session', 409)
    state = _seat_state(tx, sess)
    if state != 'open':
        raise ToolError(state, 409)
    fields: dict[str, Any] = dict(display=clean_display(display))
    if signed_in and sess['mode'] != 'knows_me':
        fields.update(email=s.email, normalized_email=normalize_email(s.email),
                      person_id=s.person_id)
    token = new_player(tx, sess['id'], 'guest', **fields)
    tx.execute('UPDATE tool_session SET last_visit_at = NOW() WHERE id = %(i)s', dict(i=sess['id']))
    return dict(session_id=sess['uuid'], player_token=token)


def set_removed(tx, player: dict, guest_id: int, removed: bool) -> dict:
    """The player takes a name off their knows-me board, or puts it back
    ("Undo")."""
    if player['seat'] != 'owner' or player['mode'] != 'knows_me':
        raise ToolError('not_allowed', 403)
    n = tx.execute(
        """UPDATE tool_player SET removed_at = CASE WHEN %(r)s THEN NOW() END
            WHERE id = %(g)s AND session_id = %(s)s AND seat = 'guest'""",
        dict(r=removed, g=guest_id, s=player['session_id'])).rowcount
    if n == 0:
        raise ToolError('not_found', 404)
    return view(tx, player['session_id'], player['player_id'])


def claim(tx, player: dict, s, display: object) -> dict:
    """Save a seat with the address the signed-in session proved (a sign-in
    code or a member's account). The owner's save issues the share token
    and, for Us, knows-me and the couple checklist, the invite token. A
    guest in Us or the couple checklist may save too, to get the image; a
    knows-me friend gives only a name. A seat saved with one address is
    never moved to another."""
    from service.leads import confirm_lead, record_lead, tool_leads_enabled
    if s is None or not s.signed_in:
        raise ToolError('sign_in_required', 401)
    name = clean_display(display)
    ne = normalize_email(s.email)
    if player['seat'] == 'owner':
        saved_ne = player['owner_normalized_email'] if player['claimed_at'] else None
        if (saved_ne and saved_ne != ne) or (
                player['owner_person_id'] is not None and player['owner_person_id'] != s.person_id):
            raise ToolError('claimed', 409)
        tx.execute(
            """UPDATE tool_session
                  SET owner_email = %(e)s, owner_normalized_email = %(ne)s,
                      owner_person_id = COALESCE(owner_person_id, %(pid)s),
                      owner_display = %(d)s, claimed_at = COALESCE(claimed_at, NOW()),
                      share_token = COALESCE(share_token, %(st)s),
                      invite_token = CASE WHEN mode = ANY(%(inv)s)
                                          THEN COALESCE(invite_token, %(it)s) END
                WHERE id = %(i)s""",
            dict(e=s.email, ne=ne, pid=s.person_id, d=name, st=new_link_token(),
                 inv=list(WITH_INVITE), it=new_link_token(), i=player['session_id']))
    else:
        if player['mode'] == 'knows_me':
            raise ToolError('not_allowed', 403)
        if player['normalized_email'] and player['normalized_email'] != ne:
            raise ToolError('claimed', 409)
        tx.execute(
            """UPDATE tool_player
                  SET email = %(e)s, normalized_email = %(ne)s,
                      person_id = COALESCE(person_id, %(pid)s), display = %(d)s
                WHERE id = %(p)s""",
            dict(e=s.email, ne=ne, pid=s.person_id, d=name, p=player['player_id']))
    if s.person_id is None and tool_leads_enabled():
        lead_id = record_lead(tx, email=s.email, source=player['source'])
        if lead_id is not None:
            confirm_lead(tx, lead_id, 'otp')
    if player['kind'] == 'checklist' and player['finished_at'] is not None:
        # A single who saves after finishing gets their summary now.
        from service.tools import mail
        mail.queue_summary(tx, player['session_id'], player['player_id'])
    return view(tx, player['session_id'], player['player_id'])


_Q_LINK_OWNED = """
    UPDATE tool_session SET owner_person_id = %(pid)s
     WHERE owner_person_id IS NULL
       AND owner_normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
"""

_Q_LINK_JOINED = """
    UPDATE tool_player SET person_id = %(pid)s
     WHERE person_id IS NULL
       AND normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
"""


def link_tool_sessions_to_person(tx, person_id: int) -> None:
    """At finish-onboarding: the sessions the new member saved before
    joining become theirs, so they go with the account. Rolled back to a
    savepoint and ignored on any failure: it can never undo the sign-up."""
    tx.execute('SAVEPOINT link_tool_sessions')
    try:
        tx.execute(_Q_LINK_OWNED, dict(pid=person_id))
        tx.execute(_Q_LINK_JOINED, dict(pid=person_id))
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT link_tool_sessions')
    else:
        tx.execute('RELEASE SAVEPOINT link_tool_sessions')


_Q_BY_SHARE = """
    SELECT id, kind, mode, owner_display, completed_at, deleted_at
      FROM tool_session WHERE share_token = %(t)s
"""


def public_summary(tx, share_token: object) -> dict:
    """What a shared link and its image may show: names and the headline
    number, never an answer, an area or another player's score."""
    if not isinstance(share_token, str) or not _TOKEN_RE.match(share_token):
        raise ToolError('not_found', 404)
    row = tx.execute(_Q_BY_SHARE, dict(t=share_token)).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    mode = row['mode']
    players = players_of(tx, row['id'])
    owner = next(p for p in players if p['seat'] == 'owner')
    names = [row['owner_display']] if row['owner_display'] else []
    if mode in TWO_PLAYER:
        guest = next((p for p in players if p['seat'] == 'guest' and p['removed_at'] is None), None)
        if guest and guest['display']:
            names.append(guest['display'])
        ready = row['completed_at'] is not None
    else:
        ready = owner['finished_at'] is not None
    out: dict[str, Any] = dict(kind=row['kind'], mode=mode, names=names,
                               state='ready' if ready else 'waiting')
    if ready and mode == 'me':
        out['archetype'] = _result_row(tx, row['id'], None)['archetype']
    elif ready and mode == 'us':
        out['score'] = _result_row(tx, row['id'], None)['score']
    elif ready and mode == 'couple':
        b = _result_row(tx, row['id'], None)['breakdown']
        out.update(agree=b['agree'], total=b['total'])
    return out


def count_open(tx, share_token: object) -> None:
    """A share link opened in a browser (Admin > Growth counts them)."""
    if isinstance(share_token, str) and _TOKEN_RE.match(share_token):
        tx.execute("""UPDATE tool_session SET share_opens = share_opens + 1
                       WHERE share_token = %(t)s AND deleted_at IS NULL""", dict(t=share_token))


def delete_session(tx, player: dict) -> None:
    """Delete a result for everyone: its answers, results, names and
    addresses go now. The row and its tokens stay as a tombstone, so every
    link says it was deleted, until the sweep removes it 30 days later
    (service/tools/retention.py). The owner may delete; so may the guest
    of an Us game or a couple checklist, which they share. A knows-me
    friend may not."""
    if player['seat'] == 'guest' and player['mode'] not in TWO_PLAYER:
        raise ToolError('not_allowed', 403)
    sid = player['session_id']
    tx.execute('DELETE FROM tool_answer WHERE session_id = %(s)s', dict(s=sid))
    tx.execute('DELETE FROM tool_result WHERE session_id = %(s)s', dict(s=sid))
    tx.execute("""UPDATE tool_player SET display = NULL, email = NULL, normalized_email = NULL,
                         person_id = NULL, role = NULL
                   WHERE session_id = %(s)s""", dict(s=sid))
    tx.execute("""UPDATE tool_session SET deleted_at = NOW(), owner_email = NULL,
                         owner_normalized_email = NULL, owner_display = NULL,
                         owner_person_id = NULL, utm = NULL
                   WHERE id = %(s)s""", dict(s=sid))
