"""The question line in Monday's E2 (TEC-1845, spec "Notifications", Email).

One line naming the question that went live in the last 7 days, behind
AHAVAH_E2_QUESTION_LINE_ENABLED. Left out for a member who had the launch
email in the last 7 days, which already carried the question. With the
switch off, E2 is exactly what it was.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from database import api_tx
from emails import send_community_weekly as e2
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

LINE = "This week's question: the window seat or the aisle seat? Answer in the app."


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_QUESTION_LINE_ENABLED', '1')


@pytest.fixture
def aisle(make_question):
    return make_question(labels=('The window seat', 'The aisle seat'), text='Window seat or aisle?')


def _row(make_person, name):
    p = make_person(name=name, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    return dict(person_id=p['id'], email=email, name='x', week=dict(new_members=[], total=40, spotlight=None))


def test_off_by_default_e2_has_no_question_line(make_person, aisle, drops, monkeypatch):
    monkeypatch.delenv('AHAVAH_E2_QUESTION_LINE_ENABLED', raising=False)
    drops(barbados_today(), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Off'))
    assert "This week's question" not in html


def test_on_it_names_the_question_that_went_live_this_week(make_person, aisle, drops, on):
    drops(barbados_today() - timedelta(days=1), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2On'))
    assert LINE in html


def test_a_drop_older_than_7_days_gives_no_line(make_person, aisle, drops, on):
    drops(barbados_today() - timedelta(days=8), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Old'))
    assert "This week's question" not in html


def test_no_line_for_a_member_who_had_the_launch_email_this_week(make_person, aisle, drops, on):
    drops(barbados_today(), aisle['key'])
    row = _row(make_person, 'E2Launch')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id)
                      VALUES (%(p)s, 'questions_launch', 'questions_launch')""", dict(p=row['person_id']))
    _, html = e2.build_for(row)
    assert "This week's question" not in html


def test_the_personal_e2_carries_it_too(make_person, aisle, drops, on, monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_PERSONAL_ENABLED', '1')
    drops(barbados_today(), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Personal'))
    assert LINE in html


def test_the_proof_shows_the_line_and_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n']
    subject, html = e2.preview_question_line('owner@example.org')
    with api_tx('read committed') as tx:
        after = tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n']
    assert "This week's question: mountains or the sea? Answer in the app." in html
    assert subject == 'This week on Ahavah' and after == before
