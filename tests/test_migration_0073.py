"""Migration 0073, the matchmaker (TEC-1845). Idempotent, as the deploy may
run it more than once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0073_matchmaker.sql').read_text(encoding='utf-8')

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
    assert {'id', 'person_id', 'lead_id', 'first_name', 'criteria', 'notify_push', 'notify_email', 'active',
            'confirmed_at', 'confirm_token_hash', 'confirm_by', 'resends', 'stop_token_hash', 'counted_since',
            'last_sent_at', 'likes_told_at', 'paused_at', 'created_at', 'updated_at'} <= _cols('match_alert')
    assert {'alert_id', 'audience', 'members', 'window_start', 'window_end', 'by_push', 'by_email'} <= _cols('match_alert_notice')
    assert {'sender_person_id', 'sender_key', 'sender_first_name', 'recipient_email', 'recipient_key', 'note',
            'referral_code', 'status', 'flag_reason', 'joined_person_id', 'reviewed_by', 'reviewed_at',
            'sent_at', 'erased_at'} <= _cols('recommendation')
    assert {'introducer_person_id', 'a_person_id', 'b_person_id', 'note', 'status', 'flag_reason',
            'a_response', 'b_response', 'a_responded_at', 'b_responded_at', 'closes_at', 'opened_at',
            'matched_at', 'introducer_told_at', 'reviewed_by', 'reviewed_at', 'note_erased_at'} <= _cols('introduction')
    assert {'email', 'normalized_email', 'last_seen_at'} <= _cols('mentor_account')
    assert {'single_person_id', 'mentor_email', 'mentor_normalized_email', 'relation', 'mentor_account_id',
            'invite_token_hash', 'invite_expires_at', 'confirmed_at', 'revoked_at'} <= _cols('mentor_link')
    assert {'token_hash', 'mentor_account_id', 'expires_at'} <= _cols('mentor_session')
    assert {'single_person_id', 'other_person_id', 'other_person_uuid', 'mentor_link_id', 'shared_at', 'revoked_at'} <= _cols('shared_conversation')
    assert {'mentor_account_id', 'single_person_id', 'about_person_id', 'note'} <= _cols('mentor_note')
    assert 'no_mentor_shared_matches' in _cols('person')
    assert {'recommendation_id', 'mentor_link_id'} <= _cols('email_outbox')

def test_an_alert_has_exactly_one_owner():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO match_alert (criteria) VALUES ('{}'::jsonb)")

def test_an_outbox_row_still_names_exactly_one_recipient():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO email_outbox (campaign, campaign_id, email, payload, unsub_scope) "
                       "VALUES ('mm_recommend', 'x', 'x@a.invalid', '{}'::jsonb, 'notifications')")

def test_a_single_has_one_live_mentor_link(make_person):
    p = make_person()
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            for _ in range(2):
                tx.execute("INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, "
                           "relation, invite_expires_at) VALUES (%(p)s, 'r@a.invalid', 'r@a.invalid', 'parent', NOW())",
                           dict(p=p['id']))
