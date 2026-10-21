"""Migration 0074 (TEC-1897): the records the acting-on-the-community
design needs that the database did not keep. The deploy runs each file once,
but the test fixtures run it at every session start, so every test here runs
it twice first."""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from database import api_tx

_MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0074_admin_community.sql'


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply()
    _apply()


def _report(make_person):
    """A report as the app files it: the skipped row's trigger (0072) writes
    the person_report row."""
    a, b = make_person(name='Reporter'), make_person(name='Reported')
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
               VALUES (%(a)s, %(b)s, TRUE, 'spam')""",
            dict(a=a['id'], b=b['id']))
    return a, b


def _resolve(a, b, outcome: str, note: str = '') -> None:
    with api_tx() as tx:
        tx.execute(
            """UPDATE person_report
                  SET outcome = %(o)s, note = %(n)s, resolved_at = NOW(),
                      resolved_by_uuid = gen_random_uuid(), resolved_by_email = 'x@example.com'
                WHERE reporter_id = %(a)s AND reported_id = %(b)s""",
            dict(a=a['id'], b=b['id'], o=outcome, n=note))


def test_the_file_waits_at_most_5_seconds_for_a_lock():
    lines = [ln.strip() for ln in _MIGRATION.read_text(encoding='utf-8').splitlines()
             if ln.strip() and not ln.strip().startswith('--')]
    assert lines[0] == "SET lock_timeout = '5s';"
    assert lines[-1] == 'RESET lock_timeout;'


def test_a_report_starts_unresolved(make_person):
    a, b = _report(make_person)
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT outcome, note, resolved_at FROM person_report
                WHERE reporter_id = %(a)s AND reported_id = %(b)s""",
            dict(a=a['id'], b=b['id'])).fetchone()
    assert row == dict(outcome=None, note=None, resolved_at=None)


def test_a_resolution_takes_only_the_three_outcomes(make_person):
    a, b = _report(make_person)
    with pytest.raises(psycopg.errors.CheckViolation):
        _resolve(a, b, 'banned')
    _resolve(a, b, 'dismissed')


def test_a_note_is_at_most_1000_characters(make_person):
    a, b = _report(make_person)
    with pytest.raises(psycopg.errors.CheckViolation):
        _resolve(a, b, 'warned', 'x' * 1001)
    _resolve(a, b, 'warned', 'x' * 1000)


def test_the_alert_log_holds_one_row_per_alert_and_key():
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'test' AND alert_key = 'k'")
        first = tx.execute("""INSERT INTO admin_alert_log (alert, alert_key) VALUES ('test', 'k')
                              ON CONFLICT DO NOTHING RETURNING alert""").fetchone()
        second = tx.execute("""INSERT INTO admin_alert_log (alert, alert_key) VALUES ('test', 'k')
                               ON CONFLICT DO NOTHING RETURNING alert""").fetchone()
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'test'")
    assert first is not None and second is None


def test_the_alert_preference_knows_only_the_report_alert():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO admin_alert_pref (alert, enabled) VALUES ('anything', TRUE)")


def test_the_report_email_preference_starts_on():
    """The report email is live (17db55a), and the owner asked for it (21 Oct
    2026), so "Email me" starts on. A rerun never turns it back on."""
    with api_tx() as tx:
        before = tx.execute("SELECT enabled FROM admin_alert_pref WHERE alert = 'report'").fetchone()
        tx.execute("UPDATE admin_alert_pref SET enabled = FALSE WHERE alert = 'report'")
    try:
        _apply()
        with api_tx('read committed') as tx:
            after = tx.execute("SELECT enabled FROM admin_alert_pref WHERE alert = 'report'").fetchone()
        assert after['enabled'] is False
    finally:
        with api_tx() as tx:
            tx.execute("UPDATE admin_alert_pref SET enabled = %(e)s WHERE alert = 'report'",
                       dict(e=before['enabled']))
    with api_tx('read committed') as tx:
        default = tx.execute(
            """SELECT column_default FROM information_schema.columns
                WHERE table_name = 'admin_alert_pref' AND column_name = 'enabled'""").fetchone()
    assert default['column_default'] == 'true'


def test_a_photo_stored_from_now_on_has_an_upload_time(make_person, add_photo):
    p = make_person(name='Uploader')
    uuid = add_photo(p['id'])
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT uploaded_at FROM photo WHERE uuid = %(u)s", dict(u=uuid)).fetchone()
        default = tx.execute(
            """SELECT column_default FROM information_schema.columns
                WHERE table_name = 'photo' AND column_name = 'uploaded_at'""").fetchone()
    assert row['uploaded_at'] is not None
    assert 'now()' in default['column_default']


def test_the_presence_and_error_tables_exist():
    with api_tx('read committed') as tx:
        names = {r['table_name'] for r in tx.execute(
            """SELECT table_name FROM information_schema.tables
                WHERE table_name IN ('member_online_day', 'api_error_tally')""").fetchall()}
    assert names == {'member_online_day', 'api_error_tally'}


def test_the_report_and_send_log_indexes_exist():
    with api_tx('read committed') as tx:
        names = {r['indexname'] for r in tx.execute(
            """SELECT indexname FROM pg_indexes
                WHERE indexname IN ('idx__person_report__unresolved', 'email_send_log_campaign_idx')""").fetchall()}
    assert names == {'idx__person_report__unresolved', 'email_send_log_campaign_idx'}


def test_a_rerun_adds_no_second_constraint():
    with api_tx('read committed') as tx:
        n = tx.execute(
            """SELECT count(*) AS n FROM pg_constraint
                WHERE conrelid = 'person_report'::regclass AND contype = 'c'""").fetchone()['n']
    assert n == 2  # the outcome and the note


def test_a_replaced_photo_takes_a_new_upload_time(make_person, monkeypatch):
    """An upload at a position that already holds a photo is an upsert. It
    must restart the upload time, or "Photo waiting" dates the new photo by
    the one it replaced. The app's own function, with the object store stubbed
    as tests/test_onboarding_freshness.py does."""
    import base64
    from io import BytesIO
    from types import SimpleNamespace

    from PIL import Image

    import duotypes as t
    import service.person as sp

    monkeypatch.setattr(sp, 'put_image_in_object_store', lambda *a, **k: None)

    def png(colour) -> str:
        buf = BytesIO()
        Image.new('RGB', (64, 64), color=colour).save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    p = make_person(name='Replacer')
    s = SimpleNamespace(person_id=p['id'])
    sp.patch_profile_info(t.PatchProfileInfo(base64_file=dict(
        position=1, base64=png((10, 20, 30)), top=0, left=0)), s)
    with api_tx() as tx:
        tx.execute("UPDATE photo SET uploaded_at = NOW() - INTERVAL '2 days' WHERE person_id = %(p)s",
                   dict(p=p['id']))
    sp.patch_profile_info(t.PatchProfileInfo(base64_file=dict(
        position=1, base64=png((200, 50, 90)), top=0, left=0)), s)
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT uploaded_at > NOW() - INTERVAL '1 minute' AS fresh
                 FROM photo WHERE person_id = %(p)s AND position = 1""", dict(p=p['id'])).fetchone()
    assert row['fresh'] is True
