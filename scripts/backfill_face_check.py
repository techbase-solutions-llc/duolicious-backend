"""Record a face count for photos checked before the face check existed.

    PYTHONPATH=/app python3 scripts/backfill_face_check.py [--limit N]

RECORDS ONLY. It writes face_count and face_checked_at and never changes a
photo's moderation status: the photos already on members' profiles were
approved before this rule existed, and whether any of them comes down is
the owner's decision, made by hand on the Photos tab (TEC-946, task 5). It
prints the primary photos in which it saw no face so that decision has a
list to start from.

Resumable: it only picks photos with no face_checked_at, so a second run
continues where the first stopped and never downloads a photo twice.
"""
from __future__ import annotations

import argparse
import asyncio

from antiabuse.facecheck import count_faces
from database.asyncdatabase import api_tx
from service.cron.cronutil import download_450_images

_Q_PICK = """
    SELECT uuid FROM photo
     WHERE face_checked_at IS NULL AND nsfw_score IS NOT NULL AND nsfw_score >= 0
     ORDER BY uuid LIMIT 50
"""

# A photo that will not download, or that the detector cannot read, is
# stamped as looked-at with no count, so the run moves past it instead of
# picking it forever. NULL keeps its meaning: nobody knows.
_Q_SET = """
    UPDATE photo SET face_count = %(n)s, face_checked_at = NOW() WHERE uuid = %(uuid)s
"""

_Q_REPORT = """
    SELECT ph.person_id, p.name, ph.moderation_status::text AS status
      FROM photo ph JOIN person p ON p.id = ph.person_id
     WHERE ph.face_count = 0 AND ph.position = 1
     ORDER BY ph.person_id
"""

_Q_TOTALS = """
    SELECT count(*) FILTER (WHERE face_checked_at IS NOT NULL) AS checked,
           count(*) FILTER (WHERE face_count = 0) AS no_face,
           count(*) FILTER (WHERE face_checked_at IS NOT NULL AND face_count IS NULL) AS unreadable,
           count(*) FILTER (WHERE position = 1 AND face_checked_at IS NOT NULL) AS primaries
      FROM photo
"""


async def main(limit: int) -> None:
    done = 0
    while done < limit:
        async with api_tx() as tx:
            rows = await (await tx.execute(_Q_PICK)).fetchall()
        if not rows:
            break
        uuids = [r['uuid'] for r in rows]
        images = await download_450_images(uuids)
        counts = await asyncio.to_thread(lambda: [count_faces(d) if d else None for d in images])
        async with api_tx() as tx:
            await tx.executemany(
                _Q_SET, [dict(uuid=u, n=n) for u, n in zip(uuids, counts)])
        done += len(uuids)
        print(f'checked {done}', flush=True)

    async with api_tx() as tx:
        totals = await (await tx.execute(_Q_TOTALS)).fetchone()
        flagged = await (await tx.execute(_Q_REPORT)).fetchall()
    print(f'totals: {dict(totals)}')
    print(f'primary photos with no face seen: {len(flagged)}')
    for r in flagged:
        print(f"  person {r['person_id']} {r['name']!r} ({r['status']})")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=100000)
    asyncio.run(main(ap.parse_args().limit))
