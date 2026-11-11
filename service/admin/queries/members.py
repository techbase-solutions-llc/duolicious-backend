"""Who counts as a member on the admin dashboard.

A member is a `person` whose `roles` does not contain 'admin'. Staff
accounts are people too, with profiles, photos and Premium, so every query
that reads `person` counts them unless it says otherwise.

Until the 13 Oct 2026 health review nothing said otherwise. The three
admin-role accounts (ids 18, 23 and 126) were counted as members on
Overview, System, Economy and Moderation, while Growth left out only the
hardcoded admin address. So Overview read 61 persons, Growth 60, and there
were 58 members.

This is the one definition. A query that counts or lists members splices
it in rather than writing its own, so the tabs cannot drift apart again. It is a SQL fragment, not a bind, so it adds
no parameters and no `%` to any query it joins.

`roles` is NOT NULL with a '{}' default, so the COALESCE is belt and
braces for a row written by hand.
"""


def member_sql(alias: str = 'p') -> str:
    """The member predicate for the `person` row aliased `alias`."""
    return f"'admin' <> ALL(COALESCE({alias}.roles, ARRAY[]::text[]))"


MEMBER_SQL = member_sql('p')


# Roles that make a person not a member for a count of members: staff
# (admin, mod) and test accounts (service/testers.py). Migration 0097 copies
# this list into its backfill.
NON_MEMBER_ROLES = ('admin', 'mod', 'tester')


def non_member_role_sql(alias: str = 'p') -> str:
    """The `person` row aliased `alias` is staff or a tester."""
    roles = ', '.join(f"'{r}'" for r in NON_MEMBER_ROLES)
    return (f"(COALESCE({alias}.roles, ARRAY[]::text[]) "
            f"&& ARRAY[{roles}]::text[])")


def signed_up_member_sql(alias: str = 'p') -> str:
    """Who a SIGN-UP count counts (TEC-2144 ruling, 11 Nov 2026): everyone
    who signed up except staff and testers, whether or not they have since
    deactivated, so a past day's sign-ups never change."""
    return f"(NOT {non_member_role_sql(alias)})"


def current_member_sql(alias: str = 'p') -> str:
    """Who an ACTIVE-USER count or a member total counts (TEC-2144): not
    staff or a tester, activated, and not deactivated by an admin.
    member_sql above left out admins only, so a moderator, a tester or a
    deactivated account counted, while testers.py promised that member
    counts leave testers out. System and Overview splice this and
    signed_up_member_sql in; tests/test_admin_system_people.py holds them
    to it. Overview's person_total keeps member_sql and says so."""
    return (f"({signed_up_member_sql(alias)} AND {alias}.activated "
            f"AND {alias}.admin_deactivated_at IS NULL)")


def counted_member_sql(alias: str = 'p', *, active: bool = True) -> str:
    """A member the Growth tab and Overview's member total count: the rule
    above (current_member_sql when `active`, signed_up_member_sql when not),
    and not one of the staff or test addresses in service/growth/queries.py
    EXCLUDED_EMAILS (bind `%(ex)s` with `_excluded()`). History (the weekly
    funnel) passes active=False: a member who has since deactivated still
    liked who they liked. Until TEC-2144 it left out admins only by role,
    so a moderator counted."""
    rule = current_member_sql(alias) if active else signed_up_member_sql(alias)
    return f"({rule} AND lower({alias}.email) <> ALL(%(ex)s))"
