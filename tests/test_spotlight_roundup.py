"""service/spotlight/roundup.py: the weekly roundup tile snapshot (Task 11,
plan spec 3.3 / 3.5 E2). `_make_eligible` copied from tests/test_spotlight_queue.py
on purpose -- test files in this suite do not import from each other."""
from __future__ import annotations
import secrets

from database import api_tx
from service.spotlight.queue import create_candidate, set_setting
from service.spotlight.revisions import create_revision, current_revision, record_consent
from service.spotlight.roundup import roundup_snapshot


def _stamp_member_approval(tx, request_key, photo_uuid):
    """set_member_approval (removed in Task 2, replaced by revision-bound
    approve_card) used to stamp approved_photo_uuid/member_approved_at
    directly; roundup_snapshot's candidate query now reads a consent row on
    the welcome request's current revision instead (Task 8), so this
    records the same subject consent approve_card would have left. The
    `photo_uuid` argument is kept for call-site compatibility -- the
    revision already carries the subject's primary approved photo from
    create_candidate."""
    subject = tx.execute(
        "SELECT subject_person_id FROM publishing_queue WHERE request_key = %(rk)s LIMIT 1",
        dict(rk=request_key)).fetchone()
    rev = current_revision(tx, request_key)
    record_consent(tx, rev['id'], subject['subject_person_id'], 'subject')


