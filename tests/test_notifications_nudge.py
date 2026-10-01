"""E6, turn on notifications (TEC-1607)."""
from database import api_tx
from emails.notifications_nudge import notifications_nudge_html, SUBJECT
from emails.send_notifications_nudge import build_for, recipient_count, recipients


def test_the_email_has_one_button_to_the_settings_and_no_em_dash():
    html = notifications_nudge_html('Ehud', 'https://ahavah.app/s/n', 'https://ahavah.app/u/x')
    assert 'Turn on notifications' in html and 'https://ahavah.app/s/n' in html
    assert 'even when the app is closed' in html
    assert 'home screen' in html
    assert '—' not in html and '—' not in SUBJECT


def test_member_supplied_name_is_escaped():
    html = notifications_nudge_html('<b>x</b>', 'https://ahavah.app/s/n', 'https://ahavah.app/u/x')
    assert '<b>x</b>' not in html and '&lt;b&gt;x&lt;/b&gt;' in html


def _set(pid, **cols):
    sets = ', '.join(f"{k} = %({k})s" for k in cols)
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET {sets} WHERE id = %(id)s", dict(id=pid, **cols))


def _mailable(make_person, name):
    p = make_person(name=name)
    _set(p['id'], email=f"{name.lower()}-{p['id']}@ahavah-test.invalid",
         normalized_email=f"{name.lower()}-{p['id']}@ahavah-test.invalid")
    return p


def test_who_is_asked(make_person):
    asked = _mailable(make_person, 'Asked')
    subscribed = _mailable(make_person, 'Subscribed')
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, 'https://push.test/e6-' || %(i)s::text, 'k', 'a')""",
                   dict(i=subscribed['id']))
    staff = _mailable(make_person, 'Staff')
    _set(staff['id'], roles=['admin'])
    gone = _mailable(make_person, 'Gone')
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - interval '31 days' WHERE id = %(i)s",
                   dict(i=gone['id']))
    paused = _mailable(make_person, 'Paused')
    _set(paused['id'], activated=False)

    ids = {r['person_id'] for r in recipients()}
    assert asked['id'] in ids
    for p in (subscribed, staff, gone, paused):
        assert p['id'] not in ids
    assert recipient_count() == len(ids)


def test_build_for_mints_a_tracked_link_to_the_settings(make_person):
    p = _mailable(make_person, 'Linked')
    subject, html = build_for(dict(person_id=p['id'], email='x@ahavah-test.invalid', name='Linked Person'))
    assert subject == SUBJECT and 'Linked,' in html and '/s/' in html
