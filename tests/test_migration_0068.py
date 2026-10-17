"""Migration 0068: the Together tables (TEC-1845).

Pins what later tasks rely on: a mode belongs to its tool, a session's
source is a tool source, one owner per session and any number of guests,
one answer per player and question, results bounded, display names 1 to 40
characters, and deleting a session takes everything under it. The deploy
may run the file more than once, so every test runs it twice first.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0068_together.sql')


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice(growth_schema):
    _apply()
    _apply()


def _session(tx, kind: str = 'game', mode: str = 'us', source: str = 'tool:game-us') -> int:
    return tx.execute(
        """INSERT INTO tool_session (kind, mode, source) VALUES (%(k)s, %(m)s, %(s)s)
           RETURNING id""", dict(k=kind, m=mode, s=source)).fetchone()['id']


def _player(tx, sid: int, seat: str = 'owner', display: str | None = None) -> int:
    return tx.execute(
        """INSERT INTO tool_player (session_id, seat, token_hash, display)
           VALUES (%(s)s, %(seat)s, %(h)s, %(d)s) RETURNING id""",
        dict(s=sid, seat=seat, h=uuid4().hex, d=display)).fetchone()['id']


def _drop(sid: int) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))


@pytest.mark.parametrize('kind,mode', [('game', 'couple'), ('checklist', 'us'), ('game', 'dating')])
def test_a_mode_belongs_to_its_tool(kind, mode):
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            _session(tx, kind, mode)


def test_a_session_source_is_a_tool_source():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            _session(tx, source='utm:facebook')


def test_one_owner_per_session_and_any_number_of_guests():
    with api_tx() as tx:
        sid = _session(tx, mode='knows_me', source='tool:knows-me')
        _player(tx, sid)
        _player(tx, sid, 'guest')
        _player(tx, sid, 'guest')
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _player(tx, sid)
    finally:
        _drop(sid)


def test_an_answer_key_is_a_slug_and_one_per_player_and_question():
    with api_tx() as tx:
        sid = _session(tx)
        pid = _player(tx, sid)
        tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                      VALUES (%(s)s, %(p)s, 'calendar', '"enoch"')""", dict(s=sid, p=pid))
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                              VALUES (%(s)s, %(p)s, 'calendar', '"other"')""", dict(s=sid, p=pid))
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                              VALUES (%(s)s, %(p)s, 'Not A Key', '1')""", dict(s=sid, p=pid))
    finally:
        _drop(sid)


def test_deleting_a_session_takes_its_players_answers_and_results():
    with api_tx() as tx:
        sid = _session(tx)
        pid = _player(tx, sid)
        tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                      VALUES (%(s)s, %(p)s, 'move', '"local-only"')""", dict(s=sid, p=pid))
        tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 82)", dict(s=sid))
    _drop(sid)
    with api_tx() as tx:
        left = [tx.execute(f'SELECT count(*) AS n FROM {t} WHERE session_id = %(s)s',
                           dict(s=sid)).fetchone()['n']
                for t in ('tool_player', 'tool_answer', 'tool_result')]
    assert left == [0, 0, 0]


def test_a_score_stays_between_0_and_100_and_one_result_per_player():
    with api_tx() as tx:
        sid = _session(tx)
        tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 100)", dict(s=sid))
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 101)",
                           dict(s=sid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 50)",
                           dict(s=sid))
    finally:
        _drop(sid)


def test_a_display_name_is_1_to_40_characters():
    with api_tx() as tx:
        sid = _session(tx)
    try:
        for bad in ('', 'x' * 41):
            with pytest.raises(psycopg.errors.CheckViolation):
                with api_tx() as tx:
                    _player(tx, sid, 'guest', bad)
    finally:
        _drop(sid)
