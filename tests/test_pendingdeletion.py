"""
F11/F12: pendingdeletion hard delete must stage CDN cleanup queues and
purge referral rows.

F11: self-service hard deletion never fed undeleted_photo/undeleted_audio,
the only queues the CDN cleaners read, so a deleted member's photos stayed
publicly fetchable forever.

F12 (0037 regression): referral.inviter_email lost its FK/cascade to
beta_signup in migration 0037 (inviters can now be any member, not just
beta testers), and invitee_email never had one. Hard delete must purge
both directions explicitly or a deleted member's email lingers in
`referral` forever (and can block re-signup via UNIQUE(invitee_email)).
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets

from database import api_tx
from service.cron.pendingdeletion import hard_delete_expired_once


def test_hard_delete_stages_media_and_purges_referrals(make_person):
    p = make_person(name='Leaver', gender='Woman')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(p)s',
                            dict(p=p['id'])).fetchone()['email']
        # Defensive: a prior failed run of this test can leak these
        # plain-text-keyed referral rows (they have no FK back to person
        # to clean them up automatically).
        tx.execute("DELETE FROM referral WHERE invitee_email IN "
                   "('ghost-invitee@example.org') OR inviter_email IN "
                   "('ghost-inviter@example.org')")
        tx.execute(
            "INSERT INTO photo (person_id, position, uuid, blurhash, hash) "
            "VALUES (%(p)s, 1, 'del-test-photo-uuid-1', '', 'del-test-hash-1')",
            dict(p=p['id']))
        tx.execute(
            "INSERT INTO audio (person_id, position, uuid) "
            "VALUES (%(p)s, 1, 'del-test-audio-uuid-1')",
            dict(p=p['id']))
        tx.execute(
            "INSERT INTO referral (inviter_email, invitee_email) VALUES "
            "(%(e)s, 'ghost-invitee@example.org'), "
            "('ghost-inviter@example.org', %(e)s)", dict(e=email))
        # A click on the leaver's own invite link. Since 13 Oct 2026 the
        # click logger records a member as the inviter, so the address
        # lands here too.
        tx.execute("DELETE FROM referral_link_click WHERE code = 'DELTEST'")
        tx.execute(
            "INSERT INTO referral_link_click (code, inviter_email, well_formed) "
            "VALUES ('DELTEST', %(e)s, TRUE)", dict(e=email))
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "  # before the request
            "WHERE id = %(p)s", dict(p=p['id']))

    asyncio.run(hard_delete_expired_once())

    try:
        with api_tx() as tx:
            staged_photo = tx.execute(
                "SELECT 1 FROM undeleted_photo WHERE uuid = 'del-test-photo-uuid-1'"
            ).fetchone()
            assert staged_photo, \
                'hard delete must stage photo uuids for the CDN cleaner (F11)'

            staged_audio = tx.execute(
                "SELECT 1 FROM undeleted_audio WHERE uuid = 'del-test-audio-uuid-1'"
            ).fetchone()
            assert staged_audio, \
                'hard delete must stage audio uuids for the CDN cleaner (F11)'

            ref = tx.execute(
                'SELECT count(*) AS n FROM referral WHERE '
                'inviter_email = %(e)s OR invitee_email = %(e)s',
                dict(e=email)).fetchone()['n']
            assert ref == 0, 'referral rows survived hard delete (F12)'

            # The click stays counted; the leaver's address goes.
            clicks = tx.execute(
                "SELECT inviter_email FROM referral_link_click WHERE code = 'DELTEST'"
            ).fetchall()
            assert [c['inviter_email'] for c in clicks] == [None],                 "a deleted member's address survived on their link's clicks"

            gone = tx.execute('SELECT 1 FROM person WHERE id = %(p)s',
                               dict(p=p['id'])).fetchone()
            assert gone is None
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM undeleted_photo WHERE uuid = 'del-test-photo-uuid-1'")
            tx.execute("DELETE FROM undeleted_audio WHERE uuid = 'del-test-audio-uuid-1'")
            tx.execute("DELETE FROM referral_link_click WHERE code = 'DELTEST'")
            tx.execute("DELETE FROM referral WHERE invitee_email = 'ghost-invitee@example.org' "
                       "OR inviter_email = 'ghost-inviter@example.org'")


def test_sign_in_after_delete_cancels_the_purge(make_person):
    """F13: signing back in during the 7-day grace resurrected visibility
    but the reaper still hard-deleted on day 7. Sign-in now clears the
    request (see Q_MAYBE_SIGN_IN), and the reaper independently skips
    anyone who signed in after requesting deletion, as belt and braces
    for rows written before this deploy."""
    regretter = make_person(name='Regret', gender='Man')
    still_leaving = make_person(name='StillLeaving', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() "  # signed in AFTER requesting deletion
            "WHERE id = %(p)s", dict(p=regretter['id']))
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "  # signed in BEFORE
            "WHERE id = %(p)s", dict(p=still_leaving['id']))

    asyncio.run(hard_delete_expired_once())

    with api_tx() as tx:
        alive = tx.execute('SELECT 1 FROM person WHERE id = %(p)s',
                            dict(p=regretter['id'])).fetchone()
        assert alive, \
            'reaper deleted a member who signed in after requesting deletion'

        gone = tx.execute('SELECT 1 FROM person WHERE id = %(p)s',
                           dict(p=still_leaving['id'])).fetchone()
        assert gone is None, \
            'reaper must still purge members who never signed in after requesting deletion'


def _admin_headers(make_person) -> dict:
    """An admin with a real session. Copied from tests/test_spotlight_withdrawal.py."""
    admin = make_person(name='DeleteAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute(
            "UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s RETURNING email",
            dict(i=admin['id'])).fetchone()['email']
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def test_admin_hard_delete_purges_referrals_and_click_addresses(make_person, client):
    """The admin's DELETE /admin/users/:uuid deletes the person at once and
    used to leave their address in `referral` (both directions) and, since
    13 Oct 2026, on the clicks of their own invite link. The deletion cron
    above clears both; the admin route now does the same."""
    headers = _admin_headers(make_person)
    p = make_person(name='AdminDeleted', gender='Woman')
    with api_tx() as tx:
        row = tx.execute('SELECT uuid::text AS u, email FROM person WHERE id = %(p)s',
                         dict(p=p['id'])).fetchone()
        uuid, email = row['u'], row['email']
        tx.execute("DELETE FROM referral WHERE invitee_email = 'admin-ghost-invitee@example.org' "
                   "OR inviter_email = 'admin-ghost-inviter@example.org'")
        tx.execute(
            "INSERT INTO referral (inviter_email, invitee_email) VALUES "
            "(%(e)s, 'admin-ghost-invitee@example.org'), "
            "('admin-ghost-inviter@example.org', %(e)s)", dict(e=email))
        tx.execute("DELETE FROM referral_link_click WHERE code = 'ADMDELT'")
        tx.execute(
            "INSERT INTO referral_link_click (code, inviter_email, well_formed) "
            "VALUES ('ADMDELT', %(e)s, TRUE)", dict(e=email))

    try:
        r = client.delete(f'/admin/users/{uuid}',
                          json={'confirm_email': email, 'reason': 'test'}, headers=headers)
        assert r.status_code == 200

        with api_tx() as tx:
            ref = tx.execute(
                'SELECT count(*) AS n FROM referral WHERE '
                'inviter_email = %(e)s OR invitee_email = %(e)s',
                dict(e=email)).fetchone()['n']
            assert ref == 0, 'referral rows survived the admin hard delete'
            clicks = tx.execute(
                "SELECT inviter_email FROM referral_link_click WHERE code = 'ADMDELT'"
            ).fetchall()
            assert [c['inviter_email'] for c in clicks] == [None],                 "a deleted member's address survived on their link's clicks"
    finally:
        with api_tx() as tx:
            tx.execute("DELETE FROM referral_link_click WHERE code = 'ADMDELT'")
            tx.execute("DELETE FROM referral WHERE invitee_email = 'admin-ghost-invitee@example.org' "
                       "OR inviter_email = 'admin-ghost-inviter@example.org'")


def _seed_leaver_traces(tx, person_id: int, uuid: str, email: str, tag: str) -> None:
    """A photo, a voice recording, an inbox row, a waitlist row and a beta
    row for the person, each keyed on `tag` so the test can find them."""
    tx.execute(
        "INSERT INTO photo (person_id, position, uuid, blurhash, hash) "
        "VALUES (%(p)s, 1, %(u)s, '', %(h)s)",
        dict(p=person_id, u=f'{tag}-photo', h=f'{tag}-hash'))
    tx.execute(
        "INSERT INTO audio (person_id, position, uuid) VALUES (%(p)s, 1, %(u)s)",
        dict(p=person_id, u=f'{tag}-audio'))
    tx.execute(
        "INSERT INTO inbox (luser, remote_bare_jid, content, timestamp, unread_count) "
        "VALUES (%(l)s, %(r)s, 'hello'::bytea, 1, 1)",
        dict(l=uuid, r=f'{tag}-peer@ahavah.app'))
    tx.execute(
        "INSERT INTO waitlist_signup (email) VALUES (%(e)s) ON CONFLICT DO NOTHING",
        dict(e=email))
    tx.execute(
        "INSERT INTO beta_signup (email) VALUES (%(e)s) ON CONFLICT DO NOTHING",
        dict(e=email))


def _assert_leaver_traces_gone(tx, uuid: str, email: str, tag: str) -> None:
    assert tx.execute("SELECT 1 FROM undeleted_photo WHERE uuid = %(u)s",
                      dict(u=f'{tag}-photo')).fetchone(), \
        'the photo was not staged for the CDN cleaner'
    assert tx.execute("SELECT 1 FROM undeleted_audio WHERE uuid = %(u)s",
                      dict(u=f'{tag}-audio')).fetchone(), \
        'the voice recording was not staged for the CDN cleaner'
    assert tx.execute("SELECT 1 FROM inbox WHERE luser = %(l)s",
                      dict(l=uuid)).fetchone() is None, \
        "the deleted member's inbox survived"
    assert tx.execute("SELECT 1 FROM waitlist_signup WHERE email = %(e)s",
                      dict(e=email)).fetchone() is None, \
        "the deleted member's waitlist row survived"
    assert tx.execute("SELECT 1 FROM beta_signup WHERE email = %(e)s",
                      dict(e=email)).fetchone() is None, \
        "the deleted member's beta row survived"


def _clean_leaver_traces(uuid: str, email: str, tag: str) -> None:
    with api_tx() as tx:
        tx.execute("DELETE FROM undeleted_photo WHERE uuid = %(u)s", dict(u=f'{tag}-photo'))
        tx.execute("DELETE FROM undeleted_audio WHERE uuid = %(u)s", dict(u=f'{tag}-audio'))
        tx.execute("DELETE FROM inbox WHERE luser = %(l)s", dict(l=uuid))
        tx.execute("DELETE FROM waitlist_signup WHERE email = %(e)s", dict(e=email))
        tx.execute("DELETE FROM beta_signup WHERE email = %(e)s", dict(e=email))


def test_the_deletion_cron_clears_inbox_waitlist_and_beta_rows(make_person):
    """Pins what the cron already did, so moving its statements to a shared
    module (for the admin hard delete below) cannot drop one."""
    p = make_person(name='CronLeaver', gender='Woman')
    tag = f"cron-leaver-{p['id']}"
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(p)s',
                           dict(p=p['id'])).fetchone()['email']
        _seed_leaver_traces(tx, p['id'], p['uuid'], email, tag)
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))

    asyncio.run(hard_delete_expired_once())

    try:
        with api_tx() as tx:
            _assert_leaver_traces_gone(tx, p['uuid'], email, tag)
    finally:
        _clean_leaver_traces(p['uuid'], email, tag)


def test_admin_hard_delete_stages_media_and_clears_inbox_and_waitlist(make_person, client):
    """Wave 1 review (privacy): the admin's DELETE /admin/users/:uuid left the
    member's photos and voice recording publicly fetchable (nothing staged
    them for the CDN cleaners) and kept their inbox and waitlist rows. It
    now does what the deletion cron does."""
    headers = _admin_headers(make_person)
    p = make_person(name='AdminLeaver', gender='Woman')
    tag = f"admin-leaver-{p['id']}"
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(p)s',
                           dict(p=p['id'])).fetchone()['email']
        _seed_leaver_traces(tx, p['id'], p['uuid'], email, tag)

    try:
        r = client.delete(f"/admin/users/{p['uuid']}",
                          json={'confirm_email': email, 'reason': 'test'}, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        with api_tx() as tx:
            assert tx.execute('SELECT 1 FROM person WHERE id = %(p)s',
                              dict(p=p['id'])).fetchone() is None
            _assert_leaver_traces_gone(tx, p['uuid'], email, tag)
    finally:
        _clean_leaver_traces(p['uuid'], email, tag)
