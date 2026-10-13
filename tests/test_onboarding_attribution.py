"""Where a member came from is written at onboarding (finding 42).

26 of 27 members who joined since August had no source. The web keeps the
first touch on the visitor's device and sends it, with the answer to "How
did you hear about Ahavah?", on POST /finish-onboarding
(ahavah-web src/lib/onboarding-attribution.ts). The API:

  1. keeps the accepted first-touch values on person.first_touch and the
     answer on person.heard_about;
  2. writes person.lead_source from them: utm_source, else 'invite' for an
     invite code, else the referring host. A source the onboardee already
     carries (the marriage checklist's) is kept;
  3. drops unknown keys and oversized, empty or unwritable values, and
     never fails onboarding because of them.
"""
from __future__ import annotations

from database import api_tx

TOUCH = {
    'utm_source': 'Facebook',
    'utm_medium': 'paid_social',
    'utm_campaign': 'oct-launch',
    'utm_content': 'video-1',
    'utm_term': 'torah marriage',
    'referrer_host': 'l.facebook.com',
    'code': 'ABC2345',
    'first_seen_at': '2026-10-01T12:00:00.000Z',
}


def _row(person_id: int) -> dict:
    with api_tx() as tx:
        return tx.execute(
            'SELECT lead_source, first_touch, heard_about FROM person WHERE id = %(i)s',
            dict(i=person_id),
        ).fetchone()


def _ok(r):
    assert r.status_code == 200, r.get_data(as_text=True)


def test_the_first_touch_and_the_answer_are_kept(finish_onboarding):
    r, pid = finish_onboarding(dict(first_touch=TOUCH, heard_about='  A friend at my assembly  '))
    _ok(r)
    row = _row(pid)
    assert row['first_touch'] == TOUCH
    assert row['heard_about'] == 'A friend at my assembly'
    assert row['lead_source'] == 'facebook'


def test_an_invite_code_without_utm_reads_as_invite(finish_onboarding):
    r, pid = finish_onboarding(dict(
        first_touch={'code': 'ABC2345', 'referrer_host': 'wa.me'}, heard_about=None))
    _ok(r)
    assert _row(pid)['lead_source'] == 'invite'


def test_a_referrer_alone_names_the_host(finish_onboarding):
    r, pid = finish_onboarding(dict(first_touch={'referrer_host': 'WWW.Google.com'}))
    _ok(r)
    assert _row(pid)['lead_source'] == 'www.google.com'


def test_nothing_sent_leaves_every_field_empty(finish_onboarding):
    r, pid = finish_onboarding(dict(first_touch=None, heard_about=None))
    _ok(r)
    assert _row(pid) == dict(lead_source=None, first_touch=None, heard_about=None)

    r, pid = finish_onboarding({})
    _ok(r)
    assert _row(pid) == dict(lead_source=None, first_touch=None, heard_about=None)


def test_the_checklist_source_is_kept(finish_onboarding):
    r, pid = finish_onboarding(dict(first_touch={'utm_source': 'instagram'}),
                               lead_source='marriage_checklist')
    _ok(r)
    row = _row(pid)
    assert row['lead_source'] == 'marriage_checklist'
    assert row['first_touch'] == {'utm_source': 'instagram'}


def test_values_up_to_200_code_points_are_kept_and_longer_ones_dropped(finish_onboarding):
    emoji_200 = '\U0001F600' * 200          # 200 code points, 400 UTF-16 units
    r, pid = finish_onboarding(dict(
        first_touch={'utm_campaign': emoji_200, 'utm_term': 'x' * 201,
                     'utm_source': 'newsletter'},
        heard_about='y' * 201,
    ))
    _ok(r)
    row = _row(pid)
    assert row['first_touch'] == {'utm_campaign': emoji_200, 'utm_source': 'newsletter'}
    assert row['heard_about'] is None

    r, pid = finish_onboarding(dict(heard_about='z' * 200))
    _ok(r)
    assert _row(pid)['heard_about'] == 'z' * 200


def test_unknown_keys_and_wrong_types_are_dropped(finish_onboarding):
    r, pid = finish_onboarding(dict(
        first_touch={'utm_source': 42, 'gclid': 'abc', 'utm_medium': ['email'],
                     'utm_campaign': '   ', 'referrer_host': 'news.example.org',
                     'first_seen_at': 'last tuesday'},
        heard_about={'answer': 'friend'},
    ))
    _ok(r)
    row = _row(pid)
    assert row['first_touch'] == {'referrer_host': 'news.example.org'}
    assert row['heard_about'] is None
    assert row['lead_source'] == 'news.example.org'


def test_a_first_touch_that_is_not_an_object_is_ignored(finish_onboarding):
    for touch in ('utm_source=facebook', ['facebook'], 7, True):
        r, pid = finish_onboarding(dict(first_touch=touch, heard_about=12))
        _ok(r)
        assert _row(pid) == dict(lead_source=None, first_touch=None, heard_about=None)


def test_values_postgres_cannot_store_never_fail_onboarding(finish_onboarding):
    r, pid = finish_onboarding(dict(
        first_touch={'utm_source': 'bad\x00value', 'utm_medium': 'lone\ud800half',
                     'utm_campaign': 'kept'},
        heard_about='nul\x00here',
    ))
    _ok(r)
    row = _row(pid)
    assert row['first_touch'] == {'utm_campaign': 'kept'}
    assert row['heard_about'] is None
    assert row['lead_source'] is None
