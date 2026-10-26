"""Migrations 0085 to 0087, release 4 of the in-app plan (TEC-1845): the
light sign-in's address sessions, the 3 push toggles and the chat a
Together session was started from. Each is idempotent, as the deploy may
run it more than once, and waits at most 5 seconds for a lock."""
from pathlib import Path

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('release_4_schema')
MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'
NAMES = ('0085_address_session.sql', '0086_release_4_push_preferences.sql', '0087_tool_session_chat.sql')


@pytest.mark.parametrize('name', NAMES)
def test_runs_twice_and_bounds_its_lock_wait(name):
    sql = (MIGRATIONS / name).read_text(encoding='utf-8')
    assert "SET lock_timeout = '5s';" in sql and 'RESET lock_timeout;' in sql
    with api_tx() as tx:
        tx.execute(sql)
        tx.execute(sql)


def _columns(table):
    with api_tx('read committed') as tx:
        return {r['column_name']: r for r in tx.execute(
            """SELECT column_name, is_nullable, column_default FROM information_schema.columns
                WHERE table_name = %(t)s""", dict(t=table)).fetchall()}


def test_the_address_session_table():
    cols = _columns('address_session')
    assert {'email', 'normalized_email', 'request_token_hash', 'code_hash', 'code_expires_at', 'code_attempts',
            'session_token_hash', 'session_expires_at', 'created_at'} <= set(cols)


def test_the_push_toggles_default_on():
    cols = _columns('notification_preference')
    for c in ('push_gathering_reminder', 'push_new_guests', 'push_match_played'):
        assert cols[c]['is_nullable'] == 'NO' and cols[c]['column_default'] == 'true', c


def test_the_chat_column_is_optional():
    assert _columns('tool_session')['chat_person_id']['is_nullable'] == 'YES'


def test_the_numbers_stay_clear_of_release_3():
    """Release 3, built beside this one, takes 0080 to 0084."""
    for name in NAMES:
        assert int(name[:4]) >= 85
