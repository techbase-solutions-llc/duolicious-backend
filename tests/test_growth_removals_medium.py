"""Growth removals, the API half of the admin audit's Medium findings
(TEC-1845, 21 Oct).

- Under the emergency stop the removals list withholds only the worker's
  automatic deletions: the tasks a person does by hand stay listed.
- Each removal task names the member's first name and the post's URL."""
from __future__ import annotations

import secrets

from database import api_tx
from service.spotlight import set_spotlight_opt_in
from service.spotlight.queue import create_candidate, set_setting

H = {'X-Growth-Cron': 'test-cron-secret'}


def _eligible(make_person, name='Miriam Levi'):
    p = make_person(name=name, gender='Woman')
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL
             WHERE id = %(id)s""", dict(id=p['id']))
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""",
                   dict(u=secrets.token_hex(32), id=p['id']))
    return p


def _first(tx, rk):
    tx.execute("""UPDATE spotlight_removal_task
                     SET deadline_at = (SELECT COALESCE(MIN(deadline_at), NOW()) - interval '1 day'
                                          FROM spotlight_removal_task WHERE done_at IS NULL)
                   WHERE request_key = %(rk)s AND done_at IS NULL""", dict(rk=rk))


def _published_then_withdrawn(make_person):
    """A welcome card live on both platforms, then the member opts out: a
    manual_instagram task and a delete_via_api (Facebook) task."""
    p = _eligible(make_person)
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=p['id'], caption='c', created_by='t')
        tx.execute("""UPDATE publishing_queue
                         SET status = 'published', external_post_id = 'post-' || platform,
                             post_url = 'https://example.com/' || platform
                       WHERE request_key = %(rk)s""", dict(rk=rk))
        set_spotlight_opt_in(tx, p['id'], False)
        _first(tx, rk)
    return rk


def test_removals_name_the_member_and_the_post(client, make_person):
    rk = _published_then_withdrawn(make_person)
    tasks = [t for t in client.get('/admin/growth/removals?pending=1', headers=H).get_json()['tasks']
             if t['request_key'] == rk]
    assert tasks
    for t in tasks:
        assert t['subject_first_name'] == 'Miriam'
        assert t['post_url'] == f"https://example.com/{t['platform']}"


def test_the_stop_keeps_hand_tasks_and_withholds_automatic_deletes(client, make_person):
    rk = _published_then_withdrawn(make_person)
    with api_tx() as tx:
        before = tx.execute("SELECT value FROM spotlight_setting WHERE key = 'external_access_enabled'"
                            ).fetchone()
        set_setting(tx, 'external_access_enabled', 'false')
    try:
        body = client.get('/admin/growth/removals?pending=1', headers=H).get_json()
        assert body['halted'] is True
        mine = {t['reason'] for t in body['tasks'] if t['request_key'] == rk}
        assert mine == {'manual_instagram'}
        assert all(t['reason'] != 'delete_via_api' for t in body['tasks'])
        worker = client.get('/admin/growth/removals?worker=1', headers=H).get_json()
        assert worker['tasks'] == []
    finally:
        with api_tx() as tx:
            set_setting(tx, 'external_access_enabled', before['value'] if before else 'true')
