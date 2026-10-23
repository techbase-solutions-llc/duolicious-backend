-- 0077_push_tap_matchmaker_sources.sql
-- Push taps for the matchmaker's pushes (TEC-1845; plan 2026-10-22, fix 11).
-- Needs 0067.
--
-- The member-alert, introduction and both-said-yes pushes now carry
-- ?src=mmalert, mmintro and mmtold, and POST /push-taps accepts them, so
-- push_tap.src allows them beside the question pushes' qpush, mpush and
-- lpush. Without this the insert would fail its check.
--
-- One statement drops and re-adds the check, so there is no moment
-- without it. push_tap is small, but the statement waits at most 5
-- seconds for its lock all the same. Existing rows already comply.
-- Idempotent: safe to run again.
SET lock_timeout = '5s';

ALTER TABLE push_tap
  DROP CONSTRAINT IF EXISTS push_tap_src_check,
  ADD CONSTRAINT push_tap_src_check
    CHECK (src IN ('qpush', 'mpush', 'lpush', 'mmalert', 'mmintro', 'mmtold'));

RESET lock_timeout;
