-- 0095_tester_isolation.sql
-- Tester isolation (TEC-2135, docs/plans/2026-11-06-tester-isolation.md).
-- The owner, 6 Nov 2026, on a tester's account getting likes from real
-- members: test accounts are hidden from the actual app users, and only test
-- accounts interact with each other.
--
-- A tester is a person whose `roles` holds 'tester'. A tester and a member
-- who is not a tester are a split pair: the hard barrier (is_blocked_pair)
-- and the deck barrier (is_deck_suppressed) both hold for them, so every
-- surface that hides a reported or unmatched pair hides them too, in both
-- directions. Nothing is deleted: revoking the role brings it all back.
--
-- Staff (admin or mod) who are not testers are never split from anyone:
-- staff keep seeing everyone. Staff who are testers are testers.
--
-- Additive and idempotent (CREATE OR REPLACE only), as the deploy and the
-- test fixtures both need. Never edit once shipped; a change is the next
-- number. Every later redefinition of is_blocked_pair or is_deck_suppressed
-- must keep is_tester_split_pair (tests/test_tester_isolation.py checks).

-- 1. The split pair.
CREATE OR REPLACE FUNCTION is_tester_split_pair(a INT, b INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM person pa, person pb
        WHERE pa.id = a
          AND pb.id = b
          -- Exactly one of the two is a tester.
          AND ('tester' = ANY(COALESCE(pa.roles, ARRAY[]::text[])))
              <> ('tester' = ANY(COALESCE(pb.roles, ARRAY[]::text[])))
          -- The one who is not a tester is not staff.
          AND NOT (COALESCE(pa.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod']::text[]
                   AND NOT ('tester' = ANY(COALESCE(pa.roles, ARRAY[]::text[]))))
          AND NOT (COALESCE(pb.roles, ARRAY[]::text[]) && ARRAY['admin', 'mod']::text[]
                   AND NOT ('tester' = ANY(COALESCE(pb.roles, ARRAY[]::text[]))))
    );
$$;

-- 2. The hard barrier: the 0070 body, plus a split pair.
CREATE OR REPLACE FUNCTION is_blocked_pair(a INT, b INT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM skipped
        WHERE reported
          AND (
                (subject_person_id = a AND object_person_id = b)
             OR (subject_person_id = b AND object_person_id = a)
          )
    )
    OR is_unmatched_pair(a, b)
    OR is_tester_split_pair(a, b);
$$;

-- 3. Discover: the 0070 body, plus a split pair.
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
    OR is_tester_split_pair(searcher, prospect);
$$;
