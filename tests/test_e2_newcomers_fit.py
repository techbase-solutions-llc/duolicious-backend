"""E2 names the week's newcomers the reader is looking for (16 Oct 2026).

The weekly email listed everyone who joined that week to every reader, so a
man looking for a woman read a list of the men who had joined. Each reader
now sees the newcomers inside their own gender and age preferences, by the
rule service/growth/queries.count_newcomers_since counts with (the personal
line's "N new people who fit what you are looking for"). When none of the
week's newcomers fit, the reader sees the list every reader saw before, so
the email still says who joined and never claims a match.
"""
import pytest

from database import api_tx
from emails import send_community_weekly as e2


def _person(make_person, name, gender, born='1990-01-01'):
    p = make_person(name=name, gender=gender)
    with api_tx() as tx:
        tx.execute("""UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                             date_of_birth = %(b)s
                       WHERE id = %(i)s""",
                   dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid", b=born))
    return p


def _looking_for(person_id, gender, min_age=None, max_age=None):
    with api_tx() as tx:
        tx.execute("DELETE FROM search_preference_gender WHERE person_id = %(p)s", dict(p=person_id))
        tx.execute("""INSERT INTO search_preference_gender (person_id, gender_id)
                      SELECT %(p)s, id FROM gender WHERE name = %(g)s""", dict(p=person_id, g=gender))
        tx.execute("DELETE FROM search_preference_age WHERE person_id = %(p)s", dict(p=person_id))
        if min_age is not None or max_age is not None:
            tx.execute("""INSERT INTO search_preference_age (person_id, min_age, max_age)
                          VALUES (%(p)s, %(lo)s, %(hi)s)""", dict(p=person_id, lo=min_age, hi=max_age))


def _row(p):
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s", dict(i=p['id'])).fetchone()['email']
    return dict(person_id=p['id'], email=email, name='x', week=e2._week_context())


@pytest.fixture(params=[False, True], ids=['plain', 'personal'])
def personal(request, monkeypatch):
    if request.param:
        monkeypatch.setenv('AHAVAH_E2_PERSONAL_ENABLED', '1')
    else:
        monkeypatch.delenv('AHAVAH_E2_PERSONAL_ENABLED', raising=False)
    return request.param


def test_a_reader_sees_the_newcomers_they_are_looking_for(make_person, personal):
    reader = _person(make_person, 'FitReader', 'Man')
    _looking_for(reader['id'], 'Woman')
    _person(make_person, 'Fitwoman', 'Woman')
    _person(make_person, 'Othermanjoined', 'Man')
    _subject, html = e2.build_for(_row(reader))
    assert 'Fitwoman' in html
    assert 'Othermanjoined' not in html


def test_age_preferences_count_too(make_person, personal):
    reader = _person(make_person, 'AgeReader', 'Man')
    _looking_for(reader['id'], 'Woman', min_age=25, max_age=40)
    _person(make_person, 'Inrange', 'Woman', born='1995-06-01')
    _person(make_person, 'Toomature', 'Woman', born='1960-06-01')
    _subject, html = e2.build_for(_row(reader))
    assert 'Inrange' in html
    assert 'Toomature' not in html


def test_with_nobody_who_fits_the_reader_sees_everyone_who_joined(make_person, personal):
    reader = _person(make_person, 'NoFitReader', 'Man')
    _looking_for(reader['id'], 'Woman', min_age=119, max_age=120)
    _person(make_person, 'Joinedwoman', 'Woman')
    _person(make_person, 'Joinedman', 'Man')
    _subject, html = e2.build_for(_row(reader))
    assert 'Joinedwoman' in html and 'Joinedman' in html
    assert 'No new members this week' not in html


def test_the_reader_is_never_listed_as_their_own_newcomer(make_person, personal):
    reader = _person(make_person, 'Selfreader', 'Woman')
    _looking_for(reader['id'], 'Woman')
    _person(make_person, 'Anotherwoman', 'Woman')
    _subject, html = e2.build_for(_row(reader))
    assert 'Anotherwoman' in html
    assert 'Selfreader' not in html
