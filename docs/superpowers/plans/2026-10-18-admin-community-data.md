# Admin, acting on the community: the API data the design still needs

Linear: TEC-1897

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the admin every number and list the "acting on the community" design draws but the API does not serve yet (resolving reports, members waiting on a reply, unfinished sign-ups, the weekly funnel, push, verification tiers, email outcomes and run history, profile gaps, approved photos with no face, the photo gate list, an API errors counter, the stale-post alert and the Users additions), then wire the admin screens to them exactly as the Claude Design export draws them.

**Architecture:** One additive migration (0069) adds the five records the database does not keep today: report resolutions, owner alert preferences and their send log, an API error tally, a per-day record of members being online and the upload time of a photo. Read-only admin endpoints count from `liked`, `skipped`, `ahavah_match`, `mam_message` (direction and id only, never content), `onboardee`, `push_subscription`, `photo` and `email_send_log`, with the member rule from `service/admin/queries/members.py` and the staff list from `service/growth/queries.py`. Two owner-only emails (stale posts, a report arriving) run from a new hourly cron job behind their own switches, off by default. The admin gains pure, vm-tested helpers in `src/lib/community.ts` and the components the export draws.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16.2.6, React 19, TanStack Query 5, Tailwind 4, `node --test` with the TypeScript transpile harness (ahavah-admin).

**Spec:** the issue TEC-1897 (the gaps left out by ahavah-admin commit 93d3759, whose message lists them) and the design brief `ahavah-web/docs/design-briefs/2026-10-13-admin-acting-on-the-community.md`. Source of truth for screens and copy: `ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html`, built by `ahavah-web/Claude Design/pages/p04-admin-acting.js`, with every string in `ahavah-web/Claude Design/handoff/copy/04-admin-acting-on-the-community.md`. Frames are named O.x (Overview), G.x (Growth), R.x (Reports), W.x (waiting on a reply and Users), U.x (unfinished sign-ups), E.x (API errors) and P.x (photo gate, profile gaps, approved with no face).

## Before you start

- The highest migration on disk is `migrations/0068_together.sql` (ahavah-api, branch `launch-email`, 18 Oct). This plan adds `0069_admin_community.sql` only. If another branch has taken 0069 by the time you start, take the next free number and change it everywhere this plan names 0069.
- ahavah-api: branch `admin-community-data` from `origin/ahavah/main` (e48e38f on 18 Oct). ahavah-admin: run `git fetch` first, then branch `admin-community-data` from `origin/master` (a13b115 on 18 Oct). Not the local `master`: it is stale at 42a3fea and has no `src/lib/acting.ts`, `src/components/admin/needs-you.tsx` or `tests/acting.test.mjs`, which Tasks 15 to 25 edit. Not 068f6ae either: that is the tip of `together-launch` (the Together launch posts), which is not merged and must not ride along with this work. Use superpowers:using-git-worktrees.
- API tests run one file at a time with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. The tests share the `ahavah-api-postgres-1` database with other sessions: never remove, reset or recreate that container or its volume, and never run the whole suite. In a worktree, change the path in both the `cd` and the `-v` mount. Below, `RUN tests/x.py` means that command with `tests/x.py`.
- Admin tests run with `cd /d/Antigravity/ahavah-admin && node --test tests/<file>.test.mjs`; types with `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit`; the build with `cd /d/Antigravity/ahavah-admin && pnpm build`.
- The shared test database holds other sessions' rows, so every count test reads a figure, makes its own rows, reads again and asserts on the difference, or filters a list to its own people.
- `api_tx` is not re-entrant: never open one inside another (the request deadlocks). Every helper below takes the caller's `tx`.
- Flask's JSON provider writes a raw `datetime` as an RFC 2822 date. Every new endpoint returns ISO 8601 through `service/admin/jsonrow.py` (Task 5), and a naive `TIMESTAMP` column (which holds UTC here: `person.last_online_time`, `skipped.created_at`, `visited.updated_at`) leaves with a `+00:00` offset.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1897`, no attribution trailers. Never push until the deploy task says so, and then only with the owner's go.
- Line numbers are hints measured on 18 Oct. Every edit is anchored on the code it quotes; trust the quote over the number.
- The admin components transcribe the export: run `/sot-sync` on the frames each admin task names once its tests are green. The code below fixes behaviour, data and copy; spacing and kit classes come from the frame.

## Global Constraints

Every task's requirements include these.

