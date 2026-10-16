"""Migration 0066: the growth foundations' schema (TEC-1845).

Pins what later tasks rely on: one lead per address and source, lead mail
in the outbox with exactly one recipient, the prompt bank, the three new
publishing kinds and lead_source on one taxonomy. The deploy may run the
file more than once, so every test runs it twice first.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0066_growth_foundations.sql')


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply()
    _apply()


def _address() -> str:
    return f'm0066-{uuid4().hex[:12]}@example.org'


def _insert_lead(tx, email: str, source: str) -> int:
    return tx.execute(
        """INSERT INTO lead (email, normalized_email, source)
           VALUES (%(e)s, %(e)s, %(s)s) RETURNING id""",
        dict(e=email, s=source)).fetchone()['id']


def _delete_leads(email: str) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = %(e)s', dict(e=email))


def test_an_address_is_one_lead_per_source():
    email = _address()
    try:
        with api_tx() as tx:
            _insert_lead(tx, email, 'tool:game-me')
            _insert_lead(tx, email, 'event:sukkot-gathering')
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _insert_lead(tx, email, 'tool:game-me')
    finally:
        _delete_leads(email)


def test_consent_cannot_be_stored_without_its_wording():
    email = _address()
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute(
                    """INSERT INTO lead (email, normalized_email, source, marketing_consent)
                       VALUES (%(e)s, %(e)s, 'alert:visitor', TRUE)""", dict(e=email))
    finally:
        _delete_leads(email)


def _outbox_row(tx, *, person_id, lead_id, email: str) -> None:
    tx.execute(
        """INSERT INTO email_outbox (campaign, campaign_id, person_id, lead_id, email,
                                     payload, unsub_scope)
           VALUES ('test-0066', 'run-1', %(p)s, %(l)s, %(e)s, '{}'::jsonb, 'news')""",
        dict(p=person_id, l=lead_id, e=email))


def test_an_outbox_row_names_exactly_one_recipient(make_person):
    person = make_person(name='M0066')
    email = _address()
    with api_tx() as tx:
        lead_id = _insert_lead(tx, email, 'alert:visitor')
    try:
        for person_id, lid in ((None, None), (person['id'], lead_id)):
            with pytest.raises(psycopg.errors.CheckViolation):
                with api_tx() as tx:
                    _outbox_row(tx, person_id=person_id, lead_id=lid, email=email)
    finally:
        _delete_leads(email)


def test_a_lead_is_queued_once_per_run_and_its_mail_goes_with_it():
    email = _address()
    with api_tx() as tx:
        lead_id = _insert_lead(tx, email, 'alert:visitor')
        _outbox_row(tx, person_id=None, lead_id=lead_id, email=email)
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _outbox_row(tx, person_id=None, lead_id=lead_id, email=email)
    finally:
        _delete_leads(email)
    with api_tx() as tx:
        left = tx.execute('SELECT count(*) AS n FROM email_outbox WHERE lead_id = %(l)s',
                          dict(l=lead_id)).fetchone()['n']
    assert left == 0, 'deleting a lead must delete the mail queued for it'


@pytest.mark.parametrize('kind', ['event', 'prompt', 'tool'])
def test_the_new_publishing_kinds_are_accepted(kind):
    rk = f'm0066:{uuid4().hex[:8]}'
    try:
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO publishing_queue (request_key, kind, platform, caption, status, created_by)
                   VALUES (%(rk)s, %(k)s, 'facebook', 'c', 'cancelled', 'test')""",
                dict(rk=rk, k=kind))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM publishing_queue WHERE request_key = %(rk)s', dict(rk=rk))


def test_the_prompt_bank_takes_a_slug_key_and_short_text():
    key = f'm0066-{uuid4().hex[:8]}'
    try:
        with api_tx() as tx:
            tx.execute("""INSERT INTO prompt_bank (key, text, category)
                          VALUES (%(k)s, 'How I keep Sabbath', 'sabbath')""", dict(k=key))
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO prompt_bank (key, text, category)
                              VALUES ('Not A Slug', 'x', 'sabbath')""")
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO prompt_bank (key, text, category)
                              VALUES (%(k)s, %(t)s, 'sabbath')""",
                           dict(k=f'{key}-long', t='x' * 121))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM prompt_bank WHERE key LIKE %(k)s', dict(k=f'{key}%'))


# (lead_source before, first_touch, lead_source after)
_LEGACY = [
    ('marriage_checklist', None, 'tool:checklist'),
    ('invite', {'code': 'abc2345'}, 'referral:ABC2345'),
    ('invite', None, 'referral'),
    ('facebook', {'utm_source': 'Facebook', 'utm_campaign': 'Oct-Launch'}, 'utm:facebook/oct-launch'),
    ('instagram', {'utm_source': 'instagram'}, 'utm:instagram'),
    ('www.google.com', {'referrer_host': 'WWW.Google.com'}, 'site:www.google.com'),
    ('event:sukkot-gathering', None, 'event:sukkot-gathering'),
    (None, None, None),
]


def test_lead_source_moves_onto_one_taxonomy(make_person):
    ids = []
    for before, touch, _ in _LEGACY:
        p = make_person(name='M0066Source')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET lead_source = %(s)s, first_touch = %(t)s::jsonb
                    WHERE id = %(i)s""",
                dict(s=before, t=json.dumps(touch) if touch is not None else None, i=p['id']))
        ids.append(p['id'])
    _apply()
    _apply()
    with api_tx() as tx:
        after = [tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=i)).fetchone()['lead_source'] for i in ids]
    assert after == [want for _, _, want in _LEGACY]
