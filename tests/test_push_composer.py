"""The push composer (TEC-2182; docs/plans/2026-11-19-push-composer.md).

The test database is shared, so every audience here is narrowed to a
country code no real member has, and checked for the people each test
makes. Composer rows and composer push_send_log rows are cleared around
each test, since the day caps count every send on the day.

Never hold an api_tx open while calling the Flask client: the api
connection is one per process behind a lock that is not reentrant.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.notifications import composer
from service.notifications.composer import Refused

NOON = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)   # Monday, 12:00 Barbados, 11:00 New York
COUNTRY = 'QZ'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clear():
    with api_tx() as tx:
        tx.execute("DELETE FROM push_composer_send")
        tx.execute("DELETE FROM push_send_log WHERE campaign = 'composer'")
        tx.execute("DELETE FROM push_tap WHERE src = 'apush'")


@pytest.fixture(autouse=True)
def _clean():
    _clear()
    yield
    _clear()


@pytest.fixture
def member(make_person):
    def _make(name, *, push=True, tz='UTC', gender='Woman', country=COUNTRY, **cols):
        p = make_person(name=name, gender=gender, email=f'{name.lower()}-{uuid.uuid4().hex[:8]}@ahavah-test.invalid')
        with api_tx() as tx:
            tx.execute("UPDATE person SET country = %(c)s WHERE id = %(i)s", dict(c=country, i=p['id']))
            for col, val in cols.items():
                tx.execute(f"UPDATE person SET {col} = %(v)s WHERE id = %(i)s", dict(v=val, i=p['id']))
            if push:
                tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                              VALUES (%(i)s, %(e)s, 'k', 'a', %(tz)s)""",
                           dict(i=p['id'], e=f'https://push.test/{uuid.uuid4()}', tz=tz))
        return p
    return _make


def _set(person_id, sql, **binds):
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET {sql} WHERE id = %(i)s", dict(i=person_id, **binds))


def _ids(filters=None, testers_only=False):
    f = {'countries': [COUNTRY], **(filters or {})} if not testers_only else (filters or {})
    with api_tx('read committed') as tx:
        return {r['person_id'] for r in composer.audience(tx, composer.clean_filters(f), testers_only)}


def _bearer(person_id):
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=person_id)).fetchone()['email']
        tx.execute("""INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
                      VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
                   dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email, p=person_id))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def admin(make_person):
    p = make_person(name='ComposerAdmin', email=f'composer-admin-{uuid.uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                      VALUES (%(i)s, %(e)s, 'k', 'a', 'UTC')""", dict(i=p['id'], e=f'https://push.test/{uuid.uuid4()}'))
    return dict(p, headers=_bearer(p['id']))


class _Sent(list):
    devices = {'n': 1}


@pytest.fixture
def pushes(monkeypatch):
    """Every push handed to a sender, delivered at once to `devices` devices."""
    import service.notifications as notifications
    sent = _Sent()
    sent.devices = devices = {'n': 1}

    def fake_member(person_id, push, kind):
        sent.append(dict(person_id=person_id, kind=kind, **push))
        return devices['n']

    def fake_one(person_id, payload, kind):
        sent.append(dict(person_id=person_id, kind=kind, **payload))
        return devices['n']

    monkeypatch.setattr(composer, '_push_member', fake_member)
    monkeypatch.setattr(composer, '_push_one', fake_one)
    monkeypatch.setattr(composer, 'run_soon', lambda sid: sent.append(dict(run_soon=sid)))
    monkeypatch.setattr(notifications, 'PUSH_ENABLED', True)
    monkeypatch.setenv('AHAVAH_PUSH_COMPOSER_ENABLED', '1')
    return sent


def _to(sent, person_id):
    return [s for s in sent if s.get('person_id') == person_id and s['kind'].startswith('composer:')]


FIELDS = dict(title='Before the Sabbath', body='Say hello to your matches today.', url='/matches',
              filters={'countries': [COUNTRY]}, testers_only=False)


def _draft(**over):
    fields = composer.clean_draft(dict(FIELDS, **over))
    with api_tx() as tx:
        return composer.create_draft(tx, fields, None)['id']


def _tested(admin_id, **over):
    sid = _draft(**over)
    assert composer.test_send(sid, admin_id, now=NOON)['delivered']
    return sid


def _send(sid, when='now', mode='barbados', now=NOON):
    with api_tx() as tx:
        return composer.send(tx, sid, when, mode, now=now)


