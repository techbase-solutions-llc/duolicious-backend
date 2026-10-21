"""What an alert looks for, and the words for it (TEC-1845)."""
from __future__ import annotations

from pathlib import Path

import pytest

from service.matchmaker import MatchmakerError
from service.matchmaker.criteria import (
    clean_member_criteria,
    clean_visitor_criteria,
    summary_line,
    visitor_words,
)
from service.matchmaker.regions import codes_in, region_of

ROOT = Path(__file__).resolve().parent.parent


def test_every_country_maps_to_a_continent():
    import json, pycountry
    table = json.loads((ROOT / 'service/matchmaker/continents.json').read_text(encoding='utf-8'))
    assert {c.alpha_2 for c in pycountry.countries} == set(table)
    assert (region_of('US'), region_of('JM'), region_of('MX'), region_of('BR'),
            region_of('UG'), region_of('GB'), region_of('RU'), region_of('TR'), region_of('FJ')) == (
        'north-america', 'north-america', 'north-america', 'south-america',
        'africa', 'europe', 'europe', 'asia', 'oceania')
    assert region_of(None) is None and region_of('XX') is None
    assert 'JM' in codes_in(['north-america']) and 'GB' not in codes_in(['north-america'])


def test_a_full_list_is_no_filter():
    c = clean_member_criteria(dict(age_min=26, age_max=34, torah_levels=['learning', 'beginner', 'intermediate', 'experienced']))
    assert c['torah_levels'] == []


@pytest.mark.parametrize('raw,field', [
    (dict(age_min=17, age_max=30), 'age_min'), (dict(age_min=40, age_max=30), 'age_min'),
    (dict(countries=['Narnia']), 'countries'), (dict(shabbats=['sunday']), 'shabbats'),
    (dict(polygyny=['open']), 'polygyny'),
])
def test_a_bad_criterion_is_refused(raw, field):
    with pytest.raises(MatchmakerError) as e:
        clean_member_criteria({'age_min': 26, 'age_max': 34, **raw})
    assert e.value.reason == 'bad_criteria' and e.value.extra == {'field': field}


def test_choosing_countries_clears_a_region():
    c = clean_member_criteria(dict(age_min=26, age_max=34, regions=['europe'], countries=['jm', 'BB']))
    assert c['countries'] == ['JM', 'BB'] and c['regions'] == []
    c = clean_member_criteria(dict(age_min=26, age_max=34, regions=['europe']))
    assert c['regions'] == ['europe'] and c['countries'] == []


def test_the_words_match_the_export():
    assert summary_line(dict(age_min=26, age_max=34, countries=[], regions=[])) == 'Ages 26 to 34, anywhere.'
    assert summary_line(dict(age_min=26, age_max=34, countries=['JM', 'BB', 'US'], regions=[])) == \
        'Ages 26 to 34, in 3 countries.'
    assert summary_line(dict(age_min=26, age_max=34, countries=[], regions=['north-america'])) == \
        'Ages 26 to 34, in North America.'
    assert visitor_words(dict(looking_for='man', age_min=26, age_max=34, region='north-america')) == \
        'a man aged 26 to 34 in North America'
    assert visitor_words(dict(looking_for='woman', age_min=30, age_max=40, region=None)) == \
        'a woman aged 30 to 40'


def test_a_visitor_criterion_is_checked():
    assert clean_visitor_criteria(dict(looking_for='woman', age_min=30, age_max=40)) == \
        dict(looking_for='woman', age_min=30, age_max=40, region=None)
    for raw, field in ((dict(looking_for='both', age_min=30, age_max=40), 'looking_for'),
                       (dict(looking_for='man', age_min=30, age_max=40, region='mars'), 'region'),
                       (dict(looking_for='man', age_min=30, age_max=81), 'age_max')):
        with pytest.raises(MatchmakerError) as e:
            clean_visitor_criteria(raw)
        assert e.value.extra == {'field': field}


def test_no_criterion_is_plural_marriage():
    """Plural marriage is left out of every tool (global constraint)."""
    for name in ('criteria.py', 'regions.py'):
        assert 'polyg' not in (ROOT / 'service/matchmaker' / name).read_text(encoding='utf-8').lower()
