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
