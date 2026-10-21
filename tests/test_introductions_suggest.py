"""Suggest two members (TEC-1845, 5b): only people the introducer can
already see, each told privately, every refusal the introducer could learn
from answered as a send, 5 pairs a week and each person once."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')

NOTE = 'Both of you love the feasts and want a big family.'


def _intros(introducer_id):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT * FROM introduction WHERE introducer_person_id = %(i)s ORDER BY id',
            dict(i=introducer_id)).fetchall()]


def _intro_rows(*person_ids):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            "SELECT * FROM email_outbox WHERE campaign = 'mm_intro' AND person_id = ANY(%(p)s) ORDER BY id",
            dict(p=list(person_ids))).fetchall()]


def _block(a, b):
    with api_tx() as tx:
        tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                   'VALUES (%(a)s, %(b)s, TRUE)', dict(a=a['id'], b=b['id']))


def _suggest(client, h, a, b, note=NOTE):
    return client.post('/introductions', headers=h, json=dict(a_uuid=a['uuid'], b_uuid=b['uuid'], note=note))


def _candidates(client, h, who, q=''):
    r = client.get(f"/introductions/candidates?for={who['uuid']}&q={q}", headers=h)
    return r


def test_the_picker_lists_only_people_the_introducer_can_see(client, introducer_with_two, make_person):
    h, miriam, daniel, _ = introducer_with_two()
    stranger = introducer_with_two.member('Stranger', 'Man', 'Woman')
    r = _candidates(client, h, miriam)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    uuids = {p['uuid']: p for p in body['people']}
    assert daniel['uuid'] in uuids and uuids[daniel['uuid']]['reach'] == 'match'
    assert uuids[daniel['uuid']]['reach_label'] == 'Your match' and uuids[daniel['uuid']]['first_name'] == 'Daniel'
    assert stranger['uuid'] not in uuids and miriam['uuid'] not in uuids
    assert body['for'] == {'first_name': 'Miriam'} and body['left'] == 5


def test_the_picker_offers_people_who_could_fit_the_first_person(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    woman = introducer_with_two.member('Ruth', 'Woman', 'Man')
    introducer_with_two.match(hannah, woman)
    uuids = {p['uuid'] for p in _candidates(client, h, miriam).get_json()['people']}
    assert woman['uuid'] not in uuids and daniel['uuid'] in uuids


def test_the_other_ways_the_introducer_can_see_someone(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    liked = introducer_with_two.member('Liked', 'Man', 'Woman')
    liked_you = introducer_with_two.member('LikedYou', 'Man', 'Woman')
    viewer = introducer_with_two.member('Viewer', 'Man', 'Woman')
    on_map = introducer_with_two.member('Mapped', 'Man', 'Woman')
    with api_tx() as tx:
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)', dict(a=hannah['id'], b=liked['id']))
        tx.execute('INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)', dict(a=liked_you['id'], b=hannah['id']))
        tx.execute('INSERT INTO profile_view (viewer_id, viewed_id) VALUES (%(a)s, %(b)s)',
                   dict(a=viewer['id'], b=hannah['id']))
        tx.execute("""UPDATE person SET show_my_location = TRUE,
                             ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb) || '{"citySet": true}'::jsonb
                       WHERE id = %(i)s""", dict(i=on_map['id']))
    reach = {p['uuid']: p['reach'] for p in _candidates(client, h, miriam).get_json()['people']}
    assert reach[liked['uuid']] == 'liked' and reach[liked_you['uuid']] == 'liked_you'
    assert reach[viewer['uuid']] == 'viewed_you' and reach[on_map['uuid']] == 'map'


def test_a_name_search_narrows_the_list(client, introducer_with_two):
    h, miriam, _daniel, hannah = introducer_with_two()
    for name in ('Josiah', 'Joel', 'Samuel'):
        introducer_with_two.match(hannah, introducer_with_two.member(name, 'Man', 'Woman'))
    names = sorted(p['first_name'] for p in _candidates(client, h, miriam, 'jo').get_json()['people'])
    assert names == ['Joel', 'Josiah']
    assert _candidates(client, h, miriam, '%').get_json()['people'] == []


def test_someone_suggested_before_is_marked(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    ruth = introducer_with_two.member('Ruth', 'Woman', 'Man')
    introducer_with_two.match(hannah, ruth)
    assert _suggest(client, h, miriam, daniel).status_code == 201
    people = {p['uuid']: p for p in _candidates(client, h, ruth).get_json()['people']}
    assert people[daniel['uuid']]['suggested_before'] is True


def test_a_suggestion_tells_both_privately(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    r = _suggest(client, h, miriam, daniel)
    assert r.status_code == 201 and r.get_json() == {'state': 'sent', 'left': 4}
    [intro] = _intros(hannah['id'])
    assert intro['status'] == 'open' and intro['note'] == NOTE
    assert abs(intro['closes_at'] - (datetime.now(timezone.utc) + timedelta(days=14))) < timedelta(minutes=1)
    rows = _intro_rows(miriam['id'], daniel['id'])
    assert sorted(r['campaign_id'] for r in rows) == [f"{intro['id']}:a", f"{intro['id']}:b"]
    by_person = {r['person_id']: r['payload'] for r in rows}
    assert by_person[miriam['id']]['subject'] == 'Hannah thinks you and Daniel might be a good fit'
    assert by_person[daniel['id']]['subject'] == 'Hannah thinks you and Miriam might be a good fit'
    assert all(NOTE not in p['html'] for p in by_person.values())


def test_the_email_follows_the_matches_setting(client, introducer_with_two):
    h, miriam, daniel, _ = introducer_with_two()
    with api_tx() as tx:
        tx.execute('INSERT INTO notification_preference (person_id, email_matches) VALUES (%(p)s, FALSE)',
                   dict(p=daniel['id']))
    _suggest(client, h, miriam, daniel)
    assert [r['person_id'] for r in _intro_rows(miriam['id'], daniel['id'])] == [miriam['id']]


def test_both_are_pushed_after_the_commit(client, introducer_with_two, monkeypatch):
    from service.matchmaker import mail
    sent = []
    monkeypatch.setattr(mail, '_send_push', lambda pid, push, kind: sent.append((pid, push['body'], kind)))
    h, miriam, daniel, _ = introducer_with_two()
    _suggest(client, h, miriam, daniel)
    assert sorted(sent) == sorted([(miriam['id'], 'Hannah thinks you and Daniel might be a good fit', 'match'),
                                   (daniel['id'], 'Hannah thinks you and Miriam might be a good fit', 'match')])


@pytest.mark.parametrize('how', ['blocked', 'unmatched', 'matched', 'prefers_not', 'not_looking'])
def test_a_hidden_refusal_answers_as_a_send(client, introducer_with_two, how):
    h, miriam, daniel, hannah = introducer_with_two()
    other = introducer_with_two.member('Other', 'Woman', 'Man') if how == 'prefers_not' else None
    with api_tx() as tx:
        if how == 'blocked':
            tx.execute('INSERT INTO skipped (subject_person_id, object_person_id, reported) '
                       'VALUES (%(a)s, %(b)s, TRUE)', dict(a=miriam['id'], b=daniel['id']))
        elif how == 'unmatched':
            tx.execute('INSERT INTO unmatched_pair (user_a_id, user_b_id, unmatched_by) '
                       'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int), %(a)s)',
                       dict(a=miriam['id'], b=daniel['id']))
        elif how == 'matched':
            tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                       'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                       dict(a=miriam['id'], b=daniel['id']))
        elif how == 'prefers_not':
            link = tx.execute(
                """INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, relation,
                                            invite_expires_at)
                   VALUES (%(p)s, 'ruth@ahavah-test.invalid', 'ruth@ahavah-test.invalid', 'parent', NOW())
                   RETURNING id""", dict(p=daniel['id'])).fetchone()['id']
            tx.execute("""INSERT INTO shared_conversation (single_person_id, other_person_id, other_person_uuid,
                                                           mentor_link_id)
                          SELECT %(s)s, id, uuid, %(l)s FROM person WHERE id = %(o)s""",
                       dict(s=daniel['id'], o=other['id'], l=link))
            tx.execute('UPDATE person SET no_mentor_shared_matches = TRUE WHERE id = %(i)s', dict(i=miriam['id']))
        elif how == 'not_looking':
            tx.execute("UPDATE search_preference_gender SET gender_id = (SELECT id FROM gender WHERE name = 'Woman') "
                       "WHERE person_id = %(i)s", dict(i=miriam['id']))
    r = _suggest(client, h, miriam, daniel)
    assert r.status_code == 201 and r.get_json() == {'state': 'sent', 'left': 4}
    assert _intro_rows(miriam['id'], daniel['id']) == []
    [row] = _intros(hannah['id'])
    assert row['status'] == 'rejected' and row['flag_reason'] == 'hidden' and row['note'] is None
    # A second try answers as it would after a real send.
    assert _suggest(client, h, miriam, daniel).status_code == 409


def test_each_person_once_per_introducer(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    ruth = introducer_with_two.member('Ruth', 'Woman', 'Man')
    introducer_with_two.match(hannah, ruth)
    assert _suggest(client, h, miriam, daniel).status_code == 201
    r = _suggest(client, h, ruth, daniel)
    assert r.status_code == 409 and r.get_json()['error'] == 'suggested_before'


def _pairs(introducer_with_two, hannah, n):
    out = []
    for i in range(n):
        w = introducer_with_two.member(f'Woman{i}', 'Woman', 'Man')
        m = introducer_with_two.member(f'Man{i}', 'Man', 'Woman')
        introducer_with_two.match(hannah, w)
        introducer_with_two.match(hannah, m)
        out.append((w, m))
    return out


def test_the_sixth_pair_in_a_week_waits_until_monday(client, introducer_with_two):
    h, _miriam, _daniel, hannah = introducer_with_two()
    pairs = _pairs(introducer_with_two, hannah, 6)
    for w, m in pairs[:5]:
        assert _suggest(client, h, w, m).status_code == 201
    r = _suggest(client, h, *pairs[5])
    assert r.status_code == 429 and r.get_json() == {'error': 'limit', 'from': 'Monday'}
    assert client.get('/introductions/allowance', headers=h).get_json() == {'left': 0, 'from': 'Monday'}


def test_a_flagged_note_waits_for_review(client, introducer_with_two):
    h, miriam, daniel, hannah = introducer_with_two()
    r = _suggest(client, h, miriam, daniel, note='Text him on 246 555 0123')
    assert r.status_code == 201 and r.get_json()['state'] == 'held'
    [row] = _intros(hannah['id'])
    assert row['status'] == 'held' and row['flag_reason'] == 'contact'
    assert _intro_rows(miriam['id'], daniel['id']) == []


def test_a_note_is_needed(client, introducer_with_two):
    h, miriam, daniel, _ = introducer_with_two()
    r = _suggest(client, h, miriam, daniel, note='   ')
    assert r.status_code == 400 and r.get_json()['error'] == 'bad_note'


def test_someone_the_introducer_cannot_see_is_not_found(client, introducer_with_two):
    h, miriam, _daniel, _ = introducer_with_two()
    stranger = introducer_with_two.member('Stranger', 'Man', 'Woman')
    r = _suggest(client, h, miriam, stranger)
    unknown = client.post('/introductions', headers=h, json=dict(
        a_uuid=miriam['uuid'], b_uuid='00000000-0000-0000-0000-000000000000', note=NOTE))
    bad = client.post('/introductions', headers=h, json=dict(a_uuid=miriam['uuid'], b_uuid='nope', note=NOTE))
    assert (r.status_code, r.get_json()) == (unknown.status_code, unknown.get_json()) == \
        (bad.status_code, bad.get_json()) == (404, {'error': 'not_found'})
    assert _candidates(client, h, stranger).status_code == 404


def test_two_suggestions_at_once_cannot_pass_the_limit(client, introducer_with_two):
    h, _miriam, _daniel, hannah = introducer_with_two()
    pairs = _pairs(introducer_with_two, hannah, 6)
    for w, m in pairs[:4]:
        _suggest(client, h, w, m)
    def _own_client(a, b):
        from service.api.decorators import app
        with app.test_client() as c:
            return _suggest(c, h, a, b)

    with ThreadPoolExecutor(2) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(_own_client, *pairs[4]),
                                                        ex.submit(_own_client, *pairs[5])])
    assert codes == [201, 429] and len(_intros(hannah['id'])) == 5


def test_closed_until_its_switch(client, introducer_with_two, monkeypatch):
    h, miriam, daniel, _ = introducer_with_two()
    monkeypatch.delenv('AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED')
    assert _suggest(client, h, miriam, daniel).status_code == 404
    assert _candidates(client, h, miriam).status_code == 404
    assert client.get('/introductions/allowance', headers=h).status_code == 404
