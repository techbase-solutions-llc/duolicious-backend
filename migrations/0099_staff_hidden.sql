-- 0099_staff_hidden.sql (TEC-2040)
-- The owner, 11 Nov 2026: staff are hidden from members. An account whose
-- `roles` holds 'admin' or 'mod' never appears to a member anywhere members
-- see people. Staff still see everyone, in the member app as in the admin
-- panel. A staff account that is also a tester stays a tester: the tester
-- line (TEC-2135, migration 0095) decides what it sees and who sees it.
--
-- The rule is one way, so it is its own function, is_staff_hidden(viewer,
-- other), and not part of is_blocked_pair, which is symmetric and which
-- callers pass in either order. is_deck_suppressed is already one way
-- (searcher, prospect), so it carries the rule; every other member-facing
-- surface names is_staff_hidden itself. Nothing is deleted: removing the
-- role brings everything back.
--
-- Additive and idempotent (CREATE OR REPLACE only). Never edit once shipped;
-- a change is the next number. Every later redefinition of
-- is_deck_suppressed must keep is_tester_split_pair and is_staff_hidden
-- (tests/test_tester_isolation.py and tests/test_staff_hidden.py check).

-- 1. The rule: `other` is staff and not a tester, and `viewer` is not
-- staff. A NULL viewer (no session) is not staff, so staff stay hidden
-- from visitors too.
CREATE OR REPLACE FUNCTION is_staff_hidden(viewer INT, other INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM person po
        WHERE po.id = other
          AND COALESCE(po.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod']::text[]
          AND NOT ('tester' = ANY(COALESCE(po.roles, ARRAY[]::text[])))
    )
    AND NOT EXISTS (
        SELECT 1
        FROM person pv
        WHERE pv.id = viewer
          AND COALESCE(pv.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod']::text[]
    );
$$;

-- 2. Discover: the 0095 body, plus staff hidden from the searcher.
CREATE OR REPLACE FUNCTION is_deck_suppressed(searcher INT, prospect INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM skipped
        WHERE (
                -- The searcher's own pass or report.
                subject_person_id = searcher
                AND object_person_id = prospect
                AND (reported OR created_at > NOW() - INTERVAL '30 days')
          )
          OR (
                -- The prospect's action only counts when it is a report.
                subject_person_id = prospect
                AND object_person_id = searcher
                AND reported
          )
    )
    OR is_unmatched_pair(searcher, prospect)
    OR is_tester_split_pair(searcher, prospect)
    OR is_staff_hidden(searcher, prospect);
$$;
