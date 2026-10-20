"""Migration 0071, gatherings (TEC-1845). Idempotent, as the deploy may run
it more than once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0071_events.sql').read_text(encoding='utf-8')

def _cols(table):
    with api_tx() as tx:
        return {r['column_name'] for r in tx.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %(t)s",
            dict(t=table)).fetchall()}

def test_runs_twice():
    with api_tx() as tx:
        tx.execute(SQL)
        tx.execute(SQL)

def test_the_tables_and_their_columns():
    assert {'id', 'name', 'kind', 'email', 'normalized_email', 'city', 'country', 'about',
            'verified_at', 'approved_at', 'approved_by', 'revoked_at', 'created_at'} <= _cols('organiser')
    assert {'organiser_id', 'token_hash', 'expires_at'} <= _cols('organiser_link')
    assert {'id', 'slug', 'organiser_id', 'title', 'starts_at', 'ends_at', 'tz', 'tz_label', 'mode',
            'city', 'country', 'region', 'venue', 'venue_visibility', 'online_url', 'description',
            'capacity', 'tags', 'feast', 'show_going', 'cover_key', 'status', 'flag_reason',
            'paused_at', 'ahavah_attending', 'cancel_note', 'changed_at', 'change_before',
            'change_after', 'published_at', 'created_at', 'updated_at'} <= _cols('event')
    assert {'id', 'event_id', 'name', 'email', 'normalized_email', 'party_size', 'status',
            'confirmed_at', 'token_hash', 'confirm_by', 'share_email_with_organiser',
            'marketing_consent', 'source', 'person_id', 'lead_id', 'new_address', 'attended_at',
            'resends', 'digested_at', 'erased_at', 'created_at'} <= _cols('event_rsvp')
    assert {'event_id', 'day', 'views'} <= _cols('event_view_day')
    assert {'gathering', 'dates', 'place', 'numbers', 'contact_name', 'contact_email', 'status',
            'notes', 'created_at', 'updated_at'} <= _cols('ahavah_invite_request')
    assert 'organiser_id' in _cols('email_outbox')

def test_status_and_mode_are_checked():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO organiser (name, kind, email, normalized_email) "
                       "VALUES ('X', 'church', 'x@a.invalid', 'x@a.invalid')")

def test_an_outbox_row_names_exactly_one_recipient():
    # unsub_scope is NOT NULL (0046) and Postgres checks that before the
    # recipient check, so the row carries one.
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO email_outbox (campaign, campaign_id, email, payload, unsub_scope) "
                       "VALUES ('event_digest', 'x', 'x@a.invalid', '{}'::jsonb, 'notifications')")
