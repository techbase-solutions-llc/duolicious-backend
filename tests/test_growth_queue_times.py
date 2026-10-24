"""The Growth queue rows say when a card was approved and when a row last
changed (TEC-1845; Claude Design "Admin Growth Tables" T.1 and T.4, handoff
17): "Scheduled · Approved {date}", "Cancelled {date}" and a failure's
"last try {date time}". approved_at is the newest growth.queue.approve audit
row for that platform row; updated_at is the row's own."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.test_brand_posts import H, _admin_headers, _approve, _cancel, _create, _render, _rows


def _queue(client, rk: str) -> list[dict]:
    return [r for r in client.get('/admin/growth/queue', headers=H).get_json() if r['request_key'] == rk]


def test_an_approved_row_says_when_it_was_approved(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    A = _admin_headers(make_person)
    rk = _create(client).get_json()['request_key']
    try:
        _render(client, monkeypatch, rk)
        rows = _rows(rk)
        before = _queue(client, rk)
        assert all(r['approved_at'] is None for r in before)
        assert all(r['updated_at'] for r in before)

        assert _approve(client, A, rows[0]['id']).status_code == 200

        after = {r['id']: r for r in _queue(client, rk)}
        approved = datetime.fromisoformat(after[str(rows[0]['id'])]['approved_at'])
        assert abs(approved.replace(tzinfo=approved.tzinfo or timezone.utc)
                   - datetime.now(timezone.utc)) < timedelta(minutes=5)
        # Only the row that was approved.
        assert after[str(rows[1]['id'])]['approved_at'] is None
    finally:
        _cancel(rk)


def test_a_cancelled_row_says_when_it_last_changed(client, monkeypatch):
    rk = _create(client).get_json()['request_key']
    _cancel(rk)
    rows = _queue(client, rk)
    assert rows and all(r['status'] == 'cancelled' for r in rows)
    for r in rows:
        at = datetime.fromisoformat(r['updated_at'])
        assert abs(at.replace(tzinfo=at.tzinfo or timezone.utc) - datetime.now(timezone.utc)) < timedelta(minutes=5)
