"""Men are shown women and women are shown men, never otherwise (TEC-1845).

Ahavah is a marriage app for Torah-observant believers. On 26 Oct 2026 the
owner, a man, found men on his map, and found that opening a man's profile
counted as a profile view. Two rules follow, each a SQL fragment so every
surface reads the same text:

- `opposite_gender_sql`: the prospect's gender is the one opposite the
  viewer's own. A viewer who is neither a man nor a woman matches nobody.
- `view_counts_sql`: a profile open counts as a view (a `visited` row, a
  `profile_view` row, the "someone viewed your profile" push) only between
  a man and a woman, and never when the viewer is staff.

Genders are matched by name, as service/matchmaker/notices.py and
service/events/admin.py do: `gender` is a SERIAL lookup seeded by
init-api.sql, and 'Man' and 'Woman' are the names it holds. Staff is a
person whose `roles` holds 'admin' or 'mod' (the owner, 26 Oct 2026:
moderators' views are hidden like admins').

The fragments are text, not binds: each names its viewer and prospect as
SQL expressions the caller passes, and adds no `%` of its own.
"""
from __future__ import annotations



# A viewer whose views never count: an admin or a moderator.
STAFF_ROLES_SQL = "ARRAY['admin', 'mod']::text[]"


def staff_sql(alias: str) -> str:
    return f"(COALESCE({alias}.roles, ARRAY[]::text[]) && {STAFF_ROLES_SQL})"


def _pair(a: str, b: str) -> str:
    return (f"(({a}.name = 'Man' AND {b}.name = 'Woman') "
            f"OR ({a}.name = 'Woman' AND {b}.name = 'Man'))")


def opposite_gender_sql(p: str, viewer: str = '%(searcher_person_id)s') -> str:
    """The person row aliased `p` is the gender opposite the viewer's."""
    return f"""EXISTS (
          SELECT 1
          FROM person mw_v
          JOIN gender mw_vg ON mw_vg.id = mw_v.gender_id
          JOIN gender mw_pg ON mw_pg.id = {p}.gender_id
          WHERE mw_v.id = {viewer}
            AND {_pair('mw_vg', 'mw_pg')}
      )"""


def view_counts_sql(viewer: str, viewed: str) -> str:
    """Opening `viewed`'s profile counts as a view by `viewer`: a man and a
    woman, and the viewer is not staff. Both are person id expressions."""
    return f"""EXISTS (
          SELECT 1
          FROM person mw_a
          JOIN gender mw_ag ON mw_ag.id = mw_a.gender_id
          JOIN person mw_b ON mw_b.id = {viewed}
          JOIN gender mw_bg ON mw_bg.id = mw_b.gender_id
          WHERE mw_a.id = {viewer}
            AND NOT {staff_sql('mw_a')}
            AND {_pair('mw_ag', 'mw_bg')}
      )"""