def _make_eligible(make_person, name='Elig', gender='Woman'):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""
            UPDATE person SET spotlight_opt_in = TRUE, spotlight_opt_in_at = NOW(),
                   ahavah_verification_tier = 'bronze', date_of_birth = '1990-01-01',
                   deletion_requested_at = NULL, spotlight_last_featured_at = NULL
             WHERE id = %(id)s""", dict(id=p['id']))
        # photo has NOT NULL blurhash and hash columns with no default (checked \d photo);
        # uuid is a text column, and a real photo id is a 64-character hex string
        # (upload_photo mints them with secrets.token_hex(32)), so the fixture does too.
        tx.execute("""
            INSERT INTO photo (uuid, person_id, position, moderation_status, blurhash, hash)
            VALUES (%(u)s, %(id)s, 1, 'approved', 'testblurhash', gen_random_uuid()::text)""", dict(u=secrets.token_hex(32), id=p['id']))
    return p


def test_snapshot_lists_only_approved_newcomers(make_person):
    a = _make_eligible(make_person, name='Approved', gender='Woman')
    b = _make_eligible(make_person, name='NotApproved', gender='Woman')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=a['id'], caption='c', created_by='t')
        photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s", dict(id=a['id'])).fetchone()['u']
        _stamp_member_approval(tx, rk, photo)
        create_candidate(tx, kind='welcome', subject_person_id=b['id'], caption='c', created_by='t')
        tx.execute("UPDATE person SET country = 'GB' WHERE id = %(id)s", dict(id=a['id']))
        tx.execute("UPDATE person SET country = 'US' WHERE id = %(id)s", dict(id=b['id']))
        # Task 8: roundup_snapshot only ever tiles when the flag is on.
        set_setting(tx, 'roundup_tiles_enabled', 'true')
        try:
            snap = roundup_snapshot(tx, days=7)
        finally:
            set_setting(tx, 'roundup_tiles_enabled', 'false')
    names = [t['first_name'] for t in snap['tiles']]
    assert 'Approved' in names and 'NotApproved' not in names
    assert snap['count'] >= 2 and snap['countries'] >= 2
    assert all(t['photo_url'].endswith('.jpg') for t in snap['tiles'])


def test_snapshot_caps_tiles_at_four(make_person):
    # `_make_eligible` opens its own api_tx (via the make_person fixture and
    # its own UPDATE/INSERT), so every person must be created BEFORE the
    # transaction below opens -- the shared api connection lock is not
    # reentrant, and calling `_make_eligible` while already inside a `with
    # api_tx()` block deadlocks the whole test process (see task-11-report.md).
    people = [_make_eligible(make_person, name=f'T{i}', gender='Woman') for i in range(5)]
    with api_tx() as tx:
        for p in people:
            rk = create_candidate(tx, kind='welcome', subject_person_id=p['id'], caption='c', created_by='t')
            photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s", dict(id=p['id'])).fetchone()['u']
            _stamp_member_approval(tx, rk, photo)
        set_setting(tx, 'roundup_tiles_enabled', 'true')
        try:
            assert len(roundup_snapshot(tx, days=7)['tiles']) <= 4
        finally:
            set_setting(tx, 'roundup_tiles_enabled', 'false')


def test_snapshot_is_count_only_by_default(make_person):
    a = _make_eligible(make_person, name='CountOnly', gender='Woman')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=a['id'], caption='c', created_by='t')
        photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s", dict(id=a['id'])).fetchone()['u']
        _stamp_member_approval(tx, rk, photo)
        set_setting(tx, 'roundup_tiles_enabled', 'false')
        snap = roundup_snapshot(tx)
        assert snap['tiles'] == [] and snap['count'] >= 1


def test_snapshot_tiles_only_when_enabled(make_person):
    a = _make_eligible(make_person, name='TileWhenOn', gender='Woman')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=a['id'], caption='c', created_by='t')
        photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s", dict(id=a['id'])).fetchone()['u']
        _stamp_member_approval(tx, rk, photo)
        set_setting(tx, 'roundup_tiles_enabled', 'true')
        try:
            assert len(roundup_snapshot(tx)['tiles']) >= 1
        finally:
            set_setting(tx, 'roundup_tiles_enabled', 'false')


def test_reissued_revision_without_consent_drops_candidate(make_person):
    """Task 8 fix round 1 (ruling 3): _Q_CANDIDATES is scoped to the
    welcome request's CURRENT revision. A re-issued revision (any
    create_revision call, e.g. a caption edit) never copies consent rows
    across, so a member who consented to revision 1 must drop out of
    roundup candidacy the moment revision 2 exists without a consent row
    of its own -- their old consent must never quietly carry over."""
    a = _make_eligible(make_person, name='Reissued', gender='Woman')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=a['id'], caption='c', created_by='t')
        photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s", dict(id=a['id'])).fetchone()['u']
        _stamp_member_approval(tx, rk, photo)
        set_setting(tx, 'roundup_tiles_enabled', 'true')
        try:
            names = [t['first_name'] for t in roundup_snapshot(tx)['tiles']]
            assert 'Reissued' in names
            # A caption edit re-issues the revision; create_revision never
            # copies consent rows onto the new one.
            create_revision(tx, rk, caption='new caption', photo_uuid=photo,
                            participants=[], channels=['facebook', 'instagram'], created_by='t')
            names = [t['first_name'] for t in roundup_snapshot(tx)['tiles']]
            assert 'Reissued' not in names
        finally:
            set_setting(tx, 'roundup_tiles_enabled', 'false')


# ---------------------------------------------------------------------------
# Health review, 13 Oct 2026 (finding 2): staff accounts are not new members.
# The W41 roundup said "4 joined" because admin account 126 signed up that
# week and the roundup left out only the test addresses.
# ---------------------------------------------------------------------------

def _make_staff(tx, person_id):
    tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(id)s",
               dict(id=person_id))


def test_a_staff_account_is_not_counted_as_a_new_member(make_person):
    staff = make_person(name='RoundupStaff')
    with api_tx() as tx:
        # Tuvalu, so the country the staff account brings is its own.
        tx.execute("UPDATE person SET country = 'TV' WHERE id = %(id)s", dict(id=staff['id']))
        before = roundup_snapshot(tx)
        _make_staff(tx, staff['id'])
        after = roundup_snapshot(tx)
    assert after['count'] == before['count'] - 1
    assert 'Tuvalu' in before['country_names']
    assert 'Tuvalu' not in after['country_names']
    assert after['countries'] == before['countries'] - 1


def test_a_staff_account_is_never_tiled(make_person):
    staff = _make_eligible(make_person, name='StaffTile', gender='Woman')
    with api_tx() as tx:
        rk = create_candidate(tx, kind='welcome', subject_person_id=staff['id'], caption='c', created_by='t')
        photo = tx.execute("SELECT uuid::text AS u FROM photo WHERE person_id = %(id)s",
                           dict(id=staff['id'])).fetchone()['u']
        _stamp_member_approval(tx, rk, photo)
        _make_staff(tx, staff['id'])
        set_setting(tx, 'roundup_tiles_enabled', 'true')
        try:
            names = [t['first_name'] for t in roundup_snapshot(tx)['tiles']]
        finally:
            set_setting(tx, 'roundup_tiles_enabled', 'false')
    assert 'StaffTile' not in names


def test_totals_can_be_taken_as_of_a_past_moment(make_person):
    """A roundup describes the week before it was created. Rebuilding one
    later (scripts/regenerate_roundup.py) must count that week, not the
    seven days before the rebuild."""
    from datetime import datetime, timedelta, timezone
    from service.spotlight.roundup import roundup_totals

    as_of = datetime.now(timezone.utc) - timedelta(days=30)
    with api_tx() as tx:
        before = roundup_totals(tx, as_of=as_of)['count']
    inside = make_person(name='InsideWeek')
    after_it = make_person(name='AfterWeek')
    staff = make_person(name='StaffInsideWeek')
    with api_tx() as tx:
        for pid, offset in ((inside['id'], -2), (after_it['id'], 1), (staff['id'], -1)):
            tx.execute("UPDATE person SET sign_up_time = (%(t)s::timestamptz + make_interval(days => %(d)s)) AT TIME ZONE 'UTC' "
                       "WHERE id = %(id)s", dict(t=as_of, d=offset, id=pid))
        _make_staff(tx, staff['id'])
        after = roundup_totals(tx, as_of=as_of)['count']
    # The member two days inside the week counts; the one who joined a day
    # after it, and the staff account inside it, do not.
    assert after == before + 1