def _row(sid):
    with api_tx('read committed') as tx:
        return composer.get(tx, sid)


def _recipients(sid):
    with api_tx('read committed') as tx:
        return {r['person_id']: (r['state'], r['reason']) for r in tx.execute(
            "SELECT person_id, state, reason FROM push_composer_recipient WHERE send_id = %(i)s::uuid",
            dict(i=sid)).fetchall()}


def _logged(person_id):
    with api_tx('read committed') as tx:
        return [r['campaign_id'] for r in tx.execute(
            "SELECT campaign_id FROM push_send_log WHERE campaign = 'composer' AND person_id = %(p)s",
            dict(p=person_id)).fetchall()]


# ---------------------------------------------------------------------------
# who
# ---------------------------------------------------------------------------

def test_each_filter_selects_what_it_says(member, add_photo):
    man = member('FMan', gender='Man')
    woman = member('FWoman', gender='Woman', region='St Michael')
    other = member('FOther', country='QY')
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - interval '20 days', "
                   "sign_up_time = NOW() - interval '60 days' WHERE id = %(i)s", dict(i=man['id']))
        tx.execute("UPDATE person SET last_online_time = NOW() - interval '1 day', "
                   "sign_up_time = NOW() - interval '2 days', ahavah_verification_tier = 'silver', "
                   "entitlements = ARRAY['premium']::text[], subscription_expires_at = NOW() + interval '30 days', "
                   "spotlight_opt_in = TRUE WHERE id = %(i)s", dict(i=woman['id']))
    add_photo(woman['id'])

    assert {man['id'], woman['id']} <= _ids()
    assert other['id'] not in _ids()
    assert other['id'] in _ids(dict(countries=['QY']))
    assert _ids(dict(gender='Man')) & {man['id'], woman['id']} == {man['id']}
    assert _ids(dict(regions=['st michael'])) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(online_within_days=7)) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(offline_for_days=14)) & {man['id'], woman['id']} == {man['id']}
    assert _ids(dict(joined_within_days=7)) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(has_photo=True)) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(has_photo=False)) & {man['id'], woman['id']} == {man['id']}
    assert _ids(dict(tiers=['silver'])) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(tiers=['none'])) & {man['id'], woman['id']} == {man['id']}
    assert _ids(dict(premium=True)) & {man['id'], woman['id']} == {woman['id']}
    assert _ids(dict(premium=False)) & {man['id'], woman['id']} == {man['id']}
    assert _ids(dict(spotlight=True)) & {man['id'], woman['id']} == {woman['id']}
    # Filters combine with AND.
    assert _ids(dict(gender='Woman', premium=False)) & {man['id'], woman['id']} == set()


def test_an_expired_premium_is_not_premium(member):
    p = member('FLapsed')
    _set(p['id'], "entitlements = ARRAY['premium']::text[], subscription_expires_at = NOW() - interval '1 day'")
    assert p['id'] not in _ids(dict(premium=True))
    assert p['id'] in _ids(dict(premium=False))


