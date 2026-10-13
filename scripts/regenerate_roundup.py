"""Rebuild a roundup's count and caption from the week it describes.

    PYTHONPATH=/app python3 scripts/regenerate_roundup.py --week 2026-W41 [--dry-run]

Health review, 13 Oct 2026 (finding 2): the W41 roundup awaiting approval
says "4 joined from 2 countries" because it counted admin account 126, who
signed up that week. The roundup now leaves staff out (service/spotlight/
roundup.py); this rebuilds one made before that.

It goes the way an admin caption edit goes (`edit_caption`): a new revision,
the post's one /s/ link kept with each row's own platform stamp, and every
platform row un-rendered so the next tick draws the card again from the
corrected payload. Status is not touched. A card in review stays in review,
and approving it stays with the owner.

The week is the seven days before the roundup was created, not before
today. It refuses a roundup that is scheduled, publishing, published or
cancelled; one with member tiles (each tiled member consented to the old
revision, and a new one would need their consent again); and one whose
caption was edited by hand, since that edit would be lost (change the
caption in the admin instead).

Idempotent: a roundup whose stored figures are already right is left alone.
"""
from __future__ import annotations

import argparse
import json
import re

from database import api_tx
from service.spotlight.revisions import IN_FLIGHT, TERMINAL, current_revision, edit_caption
from service.spotlight.roundup import roundup_caption, roundup_totals
from service.config import WEB_BASE_URL

_WEEK_RE = re.compile(r'^\d{4}-W\d{2}$')

_FIGURES = ('count', 'countries', 'country_names')


def _expected_caption(tx, request_key: str, count: int, countries: int) -> str:
    """The revision caption the route would have written for these figures:
    the default sentence, then the post's bare /s/ link (the first one
    minted for the request, the same lookup `edit_caption` makes)."""
    sentence = roundup_caption(count, countries)
    link = tx.execute("SELECT key FROM campaign_link WHERE kind = %(k)s ORDER BY created_at ASC LIMIT 1",
                      dict(k=f'post:{request_key}')).fetchone()
    if not link:
        return sentence
    return f"{sentence} {WEB_BASE_URL.rstrip('/')}/s/{link['key']}"


def regenerate_roundup(tx, request_key: str, *, dry_run: bool = False,
                       created_by: str = 'script:regenerate_roundup') -> dict:
    """Raises ValueError naming why a roundup is refused. Runs inside the
    caller's transaction and opens none."""
    rows = tx.execute(
        """SELECT id, kind, status, payload, created_at FROM publishing_queue
            WHERE request_key = %(rk)s ORDER BY id FOR UPDATE""",
        dict(rk=request_key)).fetchall()
    if not rows:
        raise ValueError('not_found')
    if any(r['kind'] != 'roundup' for r in rows):
        raise ValueError('not_a_roundup')
    statuses = {r['status'] for r in rows}
    if statuses & set(IN_FLIGHT):
        raise ValueError('in_flight')
    if statuses & set(TERMINAL):
        raise ValueError('terminal')
    payload = rows[0]['payload'] or {}
    if payload.get('tiles'):
        raise ValueError('has_tiles')

    old = {k: payload.get(k) for k in _FIGURES}
    new = roundup_totals(tx, as_of=min(r['created_at'] for r in rows))
    out = dict(request_key=request_key, old=old, new=new, dry_run=dry_run, revision=None)
    if old == new:
        return dict(out, changed=False)

    rev = current_revision(tx, request_key)
    if rev is None or rev['caption'] != _expected_caption(tx, request_key, old['count'] or 0,
                                                          old['countries'] or 0):
        raise ValueError('caption_edited')
    if dry_run:
        return dict(out, changed=True)

    tx.execute("UPDATE publishing_queue SET payload = %(p)s::jsonb WHERE request_key = %(rk)s",
               dict(p=json.dumps(dict(payload, **new)), rk=request_key))
    edit_caption(tx, request_key, roundup_caption(new['count'], new['countries']), created_by)
    out['revision'] = current_revision(tx, request_key)['revision']
    return dict(out, changed=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--week', required=True, help='the ISO week in the request key, e.g. 2026-W41')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if not _WEEK_RE.match(a.week):
        raise SystemExit('--week looks like 2026-W41')
    rk = f'roundup:{a.week}'
    with api_tx() as tx:
        try:
            out = regenerate_roundup(tx, rk, dry_run=a.dry_run)
        except ValueError as e:
            raise SystemExit(f'{rk}: refused ({e})')
    old, new = out['old'], out['new']
    print(f"{rk}: stored {old['count']} joined from {old['countries']} countries; "
          f"the week had {new['count']} from {new['countries']}")
    if not out['changed']:
        print('already right, nothing changed')
    elif out['dry_run']:
        print('dry run, nothing written')
    else:
        print(f"payload and caption rebuilt as revision {out['revision']}; "
              'the next tick renders the card again, and it stays in review')


if __name__ == '__main__':
    main()
