"""Which gatherings a member sees in their email (TEC-1845, gatherings in
the member emails, Task 3): the member's region by their country, plus
every online gathering, at most 3, by start. Read once per run for every
region, never once per member.

Every test reads as of a far-future `now`, with its gatherings just after
it, so gatherings other tests (or other runs on the shared database) left
30 days ahead are already started for this read and never show."""
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.events import fields as f
from service.events import public
from service.matchmaker.regions import REGIONS

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')

NOW = datetime(2031, 3, 3, 12, 0, tzinfo=timezone.utc)


def _at(days: float) -> datetime:
    return NOW + timedelta(days=days)


def _online(published, **over):
    return published(**dict(dict(mode='online', city=None, country=None,
                                 online_url='https://meet.example.com/near', starts_at=_at(2)), **over))


def _lists():
    with api_tx('read committed') as tx:
        return public.gatherings_for_members(tx, now=NOW)


def _slugs(cards):
    return [c['slug'] for c in cards]


def test_a_member_sees_their_region_and_online(published):
    dallas = published(country='United States', city='Dallas', starts_at=_at(1))
    london = published(country='United Kingdom', city='London', starts_at=_at(1.5))
    talk = _online(published)
    cards, online_only = public.for_member(_lists(), 'BB')
    assert _slugs(cards) == [dallas, talk] and london not in _slugs(cards)
    assert online_only is False


def test_three_at_most_by_start(published):
    late = published(starts_at=_at(5))
    first = published(starts_at=_at(1))
    third = _online(published, starts_at=_at(3))
    second = published(starts_at=_at(2))
    cards, _ = public.for_member(_lists(), 'US')
    assert _slugs(cards) == [first, second, third] and late not in _slugs(cards)


@pytest.mark.parametrize('country', [None, '', 'Barbados'])
def test_a_member_with_no_country_sees_online_only(published, country):
    published(starts_at=_at(1))
    talk = _online(published)
    cards, online_only = public.for_member(_lists(), country)
    assert _slugs(cards) == [talk]
    # With no region the heading's "near you" claims nothing, so no line.
    assert online_only is False


def test_none_at_all_gives_an_empty_list():
    lists = _lists()
    for country in ('BB', 'GB', None):
        assert public.for_member(lists, country) == ([], False)
    assert set(lists) == set(REGIONS) | {None, public.IN_PERSON}
    assert lists[public.IN_PERSON] == set()


def test_online_only_is_true_only_with_a_region_and_every_card_online(published):
    talk = _online(published)
    published(country='United Kingdom', city='London', starts_at=_at(1))
    lists = _lists()
    assert public.for_member(lists, 'US') == (public.for_member(lists, 'US')[0], True)
    assert _slugs(public.for_member(lists, 'US')[0]) == [talk]
    assert public.for_member(lists, 'GB')[1] is False
    assert public.for_member(lists, None)[1] is False


def test_draft_pending_paused_and_cancelled_are_left_out(published):
    for over in (dict(status='draft', published_at=None), dict(status='pending', published_at=None),
                 dict(paused_at=datetime.now(timezone.utc)), dict(status='cancelled')):
        published(starts_at=_at(1), **over)
    shown = published(starts_at=_at(2))
    assert _slugs(public.for_member(_lists(), 'US')[0]) == [shown]


def test_a_gathering_that_has_started_is_left_out(published):
    published(starts_at=NOW - timedelta(minutes=30), ends_at=NOW + timedelta(hours=2))
    shown = published(starts_at=_at(1))
    assert _slugs(public.for_member(_lists(), 'US')[0]) == [shown]


def test_a_full_gathering_is_left_out(published, confirmed_guest):
    full = published(starts_at=_at(1), capacity=2)
    confirmed_guest(full, party_size=2)
    roomy = published(starts_at=_at(1.5), capacity=3)
    confirmed_guest(roomy, party_size=2)
    assert _slugs(public.for_member(_lists(), 'US')[0]) == [roomy]


def test_no_card_carries_the_venue_or_the_call_link(published):
    published(starts_at=_at(1), venue='14 Elm Street', venue_visibility='confirmed')
    _online(published, online_url='https://meet.example.com/secret-call')
    text = repr(_lists())
    assert '14 Elm Street' not in text and 'secret-call' not in text


def test_one_query_for_every_region(published):
    published(starts_at=_at(1))
    _online(published)

    class Counting:
        def __init__(self, tx):
            self.tx, self.calls = tx, 0

        def execute(self, *a, **kw):
            self.calls += 1
            return self.tx.execute(*a, **kw)

    with api_tx('read committed') as tx:
        counted = Counting(tx)
        lists = public.gatherings_for_members(counted, now=NOW)
    assert counted.calls == 1 and len(lists['north-america']) == 2


def test_each_card_carries_its_date_block(published):
    # Saturday 8 March 2031, 00:00 UTC, is Friday 7 March in Chicago.
    slug = published(starts_at=datetime(2031, 3, 8, 0, 0, tzinfo=timezone.utc))
    card = next(c for c in _lists()['north-america'] if c['slug'] == slug)
    assert card['date'] == ('Fri', '7', 'Mar')


def test_the_date_block_is_in_the_gatherings_own_zone():
    # Friday 7 November 2031, 21:00 UTC, is 3pm in Chicago (CST from 2 Nov).
    assert f.date_block(datetime(2031, 11, 7, 21, 0, tzinfo=timezone.utc), 'America/Chicago') == ('Fri', '7', 'Nov')
    # Saturday 8 November, 01:00 UTC, is still Friday evening there.
    assert f.date_block(datetime(2031, 11, 8, 1, 0, tzinfo=timezone.utc), 'America/Chicago') == ('Fri', '7', 'Nov')
    assert f.date_block(datetime(2031, 11, 8, 1, 0, tzinfo=timezone.utc), 'Europe/London') == ('Sat', '8', 'Nov')
    import zoneinfo
    with pytest.raises(zoneinfo.ZoneInfoNotFoundError):
        f.date_block(datetime(2031, 11, 8, 1, 0, tzinfo=timezone.utc), 'Not/AZone')


def test_a_bad_zone_leaves_the_card_without_a_date_not_the_read(published):
    """The read is the whole run's: one row with a zone the server does
    not know must not stop it. Its card has no date, and the email drops
    that card (tests/test_e2_gatherings.py)."""
    bad = published(starts_at=_at(1), tz='Not/AZone')
    good = published(starts_at=_at(2))
    cards = _lists()['north-america']
    assert _slugs(cards) == [bad, good]
    assert 'date' not in cards[0] and cards[1]['date'][1:] == ('5', 'Mar')
