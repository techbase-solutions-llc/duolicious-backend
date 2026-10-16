"""otp_request is kept for 90 days (TEC-1848).

The table (migration 0065) gets one row per sign-in code request so Admin >
System can show codes never entered over the last 30 days. Nothing removed
old rows, so it grew for ever. The garbage records sweep, which already
clears expired sessions and tokens, now deletes rows older than 90 days.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from database import api_tx


def _row(days_old: float) -> int:
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO otp_request (requested_at, new_address, refused)
               VALUES (NOW() - make_interval(secs => %(s)s), TRUE, 'retention-test')
               RETURNING id""", dict(s=days_old * 86400)).fetchone()['id']


def _exists(row_id: int) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT 1 FROM otp_request WHERE id = %(i)s',
                          dict(i=row_id)).fetchone() is not None


def test_the_sweep_deletes_otp_requests_older_than_90_days(monkeypatch):
    import service.cron.garbagerecords as garbagerecords_mod
    from service.cron.garbagerecords import delete_garbage_records_once
    monkeypatch.setattr(garbagerecords_mod.aws_smtp, 'send', MagicMock(return_value=None))

    old, kept, recent = _row(91), _row(89), _row(1)
    try:
        asyncio.run(delete_garbage_records_once())
        assert not _exists(old)
        assert _exists(kept)
        assert _exists(recent)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM otp_request WHERE id = ANY(%(i)s)', dict(i=[old, kept, recent]))
