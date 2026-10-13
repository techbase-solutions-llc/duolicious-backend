-- 0058_campaign_unsubscribe.sql
-- Campaigns get their own unsubscribe scope (health review, 13 Oct 2026,
-- finding 62).
--
-- E1, E3, E6, the referral intro, the welcome and the Spotlight emails used
-- the `notifications` scope, which turns off every email_* channel, so
-- leaving a campaign silenced match, message and like emails too. Their
-- footers now carry the `campaigns` scope, stamped here, as E2's
-- `community` scope is stamped on person.community_unsubscribed_at (0040).
--
-- Earlier campaign unsubscribes are not copied into this column: the
-- `campaigns` predicate (service/campaigns/__init__.py) still reads every
-- email channel off as unsubscribed, so they keep their meaning without a
-- backfill, and the notification preferences they wrote are left alone.
--
-- Idempotent.
ALTER TABLE person
  ADD COLUMN IF NOT EXISTS campaigns_unsubscribed_at timestamptz;
