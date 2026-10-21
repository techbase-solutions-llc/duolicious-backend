"""A gathering's cover (TEC-1845): cropped to 1200 by 630, checked and
stored public."""
import base64
import io

import pytest
from PIL import Image

from database import api_tx
from service.photo_moderation import ModerationVerdict

pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')


def Verdict(status):
    return ModerationVerdict(status=status)


def _png_b64(w, h):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (120, 80, 40)).save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def _draft(client, organiser, event_cleanup):
    def _make(published=False):
        return _new(client, organiser, event_cleanup, published)
    return _make


def _new(client, organiser, event_cleanup, published):
    from tests.test_event_manage import draft
    o = organiser()
    slug = client.post('/organiser/events', headers=o['headers'], json=draft()).get_json()['slug']
    event_cleanup(slug)
    if published:
        assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {
            'status': 'published'}
    return o, slug


def _row(slug):
    with api_tx('read committed') as tx:
        return dict(tx.execute('SELECT * FROM event WHERE slug = %(s)s', dict(s=slug)).fetchone())


def _upload(client, o, slug, image=None, content_type='image/png'):
    return client.post(f'/organiser/events/{slug}/cover', headers=o['headers'],
                       json=dict(image=image or _png_b64(3000, 2000), content_type=content_type))


def test_a_cover_is_cropped_to_1200_by_630_and_stored_public(client, _draft, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('approved'))
    o, slug = _draft()
    r = _upload(client, o, slug)
    assert r.status_code == 200
    assert r.get_json()['cover_url'].startswith('https://user-images.ahavah.app/event-covers/')
    key, body, acl = fake_bucket.puts[-1]
    assert acl == 'public-read' and Image.open(io.BytesIO(body)).size == (1200, 630)
    assert Image.open(io.BytesIO(body)).format == 'JPEG' and key.startswith('event-covers/')
    assert _row(slug)['cover_key'] == key


def test_a_file_that_is_not_an_image_is_refused(client, _draft, fake_bucket):
    o, slug = _draft()
    r = _upload(client, o, slug, image=base64.b64encode(b'not an image at all').decode())
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_image'})
    assert fake_bucket.puts == []


def test_a_rejected_cover_is_refused_and_nothing_is_stored(client, _draft, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('rejected'))
    o, slug = _draft()
    r = _upload(client, o, slug)
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_image'})
    assert fake_bucket.puts == [] and _row(slug)['cover_key'] is None


def test_a_borderline_cover_sends_the_gathering_for_approval(client, _draft, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('manual_review'))
    o, slug = _draft(published=True)
    assert _upload(client, o, slug).status_code == 200
    row = _row(slug)
    assert (row['status'], row['flag_reason']) == ('pending', 'cover_review')


def test_a_borderline_cover_on_a_draft_waits_at_publish(client, _draft, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('manual_review'))
    o, slug = _draft()
    _upload(client, o, slug)
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'pending'}
    assert _row(slug)['flag_reason'] == 'cover_review'


def test_replacing_a_cover_deletes_the_old_one(client, _draft, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('approved'))
    o, slug = _draft()
    _upload(client, o, slug)
    first = fake_bucket.puts[-1][0]
    _upload(client, o, slug, image=_png_b64(1600, 1600))
    assert fake_bucket.deletes == [first] and _row(slug)['cover_key'] == fake_bucket.puts[-1][0]
    assert client.delete(f'/organiser/events/{slug}/cover', headers=o['headers']).status_code == 204
    assert _row(slug)['cover_key'] is None and fake_bucket.deletes[-1] == fake_bucket.puts[-1][0]
