""""See passes again" has its own ledger reason (11 Nov 2026).

It was written to token_ledger as 'rewind', the single-profile Rewind's
reason, so the ledger could not tell the two apart. Migration 0098 adds
'see_passes' to the reason check and moves the rows already written.
"""
from __future__ import annotations

import json
from pathlib import Path

from database import api_tx
from service.tokens import credit

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0098_see_passes_reason.sql'


def _apply():
    with api_tx() as tx:
        tx.execute(MIGRATION.read_text(encoding='utf-8'))


def _passed(me, other):
    with api_tx() as tx:
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                   'VALUES (%(a)s, %(b)s, FALSE)', dict(a=me['id'], b=other['id']))


def _reasons(me):
    with api_tx() as tx:
        return [r['reason'] for r in tx.execute(
            'SELECT reason FROM token_ledger WHERE person_id = %(u)s::uuid AND delta < 0 ORDER BY created_at',
            dict(u=me['uuid'])).fetchall()]


def test_see_passes_is_written_as_its_own_reason(client, make_person, sign_in):
    _apply()
    me, other = make_person(name='SeeMe'), make_person(name='SeeOther', gender='Woman')
    with api_tx() as tx:
        credit(tx, me['uuid'], 5, reason='purchase', metadata={})
    _passed(me, other)
    r = client.post('/tokens/see-passes', headers=sign_in(me))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _reasons(me) == ['see_passes']


def test_the_migration_moves_rows_already_written(make_person):
    me = make_person(name='SeeOld')
    with api_tx() as tx:
        for kind in ('see_passes', None):
            tx.execute(
                """INSERT INTO token_ledger (person_id, delta, reason, metadata)
                   VALUES (%(u)s::uuid, -3, 'rewind', %(m)s::jsonb)""",
                dict(u=me['uuid'], m=json.dumps({'kind': kind} if kind else {})))
    _apply()
    _apply()
    assert sorted(_reasons(me)) == ['rewind', 'see_passes']