def test_the_fixed_exclusions_always_hold(member, make_person):
    from service.unsubscribe import stamp_unsubscribed
    ok = member('XOk')
    admin = member('XAdmin')
    mod = member('XMod')
    tester = member('XTester')
    deleted = member('XDeleted')
    deactivated = member('XDeactivated')
    inactive = member('XInactive')
    unsub = member('XUnsub')
    toggled = member('XToggled')
    nopush = member('XNoPush', push=False)
    suppressed = make_person(name='XSuppressed')      # the fixture's @example.com address
    _set(suppressed['id'], "country = %(c)s", c=COUNTRY)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, %(e)s, 'k', 'a')""", dict(i=suppressed['id'], e=f'https://push.test/{uuid.uuid4()}'))
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=unsub['id'])).fetchone()['email']
        assert stamp_unsubscribed(tx, 'campaigns', email)
        tx.execute("INSERT INTO notification_preference (person_id, push_announcements) VALUES (%(i)s, FALSE)",
                   dict(i=toggled['id']))
    _set(admin['id'], "roles = ARRAY['admin']::text[]")
    _set(mod['id'], "roles = ARRAY['mod']::text[]")
    _set(tester['id'], "roles = ARRAY['tester']::text[]")
    _set(deleted['id'], "deletion_requested_at = NOW()")
    _set(deactivated['id'], "admin_deactivated_at = NOW()")
    _set(inactive['id'], "activated = FALSE")

    ids = _ids()
    assert ok['id'] in ids
    for p in (admin, mod, tester, deleted, deactivated, inactive, unsub, toggled, nopush, suppressed):
        assert p['id'] not in ids


def test_a_testers_only_send_reaches_testers_only_and_refuses_filters(member):
    tester = member('TTester')
    staff_tester = member('TStaffTester')
    plain = member('TMember')
    _set(tester['id'], "roles = ARRAY['tester']::text[]")
    _set(staff_tester['id'], "roles = ARRAY['tester', 'admin']::text[]")
    ids = _ids(testers_only=True)
    assert tester['id'] in ids
    assert plain['id'] not in ids
    assert staff_tester['id'] not in ids          # staff are always left out
    with pytest.raises(Refused) as e:
        composer.clean_draft(dict(FIELDS, testers_only=True))
    assert e.value.reason == 'testers_only_with_filters'
    assert composer.clean_draft(dict(FIELDS, filters={}, testers_only=True))['testers_only']


def test_unknown_and_malformed_filters_are_refused():
    for bad in ({'colour': 'red'}, {'gender': 'Other'}, {'countries': ['Barbados']}, {'online_within_days': 5},
                {'tiers': ['platinum']}, {'premium': 'yes'}, {'joined_within_days': 0},
                {'online_within_days': 7, 'offline_for_days': 14}):
        with pytest.raises(Refused):
            composer.clean_filters(bad)


# ---------------------------------------------------------------------------
# the words and the tap target
# ---------------------------------------------------------------------------

def test_the_url_allow_list_holds(monkeypatch):
    assert composer.check_url('/discover') == '/discover'
    assert composer.check_url('/matches?tab=likes') == '/matches?tab=likes'
    for bad in ('/chat', '/likes', '/your-ahavah', 'https://example.com', '/discover?x=1', '//evil.test', None, 3):
        with pytest.raises(Refused) as e:
            composer.check_url(bad)
        assert e.value.reason == 'invalid_url'
    # A page behind a switch that is off is refused in words of its own.
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED', raising=False)
    with pytest.raises(Refused) as e:
        composer.check_url('/events')
    assert e.value.reason == 'url_not_open'
    assert composer.tap_url('/matches?tab=likes', 'abc') == '/matches?tab=likes&src=apush&send=abc'
    assert composer.tap_url('/discover', 'abc') == '/discover?src=apush&send=abc'


def test_the_title_and_body_limits_and_line_breaks():
    assert composer.check_text('a' * 50, 'b' * 120) == ('a' * 50, 'b' * 120)
    # Whole characters: an accented letter is one.
    assert composer.check_text('é' * 50, 'ü' * 120)
    for title, body, problem in (('a' * 51, 'b', 'too_long'), ('a', 'b' * 121, 'too_long'),
                                 ('a\nb', 'c', 'line_break'), ('a', 'b\r\nc', 'line_break'),
                                 ('', 'b', 'required'), ('a', None, 'required'),
                                 ('Big news—today', 'b', 'dash'), ('Hello', 'Come back!', 'exclamation')):
        with pytest.raises(Refused) as e:
            composer.check_text(title, body)
        assert problem in {p['problem'] for p in e.value.detail['problems']}


# ---------------------------------------------------------------------------
# the test, the edit and the send
# ---------------------------------------------------------------------------

def test_no_send_without_a_delivered_test_and_an_edit_clears_it(member, admin, pushes):
    member('SMember')
    sid = _draft()
    with pytest.raises(Refused) as e:
        _send(sid)
    assert e.value.reason == 'test_required'

    pushes.devices['n'] = 0
    assert composer.test_send(sid, admin['id'], now=NOON) == dict(delivered=False, reason='not_delivered', send_id=sid)
    with pytest.raises(Refused):
        _send(sid)

    pushes.devices['n'] = 1
    assert composer.test_send(sid, admin['id'], now=NOON)['delivered']
    test_push = [s for s in pushes if s['kind'] == 'composer_test']
    assert test_push[-1]['person_id'] == admin['id']
    assert test_push[-1]['url'] == f'/matches?src=apush&send={sid}'
    assert _row(sid)['state'] == 'tested'

    with api_tx() as tx:
        composer.update_draft(tx, sid, composer.clean_draft(dict(FIELDS, body='Another body.')))
    assert _row(sid)['state'] == 'draft' and _row(sid)['test_delivered_at'] is None
    with pytest.raises(Refused) as e:
        _send(sid)
    assert e.value.reason == 'test_required'


def test_a_test_older_than_24_hours_no_longer_counts(member, admin, pushes):
    member('SOld')
    sid = _tested(admin['id'])
    with pytest.raises(Refused) as e:
        _send(sid, now=NOON + timedelta(hours=25))
    assert e.value.reason == 'test_required'


def test_a_send_and_a_second_press_send_each_member_once(member, admin, pushes):
    a = member('OnceA')
    b = member('OnceB')
    sid = _tested(admin['id'])
    row, repeat = _send(sid)
    assert not repeat and row['state'] == 'scheduled' and row['audience'] == 2
    again, repeat = _send(sid)
    assert repeat and again['id'] == sid

    composer.run_send(sid, NOON)
    composer.run_send(sid, NOON + timedelta(minutes=10))

    assert len(_to(pushes, a['id'])) == 1 and len(_to(pushes, b['id'])) == 1
    p = _to(pushes, a['id'])[0]
    assert p['kind'] == f'composer:{sid}' and p['url'] == f'/matches?src=apush&send={sid}'
    assert p['title'] == FIELDS['title']
    assert _logged(a['id']) == [sid]
    row = _row(sid)
    assert row['state'] == 'sent' and row['sent'] == 2 and row['held'] == 0


def test_quiet_hours_hold_a_member_in_their_own_zone(member, admin, pushes):
    day = member('QDay', tz='UTC')                     # 16:00
    night = member('QNight', tz='Pacific/Honolulu')    # 06:00
    unknown = member('QUnknown', tz=None)              # New York, 11:00
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)
    assert _to(pushes, day['id']) and _to(pushes, unknown['id'])
    assert not _to(pushes, night['id'])
    assert _recipients(sid)[night['id']] == ('held', 'quiet')
    assert _row(sid)['state'] == 'sending' and _row(sid)['held'] == 1

    composer.run_send(sid, NOON + timedelta(hours=4))   # 10:00 in Honolulu
    assert len(_to(pushes, night['id'])) == 1
    assert _row(sid)['state'] == 'sent'


def test_a_rest_period_holds_the_rest_of_a_send(member, admin, pushes, monkeypatch):
    a = member('RestA', tz='UTC')
    b = member('RestB', tz='Pacific/Honolulu')
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)
    assert _to(pushes, a['id']) and not _to(pushes, b['id'])

    # The rest period begins mid-send: B, due now, is held for it.
    monkeypatch.setattr(composer, 'resting', lambda now: True)
    composer.run_send(sid, NOON + timedelta(hours=4))
    assert not _to(pushes, b['id'])
    assert _recipients(sid)[b['id']] == ('held', 'resting')

    monkeypatch.setattr(composer, 'resting', lambda now: False)
    composer.run_send(sid, NOON + timedelta(hours=5))
    assert len(_to(pushes, b['id'])) == 1


def test_a_slot_on_a_rest_day_or_past_the_calendar_is_refused(member, admin, pushes, monkeypatch):
    import service.spotlight.restdays as rd
    member('SlotMember')
    sid = _tested(admin['id'])
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', NOON.date() + timedelta(days=3))
    with pytest.raises(Refused) as e:
        _send(sid, when=(NOON + timedelta(days=5)).replace(tzinfo=None).isoformat())
    assert e.value.reason == 'unknown'
    monkeypatch.setattr(rd, 'REST_DAYS', ((NOON + timedelta(days=2)).date(),))
    with pytest.raises(Refused) as e:
        _send(sid, when=datetime(2026, 11, 25, 10, 0).isoformat())     # the rest day itself, Barbados
    assert e.value.reason == 'rest_day'
    with pytest.raises(Refused) as e:
        _send(sid, when=datetime(2026, 11, 22, 10, 0).isoformat())     # yesterday
    assert e.value.reason == 'past'
    with pytest.raises(Refused) as e:
        _send(sid, when='2026-11-24T10:00:00', mode='member_local')    # 17:00 Barbados the 24th is the eve
    assert e.value.reason == 'rest_day'
    row, _ = _send(sid, when='2026-11-24T09:00:00')
    assert row['state'] == 'scheduled' and row['mode'] == 'barbados'


def test_send_now_is_refused_in_a_rest_period(member, admin, pushes, monkeypatch):
    import service.spotlight.restdays as rd
    member('NowRest')
    sid = _tested(admin['id'])
    monkeypatch.setattr(rd, 'REST_DAYS', (NOON.date(),))
    with pytest.raises(Refused) as e:
        _send(sid)
    assert e.value.reason == 'rest_day'


def test_member_local_time_waits_for_each_members_clock(member, admin, pushes):
    utc = member('LocalUtc', tz='UTC')                  # 16:00 at NOON
    ny = member('LocalNy', tz='America/New_York')       # 11:00 at NOON
    sid = _tested(admin['id'])
    _send(sid, when='2026-11-23T15:00:00', mode='member_local', now=NOON - timedelta(days=1) + timedelta(hours=1))
    composer.run_send(sid, NOON)
    assert _to(pushes, utc['id']) and not _to(pushes, ny['id'])
    assert _recipients(sid)[ny['id']] == ('held', 'not_yet')
    composer.run_send(sid, NOON + timedelta(hours=5))   # 16:00 in New York
    assert len(_to(pushes, ny['id'])) == 1


def test_the_hold_window_ends_as_expired_never_a_silent_drop(member, admin, pushes):
    member('ExpA', tz='UTC')
    b = member('ExpB', tz='Pacific/Honolulu')
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)
    composer.run_send(sid, NOON + composer.HOLD_WINDOW + timedelta(minutes=1))
    assert _recipients(sid)[b['id']] == ('expired', 'hold_window')
    row = _row(sid)
    assert row['state'] == 'sent' and row['sent'] == 1 and row['expired'] == 1 and row['held'] == 0


def test_a_member_who_turns_the_toggle_off_after_the_freeze_is_counted_skipped(member, admin, pushes):
    a = member('SkipA', tz='Pacific/Honolulu')
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)                        # frozen, held for quiet hours
    with api_tx() as tx:
        tx.execute("INSERT INTO notification_preference (person_id, push_announcements) VALUES (%(i)s, FALSE)",
                   dict(i=a['id']))
    composer.run_send(sid, NOON + timedelta(hours=4))
    assert not _to(pushes, a['id'])
    assert _recipients(sid)[a['id']] == ('skipped', 'left_audience')
    assert _row(sid)['skipped'] == 1 and _row(sid)['state'] == 'sent'


# ---------------------------------------------------------------------------
# caps
# ---------------------------------------------------------------------------

def test_an_audience_over_the_cap_is_refused(member, admin, pushes, monkeypatch):
    member('CapA')
    member('CapB')
    sid = _tested(admin['id'])
    monkeypatch.setenv('AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE', '1')
    with pytest.raises(Refused) as e:
        _send(sid)
    assert e.value.reason == 'over_cap' and e.value.detail == dict(most=1, count=2)
    # A setting above the Spotlight cap cannot raise it.
    monkeypatch.setenv('AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE', '5000')
    assert composer.max_audience() == composer.PUSH_CAP == 500


def test_an_empty_audience_is_refused(admin, pushes):
    sid = _tested(admin['id'])
    with pytest.raises(Refused) as e:
        _send(sid)
    assert e.value.reason == 'empty_audience'


def test_the_member_caps_skip_and_count(member, admin, pushes):
    fresh = member('MFresh')
    recent = member('MRecent')       # 1 composer push 10 hours ago
    twice = member('MTwice')         # 2 in the last 7 days, none in 72 hours
    with api_tx() as tx:
        tx.execute("INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at) "
                   "VALUES (%(p)s, 'composer', 'earlier-1', %(at)s)", dict(p=recent['id'], at=NOON - timedelta(hours=10)))
        for i, days in enumerate((4, 5)):
            tx.execute("INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at) "
                       "VALUES (%(p)s, 'composer', %(c)s, %(at)s)",
                       dict(p=twice['id'], c=f'earlier-{i + 2}', at=NOON - timedelta(days=days)))
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)
    assert _to(pushes, fresh['id'])
    assert not _to(pushes, recent['id']) and not _to(pushes, twice['id'])
    assert _recipients(sid)[recent['id']] == ('capped', 'member_cap')
    assert _row(sid)['capped'] == 2


def test_at_most_2_sends_a_barbados_day(member, admin, pushes):
    member('DayMember')
    for _ in range(2):
        _send(_tested(admin['id']))
    with pytest.raises(Refused) as e:
        _send(_tested(admin['id']))
    assert e.value.reason == 'day_limit'
    # Another day is free.
    row, _ = _send(_tested(admin['id']), when='2026-11-24T10:00:00')
    assert row['state'] == 'scheduled'


def test_the_daily_push_total_holds_the_rest(member, admin, pushes, monkeypatch):
    a = member('TotA')
    b = member('TotB')
    monkeypatch.setattr(composer, 'DAY_PUSHES', 1)
    sid = _tested(admin['id'])
    _send(sid)
    out = composer.run_send(sid, NOON)
    assert out['halted'] == 'day_cap'
    assert len(_to(pushes, a['id'])) + len(_to(pushes, b['id'])) == 1
    assert _row(sid)['halt_reason'] == 'day_cap' and _row(sid)['held'] == 1


# ---------------------------------------------------------------------------
# cancel, retries, the switch, the dry run
# ---------------------------------------------------------------------------

def test_a_cancel_releases_the_held_and_keeps_the_sent(member, admin, pushes):
    a = member('CanA', tz='UTC')
    b = member('CanB', tz='Pacific/Honolulu')
    sid = _tested(admin['id'])
    _send(sid)
    composer.run_send(sid, NOON)
    with api_tx() as tx:
        row = composer.cancel(tx, sid)
    assert row['state'] == 'cancelled' and row['sent'] == 1 and row['released'] == 1
    assert _recipients(sid) == {a['id']: ('sent', None), b['id']: ('released', 'cancelled')}
    composer.run_send(sid, NOON + timedelta(hours=4))
    assert not _to(pushes, b['id'])
    with api_tx() as tx, pytest.raises(Refused):
        composer.cancel(tx, sid)


def test_a_claim_no_device_took_is_given_back_and_tried_once_more(member, admin, pushes):
    a = member('RetryA')
    sid = _tested(admin['id'])
    _send(sid)
    pushes.devices['n'] = 0
    composer.run_send(sid, NOON)
    assert _recipients(sid)[a['id']] == ('pending', 'retry')
    assert _logged(a['id']) == []
    composer.run_send(sid, NOON + timedelta(minutes=10))
    assert _recipients(sid)[a['id']] == ('failed', 'no_device_took_it')
    assert len(_to(pushes, a['id'])) == 2
    assert _row(sid)['failed'] == 1 and _row(sid)['state'] == 'sent'


def test_a_retry_that_lands_counts_as_sent(member, admin, pushes):
    a = member('RetryOk')
    sid = _tested(admin['id'])
    _send(sid)
    pushes.devices['n'] = 0
    composer.run_send(sid, NOON)
    pushes.devices['n'] = 1
    composer.run_send(sid, NOON + timedelta(minutes=10))
    assert _recipients(sid)[a['id']] == ('sent', None)
    assert _logged(a['id']) == [sid]


def test_nothing_sends_while_the_switch_is_off(member, admin, pushes, monkeypatch):
    a = member('OffA')
    sid = _tested(admin['id'])
    _send(sid)
    monkeypatch.delenv('AHAVAH_PUSH_COMPOSER_ENABLED')
    assert composer.tick(NOON) == {}
    assert composer.run_send(sid, NOON)['halted'] == 'switch_off'
    assert not _to(pushes, a['id']) and _row(sid)['state'] == 'scheduled'


def test_a_missing_vapid_key_halts_and_says_so(member, admin, pushes, monkeypatch):
    import service.notifications as notifications
    member('VapidA')
    sid = _tested(admin['id'])
    _send(sid)
    monkeypatch.setattr(notifications, 'PUSH_ENABLED', False)
    assert composer.run_send(sid, NOON)['halted'] == 'vapid_missing'
    assert _row(sid)['halt_reason'] == 'vapid_missing'


def test_the_tick_passes_each_due_send(member, admin, pushes):
    a = member('TickA')
    sid = _tested(admin['id'])
    _send(sid)
    later = _tested(admin['id'])
    _send(later, when='2026-11-24T10:00:00')
    out = composer.tick(NOON)
    assert set(out) == {sid}
    assert len(_to(pushes, a['id'])) == 1


def test_a_dry_run_sends_nothing_writes_nothing_and_runs_inside_no_send(member, admin, pushes, monkeypatch):
    from service.notifications import _send_to_user_blocking
    from smtp import guard
    a = member('DryA', tz='UTC')
    member('DryB', tz='Pacific/Honolulu')
    sid = _tested(admin['id'])
    seen = {}

    def probe():
        seen['no_send'] = guard.in_no_send()
        with pytest.raises(guard.SendDuringDryRun):
            _send_to_user_blocking(a['id'], dict(title='x', body='y', url='/', tag='t'), kind='composer:x')

    monkeypatch.setattr(composer, '_dry_run_probe', probe)
    before = len(pushes)
    res = composer.dry_run(send_id=sid, now=NOON)
    assert seen['no_send']
    assert res['audience'] == 2 and res['would_send_now'] == 1 and res['held']['quiet'] == 1
    assert len(pushes) == before and _recipients(sid) == {} and _logged(a['id']) == []
    assert _row(sid)['state'] == 'tested'


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

def test_routes_answer_404_while_the_switch_is_off_but_the_try_out_works(client, member, admin, pushes, monkeypatch):
    member('RouteOff')
    monkeypatch.delenv('AHAVAH_PUSH_COMPOSER_ENABLED')
    h = admin['headers']
    r = client.post('/admin/growth/push/drafts', json=FIELDS, headers=h)
    assert r.status_code == 201
    sid = r.get_json()['id']
    assert client.get('/admin/growth/push/composer', headers=h).get_json()['enabled'] is False
    assert client.post('/admin/growth/push/audience', json=dict(filters=FIELDS['filters']), headers=h).status_code == 200
    assert client.post('/admin/growth/push/test', json=dict(draft_id=sid), headers=h).get_json()['delivered']
    assert client.post('/admin/growth/push/dry-run', json=dict(draft_id=sid), headers=h).status_code == 200
    assert client.post('/admin/growth/push/send', json=dict(draft_id=sid, when='now', mode='barbados'),
                       headers=h).status_code == 404
    assert client.post(f'/admin/growth/push/{sid}/cancel', headers=h).status_code == 404
    assert client.get('/admin/growth/push/sends', headers=h).status_code == 404
    assert client.get(f'/admin/growth/push/{sid}', headers=h).status_code == 404


def test_a_member_is_refused_every_route(client, member, make_person):
    p = member('RouteMember')
    h = _bearer(p['id'])
    assert client.get('/admin/growth/push/composer', headers=h).status_code == 403
    assert client.post('/admin/growth/push/drafts', json=FIELDS, headers=h).status_code == 403
    assert client.post('/admin/growth/push/audience', json={}, headers=h).status_code == 403


def test_the_audience_route_counts_and_never_names(client, member, admin):
    a = member('AudA', tz='UTC')
    member('AudB', tz='Pacific/Honolulu')
    r = client.post('/admin/growth/push/audience', json=dict(filters=FIELDS['filters']), headers=admin['headers'])
    body = r.get_json()
    assert body['count'] == 2 and body['by_country'] == [dict(country=COUNTRY, count=2)]
    assert set(body['held_now']) == {'quiet', 'resting'}
    assert str(a['id']) not in r.get_data(as_text=True) and 'auda' not in r.get_data(as_text=True).lower()
    bad = client.post('/admin/growth/push/audience', json=dict(filters={'colour': 'red'}), headers=admin['headers'])
    assert bad.status_code == 400


def test_the_routes_send_schedule_cancel_and_audit_without_addresses(client, member, admin, pushes):
    member('AuditA')
    h = admin['headers']
    sid = client.post('/admin/growth/push/drafts', json=FIELDS, headers=h).get_json()['id']
    refused = client.post('/admin/growth/push/send', json=dict(draft_id=sid, when='now', mode='barbados'), headers=h)
    assert refused.status_code == 409 and refused.get_json()['error'] == 'test_required'
    assert client.post('/admin/growth/push/test', json=dict(draft_id=sid), headers=h).get_json()['delivered']

    when = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(composer.BARBADOS).replace(
        hour=10, minute=0, second=0, microsecond=0, tzinfo=None).isoformat()
    r = client.post('/admin/growth/push/send', json=dict(draft_id=sid, when=when, mode='barbados'), headers=h)
    assert r.status_code == 200 and r.get_json()['state'] == 'scheduled' and not r.get_json()['repeat']
    again = client.post('/admin/growth/push/send', json=dict(draft_id=sid, when=when, mode='barbados'), headers=h)
    assert again.get_json()['repeat'] is True
    assert client.get(f'/admin/growth/push/{sid}', headers=h).get_json()['results']['audience'] == 1
    assert [s['id'] for s in client.get('/admin/growth/push/sends', headers=h).get_json()['sends']] == [sid]
    c = client.post(f'/admin/growth/push/{sid}/cancel', headers=h)
    assert c.status_code == 200 and c.get_json()['state'] == 'cancelled'

    now_id = client.post('/admin/growth/push/drafts', json=dict(FIELDS, title='Another one'), headers=h).get_json()['id']
    client.post('/admin/growth/push/test', json=dict(draft_id=now_id), headers=h)
    r = client.post('/admin/growth/push/send', json=dict(draft_id=now_id, when='now', mode='barbados'), headers=h)
    assert r.status_code == 200
    assert dict(run_soon=now_id) in pushes          # sent on a thread after the commit

    with api_tx('read committed') as tx:
        rows = tx.execute("""SELECT action, metadata, target_email FROM admin_audit_log
                              WHERE metadata->>'send_id' IN (%(a)s, %(b)s)""", dict(a=sid, b=now_id)).fetchall()
    actions = sorted(r['action'] for r in rows)
    assert actions.count('push_composer_test') == 2 and 'push_composer_schedule' in actions
    assert 'push_composer_send' in actions and 'push_composer_cancel' in actions
    assert actions.count('push_composer_schedule') == 1      # the repeat press is not a second schedule
    for r in rows:
        assert r['target_email'] is None and '@' not in str(r['metadata'])
        assert {'send_id', 'filters_hash', 'audience', 'title', 'url'} <= set(r['metadata'])


def test_a_composer_tap_counts_once_per_member_per_send(client, member, admin, pushes):
    a = member('TapA')
    sid = _tested(admin['id'])
    h = _bearer(a['id'])
    for _ in range(3):
        assert client.post('/push-taps', json=dict(src='apush', send=sid), headers=h).status_code == 204
    assert client.post('/push-taps', json=dict(src='apush', send='not-a-uuid'), headers=h).status_code == 204
    assert client.post('/push-taps', json=dict(src='apush', send=str(uuid.uuid4())), headers=h).status_code == 204
    with api_tx('read committed') as tx:
        n = tx.execute("SELECT count(*)::int AS n FROM push_tap WHERE src = 'apush' AND person_id = %(p)s",
                       dict(p=a['id'])).fetchone()['n']
        row = composer.get(tx, sid)
        assert composer.public(tx, row)['results']['tapped'] == 1
    assert n == 1
    for src in ('lwpush', 'nnpush', 'uspush'):
        assert client.post('/push-taps', json=dict(src=src), headers=h).status_code == 204


def test_the_announcements_toggle_shows_patches_and_stamps(client, member, monkeypatch):
    a = member('ToggleA')
    h = _bearer(a['id'])
    monkeypatch.delenv('AHAVAH_PUSH_COMPOSER_ENABLED', raising=False)
    monkeypatch.delenv('AHAVAH_PUSH_NEWCOMERS_ENABLED', raising=False)
    assert 'push_announcements' not in client.get('/notifications/preferences', headers=h).get_json()
    monkeypatch.setenv('AHAVAH_PUSH_COMPOSER_ENABLED', '1')
    assert client.get('/notifications/preferences', headers=h).get_json()['push_announcements'] is True
    assert client.patch('/notifications/preferences', json=dict(push_announcements=False), headers=h).status_code == 204
    assert client.get('/notifications/preferences', headers=h).get_json()['push_announcements'] is False
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT push_announcements, push_announcements_off_at FROM notification_preference "
                         "WHERE person_id = %(p)s", dict(p=a['id'])).fetchone()
    assert row['push_announcements'] is False and row['push_announcements_off_at'] is not None
    assert a['id'] not in _ids()
    client.patch('/notifications/preferences', json=dict(push_announcements=True), headers=h)
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT push_announcements_off_at FROM notification_preference WHERE person_id = %(p)s",
                          dict(p=a['id'])).fetchone()['push_announcements_off_at'] is None


def test_the_send_goes_through_send_to_user_counted_as_an_announcement(monkeypatch):
    import service.notifications as notifications
    seen = {}

    def fake(person_id, title, body, url, tag, *, event_kind, kind):
        seen.update(person_id=person_id, event_kind=event_kind, kind=kind)
        return 1

    monkeypatch.setattr(notifications, 'send_to_user_counted', fake)
    assert composer._push_member(7, dict(title='t', body='b', url='/', tag='g'), 'composer:abc') == 1
    assert seen == dict(person_id=7, event_kind='announcement', kind='composer:abc')
    assert notifications._EVENT_COLUMN['announcement'] == 'push_announcements'
    assert notifications._EVENT_DEFAULTS['announcement'] is True
