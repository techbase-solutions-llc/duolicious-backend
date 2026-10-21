"""The calendar file (TEC-1845): RFC 5545, the location only for a
confirmed guest."""
from datetime import datetime, timedelta, timezone

import pytest

from service.events.ics import calendar_file

START = datetime(2026, 11, 8, 0, tzinfo=timezone.utc)
EVENT = dict(slug='marriage-preparation-evening-a1b2c3', title='Marriage preparation evening',
             starts_at=START, ends_at=START + timedelta(hours=3), status='published')
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def _lines(text):
    assert '\n' not in text.replace('\r\n', '')
    return text.split('\r\n')


def test_the_file_is_valid_rfc_5545():
    text = calendar_file(EVENT, location=None, url='https://ahavah.app/e/x', now=NOW)
    lines = _lines(text)
    assert lines[0] == 'BEGIN:VCALENDAR' and 'VERSION:2.0' in lines
    assert any(l.startswith('PRODID:') for l in lines)
    assert lines.count('BEGIN:VEVENT') == 1 and lines.count('END:VEVENT') == 1
    assert text.endswith('END:VCALENDAR\r\n')
    assert 'UID:marriage-preparation-evening-a1b2c3@ahavah.app' in lines
    assert 'DTSTART:20261108T000000Z' in lines and 'DTEND:20261108T030000Z' in lines
    assert 'DTSTAMP:20261020T120000Z' in lines and 'URL:https://ahavah.app/e/x' in lines
    assert not any(l.startswith('LOCATION') for l in lines)


def test_text_is_escaped_and_folded():
    title = ('A, long; title\\ with\nevery character that needs escaping ' * 3)[:120]
    text = calendar_file(dict(EVENT, title=title), location='Hall, 14 Elm Street; Dallas',
                         url='https://ahavah.app/e/x', now=NOW)
    lines = _lines(text)
    assert all(len(l.encode('utf-8')) <= 75 for l in lines)
    unfolded = text.replace('\r\n ', '')
    assert 'SUMMARY:A\\, long\\; title\\\\ with\\nevery' in unfolded
    assert 'LOCATION:Hall\\, 14 Elm Street\\; Dallas' in unfolded


def test_a_cancelled_gathering_says_cancelled():
    text = calendar_file(dict(EVENT, status='cancelled'), location=None, url='https://ahavah.app/e/x', now=NOW)
    assert 'STATUS:CANCELLED' in _lines(text)
    assert 'STATUS:CONFIRMED' in _lines(calendar_file(EVENT, location=None, url='u', now=NOW))


@pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')
def test_the_location_is_left_out_until_confirmed(client, published, monkeypatch):
    tokens = {}
    monkeypatch.setattr('service.events.mail.queue_confirm', lambda tx, rid, token: tokens.update(t=token))
    slug = published(venue='14 Elm Street')
    client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah', email='ics@ahavah-test.invalid', party_size=1))
    r = client.get(f"/rsvp/{tokens['t']}/calendar.ics")
    assert r.status_code == 200 and r.headers['Content-Type'] == 'text/calendar; charset=utf-8'
    assert r.headers['Content-Disposition'] == 'attachment; filename="gathering.ics"'
    assert 'LOCATION' not in r.get_data(as_text=True)
    client.get(f"/rsvp/confirm/{tokens['t']}")
    assert 'LOCATION:14 Elm Street' in client.get(f"/rsvp/{tokens['t']}/calendar.ics").get_data(as_text=True)
