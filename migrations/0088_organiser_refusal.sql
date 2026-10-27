-- 0088_organiser_refusal.sql
-- The reason a request to host was refused (TEC-1845; ahavah-web Claude
-- Design "Ahavah In-app Entry Round 2.html", 8.7, and the copy pass of 23
-- Oct 2026, claim 3: the owner chose "Send an email with the reason").
--
--   refusal_reason  what the admin typed when refusing, at most 500
--                   characters, sent to the organiser in one email while
--                   events_host_refusal_email is on. NULL when refused
--                   without one, and for every organiser never refused.
--   refused_at      when Admin > Events refused the request. Refusing
--                   still revokes (revoked_at), as before; this tells a
--                   refusal from a later revoke.
--
-- Both go with the organiser row when it is deleted (with the account, by
-- Your Ahavah or the retention sweep).
--
-- Adding nullable columns rewrites nothing; the statement waits at most 5
-- seconds for its lock on organiser. Additive and idempotent: safe to run
-- again. Never edit this file once it has shipped.
SET lock_timeout = '5s';

ALTER TABLE organiser
  ADD COLUMN IF NOT EXISTS refusal_reason TEXT CHECK (char_length(refusal_reason) <= 500),
  ADD COLUMN IF NOT EXISTS refused_at TIMESTAMPTZ;

RESET lock_timeout;
