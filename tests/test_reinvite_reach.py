"""E3 asks for notifications too, and a run can be aimed at the long
offline (TEC-1607)."""
from database import api_tx
from emails.reinvite import reinvite_html
from emails.send_reinvite import build_for, recipients


def test_the_email_asks_for_notifications_when_given_the_link():
    html = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x',
                         gender_label='women', notifications_url='https://ahavah.app/s/n')
    assert 'Turn on notifications' in html and 'https://ahavah.app/s/n' in html
    assert 'even when the app is closed' in html
    paused = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x',
                           state='paused', notifications_url='https://ahavah.app/s/n')
    assert 'Turn on notifications' in paused
    assert '—' not in html


def test_without_the_link_nothing_about_notifications_is_said():
    html = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x')
    assert 'notifications' not in html.lower()


def _member(make_person, name, offline_days, sent_days_ago=None):
    p = make_person(name=name, gender='Man')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET email = %(e)s, normalized_email = %(e)s,
                      last_online_time = NOW() - make_interval(days => %(d)s),
                      reinvite_sent_at = CASE WHEN %(s)s::int IS NULL THEN NULL
                                              ELSE NOW() - make_interval(days => %(s)s) END
                WHERE id = %(i)s""",
            dict(i=p['id'], e=f"{name.lower()}-{p['id']}@ahavah-test.invalid",
                 d=offline_days, s=sent_days_ago))
        # The newcomer count only counts people the member is looking for.
        tx.execute("""INSERT INTO search_preference_gender (person_id, gender_id)
                      SELECT %(i)s, id FROM gender WHERE name = 'Woman' ON CONFLICT DO NOTHING""",
                   dict(i=p['id']))
    return p


def test_offline_days_keeps_only_the_long_offline(make_person):
    gone = _member(make_person, 'Gone', 40)
    here = _member(make_person, 'Here', 1)
    make_person(name='Newcomer', gender='Woman')
    everyone = {r['person_id'] for r in recipients()}
    offline = {r['person_id'] for r in recipients(offline_days=30)}
    assert gone['id'] in everyone and gone['id'] in offline
    # `here` is quiet (no like, pass or message) so the default run has them;
    # the offline run must not.
    assert here['id'] in everyone and here['id'] not in offline


def test_ignore_resend_lets_a_recent_recipient_through(make_person):
    p = _member(make_person, 'Resent', 40, sent_days_ago=10)
    make_person(name='Newcomer2', gender='Woman')
    assert p['id'] not in {r['person_id'] for r in recipients()}
    assert p['id'] in {r['person_id'] for r in recipients(ignore_resend=True)}


def test_build_for_puts_both_links_in_the_email(make_person):
    p = _member(make_person, 'Both', 40)
    subject, html = build_for(dict(person_id=p['id'], email='b@ahavah-test.invalid', name='Both',
                                   total_new=2, gender_label='women', state='quiet'))
    assert html.count('/s/') >= 2 and 'Turn on notifications' in html