- Production reads are counts and aggregates only. Never expose message content: queries may read `mam_message.id`, `direction`, `person_id` and `remote_bare_jid`, never `message`, `search_body`, `translations` or `audio_uuid`. The admin may show that a member is waiting on a reply, never what was said, and never who liked whom (the design's W.1, "Counts per member only, never who liked whom").
- Staff accounts are left out of every member count and list with the member rule (`member_sql`, `service/admin/queries/members.py`) and, where the Growth endpoints already do, the staff and test addresses in `service/growth/queries.py` `EXCLUDED_EMAILS` through `_excluded()`. Figures the design labels as counting staff ("Counting staff accounts", "includes staff accounts", "1 staff account") say so.
- A new email goes to the owner only, behind its own `AHAVAH_*_ENABLED` switch in `service/campaigns/switches.py`, passed through `docker-compose.production.yml` for both the `api` and `cron` services in the form `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}`, off by default. Its proof goes to `harrigan.tennyson@gmail.com` first, straight through the mailer, never the outbox.
- UI follows the returned design exactly: no UI beyond the export. Where the export has no frame or string for something the data needs, the line goes under "Spec conflicts and decisions needing the owner" and through `/copy-pass` (ux-writing) before launch.
- Copy, in UI strings, emails, code comments and commit messages: sentence case, British spelling, no em dashes, digits for numbers, no serial comma, never "dating". Times in Barbados (`America/Barbados`).
- Phones: "Nothing scrolls sideways on a phone"; every table becomes a list of rows at 390; approving, posting, sending, purging, resolving and reminding show on a phone but stay disabled with the design's "Needs a desktop" line.
- Do not invent data. A value the database does not hold reads "Not measured" (the design's own string) or is listed as a conflict.

## Review Focus

The failure modes the spec implies but no ordinary path exercises, most likely to bite the owner first. Each has its test in the task named.

1. A pair reported again after its first report was resolved: the new report must read Unresolved and count on Needs you, not inherit the old outcome. Task 4, `test_a_new_report_on_the_same_pair_is_unresolved_again`.
2. A like that was answered with a pass, a mutual like or a staff account on either end must never put a member on the waiting list. Task 5, `test_a_pass_or_a_like_back_answers_a_like` and `test_staff_never_count_as_waiting`.
3. The error tally failing while it records (the database itself down) must never turn the original 500 into a different error or hang the request. Task 3, `test_a_tally_that_cannot_write_never_raises`.
4. Two cron containers, a restart or two ticks on the same morning must send the stale-post alert once a day at most, and never before 07:00 Barbados. Task 14, `test_the_stale_alert_goes_once_a_day_after_seven`.
5. Presence writes after the migration must keep updating `last_online_time` exactly as before, or autodeactivate2 logs active members out. Task 10, `test_presence_still_moves_last_online`.

## Decisions taken

Defaults so the work can start. The owner may change any of them; each is repeated under "Spec conflicts and decisions needing the owner".

1. Report outcomes are the design's three (Dismissed, Warned, Deactivated). Resolving records the outcome only; "Deactivated" does not deactivate anyone (the drawer's existing Deactivate action does that).
2. Only the admin role may resolve a report. Mods keep reading the list.
3. "Email me when a report arrives" is stored, off by default, and sends only while `AHAVAH_REPORT_ALERT_ENABLED` is also on. The email names nobody and carries no reason.
4. The stale-post alert is the design's G.8: a daily email at or after 07:00 Barbados while a post has been in review for more than 24 hours.
5. Owner alerts go to `harrigan.tennyson@gmail.com`, the address proofs already go to (`scripts/send_proofs.py` `PROOF_TO`).
6. "Came back" defaults to any time since the send (G.1, tagged as the owner's decision). The "Within 7 days" figure is measured from a new per-day presence record that starts on the deploy day; runs before it read "Not measured".
7. Waiting on a reply is the design's W.1: counts only. "Write to them" and "Send the reminder" are drawn disabled, since either would be a new member-facing email outside this issue.
8. Unfinished sign-ups leave out people who came through a couple tool or the checklist and saved no sign-up step. The reminder stays off (U.1).
9. "Email me when a report arrives" is one setting for the whole admin, and the email goes to the owner's address whichever admin turned it on (added by the 18 Oct review; see item 25 below).

## File structure

ahavah-api:

| File | Responsibility |
|---|---|
| `migrations/0069_admin_community.sql` (create) | report resolutions, alert preferences and log, error tally, member online days, `photo.uploaded_at` |
| `tests/conftest.py` (modify) | `admin_community_schema` (session, autouse) and `admin_bearer` fixtures |
| `service/campaigns/switches.py`, `docker-compose.production.yml` (modify) | the 2 alert switches |
| `service/api/error_tally.py` (create), `service/api/__init__.py`, `service/api/decorators.py` (modify) | count unhandled errors per route |
| `service/admin/jsonrow.py` (create) | ISO 8601 for every new endpoint |
| `service/admin/queries/members.py` (modify) | `counted_member_sql`, the member rule plus the staff list |
| `service/admin/queries/community.py` (create) | waiting on a reply and the weekly funnel; never content |
| `service/admin/queries/signups.py` (create) | unfinished sign-ups |
| `service/admin/queries/profiles.py` (create) | verification tiers, profile gaps, the photo gate list, approved with no face |
| `service/admin/queries/push.py` (create) | push subscribers |
| `service/admin/queries/users.py`, `service/api/admin/users_routes.py` (modify) | last online, likes waiting, push in the drawer |
| `service/api/admin/community_routes.py` (create) | `/admin/community/*` |
| `service/moderation/__init__.py`, `service/api/admin/moderation_routes.py`, `service/admin/queries/moderation.py` (modify) | report state and resolve, the alert preference, photo filters and lists |
| `service/growth/email_outcomes.py` (create), `service/api/admin/growth_routes.py` (modify) | came back, push turned on, run history, push and tiers routes |
| `service/api/admin/system_routes.py` (modify) | `/admin/system/errors` |
| `commonsql/__init__.py`, `service/person/__init__.py` (modify) | write the member online day with each presence bump; restart `photo.uploaded_at` when a photo replaces another (Task 1) |
| `emails/admin_alerts.py` (create), `scripts/send_admin_alert_proofs.py` (create) | the 2 owner alerts and their proofs |
| `service/cron/adminalerts/__init__.py` (create), `service/cron/__init__.py` (modify) | the hourly alert and retention job |

ahavah-admin:

| File | Responsibility |
|---|---|
| `src/lib/community.ts` (create), `tests/community.test.mjs` (create) | pure labels and shapes for every new view |
| `src/lib/types.ts`, `src/lib/growth-api.ts`, `src/lib/queries.ts`, `src/lib/growth-queries.ts`, `src/lib/mutations.ts` (modify) | wire types and hooks |
| `src/components/admin/needs-you.tsx` (modify) | 5 tiles (O.1 to O.6) |
| `src/components/admin/tab-moderation.tsx` (modify), `src/components/admin/report-resolve-dialog.tsx` (create) | R.1 to R.5, P.2, P.3 and the gate list P.1 |
| `src/components/admin/community-waiting.tsx`, `src/components/admin/community-unfinished.tsx` (create), `src/components/admin/tab-users.tsx`, `src/components/admin/user-drawer-activity.tsx` (modify) | W.1, W.5, U.1 to U.4 |
| `src/components/admin/weekly-funnel.tsx` (create), `src/components/admin/tab-overview.tsx` (modify) | the funnel in O.1 |
| `src/components/admin/growth-push-tiers.tsx`, `src/components/admin/growth-run-history.tsx` (create), `src/components/admin/growth-emails.tsx`, `src/components/admin/tab-growth.tsx` (modify) | G.1, G.2, G.4 |
| `src/components/admin/tab-system.tsx` (modify) | E.1 to E.3 |
| `tests/_evidence/design-wave-2-shots.mjs` (create) | rendered proof at 390, 768 and 1440, light and dark |

---

## API (ahavah-api)

### Task 1: Migration 0069, the records the design needs and the test fixtures

**Files:**
- Create: `migrations/0069_admin_community.sql`
- Modify: `tests/conftest.py` (append after the `tool_visitor` fixture at the end of the file)
- Modify: `service/person/__init__.py` (`patch_profile_info`, the photo upsert's `ON CONFLICT (person_id, position) DO UPDATE SET` list)
- Test: `tests/test_migration_0069.py` (create)

**Interfaces:**
- Consumes: `person`, `photo`, `skipped`, `email_send_log` (init-api.sql, migration 0039).
- Produces: tables `report_resolution(reporter_id, reported_id, reported_at, outcome, note, resolved_by_uuid, resolved_by_email, resolved_at)`, `admin_alert_pref(alert, enabled, updated_at, updated_by)`, `admin_alert_log(alert, alert_key, sent_at)`, `api_error_tally(route, hour, n, last_at)`, `member_online_day(person_id, day, first_at, last_at)`; column `photo.uploaded_at TIMESTAMPTZ` (NULL for photos stored before the deploy, `NOW()` for new ones and for a photo that replaces another at the same position); indexes `idx__skipped__reported` (partial, reported rows only) and `email_send_log_campaign_idx`. Fixtures `admin_community_schema` (session, autouse) and `admin_bearer` (a signed-in admin's `Authorization` header dict).

The deploy (`scripts/apply-deploy-migrations.sh`, run by `.github/workflows/deploy-ahavah.yml` after the build and before it recreates api, chat and cron) applies each migration file once and records its checksum in `ahavah_schema_migration`; if a file it has already applied changes, the deploy stops. So 0069 must be additive, must never be edited after it ships (a later change is 0070), and must still be idempotent, because the test fixtures below run it at the start of every test session.

Two indexes come with it. The unresolved-report count runs on every Overview load (Needs you) and every hourly cron tick, and reads `skipped` by `reported`; `skipped` holds every pass anyone has made and has no index on `reported`. Run history reads `email_send_log` by `(campaign, campaign_id)` up to 24 times a load, and its only indexes lead with `person_id`. A plain `CREATE INDEX` (not `CONCURRENTLY`, which cannot run inside the test fixture's transaction) on a partial predicate is a sub-second lock at today's size.

A photo uploaded at a position that already holds one is an upsert (`patch_profile_info`, `ON CONFLICT (person_id, position) DO UPDATE`), which would keep the replaced photo's `uploaded_at`, so "Photo waiting" would date the new photo by the old one. The upsert sets `uploaded_at = NOW()`.

`admin_community_schema` is autouse because Task 10 makes every presence bump write `member_online_day`: a test database without the table would quietly stop moving `last_online_time` for every other test file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0069.py`:

```python
"""Migration 0069 (TEC-1897): the records the acting-on-the-community
design needs that the database did not keep. The deploy runs the file on
every deploy, so every test here runs it twice first."""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from database import api_tx

_MIGRATION = Path(__file__).resolve().parent.parent / 'migrations' / '0069_admin_community.sql'


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply()
    _apply()


def _report(make_person):
    a, b = make_person(name='Reporter'), make_person(name='Reported')
    with api_tx() as tx:
        at = tx.execute(
            """INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
               VALUES (%(a)s, %(b)s, TRUE, 'spam') RETURNING created_at""",
            dict(a=a['id'], b=b['id'])).fetchone()['created_at']
    return a, b, at


def test_a_resolution_takes_only_the_three_outcomes(make_person):
    a, b, at = _report(make_person)
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO report_resolution (reporter_id, reported_id, reported_at, outcome,
                                                  resolved_by_uuid, resolved_by_email)
                   VALUES (%(a)s, %(b)s, %(t)s, 'banned', gen_random_uuid(), 'x@example.com')""",
                dict(a=a['id'], b=b['id'], t=at))
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO report_resolution (reporter_id, reported_id, reported_at, outcome,
                                              resolved_by_uuid, resolved_by_email)
               VALUES (%(a)s, %(b)s, %(t)s, 'dismissed', gen_random_uuid(), 'x@example.com')""",
            dict(a=a['id'], b=b['id'], t=at))


def test_one_resolution_per_report(make_person):
    a, b, at = _report(make_person)
    row = dict(a=a['id'], b=b['id'], t=at)
    sql = """INSERT INTO report_resolution (reporter_id, reported_id, reported_at, outcome,
                                            resolved_by_uuid, resolved_by_email)
             VALUES (%(a)s, %(b)s, %(t)s, 'warned', gen_random_uuid(), 'x@example.com')"""
    with api_tx() as tx:
        tx.execute(sql, row)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            tx.execute(sql, row)


def test_the_alert_log_holds_one_row_per_alert_and_key():
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'test' AND alert_key = 'k'")
        first = tx.execute("""INSERT INTO admin_alert_log (alert, alert_key) VALUES ('test', 'k')
                              ON CONFLICT DO NOTHING RETURNING alert""").fetchone()
        second = tx.execute("""INSERT INTO admin_alert_log (alert, alert_key) VALUES ('test', 'k')
                               ON CONFLICT DO NOTHING RETURNING alert""").fetchone()
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'test'")
    assert first is not None and second is None


def test_the_alert_preference_knows_only_the_report_alert():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO admin_alert_pref (alert, enabled) VALUES ('anything', TRUE)")


def test_a_photo_stored_from_now_on_has_an_upload_time(make_person, add_photo):
    p = make_person(name='Uploader')
    uuid = add_photo(p['id'])
    with api_tx('read committed') as tx:
        row = tx.execute("SELECT uploaded_at FROM photo WHERE uuid = %(u)s", dict(u=uuid)).fetchone()
        default = tx.execute(
            """SELECT column_default FROM information_schema.columns
                WHERE table_name = 'photo' AND column_name = 'uploaded_at'""").fetchone()
    assert row['uploaded_at'] is not None
    assert 'now()' in default['column_default']


def test_the_presence_and_error_tables_exist():
    with api_tx('read committed') as tx:
        names = {r['table_name'] for r in tx.execute(
            """SELECT table_name FROM information_schema.tables
                WHERE table_name IN ('member_online_day', 'api_error_tally')""").fetchall()}
    assert names == {'member_online_day', 'api_error_tally'}


def test_the_report_and_send_log_indexes_exist():
    with api_tx('read committed') as tx:
        names = {r['indexname'] for r in tx.execute(
            """SELECT indexname FROM pg_indexes
                WHERE indexname IN ('idx__skipped__reported', 'email_send_log_campaign_idx')""").fetchall()}
    assert names == {'idx__skipped__reported', 'email_send_log_campaign_idx'}


def test_a_replaced_photo_takes_a_new_upload_time(make_person, monkeypatch):
    """An upload at a position that already holds a photo is an upsert. It
    must restart the upload time, or "Photo waiting" dates the new photo by
    the one it replaced. The app's own function, with the object store stubbed
    as tests/test_onboarding_freshness.py does."""
    import base64
    from io import BytesIO
    from types import SimpleNamespace

    from PIL import Image

    import duotypes as t
    import service.person as sp

    monkeypatch.setattr(sp, 'put_image_in_object_store', lambda *a, **k: None)

    def png(colour) -> str:
        buf = BytesIO()
        Image.new('RGB', (64, 64), color=colour).save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    p = make_person(name='Replacer')
    s = SimpleNamespace(person_id=p['id'])
    sp.patch_profile_info(t.PatchProfileInfo(base64_file=dict(
        position=1, base64=png((10, 20, 30)), top=0, left=0)), s)
    with api_tx() as tx:
        tx.execute("UPDATE photo SET uploaded_at = NOW() - INTERVAL '2 days' WHERE person_id = %(p)s",
                   dict(p=p['id']))
    sp.patch_profile_info(t.PatchProfileInfo(base64_file=dict(
        position=1, base64=png((200, 50, 90)), top=0, left=0)), s)
    with api_tx('read committed') as tx:
        row = tx.execute(
            """SELECT uploaded_at > NOW() - INTERVAL '1 minute' AS fresh
                 FROM photo WHERE person_id = %(p)s AND position = 1""", dict(p=p['id'])).fetchone()
    assert row['fresh'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_migration_0069.py`
Expected: errors at setup, `FileNotFoundError: ... 0069_admin_community.sql`.

- [ ] **Step 3: Write the migration**

Create `migrations/0069_admin_community.sql`:

```sql
-- 0069_admin_community.sql
-- Admin, acting on the community (TEC-1897): the records the design needs
-- that the database did not keep.
--
-- Additive. The deploy applies each file once and records its checksum
-- (scripts/apply-deploy-migrations.sh), and stops if an applied file
-- changes: never edit this file once it has shipped; a change is 0070.
-- Idempotent, because the test fixtures apply it at every session start.

-- 1. A report's resolution. A report is a `skipped` row with reported =
-- TRUE, keyed by its pair. The skip upsert (antiabuse/sql Q_INSERT_SKIPPED)
-- moves created_at to NOW() every time the pair is skipped or reported
-- again, so the resolution also carries the report's own time: a fresh
-- report on the same pair is unresolved until someone resolves it.
-- `reported_at` is the naive UTC `skipped.created_at` it resolves.
CREATE TABLE IF NOT EXISTS report_resolution (
  reporter_id       INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  reported_id       INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  reported_at       TIMESTAMP   NOT NULL,
  outcome           TEXT        NOT NULL CHECK (outcome IN ('dismissed', 'warned', 'deactivated')),
  note              TEXT        NOT NULL DEFAULT '' CHECK (char_length(note) <= 1000),
  resolved_by_uuid  UUID        NOT NULL,
  resolved_by_email TEXT        NOT NULL,
  resolved_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (reporter_id, reported_id, reported_at)
);

-- 2. The owner's alerts. The preference is the admin's "Email me when a
-- report arrives" switch; the email also needs AHAVAH_REPORT_ALERT_ENABLED.
-- The log is each alert's once-only key: written in the transaction that
-- decides to send, before the send, so a repeat tick never sends twice.
CREATE TABLE IF NOT EXISTS admin_alert_pref (
  alert      TEXT        PRIMARY KEY CHECK (alert IN ('report')),
  enabled    BOOLEAN     NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by TEXT
);

CREATE TABLE IF NOT EXISTS admin_alert_log (
  alert     TEXT        NOT NULL,
  alert_key TEXT        NOT NULL,
  sent_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (alert, alert_key)
);

-- 3. Unhandled API errors per route and hour (finding 17). `route` is the
-- Flask rule ("/admin/users/<uuid>"), never the path, so no id or address
-- is stored. Rows older than 30 days are deleted by the adminalerts cron.
CREATE TABLE IF NOT EXISTS api_error_tally (
  route   TEXT        NOT NULL,
  hour    TIMESTAMPTZ NOT NULL,
  n       INT         NOT NULL DEFAULT 0,
  last_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (route, hour)
);

-- 4. The Barbados days a person was online, with the first and last time
-- seen that day. person.last_online_time keeps only the latest moment, so
-- "came back within 7 days of an email" could not be answered. Written with
-- each presence bump from the deploy on; nothing before it exists. Rows
-- older than 120 days are deleted by the adminalerts cron.
CREATE TABLE IF NOT EXISTS member_online_day (
  person_id INT         NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  day       DATE        NOT NULL,
  first_at  TIMESTAMPTZ NOT NULL,
  last_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (person_id, day)
);

-- 5. When a photo was stored, so the photo gate list can say how long a
-- photo has waited for a moderator. Added without a default first, so every
-- photo already stored keeps NULL ("not recorded") instead of today's date;
-- the default then applies to new photos only.
ALTER TABLE photo ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ;
ALTER TABLE photo ALTER COLUMN uploaded_at SET DEFAULT NOW();

-- 6. Two reads this work adds on every load. The unresolved-report count
-- (Overview's Needs you, and the adminalerts cron each hour) reads skipped
-- by `reported`; skipped holds every pass and had no index on it. Run
-- history reads email_send_log by campaign and run id; its indexes led
-- with person_id.
CREATE INDEX IF NOT EXISTS idx__skipped__reported
  ON skipped (created_at) WHERE reported;
CREATE INDEX IF NOT EXISTS email_send_log_campaign_idx
  ON email_send_log (campaign, campaign_id);
```

- [ ] **Step 3b: Restart the upload time when a photo replaces another**

In `service/person/__init__.py`, inside `patch_profile_info`'s `base64_file` branch, in the `photo_insertion` CTE, replace:

```python
            ) ON CONFLICT (person_id, position) DO UPDATE SET
                uuid = EXCLUDED.uuid,
                blurhash = EXCLUDED.blurhash,
                extra_exts = EXCLUDED.extra_exts,
                hash = EXCLUDED.hash,
                verified = FALSE
        ), updated_person AS (
```

with:

```python
            ) ON CONFLICT (person_id, position) DO UPDATE SET
                uuid = EXCLUDED.uuid,
                blurhash = EXCLUDED.blurhash,
                extra_exts = EXCLUDED.extra_exts,
                hash = EXCLUDED.hash,
                verified = FALSE,
                -- A new photo at this position (TEC-1897, migration 0069):
                -- its own upload time, not the replaced photo's.
                uploaded_at = NOW()
        ), updated_person AS (
```

The migration runs before the containers are recreated, so the column exists before this code does.

- [ ] **Step 4: Add the fixtures**

Append to `tests/conftest.py`:

```python
# ---------------------------------------------------------------------------
# Admin, acting on the community (TEC-1897)
# ---------------------------------------------------------------------------
# Migration 0069 is idempotent, so applying it here is what the deploy does.
# Autouse: from Task 10 on, every presence bump writes member_online_day,
# and a database without the table would stop moving last_online_time for
# every test file.

@pytest.fixture(scope='session', autouse=True)
def admin_community_schema():
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0069_admin_community.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


@pytest.fixture
def admin_bearer(make_person, sign_in):
    """The Authorization header of a signed-in admin. The account has the
    admin role, so the member rule leaves it out of every count."""
    from database import api_tx

    p = make_person(name='CommunityAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return sign_in(p)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `RUN tests/test_migration_0069.py` then `RUN tests/test_onboarding_freshness.py`
Expected: `8 passed`; the photo upload suite passes as before.

- [ ] **Step 6: Commit**

```bash
git add migrations/0069_admin_community.sql service/person/__init__.py tests/conftest.py tests/test_migration_0069.py
git -c user.email=admin@techbaseltd.com commit -m "feat(db): the records the admin community design needs, migration 0069" -m "Refs: TEC-1897"
```

---

### Task 2: The 2 owner alert switches

**Files:**
- Modify: `service/campaigns/switches.py` (the `SWITCHES` dict, after `'together_summary_email'`)
- Modify: `docker-compose.production.yml` (the `api` block after `AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED` near line 155, and the `cron` block after the same variable near line 338)
- Test: `tests/test_admin_alert_switches.py` (create)

**Interfaces:**
- Produces: `switches.enabled('stale_post_alert')` and `switches.enabled('report_alert')`, read from `AHAVAH_STALE_POST_ALERT_ENABLED` and `AHAVAH_REPORT_ALERT_ENABLED`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_alert_switches.py`:

```python
"""The owner alert switches (TEC-1897). Each alert email is off unless its
variable is on, and each variable is passed through to the api and the
cron containers, defaulting to 0."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES, enabled

NEW = {
    'stale_post_alert': 'AHAVAH_STALE_POST_ALERT_ENABLED',
    'report_alert': 'AHAVAH_REPORT_ALERT_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2


def test_each_is_off_until_its_variable_is_on(monkeypatch):
    for name, env in NEW.items():
        monkeypatch.delenv(env, raising=False)
        assert enabled(name) is False
        monkeypatch.setenv(env, 'on')
        assert enabled(name) is True
        monkeypatch.setenv(env, 'onn')
        assert enabled(name) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_alert_switches.py`
Expected: `test_the_switches_and_their_variables` FAILS (`{'stale_post_alert': None, ...}`), the compose tests fail with count 0 and the last raises `KeyError: 'stale_post_alert'`.

- [ ] **Step 3: Add the switches**

In `service/campaigns/switches.py`, after the line `    'together_summary_email': 'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED',` add:

```python
    # Owner alerts (TEC-1897). Each goes to the owner alone, never to a
    # member: the daily list of posts in review for more than 24 hours, and
    # the note that a report has arrived (which also needs the admin's own
    # "Email me when a report arrives" preference, admin_alert_pref).
    'stale_post_alert': 'AHAVAH_STALE_POST_ALERT_ENABLED',
    'report_alert': 'AHAVAH_REPORT_ALERT_ENABLED',
```

In `docker-compose.production.yml`, in the `api` service, after `      AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED: ${AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED:-0}` (the first occurrence) add:

```yaml
      # Owner alerts (TEC-1897), to the owner only. Off until he has seen
      # each proof (scripts/send_admin_alert_proofs.py).
      AHAVAH_STALE_POST_ALERT_ENABLED: ${AHAVAH_STALE_POST_ALERT_ENABLED:-0}
      AHAVAH_REPORT_ALERT_ENABLED: ${AHAVAH_REPORT_ALERT_ENABLED:-0}
```

In the `cron` service, after the second occurrence of the same Together line, add:

```yaml
      # Owner alerts (TEC-1897): the adminalerts cron sends them. Off until
      # the owner has seen each proof.
      AHAVAH_STALE_POST_ALERT_ENABLED: ${AHAVAH_STALE_POST_ALERT_ENABLED:-0}
      AHAVAH_REPORT_ALERT_ENABLED: ${AHAVAH_REPORT_ALERT_ENABLED:-0}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_alert_switches.py`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/campaigns/switches.py docker-compose.production.yml tests/test_admin_alert_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(alerts): the stale post and report alert switches, off by default" -m "Refs: TEC-1897"
```

---

### Task 3: An API errors counter

**Files:**
- Create: `service/api/error_tally.py`
- Modify: `service/api/__init__.py` (after the last import line, `import service.api.tools_routes  # noqa: E402,F401`)
- Modify: `service/api/decorators.py:251-262` (the `except Exception:` branch of `validate`)
- Modify: `service/api/admin/system_routes.py` (append a route)
- Test: `tests/test_admin_api_errors.py` (create)

**Interfaces:**
- Consumes: `api_error_tally` (Task 1); `admin_bearer` (Task 1).
- Produces: `error_tally.record(route: str) -> None` (never raises), `error_tally.route_of() -> str`, `error_tally.summary(tx) -> {'last_24h': int, 'last_7d': int, 'routes': [{'route': str, 'errors': int, 'last_failed_at': str}]}`; `GET /admin/system/errors` answering `{'available': bool, 'last_24h': int|None, 'last_7d': int|None, 'routes': list}`.

Flask's `handle_exception` sends `got_request_exception` before it decides whether to propagate, so the signal fires in production (a 500) and in the test client (which re-raises). The `validate` decorator catches its own parsing errors and answers 500 without the signal, so it records them itself. HTTP errors such as 404 and 403 are not unhandled and are not counted.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_api_errors.py`:

```python
"""The API errors card (TEC-1897, health review finding 17): unhandled
errors per route, counted by the API's own error path. The route is the
Flask rule, so no id or address is ever stored."""
from __future__ import annotations

import pytest

from database import api_tx
from service.api import error_tally


def _errors(client, headers) -> dict:
    r = client.get('/admin/system/errors', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _route_count(body: dict, route: str) -> int:
    return next((r['errors'] for r in body['routes'] if r['route'] == route), 0)


def test_the_card_is_for_admins_only(client, make_person, sign_in):
    r = client.get('/admin/system/errors', headers=sign_in(make_person(name='ErrMember')))
    assert r.status_code == 403


def test_an_unhandled_error_is_counted_under_its_rule(client, admin_bearer, monkeypatch):
    import service.api.admin.growth_routes as gr

    before = _errors(client, admin_bearer)

    def boom(tx):
        raise RuntimeError('boom')

    monkeypatch.setattr(gr, 'source_rows', boom)
    with pytest.raises(RuntimeError):
        client.get('/admin/growth/sources', headers=admin_bearer)
    after = _errors(client, admin_bearer)
    assert after['available'] is True
    assert after['last_24h'] - before['last_24h'] == 1
    assert after['last_7d'] - before['last_7d'] == 1
    assert (_route_count(after, '/admin/growth/sources')
            - _route_count(before, '/admin/growth/sources')) == 1
    row = next(r for r in after['routes'] if r['route'] == '/admin/growth/sources')
    assert row['last_failed_at'].endswith('+00:00')


def test_a_rule_with_an_id_is_stored_as_the_rule(client, admin_bearer):
    error_tally.record('/admin/users/<uuid>')
    body = _errors(client, admin_bearer)
    assert any(r['route'] == '/admin/users/<uuid>' for r in body['routes'])


def test_a_403_is_not_an_error(client, admin_bearer, make_person, sign_in):
    before = _errors(client, admin_bearer)['last_24h']
    client.get('/admin/growth/sources', headers=sign_in(make_person(name='ErrMember2')))
    assert _errors(client, admin_bearer)['last_24h'] == before


def test_a_tally_that_cannot_write_never_raises(monkeypatch, capsys):
    from contextlib import contextmanager

    @contextmanager
    def broken(*a, **k):
        raise OSError('database down')
        yield

    monkeypatch.setattr(error_tally, 'api_tx', broken)
    error_tally.record('/anything')
    assert 'not recorded' in capsys.readouterr().out


def test_the_card_says_when_the_counter_is_unavailable(client, admin_bearer, monkeypatch):
    import psycopg

    def missing(tx):
        raise psycopg.errors.UndefinedTable('api_error_tally')

    monkeypatch.setattr(error_tally, 'summary', missing)
    assert _errors(client, admin_bearer) == dict(
        available=False, last_24h=None, last_7d=None, routes=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_api_errors.py`
Expected: collection error, `ImportError: cannot import name 'error_tally' from 'service.api'`.

- [ ] **Step 3: Write the tally**

Create `service/api/error_tally.py`:

```python
"""Unhandled API errors, counted per route (TEC-1897, health review finding
17: an admin route failed on every load and nothing showed it).

`connect(app)` subscribes to Flask's got_request_exception, which fires for
every unhandled exception before Flask answers 500. The `validate`
decorator answers its own 500s and calls `record` itself. Each error adds 1
to its route's row for the current hour.

The route is the Flask rule ("/admin/users/<uuid>"), never the path, so no
id or address is stored. Recording must never make an error worse: a
failure here is printed and dropped, and the request goes on to its 500 as
before. It opens its own transaction; the handler's has already ended by
the time the exception reaches Flask, so the non-re-entrant api lock is
free.
"""
from __future__ import annotations

from flask import got_request_exception, request

from database import api_tx

_Q_TALLY = """
    INSERT INTO api_error_tally (route, hour, n, last_at)
    VALUES (%(route)s, date_trunc('hour', NOW()), 1, NOW())
    ON CONFLICT (route, hour) DO UPDATE
       SET n = api_error_tally.n + 1, last_at = EXCLUDED.last_at
"""

_Q_TOTALS = """
    SELECT COALESCE(sum(n) FILTER (
               WHERE hour >= date_trunc('hour', NOW() - INTERVAL '24 hours')), 0)::int AS last_24h,
           COALESCE(sum(n), 0)::int AS last_7d
      FROM api_error_tally
     WHERE hour >= date_trunc('hour', NOW() - INTERVAL '7 days')
"""

_Q_ROUTES = """
    SELECT route, sum(n)::int AS errors, max(last_at) AS last_failed_at
      FROM api_error_tally
     WHERE hour >= date_trunc('hour', NOW() - INTERVAL '7 days')
     GROUP BY route
     ORDER BY errors DESC, route
     LIMIT 10
"""


def route_of() -> str:
    rule = getattr(request, 'url_rule', None)
    return (rule.rule if rule is not None else 'unmatched')[:200]


def record(route: str) -> None:
    try:
        with api_tx() as tx:
            tx.execute(_Q_TALLY, dict(route=route))
    except Exception as e:  # never make the original error worse
        print(f'error_tally: not recorded ({type(e).__name__})')


def _on_exception(sender, exception, **extra) -> None:
    record(route_of())


def connect(app) -> None:
    got_request_exception.connect(_on_exception, app, weak=False)


def summary(tx) -> dict:
    totals = tx.execute(_Q_TOTALS).fetchone()
    routes = [dict(route=r['route'], errors=r['errors'],
                   last_failed_at=r['last_failed_at'].isoformat())
              for r in tx.execute(_Q_ROUTES).fetchall()]
    return dict(last_24h=totals['last_24h'], last_7d=totals['last_7d'], routes=routes)
```

In `service/api/__init__.py`, after `import service.api.tools_routes  # noqa: E402,F401` add:

```python

# Unhandled errors per route, for Admin > System, API errors (TEC-1897).
import service.api.error_tally as _error_tally  # noqa: E402
from service.api.decorators import app as _app  # noqa: E402
_error_tally.connect(_app)
```

In `service/api/decorators.py`, inside `validate`, replace:

```python
            except Exception:
                # Stack trace and exception details go to logs only; the
                # response body is a generic 500 so file paths, library
                # versions, and env config don't leak to the client
                # (audit Auth LOW: validate-500-info-leak).
                print(traceback.format_exc())
                return 'Internal server error', 500
```

with:

```python
            except Exception:
                # Stack trace and exception details go to logs only; the
                # response body is a generic 500 so file paths, library
                # versions, and env config don't leak to the client
                # (audit Auth LOW: validate-500-info-leak).
                print(traceback.format_exc())
                # This 500 never reaches Flask's error path, so it is
                # counted here (TEC-1897).
                from service.api.error_tally import record, route_of
                record(route_of())
                return 'Internal server error', 500
```

Append to `service/api/admin/system_routes.py`:

```python
@aget('/admin/system/errors')
def get_system_errors(s: t.SessionInfo):
    """API errors (TEC-1897; frames E.1 to E.3). `available` is False when
    the tally cannot be read, which the card shows as "Error counter
    unavailable" rather than as no errors."""
    require_admin(s)
    import psycopg
    from service.api import error_tally
    try:
        with api_tx('read committed') as tx:
            return dict(available=True, **error_tally.summary(tx))
    except psycopg.Error:
        return dict(available=False, last_24h=None, last_7d=None, routes=[])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_api_errors.py`
Expected: `6 passed`.

- [ ] **Step 5: Run the neighbouring suites**

Run: `RUN tests/test_admin_system_health.py` then `RUN tests/test_growth_routes.py`
Expected: both pass as before (the signal adds a row only when something raises).

- [ ] **Step 6: Commit**

```bash
git add service/api/error_tally.py service/api/__init__.py service/api/decorators.py service/api/admin/system_routes.py tests/test_admin_api_errors.py
git -c user.email=admin@techbaseltd.com commit -m "feat(system): count unhandled API errors per route for the admin" -m "Refs: TEC-1897"
```

---

### Task 4: Reports with a state, an outcome and the "Email me" preference

**Files:**
- Modify: `service/moderation/__init__.py` (`Q_LIST_REPORTS`, `get_admin_reports`; add the resolve helpers)
- Modify: `service/api/admin/moderation_routes.py` (append 3 routes)
- Test: `tests/test_admin_reports_resolve.py` (create)

**Interfaces:**
- Consumes: `report_resolution`, `admin_alert_pref` (Task 1); `switches.enabled('report_alert')` (Task 2); `record_audit`.
- Produces:
  - `GET /admin/reports` rows gain `report_key: str` (`"<reporter_id>-<reported_id>-<YYYYMMDDHH24MISSUS>"`), `outcome: 'dismissed'|'warned'|'deactivated'|None`, `note: str|None`, `resolved_at: str|None` (ISO), `resolved_by_name: str|None` (first name); the body gains `unresolved: int`.
  - `moderation.parse_report_key(key) -> tuple[int, int, str] | None`; `moderation.resolve_report(tx, key, outcome, note, by_uuid, by_email) -> 'resolved'|'not_found'|'already_resolved'`.
  - `POST /admin/reports/<report_key>/resolve` body `{outcome, note?}` answering `{ok: True}` (200), 400 (bad outcome or note over 1000 characters), 404, 409 `{error: 'already_resolved'}`. Admin role only.
  - `GET /admin/alerts/report` answering `{enabled: bool, switch_on: bool}`; `POST /admin/alerts/report` body `{enabled: bool}` answering the same. Admin role only.
  - `moderation.unresolved_count(tx) -> int`.

The reason a member typed is never copied into the resolution, the audit row or any email.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_reports_resolve.py`:

```python
"""Reports with a resolved state (TEC-1897; frames R.1 to R.5). A report is
a `skipped` row with reported = TRUE. Resolving records an outcome, who and
when; Overview counts unresolved reports only."""
from __future__ import annotations

from antiabuse.sql import Q_INSERT_SKIPPED
from database import api_tx


def _report(a, b, reason='spam') -> None:
    """The app's own report write: the skip upsert POST /skip/by-uuid runs
    (antiabuse/lodgereport skip_by_uuid), without the report email. A
    second report on the same pair updates the row and moves created_at."""
    with api_tx() as tx:
        tx.execute(Q_INSERT_SKIPPED, dict(subject_uuid=a['uuid'], object_uuid=b['uuid'],
                                          reported=True, report_reason=reason,
                                          is_bot_report=False))


def _reports(client, headers) -> dict:
    r = client.get('/admin/reports', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _mine(body, reporter) -> dict:
    return next(r for r in body['reports'] if r['reporter_uuid'] == reporter['uuid'])


def test_a_report_starts_unresolved_and_counts(client, admin_bearer, make_person):
    a, b = make_person(name='RepA'), make_person(name='RepB')
    before = _reports(client, admin_bearer)['unresolved']
    _report(a, b)
    body = _reports(client, admin_bearer)
    row = _mine(body, a)
    assert body['unresolved'] - before == 1
    assert row['outcome'] is None and row['resolved_at'] is None
    assert row['report_key'].startswith(f"{a['id']}-{b['id']}-")


def test_resolving_records_the_outcome_who_and_when(client, admin_bearer, make_person):
    a, b = make_person(name='RepC'), make_person(name='RepD')
    _report(a, b, reason='Rude in chat')
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    before = _reports(client, admin_bearer)['unresolved']
    r = client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                    json=dict(outcome='warned', note='Spoke to them'))
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    body = _reports(client, admin_bearer)
    row = _mine(body, a)
    assert body['unresolved'] == before - 1
    assert row['outcome'] == 'warned' and row['note'] == 'Spoke to them'
    assert row['resolved_by_name'] == 'CommunityAdmin'
    assert row['resolved_at'].endswith('+00:00')
    with api_tx('read committed') as tx:
        audit = tx.execute(
            """SELECT metadata FROM admin_audit_log WHERE action = 'resolve_report'
                ORDER BY created_at DESC LIMIT 1""").fetchone()['metadata']
    assert audit == {'report_key': key, 'outcome': 'warned'}
    assert 'Rude in chat' not in str(audit)


def test_a_report_resolves_once(client, admin_bearer, make_person):
    a, b = make_person(name='RepE'), make_person(name='RepF')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='dismissed')).status_code == 200
    r = client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                    json=dict(outcome='warned'))
    assert r.status_code == 409 and r.get_json() == {'error': 'already_resolved'}


def test_a_new_report_on_the_same_pair_is_unresolved_again(client, admin_bearer, make_person):
    a, b = make_person(name='RepG'), make_person(name='RepH')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer, json=dict(outcome='dismissed'))
    _report(a, b, reason='Again')  # the upsert moves created_at: a new report
    row = _mine(_reports(client, admin_bearer), a)
    assert row['outcome'] is None and row['report_key'] != key


def test_bad_input_is_refused(client, admin_bearer, make_person):
    a, b = make_person(name='RepI'), make_person(name='RepJ')
    _report(a, b)
    key = _mine(_reports(client, admin_bearer), a)['report_key']
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='banned')).status_code == 400
    assert client.post(f'/admin/reports/{key}/resolve', headers=admin_bearer,
                       json=dict(outcome='warned', note='x' * 1001)).status_code == 400
    assert client.post('/admin/reports/1-2-20260101000000000000/resolve', headers=admin_bearer,
                       json=dict(outcome='warned')).status_code == 404
    assert client.post('/admin/reports/nonsense/resolve', headers=admin_bearer,
                       json=dict(outcome='warned')).status_code == 404


def test_only_an_admin_resolves(client, make_person, sign_in):
    mod = make_person(name='RepMod')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['mod']::TEXT[] WHERE id = %(i)s", dict(i=mod['id']))
    headers = sign_in(mod)
    assert client.get('/admin/reports', headers=headers).status_code == 200
    assert client.post('/admin/reports/1-2-20260101000000000000/resolve', headers=headers,
                       json=dict(outcome='warned')).status_code == 403


def test_the_email_me_preference(client, admin_bearer, monkeypatch):
    monkeypatch.delenv('AHAVAH_REPORT_ALERT_ENABLED', raising=False)
    with api_tx() as tx:
        tx.execute("DELETE FROM admin_alert_pref WHERE alert = 'report'")
    assert client.get('/admin/alerts/report', headers=admin_bearer).get_json() == dict(
        enabled=False, switch_on=False)
    r = client.post('/admin/alerts/report', headers=admin_bearer, json=dict(enabled=True))
    assert r.get_json() == dict(enabled=True, switch_on=False)
    monkeypatch.setenv('AHAVAH_REPORT_ALERT_ENABLED', '1')
    assert client.get('/admin/alerts/report', headers=admin_bearer).get_json() == dict(
        enabled=True, switch_on=True)
    assert client.post('/admin/alerts/report', headers=admin_bearer,
                       json=dict(enabled='yes')).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_reports_resolve.py`
Expected: failures with `KeyError: 'unresolved'` and 404s for the new routes.

- [ ] **Step 3: Extend the reports query and add the resolve helpers**

In `service/moderation/__init__.py`, replace the whole `Q_LIST_REPORTS = """ ... """` constant with:

```python
# A report is identified by its pair and its own time (TEC-1897): the skip
# upsert (antiabuse/sql Q_INSERT_SKIPPED) moves created_at whenever the pair
# is reported or skipped again, and a new report must read Unresolved. The
# key is the reporter's id, the reported member's id and the report's time
# to the microsecond.
_REPORT_KEY = ("s.subject_person_id || '-' || s.object_person_id || '-' || "
               "to_char(s.created_at, 'YYYYMMDDHH24MISSUS')")

Q_LIST_REPORTS = f"""
SELECT
    s.created_at::text                          AS created_at,
    {_REPORT_KEY}                               AS report_key,
    s.subject_person_id                          AS reporter_id,
    reporter.uuid::text                          AS reporter_uuid,
    reporter.name                                AS reporter_name,
    reporter.email                               AS reporter_email,
    s.object_person_id                           AS reported_id,
    reported.uuid::text                          AS reported_uuid,
    reported.name                                AS reported_name,
    reported.email                               AS reported_email,
    reported.activated                           AS reported_active,
    reported.verification_required               AS reported_verification_required,
    s.report_reason                              AS reason,
    rr.outcome                                   AS outcome,
    rr.note                                      AS note,
    rr.resolved_at                               AS resolved_at,
    split_part(resolver.name, ' ', 1)            AS resolved_by_name
FROM   skipped s
JOIN   person reporter ON reporter.id = s.subject_person_id
JOIN   person reported ON reported.id = s.object_person_id
LEFT JOIN report_resolution rr
       ON rr.reporter_id = s.subject_person_id
      AND rr.reported_id = s.object_person_id
      AND rr.reported_at = s.created_at
LEFT JOIN person resolver ON resolver.uuid = rr.resolved_by_uuid
WHERE  s.reported = TRUE
ORDER BY s.created_at DESC
LIMIT 200
"""

Q_COUNT_UNRESOLVED = """
SELECT count(*)::int AS n
  FROM skipped s
 WHERE s.reported = TRUE
   AND NOT EXISTS (SELECT 1 FROM report_resolution rr
                    WHERE rr.reporter_id = s.subject_person_id
                      AND rr.reported_id = s.object_person_id
                      AND rr.reported_at = s.created_at)
"""

OUTCOMES = ('dismissed', 'warned', 'deactivated')
NOTE_MAX = 1000

_KEY_RE = re.compile(r'^(\d{1,10})-(\d{1,10})-(\d{20})$')

_Q_RESOLVE = """
INSERT INTO report_resolution (reporter_id, reported_id, reported_at, outcome, note,
                               resolved_by_uuid, resolved_by_email)
SELECT s.subject_person_id, s.object_person_id, s.created_at, %(outcome)s, %(note)s,
       %(by_uuid)s, %(by_email)s
  FROM skipped s
 WHERE s.subject_person_id = %(a)s AND s.object_person_id = %(b)s AND s.reported
   AND to_char(s.created_at, 'YYYYMMDDHH24MISSUS') = %(ts)s
ON CONFLICT DO NOTHING
RETURNING reporter_id
"""

_Q_REPORT_EXISTS = """
SELECT 1 FROM skipped s
 WHERE s.subject_person_id = %(a)s AND s.object_person_id = %(b)s AND s.reported
   AND to_char(s.created_at, 'YYYYMMDDHH24MISSUS') = %(ts)s
"""


def parse_report_key(key: str):
    m = _KEY_RE.match(key or '')
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def unresolved_count(tx) -> int:
    return tx.execute(Q_COUNT_UNRESOLVED).fetchone()['n']


def resolve_report(tx, key: str, outcome: str, note: str, by_uuid: str, by_email: str) -> str:
    """'resolved', 'not_found' or 'already_resolved'. The caller has checked
    the outcome and the note's length and holds the transaction."""
    parsed = parse_report_key(key)
    if parsed is None:
        return 'not_found'
    a, b, ts = parsed
    params = dict(a=a, b=b, ts=ts, outcome=outcome, note=note, by_uuid=by_uuid, by_email=by_email)
    if tx.execute(_Q_RESOLVE, params).fetchone():
        return 'resolved'
    return 'already_resolved' if tx.execute(_Q_REPORT_EXISTS, params).fetchone() else 'not_found'
```

Add `import re` to the module's imports (after `from database import api_tx`).

In `get_admin_reports`, replace:

```python
        rows = tx.execute(Q_LIST_REPORTS).fetchall()
```

with:

```python
        rows = tx.execute(Q_LIST_REPORTS).fetchall()
        unresolved = unresolved_count(tx)
```

and replace its return block with:

```python
    # `count` is every report listed; `unresolved` is what Overview's Needs
    # you band counts (TEC-1897). resolved_at leaves as ISO 8601, never
    # Flask's RFC 2822 default.
    return {
        'reports': [dict(r, resolved_at=r['resolved_at'].isoformat() if r['resolved_at'] else None)
                    for r in rows],
        'count': len(rows),
        'unresolved': unresolved,
    }
```

Update the module docstring's last paragraph ("Read-only for now. Future enhancement: ...") to:

```python
Resolving (TEC-1897): POST /admin/reports/<report_key>/resolve records an
outcome in `report_resolution`, keyed by the pair and the report's own
time. The skip upsert moves that time when the pair is reported again, so
a repeat report is a new, unresolved one.
```

- [ ] **Step 4: Add the routes**

Append to `service/api/admin/moderation_routes.py`:

```python
@apost('/admin/reports/<report_key>/resolve')
def post_resolve_report(s: t.SessionInfo, report_key: str):
    """Records an outcome, who resolved it and when (TEC-1897; frame R.3).
    Recording "deactivated" does not deactivate anyone: the drawer's own
    Deactivate action does that. The member's reason is never copied."""
    require_admin(s)
    from service import moderation
    body = request.get_json(silent=True) or {}
    outcome = body.get('outcome')
    note = body.get('note') or ''
    if outcome not in moderation.OUTCOMES or not isinstance(note, str) or len(note) > moderation.NOTE_MAX:
        abort(400)
    with api_tx() as tx:
        result = moderation.resolve_report(tx, report_key, outcome, note.strip(),
                                           s.person_uuid, s.email)
        if result == 'resolved':
            record_audit(tx, s, 'resolve_report',
                         metadata={'report_key': report_key, 'outcome': outcome})
    if result == 'not_found':
        abort(404)
    if result == 'already_resolved':
        return {'error': 'already_resolved'}, 409
    return {'ok': True}


def _report_alert(tx) -> dict:
    from service.campaigns.switches import enabled
    row = tx.execute("SELECT enabled FROM admin_alert_pref WHERE alert = 'report'").fetchone()
    return dict(enabled=bool(row and row['enabled']), switch_on=enabled('report_alert'))


@aget('/admin/alerts/report')
def get_report_alert(s: t.SessionInfo):
    """The "Email me when a report arrives" preference (frame R.2).
    `switch_on` says whether AHAVAH_REPORT_ALERT_ENABLED lets it send."""
    require_admin(s)
    with api_tx('read committed') as tx:
        return _report_alert(tx)


@apost('/admin/alerts/report')
def post_report_alert(s: t.SessionInfo):
    require_admin(s)
    value = (request.get_json(silent=True) or {}).get('enabled')
    if not isinstance(value, bool):
        abort(400)
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO admin_alert_pref (alert, enabled, updated_at, updated_by)
               VALUES ('report', %(v)s, NOW(), %(by)s)
               ON CONFLICT (alert) DO UPDATE
                  SET enabled = EXCLUDED.enabled, updated_at = NOW(), updated_by = EXCLUDED.updated_by""",
            dict(v=value, by=s.email))
        record_audit(tx, s, 'set_report_alert', metadata={'enabled': value})
        return _report_alert(tx)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `RUN tests/test_admin_reports_resolve.py`
Expected: `7 passed`.

- [ ] **Step 6: Run the neighbouring suite**

Run: `RUN tests/test_moderation_flagged_words.py`
Expected: passes as before.

- [ ] **Step 7: Commit**

```bash
git add service/moderation/__init__.py service/api/admin/moderation_routes.py tests/test_admin_reports_resolve.py
git -c user.email=admin@techbaseltd.com commit -m "feat(moderation): resolve a report with an outcome, count unresolved reports and store the report alert preference" -m "Refs: TEC-1897"
```

---

### Task 5: Members someone is waiting on

**Files:**
- Create: `service/admin/jsonrow.py`
- Modify: `service/admin/queries/members.py` (append `counted_member_sql`)
- Create: `service/admin/queries/community.py`
- Create: `service/api/admin/community_routes.py`
- Modify: `service/api/__init__.py` (after `import service.api.admin.growth_routes  # noqa: E402,F401`)
- Test: `tests/test_admin_community_waiting.py` (create)

**Interfaces:**
- Consumes: `member_sql`; `_SENT_MESSAGES` from `service/admin/queries/engagement.py`; `_excluded()` from `service/growth/queries.py`; `admin_bearer` (Task 1).
- Produces:
  - `jsonrow.iso(value)` and `jsonrow.iso_row(row) -> dict`: datetimes as ISO 8601, a naive one read as UTC (`+00:00`), dates as `YYYY-MM-DD`.
  - `members.counted_member_sql(alias: str, *, active: bool = True) -> str`: the member rule, not a staff or test address (binds `%(ex)s`), and, when `active`, activated.
  - `community.waiting_likes_sql() -> str`: a SELECT of `person_id` (who is waiting to answer), `liker_id`, `created_at`, binding `%(ex)s`.
  - `community.member_sent_sql(active: bool) -> str`: `_SENT_MESSAGES` limited to counted members.
  - `community.Q_WAITING_SUMMARY`, `community.Q_WAITING_MEMBERS` (both bind `%(ex)s`).
  - `GET /admin/community/waiting` answering `{'summary': {likes_waiting, members_with_likes, oldest_like_at, offline_7d, push_on, with_5_or_more, with_2_to_4, with_1, conversations, one_sided, oldest_unanswered_at, matches, silent_matches_7d}, 'members': [{uuid, name, likes_waiting, unanswered_openers, silent_matches, oldest_wait_at, last_online_at, push_on}]}`, members sorted by oldest wait, at most 200.

Definitions, each from the design's W.1:
- A like is waiting when both people are counted, active members, the liked member has neither liked back nor passed and the liker has not passed since.
- A conversation is one-sided when only one person has written; the other is waiting to reply. Its date is the opener's.
- A match is silent when it is over 7 days old and nobody has written. Both people in it are waited on.
- `offline_7d` and `push_on` are out of the members with a like waiting, the design's "14 of 20" and "4 of 20".
- A pair where either person has blocked the other is never waiting and is left out of every W.1 figure. A block is a report (`is_blocked_pair`, migration 0035): it hides the match and the conversation from both people, so neither can reply. Likes already leave out any pair with a `skipped` row.

CONTENT IS NEVER READ: `community.py` builds on `_SENT_MESSAGES` (id, direction, person and the other party only). The test reads the module's SQL and fails if `m.message`, `search_body`, `translations` or `audio_uuid` appear, and checks no message text reaches the response.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_community_waiting.py`:

```python
"""Members someone is waiting on (TEC-1897; frame W.1). Counts per member,
never who liked whom, never what was said."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx
from service.admin.queries import community

_MAM_SEQ = [0]


def _like(a, b, days_ago: int = 0) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO liked (liker_id, liked_id, created_at)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))
                      ON CONFLICT DO NOTHING""", dict(a=a['id'], b=b['id'], d=days_ago))


def _pass(a, b) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id)
                      VALUES (%(a)s, %(b)s) ON CONFLICT DO NOTHING""", dict(a=a['id'], b=b['id']))


def _message(sender, recipient, text: str = 'hello there') -> None:
    """Both archive copies, as the chat service writes them, with real text
    in `message` so the test can prove it never leaves the server."""
    _MAM_SEQ[0] += 1
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(s)s AS id",
            dict(s=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'O', convert_to(%(t)s, 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id, t=text, p=sender['id'], j=recipient['uuid']))
        tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                      VALUES (%(id)s, 'I', convert_to(%(t)s, 'UTF8'), %(p)s, '', %(j)s)""",
                   dict(id=mam_id + 1, t=text, p=recipient['id'], j=sender['uuid']))


def _match(a, b, days_ago: int) -> None:
    lo, hi = sorted([a['id'], b['id']])
    with api_tx() as tx:
        tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
                      VALUES (%(a)s, %(b)s, NOW() - make_interval(days => %(d)s))""",
                   dict(a=lo, b=hi, d=days_ago))


def _waiting(client, headers) -> dict:
    r = client.get('/admin/community/waiting', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _row(body, person):
    return next((m for m in body['members'] if m['uuid'] == person['uuid']), None)


def test_waiting_is_for_admins_only(client, make_person, sign_in):
    r = client.get('/admin/community/waiting', headers=sign_in(make_person(name='WMember')))
    assert r.status_code == 403


def test_an_unanswered_like_puts_the_liked_member_on_the_list(client, admin_bearer, make_person):
    a, b = make_person(name='WA'), make_person(name='WB')
    before = _waiting(client, admin_bearer)['summary']
    _like(a, b, days_ago=3)
    body = _waiting(client, admin_bearer)
    row = _row(body, b)
    assert row['likes_waiting'] == 1 and row['unanswered_openers'] == 0
    assert row['oldest_wait_at'].endswith('+00:00') and row['last_online_at'].endswith('+00:00')
    assert row['push_on'] is False
    assert _row(body, a) is None
    after = body['summary']
    assert after['likes_waiting'] - before['likes_waiting'] == 1
    assert after['members_with_likes'] - before['members_with_likes'] == 1
    assert after['with_1'] - before['with_1'] == 1


def test_a_pass_or_a_like_back_answers_a_like(client, admin_bearer, make_person):
    a, b, c, d = (make_person(name=n) for n in ('WC', 'WD', 'WE', 'WF'))
    _like(a, b)
    _like(b, a)  # a like back is a match, not a wait
    _like(c, d)
    _pass(d, c)  # a pass is an answer
    body = _waiting(client, admin_bearer)
    assert all(_row(body, p) is None for p in (a, b, c, d))


def test_staff_never_count_as_waiting(client, admin_bearer, make_person):
    staff, member = make_person(name='WStaff'), make_person(name='WMem')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=staff['id']))
    _like(staff, member)
    _like(member, staff)
    _message(staff, member)
    body = _waiting(client, admin_bearer)
    assert _row(body, member) is None and _row(body, staff) is None


def test_a_one_sided_conversation_waits_on_the_recipient(client, admin_bearer, make_person):
    a, b = make_person(name='WG'), make_person(name='WH')
    before = _waiting(client, admin_bearer)['summary']
    _message(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, b)['unanswered_openers'] == 1 and _row(body, a) is None
    assert body['summary']['one_sided'] - before['one_sided'] == 1
    _message(b, a, 'a reply')
    assert _row(_waiting(client, admin_bearer), b) is None


def test_a_silent_match_over_7_days_waits_on_both(client, admin_bearer, make_person):
    a, b = make_person(name='WI'), make_person(name='WJ')
    _match(a, b, days_ago=8)
    body = _waiting(client, admin_bearer)
    assert _row(body, a)['silent_matches'] == 1 and _row(body, b)['silent_matches'] == 1
    _message(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, a) is None and _row(body, b)['unanswered_openers'] == 1


def test_push_and_last_online_are_reported(client, admin_bearer, make_person):
    a, b = make_person(name='WK'), make_person(name='WL')
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - INTERVAL '10 days' WHERE id = %(i)s",
                   dict(i=b['id']))
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, %(e)s, 'k', 'a')""", dict(i=b['id'], e=f'https://push.test/{uuid4()}'))
    before = _waiting(client, admin_bearer)['summary']
    _like(a, b)
    body = _waiting(client, admin_bearer)
    assert _row(body, b)['push_on'] is True
    assert body['summary']['offline_7d'] - before['offline_7d'] == 1
    assert body['summary']['push_on'] - before['push_on'] == 1


def test_a_blocked_pair_is_never_waiting(client, admin_bearer, make_person):
    a, b, c, d = (make_person(name=n) for n in ('WO', 'WP', 'WQ', 'WR'))
    _message(a, b)
    _match(c, d, days_ago=8)
    before = _waiting(client, admin_bearer)['summary']
    with api_tx() as tx:  # b blocks a, d blocks c: a block is a report
        for s, o in ((b, a), (d, c)):
            tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason)
                          VALUES (%(s)s, %(o)s, TRUE, 'blocked')""", dict(s=s['id'], o=o['id']))
    body = _waiting(client, admin_bearer)
    assert all(_row(body, p) is None for p in (a, b, c, d))
    assert before['one_sided'] - body['summary']['one_sided'] == 1
    assert before['silent_matches_7d'] - body['summary']['silent_matches_7d'] == 1


def test_no_message_content_is_read_or_returned(client, admin_bearer, make_person):
    for sql in (community.Q_WAITING_SUMMARY, community.Q_WAITING_MEMBERS):
        low = sql.lower()
        for forbidden in ('m.message', 'search_body', 'translations', 'audio_uuid'):
            assert forbidden not in low
    a, b = make_person(name='WM'), make_person(name='WN')
    _message(a, b, 'a very private sentence')
    assert 'private sentence' not in str(_waiting(client, admin_bearer))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_community_waiting.py`
Expected: collection error, `ImportError: cannot import name 'community' from 'service.admin.queries'`.

- [ ] **Step 3: Write the helpers and the queries**

Create `service/admin/jsonrow.py`:

```python
"""ISO 8601 for every admin endpoint added in TEC-1897.

Flask writes a raw datetime as an RFC 2822 date, and a naive TIMESTAMP
column here holds UTC (person.last_online_time, skipped.created_at,
visited.updated_at), which the admin would read as local time. So a naive
datetime leaves marked as UTC, an aware one as it is, and a date as
YYYY-MM-DD.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping


def iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def iso_row(row: Mapping) -> dict:
    return {k: iso(v) for k, v in dict(row).items()}
```

Append to `service/admin/queries/members.py`:

```python
def counted_member_sql(alias: str = 'p', *, active: bool = True) -> str:
    """A member the Growth tab counts: the member rule above, not one of the
    staff or test addresses in service/growth/queries.py EXCLUDED_EMAILS
    (bind `%(ex)s` with `_excluded()`), and, when `active`, activated.
    History (the weekly funnel) passes active=False: a member who has since
    deactivated still liked who they liked."""
    rule = f"({member_sql(alias)} AND lower({alias}.email) <> ALL(%(ex)s))"
    return f"({rule} AND {alias}.activated)" if active else rule
```

Create `service/admin/queries/community.py`:

```python
"""Members someone is waiting on, and the weekly funnel (TEC-1897).

CONTENT IS NEVER READ. Messages come from engagement._SENT_MESSAGES, which
reads mam_message's id, direction, person and other party only. No query
here may name `message`, `search_body`, `translations` or `audio_uuid`;
tests/test_admin_community_waiting.py and tests/test_admin_funnel.py read
the SQL and fail if one appears.

Never who liked whom: the lists here are per member counts. A row names
the member who is waiting to answer, never the people waiting on them.

Every figure is between counted members (members.counted_member_sql):
active ones for the lists of who is waiting now, any member for history.
Every query binds %(ex)s with service.growth.queries._excluded().
"""
from __future__ import annotations

from service.admin.queries.engagement import _SENT_MESSAGES
from service.admin.queries.members import counted_member_sql


def waiting_likes_sql() -> str:
    """Likes nobody has answered: `person_id` is the member who was liked
    and has neither liked back nor passed. A pass by the liker since then
    withdraws the like."""
    return f"""
        SELECT l.liked_id AS person_id, l.liker_id, l.created_at
          FROM liked l
          JOIN person a ON a.id = l.liker_id
          JOIN person b ON b.id = l.liked_id
         WHERE {counted_member_sql('a')} AND {counted_member_sql('b')}
           AND NOT EXISTS (SELECT 1 FROM liked r
                            WHERE r.liker_id = l.liked_id AND r.liked_id = l.liker_id)
           AND NOT EXISTS (SELECT 1 FROM skipped s
                            WHERE (s.subject_person_id = l.liked_id AND s.object_person_id = l.liker_id)
                               OR (s.subject_person_id = l.liker_id AND s.object_person_id = l.liked_id))
    """


def member_sent_sql(active: bool) -> str:
    """One row per message sent between counted members (sender_id,
    recipient_id, lo, hi, sent_at)."""
    return f"""
        SELECT x.sender_id, x.recipient_id, x.lo, x.hi, x.sent_at
          FROM ({_SENT_MESSAGES}) x
          JOIN person xs ON xs.id = x.sender_id
          JOIN person xr ON xr.id = x.recipient_id
         WHERE {counted_member_sql('xs', active=active)} AND {counted_member_sql('xr', active=active)}
    """


# One row per conversation: when it opened, who opened it, and how many
# people have written in it (2 means both sides did).
_CONVOS = """
        SELECT lo, hi, min(sent_at) AS opened_at,
               (array_agg(sender_id ORDER BY sent_at))[1] AS opener,
               count(DISTINCT sender_id) AS voices
          FROM sent GROUP BY lo, hi
"""

# Matches between active counted members that neither has blocked: a block
# hides the match from both (is_blocked_pair, migration 0035).
_MEMBER_MATCHES = f"""
        SELECT m.user_a_id, m.user_b_id, m.created_at
          FROM ahavah_match m
          JOIN person ma ON ma.id = m.user_a_id
          JOIN person mb ON mb.id = m.user_b_id
         WHERE {counted_member_sql('ma')} AND {counted_member_sql('mb')}
           AND NOT is_blocked_pair(m.user_a_id, m.user_b_id)
"""

_SILENT = """
        SELECT mm.user_a_id, mm.user_b_id, mm.created_at
          FROM member_matches mm
         WHERE mm.created_at < NOW() - INTERVAL '7 days'
           AND NOT EXISTS (SELECT 1 FROM sent x WHERE x.lo = mm.user_a_id AND x.hi = mm.user_b_id)
"""

_WITH = f"""
    WITH sent AS ({member_sent_sql(active=True)}),
    likes AS ({waiting_likes_sql()}),
    convos AS (SELECT c.* FROM ({_CONVOS}) c WHERE NOT is_blocked_pair(c.lo, c.hi)),
    member_matches AS ({_MEMBER_MATCHES}),
    silent AS ({_SILENT}),
    per AS (SELECT person_id, count(*) AS n, min(created_at) AS oldest
              FROM likes GROUP BY person_id)
"""

Q_WAITING_SUMMARY = f"""
    {_WITH}
    SELECT
      (SELECT count(*) FROM likes)::int                                   AS likes_waiting,
      (SELECT count(*) FROM per)::int                                     AS members_with_likes,
      (SELECT min(oldest) FROM per)                                       AS oldest_like_at,
      (SELECT count(*) FROM per JOIN person p ON p.id = per.person_id
        WHERE p.last_online_time < NOW() - INTERVAL '7 days')::int        AS offline_7d,
      (SELECT count(*) FROM per WHERE EXISTS (
          SELECT 1 FROM push_subscription ps WHERE ps.person_id = per.person_id))::int AS push_on,
      (SELECT count(*) FROM per WHERE n >= 5)::int                        AS with_5_or_more,
      (SELECT count(*) FROM per WHERE n BETWEEN 2 AND 4)::int             AS with_2_to_4,
      (SELECT count(*) FROM per WHERE n = 1)::int                         AS with_1,
      (SELECT count(*) FROM convos)::int                                  AS conversations,
      (SELECT count(*) FROM convos WHERE voices = 1)::int                 AS one_sided,
      (SELECT min(opened_at) FROM convos WHERE voices = 1)                AS oldest_unanswered_at,
      (SELECT count(*) FROM member_matches)::int                          AS matches,
      (SELECT count(*) FROM silent)::int                                  AS silent_matches_7d
"""

Q_WAITING_MEMBERS = f"""
    {_WITH},
    waits AS (
        SELECT person_id, created_at AS since, 'like' AS kind FROM likes
        UNION ALL
        SELECT CASE WHEN opener = lo THEN hi ELSE lo END, opened_at, 'opener'
          FROM convos WHERE voices = 1
        UNION ALL
        SELECT user_a_id, created_at, 'match' FROM silent
        UNION ALL
        SELECT user_b_id, created_at, 'match' FROM silent
    )
    SELECT p.uuid::text AS uuid, p.name,
           count(*) FILTER (WHERE w.kind = 'like')::int   AS likes_waiting,
           count(*) FILTER (WHERE w.kind = 'opener')::int AS unanswered_openers,
           count(*) FILTER (WHERE w.kind = 'match')::int  AS silent_matches,
           min(w.since)                                   AS oldest_wait_at,
           p.last_online_time                             AS last_online_at,
           EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = p.id) AS push_on
      FROM waits w
      JOIN person p ON p.id = w.person_id
     GROUP BY p.id
     ORDER BY min(w.since), p.id
     LIMIT 200
"""
```

Create `service/api/admin/community_routes.py`:

```python
"""Acting on the community (TEC-1897): who is waiting on a reply, unfinished
sign-ups and the weekly funnel. Admin role only; counts per member, never
content, never who liked whom."""
from __future__ import annotations

import duotypes as t

from database import api_tx
from service.admin import require_admin
from service.admin.jsonrow import iso_row
from service.admin.queries import community
from service.api.decorators import aget
from service.growth.queries import _excluded


@aget('/admin/community/waiting')
def get_admin_community_waiting(s: t.SessionInfo):
    require_admin(s)
    params = dict(ex=_excluded())
    with api_tx('read committed') as tx:
        summary = tx.execute(community.Q_WAITING_SUMMARY, params).fetchone()
        members = tx.execute(community.Q_WAITING_MEMBERS, params).fetchall()
    return dict(summary=iso_row(summary), members=[iso_row(r) for r in members])
```

In `service/api/__init__.py`, after `import service.api.admin.growth_routes  # noqa: E402,F401` add:

```python
# Acting on the community (TEC-1897): waiting on a reply, unfinished
# sign-ups, the weekly funnel.
import service.api.admin.community_routes  # noqa: E402,F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_community_waiting.py`
Expected: `9 passed`.

- [ ] **Step 5: Run the content guard's sibling**

Run: `RUN tests/test_admin_engagement.py`
Expected: passes as before (`_SENT_MESSAGES` is unchanged).

- [ ] **Step 6: Commit**

```bash
git add service/admin/jsonrow.py service/admin/queries/members.py service/admin/queries/community.py service/api/admin/community_routes.py service/api/__init__.py tests/test_admin_community_waiting.py
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): list members someone is waiting on, counts only" -m "Refs: TEC-1897"
```

---

### Task 6: Users: last online, "Has likes waiting" and push in the drawer

**Files:**
- Modify: `service/admin/queries/users.py` (`Q_USERS_LIST`, `Q_USERS_COUNT`, `Q_USER_PROFILE`)
- Modify: `service/api/admin/users_routes.py` (`_FILTER_KEYS`, the params, the row conversion)
- Test: `tests/test_admin_users_community.py` (create)

**Interfaces:**
- Consumes: `community.waiting_likes_sql()` (Task 5); `jsonrow.iso` (Task 5).
- Produces: `GET /admin/users` rows gain `last_online_at: str|None` (ISO) and `likes_waiting: int`; filter key `has_likes_waiting`; `GET /admin/users/<uuid>` profile gains `push_devices: int` and `push_failing: bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_users_community.py`:

```python
"""Users (TEC-1897; frame W.5): a Last online column, a "Has likes waiting"
filter and push on or off in the drawer."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def _like(a, b) -> None:
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=a['id'], b=b['id']))


def _users(client, headers, q: str, filters: str = '') -> list[dict]:
    r = client.get(f'/admin/users?q={q}&filters={filters}', headers=headers)
    assert r.status_code == 200
    return r.get_json()['rows']


def test_rows_carry_last_online_and_likes_waiting(client, admin_bearer, make_person):
    a, b = make_person(name='UsrLikerQ'), make_person(name='UsrLikedQ')
    _like(a, b)
    row = _users(client, admin_bearer, 'UsrLikedQ')[0]
    assert row['likes_waiting'] == 1
    assert row['last_online_at'].endswith('+00:00')
    assert _users(client, admin_bearer, 'UsrLikerQ')[0]['likes_waiting'] == 0


def test_the_filter_keeps_only_members_with_likes_waiting(client, admin_bearer, make_person):
    tag = uuid4().hex[:8]
    a, b = make_person(name=f'Fa{tag}'), make_person(name=f'Fb{tag}')
    _like(a, b)
    names = {r['name'] for r in _users(client, admin_bearer, tag, 'has_likes_waiting')}
    assert names == {f'Fb{tag}'}
    r = client.get(f'/admin/users?q={tag}&filters=has_likes_waiting', headers=admin_bearer)
    assert r.get_json()['total'] == 1


def test_the_drawer_says_whether_push_is_on(client, admin_bearer, make_person):
    p = make_person(name='UsrPush')
    body = client.get(f"/admin/users/{p['uuid']}", headers=admin_bearer).get_json()['profile']
    assert body['push_devices'] == 0 and body['push_failing'] is False
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, consecutive_failures)
                      VALUES (%(i)s, %(e)s, 'k', 'a', 2)""", dict(i=p['id'], e=f'https://push.test/{uuid4()}'))
    body = client.get(f"/admin/users/{p['uuid']}", headers=admin_bearer).get_json()['profile']
    assert body['push_devices'] == 1 and body['push_failing'] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_users_community.py`
Expected: `KeyError: 'likes_waiting'` and `KeyError: 'push_devices'`.

- [ ] **Step 3: Extend the queries**

In `service/admin/queries/users.py`, add at the top after the module docstring:

```python
from service.admin.queries.community import waiting_likes_sql

# Likes nobody has answered, per member (TEC-1897), for the Users list's
# "Has likes waiting" filter. Binds %(ex)s.
_WAITING = f"""
    waiting AS (
        SELECT person_id, count(*)::int AS n FROM ({waiting_likes_sql()}) w GROUP BY person_id
    )"""
```

Replace the whole `Q_USERS_LIST` and `Q_USERS_COUNT` constants with (the changes are the `waiting` CTE, `last_online_at`, `likes_waiting`, the `LEFT JOIN waiting` and the last filter line; add `#   has_likes_waiting: likes nobody has answered (TEC-1897)` to the filter list in the comment above):

```python
Q_USERS_LIST = f"""
    WITH {_WAITING.strip()},
    unified AS (
        SELECT
            COALESCE(p.email, bs.email, ws.email) AS email,
            p.uuid::text AS uuid,
            p.name AS name,
            p.sign_up_time,
            COALESCE(p.roles, ARRAY[]::text[]) AS roles,
            COALESCE(p.entitlements, ARRAY[]::text[]) AS entitlements,
            COALESCE(p.activated, TRUE) AS activated,
            (bs.email IS NOT NULL) AS in_beta,
            (ws.email IS NOT NULL) AS in_waitlist,
            (p.email IS NOT NULL) AS has_person,
            COALESCE(bs.unsubscribed_at, ws.unsubscribed_at) AS unsubscribed_at,
            p.last_online_time AS last_online_at,
            COALESCE(wt.n, 0) AS likes_waiting
          FROM person p
          FULL OUTER JOIN beta_signup bs ON bs.email = p.email
          FULL OUTER JOIN waitlist_signup ws ON ws.email = COALESCE(p.email, bs.email)
          LEFT JOIN waiting wt ON wt.person_id = p.id
    )
    SELECT *
      FROM unified
     WHERE
        (%(q)s = '' OR
         email ILIKE %(q_like)s OR
         COALESCE(name, '') ILIKE %(q_like)s OR
         COALESCE(uuid, '') ILIKE %(q_like)s)
       AND (NOT %(has_person)s OR has_person)
       AND (NOT %(waitlist_only)s OR (in_waitlist AND NOT has_person))
       AND (NOT %(beta_only)s OR (in_beta AND NOT has_person))
       AND (NOT %(unsubscribed)s OR unsubscribed_at IS NOT NULL)
       AND (NOT %(has_premium)s OR 'premium' = ANY(entitlements))
       AND (NOT %(role_admin)s OR 'admin' = ANY(roles))
       AND (NOT %(role_mod)s OR 'mod' = ANY(roles))
       AND (NOT %(has_likes_waiting)s OR likes_waiting > 0)
     ORDER BY COALESCE(sign_up_time, NOW()) DESC NULLS LAST, email
     LIMIT %(limit)s OFFSET %(offset)s
"""

Q_USERS_COUNT = f"""
    WITH {_WAITING.strip()},
    unified AS (
        SELECT
            COALESCE(p.email, bs.email, ws.email) AS email,
            p.uuid::text AS uuid,
            p.name AS name,
            COALESCE(p.roles, ARRAY[]::text[]) AS roles,
            COALESCE(p.entitlements, ARRAY[]::text[]) AS entitlements,
            (bs.email IS NOT NULL) AS in_beta,
            (ws.email IS NOT NULL) AS in_waitlist,
            (p.email IS NOT NULL) AS has_person,
            COALESCE(bs.unsubscribed_at, ws.unsubscribed_at) AS unsubscribed_at,
            COALESCE(wt.n, 0) AS likes_waiting
          FROM person p
          FULL OUTER JOIN beta_signup bs ON bs.email = p.email
          FULL OUTER JOIN waitlist_signup ws ON ws.email = COALESCE(p.email, bs.email)
          LEFT JOIN waiting wt ON wt.person_id = p.id
    )
    SELECT COUNT(*) AS total
      FROM unified
     WHERE
        (%(q)s = '' OR
         email ILIKE %(q_like)s OR
         COALESCE(name, '') ILIKE %(q_like)s OR
         COALESCE(uuid, '') ILIKE %(q_like)s)
       AND (NOT %(has_person)s OR has_person)
       AND (NOT %(waitlist_only)s OR (in_waitlist AND NOT has_person))
       AND (NOT %(beta_only)s OR (in_beta AND NOT has_person))
       AND (NOT %(unsubscribed)s OR unsubscribed_at IS NOT NULL)
       AND (NOT %(has_premium)s OR 'premium' = ANY(entitlements))
       AND (NOT %(role_admin)s OR 'admin' = ANY(roles))
       AND (NOT %(role_mod)s OR 'mod' = ANY(roles))
       AND (NOT %(has_likes_waiting)s OR likes_waiting > 0)
"""
```

In `Q_USER_PROFILE`, after `        p.location_long_friendly AS location_long` add `,` to that line and:

```sql
        (SELECT count(*)::int FROM push_subscription ps WHERE ps.person_id = p.id) AS push_devices,
        EXISTS (SELECT 1 FROM push_subscription ps
                 WHERE ps.person_id = p.id AND ps.consecutive_failures > 0) AS push_failing
```

In `service/api/admin/users_routes.py`:
- Add `'has_likes_waiting'` to the end of `_FILTER_KEYS`.
- Add the imports `from service.admin.jsonrow import iso` and `from service.growth.queries import _excluded`.
- In `get_admin_users`, add `'ex': _excluded(),` to `params`, and replace `rows = [dict(r) for r in tx.execute(Q_USERS_LIST, params).fetchall()]` with:

```python
        rows = [dict(r, last_online_at=iso(r['last_online_at']))
                for r in tx.execute(Q_USERS_LIST, params).fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_users_community.py` then `RUN tests/test_admin.py`
Expected: `3 passed`; `tests/test_admin.py` passes as before.

- [ ] **Step 5: Commit**

```bash
git add service/admin/queries/users.py service/api/admin/users_routes.py tests/test_admin_users_community.py
git -c user.email=admin@techbaseltd.com commit -m "feat(users): last online, a has likes waiting filter and push in the drawer" -m "Refs: TEC-1897"
```

---

### Task 7: Unfinished sign-ups

**Files:**
- Create: `service/admin/queries/signups.py`
- Modify: `service/api/admin/community_routes.py` (append a route)
- Test: `tests/test_admin_unfinished_signups.py` (create)

**Interfaces:**
- Consumes: `onboardee`, `onboardee_photo`; `_excluded()`; `jsonrow.iso_row`.
- Produces: `signups.STEPS` (the step keys in sign-up order); `signups.Q_UNFINISHED` (binds `%(ex)s`); `GET /admin/community/unfinished` answering `{'count': int, 'rows': [{'started_at': str, 'last_saved_at': str, 'furthest_step': str}]}`, newest first, at most 200. No name or address leaves the server: the design's U.1 shows dates and a step only.

What the database can say, read on 18 Oct:
- An `onboardee` row is written when an address enters its first sign-in code and is deleted when the person finishes (their `person` row then exists), when they sign in again more than an hour after their last save (`Q_MAYBE_DELETE_ONBOARDEE`), and by the garbage cron once nothing has been saved for a week (`service/cron/garbagerecords`). So the list holds people who stopped within the last 7 days, and "Started" is the first sign-in of their current attempt.
- During sign-up the server stores only name, date of birth, gender, photos, the country step's location and the `ahavah_extra` answers the web sends while onboarding (`ahavah-web/src/lib/use-profile.ts` `ONBOARDEE_ALLOWED_KEYS`). Verify email, verify phone, marital status, children and looking for leave no server record, so the furthest step is the furthest of: `none` (signed in, saved nothing), `name`, `date_of_birth`, `gender`, `photos`, `country`, `assembly`, `relocation`, in the web's order (`ahavah-web/src/lib/wizard-flow.ts`).
- A row saved within the last hour is someone still signing up, and is left out.
- A row with a `lead_source` came from a couple tool or the checklist (`service/person` sets it); it is left out unless that person saved a sign-up step.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_unfinished_signups.py`:

```python
"""Unfinished sign-ups (TEC-1897; frames U.1 to U.4): when they started, when
they last saved and the furthest step the server recorded. No address."""
from __future__ import annotations

from collections import Counter
from datetime import date
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from database import api_tx


@pytest.fixture
def onboardee():
    made: list[str] = []

    def _make(*, idle_hours: float = 3, lead_source=None, email=None, **fields) -> str:
        email = email or f'unfinished-{uuid4().hex[:10]}@example.com'
        cols = dict(email=email, lead_source=lead_source, **fields)
        names = ', '.join(cols)
        values = ', '.join(f'%({k})s' for k in cols)
        with api_tx() as tx:
            tx.execute(f"INSERT INTO onboardee ({names}) VALUES ({values})", cols)
            # make_interval's `hours` takes an integer only; `secs` takes the
            # fractional idle times the tests use (0.2 hours).
            tx.execute("""UPDATE onboardee SET created_at = NOW() - make_interval(secs => %(h)s * 7200),
                                               updated_at = NOW() - make_interval(secs => %(h)s * 3600)
                           WHERE email = %(e)s""", dict(h=idle_hours, e=email))
        made.append(email)
        return email

    yield _make
    with api_tx() as tx:
        tx.execute("DELETE FROM onboardee WHERE email = ANY(%(e)s)", dict(e=made))


def _rows(client, headers) -> dict:
    r = client.get('/admin/community/unfinished', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _steps(body) -> Counter:
    """The shared database holds other rows, so tests compare step counts
    before and after rather than reading positions."""
    return Counter(r['furthest_step'] for r in body['rows'])


def test_admins_only(client, make_person, sign_in):
    assert client.get('/admin/community/unfinished',
                      headers=sign_in(make_person(name='UfMember'))).status_code == 403


def test_a_stalled_sign_up_is_listed_with_its_furthest_step(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)
    onboardee(name='Rivka', date_of_birth=date(1990, 1, 1))
    body = _rows(client, admin_bearer)
    assert body['count'] - before['count'] == 1
    assert _steps(body) - _steps(before) == Counter({'date_of_birth': 1})
    assert all(r['started_at'].endswith('+00:00') for r in body['rows'])
    assert 'example.com' not in str(body) and 'Rivka' not in str(body)


def test_steps_follow_the_sign_up_order(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)
    onboardee(name='A', gender_id=1, ahavah_extra=Jsonb({'assembly': ['x']}))
    onboardee()
    after = _rows(client, admin_bearer)
    assert _steps(after) - _steps(before) == Counter({'assembly': 1, 'none': 1})


def test_someone_still_signing_up_is_not_listed(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)['count']
    onboardee(idle_hours=0.2, name='Busy')
    assert _rows(client, admin_bearer)['count'] == before


def test_a_tool_visitor_who_saved_no_step_is_not_listed(client, admin_bearer, onboardee):
    before = _rows(client, admin_bearer)['count']
    onboardee(lead_source='tool:game-us')
    assert _rows(client, admin_bearer)['count'] == before
    onboardee(lead_source='tool:checklist', name='Started anyway')
    assert _rows(client, admin_bearer)['count'] == before + 1


def test_staff_addresses_and_finished_members_are_not_listed(client, admin_bearer, onboardee, make_person):
    before = _rows(client, admin_bearer)['count']
    try:
        onboardee(email='admin@techbaseltd.com', name='Staff')
    except Exception:  # a real row for the staff address already exists
        pytest.skip('an onboardee row exists for the staff address')
    member = make_person(name='Finished')
    with api_tx('read committed') as tx:
        email = tx.execute("SELECT email FROM person WHERE id = %(i)s",
                           dict(i=member['id'])).fetchone()['email']
    onboardee(email=email, name='Finished')
    assert _rows(client, admin_bearer)['count'] == before
```

The staff row is made only when the shared database has none for that address, and the fixture deletes only the rows it made.

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_unfinished_signups.py`
Expected: 404 on `/admin/community/unfinished`.

- [ ] **Step 3: Write the query and the route**

Create `service/admin/queries/signups.py`:

```python
"""Unfinished sign-ups (TEC-1897; frames U.1 to U.4).

An `onboardee` row exists from the first sign-in code until the person
finishes, signs in again more than an hour after their last save, or saves
nothing for a week (the garbage cron). So this lists people who stopped
within the last 7 days. Only steps the server stores can be the furthest
step; verify email, verify phone, marital status, children and looking for
leave no server record during sign-up. Dates and a step only: no name and
no address leave the server.
"""
from __future__ import annotations

# In the web's order (ahavah-web src/lib/wizard-flow.ts), limited to the
# steps the server records. 'none' is someone who signed in and saved
# nothing, which the design calls "The first step".
STEPS = ('none', 'name', 'date_of_birth', 'gender', 'photos', 'country', 'assembly', 'relocation')

_STEP = """
    CASE
      WHEN o.ahavah_extra ? 'relocation' THEN 'relocation'
      WHEN o.ahavah_extra ? 'assembly' THEN 'assembly'
      WHEN o.coordinates IS NOT NULL THEN 'country'
      WHEN EXISTS (SELECT 1 FROM onboardee_photo ph WHERE ph.email = o.email) THEN 'photos'
      WHEN o.gender_id IS NOT NULL THEN 'gender'
      WHEN o.date_of_birth IS NOT NULL THEN 'date_of_birth'
      WHEN o.name IS NOT NULL THEN 'name'
      ELSE 'none'
    END
"""

Q_UNFINISHED = f"""
    WITH o AS (
        SELECT o.created_at, o.updated_at, o.lead_source, {_STEP} AS furthest_step
          FROM onboardee o
         WHERE NOT EXISTS (SELECT 1 FROM person p WHERE lower(p.email) = lower(o.email))
           AND lower(o.email) <> ALL(%(ex)s)
           AND o.updated_at < NOW() - INTERVAL '1 hour'
    )
    SELECT created_at AS started_at, updated_at AS last_saved_at, furthest_step
      FROM o
     WHERE lead_source IS NULL OR furthest_step <> 'none'
     ORDER BY created_at DESC
     LIMIT 200
"""
```

Append to `service/api/admin/community_routes.py`:

```python
@aget('/admin/community/unfinished')
def get_admin_community_unfinished(s: t.SessionInfo):
    """People who started sign-up and stopped (frames U.1 to U.4)."""
    require_admin(s)
    from service.admin.queries.signups import Q_UNFINISHED
    with api_tx('read committed') as tx:
        rows = [iso_row(r) for r in tx.execute(Q_UNFINISHED, dict(ex=_excluded())).fetchall()]
    return dict(count=len(rows), rows=rows)
```

`onboardee.created_at` is a naive `TIMESTAMP` holding UTC, so `iso_row` marks it `+00:00`.

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_unfinished_signups.py`
Expected: `6 passed` (or 5 passed and 1 skipped if a real staff onboardee row exists).

- [ ] **Step 5: Commit**

```bash
git add service/admin/queries/signups.py service/api/admin/community_routes.py tests/test_admin_unfinished_signups.py
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): list unfinished sign-ups with the furthest step the server recorded" -m "Refs: TEC-1897"
```

---

### Task 8: The weekly funnel

**Files:**
- Modify: `service/admin/queries/community.py` (append `Q_WEEKLY_FUNNEL`)
- Modify: `service/api/admin/community_routes.py` (append a route)
- Test: `tests/test_admin_funnel.py` (create)

**Interfaces:**
- Consumes: `member_sent_sql(active=False)`, `counted_member_sql(active=False)` (Task 5); `BARBADOS_TODAY` from `service/admin/queries/days.py`.
- Produces: `community.Q_WEEKLY_FUNNEL` (binds `%(ex)s`); `GET /admin/community/funnel` answering `{'weeks': [{'week_start': 'YYYY-MM-DD', 'likes': int, 'matches': int, 'first_messages': int, 'replies': int}]}`, 12 rows, oldest first, each a Barbados week from Monday.

Definitions: likes are `liked` rows between members; matches are `ahavah_match` rows between members (the Growth tab's measure); a first message is the first message of a conversation; a reply is the first message in a conversation from the person who did not open it. Each counts in the Barbados week it happened. History counts members who have since deactivated (`active=False`). A member who deletes their account takes their rows with them (`ON DELETE CASCADE`), so past weeks can fall slightly; there is no other record.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_funnel.py`:

```python
"""The weekly funnel (TEC-1897; frame O.1): likes, matches, first messages
and replies per Barbados week over 12 weeks. Never content."""
from __future__ import annotations

from database import api_tx
from service.admin.queries import community

_SEQ = [0]


def _funnel(client, headers) -> list[dict]:
    r = client.get('/admin/community/funnel', headers=headers)
    assert r.status_code == 200
    return r.get_json()['weeks']


def _message(sender, recipient) -> None:
    _SEQ[0] += 1
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(s)s AS id",
            dict(s=(_SEQ[0] + 100) % 256)).fetchone()['id']
        for direction, owner, other in (('O', sender, recipient), ('I', recipient, sender)):
            tx.execute("""INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
                          VALUES (%(id)s, %(d)s, ''::bytea, %(p)s, '', %(j)s)""",
                       dict(id=mam_id + (direction == 'I'), d=direction, p=owner['id'], j=other['uuid']))


def test_twelve_weeks_oldest_first_ending_this_week(client, admin_bearer):
    weeks = _funnel(client, admin_bearer)
    assert len(weeks) == 12
    with api_tx('read committed') as tx:
        this_monday = tx.execute(
            "SELECT date_trunc('week', (NOW() AT TIME ZONE 'America/Barbados'))::date AS d").fetchone()['d']
    assert weeks[-1]['week_start'] == this_monday.isoformat()
    assert weeks == sorted(weeks, key=lambda w: w['week_start'])


def test_this_weeks_likes_match_first_message_and_reply(client, admin_bearer, make_person):
    a, b = make_person(name='FunA'), make_person(name='FunB')
    before = _funnel(client, admin_bearer)[-1]
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s), (%(b)s, %(a)s)",
                   dict(a=a['id'], b=b['id']))
        lo, hi = sorted([a['id'], b['id']])
        tx.execute("INSERT INTO ahavah_match (user_a_id, user_b_id) VALUES (%(a)s, %(b)s)",
                   dict(a=lo, b=hi))
    _message(a, b)
    _message(a, b)  # a second message from the opener is not a reply
    _message(b, a)
    after = _funnel(client, admin_bearer)[-1]
    assert {k: after[k] - before[k] for k in ('likes', 'matches', 'first_messages', 'replies')} == dict(
        likes=2, matches=1, first_messages=1, replies=1)


def test_the_week_is_the_barbados_week(client, admin_bearer, make_person):
    a, b = make_person(name='FunC'), make_person(name='FunD')
    weeks_before = _funnel(client, admin_bearer)
    with api_tx() as tx:
        # Sunday 23:00 in Barbados is Monday 03:00 UTC: last week, not this one.
        tx.execute(
            """INSERT INTO liked (liker_id, liked_id, created_at)
               VALUES (%(a)s, %(b)s,
                       (date_trunc('week', NOW() AT TIME ZONE 'America/Barbados') - INTERVAL '1 hour')
                         AT TIME ZONE 'America/Barbados')""",
            dict(a=a['id'], b=b['id']))
    weeks_after = _funnel(client, admin_bearer)
    assert weeks_after[-2]['likes'] - weeks_before[-2]['likes'] == 1
    assert weeks_after[-1]['likes'] == weeks_before[-1]['likes']


def test_staff_likes_are_not_counted(client, admin_bearer, make_person):
    staff, member = make_person(name='FunStaff'), make_person(name='FunMem')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = _funnel(client, admin_bearer)[-1]['likes']
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=staff['id'], b=member['id']))
    assert _funnel(client, admin_bearer)[-1]['likes'] == before


def test_the_funnel_reads_no_content():
    low = community.Q_WEEKLY_FUNNEL.lower()
    for forbidden in ('m.message', 'search_body', 'translations', 'audio_uuid'):
        assert forbidden not in low
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_funnel.py`
Expected: `AttributeError: module 'service.admin.queries.community' has no attribute 'Q_WEEKLY_FUNNEL'` and 404s.

- [ ] **Step 3: Write the query and the route**

Append to `service/admin/queries/community.py`:

```python
from service.admin.queries.days import BARBADOS_TODAY  # noqa: E402


def _week(col: str) -> str:
    """The Monday of the Barbados week a timestamptz falls in."""
    return f"date_trunc('week', ({col} AT TIME ZONE 'America/Barbados'))::date"


Q_WEEKLY_FUNNEL = f"""
    WITH weeks AS (
        SELECT generate_series(
                 date_trunc('week', ({BARBADOS_TODAY})::timestamp) - INTERVAL '11 weeks',
                 date_trunc('week', ({BARBADOS_TODAY})::timestamp),
                 INTERVAL '1 week')::date AS wk
    ),
    likes AS (
        SELECT {_week('l.created_at')} AS wk
          FROM liked l
          JOIN person a ON a.id = l.liker_id
          JOIN person b ON b.id = l.liked_id
         WHERE {counted_member_sql('a', active=False)} AND {counted_member_sql('b', active=False)}
    ),
    matches AS (
        SELECT {_week('m.created_at')} AS wk
          FROM ahavah_match m
          JOIN person ma ON ma.id = m.user_a_id
          JOIN person mb ON mb.id = m.user_b_id
         WHERE {counted_member_sql('ma', active=False)} AND {counted_member_sql('mb', active=False)}
    ),
    sent AS ({member_sent_sql(active=False)}),
    convos AS ({_CONVOS}),
    replies AS (
        SELECT c.lo, c.hi, min(x.sent_at) AS replied_at
          FROM convos c
          JOIN sent x ON x.lo = c.lo AND x.hi = c.hi AND x.sender_id <> c.opener
         GROUP BY c.lo, c.hi
    )
    SELECT w.wk AS week_start,
           (SELECT count(*) FROM likes x WHERE x.wk = w.wk)::int                      AS likes,
           (SELECT count(*) FROM matches x WHERE x.wk = w.wk)::int                    AS matches,
           (SELECT count(*) FROM convos c WHERE {_week('c.opened_at')} = w.wk)::int   AS first_messages,
           (SELECT count(*) FROM replies r WHERE {_week('r.replied_at')} = w.wk)::int AS replies
      FROM weeks w
     ORDER BY w.wk
"""
```

Append to `service/api/admin/community_routes.py`:

```python
@aget('/admin/community/funnel')
def get_admin_community_funnel(s: t.SessionInfo):
    """Likes, matches, first messages and replies per Barbados week, 12
    weeks, oldest first (frame O.1)."""
    require_admin(s)
    with api_tx('read committed') as tx:
        weeks = [iso_row(r) for r in tx.execute(community.Q_WEEKLY_FUNNEL,
                                                dict(ex=_excluded())).fetchall()]
    return dict(weeks=weeks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_funnel.py`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/admin/queries/community.py service/api/admin/community_routes.py tests/test_admin_funnel.py
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): the weekly funnel of likes, matches, first messages and replies" -m "Refs: TEC-1897"
```

---

### Task 9: Push subscribers and verification tiers

**Files:**
- Create: `service/admin/queries/push.py`
- Create: `service/admin/queries/profiles.py` (tiers now; Task 12 adds the rest)
- Modify: `service/api/admin/growth_routes.py` (append 2 routes after `get_admin_growth_sources`)
- Test: `tests/test_admin_push_tiers.py` (create)

**Interfaces:**
- Consumes: `counted_member_sql` (Task 5); `_excluded()`.
- Produces: `push.Q_PUSH` (binds `%(ex)s`, `%(since)s`); `push.PUSH_BANNER_SHIPPED = '2026-10-01'`; `profiles.TIERS = ('none', 'bronze', 'silver', 'gold')`; `profiles.Q_VERIFICATION_TIERS` (binds `%(ex)s`); `GET /admin/growth/push?since=YYYY-MM-DD` answering `{members, members_with_push, with_push_counting_staff, members_failing, members_new_since, since}`; `GET /admin/growth/tiers` answering `{'tiers': [{'tier': str, 'members': int}]}` in the order of `TIERS`.

Frame G.1's Push tile reads "11 of 58 members have push on", "Counting staff accounts 13", "Failing 0", "New since 1 Oct 2". A member has push on while they have at least one `push_subscription` row. The API deletes a subscription that the push service refuses (404 or 410) or that keeps failing (migration 0030), so "new since" counts the members whose oldest surviving subscription is that recent; a subscription that was made and later removed is not counted anywhere. "New per week" stays "Not measured" (see the conflicts section).

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_push_tiers.py`:

```python
"""Growth: push subscribers and verification tiers (TEC-1897; frame G.1)."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx


def _sub(person, *, failures: int = 0, days_ago: int = 0) -> None:
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, consecutive_failures, created_at)
               VALUES (%(i)s, %(e)s, 'k', 'a', %(f)s, NOW() - make_interval(days => %(d)s))""",
            dict(i=person['id'], e=f'https://push.test/{uuid4()}', f=failures, d=days_ago))


def _push(client, headers, since='2026-10-01') -> dict:
    r = client.get(f'/admin/growth/push?since={since}', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def test_push_counts_members_and_says_which_count_has_staff(client, admin_bearer, make_person):
    a, b, staff = make_person(name='PushA'), make_person(name='PushB'), make_person(name='PushStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = _push(client, admin_bearer)
    _sub(a)
    _sub(a)  # two devices are one member
    _sub(b, failures=3, days_ago=400)  # long before 1 Oct 2026, whenever this runs
    _sub(staff)
    after = _push(client, admin_bearer)
    delta = {k: after[k] - before[k] for k in
             ('members', 'members_with_push', 'with_push_counting_staff', 'members_failing', 'members_new_since')}
    assert delta == dict(members=0, members_with_push=2, with_push_counting_staff=3,
                         members_failing=1, members_new_since=1)
    assert after['since'] == '2026-10-01'


def test_a_bad_since_is_refused(client, admin_bearer):
    assert client.get('/admin/growth/push?since=last-week', headers=admin_bearer).status_code == 400


def test_tiers_count_members_in_order(client, admin_bearer, make_person):
    p, staff = make_person(name='TierGold'), make_person(name='TierStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = client.get('/admin/growth/tiers', headers=admin_bearer).get_json()['tiers']
    assert [t['tier'] for t in before] == ['none', 'bronze', 'silver', 'gold']
    with api_tx() as tx:
        tx.execute("UPDATE person SET ahavah_verification_tier = 'gold' WHERE id = ANY(%(i)s)",
                   dict(i=[p['id'], staff['id']]))
    after = client.get('/admin/growth/tiers', headers=admin_bearer).get_json()['tiers']
    assert {a['tier']: a['members'] - b['members'] for a, b in zip(after, before)} == dict(
        none=-1, bronze=0, silver=0, gold=1)
```

Both people are made, and the staff role set, before `before` is read: the member moves from none to gold, and the staff account is never counted whatever its tier.

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_push_tiers.py`
Expected: 404 on both routes.

- [ ] **Step 3: Write the queries and routes**

Create `service/admin/queries/push.py`:

```python
"""Push subscribers for Growth (TEC-1897; frame G.1).

A member has push on while at least one push_subscription row is theirs.
Rows the push service refuses are deleted (migration 0030), so "new since"
counts members whose oldest surviving subscription is that recent. Binds
%(ex)s and %(since)s (a Barbados date).
"""
from __future__ import annotations

from service.admin.queries.members import counted_member_sql

# The Discover banner that asks members to turn push on shipped on 1 Oct
# 2026 (design brief, section 6), so the tile counts from that day.
PUSH_BANNER_SHIPPED = '2026-10-01'

Q_PUSH = f"""
    WITH m AS (
        SELECT p.id,
               (SELECT min(ps.created_at) FROM push_subscription ps WHERE ps.person_id = p.id) AS first_sub,
               EXISTS (SELECT 1 FROM push_subscription ps
                        WHERE ps.person_id = p.id AND ps.consecutive_failures > 0) AS failing
          FROM person p
         WHERE {counted_member_sql('p')}
    )
    SELECT count(*)::int                                          AS members,
           count(*) FILTER (WHERE first_sub IS NOT NULL)::int     AS members_with_push,
           count(*) FILTER (WHERE failing)::int                   AS members_failing,
           count(*) FILTER (WHERE first_sub >=
               (%(since)s::date::timestamp AT TIME ZONE 'America/Barbados'))::int AS members_new_since,
           (SELECT count(DISTINCT ps.person_id) FROM push_subscription ps
              JOIN person p ON p.id = ps.person_id WHERE p.activated)::int AS with_push_counting_staff
      FROM m
"""
```

Create `service/admin/queries/profiles.py`:

```python
"""Verification tiers, profile gaps, the photo gate list and approved photos
with no face (TEC-1897; frames G.1, P.1, P.2 and P.3).

CONTENT IS NEVER READ: the gate list counts a member's sent messages from
mam_message's id, direction and person only.
"""
from __future__ import annotations

from service.admin.queries.members import counted_member_sql, member_sql

TIERS = ('none', 'bronze', 'silver', 'gold')

Q_VERIFICATION_TIERS = f"""
    SELECT t.tier, count(p.id)::int AS members
      FROM unnest(ARRAY['none', 'bronze', 'silver', 'gold']) WITH ORDINALITY AS t(tier, ord)
      LEFT JOIN person p
        ON p.ahavah_verification_tier::text = t.tier AND {counted_member_sql('p')}
     GROUP BY t.tier, t.ord
     ORDER BY t.ord
"""
```

Append to `service/api/admin/growth_routes.py` after `get_admin_growth_sources`:

```python
@aget('/admin/growth/push')
def get_admin_growth_push(s: t.SessionInfo):
    """Push on, failing and new since a day (frame G.1). Members only,
    except `with_push_counting_staff`, which the tile labels so."""
    require_admin(s)
    from datetime import date
    from service.admin.queries.push import PUSH_BANNER_SHIPPED, Q_PUSH
    from service.growth.queries import _excluded
    since = request.args.get('since') or PUSH_BANNER_SHIPPED
    try:
        date.fromisoformat(since)
    except ValueError:
        abort(400)
    with api_tx('read committed') as tx:
        row = tx.execute(Q_PUSH, dict(ex=_excluded(), since=since)).fetchone()
    return dict(row, since=since)


@aget('/admin/growth/tiers')
def get_admin_growth_tiers(s: t.SessionInfo):
    """Members per verification tier, none first (frame G.1)."""
    require_admin(s)
    from service.admin.queries.profiles import Q_VERIFICATION_TIERS
    from service.growth.queries import _excluded
    with api_tx('read committed') as tx:
        rows = tx.execute(Q_VERIFICATION_TIERS, dict(ex=_excluded())).fetchall()
    return dict(tiers=[dict(r) for r in rows])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_push_tiers.py`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/admin/queries/push.py service/admin/queries/profiles.py service/api/admin/growth_routes.py tests/test_admin_push_tiers.py
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): push subscribers and verification tiers for the admin" -m "Refs: TEC-1897"
```

---

### Task 10: Record the days a member is online

**Files:**
- Modify: `commonsql/__init__.py` (`Q_UPDATE_LAST`, line 41)
- Modify: `service/person/__init__.py` (`bump_presence`, line 315)
- Test: `tests/test_member_online_day.py` (create)

**Interfaces:**
- Consumes: `member_online_day` (Task 1).
- Produces: every presence bump (the chat socket's `Q_UPDATE_LAST` and the REST `bump_presence`) upserts `member_online_day(person_id, today in Barbados)`, setting `first_at` on the first bump of the day and `last_at` on every bump. Task 11 reads it for "Came back within 7 days".

Both writers keep their existing behaviour exactly: the person update and the presence histogram are unchanged, and the day row is a second, data-modifying CTE driven by the same `UPDATE ... RETURNING`. The REST bump still writes nothing inside its 10 minute throttle. The migration runs before the containers restart, so the table exists before this code does.

- [ ] **Step 1: Write the failing test**

Create `tests/test_member_online_day.py`:

```python
"""The days a member is online (TEC-1897): written with each presence bump
so "came back within 7 days of an email" can be answered. Presence itself
must move exactly as before, or autodeactivate2 logs active members out."""
from __future__ import annotations

from commonsql import Q_UPDATE_LAST
from database import api_tx
from service.person import bump_presence


def _set_last_online(person, interval: str) -> None:
    with api_tx() as tx:
        tx.execute(f"UPDATE person SET last_online_time = NOW() - INTERVAL '{interval}' WHERE id = %(i)s",
                   dict(i=person['id']))


def _state(person) -> dict:
    with api_tx('read committed') as tx:
        return dict(tx.execute(
            """SELECT p.last_online_time > NOW() - INTERVAL '1 minute' AS fresh,
                      d.first_at, d.last_at
                 FROM person p
                 LEFT JOIN member_online_day d
                   ON d.person_id = p.id AND d.day = (NOW() AT TIME ZONE 'America/Barbados')::date
                WHERE p.id = %(i)s""", dict(i=person['id'])).fetchone())


def test_presence_still_moves_last_online(make_person):
    p = make_person(name='PresChat')
    _set_last_online(p, '2 days')
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    s = _state(p)
    assert s['fresh'] is True and s['first_at'] is not None and s['first_at'] == s['last_at']


def test_a_second_bump_keeps_the_first_time_of_the_day(make_person):
    p = make_person(name='PresTwice')
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    first = _state(p)['first_at']
    with api_tx() as tx:
        tx.execute(Q_UPDATE_LAST, dict(person_uuid=p['uuid']))
    s = _state(p)
    assert s['first_at'] == first and s['last_at'] >= first


def test_the_rest_bump_records_the_day_too(make_person):
    p = make_person(name='PresRest')
    _set_last_online(p, '1 hour')
    bump_presence(p['id'])
    s = _state(p)
    assert s['fresh'] is True and s['first_at'] is not None


def test_a_bump_inside_ten_minutes_writes_nothing(make_person):
    p = make_person(name='PresQuiet')
    _set_last_online(p, '2 minutes')
    bump_presence(p['id'])
    assert _state(p)['first_at'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_member_online_day.py`
Expected: the first 3 fail on `assert ... s['first_at'] is not None`; the last passes.

- [ ] **Step 3: Write the day with each bump**

In `commonsql/__init__.py`, replace the opening of `Q_UPDATE_LAST`:

```python
Q_UPDATE_LAST = """
WITH updated_person AS (
    UPDATE
        person
    SET
        last_online_time = NOW()
    WHERE
        uuid = %(person_uuid)s
    RETURNING
        id
)
INSERT INTO presence_histogram (
```

with:

```python
Q_UPDATE_LAST = """
WITH updated_person AS (
    UPDATE
        person
    SET
        last_online_time = NOW()
    WHERE
        uuid = %(person_uuid)s
    RETURNING
        id
), online_day AS (
    -- The Barbados days a person was online (TEC-1897, migration 0069):
    -- last_online_time keeps only the latest moment.
    INSERT INTO member_online_day (person_id, day, first_at, last_at)
    SELECT id, (NOW() AT TIME ZONE 'America/Barbados')::date, NOW(), NOW()
    FROM updated_person
    ON CONFLICT (person_id, day) DO UPDATE SET last_at = EXCLUDED.last_at
)
INSERT INTO presence_histogram (
```

In `service/person/__init__.py`, inside `bump_presence`, replace:

```python
        tx.execute(
            """
            UPDATE person SET last_online_time = NOW()
            WHERE id = %(id)s
              AND last_online_time < NOW() - INTERVAL '10 minutes'
            """, dict(id=person_id))
```

with:

```python
        # The day row rides on the same throttled update (TEC-1897): no
        # bump, no write.
        tx.execute(
            """
            WITH bumped AS (
                UPDATE person SET last_online_time = NOW()
                WHERE id = %(id)s
                  AND last_online_time < NOW() - INTERVAL '10 minutes'
                RETURNING id
            )
            INSERT INTO member_online_day (person_id, day, first_at, last_at)
            SELECT id, (NOW() AT TIME ZONE 'America/Barbados')::date, NOW(), NOW()
              FROM bumped
            ON CONFLICT (person_id, day) DO UPDATE SET last_at = EXCLUDED.last_at
            """, dict(id=person_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_member_online_day.py`
Expected: `4 passed`.

- [ ] **Step 5: Run the suites that lean on presence**

Run: `RUN tests/test_garbage_and_beta.py` then `RUN tests/test_notification_fallback.py`
Expected: both pass as before.

- [ ] **Step 6: Commit**

```bash
git add commonsql/__init__.py service/person/__init__.py tests/test_member_online_day.py
git -c user.email=admin@techbaseltd.com commit -m "feat(presence): record the Barbados days a member is online" -m "Refs: TEC-1897"
```

---

### Task 11: What each email achieved: came back, push turned on and run history

**Files:**
- Create: `service/growth/email_outcomes.py` (with `_Q_RUN_RESULTS` and its comment, `service/api/admin/growth_routes.py:90-117`, and `_run_results`, lines 129-133, moved out of the route module; `_NEXT_RUN_ID` between them stays)
- Modify: `service/api/admin/growth_routes.py` (`get_admin_growth_emails`; a new route)
- Test: `tests/test_admin_email_outcomes.py` (create)

**Interfaces:**
- Consumes: `email_send_log`, `campaign_link`, `campaign_click`, `email_outbox`, `admin_audit_log`, `push_subscription`, `member_online_day` (Task 10); `SEND_AUDIT_ACTION` (`service/campaigns/runner.py`); `record_system_audit`.
- Produces:
  - `email_outcomes.run_results(tx, campaign, campaign_id) -> tuple[int|None, int|None]` (moved, unchanged).
  - `email_outcomes.run_outcomes(tx, campaign, campaign_id) -> {'came_back': int|None, 'came_back_7d': int|None, 'push_turned_on': int|None}`; `came_back_7d` is None when the per-day record started after the run; `push_turned_on` only for `e6`.
  - `email_outcomes.started_by(actor_email: str|None) -> 'schedule'|'command_line'|'send_button'|None`.
  - `email_outcomes.run_history(tx, campaign, limit=12) -> [{'campaign_id', 'sent_at', 'started_by', 'reached', 'clicks', 'came_back', 'came_back_7d'}]`, newest first.
  - `email_outcomes.last_30_days(tx, campaign) -> {'sends': int, 'people': int, 'came_back': int}`.
  - `email_outcomes.came_back_all_time(tx, campaign) -> int`.
  - `GET /admin/growth/emails` admin-run rows gain `last_run_came_back`, `last_run_came_back_7d`, `last_run_push_turned_on`; system rows gain `came_back`.
  - `GET /admin/growth/emails/<campaign>/runs` (e1, e2, e3, e6) answering `{'runs': [...], 'last_30_days': {...}}`; 404 for any other campaign.

Definitions, from frame G.1's footnote "Came back counts anyone online since the send. The email may not have caused it.": a recipient came back when `person.last_online_time` is later than their send. Within 7 days: a `member_online_day` row overlapping the 7 days after the send. Push turned on: a recipient of the notifications email (`e6`) with a subscription made after their send that still exists. "Started by" reads the run's earliest non-dry audit row: actor `cron` is the schedule, `cli` the command line, an admin's address the Send button; runs before 13 Oct 2026 have no audit row (health review) and read None. An admin reactivating a member also moves `last_online_time` (`users_action_routes.py` `_Q_REACTIVATE`), which would count as coming back; this is listed as a conflict.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_email_outcomes.py`:

```python
"""What each email achieved (TEC-1897; frames G.1, G.2 and G.4): came back
any time and within 7 days, push turned on, and each run's history."""
from __future__ import annotations

from uuid import uuid4

from database import api_tx
from service.admin import record_system_audit
from service.campaigns.runner import SEND_AUDIT_ACTION
from service.growth import email_outcomes


def _send(person, campaign: str, cid: str, hours_ago: float = 1) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, %(c)s, %(cid)s, NOW() - make_interval(secs => %(s)s))""",
                   dict(p=person['id'], c=campaign, cid=cid, s=hours_ago * 3600))


def _online(person, *, days_ago: int = 0, recorded: bool = True) -> None:
    with api_tx() as tx:
        tx.execute("UPDATE person SET last_online_time = NOW() - make_interval(days => %(d)s) WHERE id = %(i)s",
                   dict(d=days_ago, i=person['id']))
        if recorded:
            tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                          VALUES (%(i)s, (NOW() AT TIME ZONE 'America/Barbados')::date
                                         - %(d)s, NOW() - make_interval(days => %(d)s),
                                         NOW() - make_interval(days => %(d)s))
                          ON CONFLICT (person_id, day) DO UPDATE SET last_at = EXCLUDED.last_at""",
                       dict(i=person['id'], d=days_ago))


def _recording_since_a_month_ago(make_person) -> None:
    """The per-day record must predate the run for a 7 day figure."""
    keeper = make_person(name='RecKeeper')
    with api_tx() as tx:
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(i)s, CURRENT_DATE - 30, NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days')""",
                   dict(i=keeper['id']))


def test_came_back_and_push_turned_on_for_one_run(make_person):
    _recording_since_a_month_ago(make_person)
    back, away, pushed = (make_person(name=n) for n in ('OutBack', 'OutAway', 'OutPush'))
    cid = f'test-{uuid4().hex[:8]}'
    for p in (back, away, pushed):
        _send(p, 'e6', cid, hours_ago=2)
    _online(back)
    _online(away, days_ago=1, recorded=False)
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_subscription (person_id, endpoint, p256dh, auth)
                      VALUES (%(i)s, %(e)s, 'k', 'a')""", dict(i=pushed['id'], e=f'https://push.test/{uuid4()}'))
        out = email_outcomes.run_outcomes(tx, 'e6', cid)
    # pushed's last_online_time is make_person's default NOW(), after the send.
    assert out == dict(came_back=2, came_back_7d=1, push_turned_on=1)


def test_seven_days_is_not_measured_before_the_record_began(make_person):
    p = make_person(name='OutOld')
    cid = f'test-{uuid4().hex[:8]}'
    _send(p, 'e2', cid, hours_ago=24 * 400)
    with api_tx() as tx:
        out = email_outcomes.run_outcomes(tx, 'e2', cid)
    assert out['came_back'] == 1 and out['came_back_7d'] is None and out['push_turned_on'] is None


def test_started_by():
    assert email_outcomes.started_by('cron') == 'schedule'
    assert email_outcomes.started_by('cli') == 'command_line'
    assert email_outcomes.started_by('owner@example.com') == 'send_button'
    assert email_outcomes.started_by(None) is None


def test_run_history_and_the_last_30_days(client, admin_bearer, make_person):
    a, b = make_person(name='HistA'), make_person(name='HistB')
    cid = f'test-{uuid4().hex[:8]}'
    _send(a, 'e2', cid, hours_ago=0.5)
    _send(b, 'e2', cid, hours_ago=0.5)
    with api_tx() as tx:
        record_system_audit(tx, 'cron', SEND_AUDIT_ACTION,
                            dict(campaign='e2', campaign_id=cid, dry_run=False, queued=2))
    r = client.get('/admin/growth/emails/e2/runs', headers=admin_bearer)
    assert r.status_code == 200
    body = r.get_json()
    run = next(x for x in body['runs'] if x['campaign_id'] == cid)
    assert run['started_by'] == 'schedule' and run['reached'] == 2
    assert run['came_back'] == 2 and run['clicks'] is None
    assert run['sent_at'].endswith('+00:00')
    assert body['last_30_days']['sends'] >= 2 and body['last_30_days']['people'] >= 2


def test_runs_are_for_admin_run_emails_only(client, admin_bearer):
    assert client.get('/admin/growth/emails/welcome/runs', headers=admin_bearer).status_code == 404
    assert client.get('/admin/growth/emails/e9/runs', headers=admin_bearer).status_code == 404


def test_the_emails_index_carries_the_outcomes(client, admin_bearer, make_person):
    p = make_person(name='IdxBack')
    _send(p, 'welcome', f'test-{uuid4().hex[:8]}', hours_ago=1)
    body = client.get('/admin/growth/emails', headers=admin_bearer).get_json()['campaigns']
    rows = {c['campaign']: c for c in body}
    for key in ('e1', 'e2', 'e3', 'e6'):
        assert {'last_run_came_back', 'last_run_came_back_7d', 'last_run_push_turned_on'} <= set(rows[key])
    assert rows['e2']['last_run_push_turned_on'] is None
    assert rows['welcome']['came_back'] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_email_outcomes.py`
Expected: collection error, `ImportError: cannot import name 'email_outcomes' from 'service.growth'`.

- [ ] **Step 3: Write the module**

Create `service/growth/email_outcomes.py` with the content below. `Q_RUN_RESULTS` and `run_results` are `_Q_RUN_RESULTS` (with its comment block) and `_run_results` from `service/api/admin/growth_routes.py`, moved verbatim and renamed; they are written out here in full:

```python
"""What each email achieved (TEC-1897; frames G.1, G.2 and G.4).

"Came back counts anyone online since the send. The email may not have
caused it." A recipient came back when person.last_online_time is later
than their send. Within 7 days reads member_online_day (migration 0069),
which starts on its deploy day, so a run sent before the record began has
no 7 day figure. Push turned on is the notifications email's own measure.
"""
from __future__ import annotations

from typing import Optional

from service.campaigns.runner import SEND_AUDIT_ACTION

PUSH_CAMPAIGN = 'e6'

# What one run achieved. `reached` is the members its mail was accepted for
# (the drain writes the send log on acceptance). `clicks` counts clicks on
# the /s/ links that run's own mail carried, found in the outbox payload,
# with bots left out as service.growth.queries.post_stats leaves them out.
# A campaign mints its CTA links under its own key as the link kind and with
# the recipient as the link's subject (each module's build_for), so each
# outbox row is only searched for its own member's few links. Matching on
# kind alone searched every link the campaign ever minted in every mail of
# the run, about 53 more e2 links a week. `links` is 0 when the mail carried
# no tracked link (an e1 run before 13 Oct 2026, when its confirm link was
# bare, or a run from before the outbox), and
# then there is no click figure to give.
Q_RUN_RESULTS = """
    WITH run_links AS (
        SELECT DISTINCT l.key
          FROM email_outbox o
          JOIN campaign_link l
            ON l.kind = o.campaign
           AND l.subject_person_id = o.person_id
           AND strpos(o.payload->>'html', '/s/' || l.key) > 0
         WHERE o.campaign = %(c)s AND o.campaign_id = %(cid)s
    )
    SELECT (SELECT count(*) FROM email_send_log
             WHERE campaign = %(c)s AND campaign_id = %(cid)s) AS reached,
           (SELECT count(*) FROM run_links) AS links,
           (SELECT count(*) FROM campaign_click c JOIN run_links r ON r.key = c.link_key
             WHERE c.ua_class <> 'bot') AS clicks
"""


def run_results(tx, campaign: str, campaign_id: str | None) -> tuple[int | None, int | None]:
    if not campaign_id:
        return None, None
    r = tx.execute(Q_RUN_RESULTS, dict(c=campaign, cid=campaign_id)).fetchone()
    return int(r['reached']), (int(r['clicks']) if r['links'] else None)


_Q_RUN_OUTCOMES = """
    SELECT count(*) FILTER (WHERE p.last_online_time > l.sent_at)::int AS came_back,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM member_online_day d
                WHERE d.person_id = l.person_id
                  AND d.last_at > l.sent_at
                  AND d.first_at < l.sent_at + INTERVAL '7 days'))::int AS came_back_7d,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM push_subscription ps
                WHERE ps.person_id = l.person_id AND ps.created_at > l.sent_at))::int AS push_turned_on,
           min(l.sent_at) AS first_sent_at,
           (SELECT min(first_at) FROM member_online_day) AS recording_since
      FROM email_send_log l
      JOIN person p ON p.id = l.person_id
     WHERE l.campaign = %(c)s AND l.campaign_id = %(cid)s
"""

_Q_STARTED_BY = """
    SELECT actor_email FROM admin_audit_log
     WHERE action = %(action)s
       AND metadata->>'campaign' = %(c)s
       AND metadata->>'campaign_id' = %(cid)s
       AND COALESCE((metadata->>'dry_run')::boolean, FALSE) = FALSE
     ORDER BY created_at
     LIMIT 1
"""

_Q_RUNS = """
    SELECT campaign_id, min(sent_at) AS sent_at, count(*)::int AS reached
      FROM email_send_log
     WHERE campaign = %(c)s
     GROUP BY campaign_id
     ORDER BY min(sent_at) DESC
     LIMIT %(lim)s
"""

_Q_LAST_30 = """
    WITH s AS (
        SELECT l.person_id, min(l.sent_at) AS first_at, count(*) AS n
          FROM email_send_log l
         WHERE l.campaign = %(c)s AND l.sent_at > NOW() - INTERVAL '30 days'
         GROUP BY l.person_id
    )
    SELECT COALESCE(sum(s.n), 0)::int AS sends,
           count(*)::int AS people,
           count(*) FILTER (WHERE p.last_online_time > s.first_at)::int AS came_back
      FROM s JOIN person p ON p.id = s.person_id
"""

_Q_CAME_BACK_ALL = """
    SELECT count(*)::int AS n
      FROM (SELECT l.person_id, min(l.sent_at) AS first_at
              FROM email_send_log l WHERE l.campaign = %(c)s GROUP BY l.person_id) s
      JOIN person p ON p.id = s.person_id
     WHERE p.last_online_time > s.first_at
"""


def run_outcomes(tx, campaign: str, campaign_id: Optional[str]) -> dict:
    if not campaign_id:
        return dict(came_back=None, came_back_7d=None, push_turned_on=None)
    r = tx.execute(_Q_RUN_OUTCOMES, dict(c=campaign, cid=campaign_id)).fetchone()
    measured_7d = (r['recording_since'] is not None and r['first_sent_at'] is not None
                   and r['recording_since'] <= r['first_sent_at'])
    return dict(came_back=r['came_back'],
                came_back_7d=r['came_back_7d'] if measured_7d else None,
                push_turned_on=r['push_turned_on'] if campaign == PUSH_CAMPAIGN else None)


def started_by(actor_email: Optional[str]) -> Optional[str]:
    if actor_email is None:
        return None
    return {'cron': 'schedule', 'cli': 'command_line'}.get(actor_email, 'send_button')


def run_history(tx, campaign: str, limit: int = 12) -> list[dict]:
    out = []
    for r in tx.execute(_Q_RUNS, dict(c=campaign, lim=limit)).fetchall():
        cid = r['campaign_id']
        _, clicks = run_results(tx, campaign, cid)
        o = run_outcomes(tx, campaign, cid)
        actor = tx.execute(_Q_STARTED_BY, dict(action=SEND_AUDIT_ACTION, c=campaign, cid=cid)).fetchone()
        out.append(dict(campaign_id=cid, sent_at=r['sent_at'].isoformat(),
                        started_by=started_by(actor['actor_email'] if actor else None),
                        reached=r['reached'], clicks=clicks,
                        came_back=o['came_back'], came_back_7d=o['came_back_7d']))
    return out


def last_30_days(tx, campaign: str) -> dict:
    return dict(tx.execute(_Q_LAST_30, dict(c=campaign)).fetchone())


def came_back_all_time(tx, campaign: str) -> int:
    return tx.execute(_Q_CAME_BACK_ALL, dict(c=campaign)).fetchone()['n']
```

- [ ] **Step 4: Wire the routes**

In `service/api/admin/growth_routes.py`:
- Delete the moved code: the comment block that begins `# What one run achieved.` with the `_Q_RUN_RESULTS` constant under it, and the `_run_results` function (keep `_NEXT_RUN_ID`, which sits between them). Nothing else imports either (checked 18 Oct). Add `from service.growth import email_outcomes` to the imports.
- In `get_admin_growth_emails`, replace:

```python
            reached, clicks = _run_results(tx, key, last['cid'] if last else None)
            out.append(dict(campaign=key, recipients=len(ids),
                            eligible_now=len(ids), would_reach_now=would_reach,
                            last_run_reached=reached, last_run_clicks=clicks,
```

with:

```python
            cid = last['cid'] if last else None
            reached, clicks = email_outcomes.run_results(tx, key, cid)
            outcome = email_outcomes.run_outcomes(tx, key, cid)
            out.append(dict(campaign=key, recipients=len(ids),
                            eligible_now=len(ids), would_reach_now=would_reach,
                            last_run_reached=reached, last_run_clicks=clicks,
                            last_run_came_back=outcome['came_back'],
                            last_run_came_back_7d=outcome['came_back_7d'],
                            last_run_push_turned_on=outcome['push_turned_on'],
                            came_back=None,
```

- Replace the system-row loop:

```python
    for key in ('e4', 'e5', 'welcome', 'referral'):
        last = last_sent.get(key)
        out.append(dict(campaign=key, recipients=int(last['n']) if last else 0,
                        eligible_now=None, would_reach_now=None,
                        last_run_reached=None, last_run_clicks=None,
```

with:

```python
    with api_tx('read committed') as tx:
        came_back = {key: email_outcomes.came_back_all_time(tx, key)
                     for key in ('e4', 'e5', 'welcome', 'referral')}
    for key in ('e4', 'e5', 'welcome', 'referral'):
        last = last_sent.get(key)
        out.append(dict(campaign=key, recipients=int(last['n']) if last else 0,
                        eligible_now=None, would_reach_now=None,
                        last_run_reached=None, last_run_clicks=None,
                        last_run_came_back=None, last_run_came_back_7d=None,
                        last_run_push_turned_on=None,
                        came_back=came_back[key],
```

- Append the route after `get_admin_growth_email_status`:

```python
@aget('/admin/growth/emails/<campaign>/runs')
def get_admin_growth_email_runs(s: t.SessionInfo, campaign: str):
    """One email's run history (frame G.4): date, campaign id, how it was
    started, reached, clicks and came back, newest first, and the last 30
    days in one line. Admin-run emails only."""
    require_admin(s)
    _CAMPAIGNS.get(campaign) or abort(404)
    with api_tx('read committed') as tx:
        return dict(runs=email_outcomes.run_history(tx, campaign),
                    last_30_days=email_outcomes.last_30_days(tx, campaign))
```

Add to the docstring of `get_admin_growth_emails`, after the `recipients` paragraph:

```python
    TEC-1897 adds, per admin-run row, last_run_came_back (recipients online
    since their send), last_run_came_back_7d (online within 7 days of it;
    null before the per-day record began) and last_run_push_turned_on (e6
    only), and `came_back` on the system rows (people online since their
    first send of that email).
```

- [ ] **Step 5: Run test to verify it passes**

Run: `RUN tests/test_admin_email_outcomes.py` then `RUN tests/test_growth_emails_index.py` then `RUN tests/test_growth_routes.py`
Expected: `6 passed`; the two existing suites pass as before.

- [ ] **Step 6: Commit**

```bash
git add service/growth/email_outcomes.py service/api/admin/growth_routes.py tests/test_admin_email_outcomes.py
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): who came back after each email, push turned on and each run's history" -m "Refs: TEC-1897"
```

---

### Task 12: Profile gaps, approved photos with no face and the photo gate list

**Files:**
- Modify: `service/admin/queries/profiles.py` (append)
- Modify: `service/admin/queries/moderation.py` (`Q_PHOTOS_LIST`; add `Q_APPROVED_NO_FACE_KPIS`)
- Modify: `service/api/admin/moderation_routes.py` (`get_moderation_photos`; 2 new routes)
- Test: `tests/test_admin_profile_gaps.py` (create)

**Interfaces:**
- Consumes: `can_view_photos()` (migration 0062); `photo.uploaded_at` (Task 1); `counted_member_sql` (Task 5); `jsonrow.iso_row`.
- Produces:
  - `GET /admin/moderation/photos?state=approved_no_face`: approved photos with `face_count = 0` and no moderator confirmation; every row gains `owner_is_staff: bool` and `uploaded_at`; the body gains `approved_no_face: {photos, people, members, staff}` on every state.
  - `profiles.Q_PROFILE_GAP_KPIS`, `profiles.Q_PROFILE_GAPS` (bind `%(ex)s`); `GET /admin/moderation/profile-gaps` answering `{'kpis': {not_verified, only_declined, no_photo, no_face_photo}, 'rows': [{uuid, name, gap, tier}]}` where `gap` is `'no_photo'|'only_declined'|'only_pending'|'no_face'`.
  - `profiles.Q_PHOTO_GATE_MEMBERS`; `GET /admin/moderation/photo-gate` answering `{'enabled': bool, 'members': [{uuid, name, likes_sent_30d, likes_received_30d, matches_30d, messages_30d, profile_views_30d, last_online_at, has_waiting_photo, waiting_photo_uuid, photo_waiting_since}]}`.

Rules:
- Profile gaps (P.2) count counted members. `no_face_photo` is everyone the photo gate would hold (`NOT can_view_photos`), which includes the members with no photo and with only declined photos, as the brief's figures do ("3 members have only declined photos and 1 has none; 4 have no approved photo with a face"). The list holds members with a photo gap; members who are only unverified are counted in the strip, not listed.
- Approved, no face (P.3) lists staff photos too, marked, as the design's line does ("6 photos, 5 people: 4 members and 1 staff account"). A photo a moderator confirmed (`face_confirmed_at`) is not listed; a photo the detector never checked (`face_count` NULL) is not listed either, the gate's own rule.
- The gate list (P.1) uses the same people as the existing `Q_PHOTO_GATE_KPIS` (the member rule and activated, no staff address list), so the Needs you tile and the list agree. Activity is over the last 30 days. "Profile views" counts distinct members who opened the profile: `visited` keeps one row per pair with the latest visit. "Photo waiting" is the oldest pending or manual review photo's `uploaded_at`, NULL for photos stored before the deploy.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_profile_gaps.py`:

```python
"""Profile gaps, approved photos with no face and the photo gate list
(TEC-1897; frames P.1, P.2 and P.3)."""
from __future__ import annotations

from database import api_tx
from service.admin.queries import profiles


def _gaps(client, headers) -> dict:
    r = client.get('/admin/moderation/profile-gaps', headers=headers)
    assert r.status_code == 200
    return r.get_json()


def _gap_of(body, person):
    return next((r['gap'] for r in body['rows'] if r['uuid'] == person['uuid']), None)


def test_each_gap_is_counted_and_listed(client, admin_bearer, make_person, add_photo):
    none_, declined, pending, faceless, fine = (make_person(name=n) for n in
                                                ('GapNone', 'GapDecl', 'GapPend', 'GapFace', 'GapFine'))
    add_photo(declined['id'], status='rejected')
    add_photo(pending['id'], status='pending')
    add_photo(faceless['id'], status='approved', face_count=0)
    add_photo(fine['id'], status='approved', face_count=1)
    body = _gaps(client, admin_bearer)
    assert [_gap_of(body, p) for p in (none_, declined, pending, faceless, fine)] == [
        'no_photo', 'only_declined', 'only_pending', 'no_face', None]
    row = next(r for r in body['rows'] if r['uuid'] == faceless['uuid'])
    assert row['tier'] == 'none' and row['name'] == 'GapFace'


def test_the_strip_moves_with_one_member(client, admin_bearer, make_person):
    before = _gaps(client, admin_bearer)['kpis']
    make_person(name='GapStrip')
    after = _gaps(client, admin_bearer)['kpis']
    assert {k: after[k] - before[k] for k in before} == dict(
        not_verified=1, only_declined=0, no_photo=1, no_face_photo=1)


def test_staff_are_not_profile_gaps(client, admin_bearer, make_person):
    before = _gaps(client, admin_bearer)['kpis']
    staff = make_person(name='GapStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    assert _gaps(client, admin_bearer)['kpis'] == before


def test_approved_with_no_face_lists_unconfirmed_photos_and_marks_staff(client, admin_bearer, make_person, add_photo):
    m, staff = make_person(name='NoFaceMem'), make_person(name='NoFaceStaff')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    before = client.get('/admin/moderation/photos?state=approved_no_face',
                        headers=admin_bearer).get_json()['approved_no_face']
    listed = add_photo(m['id'], status='approved', face_count=0)
    add_photo(m['id'], position=2, status='approved', face_count=0, face_confirmed=True)
    add_photo(staff['id'], status='approved', face_count=0)
    body = client.get('/admin/moderation/photos?state=approved_no_face', headers=admin_bearer).get_json()
    mine = {r['photo_uuid']: r for r in body['rows'] if r['owner_uuid'] in (m['uuid'], staff['uuid'])}
    assert listed in mine and len(mine) == 2
    assert {r['owner_is_staff'] for r in mine.values()} == {True, False}
    after = body['approved_no_face']
    assert {k: after[k] - before[k] for k in before} == dict(photos=2, people=2, members=1, staff=1)


def test_the_gate_list_carries_activity_and_the_waiting_photo(client, admin_bearer, make_person, add_photo):
    held, other = make_person(name='GateHeld'), make_person(name='GateOther')
    photo = add_photo(held['id'], status='pending')
    with api_tx() as tx:
        tx.execute("INSERT INTO liked (liker_id, liked_id) VALUES (%(a)s, %(b)s)",
                   dict(a=other['id'], b=held['id']))
        tx.execute("""INSERT INTO visited (subject_person_id, object_person_id)
                      VALUES (%(a)s, %(b)s)""", dict(a=other['id'], b=held['id']))
    body = client.get('/admin/moderation/photo-gate', headers=admin_bearer).get_json()
    row = next(r for r in body['members'] if r['uuid'] == held['uuid'])
    assert row['likes_received_30d'] == 1 and row['likes_sent_30d'] == 0
    assert row['profile_views_30d'] == 1 and row['messages_30d'] == 0
    assert row['has_waiting_photo'] is True and row['waiting_photo_uuid'] == photo
    assert row['photo_waiting_since'].endswith('+00:00')
    assert isinstance(body['enabled'], bool)


def test_the_gate_list_reads_no_message_content():
    low = profiles.Q_PHOTO_GATE_MEMBERS.lower()
    for forbidden in ('.message', 'search_body', 'translations', 'audio_uuid'):
        assert forbidden not in low
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_profile_gaps.py`
Expected: 404s, `KeyError: 'approved_no_face'` and `AttributeError` on `Q_PHOTO_GATE_MEMBERS`.

- [ ] **Step 3: Write the queries**

Append to `service/admin/queries/profiles.py`:

```python
# One row per counted member with their photo tallies. can_view_photos() is
# the photo gate's own rule: an approved photo showing a face.
_MEMBER_PHOTOS = f"""
    SELECT p.id, p.uuid::text AS uuid, p.name, p.ahavah_verification_tier::text AS tier,
           count(ph.uuid) AS photos,
           count(ph.uuid) FILTER (WHERE ph.moderation_status::text = 'approved') AS approved,
           count(ph.uuid) FILTER (WHERE ph.moderation_status::text = 'rejected') AS rejected,
           can_view_photos(p.id) AS has_face_photo
      FROM person p
      LEFT JOIN photo ph ON ph.person_id = p.id
     WHERE {counted_member_sql('p')}
     GROUP BY p.id
"""

_GAP = """
    CASE WHEN photos = 0 THEN 'no_photo'
         WHEN rejected = photos THEN 'only_declined'
         WHEN approved = 0 THEN 'only_pending'
         WHEN NOT has_face_photo THEN 'no_face'
    END
"""

Q_PROFILE_GAP_KPIS = f"""
    WITH m AS ({_MEMBER_PHOTOS})
    SELECT count(*) FILTER (WHERE tier = 'none')::int                     AS not_verified,
           count(*) FILTER (WHERE photos > 0 AND rejected = photos)::int  AS only_declined,
           count(*) FILTER (WHERE photos = 0)::int                        AS no_photo,
           count(*) FILTER (WHERE NOT has_face_photo)::int                AS no_face_photo
      FROM m
"""

Q_PROFILE_GAPS = f"""
    WITH m AS ({_MEMBER_PHOTOS})
    SELECT uuid, name, tier, gap
      FROM (SELECT m.*, {_GAP} AS gap FROM m) g
     WHERE gap IS NOT NULL
     ORDER BY array_position(ARRAY['no_photo', 'only_declined', 'only_pending', 'no_face'], gap), name
     LIMIT 500
"""

# The people Q_PHOTO_GATE_KPIS counts (members, activated), so the Needs you
# tile and this list agree. Activity over the last 30 days. Messages are
# counted from mam_message's id, direction and person only.
Q_PHOTO_GATE_MEMBERS = f"""
    SELECT p.uuid::text AS uuid, p.name, p.last_online_time AS last_online_at,
           (SELECT count(*) FROM liked l
             WHERE l.liker_id = p.id AND l.created_at > NOW() - INTERVAL '30 days')::int AS likes_sent_30d,
           (SELECT count(*) FROM liked l
             WHERE l.liked_id = p.id AND l.created_at > NOW() - INTERVAL '30 days')::int AS likes_received_30d,
           (SELECT count(*) FROM ahavah_match am
             WHERE p.id IN (am.user_a_id, am.user_b_id)
               AND am.created_at > NOW() - INTERVAL '30 days')::int AS matches_30d,
           (SELECT count(*) FROM mam_message mm
             WHERE mm.person_id = p.id AND mm.direction = 'O'
               AND to_timestamp(mm.id / 1000000 / 256) > NOW() - INTERVAL '30 days')::int AS messages_30d,
           (SELECT count(*) FROM visited v
             WHERE v.object_person_id = p.id AND v.subject_person_id <> p.id
               AND v.updated_at > NOW() - INTERVAL '30 days')::int AS profile_views_30d,
           w.uuid IS NOT NULL AS has_waiting_photo,
           w.uuid AS waiting_photo_uuid,
           w.uploaded_at AS photo_waiting_since
      FROM person p
      LEFT JOIN LATERAL (
          SELECT ph.uuid, ph.uploaded_at FROM photo ph
           WHERE ph.person_id = p.id AND ph.moderation_status::text IN ('pending', 'manual_review')
           ORDER BY ph.uploaded_at NULLS FIRST, ph.position
           LIMIT 1) w ON TRUE
     WHERE {member_sql('p')} AND p.activated AND NOT can_view_photos(p.id)
     ORDER BY p.last_online_time DESC
     LIMIT 200
"""
```

In `service/admin/queries/moderation.py`, replace `Q_PHOTOS_LIST = """` and its body with:

```python
Q_PHOTOS_LIST = f"""
    SELECT
        ph.uuid AS photo_uuid,
        ph.position,
        ph.moderation_status::text AS moderation_status,
        ph.nsfw_score,
        ph.face_count,
        ph.face_checked_at,
        ph.moderated_at,
        ph.uploaded_at,
        p.email AS owner_email,
        p.uuid::text AS owner_uuid,
        NOT ({_MEMBER_P}) AS owner_is_staff
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
     -- 'queue' is everything waiting on a person: pending AND manual_review.
     -- The Photos tab used to ask for 'pending' alone, so a photo the cron
     -- had sent for a human decision was never shown to anyone (TEC-946).
     -- 'approved_no_face' (TEC-1897, finding 9): approved photos the
     -- detector saw no face in and no moderator has confirmed.
     WHERE (%(state)s = ''
            OR ph.moderation_status::text = %(state)s
            OR (%(state)s = 'queue'
                AND ph.moderation_status::text IN ('pending', 'manual_review'))
            OR (%(state)s = 'approved_no_face'
                AND ph.moderation_status::text = 'approved'
                AND ph.face_count = 0
                AND ph.face_confirmed_at IS NULL))
     ORDER BY ph.moderated_at DESC NULLS FIRST
     LIMIT 100
"""
```

`_MEMBER_P` is defined above `Q_PHOTOS_LIST` already. After `Q_PHOTOS_KPIS` add:

```python
# Frame P.3's line, "6 photos, 5 people: 4 members and 1 staff account".
Q_APPROVED_NO_FACE_KPIS = f"""
    SELECT count(*)::int AS photos,
           count(DISTINCT ph.person_id)::int AS people,
           count(DISTINCT ph.person_id) FILTER (WHERE {_MEMBER_P})::int AS members,
           count(DISTINCT ph.person_id) FILTER (WHERE NOT ({_MEMBER_P}))::int AS staff
      FROM photo ph
      JOIN person p ON p.id = ph.person_id
     WHERE ph.moderation_status::text = 'approved'
       AND ph.face_count = 0
       AND ph.face_confirmed_at IS NULL
"""
```

Export it through `service/admin/queries/__init__.py` the way `Q_PHOTO_GATE_KPIS` is exported (add it to the same import list there).

- [ ] **Step 4: Wire the routes**

In `service/api/admin/moderation_routes.py`, add `Q_APPROVED_NO_FACE_KPIS` to the `from service.admin.queries import (...)` list, and in `get_moderation_photos` replace:

```python
        rows = [dict(r) for r in tx.execute(Q_PHOTOS_LIST, dict(state=state)).fetchall()]
        kpis = tx.execute(Q_PHOTOS_KPIS).fetchone() or {}
        gate = dict(tx.execute(Q_PHOTO_GATE_KPIS).fetchone() or {})
```

with:

```python
        rows = [iso_row(r) for r in tx.execute(Q_PHOTOS_LIST, dict(state=state)).fetchall()]
        kpis = tx.execute(Q_PHOTOS_KPIS).fetchone() or {}
        gate = dict(tx.execute(Q_PHOTO_GATE_KPIS).fetchone() or {})
        no_face = dict(tx.execute(Q_APPROVED_NO_FACE_KPIS).fetchone())
```

and its return with `return {'rows': rows, 'kpis': dict(kpis), 'photo_gate': gate, 'approved_no_face': no_face}`. Add `from service.admin.jsonrow import iso_row` to the imports.

Append:

```python
@aget('/admin/moderation/profile-gaps')
def get_moderation_profile_gaps(s: t.SessionInfo):
    """Members with no photo, only declined or pending photos, or no approved
    photo showing a face, and the not verified count (frame P.2)."""
    require_admin(s)
    from service.admin.queries.profiles import Q_PROFILE_GAP_KPIS, Q_PROFILE_GAPS
    from service.growth.queries import _excluded
    params = dict(ex=_excluded())
    with api_tx('read committed') as tx:
        kpis = dict(tx.execute(Q_PROFILE_GAP_KPIS, params).fetchone())
        rows = [dict(r) for r in tx.execute(Q_PROFILE_GAPS, params).fetchall()]
    return dict(kpis=kpis, rows=rows)


@aget('/admin/moderation/photo-gate')
def get_moderation_photo_gate(s: t.SessionInfo):
    """The members the photo gate holds or would hold, with their last 30
    days (frame P.1). Counts only."""
    require_admin(s)
    from service.admin.queries.profiles import Q_PHOTO_GATE_MEMBERS
    with api_tx('read committed') as tx:
        members = [iso_row(r) for r in tx.execute(Q_PHOTO_GATE_MEMBERS).fetchall()]
    return dict(enabled=photo_gate_enabled(), members=members)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `RUN tests/test_admin_profile_gaps.py` then `RUN tests/test_views_approved_photos.py`
Expected: `6 passed`; the existing suite passes as before.

- [ ] **Step 6: Commit**

```bash
git add service/admin/queries/profiles.py service/admin/queries/moderation.py service/admin/queries/__init__.py service/api/admin/moderation_routes.py tests/test_admin_profile_gaps.py
git -c user.email=admin@techbaseltd.com commit -m "feat(moderation): profile gaps, approved photos with no face and the photo gate list" -m "Refs: TEC-1897"
```

---

### Task 13: The 2 owner alert emails and their proofs

**Files:**
- Create: `emails/admin_alerts.py`
- Create: `scripts/send_admin_alert_proofs.py`
- Test: `tests/test_admin_alert_emails.py` (create)

**Interfaces:**
- Consumes: `emails.base.render`, `button`, `chip`, `SANS`, `INK`, `INK_SOFT`; `scripts.send_proofs.PROOF_TO`, `_inert`, `_smtp`.
- Produces: `admin_alerts.OWNER_TO`; `admin_alerts.ADMIN_URL`; `admin_alerts.KIND_LABELS`; `admin_alerts.post_line(post: dict) -> str`; `admin_alerts.stale_posts_email(posts: list[dict], now: datetime) -> tuple[str, str]` (subject, html), each post `{'kind': str, 'week': int|None, 'members': int|None, 'in_review_since': datetime}`; `admin_alerts.report_email(count: int, now: datetime) -> tuple[str, str]`; `preview_stale(to)` and `preview_report(to)` returning `(subject, html)` from sample data; `scripts/send_admin_alert_proofs.py` with `plan()` and `main(argv)`.

Frame G.8 is the stale-post email. The report email has no frame; its lines are listed in the conflicts section and go through `/copy-pass` and the owner before its switch is turned on. Neither email names a member or carries a report's reason. The heading is body text in bold, not display type: the shell's display titles are pre-rendered images (`title_image`), and none exists for these headings.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_alert_emails.py`:

```python
"""The owner alerts (TEC-1897; frame G.8): to the owner only, no member
named, no reason quoted. Proofs go to his address, never the outbox."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from database import api_tx
from emails import admin_alerts
from scripts import send_admin_alert_proofs as ap

NOW = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)  # 07:00 in Barbados
POSTS = [
    dict(kind='roundup', week=41, members=4, in_review_since=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)),
    dict(kind='roundup', week=42, members=2, in_review_since=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)),
]


def test_the_stale_email_reads_as_the_design_draws_it():
    subject, html = admin_alerts.stale_posts_email(POSTS, NOW)
    assert subject == '2 posts are waiting for approval'
    for line in ('Admin alert · 14 Oct, 07:00 Barbados',
                 'Roundup, week 41, 4 members. In review since 5 Oct.',
                 'Roundup, week 42, 2 members. In review since 12 Oct.',
                 'Open the queue',
                 'Sent once a day while a post has waited more than 24 hours.'):
        assert line in html
    assert 'https://admin.ahavah.app/?tab=growth' in html
    assert '\u2014' not in html  # no em dash


def test_one_post_and_other_kinds():
    one = [dict(kind='brand', week=None, members=None,
                in_review_since=datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc))]
    subject, html = admin_alerts.stale_posts_email(one, NOW)
    assert subject == '1 post is waiting for approval'
    assert 'Brand post. In review since 12 Oct.' in html
    assert admin_alerts.post_line(dict(kind='roundup', week=40, members=1,
                                       in_review_since=NOW)) == 'Roundup, week 40, 1 member. In review since 14 Oct.'


def test_the_report_email_names_nobody():
    subject, html = admin_alerts.report_email(1, NOW)
    assert subject == 'A member has reported someone'
    assert 'https://admin.ahavah.app/?tab=moderation&amp;sub=reports' in html or \
           'https://admin.ahavah.app/?tab=moderation&sub=reports' in html
    assert admin_alerts.report_email(3, NOW)[0] == '3 new reports are waiting'


def test_the_alerts_go_to_the_proof_address():
    from scripts.send_proofs import PROOF_TO
    assert admin_alerts.OWNER_TO == PROOF_TO == 'harrigan.tennyson@gmail.com'


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def smtp(monkeypatch):
    s = _Smtp()
    monkeypatch.setattr(ap, '_smtp', lambda: s)
    return s


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                for t in ('email_outbox', 'email_send_log', 'admin_alert_log')}


def test_the_proof_plan_covers_both_alerts():
    assert {e['name'] for e in ap.plan()} == {'stale_post_alert', 'report_alert'}


def test_a_dry_run_sends_nothing(smtp, capsys):
    before = _counts()
    ap.main([])
    assert smtp.sent == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    before = _counts()
    ap.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == 2 and all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert _counts() == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_alert_emails.py`
Expected: collection error, `ImportError: cannot import name 'admin_alerts' from 'emails'`.

- [ ] **Step 3: Write the emails and the proof script**

Create `emails/admin_alerts.py`:

```python
"""Alerts to the owner alone (TEC-1897; frame G.8 for the stale posts).

Never to a member. Each is sent straight through the mailer to OWNER_TO by
service/cron/adminalerts, behind its switch (stale_post_alert,
report_alert), and proofed first by scripts/send_admin_alert_proofs.py.
No member is named and no report's reason is quoted. The heading is bold
body text: the shell's display titles are pre-rendered images and none
exists for these lines.
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from zoneinfo import ZoneInfo

from emails.base import INK, INK_SOFT, SANS, button, chip, render

# The address every proof already goes to (scripts/send_proofs.py PROOF_TO).
OWNER_TO = 'harrigan.tennyson@gmail.com'
ADMIN_URL = 'https://admin.ahavah.app'
# None: the mailer's default sender, as the like and match emails use.
FROM_ADDR = None
BARBADOS = ZoneInfo('America/Barbados')

# The admin's own labels for a post kind (ahavah-admin src/lib/growth-api.ts
# KIND_BADGES), so the email and the queue name a post the same way.
KIND_LABELS = {
    'welcome': 'Welcome',
    'roundup': 'Roundup',
    'member_of_week': 'Member of the week',
    'highlight': 'Highlight',
    'brand': 'Brand post',
}


def _day(at: datetime) -> str:
    b = at.astimezone(BARBADOS)
    return f'{b.day} {b:%b}'


def _stamp(now: datetime) -> str:
    b = now.astimezone(BARBADOS)
    return f'Admin alert · {b.day} {b:%b}, {b:%H:%M} Barbados'


def post_line(post: dict) -> str:
    since = _day(post['in_review_since'])
    if post['kind'] == 'roundup' and post.get('week') is not None:
        n = post.get('members')
        who = '' if n is None else f", {n} {'member' if n == 1 else 'members'}"
        return f"Roundup, week {post['week']}{who}. In review since {since}."
    return f"{KIND_LABELS.get(post['kind'], 'Post')}. In review since {since}."


def _email(now: datetime, heading: str, lines: list[str], label: str, url: str, footer: str) -> str:
    items = ''.join(
        f'<li style="margin:0 0 8px;">{_html.escape(line)}</li>' for line in lines)
    body = f"""
{chip(_html.escape(_stamp(now)))}
<p class="e-text" style="margin:18px 0 12px;font-family:{SANS};font-size:20px;line-height:1.35;font-weight:800;color:{INK};">{_html.escape(heading)}</p>
<ul class="e-text" style="margin:0 0 20px;padding-left:18px;font-family:{SANS};font-size:15px;line-height:1.5;color:{INK_SOFT};">{items}</ul>
{button(label, url)}
"""
    return render(title=heading, preheader=heading, body_html=body, footer_html=_html.escape(footer))


def stale_posts_email(posts: list[dict], now: datetime) -> tuple[str, str]:
    n = len(posts)
    heading = '1 post is waiting for approval' if n == 1 else f'{n} posts are waiting for approval'
    return heading, _email(now, heading, [post_line(p) for p in posts], 'Open the queue',
                           f'{ADMIN_URL}/?tab=growth',
                           'Sent once a day while a post has waited more than 24 hours.')


def report_email(count: int, now: datetime) -> tuple[str, str]:
    heading = 'A member has reported someone' if count == 1 else f'{count} new reports are waiting'
    return heading, _email(now, heading, ['Open Reports in Moderation to see who and why.'],
                           'Open reports', f'{ADMIN_URL}/?tab=moderation&sub=reports',
                           'Sent when a report arrives, while Email me when a report arrives is on.')


def preview_stale(to: str) -> tuple[str, str]:
    from datetime import timezone
    now = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)
    posts = [
        dict(kind='roundup', week=41, members=4, in_review_since=datetime(2026, 10, 5, 15, tzinfo=timezone.utc)),
        dict(kind='roundup', week=42, members=2, in_review_since=datetime(2026, 10, 12, 15, tzinfo=timezone.utc)),
    ]
    return stale_posts_email(posts, now)


def preview_report(to: str) -> tuple[str, str]:
    from datetime import timezone
    return report_email(1, datetime(2026, 10, 14, 15, 20, tzinfo=timezone.utc))
```

Create `scripts/send_admin_alert_proofs.py`:

```python
"""Send the owner one proof of each owner alert (TEC-1897), before either
switch is turned on.

    python -m scripts.send_admin_alert_proofs            # DRY RUN
    python -m scripts.send_admin_alert_proofs --send     # send the proofs

Run inside the api container. The same rules as scripts/send_proofs.py,
whose address and helpers this reuses: to PROOF_TO only, straight through
the mailer, never the outbox; sample data only; no switch read or changed.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from scripts.send_proofs import PROOF_TO, _inert, _smtp

__all__ = ['PROOF_TO', 'plan', 'main']


def plan() -> list[dict]:
    from emails import admin_alerts
    builders = [
        ('stale_post_alert', 'Posts waiting for approval (G.8)', admin_alerts.preview_stale),
        ('report_alert', 'A report has arrived (no frame; see the plan)', admin_alerts.preview_report),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert(name, html), from_addr=admin_alerts.FROM_ADDR))
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}")
    for e in emails:
        print(f"  email  {e['name']:20s} {e['subject']}  ({e['label']})")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO, from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")


if __name__ == '__main__':
    main(sys.argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_alert_emails.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add emails/admin_alerts.py scripts/send_admin_alert_proofs.py tests/test_admin_alert_emails.py
git -c user.email=admin@techbaseltd.com commit -m "feat(alerts): the stale post and report emails to the owner, with proofs" -m "Refs: TEC-1897"
```

---

### Task 14: The adminalerts cron: the daily stale-post alert, report alerts and retention

**Files:**
- Create: `service/cron/adminalerts/__init__.py`
- Modify: `service/cron/__init__.py` (import and add to `asyncio.gather` in `main`)
- Test: `tests/test_admin_alerts_cron.py` (create)

**Interfaces:**
- Consumes: `admin_alerts.stale_posts_email`, `report_email`, `OWNER_TO`, `FROM_ADDR` (Task 13); `switches.enabled` (Task 2); `admin_alert_log`, `admin_alert_pref`, `report_resolution`, `api_error_tally`, `member_online_day` (Task 1); `publishing_queue`; `record_system_audit`.
- Produces: `adminalerts.STALE_HOURS = 24`, `adminalerts.SEND_HOUR = 7`; `adminalerts.stale_posts(tx) -> list[dict]`; `adminalerts.queue_stale(tx, now) -> list[dict]|None` (the posts to send, after writing the log row, or None); `adminalerts.queue_reports(tx, now) -> int` (reports to announce, after writing their log rows); `adminalerts.prune(tx) -> None`; `adminalerts.tick(now=None) -> dict`; `adminalerts.admin_alerts_forever()`; `adminalerts._smtp()` (patched in tests).

Rules:
- Hourly. The stale alert is due once per Barbados day, at or after 07:00, while a post (every platform row of one request key) has been in review for more than 24 hours. Its log key is the Barbados date.
- A report is announced once (its log key is its report key), only when it arrived after the owner turned the preference on (so turning it on never sends the backlog), and only while it is unresolved. One email per tick, with the count.
- The log row is written in the transaction that decides to send, before the send: two ticks or two containers send once; a crash between the two loses that one alert, the right way to fail for an alert.
- Each send leaves a system audit row (`admin_alert.sent`).
- Retention: `api_error_tally` older than 30 days and `member_online_day` older than 120 days are deleted each tick.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_alerts_cron.py`:

```python
"""The adminalerts cron (TEC-1897): the daily stale-post alert and report
alerts to the owner, each behind its switch, each sent once."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from service.cron import adminalerts

# 14 Oct 2026: 11:30 UTC is 07:30 in Barbados; 10:30 UTC is 06:30.
AFTER_SEVEN = datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc)
BEFORE_SEVEN = datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc)


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'id'


@pytest.fixture
def smtp(monkeypatch):
    s = _Smtp()
    monkeypatch.setattr(adminalerts, '_smtp', lambda: s)
    return s


@pytest.fixture
def stale_roundup():
    key = f'roundup:2026-W41-{uuid4().hex[:6]}'
    with api_tx() as tx:
        for platform in ('facebook', 'instagram'):
            tx.execute(
                """INSERT INTO publishing_queue (request_key, kind, platform, status, created_at, payload)
                   VALUES (%(k)s, 'roundup', %(p)s, 'review', NOW() - INTERVAL '3 days',
                           '{"count": 4}'::jsonb)""", dict(k=key, p=platform))
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")
    yield key
    with api_tx() as tx:
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(k)s", dict(k=key))
        tx.execute("DELETE FROM admin_alert_log WHERE alert = 'stale_posts'")


def test_nothing_sends_while_the_switch_is_off(smtp, stale_roundup, monkeypatch):
    monkeypatch.delenv('AHAVAH_STALE_POST_ALERT_ENABLED', raising=False)
    adminalerts.tick(AFTER_SEVEN)
    assert smtp.sent == []


def test_the_stale_alert_goes_once_a_day_after_seven(smtp, stale_roundup, monkeypatch):
    monkeypatch.setenv('AHAVAH_STALE_POST_ALERT_ENABLED', '1')
    adminalerts.tick(BEFORE_SEVEN)
    assert smtp.sent == []
    adminalerts.tick(AFTER_SEVEN)
    adminalerts.tick(AFTER_SEVEN)
    assert len(smtp.sent) == 1
    mail = smtp.sent[0]
    assert mail['to_addr'] == 'harrigan.tennyson@gmail.com'
    assert 'Roundup, week 41, 4 members. In review since' in mail['body']
    with api_tx('read committed') as tx:
        audit = tx.execute("""SELECT metadata FROM admin_audit_log WHERE action = 'admin_alert.sent'
                               ORDER BY created_at DESC LIMIT 1""").fetchone()['metadata']
    assert audit['alert'] == 'stale_posts'


def test_a_post_under_24_hours_is_not_stale(smtp, monkeypatch):
    monkeypatch.setenv('AHAVAH_STALE_POST_ALERT_ENABLED', '1')
    key = f'roundup:2026-W42-{uuid4().hex[:6]}'
    with api_tx() as tx:
        tx.execute("""INSERT INTO publishing_queue (request_key, kind, platform, status)
                      VALUES (%(k)s, 'roundup', 'facebook', 'review')""", dict(k=key))
        posts = adminalerts.stale_posts(tx)
        tx.execute("DELETE FROM publishing_queue WHERE request_key = %(k)s", dict(k=key))
    assert all(p['request_key'] != key for p in posts)


@pytest.fixture
def report_pair(make_person):
    a, b = make_person(name='AlertRep'), make_person(name='AlertRepd')
    with api_tx() as tx:
        tx.execute("""INSERT INTO admin_alert_pref (alert, enabled, updated_at)
                      VALUES ('report', TRUE, NOW() - INTERVAL '1 minute')
                      ON CONFLICT (alert) DO UPDATE SET enabled = TRUE,
                                                       updated_at = NOW() - INTERVAL '1 minute'""")
    yield a, b
    with api_tx() as tx:
        tx.execute("UPDATE admin_alert_pref SET enabled = FALSE WHERE alert = 'report'")


def _report(a, b, minutes_ago: int = 0) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO skipped (subject_person_id, object_person_id, reported, report_reason, created_at)
                      VALUES (%(a)s, %(b)s, TRUE, 'secret reason',
                              (NOW() AT TIME ZONE 'UTC') - make_interval(mins => %(m)s))""",
                   dict(a=a['id'], b=b['id'], m=minutes_ago))


def test_a_new_report_is_announced_once_and_names_nobody(smtp, report_pair, monkeypatch):
    monkeypatch.setenv('AHAVAH_REPORT_ALERT_ENABLED', '1')
    a, b = report_pair
    _report(a, b)
    adminalerts.tick(AFTER_SEVEN)
    adminalerts.tick(AFTER_SEVEN)
    mails = [m for m in smtp.sent if 'report' in m['subject'].lower()]
    assert len(mails) == 1
    assert 'secret reason' not in mails[0]['body'] and 'AlertRep' not in mails[0]['body']


def test_reports_from_before_the_preference_are_not_announced(smtp, report_pair, monkeypatch):
    monkeypatch.setenv('AHAVAH_REPORT_ALERT_ENABLED', '1')
    a, b = report_pair
    _report(a, b, minutes_ago=30)
    with api_tx() as tx:
        assert adminalerts.queue_reports(tx, AFTER_SEVEN) == 0


def test_no_report_mail_without_the_preference(smtp, report_pair, monkeypatch):
    monkeypatch.setenv('AHAVAH_REPORT_ALERT_ENABLED', '1')
    with api_tx() as tx:
        tx.execute("UPDATE admin_alert_pref SET enabled = FALSE WHERE alert = 'report'")
    a, b = report_pair
    _report(a, b)
    with api_tx() as tx:
        assert adminalerts.queue_reports(tx, AFTER_SEVEN) == 0


def test_old_rows_are_pruned(make_person):
    p = make_person(name='PruneMe')
    with api_tx() as tx:
        tx.execute("""INSERT INTO member_online_day (person_id, day, first_at, last_at)
                      VALUES (%(i)s, CURRENT_DATE - 200, NOW() - INTERVAL '200 days', NOW() - INTERVAL '200 days')""",
                   dict(i=p['id']))
        tx.execute("""INSERT INTO api_error_tally (route, hour, n, last_at)
                      VALUES ('/prune-me', date_trunc('hour', NOW() - INTERVAL '40 days'), 1, NOW() - INTERVAL '40 days')
                      ON CONFLICT DO NOTHING""")
        adminalerts.prune(tx)
        left = tx.execute("""SELECT (SELECT count(*) FROM member_online_day WHERE person_id = %(i)s) AS days,
                                    (SELECT count(*) FROM api_error_tally WHERE route = '/prune-me') AS errs""",
                          dict(i=p['id'])).fetchone()
    assert dict(left) == dict(days=0, errs=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `RUN tests/test_admin_alerts_cron.py`
Expected: collection error, `ImportError: cannot import name 'adminalerts' from 'service.cron'`.

- [ ] **Step 3: Write the cron module**

Create `service/cron/adminalerts/__init__.py`:

```python
"""adminalerts - alerts to the owner, and two retention sweeps (TEC-1897).

Hourly. Each alert goes to the owner alone (emails/admin_alerts.py), behind
its switch, which is off until the owner has seen its proof:

  * stale_post_alert: once per Barbados day, at or after 07:00, while a post
    has been in review for more than 24 hours (frame G.8).
  * report_alert: once per report, for reports that arrived after the owner
    turned "Email me when a report arrives" on and are still unresolved.

THE LOG ROW IS THE GUARD. It is written in the transaction that decides to
send, before the send, so two ticks or two containers send once; a crash
between the commit and the send loses that one alert.

It also deletes api_error_tally rows older than 30 days and
member_online_day rows older than 120 days.
"""
from __future__ import annotations

import asyncio
import random
import re
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import api_tx
from emails import admin_alerts
from service.admin import record_system_audit
from service.campaigns.switches import enabled
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace

ADMIN_ALERTS_POLL_SECONDS = env_int('DUO_CRON_ADMIN_ALERTS_POLL_SECONDS', 60 * 60)
STALE_HOURS = 24
SEND_HOUR = 7
BARBADOS = ZoneInfo('America/Barbados')

print(f'Hello from cron module: {__name__}')

_Q_STALE = """
    SELECT request_key, min(kind) AS kind, min(created_at) AS in_review_since,
           max((payload->>'count')::int) AS members
      FROM publishing_queue
     GROUP BY request_key
    HAVING bool_and(status = 'review')
       AND min(created_at) < NOW() - make_interval(hours => %(h)s)
     ORDER BY min(created_at)
"""

_Q_LOG = """
    INSERT INTO admin_alert_log (alert, alert_key) VALUES (%(a)s, %(k)s)
    ON CONFLICT DO NOTHING RETURNING alert
"""

_Q_NEW_REPORTS = """
    SELECT s.subject_person_id || '-' || s.object_person_id || '-' ||
           to_char(s.created_at, 'YYYYMMDDHH24MISSUS') AS report_key
      FROM skipped s
      JOIN admin_alert_pref ap ON ap.alert = 'report' AND ap.enabled
     WHERE s.reported
       AND s.created_at > (ap.updated_at AT TIME ZONE 'UTC')
       AND NOT EXISTS (SELECT 1 FROM report_resolution rr
                        WHERE rr.reporter_id = s.subject_person_id
                          AND rr.reported_id = s.object_person_id
                          AND rr.reported_at = s.created_at)
"""

_WEEK = re.compile(r'W(\d{1,2})')


def _smtp():
    from smtp import make_aws_smtp
    return make_aws_smtp()


def stale_posts(tx) -> list[dict]:
    out = []
    for r in tx.execute(_Q_STALE, dict(h=STALE_HOURS)).fetchall():
        m = _WEEK.search(r['request_key']) if r['kind'] == 'roundup' else None
        out.append(dict(request_key=r['request_key'], kind=r['kind'],
                        week=int(m.group(1)) if m else None, members=r['members'],
                        in_review_since=r['in_review_since']))
    return out


def queue_stale(tx, now: datetime):
    if not enabled('stale_post_alert'):
        return None
    local = now.astimezone(BARBADOS)
    if local.hour < SEND_HOUR:
        return None
    posts = stale_posts(tx)
    if not posts:
        return None
    if tx.execute(_Q_LOG, dict(a='stale_posts', k=local.date().isoformat())).fetchone() is None:
        return None
    record_system_audit(tx, 'cron', 'admin_alert.sent', dict(alert='stale_posts', posts=len(posts)))
    return posts


def queue_reports(tx, now: datetime) -> int:
    if not enabled('report_alert'):
        return 0
    n = 0
    for r in tx.execute(_Q_NEW_REPORTS).fetchall():
        if tx.execute(_Q_LOG, dict(a='report', k=r['report_key'])).fetchone() is not None:
            n += 1
    if n:
        record_system_audit(tx, 'cron', 'admin_alert.sent', dict(alert='report', reports=n))
    return n


def prune(tx) -> None:
    tx.execute("DELETE FROM api_error_tally WHERE hour < NOW() - INTERVAL '30 days'")
    tx.execute("DELETE FROM member_online_day WHERE day < CURRENT_DATE - 120")


def _send(subject: str, html: str) -> None:
    _smtp().send(subject=subject, body=html, to_addr=admin_alerts.OWNER_TO,
                 from_addr=admin_alerts.FROM_ADDR)


def tick(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    for name, job in (('stale_posts', queue_stale), ('report', queue_reports)):
        try:
            with api_tx() as tx:
                result = job(tx, now)
        except Exception:
            print(traceback.format_exc())
            out[name] = 'error'
            continue
        out[name] = result
        try:
            if name == 'stale_posts' and result:
                _send(*admin_alerts.stale_posts_email(result, now))
            elif name == 'report' and result:
                _send(*admin_alerts.report_email(result, now))
        except Exception:
            print(f'admin_alerts: {name} not sent ({traceback.format_exc()})')
    try:
        with api_tx() as tx:
            prune(tx)
    except Exception:
        print(traceback.format_exc())
    return out


async def admin_alerts_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(tick))
        await asyncio.sleep(ADMIN_ALERTS_POLL_SECONDS)
```

`skipped.created_at` is a naive UTC `TIMESTAMP`; `ap.updated_at AT TIME ZONE 'UTC'` turns the preference's `timestamptz` into the same naive UTC form before they are compared.

In `service/cron/__init__.py`, after `from service.cron.returnmail import return_mail_forever` add `from service.cron.adminalerts import admin_alerts_forever`, and in `main()`'s `asyncio.gather(...)`, after `return_mail_forever(),` (or as the last entry) add:

```python
        # Owner alerts (TEC-1897): stale posts daily, reports as they come,
        # each behind its switch; and the error tally and online days kept
        # to 30 and 120 days. Hourly.
        admin_alerts_forever(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `RUN tests/test_admin_alerts_cron.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/cron/adminalerts/__init__.py service/cron/__init__.py tests/test_admin_alerts_cron.py
git -c user.email=admin@techbaseltd.com commit -m "feat(alerts): an hourly cron for the owner's stale post and report alerts, with retention" -m "Refs: TEC-1897"
```

---

## Admin (ahavah-admin)

Every admin task builds against the API shapes above. Until the API deploy (Task 26) the screens read a stub: `tests/_evidence/design-wave-2-shots.mjs` (Task 25) serves every new route on 127.0.0.1:5000, which `next.config.ts` rewrites `/api/*` to in development.

### Task 15: Pure labels and shapes for every new view

**Files:**
- Create: `src/lib/community.ts`
- Test: `tests/community.test.mjs` (create)

**Interfaces:**
- Produces (all exported from `src/lib/community.ts`, which has no imports, so the vm harness can load it):
  - Wire types: `WaitingSummary`, `WaitingMember`, `WaitingResponse`, `UnfinishedRow`, `UnfinishedResponse`, `FunnelWeek`, `FunnelResponse`, `PushResponse`, `TierRow`, `TiersResponse`, `EmailRun`, `EmailRunsResponse`, `ProfileGapRow`, `ProfileGapsResponse`, `GateMember`, `PhotoGateResponse`, `ApiErrorsResponse`, `ReportAlert`, `Outcome`.
  - `lastOnlineLabel(iso: string | null | undefined, now: Date): string`: "Today", "Yesterday", "N days ago" (2 to 7), "Over 7 days ago", or "".
  - `dayMonth(iso: string | null | undefined): string`: "5 Oct" in Barbados.
  - `stepLabel(key: string): string`; `gapLabel(key: string): string`; `tierLabel(key: string): string`; `outcomeLabel(key: string | null): string`; `OUTCOMES: { key: Outcome; label: string }[]`.
  - `startedByLabel(v: string | null): string`: "Send button", "Schedule", "Command line" or "Not recorded".
  - `weekOfLabel(weekStart: string): string`: "5 Oct" from "2026-10-05" with no time zone shift.
  - `funnelLatestLine(weeks: FunnelWeek[]): string`: "First messages and replies, 0 in the week of 5 Oct".
  - `cameBack(c: { last_run_came_back?: number | null; last_run_came_back_7d?: number | null }, win: "any" | "7"): number | null`.
  - `pushTurnedOn(c: { last_run_push_turned_on?: number | null; last_run_reached?: number | null }): string | null`: "0 of 24", or null (the row shows "Not this email").
  - `waitingStrip(s: WaitingSummary): [string, string][]`; `waitingBuckets(s: WaitingSummary): [string, number][]`.
  - `pushLine(members: number): string`: "of 58 members have push on".
  - `resolvedLine(r: { resolved_by_name: string | null; resolved_at: string | null }): string`: "Sarah, 13 Oct, 16:20".
  - `noFaceLine(k: { photos: number; people: number; members: number; staff: number }): string`: "6 photos, 5 people: 4 members and 1 staff account."
  - `gapStrip(k: ProfileGapsResponse["kpis"]): [number, string][]`.
  - `last30Line(l: { sends: number; people: number; came_back: number }): string`.
  - `errorsState(q: { isLoading: boolean; isError: boolean }, d: ApiErrorsResponse | undefined): "loading" | "na" | "none" | "some"`.
  - `photoWaiting(m: GateMember): string`: "" with no waiting photo, "Not recorded" when its upload time is unknown, else "5 Oct".

Every string here is either the export's (`handoff/copy/04-admin-acting-on-the-community.md`) or listed under the conflicts section as added.

- [ ] **Step 1: Write the failing test**

Create `tests/community.test.mjs`:

```js
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

// Acting on the community, the API data (TEC-1897). Same transpile and
// sandbox harness as tests/acting.test.mjs: the module is pure.
const source = readFileSync(new URL('../src/lib/community.ts', import.meta.url), 'utf8');

function load() {
  const module = { exports: {} };
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { module, exports: module.exports, console, Intl, Date });
  return module.exports;
}

const c = load();
const plain = (v) => JSON.parse(JSON.stringify(v));
// 13 Oct 2026, 10:00 in Barbados (UTC minus 4).
const NOW = new Date('2026-10-13T14:00:00Z');

test('last online reads in Barbados days', () => {
  assert.equal(c.lastOnlineLabel('2026-10-13T13:00:00+00:00', NOW), 'Today');
  assert.equal(c.lastOnlineLabel('2026-10-13T02:00:00+00:00', NOW), 'Yesterday'); // 22:00 on 12 Oct
  assert.equal(c.lastOnlineLabel('2026-10-10T14:00:00+00:00', NOW), '3 days ago');
  assert.equal(c.lastOnlineLabel('2026-10-06T14:00:00+00:00', NOW), '7 days ago');
  assert.equal(c.lastOnlineLabel('2026-10-05T14:00:00+00:00', NOW), 'Over 7 days ago');
  assert.equal(c.lastOnlineLabel(null, NOW), '');
});

test('steps, gaps, tiers and outcomes use the design words', () => {
  assert.equal(c.stepLabel('none'), 'The first step');
  assert.equal(c.stepLabel('date_of_birth'), 'Date of birth');
  assert.equal(c.gapLabel('only_declined'), 'Only declined photos');
  assert.equal(c.gapLabel('no_photo'), 'No photo');
  assert.equal(c.gapLabel('no_face'), 'No face in approved photos');
  assert.equal(c.tierLabel('none'), 'None');
  assert.deepEqual(plain(c.OUTCOMES.map((o) => o.label)), ['Dismissed', 'Warned', 'Deactivated']);
  assert.equal(c.outcomeLabel(null), 'Unresolved');
});

test('who started a run', () => {
  assert.equal(c.startedByLabel('schedule'), 'Schedule');
  assert.equal(c.startedByLabel('send_button'), 'Send button');
  assert.equal(c.startedByLabel('command_line'), 'Command line');
  assert.equal(c.startedByLabel(null), 'Not recorded');
});

test('the funnel names its latest week', () => {
  assert.equal(c.weekOfLabel('2026-10-05'), '5 Oct');
  const weeks = [
    { week_start: '2026-09-28', likes: 15, matches: 1, first_messages: 2, replies: 1 },
    { week_start: '2026-10-05', likes: 18, matches: 0, first_messages: 0, replies: 0 },
  ];
  assert.equal(c.funnelLatestLine(weeks), 'First messages and replies, 0 in the week of 5 Oct');
  assert.equal(c.funnelLatestLine([]), '');
});

test('came back follows the window, push turned on reads "0 of 24"', () => {
  const row = { last_run_came_back: 11, last_run_came_back_7d: null, last_run_push_turned_on: 0, last_run_reached: 24 };
  assert.equal(c.cameBack(row, 'any'), 11);
  assert.equal(c.cameBack(row, '7'), null);
  assert.equal(c.pushTurnedOn(row), '0 of 24');
  assert.equal(c.pushTurnedOn({ last_run_push_turned_on: null, last_run_reached: 50 }), null);
});

test('the waiting strip and buckets', () => {
  const s = {
    likes_waiting: 58, members_with_likes: 20, oldest_like_at: '2026-06-17T15:00:00+00:00',
    offline_7d: 14, push_on: 4, with_5_or_more: 6, with_2_to_4: 6, with_1: 8,
    conversations: 6, one_sided: 3, oldest_unanswered_at: null, matches: 7, silent_matches_7d: 1,
  };
  assert.deepEqual(plain(c.waitingStrip(s)), [
    ['58', 'likes waiting on 20 members'],
    ['17 Jun', 'oldest waiting like'],
    ['14 of 20', 'last online more than 7 days ago'],
    ['4 of 20', 'have push on'],
  ]);
  assert.deepEqual(plain(c.waitingBuckets(s)), [['5 or more', 6], ['2 to 4', 6], ['1', 8]]);
});

test('lines the design writes out', () => {
  assert.equal(c.pushLine(58), 'of 58 members have push on');
  assert.equal(c.resolvedLine({ resolved_by_name: 'Sarah', resolved_at: '2026-10-13T20:20:00+00:00' }), 'Sarah, 13 Oct, 16:20');
  assert.equal(c.noFaceLine({ photos: 6, people: 5, members: 4, staff: 1 }), '6 photos, 5 people: 4 members and 1 staff account.');
  assert.equal(c.noFaceLine({ photos: 1, people: 1, members: 1, staff: 0 }), '1 photo, 1 person: 1 member and 0 staff accounts.');
  assert.deepEqual(plain(c.gapStrip({ not_verified: 31, only_declined: 3, no_photo: 1, no_face_photo: 4 })), [
    [31, 'not verified'], [3, 'with only declined photos'], [1, 'with no photo'],
    [4, 'with no approved photo showing a face'],
  ]);
  assert.equal(c.last30Line({ sends: 53, people: 50, came_back: 5 }),
    '53 sends to 50 people in the last 30 days, 5 back online since. Every run also appears in Audit.');
});

test('the API errors card has four states', () => {
  assert.equal(c.errorsState({ isLoading: true, isError: false }, undefined), 'loading');
  assert.equal(c.errorsState({ isLoading: false, isError: true }, undefined), 'na');
  assert.equal(c.errorsState({ isLoading: false, isError: false }, { available: false, last_24h: null, last_7d: null, routes: [] }), 'na');
  assert.equal(c.errorsState({ isLoading: false, isError: false }, { available: true, last_24h: 0, last_7d: 0, routes: [] }), 'none');
  assert.equal(c.errorsState({ isLoading: false, isError: false }, { available: true, last_24h: 0, last_7d: 2, routes: [] }), 'some');
});

test('photo waiting', () => {
  const m = { has_waiting_photo: true, photo_waiting_since: null };
  assert.equal(c.photoWaiting(m), 'Not recorded');
  assert.equal(c.photoWaiting({ ...m, photo_waiting_since: '2026-10-05T15:00:00+00:00' }), '5 Oct');
  assert.equal(c.photoWaiting({ has_waiting_photo: false, photo_waiting_since: null }), '');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/community.test.mjs`
Expected: FAIL, `ENOENT: no such file or directory ... src/lib/community.ts`.

- [ ] **Step 3: Write the module**

Create `src/lib/community.ts`:

```ts
/**
 * Acting on the community, the API data (TEC-1897): wire types and pure
 * labels for the views the API now serves (Claude Design frames O.1, G.1,
 * G.2, G.4, R.2 to R.4, W.1, W.5, U.1, E.1 to E.3 and P.1 to P.3).
 *
 * No imports, no React, no fetch: tests/community.test.mjs transpiles this
 * file into a vm sandbox. Every string is the export's
 * (handoff/copy/04-admin-acting-on-the-community.md) or one the plan lists
 * as added for the owner's review.
 */

const BARBADOS = "America/Barbados";
const DAY_MS = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

export type WaitingSummary = {
  likes_waiting: number; members_with_likes: number; oldest_like_at: string | null;
  offline_7d: number; push_on: number; with_5_or_more: number; with_2_to_4: number; with_1: number;
  conversations: number; one_sided: number; oldest_unanswered_at: string | null;
  matches: number; silent_matches_7d: number;
};
export type WaitingMember = {
  uuid: string; name: string | null; likes_waiting: number; unanswered_openers: number;
  silent_matches: number; oldest_wait_at: string; last_online_at: string | null; push_on: boolean;
};
export type WaitingResponse = { summary: WaitingSummary; members: WaitingMember[] };

export type UnfinishedRow = { started_at: string; last_saved_at: string; furthest_step: string };
export type UnfinishedResponse = { count: number; rows: UnfinishedRow[] };

export type FunnelWeek = { week_start: string; likes: number; matches: number; first_messages: number; replies: number };
export type FunnelResponse = { weeks: FunnelWeek[] };

export type PushResponse = {
  members: number; members_with_push: number; with_push_counting_staff: number;
  members_failing: number; members_new_since: number; since: string;
};
export type TierRow = { tier: "none" | "bronze" | "silver" | "gold"; members: number };
export type TiersResponse = { tiers: TierRow[] };

export type EmailRun = {
  campaign_id: string; sent_at: string; started_by: string | null; reached: number;
  clicks: number | null; came_back: number | null; came_back_7d: number | null;
};
export type EmailRunsResponse = { runs: EmailRun[]; last_30_days: { sends: number; people: number; came_back: number } };

export type ProfileGapRow = { uuid: string; name: string | null; gap: string; tier: string };
export type ProfileGapsResponse = {
  kpis: { not_verified: number; only_declined: number; no_photo: number; no_face_photo: number };
  rows: ProfileGapRow[];
};

export type GateMember = {
  uuid: string; name: string | null; likes_sent_30d: number; likes_received_30d: number;
  matches_30d: number; messages_30d: number; profile_views_30d: number; last_online_at: string | null;
  has_waiting_photo: boolean; waiting_photo_uuid: string | null; photo_waiting_since: string | null;
};
export type PhotoGateResponse = { enabled: boolean; members: GateMember[] };

export type ApiErrorsResponse = {
  available: boolean; last_24h: number | null; last_7d: number | null;
  routes: { route: string; errors: number; last_failed_at: string }[];
};

export type ReportAlert = { enabled: boolean; switch_on: boolean };
export type Outcome = "dismissed" | "warned" | "deactivated";

// ---------------------------------------------------------------------------
// Time, in Barbados
// ---------------------------------------------------------------------------

function parts(at: Date, opts: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("en-US", { timeZone: BARBADOS, ...opts }).formatToParts(at)) {
    out[p.type] = p.value;
  }
  return out;
}

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at;
}

/** The Barbados calendar day as a UTC midnight, so two days subtract. */
function dayStamp(at: Date): number {
  const p = parts(at, { year: "numeric", month: "2-digit", day: "2-digit" });
  return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day));
}

export function dayMonth(iso: string | null | undefined): string {
  const at = parse(iso);
  if (!at) return "";
  const p = parts(at, { day: "numeric", month: "short" });
  return `${p.day} ${p.month}`;
}

function hourMinute(at: Date): string {
  const p = parts(at, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return `${p.hour}:${p.minute}`;
}

/** W.1 and W.5: "Today", "Yesterday", "3 days ago", "Over 7 days ago". */
export function lastOnlineLabel(iso: string | null | undefined, now: Date): string {
  const at = parse(iso);
  if (!at) return "";
  const days = Math.round((dayStamp(now) - dayStamp(at)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return `${days} days ago`;
  return "Over 7 days ago";
}

/** "5 Oct" from a "2026-10-05" week start, read as a date, not a moment. */
export function weekOfLabel(weekStart: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(weekStart);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : "";
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

const STEP_LABELS: Record<string, string> = {
  none: "The first step",
  name: "Name",
  date_of_birth: "Date of birth",
  gender: "Gender",
  photos: "Photos",
  country: "Country",
  assembly: "Assembly",
  relocation: "Relocation",
};
export function stepLabel(key: string): string {
  return STEP_LABELS[key] ?? "Not recorded";
}

const GAP_LABELS: Record<string, string> = {
  no_photo: "No photo",
  only_declined: "Only declined photos",
  only_pending: "Pending",
  no_face: "No face in approved photos",
};
export function gapLabel(key: string): string {
  return GAP_LABELS[key] ?? key;
}

const TIER_LABELS: Record<string, string> = { none: "None", bronze: "Bronze", silver: "Silver", gold: "Gold" };
export function tierLabel(key: string): string {
  return TIER_LABELS[key] ?? key;
}

export const OUTCOMES: { key: Outcome; label: string }[] = [
  { key: "dismissed", label: "Dismissed" },
  { key: "warned", label: "Warned" },
  { key: "deactivated", label: "Deactivated" },
];
export function outcomeLabel(key: string | null): string {
  return OUTCOMES.find((o) => o.key === key)?.label ?? "Unresolved";
}

const STARTED_BY: Record<string, string> = {
  schedule: "Schedule",
  send_button: "Send button",
  command_line: "Command line",
};
export function startedByLabel(v: string | null): string {
  return STARTED_BY[v ?? ""] ?? "Not recorded";
}

// ---------------------------------------------------------------------------
// Lines the design writes out
// ---------------------------------------------------------------------------

export function funnelLatestLine(weeks: FunnelWeek[]): string {
  const last = weeks[weeks.length - 1];
  if (!last) return "";
  return `First messages and replies, ${last.first_messages + last.replies} in the week of ${weekOfLabel(last.week_start)}`;
}

export function cameBack(
  c: { last_run_came_back?: number | null; last_run_came_back_7d?: number | null },
  win: "any" | "7",
): number | null {
  const v = win === "7" ? c.last_run_came_back_7d : c.last_run_came_back;
  return v ?? null;
}

export function pushTurnedOn(c: { last_run_push_turned_on?: number | null; last_run_reached?: number | null }): string | null {
  if (c.last_run_push_turned_on == null || c.last_run_reached == null) return null;
  return `${c.last_run_push_turned_on} of ${c.last_run_reached}`;
}

export function waitingStrip(s: WaitingSummary): [string, string][] {
  const n = s.members_with_likes;
  return [
    [String(s.likes_waiting), `likes waiting on ${n} members`],
    [dayMonth(s.oldest_like_at), "oldest waiting like"],
    [`${s.offline_7d} of ${n}`, "last online more than 7 days ago"],
    [`${s.push_on} of ${n}`, "have push on"],
  ];
}

export function waitingBuckets(s: WaitingSummary): [string, number][] {
  return [["5 or more", s.with_5_or_more], ["2 to 4", s.with_2_to_4], ["1", s.with_1]];
}

export function pushLine(members: number): string {
  return `of ${members} members have push on`;
}

export function resolvedLine(r: { resolved_by_name: string | null; resolved_at: string | null }): string {
  const at = parse(r.resolved_at);
  if (!at) return "";
  const when = `${dayMonth(r.resolved_at)}, ${hourMinute(at)}`;
  return r.resolved_by_name ? `${r.resolved_by_name}, ${when}` : when;
}

function n(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function noFaceLine(k: { photos: number; people: number; members: number; staff: number }): string {
  return `${n(k.photos, "photo", "photos")}, ${n(k.people, "person", "people")}: ` +
    `${n(k.members, "member", "members")} and ${n(k.staff, "staff account", "staff accounts")}.`;
}

export function gapStrip(k: ProfileGapsResponse["kpis"]): [number, string][] {
  return [
    [k.not_verified, "not verified"],
    [k.only_declined, "with only declined photos"],
    [k.no_photo, "with no photo"],
    [k.no_face_photo, "with no approved photo showing a face"],
  ];
}

export function last30Line(l: { sends: number; people: number; came_back: number }): string {
  return `${l.sends} sends to ${l.people} people in the last 30 days, ${l.came_back} back online since. ` +
    "Every run also appears in Audit.";
}

export function errorsState(
  q: { isLoading: boolean; isError: boolean },
  d: ApiErrorsResponse | undefined,
): "loading" | "na" | "none" | "some" {
  if (q.isLoading) return "loading";
  if (q.isError || !d || !d.available) return "na";
  return (d.last_7d ?? 0) > 0 ? "some" : "none";
}

export function photoWaiting(m: { has_waiting_photo: boolean; photo_waiting_since: string | null }): string {
  if (!m.has_waiting_photo) return "";
  return m.photo_waiting_since ? dayMonth(m.photo_waiting_since) : "Not recorded";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/community.test.mjs`
Expected: `# pass 9`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add src/lib/community.ts tests/community.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): labels and shapes for the community views the API now serves" -m "Refs: TEC-1897"
```

---

### Task 16: Wire types, hooks and mutations

**Files:**
- Modify: `src/lib/types.ts` (`UserListRow`, `UserDetailResponse.profile`, `ReportRow`, `ReportsResponse`, `ModerationPhotosResponse`)
- Modify: `src/lib/growth-api.ts` (`EmailCampaign`)
- Modify: `src/lib/queries.ts` (append hooks)
- Modify: `src/lib/growth-queries.ts` (append hooks)
- Modify: `src/lib/mutations.ts` (append mutations)

**Interfaces:**
- Consumes: the wire types of Task 15; `api` from `src/lib/api-client.ts`.
- Produces: `useWaiting()`, `useUnfinished()`, `useFunnel()`, `useProfileGaps()`, `usePhotoGate()`, `useApiErrors()`, `useReportAlert()` in `queries.ts`; `usePush()`, `useTiers()`, `useEmailRuns(campaign: string | null)` in `growth-queries.ts`; `useResolveReport()` (variables `{ key: string; outcome: Outcome; note: string }`) and `useSetReportAlert()` (variables `boolean`) in `mutations.ts`.

These are wiring with no logic of their own; the type check is their test.

- [ ] **Step 1: Write the failing check**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit`
Expected: passes today. Add the file below first, then run it again.

Create `src/lib/community-wire-check.ts` (deleted in Step 4; it pins every name later tasks import):

```ts
import { usePush, useTiers, useEmailRuns } from "@/lib/growth-queries";
import { useWaiting, useUnfinished, useFunnel, useProfileGaps, usePhotoGate, useApiErrors, useReportAlert } from "@/lib/queries";
import { useResolveReport, useSetReportAlert } from "@/lib/mutations";
import type { ReportRow, UserListRow, UserDetailResponse, ModerationPhotosResponse } from "@/lib/types";
import type { EmailCampaign } from "@/lib/growth-api";

export const hooks = [usePush, useTiers, useEmailRuns, useWaiting, useUnfinished, useFunnel,
  useProfileGaps, usePhotoGate, useApiErrors, useReportAlert, useResolveReport, useSetReportAlert];
export type Check = [
  ReportRow["report_key"], ReportRow["outcome"], UserListRow["likes_waiting"],
  UserDetailResponse["profile"]["push_devices"], ModerationPhotosResponse["approved_no_face"],
  EmailCampaign["last_run_came_back"],
];
```

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit`
Expected: FAIL, `Module '"@/lib/growth-queries"' has no exported member 'usePush'` and the other missing names.

- [ ] **Step 2: Add the types**

In `src/lib/types.ts`, add to `UserListRow` after `unsubscribed_at: string | null;`:

```ts
  // TEC-1897 (frame W.5): when the member was last online, ISO, and how many
  // likes nobody has answered.
  last_online_at?: string | null;
  likes_waiting?: number;
```

Add to `UserDetailResponse["profile"]`, after `last_online_time: string | null;`:

```ts
    // Push on or off in the drawer (TEC-1897): devices subscribed, and
    // whether any of them is failing.
    push_devices?: number;
    push_failing?: boolean;
```

Replace `ReportRow` and `ReportsResponse` with:

```ts
export type ReportRow = {
  created_at: string;
  // TEC-1897: the report's key, and its resolution when there is one.
  report_key: string;
  reporter_uuid: string | null;
  reporter_name: string | null;
  reporter_email: string | null;
  reported_uuid: string | null;
  reported_name: string | null;
  reported_email: string | null;
  reported_active: boolean | null;
  reported_verification_required: boolean | null;
  reason: string | null;
  outcome: "dismissed" | "warned" | "deactivated" | null;
  note: string | null;
  resolved_at: string | null;
  resolved_by_name: string | null;
};

export type ReportsResponse = { reports: ReportRow[]; count: number; unresolved?: number };
```

In `ModerationPhotosResponse`, add to the row type after `owner_uuid: string;`:

```ts
    owner_is_staff?: boolean;
    uploaded_at?: string | null;
```

and after its `kpis` line:

```ts
  // Frame P.3's line (TEC-1897).
  approved_no_face?: { photos: number; people: number; members: number; staff: number };
```

In `src/lib/growth-api.ts`, add to `EmailCampaign` after `people_reached?: number;`:

```ts
  // What each email achieved (TEC-1897; frames G.1 and G.2). Came back
  // counts recipients online since their send; the 7 day figure is null for
  // runs before the per-day record began; push turned on is e6's alone.
  // `came_back` is on the system rows.
  last_run_came_back?: number | null;
  last_run_came_back_7d?: number | null;
  last_run_push_turned_on?: number | null;
  came_back?: number | null;
```

- [ ] **Step 3: Add the hooks and mutations**

Append to `src/lib/queries.ts` (and add `import type { ApiErrorsResponse, FunnelResponse, PhotoGateResponse, ProfileGapsResponse, ReportAlert, UnfinishedResponse, WaitingResponse } from "@/lib/community";` to its imports):

```ts
/** Members someone is waiting on (TEC-1897; frame W.1). Counts only. */
export function useWaiting() {
  return useQuery<WaitingResponse>({
    queryKey: ["community", "waiting"],
    queryFn: () => api.get<WaitingResponse>("/admin/community/waiting"),
  });
}

/** People who started sign-up and stopped (frames U.1 to U.4). */
export function useUnfinished() {
  return useQuery<UnfinishedResponse>({
    queryKey: ["community", "unfinished"],
    queryFn: () => api.get<UnfinishedResponse>("/admin/community/unfinished"),
  });
}

/** Likes, matches, first messages and replies per Barbados week (O.1). */
export function useFunnel() {
  return useQuery<FunnelResponse>({
    queryKey: ["community", "funnel"],
    queryFn: () => api.get<FunnelResponse>("/admin/community/funnel"),
  });
}

export function useProfileGaps() {
  return useQuery<ProfileGapsResponse>({
    queryKey: ["moderation", "profile-gaps"],
    queryFn: () => api.get<ProfileGapsResponse>("/admin/moderation/profile-gaps"),
  });
}

export function usePhotoGate() {
  return useQuery<PhotoGateResponse>({
    queryKey: ["moderation", "photo-gate"],
    queryFn: () => api.get<PhotoGateResponse>("/admin/moderation/photo-gate"),
  });
}

export function useApiErrors() {
  return useQuery<ApiErrorsResponse>({
    queryKey: ["system", "errors"],
    queryFn: () => api.get<ApiErrorsResponse>("/admin/system/errors"),
  });
}

/** "Email me when a report arrives" (frame R.2). */
export function useReportAlert() {
  return useQuery<ReportAlert>({
    queryKey: ["moderation", "report-alert"],
    queryFn: () => api.get<ReportAlert>("/admin/alerts/report"),
  });
}
```

Append to `src/lib/growth-queries.ts` (and add `import type { EmailRunsResponse, PushResponse, TiersResponse } from "@/lib/community";`):

```ts
/** Push on, failing and new since the Discover banner (frame G.1). */
export function usePush() {
  return useQuery<PushResponse>({
    queryKey: ["growth", "push"],
    queryFn: () => api.get<PushResponse>("/admin/growth/push"),
  });
}

/** Members per verification tier (frame G.1). */
export function useTiers() {
  return useQuery<TiersResponse>({
    queryKey: ["growth", "tiers"],
    queryFn: () => api.get<TiersResponse>("/admin/growth/tiers"),
  });
}

/** One email's run history (frame G.4). Off until a row is opened. */
export function useEmailRuns(campaign: string | null) {
  return useQuery<EmailRunsResponse>({
    queryKey: ["growth", "email-runs", campaign],
    queryFn: () => api.get<EmailRunsResponse>(`/admin/growth/emails/${campaign}/runs`),
    enabled: !!campaign,
  });
}
```

Append to `src/lib/mutations.ts` (and add `import type { Outcome, ReportAlert } from "@/lib/community";`):

```ts
/** Resolve a report (frame R.3). The list and the Needs you tile refresh. */
export function useResolveReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { key: string; outcome: Outcome; note: string }) =>
      api.post<{ ok: boolean }>(`/admin/reports/${encodeURIComponent(v.key)}/resolve`,
        { outcome: v.outcome, note: v.note }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["moderation", "reports"] }),
  });
}

/** Turn "Email me when a report arrives" on or off (frame R.2). */
export function useSetReportAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.post<ReportAlert>("/admin/alerts/report", { enabled }),
    onSuccess: (data) => qc.setQueryData(["moderation", "report-alert"], data),
  });
}
```

- [ ] **Step 4: Run the type check, then delete the pin file**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit`
Expected: no errors. Then delete `src/lib/community-wire-check.ts` and run `npx tsc --noEmit` again: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/lib/types.ts src/lib/growth-api.ts src/lib/queries.ts src/lib/growth-queries.ts src/lib/mutations.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): types and hooks for the community endpoints" -m "Refs: TEC-1897"
```

---

### Task 17: The Needs you band with all 5 tiles

**Files:**
- Modify: `src/components/admin/needs-you.tsx`
- Modify: `src/lib/acting.ts` (append `reportsWaiting`)
- Test: `tests/acting.test.mjs` (append)

**Interfaces:**
- Consumes: `useWaiting`, `useUnfinished` (Task 16); `ReportsResponse.unresolved`; `dayMonth` from `src/lib/acting.ts`.
- Produces: `acting.reportsWaiting(data: { count?: number; unresolved?: number; reports?: unknown[] } | undefined): number | undefined`; the band with the export's 5 tiles in its order (posts, reports, waiting, unfinished, gate).

Frames O.1 to O.6. Labels: "members have likes nobody has answered" (W.1's count, `members_with_likes`), "unfinished sign-up, started 8 Oct" (the newest unfinished sign-up's start; plural "unfinished sign-ups, the latest started 8 Oct" is added, see conflicts), empties "Nobody waiting on a reply" and "No unfinished sign-ups". The waiting tile opens `/?tab=users&view=waiting`, the unfinished tile `/?tab=users&view=unfinished`. Desktop is 5 level tiles; tablet is the export's 6-column bento (3 tiles of 2, then 2 of 3).

- [ ] **Step 1: Write the failing test**

Append to `tests/acting.test.mjs`:

```js
test('reports waiting reads the unresolved count, never every report', () => {
  assert.equal(a.reportsWaiting({ count: 5, unresolved: 2, reports: [] }), 2);
  // An API from before TEC-1897 has no unresolved count: every report is
  // unresolved there, since nothing could resolve one.
  assert.equal(a.reportsWaiting({ count: 3, reports: [] }), 3);
  assert.equal(a.reportsWaiting(undefined), undefined);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/acting.test.mjs`
Expected: FAIL, `a.reportsWaiting is not a function`.

- [ ] **Step 3: Write the helper and the tiles**

Append to `src/lib/acting.ts`:

```ts
/** The reports tile's count (TEC-1897): unresolved reports only. Before the
 *  API counted them, nothing could resolve a report, so every report was
 *  unresolved. */
export function reportsWaiting(
  data: { count?: number; unresolved?: number; reports?: unknown[] } | undefined,
): number | undefined {
  if (!data) return undefined;
  return data.unresolved ?? data.count ?? data.reports?.length;
}
```

In `src/components/admin/needs-you.tsx`:
- Imports: add `Heart, User` to the lucide import; replace `import { bandState, postsWaiting, tileState, type TileState } from "@/lib/acting";` with `import { bandState, dayMonth, postsWaiting, reportsWaiting, tileState, type TileState } from "@/lib/acting";`; replace `import { useModerationPhotos, useReports } from "@/lib/queries";` with `import { useModerationPhotos, useReports, useUnfinished, useWaiting } from "@/lib/queries";`.
- Replace the component docstring's second and third paragraphs with: `All five tiles the design draws are here (TEC-1897): posts waiting for approval, unresolved reports, members someone is waiting on, unfinished sign-ups and members held by the photo gate.`
- In `NeedsYouBand`, after `const photos = useModerationPhotos("queue");` add:

```tsx
  const waiting = useWaiting();
  const unfinished = useUnfinished();
```

- Replace `const reportCount = reports.data?.count ?? (reports.data ? reports.data.reports.length : undefined);` with `const reportCount = reportsWaiting(reports.data);`.
- Replace the reports tile's comment and label lines:

```tsx
      // Nothing can resolve a report yet (the API records no outcome), so
      // every report on file is unresolved.
      label: plural(reportCount ?? 0, "unresolved report", "unresolved reports"),
```

with:

```tsx
      label: plural(reportCount ?? 0, "unresolved report", "unresolved reports"),
```

- Between the reports tile and the gate tile in `tiles`, add:

```tsx
    {
      id: "waiting",
      icon: Heart,
      state: tileState(waiting, waiting.data?.summary.members_with_likes),
      count: waiting.data?.summary.members_with_likes ?? 0,
      label: plural(waiting.data?.summary.members_with_likes ?? 0,
        "member has likes nobody has answered", "members have likes nobody has answered"),
      empty: "Nobody waiting on a reply",
      href: "/?tab=users&view=waiting",
      retry: () => { waiting.refetch(); },
    },
    {
      id: "unfinished",
      icon: User,
      state: tileState(unfinished, unfinished.data?.count),
      count: unfinished.data?.count ?? 0,
      label: (unfinished.data?.count ?? 0) === 1
        ? `unfinished sign-up, started ${dayMonth(unfinished.data?.rows[0]?.started_at)}`
        : `unfinished sign-ups, the latest started ${dayMonth(unfinished.data?.rows[0]?.started_at)}`,
      empty: "No unfinished sign-ups",
      href: "/?tab=users&view=unfinished",
      retry: () => { unfinished.refetch(); },
    },
```

- Replace the desktop grid:

```tsx
        <div className="grid grid-cols-3 gap-3.5 items-stretch">
          {tiles.map((t) => <DeskTile key={t.id} t={t} open={open} />)}
        </div>
```

with (frame O.1 at 1440, five level tiles; at 768 the export's 6-column bento, 2, 2, 2, then 3, 3):

```tsx
        <div className="grid grid-cols-6 lg:grid-cols-5 gap-3.5 items-stretch">
          {tiles.map((t, i) => (
            <div key={t.id} className={cn("flex flex-col lg:col-span-1", i < 3 ? "col-span-2" : "col-span-3")}>
              <DeskTile t={t} open={open} />
            </div>
          ))}
        </div>
```

and give `DeskTile`'s `Card` `flex-1` in its className (append `"flex-1"` to the `cn(...)` list) so tiles in a row share a height.

- [ ] **Step 4: Run tests and the type check**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/acting.test.mjs && npx tsc --noEmit`
Expected: all acting tests pass; no type errors.

- [ ] **Step 5: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" O.1,O.2,O.3,O.4,O.5,O.6` and fix any difference it reports in `needs-you.tsx` only.

```bash
git add src/lib/acting.ts tests/acting.test.mjs src/components/admin/needs-you.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(overview): the Needs you band with all five tiles" -m "Refs: TEC-1897"
```

---

### Task 18: Reports: outcome, resolving and "Email me when a report arrives"

**Files:**
- Create: `src/components/admin/report-resolve-dialog.tsx`
- Modify: `src/components/admin/tab-moderation.tsx` (`ReportsView`)

**Interfaces:**
- Consumes: `ReportRow` (Task 16); `useResolveReport`, `useSetReportAlert`, `useReportAlert` (Task 16); `OUTCOMES`, `outcomeLabel`, `resolvedLine` (Task 15); `Dialog`, `DialogContent` (`src/components/ui/dialog.tsx`); `growthBtn`.
- Produces: `ResolveReportDialog({ report, open, onOpenChange })`.

Frames R.1 to R.5. The table gains the Outcome column ("Unresolved" as an amber pill; a resolved row shows its outcome pill and, beneath it, `resolvedLine`). Desktop rows carry "Resolve" (primary, extra small). A phone shows the button disabled and the line "Needs a desktop" with the lock icon. The card's caption is the design's "Overview counts unresolved reports only." without the export's note about placeholders, which described the mock. Below the card, on desktop only, the "Email me when a report arrives" switch row from R.2; its secondary line ("Owner decision: on or off") was a design note and is not shown.

- [ ] **Step 1: Write the dialog**

Create `src/components/admin/report-resolve-dialog.tsx`:

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { growthBtn } from "@/components/admin/growth-dialogs";
import { OUTCOMES, type Outcome } from "@/lib/community";
import { useResolveReport } from "@/lib/mutations";
import type { ReportRow } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Resolve this report (TEC-1897; frame R.3): an outcome, an optional note,
 * and the API records who resolved it and when. Recording "Deactivated"
 * deactivates nobody; the drawer's Deactivate action does that.
 */
export function ResolveReportDialog({
  report, open, onOpenChange,
}: { report: ReportRow | null; open: boolean; onOpenChange: (next: boolean) => void }) {
  const [outcome, setOutcome] = useState<Outcome>("dismissed");
  const [note, setNote] = useState("");
  const resolve = useResolveReport();

  async function onResolve() {
    if (!report) return;
    try {
      await resolve.mutateAsync({ key: report.report_key, outcome, note });
      onOpenChange(false);
      setNote("");
    } catch {
      toast.error("Could not load reports.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[480px] max-w-[calc(100vw-32px)] rounded-[18px] border-(--line-2) p-[22px] flex flex-col gap-3.5">
        <h2 className="text-[18px] font-extrabold text-(--ink) m-0">Resolve this report</h2>
        <div role="radiogroup" className="flex flex-col gap-2">
          {OUTCOMES.map((o) => (
            <button
              key={o.key}
              type="button"
              role="radio"
              aria-checked={outcome === o.key}
              onClick={() => setOutcome(o.key)}
              className={cn(
                "flex items-center gap-3 min-h-12 px-3.5 rounded-[12px] border text-left text-[14px] font-bold",
                outcome === o.key ? "border-(--lavender) bg-(--lavender-soft) text-(--ink)" : "border-(--line-2) text-(--ink-2)",
              )}
            >
              <span className={cn("h-4 w-4 rounded-full border-2", outcome === o.key ? "border-(--lavender) bg-(--lavender)" : "border-(--line-3)")} />
              {o.label}
            </button>
          ))}
        </div>
        <label className="flex flex-col gap-1.5 text-[12.5px] font-bold text-(--ink-2)">
          Note (optional)
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value.slice(0, 1000))}
            placeholder="What you decided and why"
            className="min-h-20 rounded-[10px] border border-(--line-2) bg-(--card-2) p-3 text-[13.5px] font-medium text-(--ink)"
          />
        </label>
        <span className="text-[12px] text-(--faint)">Records the outcome, who resolved it and when.</span>
        <div className="flex justify-end gap-2.5">
          <button type="button" className={growthBtn("ghost", "sm")} onClick={() => onOpenChange(false)}>Cancel</button>
          <button type="button" className={growthBtn("lime", "sm")} onClick={onResolve} disabled={resolve.isPending}>Resolve</button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

The failure toast reuses R.5's "Could not load reports." because the export has no resolve-failed line; a dedicated line is listed under the conflicts.

- [ ] **Step 2: Extend the Reports view**

In `src/components/admin/tab-moderation.tsx`:
- Imports: add `Lock` to the lucide import; add `import { Switch } from "@/components/ui/switch";`, `import { ResolveReportDialog } from "@/components/admin/report-resolve-dialog";`, `import { outcomeLabel, resolvedLine } from "@/lib/community";`, and `useReportAlert` to the `@/lib/queries` import, `useSetReportAlert` to the `@/lib/mutations` import; `import type { ReportRow } from "@/lib/types";`; `import { growthBtn } from "@/components/admin/growth-dialogs";`.
- Replace the `ReportsView` docstring's second paragraph with: `Resolving records an outcome, who resolved it and when (TEC-1897; R.2 to R.4). On a phone the Resolve button shows but stays disabled.`
- Inside `ReportsView`, after `const rows = data?.reports ?? [];` add:

```tsx
  const [resolving, setResolving] = useState<ReportRow | null>(null);
  const outcome = (r: ReportRow) =>
    r.outcome ? (
      <span className="flex flex-col gap-1 items-start">
        <Badge tone="neutral">{outcomeLabel(r.outcome)}</Badge>
        <span className="text-[11.5px] text-(--faint)">{resolvedLine(r)}</span>
      </span>
    ) : (
      <Badge tone="pending">Unresolved</Badge>
    );
```

- In the phone list, after the Member status row add:

```tsx
                  <div className="flex justify-between gap-2.5 items-center"><span className="text-(--faint)">Outcome</span>{outcome(r)}</div>
                  {!r.outcome ? (
                    <div className="flex items-center justify-between gap-2.5 pt-1">
                      <span className="flex items-center gap-1.5 text-[12px] text-(--faint)"><Lock size={13} />Needs a desktop</span>
                      <button type="button" className={growthBtn("lime", "sm")} disabled>Resolve</button>
                    </div>
                  ) : null}
```

- In the desktop table head, after `<Th>Member status</Th>` add `<Th>Outcome</Th>` and `<Th> </Th>`; in each desktop row, after the member status cell add:

```tsx
                      <Td>{outcome(r)}</Td>
                      <Td className="text-right">
                        {!r.outcome ? (
                          <button type="button" className={growthBtn("lime", "sm")} onClick={() => setResolving(r)}>Resolve</button>
                        ) : null}
                      </Td>
```

- Change the card to `<AdminCard title="Reports" sub="Overview counts unresolved reports only.">`.
- After the closing `</AdminCard>` of the Reports card add:

```tsx
      <ReportAlertRow />
      <ResolveReportDialog report={resolving} open={!!resolving} onOpenChange={(next) => { if (!next) setResolving(null); }} />
```

- Add, below `ReportsView`:

```tsx
/** "Email me when a report arrives" (frame R.2), desktop only as drawn. The
 *  email also needs AHAVAH_REPORT_ALERT_ENABLED on the server; the switch
 *  stores the owner's choice either way. */
function ReportAlertRow() {
  const alert = useReportAlert();
  const set = useSetReportAlert();
  return (
    <div className="max-md:hidden mt-3.5 flex items-center gap-3 rounded-[16px] border border-(--line) bg-(--card) p-[16px_18px]">
      <Switch
        checked={alert.data?.enabled ?? false}
        disabled={alert.isLoading || set.isPending}
        onCheckedChange={(next) => set.mutate(next)}
        aria-label="Email me when a report arrives"
      />
      <b className="text-[14px] text-(--ink)">Email me when a report arrives</b>
    </div>
  );
}
```

- [ ] **Step 3: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no type errors; the build completes.

- [ ] **Step 4: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" R.1,R.2,R.3,R.4,R.5` and fix what it reports in these two files.

```bash
git add src/components/admin/report-resolve-dialog.tsx src/components/admin/tab-moderation.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(moderation): resolve a report and choose whether a new one emails the owner" -m "Refs: TEC-1897"
```

---

### Task 19: Waiting on a reply, the Users additions and push in the drawer

**Files:**
- Create: `src/components/admin/community-waiting.tsx`
- Modify: `src/components/admin/tab-users.tsx` (`FILTER_PILLS`, the table, the `view` switch)
- Modify: `src/components/admin/user-drawer-activity.tsx`

**Interfaces:**
- Consumes: `useWaiting` (Task 16); `waitingStrip`, `waitingBuckets`, `lastOnlineLabel`, `dayMonth` (Task 15); `UserDrawer`; `UserListRow.last_online_at`, `likes_waiting`; `UserDetailResponse.profile.push_devices`, `push_failing`.
- Produces: `CommunityWaiting()`; the Users tab renders it when `?view=waiting`.

Frames W.1 and W.5. W.1 is the owner's recommended option (counts only, "Write to them"). "Write to them" shows on each row, disabled at every width with the U.1 line "Off until the owner approves a reminder and its words.", because writing to a member is a member-facing email outside this issue (decision 7). The drawer's Activity card gains "Push" with an "On" or "Off" pill. The Users table gains "Last online" between Type and Roles, and a "Likes waiting" pill in Status.

- [ ] **Step 1: Write the waiting view**

Create `src/components/admin/community-waiting.tsx`:

```tsx
"use client";

import { useState } from "react";
import { AlertCircle, Heart, Lock, MessageCircle, Users } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { AdminCard, Badge, PageHead, Td, Th, Tr } from "@/components/admin/design-primitives";
import { UserDrawer } from "@/components/admin/user-drawer";
import { growthBtn } from "@/components/admin/growth-dialogs";
import { dayMonth, lastOnlineLabel, waitingBuckets, waitingStrip } from "@/lib/community";
import { useWaiting } from "@/lib/queries";

/**
 * Waiting on a reply (TEC-1897; frame W.1): members with likes nobody has
 * answered, a conversation they have not replied to or a match where nobody
 * has written. Counts per member only, never who liked whom, never what was
 * said. Sorted by oldest wait.
 */
export function CommunityWaiting() {
  const { data, isLoading, isError, refetch } = useWaiting();
  const [openUuid, setOpenUuid] = useState<string | null>(null);
  const now = new Date();

  const write = (
    <button type="button" className={growthBtn("lime", "sm")} disabled>Write to them</button>
  );
  const off = (
    <span className="flex items-center gap-1.5 text-[12px] text-(--faint)">
      <Lock size={13} />Off until the owner approves a reminder and its words.
    </span>
  );

  if (isError) {
    return (
      <AdminCard title="Waiting on a reply">
        <div className="flex flex-wrap items-center gap-3 mt-2">
          <span className="flex gap-1.5 items-center text-[13px] font-semibold text-(--red)"><AlertCircle size={15} />Could not load this count.</span>
          <button type="button" className={growthBtn("ghost", "sm")} onClick={() => refetch()}>Try again</button>
        </div>
      </AdminCard>
    );
  }

  const s = data?.summary;
  return (
    <div className="flex flex-col gap-3.5">
      <PageHead title="Waiting on a reply" sub="Members someone is waiting on" />

      {/* The strip: four tiles from tablet up, one card of rows on a phone. */}
      {isLoading || !s ? (
        <Skeleton className="h-[96px] w-full" />
      ) : (
        <>
          <div className="md:hidden rounded-[16px] border border-(--line) bg-(--card) p-[16px_18px] flex flex-col gap-2">
            {waitingStrip(s).map(([v, l]) => (
              <div key={l} className="flex items-baseline gap-2.5">
                <b className="text-[20px] min-w-20 tabular-nums">{v}</b>
                <span className="text-[13px] text-(--muted)">{l}</span>
              </div>
            ))}
          </div>
          <div className="max-md:hidden grid grid-cols-4 gap-3.5">
            {waitingStrip(s).map(([v, l]) => (
              <div key={l} className="rounded-[16px] border border-(--line) bg-(--card) p-[16px_18px] flex flex-col gap-1.5">
                <span className="text-[26px] font-extrabold leading-none tabular-nums">{v}</span>
                <span className="text-[13px] text-(--muted)">{l}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-3.5 items-start">
        <AdminCard title="Waiting on a reply" sub="Sorted by oldest wait. Counts per member only, never who liked whom.">
          {isLoading ? <Skeleton className="h-10 w-full mt-2" /> : (
            <>
              <div className="md:hidden flex flex-col">
                {data!.members.map((m) => (
                  <div key={m.uuid} className="flex flex-col gap-1 py-3 border-b border-(--line) last:border-b-0 text-[12.5px]">
                    <button type="button" onClick={() => setOpenUuid(m.uuid)} className="text-left text-[14px] font-bold text-(--ink)">{m.name || "Unknown member"}</button>
                    <div className="flex justify-between"><span className="text-(--faint)">Likes waiting</span><span>{m.likes_waiting}</span></div>
                    <div className="flex justify-between"><span className="text-(--faint)">Oldest wait</span><span>{dayMonth(m.oldest_wait_at)}</span></div>
                    <div className="flex justify-between"><span className="text-(--faint)">Last online</span><span>{lastOnlineLabel(m.last_online_at, now)}</span></div>
                    <div className="flex justify-between items-center"><span className="text-(--faint)">Push</span><Badge tone={m.push_on ? "active" : "neutral"}>{m.push_on ? "On" : "Off"}</Badge></div>
                    <div className="pt-1">{write}</div>
                  </div>
                ))}
              </div>
              <table className="max-md:hidden w-full border-collapse text-[13.5px] mt-1">
                <thead><tr><Th>Member</Th><Th>Likes waiting</Th><Th>Oldest wait</Th><Th>Last online</Th><Th>Push</Th><Th> </Th></tr></thead>
                <tbody>
                  {data!.members.map((m) => (
                    <Tr key={m.uuid}>
                      <Td><button type="button" onClick={() => setOpenUuid(m.uuid)} className="font-bold text-(--ink) hover:underline">{m.name || "Unknown member"}</button></Td>
                      <Td className="tabular-nums">{m.likes_waiting}</Td>
                      <Td className="whitespace-nowrap">{dayMonth(m.oldest_wait_at)}</Td>
                      <Td className="whitespace-nowrap">{lastOnlineLabel(m.last_online_at, now)}</Td>
                      <Td><Badge tone={m.push_on ? "active" : "neutral"}>{m.push_on ? "On" : "Off"}</Badge></Td>
                      <Td className="text-right">{write}</Td>
                    </Tr>
                  ))}
                </tbody>
              </table>
              <div className="pt-2.5">{off}</div>
            </>
          )}
        </AdminCard>

        <div className="flex flex-col gap-3.5">
          <AdminCard title="Likes waiting, per member">
            {s ? (
              <div className="flex flex-col gap-1.5 text-[13px] mt-2">
                {waitingBuckets(s).map(([l, v]) => {
                  const max = Math.max(1, ...waitingBuckets(s).map(([, x]) => x));
                  return (
                    <div key={l} className="flex items-center gap-2.5">
                      <span className="w-20">{l}</span>
                      <div className="flex-1 h-2.5 rounded-full bg-(--line)"><div className="h-full rounded-full bg-(--lavender)" style={{ width: `${(v / max) * 100}%` }} /></div>
                      <b className="w-5 text-right tabular-nums">{v}</b>
                    </div>
                  );
                })}
              </div>
            ) : <Skeleton className="h-16 w-full mt-2" />}
          </AdminCard>
          <AdminCard title="Conversations and matches">
            {s ? (
              <div className="flex flex-col gap-1.5 text-[13px] mt-2">
                <div className="flex justify-between"><span>Conversations</span><b>{s.conversations}</b></div>
                <div className="flex justify-between"><span>One-sided</span><b>{s.one_sided}</b></div>
                <div className="flex justify-between"><span>Oldest unanswered opener</span><b>{dayMonth(s.oldest_unanswered_at)}</b></div>
                <div className="flex justify-between"><span>Matches</span><b>{s.matches}</b></div>
                <div className="flex justify-between"><span>No message for 7 days or more</span><b>{s.silent_matches_7d}</b></div>
              </div>
            ) : <Skeleton className="h-24 w-full mt-2" />}
          </AdminCard>
        </div>
      </div>

      {openUuid ? <UserDrawer uuid={openUuid} onClose={() => setOpenUuid(null)} /> : null}
    </div>
  );
}
```

The icons imported for the card heads (`Heart`, `MessageCircle`, `Users`) are placed by `/sot-sync` where the frame draws them.

- [ ] **Step 2: The Users tab and the drawer**

In `src/components/admin/tab-users.tsx`:
- Add `{ id: "has_likes_waiting", label: "Has likes waiting" },` as the last entry of `FILTER_PILLS`.
- Add imports `import { CommunityWaiting } from "@/components/admin/community-waiting";` and `import { lastOnlineLabel } from "@/lib/community";`.
- `TabUsers` (line 103) calls hooks after `useSearchParams()`, so an early return inside it would change the hook order between views. Rename the existing `export function TabUsers() {` to `function UsersList() {` and add above it:

```tsx
/** The Users tab and the two lists the Needs you band opens into it
 *  (TEC-1897): ?view=waiting and ?view=unfinished. */
export function TabUsers() {
  const view = useSearchParams().get("view");
  if (view === "waiting") return <CommunityWaiting />;
  return <UsersList />;
}
```
- In the table head, after the `Type` header cell add a header cell with the same classes and the text `Last online`; in each row, after the type cell add:

```tsx
                    <td className="px-4 h-[46px] align-middle whitespace-nowrap text-(--muted)">
                      {lastOnlineLabel(r.last_online_at, new Date())}
                    </td>
```

- In the Status cell, before the existing status dot, add `{(r.likes_waiting ?? 0) > 0 ? <Badge tone="mod">Likes waiting</Badge> : null}` (import `Badge` from `@/components/admin/design-primitives`).

In `src/components/admin/user-drawer-activity.tsx`, add `import { Badge } from "@/components/admin/design-primitives";` and after the Last online row add:

```tsx
        <Row
          k="Push"
          v={p.push_devices == null ? null : (
            <Badge tone={p.push_devices > 0 ? (p.push_failing ? "pending" : "active") : "neutral"}>
              {p.push_devices > 0 ? "On" : "Off"}
            </Badge>
          )}
        />
```

- [ ] **Step 3: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no errors; the build completes.

- [ ] **Step 4: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" W.1,W.5` and fix what it reports.

```bash
git add src/components/admin/community-waiting.tsx src/components/admin/tab-users.tsx src/components/admin/user-drawer-activity.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(users): waiting on a reply, last online, a has likes waiting filter and push in the drawer" -m "Refs: TEC-1897"
```

---

### Task 20: Unfinished sign-ups

**Files:**
- Create: `src/components/admin/community-unfinished.tsx`
- Modify: `src/components/admin/tab-users.tsx` (the `view` switch)

**Interfaces:**
- Consumes: `useUnfinished` (Task 16); `dayMonth`, `stepLabel` (Task 15).
- Produces: `CommunityUnfinished()`; the Users tab renders it when `?view=unfinished`.

Frames U.1 to U.4: loaded (Started, Last saved, Furthest step, a disabled "Send a reminder" and its locked line), empty ("No unfinished sign-ups."), loading, error ("Could not load unfinished sign-ups." with "Try again"). No name or address is shown or sent.

- [ ] **Step 1: Write the view**

Create `src/components/admin/community-unfinished.tsx`:

```tsx
"use client";

import { AlertCircle, Lock } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { AdminCard, PageHead, Td, Th, Tr } from "@/components/admin/design-primitives";
import { growthBtn } from "@/components/admin/growth-dialogs";
import { dayMonth, stepLabel } from "@/lib/community";
import { useUnfinished } from "@/lib/queries";

/**
 * Unfinished sign-ups (TEC-1897; frames U.1 to U.4): when they started,
 * when they last saved and the furthest step the server recorded. The
 * reminder stays off until the owner approves it and its words.
 */
export function CommunityUnfinished() {
  const { data, isLoading, isError, refetch } = useUnfinished();
  const remind = <button type="button" className={growthBtn("ghost", "sm")} disabled>Send a reminder</button>;

  let body;
  if (isLoading) body = <Skeleton className="h-10 w-full" />;
  else if (isError) {
    body = (
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex gap-1.5 items-center text-[13px] font-semibold text-(--red)"><AlertCircle size={15} />Could not load unfinished sign-ups.</span>
        <button type="button" className={growthBtn("ghost", "sm")} onClick={() => refetch()}>Try again</button>
      </div>
    );
  } else if (!data || data.rows.length === 0) {
    body = <p className="text-[13.5px] text-(--muted) m-0">No unfinished sign-ups.</p>;
  } else {
    body = (
      <>
        <div className="md:hidden flex flex-col">
          {data.rows.map((r, i) => (
            <div key={i} className="flex flex-col gap-1 py-3 border-b border-(--line) last:border-b-0 text-[12.5px]">
              <b className="text-[14px]">{dayMonth(r.started_at)}</b>
              <div className="flex justify-between"><span className="text-(--faint)">Last saved</span><span>{dayMonth(r.last_saved_at)}</span></div>
              <div className="flex justify-between"><span className="text-(--faint)">Furthest step</span><span>{stepLabel(r.furthest_step)}</span></div>
              <div className="pt-1">{remind}</div>
            </div>
          ))}
        </div>
        <table className="max-md:hidden w-full border-collapse text-[13.5px]">
          <thead><tr><Th>Started</Th><Th>Last saved</Th><Th>Furthest step</Th><Th> </Th></tr></thead>
          <tbody>
            {data.rows.map((r, i) => (
              <Tr key={i}>
                <Td>{dayMonth(r.started_at)}</Td>
                <Td>{dayMonth(r.last_saved_at)}</Td>
                <Td>{stepLabel(r.furthest_step)}</Td>
                <Td className="text-right">{remind}</Td>
              </Tr>
            ))}
          </tbody>
        </table>
        <span className="flex items-center gap-1.5 pt-2.5 text-[12px] text-(--faint)">
          <Lock size={13} />Off until the owner approves a reminder and its words.
        </span>
      </>
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      <PageHead title="Unfinished sign-ups" sub="People who started sign-up and stopped" />
      <AdminCard title="Unfinished sign-ups">{body}</AdminCard>
    </div>
  );
}
```

In `src/components/admin/tab-users.tsx`, add `import { CommunityUnfinished } from "@/components/admin/community-unfinished";` and, in the `TabUsers` wrapper Task 19 added, after `if (view === "waiting") return <CommunityWaiting />;` add `if (view === "unfinished") return <CommunityUnfinished />;`.

- [ ] **Step 2: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no errors.

- [ ] **Step 3: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" U.1,U.2,U.3,U.4` and fix what it reports.

```bash
git add src/components/admin/community-unfinished.tsx src/components/admin/tab-users.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(users): unfinished sign-ups, with the reminder off" -m "Refs: TEC-1897"
```

---

### Task 21: The weekly funnel on Overview

**Files:**
- Create: `src/components/admin/weekly-funnel.tsx`
- Modify: `src/components/admin/tab-overview.tsx` (after `<NeedsYouBand />`)

**Interfaces:**
- Consumes: `useFunnel` (Task 16); `weekOfLabel`, `funnelLatestLine` (Task 15).
- Produces: `WeeklyFunnel()`.

Frame O.1. Desktop and tablet: the export's bar chart, one bar of Likes per week with its value above it, the week under it, and the warn-coloured mark for first messages and replies beside each bar, scaled with the likes; the legend's "Likes" and the line `funnelLatestLine`. Every week is measured now, so the export's hatched placeholders and its "Not measured" legend item and caption, which described the review's gaps, are not drawn. Matches are not drawn in the chart because the export has no mark for them (conflict listed). A phone: the export's rows for the latest 3 weeks, "Week of 5 Oct" with Likes, Matches, First messages and Replies, all four measured. The panel sits full width under the band, the export's 768 row; the export's 1440 row also moves Sign-ups by source and Recent activity beside it, which is listed as a conflict rather than done here.

- [ ] **Step 1: Write the panel**

Create `src/components/admin/weekly-funnel.tsx`:

```tsx
"use client";

import { AlertCircle, BarChart3 } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { AdminCard } from "@/components/admin/design-primitives";
import { growthBtn } from "@/components/admin/growth-dialogs";
import { funnelLatestLine, weekOfLabel } from "@/lib/community";
import { useFunnel } from "@/lib/queries";

const H = 150;

/** Weekly funnel (TEC-1897; frame O.1): likes, matches, first messages and
 *  replies per Barbados week, 12 weeks. */
export function WeeklyFunnel() {
  const { data, isLoading, isError, refetch } = useFunnel();
  const weeks = data?.weeks ?? [];
  const max = Math.max(1, ...weeks.map((w) => Math.max(w.likes, w.first_messages + w.replies)));

  if (isError) {
    return (
      <AdminCard title="Weekly funnel">
        <div className="flex flex-wrap items-center gap-3 mt-2">
          <span className="flex gap-1.5 items-center text-[13px] font-semibold text-(--red)"><AlertCircle size={15} />Could not load this count.</span>
          <button type="button" className={growthBtn("ghost", "sm")} onClick={() => refetch()}>Try again</button>
        </div>
      </AdminCard>
    );
  }

  return (
    <AdminCard title="Weekly funnel" className="mb-[22px]">
      {isLoading ? <Skeleton className="h-[180px] w-full mt-2" /> : (
        <>
          {/* A phone: the latest weeks as rows. */}
          <div className="md:hidden flex flex-col">
            {weeks.slice(-3).reverse().map((w) => (
              <div key={w.week_start} className="flex flex-col gap-1 py-2.5 border-t border-(--line) first:border-t-0">
                <b className="text-[13.5px]">Week of {weekOfLabel(w.week_start)}</b>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[12.5px]">
                  <span>Likes <b>{w.likes}</b></span>
                  <span>Matches <b>{w.matches}</b></span>
                  <span>First messages <b>{w.first_messages}</b></span>
                  <span>Replies <b>{w.replies}</b></span>
                </div>
              </div>
            ))}
          </div>
          {/* Tablet and desktop: likes as bars, first messages and replies as
              the warn mark beside each bar. */}
          <div className="max-md:hidden flex flex-col gap-2.5">
            <div className="flex flex-wrap gap-3.5 text-[11.5px] text-(--faint)">
              <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-(--lavender)" />Likes</span>
              <span className="flex items-center gap-1.5"><i className="inline-block h-[3px] w-2.5 bg-(--amber)" />{funnelLatestLine(weeks)}</span>
            </div>
            <div className="flex gap-1 pt-[18px]">
              {weeks.map((w) => {
                const talk = w.first_messages + w.replies;
                return (
                  <div key={w.week_start} className="flex-1 min-w-0 flex flex-col items-center gap-1.5">
                    <div className="flex items-end gap-[3px]" style={{ height: H }}>
                      <div className="relative w-5 lg:w-[30px] rounded-t-[6px] bg-(--lavender)" style={{ height: Math.max(2, (w.likes / max) * H) }}>
                        <span className="absolute -top-[18px] inset-x-0 text-center text-[11.5px] font-extrabold">{w.likes}</span>
                      </div>
                      <div className="w-2.5 lg:w-[15px] bg-(--amber)" style={{ height: Math.max(3, (talk / max) * H) }} />
                    </div>
                    <span className="text-[10.5px] text-(--faint) whitespace-nowrap">{weekOfLabel(w.week_start)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </AdminCard>
  );
}
```

In `src/components/admin/tab-overview.tsx`, add `import { WeeklyFunnel } from "@/components/admin/weekly-funnel";` and directly after `<NeedsYouBand />` add `<WeeklyFunnel />`.

- [ ] **Step 2: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no errors.

- [ ] **Step 3: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" O.1` limited to the funnel tile, and fix what it reports in `weekly-funnel.tsx`.

```bash
git add src/components/admin/weekly-funnel.tsx src/components/admin/tab-overview.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(overview): the weekly funnel of likes and conversations" -m "Refs: TEC-1897"
```

---

### Task 22: Growth: push, verification tiers, came back, push turned on, the 7 day toggle and run history

**Files:**
- Create: `src/components/admin/growth-push-tiers.tsx`
- Create: `src/components/admin/growth-run-history.tsx`
- Modify: `src/components/admin/growth-emails.tsx`
- Modify: `src/components/admin/tab-growth.tsx` (after `<GrowthStats />`)

**Interfaces:**
- Consumes: `usePush`, `useTiers`, `useEmailRuns` (Task 16); `pushLine`, `tierLabel`, `cameBack`, `pushTurnedOn`, `startedByLabel`, `last30Line`, `dayMonth` (Task 15); `Sheet`, `SheetContent` (`src/components/ui/sheet.tsx`).
- Produces: `GrowthPushTiers()`; `RunHistorySheet({ campaign, name, onClose })`.

Frames G.1, G.2, G.4 and G.7. The Push tile: the count, `pushLine(members)`, then "Counting staff accounts", "Failing", "New since 1 Oct" and "New per week" ("Not measured"). Verification tiers: the stacked bar and the four counts in the export's colours. Emails gain "Came back" and "Push turned on" ("Not this email" where null) and the segmented "Came back: any time" / "Within 7 days" toggle; a null 7 day figure reads "Not measured". System emails gain "Clicks" ("Not measured") and "Came back". Each admin-run row's name opens its run history sheet. The footnote "Came back counts anyone online since the send. The email may not have caused it." replaces the current caption's second sentence.

- [ ] **Step 1: Write the tiles and the sheet**

Create `src/components/admin/growth-push-tiers.tsx`:

```tsx
"use client";

import { Bell, Shield } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { AdminCard } from "@/components/admin/design-primitives";
import { dayMonth, pushLine, tierLabel } from "@/lib/community";
import { usePush, useTiers } from "@/lib/growth-queries";

// The export's tier colours (frame G.1).
const TIER_COLOURS: Record<string, string> = { none: "var(--line-2)", bronze: "#CD7F32", silver: "#C0C0C0", gold: "#E5B800" };

/** Push and verification tiers (TEC-1897; frame G.1), side by side from
 *  tablet up. */
export function GrowthPushTiers() {
  const push = usePush();
  const tiers = useTiers();
  const p = push.data;
  const t = tiers.data?.tiers ?? [];
  const total = Math.max(1, t.reduce((s, x) => s + x.members, 0));
  const notMeasured = <span className="italic text-(--faint)">Not measured</span>;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 mb-[22px] items-stretch">
      <AdminCard title="Push">
        {!p ? <Skeleton className="h-24 w-full mt-2" /> : (
          <div className="flex flex-col gap-2 mt-1">
            <div className="flex items-baseline gap-2.5">
              <span className="text-[30px] font-extrabold leading-none tabular-nums">{p.members_with_push}</span>
              <span className="text-[13px] text-(--muted)">{pushLine(p.members)}</span>
            </div>
            <div className="flex flex-col gap-1.5 text-[13px]">
              <div className="flex justify-between"><span>Counting staff accounts</span><b>{p.with_push_counting_staff}</b></div>
              <div className="flex justify-between"><span>Failing</span><b>{p.members_failing}</b></div>
              <div className="flex justify-between"><span>New since {dayMonth(`${p.since}T12:00:00Z`)}</span><b>{p.members_new_since}</b></div>
              <div className="flex justify-between"><span>New per week</span>{notMeasured}</div>
            </div>
          </div>
        )}
      </AdminCard>
      <AdminCard title="Verification tiers">
        {!tiers.data ? <Skeleton className="h-24 w-full mt-2" /> : (
          <div className="flex flex-col gap-2.5 mt-1">
            <div className="flex h-3.5 rounded-full overflow-hidden gap-0.5">
              {t.map((x) => <div key={x.tier} style={{ flex: x.members / total, background: TIER_COLOURS[x.tier] }} />)}
            </div>
            <div className="grid grid-cols-2 gap-x-3.5 gap-y-1.5 text-[13px]">
              {t.map((x) => (
                <div key={x.tier} className="flex justify-between">
                  <span className="flex items-center gap-2"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: TIER_COLOURS[x.tier] }} />{tierLabel(x.tier)}</span>
                  <b>{x.members}</b>
                </div>
              ))}
            </div>
          </div>
        )}
      </AdminCard>
    </div>
  );
}
```

(`Bell` and `Shield` are the export's card-head icons; `/sot-sync` places them.)

Create `src/components/admin/growth-run-history.tsx`:

```tsx
"use client";

import { X } from "lucide-react";

import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Td, Th, Tr } from "@/components/admin/design-primitives";
import { dayMonth, last30Line, startedByLabel } from "@/lib/community";
import { useEmailRuns } from "@/lib/growth-queries";

/** Run history (TEC-1897; frame G.4). */
export function RunHistorySheet({
  campaign, name, win, onClose,
}: { campaign: string | null; name: string; win: "any" | "7"; onClose: () => void }) {
  const runs = useEmailRuns(campaign);
  const nm = <span className="italic text-(--faint)">Not measured</span>;
  const back = (v: number | null) => (v == null ? nm : v);
  return (
    <Sheet open={!!campaign} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="w-[760px] max-w-[100vw] p-[22px] flex flex-col gap-3.5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[18px] font-extrabold m-0">{name}</h2>
            <span className="text-[12px] text-(--faint)">Run history</span>
          </div>
          <button type="button" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </div>
        {runs.isLoading || !runs.data ? <Skeleton className="h-24 w-full" /> : (
          <>
            <div className="md:hidden flex flex-col">
              {runs.data.runs.map((r) => (
                <div key={r.campaign_id} className="flex flex-col gap-1 py-3 border-b border-(--line) text-[12.5px]">
                  <b className="text-[14px]">{dayMonth(r.sent_at)}</b>
                  <div className="flex justify-between"><span className="text-(--faint)">Campaign id</span><span className="font-mono text-[12px]">{r.campaign_id}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Started by</span><span>{startedByLabel(r.started_by)}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Reached</span><span>{r.reached}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Clicks</span><span>{r.clicks ?? nm}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Came back</span><span>{back(win === "7" ? r.came_back_7d : r.came_back)}</span></div>
                </div>
              ))}
            </div>
            <table className="max-md:hidden w-full border-collapse text-[13.5px]">
              <thead><tr><Th>Date</Th><Th>Campaign id</Th><Th>Started by</Th><Th>Reached</Th><Th>Clicks</Th><Th>Came back</Th></tr></thead>
              <tbody>
                {runs.data.runs.map((r) => (
                  <Tr key={r.campaign_id}>
                    <Td>{dayMonth(r.sent_at)}</Td>
                    <Td><span className="font-mono text-[12px]">{r.campaign_id}</span></Td>
                    <Td>{startedByLabel(r.started_by)}</Td>
                    <Td className="tabular-nums">{r.reached}</Td>
                    <Td className="tabular-nums">{r.clicks ?? nm}</Td>
                    <Td className="tabular-nums">{back(win === "7" ? r.came_back_7d : r.came_back)}</Td>
                  </Tr>
                ))}
              </tbody>
            </table>
            <span className="text-[12px] text-(--faint)">{last30Line(runs.data.last_30_days)}</span>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 2: Extend the emails table**

In `src/components/admin/growth-emails.tsx`:
- Imports: add `import { cameBack, pushTurnedOn } from "@/lib/community";` and `import { RunHistorySheet } from "@/components/admin/growth-run-history";`.
- Replace the docstring paragraph that begins "The design's Came back and Push turned on columns" with: `Came back counts recipients online since their send (any time, or within 7 days where the per-day record covers the run); push turned on is the notifications email's own measure; each row's name opens its run history (TEC-1897; G.1, G.2, G.4).`
- In `GrowthEmails`, add state `const [win, setWin] = useState<"any" | "7">("any");` and `const [history, setHistory] = useState<EmailCampaign | null>(null);`.
- Add helpers above `GrowthEmails`:

```tsx
function back(c: EmailCampaign, win: "any" | "7"): ReactNode {
  const v = cameBack(c, win);
  return v == null ? <NotMeasured /> : v;
}

function pushOn(c: EmailCampaign): ReactNode {
  return pushTurnedOn(c) ?? <span className="text-(--faint)">Not this email</span>;
}

function WindowToggle({ win, setWin }: { win: "any" | "7"; setWin: (w: "any" | "7") => void }) {
  const opt = (w: "any" | "7", label: string) => (
    <button
      type="button"
      aria-pressed={win === w}
      onClick={() => setWin(w)}
      className={win === w ? "px-3 h-8 rounded-[8px] bg-(--card-3) text-(--ink) font-bold" : "px-3 h-8 rounded-[8px] text-(--muted)"}
    >
      {label}
    </button>
  );
  return (
    <div className="inline-flex gap-1 p-1 rounded-[10px] border border-(--line-2) text-[12.5px]">
      {opt("any", "Came back: any time")}
      {opt("7", "Within 7 days")}
    </div>
  );
}
```

- Put `<WindowToggle win={win} setWin={setWin} />` beside the section label: wrap the existing `{label}` in the final return as `<div className="flex flex-wrap items-center justify-between gap-2.5">{label}<WindowToggle win={win} setWin={setWin} /></div>`.
- Desktop admin-run table: after `<Th>Clicks</Th>` add `<Th>Came back</Th>` and `<Th>Push turned on</Th>`; after the clicks cell add `<Td className="tabular-nums">{back(c, win)}</Td>` and `<Td className="tabular-nums">{pushOn(c)}</Td>`; make the name cell a button: replace `<Td className="font-bold text-(--ink)">{NAMES[c.campaign] ?? c.campaign}</Td>` with `<Td><button type="button" className="font-bold text-(--ink) hover:underline" onClick={() => setHistory(c)}>{NAMES[c.campaign] ?? c.campaign}</button></Td>`.
- System table: after `<Th>Sent, all time</Th>` add `<Th>Clicks</Th>` and `<Th>Came back</Th>`; after its sent cell add `<Td><NotMeasured /></Td>` and `<Td className="tabular-nums">{c.came_back ?? <NotMeasured />}</Td>`.
- Phone rows: after `<Pair label="Clicks">{clicks(c)}</Pair>` add `<Pair label="Came back">{back(c, win)}</Pair>` and `<Pair label="Push turned on">{pushOn(c)}</Pair>`; in the system rows after the sent pair add `<Pair label="Came back">{c.came_back ?? <NotMeasured />}</Pair>`; make the phone row's name open the history the same way.
- Both captions (desktop and phone): replace `Last run reached and clicks are for each email&apos;s last run. Clicks leave bots out.` with `Last run reached and clicks are for each email&apos;s last run. Clicks leave bots out. Came back counts anyone online since the send. The email may not have caused it.`
- The error state's title already reads "Could not load email results." (G.7); keep it.
- After `<SendEmailDialog ... />` add:

```tsx
      <RunHistorySheet
        campaign={history?.campaign ?? null}
        name={history ? (NAMES[history.campaign] ?? history.campaign) : ""}
        win={win}
        onClose={() => setHistory(null)}
      />
```

In `src/components/admin/tab-growth.tsx`, add `import { GrowthPushTiers } from "@/components/admin/growth-push-tiers";` and after `<GrowthStats />` add `<GrowthPushTiers />`.

- [ ] **Step 3: Run the tests, the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/growth-labels.test.mjs tests/community.test.mjs && npx tsc --noEmit && pnpm build`
Expected: tests pass; no type errors; the build completes.

- [ ] **Step 4: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" G.1,G.2,G.4,G.6,G.7` limited to the Push, Verification tiers and Emails tiles, and fix what it reports.

```bash
git add src/components/admin/growth-push-tiers.tsx src/components/admin/growth-run-history.tsx src/components/admin/growth-emails.tsx src/components/admin/tab-growth.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): push, verification tiers, who came back and each email's run history" -m "Refs: TEC-1897"
```

---

### Task 23: Moderation: profile gaps, approved with no face and the photo gate list

**Files:**
- Modify: `src/components/admin/tab-moderation.tsx` (`SUBS`, the `sub` switch, `PhotosView`; new `ProfileGapsView` and `PhotoGateView`)
- Modify: `src/components/admin/needs-you.tsx` (the gate tile's `href`)

**Interfaces:**
- Consumes: `useProfileGaps`, `usePhotoGate`, `useModerationPhotos(state)` (Task 16); `gapStrip`, `gapLabel`, `tierLabel`, `noFaceLine`, `lastOnlineLabel`, `photoWaiting` (Task 15).
- Produces: sub-tabs Reports, Photos, Messages, Profile gaps (the export's order); `?sub=gate` renders the gate list, which has no sub-tab of its own in the export and is reached from the Needs you tile.

Frames P.1, P.2 and P.3. Photos gains the export's filter pills "Pending", "Manual review" and "Approved, no face"; the last asks for `state=approved_no_face`, shows `noFaceLine` and marks staff rows. Profile gaps: the four-figure strip and the Member, Gap, Verification list; each name opens the drawer. The gate list: Member, "Likes sent / received", Matches, Messages, "Profile views, 30 days", Last online, Photo waiting, and "Open photo" linking the waiting photo.

- [ ] **Step 1: Write the views**

In `src/components/admin/tab-moderation.tsx`:
- Replace `SUBS` with:

```tsx
const SUBS = [
  { key: "reports",  label: "Reports" },
  { key: "photos",   label: "Photos" },
  { key: "messages", label: "Messages" },
  { key: "gaps",     label: "Profile gaps" },
] as const;
type Sub = typeof SUBS[number]["key"] | "gate";
```

- Pass `value={sub === "gate" ? "photos" : sub}` to `SubTabs`, and after `{sub === "messages" ? <MessagesView /> : null}` add:

```tsx
      {sub === "gaps"     ? <ProfileGapsView /> : null}
      {sub === "gate"     ? <PhotoGateView />   : null}
```

- Add imports: `useProfileGaps, usePhotoGate` to the queries import; `import { gapLabel, gapStrip, lastOnlineLabel, noFaceLine, photoWaiting, tierLabel } from "@/lib/community";`.
- In `PhotosView`, add a filter state and pills before the KPI strip:

```tsx
  const [filter, setFilter] = useState<"queue" | "pending" | "manual_review" | "approved_no_face">("queue");
```

change its query to `useModerationPhotos(filter)`, and render, above `<KpiStrip ...>`:

```tsx
      <div className="flex flex-wrap gap-2 mb-3">
        {([["pending", "Pending"], ["manual_review", "Manual review"], ["approved_no_face", "Approved, no face"]] as const).map(([k, l]) => (
          <button
            key={k}
            type="button"
            aria-pressed={filter === k}
            onClick={() => setFilter(filter === k ? "queue" : k)}
            className={cn("h-8 px-3 rounded-full border text-[12.5px] font-bold",
              filter === k ? "border-(--lavender) bg-(--lavender-soft) text-(--ink)" : "border-(--line-2) text-(--ink-2)")}
          >
            {l}
          </button>
        ))}
      </div>
      {filter === "approved_no_face" && data?.approved_no_face ? (
        <p className="text-[12.5px] text-(--faint) mb-3">{noFaceLine(data.approved_no_face)}</p>
      ) : null}
```

  and in each photo row's status badges add `{r.owner_is_staff ? <Badge tone="admin">Staff</Badge> : null}`. The "Staff" badge text is added (conflict listed); the export marks the staff photo only in the line above.
- Add, below `MessagesView`:

```tsx
/** Profile gaps (TEC-1897; frame P.2). */
function ProfileGapsView() {
  const { data, isLoading, isError } = useProfileGaps();
  const [openUuid, setOpenUuid] = useState<string | null>(null);
  if (isError) return <AdminCard><EmptyState title="Could not load this count." /></AdminCard>;
  return (
    <>
      {isLoading || !data ? <Skeleton className="h-[96px] w-full mb-3.5" /> : (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3.5 mb-3.5">
          {gapStrip(data.kpis).map(([v, l]) => (
            <div key={l} className="rounded-[16px] border border-(--line) bg-(--card) p-[16px_18px] flex md:flex-col items-baseline md:items-start gap-2.5 md:gap-1.5">
              <span className="text-[20px] md:text-[30px] font-extrabold leading-none tabular-nums">{v}</span>
              <span className="text-[13px] text-(--muted)">{l}</span>
            </div>
          ))}
        </div>
      )}
      <AdminCard title="Profile gaps">
        {isLoading || !data ? <Skeleton className="h-10 w-full mt-2" /> : (
          <>
            <div className="md:hidden flex flex-col">
              {data.rows.map((r) => (
                <div key={r.uuid} className="flex flex-col gap-1 py-3 border-b border-(--line) last:border-b-0 text-[12.5px]">
                  <button type="button" onClick={() => setOpenUuid(r.uuid)} className="text-left text-[14px] font-bold">{r.name || "Unknown member"}</button>
                  <div className="flex justify-between"><span className="text-(--faint)">Gap</span><span>{gapLabel(r.gap)}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Verification</span><span>{tierLabel(r.tier)}</span></div>
                </div>
              ))}
            </div>
            <table className="max-md:hidden w-full border-collapse text-[13.5px] mt-1">
              <thead><tr><Th>Member</Th><Th>Gap</Th><Th>Verification</Th></tr></thead>
              <tbody>
                {data.rows.map((r) => (
                  <Tr key={r.uuid}>
                    <Td><button type="button" onClick={() => setOpenUuid(r.uuid)} className="font-bold hover:underline">{r.name || "Unknown member"}</button></Td>
                    <Td>{gapLabel(r.gap)}</Td>
                    <Td>{tierLabel(r.tier)}</Td>
                  </Tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </AdminCard>
      {openUuid ? <UserDrawer uuid={openUuid} onClose={() => setOpenUuid(null)} /> : null}
    </>
  );
}

/** Members held by the photo gate (TEC-1897; frame P.1). */
function PhotoGateView() {
  const { data, isLoading, isError } = usePhotoGate();
  const [openUuid, setOpenUuid] = useState<string | null>(null);
  const now = new Date();
  if (isError) return <AdminCard><EmptyState title="Could not load this count." /></AdminCard>;
  const open = (uuid: string | null) => uuid ? (
    <a href={`${PHOTO_HOST}/900-${uuid}.jpg`} target="_blank" rel="noreferrer" className="text-[13px] font-bold text-(--lavender) min-h-8 inline-flex items-center">Open photo</a>
  ) : null;
  return (
    <>
      <PageHead title="Held by the photo gate" sub={data ? `${data.members.length} members` : undefined} />
      <AdminCard title="Members held by the photo gate">
        {isLoading || !data ? <Skeleton className="h-10 w-full mt-2" /> : (
          <>
            <div className="md:hidden flex flex-col">
              {data.members.map((m) => (
                <div key={m.uuid} className="flex flex-col gap-1 py-3 border-b border-(--line) last:border-b-0 text-[12.5px]">
                  <button type="button" onClick={() => setOpenUuid(m.uuid)} className="text-left text-[14px] font-bold">{m.name || "Unknown member"}</button>
                  <div className="flex justify-between"><span className="text-(--faint)">Likes sent / received</span><span>{m.likes_sent_30d} / {m.likes_received_30d}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Matches</span><span>{m.matches_30d}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Messages</span><span>{m.messages_30d}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Profile views, 30 days</span><span>{m.profile_views_30d}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Last online</span><span>{lastOnlineLabel(m.last_online_at, now)}</span></div>
                  <div className="flex justify-between"><span className="text-(--faint)">Photo waiting</span><span>{photoWaiting(m)}</span></div>
                  {open(m.waiting_photo_uuid)}
                </div>
              ))}
            </div>
            <table className="max-md:hidden w-full border-collapse text-[13.5px] mt-1">
              <thead><tr><Th>Member</Th><Th>Likes sent / received</Th><Th>Matches</Th><Th>Messages</Th><Th>Profile views, 30 days</Th><Th>Last online</Th><Th>Photo waiting</Th><Th> </Th></tr></thead>
              <tbody>
                {data.members.map((m) => (
                  <Tr key={m.uuid}>
                    <Td><button type="button" onClick={() => setOpenUuid(m.uuid)} className="font-bold hover:underline">{m.name || "Unknown member"}</button></Td>
                    <Td className="tabular-nums">{m.likes_sent_30d} / {m.likes_received_30d}</Td>
                    <Td className="tabular-nums">{m.matches_30d}</Td>
                    <Td className="tabular-nums">{m.messages_30d}</Td>
                    <Td className="tabular-nums">{m.profile_views_30d}</Td>
                    <Td className="whitespace-nowrap">{lastOnlineLabel(m.last_online_at, now)}</Td>
                    <Td className="whitespace-nowrap">{photoWaiting(m)}</Td>
                    <Td className="text-right">{open(m.waiting_photo_uuid)}</Td>
                  </Tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </AdminCard>
      {openUuid ? <UserDrawer uuid={openUuid} onClose={() => setOpenUuid(null)} /> : null}
    </>
  );
}
```

  (`PHOTO_HOST` is the constant `PhotosView` already uses in this file.) The page sub-line drops the export's "Activity columns were not measured in the review; placeholders shown.", which described the mock. "N members" is the export's own "4 members" with the live count.

In `src/components/admin/needs-you.tsx`, change the gate tile's `href: "/?tab=moderation&sub=photos"` to `href: "/?tab=moderation&sub=gate"`.

- [ ] **Step 2: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no errors.

- [ ] **Step 3: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" P.1,P.2,P.3` and fix what it reports.

```bash
git add src/components/admin/tab-moderation.tsx src/components/admin/needs-you.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(moderation): profile gaps, approved photos with no face and the photo gate list" -m "Refs: TEC-1897"
```

---

### Task 24: System: the API errors card

**Files:**
- Modify: `src/components/admin/tab-system.tsx:266-272` (the `API errors` card)

**Interfaces:**
- Consumes: `useApiErrors` (Task 16); `errorsState` (Task 15).

Frames E.1 to E.3: some errors (Last 24 hours, Last 7 days, then Route, Errors, Last failed), none ("No errors in the last 7 days" in green with a check) and unavailable ("Error counter unavailable" with the info icon). The export's caption "Values are placeholders. The route fails on every load today." described the mock and is not shown.

- [ ] **Step 1: Replace the card**

In `src/components/admin/tab-system.tsx`, add `Check, Info` to the lucide import, `useApiErrors` to the queries import and `import { errorsState } from "@/lib/community";` and `import { Skeleton } from "@/components/ui/skeleton";` if not imported. Replace:

```tsx
        <AdminCard title="API errors">
          <EmptyState
            title="Sentry not yet wired"
            hint="5xx counts and top failing endpoints will appear once the log pipeline exists."
            icon={<AlertTriangle size={18} />}
          />
        </AdminCard>
```

with `<ApiErrorsCard />`, and add below the tab component:

```tsx
/** API errors from the API's own counter (TEC-1897; frames E.1 to E.3). */
function ApiErrorsCard() {
  const q = useApiErrors();
  const state = errorsState(q, q.data);
  return (
    <AdminCard title="API errors">
      {state === "loading" ? <Skeleton className="h-20 w-full mt-2" /> : state === "na" ? (
        <span className="flex items-center gap-2 font-bold text-(--ink-2) mt-2"><Info size={17} />Error counter unavailable</span>
      ) : state === "none" ? (
        <span className="flex items-center gap-2 font-bold text-(--green) mt-2"><Check size={17} />No errors in the last 7 days</span>
      ) : (
        <div className="flex flex-col gap-3 mt-2">
          <div className="flex gap-6">
            <div><span className="text-[30px] font-extrabold leading-none tabular-nums">{q.data!.last_24h}</span><div className="text-[11.5px] text-(--faint)">Last 24 hours</div></div>
            <div><span className="text-[30px] font-extrabold leading-none tabular-nums">{q.data!.last_7d}</span><div className="text-[11.5px] text-(--faint)">Last 7 days</div></div>
          </div>
          <div className="md:hidden flex flex-col">
            {q.data!.routes.map((r) => (
              <div key={r.route} className="flex flex-col gap-1 py-2.5 border-t border-(--line) text-[12.5px]">
                <span className="font-mono text-[12px] break-all">{r.route}</span>
                <div className="flex justify-between"><span className="text-(--faint)">Errors</span><span>{r.errors}</span></div>
                <div className="flex justify-between"><span className="text-(--faint)">Last failed</span><span>{activityStamp(r.last_failed_at, new Date())}</span></div>
              </div>
            ))}
          </div>
          <table className="max-md:hidden w-full border-collapse text-[13.5px]">
            <thead><tr><Th>Route</Th><Th>Errors</Th><Th>Last failed</Th></tr></thead>
            <tbody>
              {q.data!.routes.map((r) => (
                <Tr key={r.route}>
                  <Td><span className="font-mono text-[12px]">{r.route}</span></Td>
                  <Td className="tabular-nums">{r.errors}</Td>
                  <Td className="whitespace-nowrap">{activityStamp(r.last_failed_at, new Date())}</Td>
                </Tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AdminCard>
  );
}
```

Import `activityStamp` from `@/lib/acting` ("Today, 09:12" or "20 Sep, 05:05", the Recent activity format) and `Th`, `Td`, `Tr` from the design primitives if the file does not already. Remove `AlertTriangle` from the imports if nothing else uses it.

- [ ] **Step 2: Run the type check and build**

Run: `cd /d/Antigravity/ahavah-admin && npx tsc --noEmit && pnpm build`
Expected: no errors.

- [ ] **Step 3: Transcribe and commit**

Run `/sot-sync "D:/Antigravity/ahavah-web/Claude Design/Ahavah Admin Acting on the Community.html" E.1,E.2,E.3` and fix what it reports.

```bash
git add src/components/admin/tab-system.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(system): the API errors card from the API's own counter" -m "Refs: TEC-1897"
```

---

### Task 25: Rendered proof at 390, 768 and 1440, light and dark

**Files:**
- Create: `tests/_evidence/design-wave-2-shots.mjs`

**Interfaces:**
- Consumes: the harness of `tests/_evidence/design-wave-1-shots.mjs` (a stub API on 127.0.0.1:5000, playwright-core, the installed Chrome with a fresh profile).

- [ ] **Step 1: Write the script**

Copy `tests/_evidence/design-wave-1-shots.mjs` to `tests/_evidence/design-wave-2-shots.mjs`. Keep its fixtures (`ago`, `HEALTH`, `OVERVIEW_STUB`, `GROWTH_REST`, `QUEUE`, `REPORTS_ONE`, `PHOTOS`), the stub server and `shot()`. The wave 1 stub has no route table: each `shot()` call passes its own `stub` map from a path (the query string is dropped) to a body, and its `query` is the part after `/?`. Change the header comment to name TEC-1897 and the frames below, delete every shot loop between `const THEMES = ["light", "dark"];` and `await chrome.close();`, and put this in their place (sample figures are the export's mock values, so a screenshot can be laid beside its frame; they never reach production):

```js
// --- TEC-1897: the community views -------------------------------------------

const COMMUNITY_STUBS = {
  "/admin/community/waiting": { summary: {
    likes_waiting: 58, members_with_likes: 20, oldest_like_at: "2026-06-17T15:00:00+00:00", offline_7d: 14, push_on: 4,
    with_5_or_more: 6, with_2_to_4: 6, with_1: 8, conversations: 6, one_sided: 3,
    oldest_unanswered_at: "2026-07-19T15:00:00+00:00", matches: 7, silent_matches_7d: 1 },
    members: [
      { uuid: "u1", name: "Sample member", likes_waiting: 5, unanswered_openers: 0, silent_matches: 0,
        oldest_wait_at: "2026-06-17T15:00:00+00:00", last_online_at: "2026-09-30T15:00:00+00:00", push_on: false },
    ] },
  "/admin/community/unfinished": { count: 1, rows: [{ started_at: "2026-10-08T15:00:00+00:00", last_saved_at: "2026-10-08T15:05:00+00:00", furthest_step: "none" }] },
  "/admin/community/funnel": { weeks: Array.from({ length: 12 }, (_, i) => ({
    week_start: new Date(Date.UTC(2026, 6, 20 + 7 * i)).toISOString().slice(0, 10),
    likes: [0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 15, 18][i], matches: 0, first_messages: 0, replies: 0 })) },
  "/admin/growth/push": { members: 58, members_with_push: 11, with_push_counting_staff: 13, members_failing: 0, members_new_since: 2, since: "2026-10-01" },
  "/admin/growth/tiers": { tiers: [{ tier: "none", members: 31 }, { tier: "bronze", members: 6 }, { tier: "silver", members: 8 }, { tier: "gold", members: 13 }] },
  "/admin/growth/emails/e2/runs": { runs: [
    { campaign_id: "weekly-2026-10-12", sent_at: "2026-10-12T22:30:00+00:00", started_by: "schedule", reached: 50, clicks: 0, came_back: 5, came_back_7d: null },
    { campaign_id: "weekly-2026-10-05", sent_at: "2026-10-05T22:30:00+00:00", started_by: "schedule", reached: 3, clicks: 0, came_back: 0, came_back_7d: null },
  ], last_30_days: { sends: 53, people: 50, came_back: 5 } },
  "/admin/moderation/profile-gaps": { kpis: { not_verified: 31, only_declined: 3, no_photo: 1, no_face_photo: 4 },
    rows: [{ uuid: "u2", name: "Sample member", gap: "only_declined", tier: "none" }] },
  "/admin/moderation/photo-gate": { enabled: false, members: [] },
  "/admin/moderation/photos": { ...PHOTOS(4), approved_no_face: { photos: 6, people: 5, members: 4, staff: 1 } },
  "/admin/system/errors": { available: true, last_24h: 0, last_7d: 0, routes: [] },
  "/admin/alerts/report": { enabled: false, switch_on: false },
};

// One unresolved report and one resolved (frames R.2 and R.4).
const REPORTS_W2 = {
  count: 2, unresolved: 1,
  reports: [
    { ...REPORTS_ONE.reports[0], report_key: "1-2-20261015140000000000",
      outcome: null, note: null, resolved_at: null, resolved_by_name: null },
    { ...REPORTS_ONE.reports[0], report_key: "3-4-20261012140000000000", reporter_uuid: "u-3", reported_uuid: "u-4",
      outcome: "warned", note: "Spoke to them", resolved_at: ago(5), resolved_by_name: "Sarah" },
  ],
};

// Frame W.5: one Users row with Last online and Likes waiting.
const USERS_W2 = { page: 1, page_size: 20, total: 1, rows: [{
  email: "sample@example.com", uuid: "u1", name: "Sample member", sign_up_time: ago(40), roles: [], entitlements: [],
  activated: true, in_beta: false, in_waitlist: false, has_person: true, unsubscribed_at: null,
  last_online_at: ago(9), likes_waiting: 5 }] };

const STUB_W2 = {
  ...OVERVIEW_STUB, ...GROWTH_REST, ...COMMUNITY_STUBS,
  "/admin/reports": REPORTS_W2, "/admin/users": USERS_W2, "/admin/system/health": HEALTH,
};

const SIZES_W2 = [
  { tag: "390", width: 390, height: 844 },
  { tag: "768", width: 768, height: 1024 },
  { tag: "1440", width: 1440, height: 900 },
];

const PAGES = [
  ["overview", "tab=overview"],
  ["growth", "tab=growth"],
  ["reports", "tab=moderation&sub=reports"],
  ["photos", "tab=moderation&sub=photos"],
  ["profile-gaps", "tab=moderation&sub=gaps"],
  ["photo-gate", "tab=moderation&sub=gate"],
  ["users", "tab=users"],
  ["waiting", "tab=users&view=waiting"],
  ["unfinished", "tab=users&view=unfinished"],
  ["system", "tab=system"],
];

for (const [name, query] of PAGES) {
  for (const size of SIZES_W2) {
    for (const theme of THEMES) {
      await shot(`${name}-${size.tag}-${theme}`, { query, ...size, theme, stub: STUB_W2 });
    }
  }
}

// Frame G.4: the run history sheet, opened from the weekly email's name.
for (const size of SIZES_W2) {
  await shot(`growth-run-history-${size.tag}-light`, {
    query: "tab=growth", ...size, theme: "light", stub: STUB_W2, fullPage: false,
    before: async (page) => {
      await page.getByRole("button", { name: "Weekly community email" }).first().click();
      await page.waitForTimeout(400);
    },
  });
}
```

The script keeps wave 1's closing lines, which print any page with horizontal overflow.

- [ ] **Step 2: Run it**

Run (two shells):

```bash
cd /d/Antigravity/ahavah-admin && AHAVAH_API_ORIGIN=http://127.0.0.1:5000 npx next dev -p 3101
cd /d/Antigravity/ahavah-admin && node tests/_evidence/design-wave-2-shots.mjs http://localhost:3101 "C:/Users/Ehud/AppData/Local/Temp/tec-1897-shots"
```

Expected: 63 screenshots and the closing line "no horizontal overflow". Open each beside its frame in `Ahavah Admin Acting on the Community.html`. At 390 nothing scrolls sideways (check `document.documentElement.scrollWidth <= 390` in each 390 shot, which the wave 1 script already asserts) and the Needs you band is on the first screen without a scroll. At 768 and 1440 every row of tiles is full width and level.

- [ ] **Step 3: Commit**

```bash
git add tests/_evidence/design-wave-2-shots.mjs
git -c user.email=admin@techbaseltd.com commit -m "test(evidence): render the community views at 390, 768 and 1440" -m "Refs: TEC-1897"
```

---

## Deploy order

### Task 26: Ship the API dark, then the admin

Nothing here runs without the owner's go. Pushing `ahavah/main` deploys production.

- [ ] **Step 1: Review and copy pass before anything ships**

Run `/copy-pass` (ux-writing) on every line listed under "Spec conflicts and decisions needing the owner", item 13, and put the result in front of the owner with the decisions list. Run superpowers:requesting-code-review on both branches.

- [ ] **Step 2: API, additive and dark**

With the owner's go, merge `admin-community-data` into `ahavah/main` in ahavah-api and push `origin ahavah/main`. The deploy applies 0069 before it recreates api, chat and cron. Every new route is read-only or admin-only; both alert switches default to 0; the adminalerts cron sends nothing while they are off, and prunes only its own two new tables. Presence starts writing `member_online_day` and the error tally starts counting at once: this is the start of the 7 day record.

- [ ] **Step 3: Verify in production with counts only**

Signed in to admin.ahavah.app as the owner's admin account, open each endpoint through the existing admin (old build) or with the browser's network panel, and read counts only: `GET /api/admin/community/waiting` summary, `/api/admin/community/unfinished` count, `/api/admin/community/funnel`, `/api/admin/growth/push`, `/api/admin/growth/tiers`, `/api/admin/moderation/profile-gaps` kpis, `/api/admin/system/errors`. Compare the summary figures with the brief's 13 Oct figures as a sanity check (they will have moved). Do not copy any name, address or row into notes, Linear or chat.

- [ ] **Step 4: Proofs, then the switches**

On the server: `docker compose exec api python -m scripts.send_admin_alert_proofs --send`. When the owner confirms each proof, set `AHAVAH_STALE_POST_ALERT_ENABLED=1` and, if he wants it, `AHAVAH_REPORT_ALERT_ENABLED=1` in `.env.production`, then recreate api and cron. The report email also needs his "Email me when a report arrives" switch in the admin.

- [ ] **Step 5: Admin**

Merge `admin-community-data` into `master` in ahavah-admin and push; Vercel deploys. The admin reads every new field defensively (a missing field shows the tile's failed or "Not measured" state), so if the order ever reverses the old API leaves tiles failed, not wrong.

- [ ] **Step 6: Check the live admin**

On the owner's phone at 390 and on a desktop: each Needs you tile opens its list; Reports resolves on desktop and shows "Needs a desktop" on a phone; Growth shows Push, Verification tiers and the new email columns; Moderation shows Profile gaps, Approved, no face and the gate list; System shows the API errors card. Then run `/linear-sync` and record TEC-1897's state.

---

## Spec conflicts and decisions needing the owner

Each item says what the design or brief asks, what the database can honestly give, what this plan does by default and what it needs from the owner.

1. **Report outcomes.** The design offers Dismissed, Warned and Deactivated (R.3, tagged as the owner's decision). The plan records the outcome only: choosing "Deactivated" does not deactivate the member, the drawer's Deactivate action does. Decide the outcomes, and whether "Deactivated" should also deactivate.
2. **Who may resolve.** Admins and mods can read reports today. The plan lets only the admin role resolve. Decide whether mods may.
3. **"Email me when a report arrives".** The design draws a switch (R.2, "Owner decision: on or off"). The plan stores it, off by default, and the email also needs `AHAVAH_REPORT_ALERT_ENABLED`. The export has no frame for the email and no state for "the server switch is off". The email names nobody and quotes no reason. Approve the email's lines (item 13) and say whether you want it at all.
4. **Where owner alerts go.** The plan sends to `harrigan.tennyson@gmail.com`, the address every proof goes to. The existing admin notices (new waitlist sign-ups, `emails/waitlist_admin.py`) go to `admin@techbaseltd.com`. Confirm the address.
5. **The stale-post alert.** G.8 is tagged "daily email, 24 hours" as the owner's decision; the plan builds exactly that, at or after 07:00 Barbados. G.3 ("A roundup expires when the next is made") is a separate decision and is not built. The design's 22 px heading would be hand-set display type; the email shell's display titles are pre-rendered images and none exists for this line, so the plan sets it as bold body text. Decide the channel and threshold, whether roundups expire, and whether a title image should be made for the heading.
6. **"Came back": any time or within 7 days.** G.1 (any time) is the default. The database keeps only each member's latest moment online (`person.last_online_time`), so "within 7 days of a send" could not be answered. The plan adds a per-day record of members being online (`member_online_day`, kept 120 days), written from the deploy day; every run before it reads "Not measured" in the 7 day view. This is a new record of member activity: approve it and its 120 day retention, or the 7 day toggle stays "Not measured". Also: an admin reactivating a member sets their last online time, which counts as coming back.
7. **What counts as success for each email** (a click, a return within 7 days, push turned on) and whether the weekly cadence stays. Not built; the table shows all three measures side by side.
8. **Waiting on a reply.** Built as W.1 (counts only). W.2 (who liked whom) is not built. "Write to them" and "Send the reminder" are drawn disabled, with U.1's line "Off until the owner approves a reminder and its words." reused, because either is a new member-facing email outside this issue. Decide counts or names, and which nudge, with its words.
9. **Unfinished sign-ups.** The database deletes an unfinished sign-up after a week with no save (the garbage cron) and when the person signs in again more than an hour after their last save, so the list covers the last 7 days only and "Started" is the start of the current attempt. The server records only some steps during sign-up: verify email, verify phone, marital status, children and looking for leave no trace, so "Furthest step" is the furthest of Name, Date of birth, Gender, Photos, Country, Assembly and Relocation, or "The first step". People who came through a couple tool or the checklist are left out unless they saved a sign-up step. If you want a longer view, a count-only daily tally of abandoned sign-ups would be a new record; say so. The reminder stays off (U.1).
10. **The weekly funnel.** The export draws Likes as bars, one mark for first messages and replies in the latest week, and hatched "Not measured" weeks, because the review measured only some weeks. Every week is measurable from the database, so the plan draws real values, drops the hatching and its caption, draws first messages and replies as the warn mark on every week, and does not draw matches in the chart (the export has no mark for them; the phone rows show all four). A chart showing all four series needs a design pass through a brief into the existing Claude Design project. The export's 1440 row also puts Sign-ups by source and Recent activity beside the funnel; the plan places the funnel full width under the band (the export's 768 row) and leaves those panels where 93d3759 put them.
11. **Push.** "New per week" stays "Not measured": the API deletes a subscription the push service refuses, so past weeks cannot be counted honestly without a new subscription log. "New since 1 Oct" counts from the Discover banner's date in the brief. The brief also asked for a "Push on" row in Members by gender; the export draws a Push tile instead, and the plan follows the export.
12. **Verification.** Whether to nudge the unverified members (31 in the brief) is not built.
13. **Lines this plan adds that the export does not have.** Each goes through `/copy-pass` (ux-writing) and the owner before launch:
    - Last online for 2 to 7 days: "3 days ago" (the export has "Today", "Yesterday", "Over 7 days ago").
    - Furthest step labels after "The first step": "Name", "Date of birth", "Gender", "Photos", "Country", "Assembly", "Relocation" (the web wizard's own labels).
    - "Not recorded" for an unknown step, a run with no audit row and a photo stored before the deploy.
    - Gap label "Pending" for members whose only photos wait for review.
    - "Staff" badge on approved photos with no face belonging to a staff account.
    - Run history "Started by": "Send button", "Command line" (the brief's words; the export shows only "Schedule").
    - Run history footer: "53 sends to 50 people in the last 30 days, 5 back online since. Every run also appears in Audit." (the export's mock says "since 1 Oct").
    - Needs you singulars and plurals: "member has likes nobody has answered", "unfinished sign-ups, the latest started 8 Oct".
    - Photo waiting shown as a date, "5 Oct".
    - The stale email's "1 post is waiting for approval" and its lines for other kinds, "Brand post. In review since 12 Oct." (the queue's own kind labels).
    - The report email: subject "A member has reported someone" or "3 new reports are waiting", line "Open Reports in Moderation to see who and why.", button "Open reports", footer "Sent when a report arrives, while Email me when a report arrives is on."
    - Failure lines reused from the export where it has none: "Could not load reports." when resolving fails, "Could not load this count." when a list fails to load.
14. **Photo waiting.** No upload time was stored for photos. The plan adds `photo.uploaded_at` from the deploy; photos already stored read "Not recorded". A photo uploaded during sign-up is copied to `photo` when sign-up finishes, so its time is the finish.
15. **Profile views, 30 days** counts distinct members who opened the profile, invisible browsing included: `visited` keeps one row per pair with the latest visit, not each view.
16. **The photo gate list's window.** The brief says "in the last 30 days" for all activity; the export labels only "Profile views, 30 days". The plan counts all activity columns over 30 days and keeps the export's column names.
17. **Two staff rules on Moderation.** The gate list counts the people the existing gate tile counts (the member rule, no staff address list), so the tile and list agree; profile gaps use the Growth rule (with the staff address list). They can differ by any test account that is not an admin.
18. **Approved, no face** leaves out photos a moderator confirmed and photos the detector never checked, the gate's own rule. Say if confirmed ones should still be listed.
19. **Profile gaps list** holds photo gaps only; members who are only unverified are counted in the strip, not listed (31 rows on 13 Oct).
20. **Users table.** W.5 draws 5 columns (Name, Joined, Type, Last online, Status). The plan keeps today's Email and Roles columns and adds Last online, reading the frame as showing the additions. Decide whether Email and Roles go.
21. **System email clicks** read "Not measured". The export's "0 invite-link clicks since 1 Oct" on the referral row is invite-link clicks, which this table does not join.
22. **Growth layout.** G.1 at 1440 puts Push, Verification tiers and the Publishing queue in one row and Quotable notes (brief 3) below the emails. The plan adds Push and Verification tiers as their own row after the stats (the 768 arrangement) and leaves the queue and everything else in place; the full Growth layout belongs with the referral brief's round, as the brief says ("Lay out Growth once").
23. **Started by** reads the audit log, which has a row for cron and command line sends only since 13 Oct 2026; earlier runs read "Not recorded".
24. **The gate tile** now opens the gate list (`?tab=moderation&sub=gate`), which has no sub-tab in the export, instead of the Photos queue.
25. **Whose "Email me" it is** (added by the 18 Oct review). R.2's switch reads "Email me", but three accounts hold the admin role (ids 18, 23 and 126) and the plan stores one setting for all of them (`admin_alert_pref`, keyed by the alert alone) and always mails `OWNER_TO`. If another admin turns it on, the owner gets the emails and that admin gets none; if another admin turns it off, the owner's emails stop. The default keeps it as one setting that mails the owner. Decide whether only the owner's account may change it, or whether each admin keeps their own setting and gets the email at their own address (a `person_id` column on the preference, and a send to each admin who has it on).
26. **A report made again** (added by the 18 Oct review). The app writes a report with the skip upsert, which moves the pair's `created_at` whenever that member reports or passes the same person again. The plan treats that as a new report: it reads Unresolved and counts on Needs you, and the earlier resolution stays in `report_resolution` without showing. A plain pass on someone already reported cannot come from the app (a block hides the person everywhere), only from a direct API call. No decision needed unless you want a repeat report shown with the earlier outcome beside it.

## Self-review

**Spec coverage (the issue's gaps):**

| Gap | Tasks |
|---|---|
| Report state and outcome, the outcome column, the "email me" switch | 1, 4, 13, 14, 18 |
| Members waiting on a reply | 5, 17, 19 |
| Unfinished sign-ups | 7, 17, 20 |
| The weekly funnel | 8, 21 |
| Push | 9, 22 |
| Verification tiers | 9, 22 |
| Came back, push turned on, the 7 day toggle | 10, 11, 22 |
| Campaign run history | 11, 22 |
| Profile gaps | 12, 23 |
| The approved-no-face photo filter | 12, 23 |
| The photo gate member list | 12, 23 |
| An API errors counter | 3, 24 |
| The stale-post alert email to the owner | 2, 13, 14 |
| Users: last online, "has likes waiting", push status | 6, 19 |
| Deploy order | 26 |

**Placeholders:** none of "TBD", "TODO", "fill in" or "similar to Task N". Task 11's moved `Q_RUN_RESULTS` and `run_results` are written out in full (review, 18 Oct).

**Type consistency:** `counted_member_sql(alias, *, active)` (Task 5) is used in Tasks 7 to 12 with the same name; `waiting_likes_sql()` and `member_sent_sql(active)` (Task 5) in Tasks 6 and 8; `iso_row` (Task 5) in Tasks 5, 7, 8 and 12; `report_key` is the same `"<reporter>-<reported>-<YYYYMMDDHH24MISSUS>"` in Tasks 4 and 14; `email_outcomes.run_outcomes` returns `came_back`, `came_back_7d`, `push_turned_on`, which the index renames `last_run_*` (Task 11) and the admin reads under those names (Tasks 15, 16, 22); `started_by` values `schedule`, `command_line`, `send_button` match `startedByLabel` (Task 15); the admin hooks of Task 16 are the ones Tasks 17 to 24 import.

**Review Focus:** each of the five lines has its named test in its owning task (Tasks 4, 5, 3, 14 and 10).

## Review (18 Oct)

A review against the code and schema on `origin/ahavah/main` (e48e38f) and ahavah-admin `origin/master` (a13b115). Every SQL statement in Tasks 1 to 14 was run against the local test database inside a transaction that was rolled back (the 0069 tables as temporary tables, the migration itself applied twice), and all of them ran; nothing was left in the shared database. `src/lib/community.ts` (Task 15) type-checks under `tsc --strict` and its 9 tests pass, run from a scratch copy. The API test command was run on an existing file (`tests/test_migration_0068.py`, 10 passed). Migration 0069 is free on every local and remote branch and in the one worktree.

What changed, and why:

1. **Admin base branch** (Before you start). The plan said `master` at 068f6ae. Local `master` is stale at 42a3fea and has no `acting.ts`, `needs-you.tsx` or `acting.test.mjs`, which Tasks 15 to 25 edit; 068f6ae is the unmerged tip of `together-launch`. The admin now branches from `origin/master` (a13b115) after a fetch.
2. **Deploy behaviour** (Task 1). The plan said the deploy runs every migration on every deploy. `scripts/apply-deploy-migrations.sh` applies each file once, records its checksum and stops the deploy if an applied file changes. The text and the migration's header now say so: 0069 is never edited after it ships.
3. **Two indexes** (Task 1). The unresolved-report count reads `skipped` by `reported` on every Overview load and every cron tick, and `skipped` (every pass ever made) had no such index. Run history reads `email_send_log` by campaign and run id up to 24 times a load, and its indexes led with `person_id`. Migration 0069 now adds a partial index on reported rows and one on `(campaign, campaign_id)`, with a test.
4. **A replaced photo's upload time** (Task 1). An upload to a position that already holds a photo is an upsert, which would have kept the old photo's `uploaded_at`, so "Photo waiting" dated the new photo by the old one. The upsert now sets it, with a behavioural test through `patch_profile_info`.
5. **Blocked pairs on the waiting list** (Task 5). A one-sided conversation or a silent match where one person had blocked (reported) the other counted as someone waiting, though a block hides both from each other. The waiting queries now leave out any pair `is_blocked_pair` (migration 0035) holds, with a test. The funnel still counts history as it happened.
6. **The re-report test** (Task 4). The test unskipped with a DELETE and reported with an INSERT, a path the app never takes. The app reports through the skip upsert, which moves `created_at` on every repeat. The test helper now runs that upsert (`antiabuse.sql.Q_INSERT_SKIPPED`) and the comments describe it. Conflicts item 26 records what a repeat report does.
7. **A test fixture that could not run** (Task 7). `make_interval(hours => ...)` takes an integer, so the 0.2 hour idle time raised `function make_interval(hours => numeric) does not exist` (checked on the test database). The fixture uses `secs`.
8. **A retired lead source** (Task 7). The test used `marriage_checklist`, which migration 0066 rewrote to `tool:checklist`; it now uses the live value.
9. **The conftest anchor** (Task 1). The fixtures are appended after `tool_visitor`, the last fixture in the file, not `together_schema`.
10. **Moved code written in full** (Task 11). `Q_RUN_RESULTS` and `run_results` were referenced by line number; they are now in the step, and the delete instruction names exactly what goes.
11. **The rendered proof script** (Task 25). The wave 1 harness has no route table: each shot passes its own stub map and a query without `/?`, and it shoots 390 and 1280. The step now gives the code: the stubs (with Users, Reports and Photos bodies the new screens need), the three widths, the 10 pages and the run history sheet, 63 shots.
12. **A new owner decision** (Decisions taken item 9, conflicts item 25). "Email me when a report arrives" is one setting shared by the three admin accounts and always mails the owner, so another admin can turn the owner's emails on or off.

Checked and found sound: the staff rule on every new count matches the endpoint it sits beside (Growth's address list where Growth uses it, the member rule alone where Moderation's gate tile does, as conflicts item 17 says); every Barbados day and week converts on both sides; production reads stay counts, no query names message content, and the two owner emails sit behind default-off switches passed to both api and cron; the JSON keys and routes in Tasks 3 to 14 match the types and hooks in Tasks 15 and 16.

Left as it is, on purpose: Tasks 17 to 24 change React components with no failing test first. The admin has no component test harness; their logic lives in `community.ts` and `acting.ts`, tested in Tasks 15 and 17, and the components are checked by the type check, the build, `/sot-sync` and Task 25's screenshots.
