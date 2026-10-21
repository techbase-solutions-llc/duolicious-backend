"""Member of the week refuses a caption over CAPTION_MAX (TEC-1845 admin
audit, Minor 12). create_candidate appends a campaign link of about forty
characters, and CAPTION_MAX (2000) keeps that margin under Instagram's
2200. Brand posts were held to it; member of the week was not, so a long
caption was queued and then failed on Instagram."""
from __future__ import annotations

from database import api_tx
from service.spotlight.queue import CAPTION_MAX
from tests.test_member_of_week_slot import _admin, _eligible


def _queued(person_id: int) -> bool:
    with api_tx() as tx:
        return tx.execute("SELECT 1 FROM publishing_queue WHERE subject_person_id = %(p)s",
                          dict(p=person_id)).fetchone() is not None


def test_a_caption_over_the_limit_is_refused(client, make_person):
    headers = _admin(make_person)
    p = _eligible(make_person)
    r = client.post('/admin/growth/spotlight/member-of-week',
                    json={'person_id': p['id'], 'caption': 'x' * (CAPTION_MAX + 1)},
                    headers=headers)
    assert r.status_code == 400
    assert r.get_json() == {'error': 'bad_caption'}
    assert not _queued(p['id'])


def test_a_caption_that_is_not_text_is_refused(client, make_person):
    headers = _admin(make_person)
    p = _eligible(make_person)
    r = client.post('/admin/growth/spotlight/member-of-week',
                    json={'person_id': p['id'], 'caption': ['not', 'text']}, headers=headers)
    assert r.status_code == 400
    assert r.get_json() == {'error': 'bad_caption'}
