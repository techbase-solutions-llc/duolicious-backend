"""The source taxonomy (TEC-1845).

The Sources table compares a game player with an event guest only if both
are written the same way. These pin every shape: tool:*, event:{slug},
alert:visitor, intro, mentor, referral:{code}, utm:{source}/{campaign} and
site:{host}.
"""
from __future__ import annotations

import pytest

from service.leads.sources import (EVENT_SLUG_MAX, canonical_tool_source, event_source,
                                   is_lead_source, referral_source, site_source,
                                   source_kind, utm_label)
from service.person.attribution import lead_source_from


def test_a_utm_touch_is_named_by_its_source_and_campaign():
    assert lead_source_from({'utm_source': 'Facebook', 'utm_campaign': 'Event'}) == 'utm:facebook/event'
    assert lead_source_from({'utm_source': 'newsletter'}) == 'utm:newsletter'


def test_an_invite_code_is_a_referral_by_its_code():
    assert lead_source_from({'code': 'abc2345', 'referrer_host': 'wa.me'}) == 'referral:ABC2345'


def test_a_referrer_alone_is_a_site():
    assert lead_source_from({'referrer_host': 'WWW.Google.com'}) == 'site:www.google.com'


def test_a_touch_with_nothing_to_name_is_none():
    assert lead_source_from(None) is None
    assert lead_source_from({'first_seen_at': '2026-10-01T00:00:00+00:00'}) is None


def test_the_checklist_old_name_reads_as_tool_checklist():
    assert canonical_tool_source('marriage_checklist') == 'tool:checklist'
    assert canonical_tool_source('tool:game-us') == 'tool:game-us'
    assert canonical_tool_source('tool:roulette') is None
    assert canonical_tool_source(None) is None


@pytest.mark.parametrize('value,ok', [
    ('tool:game-me', True), ('tool:game-us', True), ('tool:knows-me', True),
    ('tool:checklist', True), ('alert:visitor', True), ('event:sukkot-2027', True),
    ('event:' + 'a' * EVENT_SLUG_MAX, True),
    ('event:' + 'a' * (EVENT_SLUG_MAX + 1), False), ('event:Sukkot', False),
    ('event:', False), ('intro', False), ('mentor', False),
    ('utm:facebook/event', False), ('referral:ABC2345', False),
    ('', False), (None, False), (7, False),
])
def test_only_pre_join_sources_may_be_a_lead(value, ok):
    assert is_lead_source(value) is ok


def test_an_event_source_needs_a_slug():
    assert event_source('sukkot-2027') == 'event:sukkot-2027'
    for bad in ('Sukkot', 'a b', '-x', 'x-', 'a--b', 'a' * (EVENT_SLUG_MAX + 1), '', None):
        with pytest.raises(ValueError, match='bad_slug'):
            event_source(bad)


def test_the_kind_is_the_part_before_the_colon():
    assert source_kind('event:sukkot-2027') == 'event'
    assert source_kind('utm:facebook/event') == 'utm'
    assert source_kind('intro') == 'intro'
    assert source_kind(None) == 'unknown'
    assert source_kind('') == 'unknown'


def test_the_helpers_store_one_case():
    assert referral_source(' abc2345 ') == 'referral:ABC2345'
    assert site_source(' WA.me ') == 'site:wa.me'
    assert utm_label(' Instagram ', '') == 'utm:instagram'
    assert utm_label('Instagram', ' Profile ') == 'utm:instagram/profile'
