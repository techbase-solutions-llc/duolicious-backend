-- 0059_pass_window_30_days.sql
-- A pass hides a member for 30 days (health review, 13 Oct 2026, finding 40).
--
-- 0036 hid a pass for 7 days. On a pool this small that put almost every
-- passed member back in the deck each week: the median woman had 35 of 36
-- men back in hers. The window is now 30 days. Everything else in 0036 is
-- kept: a pass is one-directional, a report hides both ways for good, and
-- re-passing restarts the window (antiabuse Q_INSERT_SKIPPED).
--
-- Supersedes the is_deck_suppressed body in 0036. Idempotent:
-- CREATE OR REPLACE.

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
    );
$$;
