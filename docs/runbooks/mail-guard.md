# Mail guard runbook

What to do when Ahavah sends too much email or push, and the rules that keep it from happening
again. Written after the dormancy loop of 2 Nov 2026: a dry run of
`service/cron/autodeactivate2` emailed "Your Ahavah profile is resting" to the same members every
10 minutes for about a month, outside the outbox, the send log and every cap. Plan:
`docs/superpowers/plans/2026-11-02-send-safeguards.md`.

## Rules for whoever pushes

- **Branch `launch-email` must be rebased before it is ever pushed.** It was cut before the fix and
  its `service/cron/autodeactivate2/__init__.py` still emails during a dry run. Run
  `git rebase origin/ahavah/main` first, then confirm that `autodeactivate2_once` returns before
  any send when `DRY_RUN` is on. A force-push of the old branch brings the loop back.
- **A manual rollback runs no tests.** The rollback command in
  `.github/workflows/deploy-ahavah.yml` goes straight to the droplet; the `rules` job never sees
  it. Never roll back to a commit before eb5b1b3. After any rollback, the outside watchdog
  (`techbase-solutions-llc/mail-watchdog`) is the only safeguard until the next real deploy.
- **The live dry-run value.** `.env.production.template` and the compose default both say
  `DUO_CRON_AUTODEACTIVATE2_DRY_RUN=true`, as decided on 1 Oct 2026. The live
  `.env.production` on the droplet was not read when this was written; whoever has droplet
  access should confirm it says `true` or leaves it unset.

## Stop everything now

In order, fastest first. Each step works on its own.

1. Halt every non-essential email and push at the gate (sign-in and change-of-email codes still
   go):
   `docker compose exec cron python scripts/mail_guard_halt.py --all --reason "<why>"`
   or, without a script, in the Redis container: `SET sg:halt:all '{"reason":"manual"}'` and the
   same for `sg:p:halt:all` (push).
2. Stop the cron container, which runs every scheduled sender:
   `docker compose -f docker-compose.yml -f docker-compose.production.yml --env-file .env.production stop cron`.
3. Revoke the Ahavah Resend key in the Resend dashboard. This also stops sign-in codes, so
   members cannot sign in until a new key is set in `.env.production` and the api and cron are
   recreated.

## Clear a halt

A halt never clears itself. Once the cause is fixed:

- `docker compose exec cron python scripts/mail_guard_clear.py --kind <kind> --by <your name>`, or
  `--all` for the global halt. Add `--push` for a push halt.
- Or, signed in as an admin: `POST /admin/system/mail-guard/clear` with
  `{"kind": "<kind>"}` or `{"all": true}`, and `"channel": "push"` for a push halt.

Both clear Redis, stamp `cleared_at` and `cleared_by` in `send_guard_halt`, and write a
`cleared` row to `send_guard_event`. Clearing only Redis by hand does not work: the `sendguard`
cron puts back, within a minute, any halt still open in Postgres.

## Planned large sends

Set `AHAVAH_SEND_GUARD_BULK_UNTIL=<ISO time>` (Barbados or with an offset) in `.env.production`
and recreate the api and cron containers. Until that time the global hourly email ceiling is
2,000 instead of 300. A value more than 24 hours ahead is ignored and alerts. It never lifts a
per-person limit: a bulk kind still reaches each person once in 24 hours.

## The trial week

`AHAVAH_SEND_GUARD_GLOBAL_SHADOW_UNTIL=<YYYY-MM-DD>` (Barbados date) is set at the merge to the
deploy date plus 7 days. Until then the global hourly and daily ceilings alert and stop nothing.
From that date they halt all non-essential mail when crossed. A missing or unreadable value
means enforce. Per-person limits always enforce.

## Limits of the trial-run scan

`tests/test_dry_run_sends_nothing.py` finds trial modes spelt `DRY_RUN`, `DRYRUN`, `SHADOW` or
`--dry-run`. A trial mode spelt some other way (a `?dry=1` query string, say) gets past the scan.
The gate's per-person limits are the backstop there.

## The outside watchdog and healthchecks.io

The watchdog lives in `techbase-solutions-llc/mail-watchdog` and reads the Resend account every
30 minutes, and this API's `GET /internal/send-stats` with the `X-Send-Stats` header. Its setup
steps, including the 2 free healthchecks.io checks (a 30-minute check for the watchdog runs and
a daily check for the summary, each alerting admin@techbaseltd.com from healthchecks.io's own
email), are in that repo's README. Set `AHAVAH_SEND_STATS_SECRET` to the same value in that repo
and in `.env.production`.
