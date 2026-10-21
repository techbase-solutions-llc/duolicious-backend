"""The Users list sorts by the date a row joined, whichever table it came
from, and sends that date as `joined_at` with `deletion_requested_at`
(TEC-1845 admin audit, Medium). sign_up_time, which the live admin reads,
keeps its meaning."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def test_a_member_sorts_above_an_old_waitlist_row_and_both_carry_a_joined_date(
        client, make_person, admin_headers):
    tag = uuid4().hex[:12]
    waitlist_email = f'wl-{tag}@example.com'
    member = make_person(name='Joined', email=f'member-{tag}@example.com')
    with api_tx() as tx:
        tx.execute("""INSERT INTO waitlist_signup (email, created_at)
                      VALUES (%(e)s, NOW() - INTERVAL '400 days')""", dict(e=waitlist_email))
    try:
        r = client.get(f'/admin/users?q={tag}', headers=admin_headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        rows = r.get_json()['rows']
        assert [row['email'] for row in rows] == [f'member-{tag}@example.com', waitlist_email]
        assert rows[0]['uuid'] == member['uuid']
        assert rows[0]['joined_at'] and rows[1]['joined_at']
        assert rows[1]['joined_at'] < rows[0]['joined_at']
        # The live admin reads sign_up_time; it stays as it was.
        assert rows[1]['sign_up_time'] is None
        assert rows[0]['deletion_requested_at'] is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM waitlist_signup WHERE email = %(e)s', dict(e=waitlist_email))


def test_the_list_carries_a_pending_deletion(client, make_person, admin_headers):
    tag = uuid4().hex[:12]
    member = make_person(name='Leaving', email=f'leaving-{tag}@example.com')
    with api_tx() as tx:
        tx.execute('UPDATE person SET deletion_requested_at = NOW() WHERE id = %(i)s',
                   dict(i=member['id']))
    r = client.get(f'/admin/users?q={tag}', headers=admin_headers)
    assert r.status_code == 200
    (row,) = r.get_json()['rows']
    assert row['deletion_requested_at'] and row['deletion_requested_at'].endswith('+00:00')
