"""Finishing onboarding needs a photo, on the server (health review, 13 Oct
2026, finding 94).

Only the browser asked for a photo: the onboarding photos screen keeps
Continue disabled until a photo is approved or pending, but
/finish-onboarding checked name, date of birth and gender alone, so a stale
or scripted client could make a member with no photo. The guard now also
needs an uploaded photo that is approved or pending, and names `photo` in
the same 409 it uses for the other fields.

Uploads during onboarding are written to onboardee_photo as 'pending' and
nothing changes that before graduation, so every onboardee who uploaded a
photo passes, as the web's own check already requires.
"""
from __future__ import annotations

import pytest

from database import api_tx


@pytest.mark.parametrize('status', ['pending', 'approved'])
def test_an_uploaded_photo_lets_the_member_finish(finish_onboarding, status):
    r, person_id = finish_onboarding(photo=status)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx() as tx:
        n = tx.execute('SELECT count(*) AS n FROM photo WHERE person_id = %(p)s',
                       dict(p=person_id)).fetchone()['n']
    assert n == 1


def test_no_photo_is_refused_with_a_named_409(finish_onboarding):
    r, person_id = finish_onboarding(photo=None)
    assert r.status_code == 409
    assert r.get_data(as_text=True) == 'Onboarding incomplete: photo'
    assert person_id is None


@pytest.mark.parametrize('status', ['rejected', 'manual_review'])
def test_a_photo_that_is_not_approved_or_pending_is_refused(finish_onboarding, status):
    r, person_id = finish_onboarding(photo=status)
    assert r.status_code == 409
    assert 'photo' in r.get_data(as_text=True)
    assert person_id is None

