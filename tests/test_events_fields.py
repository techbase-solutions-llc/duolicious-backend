"""Field rules for a gathering (TEC-1845): slugs, regions, feasts, tags, a
draft, text flags and the words for its time."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from service.events import EventError
from service.events import fields as f

ROOT = Path(__file__).resolve().parent.parent
GOOD = dict(title='Marriage preparation evening', starts_at='2026-11-08T00:00:00+00:00',
            ends_at='2026-11-08T03:00:00+00:00', tz='America/Chicago', tz_label='Central Time',
            mode='in_person', city='Dallas', country='United States',
            venue='Grace Fellowship hall, 14 Elm Street, Dallas', venue_visibility='confirmed',
            description='An evening for single believers who hope to marry.', capacity=40,
            tags=['singles_welcome', 'marriage_preparation'], feast=None, show_going=False)

def test_every_country_in_the_location_list_has_a_continent():
    countries = {r['country'] for r in json.loads((ROOT / 'locations/locations.json').read_text(encoding='utf-8'))}
    table = json.loads((ROOT / 'service/events/continents.json').read_text(encoding='utf-8'))
    assert countries == set(table)
    assert set(table.values()) <= set(f.REGIONS) - {'online'}
    assert (f.region_for('United States'), f.region_for('Jamaica'), f.region_for('Brazil'),
            f.region_for('Uganda'), f.region_for('United Kingdom'), f.region_for('Fiji')) == (
        'north-america', 'north-america', 'south-america', 'africa', 'europe', 'oceania')

def test_slugs_fit_the_source_taxonomy():
    from service.leads.sources import event_source
    s = f.slug_for('A marriage preparation weekend for singles and the families who support them', 'a1b2c3')
    assert s == 'a-marriage-preparation-weekend-for-a1b2c3' and len(s) <= 45
    assert event_source(s) == f'event:{s}'
    assert f.slug_for('!!!', 'a1b2c3') == 'gathering-a1b2c3'
    assert f.slug_for('Sukkot: Atlanta', 'ff0011') == 'sukkot-atlanta-ff0011'

def test_a_good_draft_is_kept_and_gets_its_region():
    d = f.clean_draft(GOOD)
    assert d['region'] == 'north-america' and d['title'] == GOOD['title']

@pytest.mark.parametrize('change,reason', [
    (dict(title=''), 'bad_title'),
    (dict(ends_at='2026-11-07T23:00:00+00:00'), 'bad_time'),
    (dict(starts_at='2026-11-08T00:00:00'), 'bad_time'),
    (dict(ends_at='2026-11-20T00:00:00+00:00'), 'bad_time'),
    (dict(tz='Mars/Olympus'), 'bad_tz'),
    (dict(country='Atlantis'), 'bad_country'),
    (dict(mode='online', online_url='http://meet.example.com/x'), 'bad_online_url'),
    (dict(capacity=0), 'bad_capacity'),
    (dict(tags=['adults_only']), 'bad_tags'),
    (dict(feast='hanukkah'), 'bad_feast'),
])
def test_a_bad_field_is_refused(change, reason):
    with pytest.raises(EventError) as e:
        f.clean_draft({**GOOD, **change})
    assert e.value.reason == reason and e.value.status == 400

def test_an_online_gathering_drops_the_place():
    d = f.clean_draft({**GOOD, 'mode': 'online', 'online_url': 'https://meet.example.com/ahavah-talk'})
    assert d['region'] == 'online' and d['city'] is None and d['venue'] is None

def test_text_is_cleaned_and_flagged():
    assert f.clean_text('  Hello\x00 <b>there</b>\n\n\n\nfriends ', 200, multiline=True) == 'Hello <b>there</b>\n\nfriends'
    assert f.text_flag('A shared meal and time to talk.') is None
    # Scores 0.95 on analyze_message (checked 20 Oct 2026).
    assert f.text_flag('Send me money by Western Union and gift cards, my darling') == 'scam'

def test_the_feasts_are_the_biblical_english_names_in_order():
    assert list(f.FEASTS.values()) == ['Passover', 'Unleavened Bread', 'Firstfruits', 'Pentecost',
                                       'Trumpets', 'Day of Atonement', 'Tabernacles', 'Last Great Day']

def test_time_words_match_the_export():
    s = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)
    assert f.when_words(s, e, 'America/Chicago', 'Central Time') == ('Saturday 7 November 2026', '6pm to 9pm, Central Time')
    s2 = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)
    e2 = datetime(2026, 11, 12, 20, 15, tzinfo=timezone.utc)
    assert f.when_words(s2, e2, 'Europe/London', 'UK time') == ('Thursday 12 November 2026', '7pm to 8.15pm, UK time')
    s3 = datetime(2026, 11, 7, 23, 0, tzinfo=timezone.utc)
    assert f.when_words(s3, s3.replace(hour=23, minute=59), 'Europe/London', 'UK time')[1] == '11pm to 11.59pm, UK time'
    assert f.when_words(datetime(2026, 11, 8, 6, tzinfo=timezone.utc), datetime(2026, 11, 8, 9, tzinfo=timezone.utc),
                        'America/Chicago', 'Central Time')[1] == 'midnight to 3am, Central Time'

def test_time_words_across_midnight_and_across_days():
    # 6pm to 2am the next day, and a gathering over three days (interface notes).
    s = datetime(2026, 11, 8, 0, tzinfo=timezone.utc)
    assert f.when_words(s, datetime(2026, 11, 8, 8, tzinfo=timezone.utc),
                        'America/Chicago', 'Central Time')[1] == '6pm to 2am, Central Time'
    assert f.when_words(datetime(2026, 12, 4, 6, tzinfo=timezone.utc), datetime(2026, 12, 6, 13, tzinfo=timezone.utc),
                        'Africa/Nairobi', 'East Africa Time') == (
        'Friday 4 December 2026', '9am, East Africa Time, to Sunday 6 December, 4pm')
