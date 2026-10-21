"""The 8-week window on who a member can introduce (TEC-1845, owner's
answers, second round, 21 Oct 2026): only people the introducer has
interacted with in the last 8 weeks, from every source. Each source is
dated by its own row:

  match       the match's created_at, or the latest message between the two
              (the introducer's chat archive, mam_message's id)
  liked       the like's created_at, either way
  viewed_you  the visited row's updated_at (their latest view of the
              introducer), a view the introducer is shown only
  map         on the introducer's map and a visited row of the introducer
              opening their profile (the map records no interaction itself)
  spotlight   the published post's time, as before

The picker and the server check share one definition, so someone just
outside the window is neither listed nor accepted.
"""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

NOTE = 'Both of you love the feasts and want a big family.'
INSIDE = '55 days 23 hours'
OUTSIDE = '56 days 1 hour'
LONG_AGO = '20 weeks'


def _sql(sql, **params):
    with api_tx() as tx:
        tx.execute(sql, params)


def _match_at(a, b, age):
    _sql("""INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
            VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int),
                    NOW() - %(age)s::interval)""", a=a['id'], b=b['id'], age=age)


def _message_at(sender, recipient, age):
    """One message, stored as the chat server does: a copy in each archive,
    the id a MAM id (microseconds since the epoch, shifted left 8 bits)."""
    _sql("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
            VALUES ((EXTRACT(EPOCH FROM NOW() - %(age)s::interval) * 1000000)::bigint * 256,
                    'O', ''::bytea, %(s)s, '', %(rj)s),
                   ((EXTRACT(EPOCH FROM NOW() - %(age)s::interval) * 1000000)::bigint * 256 + 1,
                    'I', ''::bytea, %(r)s, '', %(sj)s)""",
         s=sender['id'], r=recipient['id'], sj=sender['uuid'], rj=recipient['uuid'], age=age)


def _like_at(liker, liked, age):
    _sql("""INSERT INTO liked (liker_id, liked_id, created_at)
            VALUES (%(a)s, %(b)s, NOW() - %(age)s::interval)""", a=liker['id'], b=liked['id'], age=age)


def _visit_at(viewer, viewed, age, invisible=False):
    _sql("""INSERT INTO visited (subject_person_id, object_person_id, updated_at, invisible)
            VALUES (%(a)s, %(b)s, NOW() - %(age)s::interval, %(inv)s)""",
         a=viewer['id'], b=viewed['id'], age=age, inv=invisible)


def _put_on_map(p):
    _sql("""UPDATE person SET show_my_location = TRUE,
                   ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || '{"citySet": true}'::jsonb
             WHERE id = %(i)s""", i=p['id'])


def _spotlight_at(p, age):
    _sql('UPDATE person SET spotlight_opt_in = TRUE WHERE id = %(i)s', i=p['id'])
    _sql("""INSERT INTO publishing_queue (request_key, kind, subject_person_id, platform, status,
                                          scheduled_for)
            VALUES ('mm-window-' || %(i)s::text || '-' || %(age)s, 'member_of_week', %(i)s,
                    'instagram', 'published', NOW() - %(age)s::interval)""", i=p['id'], age=age)


def _clear_spotlight(*people):
    _sql('DELETE FROM publishing_queue WHERE subject_person_id = ANY(%(p)s)', p=[p['id'] for p in people])


# Each source: how the introducer comes to know the person `p`, `age` ago.
SOURCES = {
    'match': lambda me, p, age: _match_at(me, p, age),
    'match_message': lambda me, p, age: (_match_at(me, p, LONG_AGO), _message_at(p, me, age)),
    'liked': lambda me, p, age: _like_at(me, p, age),
    'liked_you': lambda me, p, age: _like_at(p, me, age),
    'viewed_you': lambda me, p, age: _visit_at(p, me, age),
    'map': lambda me, p, age: (_put_on_map(p), _visit_at(me, p, age)),
    'spotlight': lambda me, p, age: _spotlight_at(p, age),
}
REACH_OF = {'match_message': 'match'}


def _candidates(client, h, who):
    return client.get(f"/introductions/candidates?for={who['uuid']}", headers=h)


def _listed(client, h, who):
    r = _candidates(client, h, who)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {p['uuid']: p['reach'] for p in r.get_json()['people']}


def _suggest(client, h, a, b):
    return client.post('/introductions', headers=h, json=dict(a_uuid=a['uuid'], b_uuid=b['uuid'], note=NOTE))


@pytest.mark.parametrize('source', list(SOURCES))
def test_each_source_counts_only_within_8_weeks(client, introducer_with_two, source):
    h, miriam, _daniel, hannah = introducer_with_two()
    inside = introducer_with_two.member('Inside', 'Man', 'Woman')
    outside = introducer_with_two.member('Outside', 'Man', 'Woman')
    try:
        SOURCES[source](hannah, inside, INSIDE)
        SOURCES[source](hannah, outside, OUTSIDE)
        listed = _listed(client, h, miriam)
        assert listed.get(inside['uuid']) == REACH_OF.get(source, source)
        assert outside['uuid'] not in listed
        # The check refuses what the picker does not list, as it answers a
        # stranger, for either place in the pair.
        assert (_suggest(client, h, miriam, outside).status_code, _suggest(client, h, outside, miriam).status_code) \
            == (404, 404)
        assert _candidates(client, h, outside).status_code == 404
        assert _suggest(client, h, miriam, inside).status_code == 201
    finally:
        _clear_spotlight(inside, outside)


def test_an_old_match_with_a_recent_message_from_the_introducer_counts(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    talked = introducer_with_two.member('Talked', 'Man', 'Woman')
    _match_at(hannah, talked, LONG_AGO)
    _message_at(hannah, talked, INSIDE)
    assert _listed(client, h, miriam).get(talked['uuid']) == 'match'


def test_an_old_match_with_only_old_messages_does_not(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    quiet = introducer_with_two.member('Quiet', 'Man', 'Woman')
    _match_at(hannah, quiet, LONG_AGO)
    _message_at(quiet, hannah, OUTSIDE)
    _message_at(hannah, quiet, LONG_AGO)
    assert quiet['uuid'] not in _listed(client, h, miriam)
    assert _suggest(client, h, miriam, quiet).status_code == 404


def test_a_view_the_introducer_is_not_shown_does_not_count(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    unseen = introducer_with_two.member('Unseen', 'Man', 'Woman')
    _visit_at(unseen, hannah, INSIDE, invisible=True)
    assert unseen['uuid'] not in _listed(client, h, miriam)
    assert _suggest(client, h, miriam, unseen).status_code == 404


def test_someone_on_the_map_the_introducer_never_opened_does_not_count(client, introducer_with_two):
    h, miriam, _daniel, _hannah = introducer_with_two()
    pinned = introducer_with_two.member('Pinned', 'Man', 'Woman')
    _put_on_map(pinned)
    assert pinned['uuid'] not in _listed(client, h, miriam)
    assert _suggest(client, h, miriam, pinned).status_code == 404


def test_the_introducer_opening_a_profile_off_the_map_is_not_the_map(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    offmap = introducer_with_two.member('Offmap', 'Man', 'Woman')
    _visit_at(hannah, offmap, INSIDE)
    assert offmap['uuid'] not in _listed(client, h, miriam)
    assert _suggest(client, h, miriam, offmap).status_code == 404
