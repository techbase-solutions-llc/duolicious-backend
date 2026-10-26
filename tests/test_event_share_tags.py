"""Share tags on a gathering's counts (TEC-1845; ahavah-web
docs/plans/2026-10-22-in-app-entry-and-sign-up.md, section 7, measurement,
and fix 12). A shared link may say which share it came from (host, guest,
app, feed); the page-view count and the RSVP keep it (migration 0081), and
Admin > Events shows views and RSVPs by share and guests per organiser
share. Nothing here says who anyone is."""
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits', 'mail_allowed')

AGENT = {'User-Agent': 'Mozilla/5.0 (iPhone)'}


def _share_views(slug: str) -> dict:
    with api_tx('read committed') as tx:
        return {r['share_tag']: r['views'] for r in tx.execute(
            """SELECT v.share_tag, SUM(v.views)::int AS views FROM event_view_share_day v
                 JOIN event e ON e.id = v.event_id WHERE e.slug = %(s)s GROUP BY v.share_tag""",
            dict(s=slug)).fetchall()}


def _total_views(slug: str) -> int:
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT COALESCE(SUM(v.views), 0)::int AS n FROM event_view_day v
                 JOIN event e ON e.id = v.event_id WHERE e.slug = %(s)s""", dict(s=slug)).fetchone()['n']


def test_a_view_keeps_its_share_tag_and_still_counts_once_in_the_total(client, published):
    slug = published()
    assert client.post(f'/events/{slug}/view', headers=AGENT, json=dict(share='host')).status_code == 204
    assert client.post(f'/events/{slug}/view', headers=AGENT, json=dict(share='guest')).status_code == 204
    assert client.post(f'/events/{slug}/view', headers=AGENT, json=dict(share='host')).status_code == 204
    assert client.post(f'/events/{slug}/view', headers=AGENT).status_code == 204
    assert _total_views(slug) == 4
    assert _share_views(slug) == {'host': 2, 'guest': 1}


@pytest.mark.parametrize('share', ['email', '', 'HOST', 7, None])
def test_an_unknown_share_tag_counts_as_an_untagged_view(client, published, share):
    slug = published()
    assert client.post(f'/events/{slug}/view', headers=AGENT, json=dict(share=share)).status_code == 204
    assert _total_views(slug) == 1 and _share_views(slug) == {}


def _tag_of(slug: str, email: str):
    with api_tx('read committed') as tx:
        return tx.execute(
            """SELECT r.share_tag FROM event_rsvp r JOIN event e ON e.id = r.event_id
                WHERE e.slug = %(s)s AND r.normalized_email = %(ne)s""",
            dict(s=slug, ne=email.lower())).fetchone()['share_tag']


def test_a_visitors_rsvp_keeps_the_first_share_tag(client, published):
    slug = published()
    email = 'guest-share@ahavah-test.invalid'
    body = dict(name='Hannah', email=email, party_size=1)
    assert client.post(f'/events/{slug}/rsvp', json=dict(body, share='guest')).status_code == 201
    assert _tag_of(slug, email) == 'guest'
    # Asking again from another share keeps the first.
    assert client.post(f'/events/{slug}/rsvp', json=dict(body, share='feed')).status_code == 201
    assert _tag_of(slug, email) == 'guest'


def test_a_members_rsvp_keeps_its_share_tag(client, published, make_person, sign_in):
    slug = published()
    p = make_person(name='Ruth', email='ruth-share@ahavah-test.invalid')
    r = client.post(f'/events/{slug}/rsvp', headers=sign_in(p), json=dict(name='Ruth', party_size=1, share='app'))
    assert r.status_code == 201
    assert _tag_of(slug, 'ruth-share@ahavah-test.invalid') == 'app'


def test_an_rsvp_with_no_or_an_unknown_tag_has_none(client, published):
    slug = published()
    client.post(f'/events/{slug}/rsvp', json=dict(name='A', email='a-share@ahavah-test.invalid', party_size=1))
    client.post(f'/events/{slug}/rsvp', json=dict(name='B', email='b-share@ahavah-test.invalid', party_size=1,
                                                   share='email'))
    assert _tag_of(slug, 'a-share@ahavah-test.invalid') is None
    assert _tag_of(slug, 'b-share@ahavah-test.invalid') is None


def test_admin_events_shows_views_rsvps_and_guests_by_share(client, admin_headers, organiser, published):
    o = organiser()
    slug = published(o)
    client.post(f'/events/{slug}/view', headers=AGENT, json=dict(share='host'))
    client.post(f'/events/{slug}/rsvp', json=dict(name='Guest', email='g-share@ahavah-test.invalid',
                                                   party_size=3, share='host'))
    with api_tx() as tx:
        tx.execute("""UPDATE event_rsvp SET confirmed_at = NOW()
                       WHERE normalized_email = 'g-share@ahavah-test.invalid'""")
    body = client.get('/admin/events', headers=admin_headers).get_json()
    row = next(e for e in body['events'] if e['slug'] == slug)
    assert row['shares'] == dict(host=dict(views=1, rsvps=1, confirmed=1),
                                 guest=dict(views=0, rsvps=0, confirmed=0),
                                 app=dict(views=0, rsvps=0, confirmed=0),
                                 feed=dict(views=0, rsvps=0, confirmed=0))
    org = next(x for x in body['organisers'] if x['id'] == o['id'])
    # Guests per organiser share: confirmed people from the host's own links.
    assert org['host_share_guests'] == 3
