"""The reports list sends created_at as ISO 8601 UTC (TEC-1845 admin audit,
Medium). reported_at is naive UTC and ::text carried no zone, so the admin
read an evening report as the next day."""
from __future__ import annotations

from database import api_tx


def test_report_times_are_iso_utc(client, make_person, admin_headers):
    a, b = make_person(name='Reporter'), make_person(name='Reported')
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO person_report (reporter_id, reported_id, reported_at, reason)
               VALUES (%(a)s, %(b)s, '2026-10-14 02:00:00.123456', 'spam')""",
            dict(a=a['id'], b=b['id']))
    r = client.get('/admin/reports', headers=admin_headers)
    assert r.status_code == 200
    rows = r.get_json()
    rows = rows['reports'] if isinstance(rows, dict) and 'reports' in rows else rows
    (mine,) = [x for x in rows if x['reporter_uuid'] == a['uuid']]
    assert mine['created_at'] == '2026-10-14T02:00:00.123Z'
