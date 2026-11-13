"""The public read (TEC-1845): gatherings by region, one gathering, page
views.

Never in a public response, a share image, schema.org data or a post: the
venue (unless the organiser made it public) and the call link. Only what
card() and event_view() build leaves here.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from service.events import EventError
from service.events import fields as f
from service.testers import guest_on_side_sql, tester_organiser_sql

LIST_MAX = 50
CHANGE_SHOWN = timedelta(days=14)

# going_now counts only places on the gathering's side of the tester line
# (guest_on_side_sql): a tester's place never fills a member's gathering,
# nor a member's place a tester's, places held before the rule included.
_SELECT = f"""
    SELECT e.*, o.name AS organiser_name, o.kind AS organiser_kind,
           COALESCE((SELECT SUM(r.party_size) FROM event_rsvp r
                      WHERE r.event_id = e.id AND r.status = 'going'
                        AND r.confirmed_at IS NOT NULL
                        AND {guest_on_side_sql('r', 'e.organiser_id')}), 0)::int AS going_now
      FROM event e JOIN organiser o ON o.id = e.organiser_id
"""

# What the public may find: published (or cancelled after it was), never
# paused. Drafts and gatherings waiting for approval do not exist to them.
_VISIBLE = "e.published_at IS NOT NULL AND e.status IN ('published', 'cancelled') AND e.paused_at IS NULL"


def visible(row: dict) -> bool:
    """_VISIBLE for a row already read: what the public may find."""
    return (row['published_at'] is not None and row['status'] in ('published', 'cancelled')
            and row['paused_at'] is None)


def shown_sql(viewer_tester: bool, organiser_id: str = 'e.organiser_id') -> str:
    """SQL boolean: the gathering whose organiser id is `organiser_id` is
    one this viewer may find (TEC-2085, decision 3, both ways as decided on
    13 Nov 2026; TEC-2135). A tester's gathering shows only to testers: a
    member, a signed-out visitor, a crawler, a member email and a social
    post never find it, and its page is not found. A member's gathering
    never shows to a tester: not listed, its page not found and no RSVP.
    Staff are no exception here; Admin > Events shows everything."""
    tester_gathering = tester_organiser_sql(organiser_id)
    return tester_gathering if viewer_tester else f'NOT {tester_gathering}'


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.astimezone(timezone.utc).isoformat() if t else None


def card(row: dict) -> dict:
    """One gathering on a list or a page. Never the venue or the call link."""
    from service.events.manage import cover_url
    out = dict(
        slug=row['slug'], title=row['title'], starts_at=_iso(row['starts_at']),
        ends_at=_iso(row['ends_at']), tz=row['tz'], tz_label=row['tz_label'], mode=row['mode'],
        city=row['city'], country=row['country'], region=row['region'],
        organiser=dict(name=row['organiser_name'], kind=row['organiser_kind']),
        tags=list(row['tags']), feast=row['feast'],
        feast_label=f.FEASTS.get(row['feast']) if row['feast'] else None,
        cover_url=cover_url(row['cover_key']), ahavah_attending=bool(row['ahavah_attending']))
    if row['show_going']:
        out['going'] = row['going_now']
    return out


def _public_facts(facts: Optional[dict]) -> Optional[dict]:
    if not facts:
        return None
    return {k: facts.get(k) for k in ('date', 'time', 'place')}


def view_of(row: dict, now: datetime) -> dict:
    """The page's view of a gathering row (with going_now)."""
    out = card(row)
    places_left = None
    if row['capacity'] is not None:
        places_left = max(row['capacity'] - row['going_now'], 0)
    if row['status'] == 'cancelled':
        state = 'cancelled'
    elif row['ends_at'] <= now:
        state = 'ended'
    elif places_left == 0:
        state = 'full'
    else:
        state = 'open'
    out.update(description=row['description'], capacity=row['capacity'],
               places_left=places_left, state=state, cancel_note=row['cancel_note'],
               changed=None)
    if (row['changed_at'] is not None and now - row['changed_at'] <= CHANGE_SHOWN
            and row['starts_at'] > now and row['status'] == 'published'):
        out['changed'] = dict(before=_public_facts(row['change_before']),
                              after=_public_facts(row['change_after']))
    if row['mode'] == 'in_person' and row['venue_visibility'] == 'public' and row['venue']:
        out['venue'] = row['venue']
    return out


def list_events(tx, *, region: Optional[str], limit: int = 20,
                now: Optional[datetime] = None, viewer_tester: bool = False) -> list[dict]:
    """Published, not paused, not ended, by start. A region shows its own
    and every online gathering (decision 6); no region shows them all. A
    tester's gathering only when the viewer is a tester (shown_sql)."""
    now = now or datetime.now(timezone.utc)
    if region is not None and region not in f.REGIONS:
        raise EventError('bad_region', 400)
    limit = max(1, min(int(limit), LIST_MAX))
    where = f"{_VISIBLE} AND {shown_sql(viewer_tester)} AND e.status = 'published' AND e.ends_at > %(now)s"
    if region is not None:
        where += " AND (e.region = %(r)s OR e.region = 'online')"
    rows = tx.execute(f'{_SELECT} WHERE {where} ORDER BY e.starts_at, e.id LIMIT %(n)s',
                      dict(now=now, r=region, n=limit)).fetchall()
    return [card(dict(r)) for r in rows]


def event_row(tx, slug: str) -> Optional[dict]:
    """Any gathering's row with its going count, visible or not."""
    row = tx.execute(f'{_SELECT} WHERE e.slug = %(s)s', dict(s=slug)).fetchone()
    return dict(row) if row else None


