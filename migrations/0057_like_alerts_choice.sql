-- 0057_like_alerts_choice.sql
-- Like alerts on with push (health review, 13 Oct 2026, findings 32, 58).
--
-- Subscribing a device now turns push_likes on, unless the member has made
-- a choice about likes. A notification_preference row cannot say that on
-- its own: the web saves one switch per PATCH, so a row written for another
-- switch carries push_likes at its DEFAULT FALSE, which reads the same as a
-- deliberate no. This column records the choice: the PATCH route stamps it
-- whenever the request carries push_likes.
--
-- Rows from before this migration: push_likes TRUE can only have come from
-- the member (the default is FALSE and nothing else writes it), so those
-- are stamped as chosen. A FALSE row stays unstamped; it cannot be told
-- apart from the default.
--
-- Idempotent (IF NOT EXISTS, and the stamp only fills NULLs).

ALTER TABLE notification_preference
  ADD COLUMN IF NOT EXISTS push_likes_chosen_at TIMESTAMPTZ;

UPDATE notification_preference
   SET push_likes_chosen_at = updated_at
 WHERE push_likes
   AND push_likes_chosen_at IS NULL;
