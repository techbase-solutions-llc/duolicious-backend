"""The one-off reactivation push (TEC-1607): who is picked, and what it says."""
from database import api_tx
from scripts.push_reactivation import body_for, select_recipients, send_all
from service.unsubscribe import stamp_unsubscribed


def _offline(pid, days=40, email=None):
    """Offline for `days`, and looking for women, because the newcomer count
    only counts people the member would want to see."""
    with api_tx() as tx:
        tx.execute("""UPDATE person SET last_online_time = NOW() - make_interval(days => %(d)s),
                             email = COALESCE(%(e)s, email), normalized_email = COALESCE(%(e)s, normalized_email)
                       WHERE id = %(i)s""", dict(i=pid, d=days, e=email))
        tx.execute("""INSERT INTO search_preference_gender (person_id, gender_id)
                      SELECT %(i)s, id FROM gender WHERE name = 'Woman' ON CONFLICT DO NOTHING""",
                   dict(i=pid))


def _subscribe(pid):
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, 'https://push.test/' || %(i)s::text, 'k', 'a')""", dict(i=pid))


def _ids(days=30):
    with api_tx('read committed') as tx:
        return {r['person_id']: r['total_new'] for r in select_recipients(tx, days)}


def test_an_offline_subscriber_with_a_newcomer_is_picked(make_person):
    gone = make_person(name='Gone', gender='Man')
    _offline(gone['id'])
    _subscribe(gone['id'])
    make_person(name='Newcomer', gender='Woman')  # joined after `gone` was last online
    picked = _ids()
    assert gone['id'] in picked and picked[gone['id']] >= 1


def test_a_recent_member_and_an_unsubscribed_one_are_not(make_person):
    recent = make_person(name='Recent')
    _offline(recent['id'], days=2)
    _subscribe(recent['id'])
    quiet = make_person(name='Unsub')
    _offline(quiet['id'], email=f"unsub-{quiet['id']}@ahavah-test.invalid")
    _subscribe(quiet['id'])
    with api_tx() as tx:
        assert stamp_unsubscribed(tx, 'notifications', f"unsub-{quiet['id']}@ahavah-test.invalid")
    make_person(name='Newcomer2', gender='Woman')
    picked = _ids()
    assert recent['id'] not in picked and quiet['id'] not in picked


def test_an_admin_is_never_pushed(make_person):
    admin = make_person(name='Staff')
    _offline(admin['id'])
    _subscribe(admin['id'])
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::text[] WHERE id = %(i)s", dict(i=admin['id']))
    make_person(name='Newcomer3', gender='Woman')
    assert admin['id'] not in _ids()


def test_nobody_new_in_range_falls_back_to_everyone_who_joined(make_person):
    narrow = make_person(name='NarrowPush')
    _offline(narrow['id'])
    _subscribe(narrow['id'])
    with api_tx() as tx:
        tx.execute("""INSERT INTO search_preference_age (person_id, min_age, max_age)
                      VALUES (%(i)s, 90, 99) ON CONFLICT (person_id) DO UPDATE SET min_age = 90, max_age = 99""",
                   dict(i=narrow['id']))
    make_person(name='Newcomer5', gender='Woman')
    picked = _ids()
    assert narrow['id'] in picked and picked[narrow['id']] >= 1


def test_a_member_without_a_subscription_is_not_picked(make_person):
    p = make_person(name='NoPush')
    _offline(p['id'])
    make_person(name='Newcomer4', gender='Woman')
    assert p['id'] not in _ids()


def test_the_payload_counts_and_names_nobody():
    sent = []
    send_all([dict(person_id=7, total_new=1), dict(person_id=8, total_new=3)],
             lambda pid, payload: sent.append((pid, payload)))
    assert sent[0][1]['body'] == '1 new member since you were last here. Come and see who.'
    assert sent[1][1]['body'] == body_for(3) == '3 new members since you were last here. Come and see who.'
    assert all(p['url'] == '/discover' and '—' not in p['title'] for _, p in sent)