def event_view(tx, slug: str, now: Optional[datetime] = None, *, viewer_tester: bool = False) -> dict:
    """The page's view. A tester's gathering is not found unless the viewer
    is a tester (shown_sql)."""
    now = now or datetime.now(timezone.utc)
    row = tx.execute(f'{_SELECT} WHERE e.slug = %(s)s AND {_VISIBLE} AND {shown_sql(viewer_tester)}',
                     dict(s=slug)).fetchone()
    if row is None:
        raise EventError('not_found', 404)
    return view_of(dict(row), now)


# Which share brought a view or an RSVP (migration 0081; in-app entry plan,
# section 7, measurement): the organiser's kit, a guest's "Bring someone
# with you", a member's "Send to a match" and Ahavah's own social posts.
SHARE_TAGS = ('host', 'guest', 'app', 'feed')


def share_tag(value: object) -> Optional[str]:
    """A share tag a link carried, or None for anything else."""
    return value if isinstance(value, str) and value in SHARE_TAGS else None


def count_view(tx, slug: str, day: date, share: Optional[str] = None, *,
               viewer_tester: bool = False) -> None:
    """One page view, on a gathering this viewer may find only. A view from
    a shared link is counted again under its share tag (fix 12); the total
    in event_view_day is every view, as before."""
    shown = f'{_VISIBLE} AND {shown_sql(viewer_tester)}'
    tx.execute(
        f"""INSERT INTO event_view_day (event_id, day, views)
            SELECT e.id, %(d)s, 1 FROM event e WHERE e.slug = %(s)s AND {shown}
            ON CONFLICT (event_id, day) DO UPDATE SET views = event_view_day.views + 1""",
        dict(s=slug, d=day))
    tag = share_tag(share)
    if tag is not None:
        tx.execute(
            f"""INSERT INTO event_view_share_day (event_id, day, share_tag, views)
                SELECT e.id, %(d)s, %(t)s, 1 FROM event e WHERE e.slug = %(s)s AND {shown}
                ON CONFLICT (event_id, day, share_tag)
                DO UPDATE SET views = event_view_share_day.views + 1""",
            dict(s=slug, d=day, t=tag))


# gatherings_for_members' key for the regions with an in-person gathering.
IN_PERSON = 'in_person_regions'


def online_listed(tx, *, now: datetime, viewer_tester: bool = False) -> bool:
    """Whether /events lists an online gathering now, for this reader: one
    they may find (shown_sql: a member never a tester's, a tester only a
    tester's), published and not yet ended. The welcome says "Online
    gatherings are open to you wherever you live." only while this holds
    (copy pass, 23 Oct 2026, claim 9)."""
    row = tx.execute(
        f"""SELECT 1 FROM event e WHERE {_VISIBLE} AND {shown_sql(viewer_tester)} AND e.status = 'published'
                AND e.ends_at > %(now)s AND e.region = 'online' LIMIT 1""",
        dict(now=now)).fetchone()
    return row is not None


def gatherings_for_members(tx, *, now: datetime, limit: int = 3) -> dict[Optional[str], list[dict]]:
    """The gatherings a member email shows (TEC-1845, gatherings in the
    member emails), for every reader at once: for each of the Map's 6
    regions, the first `limit` gatherings in that region or online; for
    None (a member with no country, or one we cannot place), the first
    `limit` online ones. Only what the public may find, published, not yet
    started and not full, by start. One query, grouped here, so a send
    reads it once per run and never once per member.

    Each item is card() with the date block under `date`. A row whose zone
    the server does not know has no `date`; the email drops that card, so
    one bad row never stops the run.

    Under IN_PERSON the set of regions where /events lists an in-person
    gathering (list_events: published, not paused, not ended, full or
    under way included), so for_member never says "Nothing near you yet"
    while See all gatherings shows one (reviews of 23 and 24 Oct 2026).

    Never a tester's gathering: these emails go to members, and testers
    get none of them (service.growth.queries._excluded)."""
    from service.matchmaker.regions import REGIONS
    rows = tx.execute(
        f"""{_SELECT} WHERE {_VISIBLE} AND {shown_sql(False)} AND e.status = 'published' AND e.ends_at > %(now)s
             ORDER BY e.starts_at, e.id""",
        dict(now=now)).fetchall()
    out: dict[Optional[str], list[dict]] = {r: [] for r in REGIONS}
    out[None] = []
    in_person: set[str] = set()
    for row in rows:
        row = dict(row)
        # Every row is one /events lists (list_events); a card needs one
        # not yet started and not full.
        if row['region'] != 'online':
            in_person.add(row['region'])
        if row['starts_at'] <= now or (row['capacity'] is not None and row['going_now'] >= row['capacity']):
            continue
        item = card(row)
        try:
            item['date'] = f.date_block(row['starts_at'], row['tz'])
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            print(f"events: gathering {row['slug']} has no date block ({e!r})")
        keys = list(REGIONS) + [None] if row['region'] == 'online' else [row['region']]
        for k in keys:
            if k in out and len(out[k]) < limit:
                out[k].append(item)
    out[IN_PERSON] = in_person  # type: ignore[index,assignment]
    return out


def for_member(lists: dict, country: Optional[str]) -> tuple[list[dict], bool]:
    """One member's list from gatherings_for_members, by the region of
    their country (service.matchmaker.regions.region_of; none or an unknown
    code gives the online list), and whether every card on it is online
    while the member has a region with no in-person gathering at all: the
    email then says "Nothing near you yet. These are online." """
    from service.matchmaker.regions import region_of
    region = region_of(country)
    cards = list(lists.get(region) or [])
    online_only = (region is not None and bool(cards) and all(c['region'] == 'online' for c in cards)
                   and region not in (lists.get(IN_PERSON) or set()))
    return cards, online_only
