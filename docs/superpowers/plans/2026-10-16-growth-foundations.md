Linear: TEC-1845

# Growth foundations implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared backend groundwork that the couple tools, profile prompts, gatherings and the matchmaker all depend on, so each feature plan can start the day its Claude Design export returns.

**Architecture:** One `lead` table (with consent, source, confirmation and retention) sits behind a small `service/leads` package that the sign-in code flow, finish-onboarding, the email outbox, the unsubscribe link and the deletion paths all call. The publishing queue gains three subjectless kinds (`event`, `prompt`, `tool`) held to the owner's calendar like `brand`, every post link lands tagged with UTM values, and two scheduler functions queue event and "Question of the week" posts that wait for artwork and approval. Admin gets one data endpoint, the Sources table; the web gets one share-image helper that the feature pages' `opengraph-image` files will call.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16.2, React 19, `next/og` `ImageResponse`, vitest (ahavah-web).

**Spec:** `docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md` (its Order step 1, "Foundations", and the shared Scheduler, Dashboard and Privacy parts). Read with the four feature specs in the same folder: `2026-10-13-couple-tools-design.md`, `2026-10-13-profile-prompts-design.md`, `2026-10-13-events-design.md`, `2026-10-13-matchmaker-design.md`. Owner decisions: `docs/superpowers/plans/2026-10-13-health-review-owner-decisions.md`.

## Before you start

- The spec's Order step 0 comes first: the health review remediation is merged and deployed. Start from the tip of `ahavah/main` in ahavah-api and of `master` in ahavah-web, each on a new branch `growth-foundations` (superpowers:using-git-worktrees). Task 14 uses a second web branch, `growth-privacy`.
- This plan was written against the ahavah-api working tree of 16 Oct 2026, which held uncommitted changes from another session in `service/campaigns/__init__.py`, `service/campaigns/outbox.py`, `service/campaigns/runner.py` and `service/spotlight/eligibility.py` (the owner's note to the Spotlight candidates: `_PERSONAL_FIELDS`, `text`/`from_name`/`reply_to` on `enqueue`). Task 5 edits other regions of `outbox.py`; if that work has landed, keep it and apply these edits beside it.
- Paths below assume the checkouts at `/d/Antigravity/ahavah-api` and `/d/Antigravity/ahavah-web`. In a worktree, replace the path in both the `cd` and the `-v` mount of the test command, and keep `-p ahavah-api`.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. Without it compose names the project after the directory, so in a worktree it starts a second postgres that cannot bind port 5432 and that Task 1 Step 5's script never touches. With it, every test command uses the shared `ahavah-api-postgres-1` database, which other sessions also use and whose schema Task 1 Step 5 changes. Never remove, reset or recreate that container.
- Line numbers in this plan are hints only: they were measured on the 16 Oct working tree named above, and earlier tasks shift them. Every edit is anchored on the code it quotes: find that code, and if it is not where the number says, trust the quote.
- Web tests run with: `cd /d/Antigravity/ahavah-web && npx vitest run <file>`
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845`, no attribution trailers.

## Global Constraints

Every task's requirements include these. Quoted lines are verbatim from the specs or the owner's recorded decisions.

- Copy: sentence case, British spelling, no em dashes, digits for numbers, no serial comma. This covers captions, email text, privacy text, code comments and commit messages.
- Social: "No stock or staged faces of real members, no captions that rate people, nothing that says dating; the research guardrails (`docs/marketing/2026-09-19-social-content-cadence-research.md`) apply."
- Framing: the audience is "Torah-observant believers seeking marriage" (prompts spec). "No prompt about plural marriage." "Plural marriage stays out of the game for now."
- Scheduler: new kinds are "each subjectless, rendered from its template and waiting for the owner's approval like every other post".
- Links: "Every post link carries UTM tags (`utm_source=facebook|instagram`, `utm_campaign={kind}`, `utm_content={slug}`), so first-touch capture credits it."
- Instagram: "Instagram posts carry no link" (owner, 13 Oct; `service.campaigns.caption_for_platform`).
- Rest days: "no promotional posts and no campaign emails on the Day of Atonement or on the Sabbaths" (`service/spotlight/restdays.py`); nothing is decided past `KNOWN_THROUGH` for a calendar-held kind.
- Email: "Every changed email is proofed to the owner first." "Each new template goes to the owner as a proof before it is switched on." Emails "go through the durable outbox on the brand shell".
- Privacy: tool answers "are only readable by the two players through their tokens, and by no admin screen except as counts". "Rows are deleted 12 months after the last visit, or on request." A share image "never shows answers". The RSVP box "unticked by default" is "the only marketing consent". "Nobody browses anyone they could not already see as a member." Attribution is "first-party only, never shared" (migration 0060).
- Privacy page: "names each new kind of stored data ..., why it is kept, for how long, who can see it and how to delete it", before the first feature launches. Consent wording "goes through the ux-writing skill and the owner".
- Bot protection is free only (owner, 13 Oct: no Cloudflare account, no Turnstile keys): reuse `service/signupguard`.
- Owner decisions that bound this work: no cold outreach; no ad spend; US women are the focus for copy; non-members can RSVP; couple tools may store results; a parent or mentor role is welcome.
- Screens: every screen and every template's visual design comes from Claude Design. Nothing visual is hand-made here beyond the share-image fallback, which reuses the existing app icon's mark and colours.

## Review Focus

The five inputs the specs imply but no feature spec tests, most likely to bite first. Each has a test in the task named.

1. One address typed two ways (case, Gmail dots or a plus tag): one lead per source, never two. Task 3, `test_one_address_written_two_ways_is_one_lead`.
2. A confirm link tapped twice, tapped after it lapsed, or forged: the second tap confirms the same lead, a lapsed or forged one confirms nothing and says nothing. Task 3, `test_a_confirm_link_confirms_and_works_twice` and `test_a_lapsed_forged_or_odd_token_confirms_nothing`.
3. A member's own address entering a lead flow (a member playing the game, signing in from the checklist): no lead row, so members never count as leads. Task 3, `test_a_member_is_not_a_lead`; Task 4, `test_a_member_signing_in_from_a_tool_is_not_a_lead`.
4. A gathering 1 to 9 days away, or one whose post day is a Sabbath: past offsets are skipped, a rest day moves the post earlier and never after the gathering starts, at queueing and at approval. Task 10, `test_an_offset_already_past_is_skipped`, `test_a_gathering_tomorrow_gets_no_post`, `test_a_rest_day_moves_the_post_earlier`, `test_a_late_approval_of_the_d2_post_is_refused_never_moved_after_the_gathering`, `test_a_slot_that_turns_out_to_be_a_rest_day_moves_earlier_on_approval`.
5. A click with no platform or an unknown one, and a link that is not a post's: no `utm_source` is invented and email links stay untouched. Task 8, `test_a_click_with_no_or_an_unknown_platform_adds_no_source`, `test_an_email_link_is_never_tagged`.

## Decisions taken where the specs leave a choice

- One `lead` row per address and source, not one per address: consent is given in a context (an RSVP box, an alert), and the Sources table counts per source.
- A member is never a lead: the feature tables (`tool_session.owner_person_id`, `event_rsvp.person_id`) carry members; the lead table measures acquisition only.
- A confirmed lead's source outranks the first touch at sign-up: it was recorded on the server against the same address, while the touch lives on one device. The onboardee's own tag (set at `/check-otp`) still comes first, as today.
- Existing `lead_source` values move onto the taxonomy in the migration (`facebook` becomes `utm:facebook/{campaign}`, `invite` becomes `referral:{code}`, `marriage_checklist` becomes `tool:checklist`), so the Sources table has one encoding. A referring host becomes `site:{host}`, a kind the spec's list lacks.
- Confirm links last 7 days and may be tapped again in that time: an RSVP a week ahead still confirms, and a second tap is not an error.
- Lead mail rides the existing outbox (`email_outbox.lead_id`) rather than a second outbox, so the drain, its retry rules and its uncertainty handling stay single.
- The unsubscribe scope for lead mail is named `news`, because the success page prints the scope name to the visitor.
- `prompt_bank` is created here, empty: the weekly prompt post reads it. The prompts plan seeds it once the owner has the wording.
- Event posts go out at 12:00 UTC on the day 10 days and 2 days before; a rest day moves one up to 2 days earlier. The request key carries the gathering's date, so a moved gathering gets new posts.
- The on-the-day story variant of an event post is not built: the publisher and the image route post feed cards only. See "Spec conflicts" at the end.
- The weekly prompt post takes the first day of next week with nothing else scheduled, at 12:00 UTC, else 18:00. Its cron is off until the owner switches it on.
- The tool kind takes the brand route with `kind: "tool"`, so the calendar run needs one extra field and nothing else.
- Moderation > Text and the parent or mentor groundwork are not in Foundations: the spec's Order step 1 does not list them, and their first users (prompts, matchmaker step 3) ship later.

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `migrations/0066_growth_foundations.sql` | Create | `lead`, `email_outbox.lead_id`, `prompt_bank`, the new kinds, the `lead_source` backfill |
| `tests/test_migration_0066.py` | Create | Pins the schema and the backfill |
| `tests/conftest.py` | Modify | `growth_schema` fixture; `finish_onboarding` takes an `email`; `outbox_drain` parks lead mail |
| `service/leads/sources.py` | Create | The source taxonomy |
| `service/leads/__init__.py` | Create | Record, confirm, touch, link and refuse leads |
| `service/person/attribution.py` | Modify | First touch written on the taxonomy |
| `duotypes/__init__.py` | Modify | `/check-otp` accepts the tool sources |
| `service/person/__init__.py` | Modify | `/check-otp` records a confirmed tool lead; finish-onboarding links leads |
| `service/campaigns/outbox.py` | Modify | `enqueue_for_lead`; lead mail in the drain |
| `service/unsubscribe/__init__.py` | Modify | The `news` scope |
| `service/hard_delete.py` | Modify | `Q_DELETE_LEADS_OF` |
| `service/cron/pendingdeletion/__init__.py` | Modify | Deletes a leaver's leads |
| `service/api/admin/users_action_routes.py` | Modify | Admin hard delete deletes leads |
| `service/cron/leadretention/__init__.py` | Create | The 12 month sweep |
| `service/cron/__init__.py` | Modify | Registers the two new crons |
| `service/spotlight/queue.py` | Modify | New kinds, kind groups, `CAPTION_MAX`, tagged post links |
| `service/spotlight/dispatch.py` | Modify | Calendar rule for every held kind |
| `service/api/admin/spotlight_routes.py` | Modify | Held kinds in approval, retry, reschedule, image size and listings; queue row fields; `kind` on the brand route |
| `service/campaigns/__init__.py` | Modify | `valid_target_path`, `post_target_url`, `with_utm_source` |
| `service/api/campaign_link_routes.py` | Modify | Adds `utm_source` on a post click |
| `service/spotlight/growthposts.py` | Create | Event posts and the question of the week |
| `service/cron/questionofweek/__init__.py` | Create | The weekly prompt cron |
| `docker-compose.production.yml` | Modify | The tool-leads switch and the prompt cron's switch, both off by default |
| `service/growth/sources.py` | Create | The Sources query |
| `service/api/admin/growth_routes.py` | Modify | `GET /admin/growth/sources` |
| `tests/test_lead_sources.py`, `tests/test_leads.py`, `tests/test_lead_signup.py`, `tests/test_lead_mail.py`, `tests/test_lead_retention.py`, `tests/test_growth_kinds.py`, `tests/test_post_links_utm.py`, `tests/test_tool_posts.py`, `tests/test_event_posts.py`, `tests/test_question_of_week.py`, `tests/test_growth_sources.py` | Create | One file per task |
| `tests/test_onboarding_attribution.py` | Modify | Expectations on the taxonomy |

ahavah-web:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/share-image/sizes.ts` | Create | The three share sizes |
| `src/lib/share-image/mark.tsx` | Create | The Ahavah mark and its two colours, once |
| `src/lib/share-image/templates.tsx` | Create | Template registry with the fallback |
| `src/lib/share-image/render.tsx` | Create | `renderShareImage` |
| `src/lib/share-image/summary.ts` | Create | `fetchPublicSummary` |
| `src/app/apple-icon.tsx` | Modify | Draws the mark from `mark.tsx` |
| `tests/lib/share-image.test.ts` | Create | Helper tests |
| `src/lib/legal-leads-copy.ts` | Create (branch `growth-privacy`) | The privacy paragraph for leads |
| `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` | Modify (branch `growth-privacy`) | Show it |
| `tests/app/legal-leads.test.tsx` | Create (branch `growth-privacy`) | Pins it on both pages |

---

### Task 1: Migration 0066, the shared schema

**Files:**
- Create: `migrations/0066_growth_foundations.sql`
- Create: `tests/test_migration_0066.py`
- Modify: `tests/conftest.py` (append a `growth_schema` fixture at the end of the file)

**Interfaces:**
- Consumes: `person`, `onboardee`, `email_outbox` (0046), `publishing_queue` (0041, kind check from 0055).
- Produces: table `lead(id bigserial, email text, normalized_email text, source text, marketing_consent bool, consent_wording text, consented_at, unsubscribed_at, consent_pending_wording text, consent_pending_at, confirmed_at timestamptz, confirmed_via text in ('otp','link'), confirm_token_hash text, confirm_token_expires_at, person_id int -> person ON DELETE CASCADE, converted_at, last_seen_at, created_at)`, unique `(normalized_email, source)`; `email_outbox.lead_id bigint -> lead ON DELETE CASCADE`, `person_id` nullable, check `num_nonnulls(person_id, lead_id) = 1`, partial unique `(campaign, campaign_id, lead_id)`; table `prompt_bank(key text pk slug, text text 1..120, category text, active bool, sort int)`; `publishing_queue_kind_check` adds `event`, `prompt`, `tool`; session fixture `growth_schema`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0066.py`:

```python
"""Migration 0066: the growth foundations' schema (TEC-1845).

Pins what later tasks rely on: one lead per address and source, lead mail
in the outbox with exactly one recipient, the prompt bank, the three new
publishing kinds and lead_source on one taxonomy. The deploy may run the
file more than once, so every test runs it twice first.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0066_growth_foundations.sql')


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply()
    _apply()


def _address() -> str:
    return f'm0066-{uuid4().hex[:12]}@example.org'


def _insert_lead(tx, email: str, source: str) -> int:
    return tx.execute(
        """INSERT INTO lead (email, normalized_email, source)
           VALUES (%(e)s, %(e)s, %(s)s) RETURNING id""",
        dict(e=email, s=source)).fetchone()['id']


def _delete_leads(email: str) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = %(e)s', dict(e=email))


def test_an_address_is_one_lead_per_source():
    email = _address()
    try:
        with api_tx() as tx:
            _insert_lead(tx, email, 'tool:game-me')
            _insert_lead(tx, email, 'event:sukkot-gathering')
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _insert_lead(tx, email, 'tool:game-me')
    finally:
        _delete_leads(email)


def test_consent_cannot_be_stored_without_its_wording():
    email = _address()
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute(
                    """INSERT INTO lead (email, normalized_email, source, marketing_consent)
                       VALUES (%(e)s, %(e)s, 'alert:visitor', TRUE)""", dict(e=email))
    finally:
        _delete_leads(email)


def _outbox_row(tx, *, person_id, lead_id, email: str) -> None:
    tx.execute(
        """INSERT INTO email_outbox (campaign, campaign_id, person_id, lead_id, email,
                                     payload, unsub_scope)
           VALUES ('test-0066', 'run-1', %(p)s, %(l)s, %(e)s, '{}'::jsonb, 'news')""",
        dict(p=person_id, l=lead_id, e=email))


def test_an_outbox_row_names_exactly_one_recipient(make_person):
    person = make_person(name='M0066')
    email = _address()
    with api_tx() as tx:
        lead_id = _insert_lead(tx, email, 'alert:visitor')
    try:
        for person_id, lid in ((None, None), (person['id'], lead_id)):
            with pytest.raises(psycopg.errors.CheckViolation):
                with api_tx() as tx:
                    _outbox_row(tx, person_id=person_id, lead_id=lid, email=email)
    finally:
        _delete_leads(email)


def test_a_lead_is_queued_once_per_run_and_its_mail_goes_with_it():
    email = _address()
    with api_tx() as tx:
        lead_id = _insert_lead(tx, email, 'alert:visitor')
        _outbox_row(tx, person_id=None, lead_id=lead_id, email=email)
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _outbox_row(tx, person_id=None, lead_id=lead_id, email=email)
    finally:
        _delete_leads(email)
    with api_tx() as tx:
        left = tx.execute('SELECT count(*) AS n FROM email_outbox WHERE lead_id = %(l)s',
                          dict(l=lead_id)).fetchone()['n']
    assert left == 0, 'deleting a lead must delete the mail queued for it'


@pytest.mark.parametrize('kind', ['event', 'prompt', 'tool'])
def test_the_new_publishing_kinds_are_accepted(kind):
    rk = f'm0066:{uuid4().hex[:8]}'
    try:
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO publishing_queue (request_key, kind, platform, caption, status, created_by)
                   VALUES (%(rk)s, %(k)s, 'facebook', 'c', 'cancelled', 'test')""",
                dict(rk=rk, k=kind))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM publishing_queue WHERE request_key = %(rk)s', dict(rk=rk))


def test_the_prompt_bank_takes_a_slug_key_and_short_text():
    key = f'm0066-{uuid4().hex[:8]}'
    try:
        with api_tx() as tx:
            tx.execute("""INSERT INTO prompt_bank (key, text, category)
                          VALUES (%(k)s, 'How I keep Sabbath', 'sabbath')""", dict(k=key))
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO prompt_bank (key, text, category)
                              VALUES ('Not A Slug', 'x', 'sabbath')""")
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO prompt_bank (key, text, category)
                              VALUES (%(k)s, %(t)s, 'sabbath')""",
                           dict(k=f'{key}-long', t='x' * 121))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM prompt_bank WHERE key LIKE %(k)s', dict(k=f'{key}%'))


# (lead_source before, first_touch, lead_source after)
_LEGACY = [
    ('marriage_checklist', None, 'tool:checklist'),
    ('invite', {'code': 'abc2345'}, 'referral:ABC2345'),
    ('invite', None, 'referral'),
    ('facebook', {'utm_source': 'Facebook', 'utm_campaign': 'Oct-Launch'}, 'utm:facebook/oct-launch'),
    ('instagram', {'utm_source': 'instagram'}, 'utm:instagram'),
    ('www.google.com', {'referrer_host': 'WWW.Google.com'}, 'site:www.google.com'),
    ('event:sukkot-gathering', None, 'event:sukkot-gathering'),
    (None, None, None),
]


def test_lead_source_moves_onto_one_taxonomy(make_person):
    ids = []
    for before, touch, _ in _LEGACY:
        p = make_person(name='M0066Source')
        with api_tx() as tx:
            tx.execute(
                """UPDATE person SET lead_source = %(s)s, first_touch = %(t)s::jsonb
                    WHERE id = %(i)s""",
                dict(s=before, t=json.dumps(touch) if touch is not None else None, i=p['id']))
        ids.append(p['id'])
    _apply()
    _apply()
    with api_tx() as tx:
        after = [tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=i)).fetchone()['lead_source'] for i in ids]
    assert after == [want for _, _, want in _LEGACY]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0066.py -q -p no:warnings`
Expected: every test errors in `_applied_twice` with `FileNotFoundError` for `0066_growth_foundations.sql`.

- [ ] **Step 3: Write the migration**

Create `migrations/0066_growth_foundations.sql`:

```sql
-- 0066_growth_foundations.sql
-- The shared groundwork for the growth features (TEC-1845,
-- docs/superpowers/plans/2026-10-16-growth-foundations.md). The couple
-- tools, profile prompts, gatherings and the matchmaker all read or write
-- these.
--
--   lead          one row per address and source for someone who gave
--                 Ahavah an email before joining: a tool player who saved a
--                 result, a gathering RSVP, a visitor alert. Marketing
--                 consent is per row, with the key of the exact wording
--                 shown. A tick that arrives after the address unsubscribed
--                 waits in consent_pending_* until a confirm link issued
--                 after it is tapped. A member's address is never a lead
--                 (service/leads). Deleted 12 months after last_seen_at, 8
--                 days after creation if never confirmed, or on request.
--   email_outbox  may now hold mail for a lead (lead_id) instead of a
--                 member (person_id); exactly one of the two.
--   prompt_bank   the prompts members answer. Created here because the
--                 weekly "Question of the week" post reads it; seeded by the
--                 profile prompts plan once the owner has the wording.
--   publishing_queue.kind  gains event, prompt and tool.
--   lead_source   existing values moved onto one taxonomy
--                 (service/leads/sources.py). Only values in the old shapes
--                 match, so a second run changes nothing.
--
-- First-party only, never shared. Idempotent: the deploy may run this file
-- more than once.

CREATE TABLE IF NOT EXISTS lead (
  id                        BIGSERIAL    PRIMARY KEY,
  email                     TEXT         NOT NULL,
  normalized_email          TEXT         NOT NULL,
  source                    TEXT         NOT NULL,
  marketing_consent         BOOLEAN      NOT NULL DEFAULT FALSE,
  consent_wording           TEXT,
  consented_at              TIMESTAMPTZ,
  unsubscribed_at           TIMESTAMPTZ,
  consent_pending_wording   TEXT,
  consent_pending_at        TIMESTAMPTZ,
  confirmed_at              TIMESTAMPTZ,
  confirmed_via             TEXT         CHECK (confirmed_via IN ('otp', 'link')),
  confirm_token_hash        TEXT,
  confirm_token_expires_at  TIMESTAMPTZ,
  person_id                 INT          REFERENCES person(id) ON DELETE CASCADE,
  converted_at              TIMESTAMPTZ,
  last_seen_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (normalized_email, source),
  CHECK (NOT marketing_consent OR consent_wording IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx__lead__email ON lead (email);
CREATE INDEX IF NOT EXISTS idx__lead__person_id ON lead (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__lead__last_seen_at ON lead (last_seen_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx__lead__confirm_token_hash
  ON lead (confirm_token_hash) WHERE confirm_token_hash IS NOT NULL;

-- Lead mail. A lead has no person row, so the outbox names one or the other.
ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS lead_id BIGINT REFERENCES lead(id) ON DELETE CASCADE;
ALTER TABLE email_outbox ALTER COLUMN person_id DROP NOT NULL;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__lead_run
  ON email_outbox (campaign, campaign_id, lead_id) WHERE lead_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS prompt_bank (
  key       TEXT     PRIMARY KEY CHECK (key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  text      TEXT     NOT NULL CHECK (char_length(text) BETWEEN 1 AND 120),
  category  TEXT     NOT NULL,
  active    BOOLEAN  NOT NULL DEFAULT TRUE,
  sort      INT      NOT NULL DEFAULT 0
);

-- Dropped and re-added under the name 0055 left, so the next migration can
-- do the same.
ALTER TABLE publishing_queue DROP CONSTRAINT IF EXISTS publishing_queue_kind_check;
ALTER TABLE publishing_queue ADD CONSTRAINT publishing_queue_kind_check
  CHECK (kind IN ('welcome', 'roundup', 'member_of_week', 'highlight', 'brand',
                  'event', 'prompt', 'tool'));

-- lead_source on one taxonomy. The writers change in the same release
-- (service/person/attribution.py, service/person/__init__.py).
UPDATE person    SET lead_source = 'tool:checklist' WHERE lead_source = 'marriage_checklist';
UPDATE onboardee SET lead_source = 'tool:checklist' WHERE lead_source = 'marriage_checklist';

UPDATE person
   SET lead_source = CASE WHEN COALESCE(btrim(first_touch->>'code'), '') <> ''
                          THEN 'referral:' || upper(btrim(first_touch->>'code'))
                          ELSE 'referral' END
 WHERE lead_source = 'invite';

UPDATE person
   SET lead_source = 'utm:' || lead_source
                     || COALESCE('/' || lower(NULLIF(btrim(first_touch->>'utm_campaign'), '')), '')
 WHERE strpos(lead_source, ':') = 0
   AND lead_source = lower(btrim(first_touch->>'utm_source'));

UPDATE person
   SET lead_source = 'site:' || lead_source
 WHERE strpos(lead_source, ':') = 0
   AND lead_source = lower(btrim(first_touch->>'referrer_host'));
```

Append to `tests/conftest.py`:

```python
# ---------------------------------------------------------------------------
# Growth foundations schema (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0066 is idempotent, so applying it here is what the deploy does.
# A test module that reads the lead table, the prompt bank or the new
# publishing kinds asks for it with
#     pytestmark = pytest.mark.usefixtures('growth_schema')

@pytest.fixture(scope='session')
def growth_schema():
    from pathlib import Path

    from database import api_tx

    path = (Path(__file__).resolve().parent.parent
            / 'migrations' / '0066_growth_foundations.sql')
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0066.py -q -p no:warnings`
Expected: `9 passed`.

- [ ] **Step 5: Apply the migration to the local test database**

Later tasks change code that existing suites run (finish-onboarding, the outbox drain), and those suites do not ask for `growth_schema`. With the test postgres container up from Step 4:
Run: `cd /d/Antigravity/ahavah-api && bash scripts/apply-deploy-migrations.sh`
Expected: the last lines read `Applying 0066_growth_foundations.sql` (or `Already applied` for every file on a second run), exit code 0.

The script targets `ahavah-api-postgres-1`, the shared database other sessions are using. It records each file's checksum and stops at the first file whose checksum has changed (`Migration checksum changed: <file>`), which may be an older file than 0066: an earlier session recorded drift on 0046 in this stack. If the script refuses on any file, stop and report the message; never remove, reset or recreate the `ahavah-api-postgres-1` container or its volume. Where a clean database is genuinely needed, use one of these instead:

- Apply 0066 alone to the shared database, which is safe because the file is idempotent: `docker exec -i ahavah-api-postgres-1 psql -X -v ON_ERROR_STOP=1 -U postgres -d duo_api < migrations/0066_growth_foundations.sql`.
- Or run the script against a separately named throwaway container: `AHAVAH_POSTGRES_CONTAINER=<throwaway container name> bash scripts/apply-deploy-migrations.sh`.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add migrations/0066_growth_foundations.sql tests/test_migration_0066.py tests/conftest.py
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): one lead table, lead mail in the outbox, the prompt bank and three post kinds" -m "Refs: TEC-1845"
```

---

### Task 2: The source taxonomy

**Files:**
- Create: `service/leads/sources.py`
- Modify: `service/person/attribution.py` (docstring lines 18 to 21; `lead_source_from`, lines 85 to 94)
- Test: `tests/test_lead_sources.py` (create), `tests/test_onboarding_attribution.py` (modify lines 10 to 12, 50, 53 to 57, 63, 113)

**Interfaces:**
- Consumes: `clean_first_touch` output from `service.person.attribution` (dict of trimmed strings).
- Produces, in `service.leads.sources`: `TOOL_SOURCES: tuple[str, ...]`, `ALERT_VISITOR = 'alert:visitor'`, `INTRO = 'intro'`, `MENTOR = 'mentor'`, `LEGACY_CHECKLIST = 'marriage_checklist'`, `SLUG_RE: re.Pattern`, `EVENT_SLUG_MAX = 45`, `event_source(slug: str) -> str` (raises `ValueError('bad_slug')`), `referral_source(code: str) -> str`, `utm_label(source: str, campaign: Optional[str]) -> str`, `site_source(host: str) -> str`, `canonical_tool_source(value: Optional[str]) -> Optional[str]`, `is_lead_source(value: object) -> bool`, `source_kind(value: Optional[str]) -> str`. `service.person.attribution.lead_source_from(touch) -> Optional[str]` now returns taxonomy values.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lead_sources.py`:

```python
"""The source taxonomy (TEC-1845).

The Sources table compares a game player with an event guest only if both
are written the same way. These pin every shape: tool:*, event:{slug},
alert:visitor, intro, mentor, referral:{code}, utm:{source}/{campaign} and
site:{host}.
"""
from __future__ import annotations

import pytest

from service.leads.sources import (EVENT_SLUG_MAX, canonical_tool_source, event_source,
                                   is_lead_source, referral_source, site_source,
                                   source_kind, utm_label)
from service.person.attribution import lead_source_from


def test_a_utm_touch_is_named_by_its_source_and_campaign():
    assert lead_source_from({'utm_source': 'Facebook', 'utm_campaign': 'Event'}) == 'utm:facebook/event'
    assert lead_source_from({'utm_source': 'newsletter'}) == 'utm:newsletter'


def test_an_invite_code_is_a_referral_by_its_code():
    assert lead_source_from({'code': 'abc2345', 'referrer_host': 'wa.me'}) == 'referral:ABC2345'


def test_a_referrer_alone_is_a_site():
    assert lead_source_from({'referrer_host': 'WWW.Google.com'}) == 'site:www.google.com'


def test_a_touch_with_nothing_to_name_is_none():
    assert lead_source_from(None) is None
    assert lead_source_from({'first_seen_at': '2026-10-01T00:00:00+00:00'}) is None


def test_the_checklist_old_name_reads_as_tool_checklist():
    assert canonical_tool_source('marriage_checklist') == 'tool:checklist'
    assert canonical_tool_source('tool:game-us') == 'tool:game-us'
    assert canonical_tool_source('tool:roulette') is None
    assert canonical_tool_source(None) is None


@pytest.mark.parametrize('value,ok', [
    ('tool:game-me', True), ('tool:game-us', True), ('tool:knows-me', True),
    ('tool:checklist', True), ('alert:visitor', True), ('event:sukkot-2027', True),
    ('event:' + 'a' * EVENT_SLUG_MAX, True),
    ('event:' + 'a' * (EVENT_SLUG_MAX + 1), False), ('event:Sukkot', False),
    ('event:', False), ('intro', False), ('mentor', False),
    ('utm:facebook/event', False), ('referral:ABC2345', False),
    ('', False), (None, False), (7, False),
])
def test_only_pre_join_sources_may_be_a_lead(value, ok):
    assert is_lead_source(value) is ok


def test_an_event_source_needs_a_slug():
    assert event_source('sukkot-2027') == 'event:sukkot-2027'
    for bad in ('Sukkot', 'a b', '-x', 'x-', 'a--b', 'a' * (EVENT_SLUG_MAX + 1), '', None):
        with pytest.raises(ValueError, match='bad_slug'):
            event_source(bad)


def test_the_kind_is_the_part_before_the_colon():
    assert source_kind('event:sukkot-2027') == 'event'
    assert source_kind('utm:facebook/event') == 'utm'
    assert source_kind('intro') == 'intro'
    assert source_kind(None) == 'unknown'
    assert source_kind('') == 'unknown'


def test_the_helpers_store_one_case():
    assert referral_source(' abc2345 ') == 'referral:ABC2345'
    assert site_source(' WA.me ') == 'site:wa.me'
    assert utm_label(' Instagram ', '') == 'utm:instagram'
    assert utm_label('Instagram', ' Profile ') == 'utm:instagram/profile'
```

In `tests/test_onboarding_attribution.py`:

Replace lines 10 to 12 of the docstring:

```python
  2. writes person.lead_source from them on the source taxonomy
     (service/leads/sources.py): utm:{source}/{campaign}, else
     referral:{code} for an invite code, else site:{host}. A source the
     onboardee already carries (the marriage checklist's) is kept;
```

Line 50: `    assert row['lead_source'] == 'utm:facebook/oct-launch'`

Lines 53 to 57:

```python
def test_an_invite_code_without_utm_reads_as_a_referral(finish_onboarding):
    r, pid = finish_onboarding(dict(
        first_touch={'code': 'ABC2345', 'referrer_host': 'wa.me'}, heard_about=None))
    _ok(r)
    assert _row(pid)['lead_source'] == 'referral:ABC2345'
```

Line 63: `    assert _row(pid)['lead_source'] == 'site:www.google.com'`

Line 113: `    assert row['lead_source'] == 'site:news.example.org'`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_sources.py tests/test_onboarding_attribution.py -q -p no:warnings`
Expected: `test_lead_sources.py` errors at collection with `ModuleNotFoundError: No module named 'service.leads'`; the 4 edited attribution tests fail on the old values (`'facebook' == 'utm:facebook/oct-launch'`).

- [ ] **Step 3: Write the implementation**

Create `service/leads/sources.py`:

```python
"""Where a lead or a member came from, on one taxonomy (TEC-1845).

Growth spec, Dashboard: a Sources table compares a game player with an
event guest only if both are written the same way. Every value is `<kind>`
or `<kind>:<detail>`:

  tool:game-me  tool:game-us  tool:knows-me  tool:checklist
  event:{slug}  alert:visitor  intro  mentor
  referral:{code}  utm:{source}/{campaign}  site:{host}

`site:{host}` is not in the spec's list. Before this, a referring host was
written bare ('www.google.com'), and it needs a kind like every other value.
Migration 0066 moved the old values onto these shapes.
"""
from __future__ import annotations

import re
from typing import Optional

TOOL_SOURCES = ('tool:game-me', 'tool:game-us', 'tool:knows-me', 'tool:checklist')
ALERT_VISITOR = 'alert:visitor'
INTRO = 'intro'
MENTOR = 'mentor'
# What the marriage checklist page sends to /check-otp today.
LEGACY_CHECKLIST = 'marriage_checklist'

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
# event:{slug}:{yyyymmdd}:d10, an event post's request key
# (service/spotlight/growthposts.py), must fit the queue's 64 characters.
EVENT_SLUG_MAX = 45


def _is_slug(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= EVENT_SLUG_MAX and bool(SLUG_RE.match(value))


def event_source(slug: str) -> str:
    if not _is_slug(slug):
        raise ValueError('bad_slug')
    return f'event:{slug}'


def referral_source(code: str) -> str:
    return f'referral:{code.strip().upper()}'


def utm_label(source: str, campaign: Optional[str]) -> str:
    s = source.strip().lower()
    c = (campaign or '').strip().lower()
    return f'utm:{s}/{c}' if c else f'utm:{s}'


def site_source(host: str) -> str:
    return f'site:{host.strip().lower()}'


def canonical_tool_source(value: Optional[str]) -> Optional[str]:
    """A /check-otp `source` as stored: the checklist's old name reads as
    tool:checklist, anything that is not a tool reads as None."""
    if value == LEGACY_CHECKLIST:
        return 'tool:checklist'
    return value if value in TOOL_SOURCES else None


def is_lead_source(value: object) -> bool:
    """The sources a lead row may carry: where someone gave an email before
    joining. intro and mentor are sign-up sources the matchmaker writes on
    person.lead_source; nobody gives their own email there."""
    if not isinstance(value, str):
        return False
    if value in TOOL_SOURCES or value == ALERT_VISITOR:
        return True
    return value.startswith('event:') and _is_slug(value[len('event:'):])


def source_kind(value: Optional[str]) -> str:
    return value.split(':', 1)[0] if value else 'unknown'
```

Create an empty `service/leads/__init__.py` containing only a docstring placeholder line that Task 3 replaces:

```python
"""Leads (TEC-1845). Filled in by Task 3 of docs/superpowers/plans/2026-10-16-growth-foundations.md."""
```

In `service/person/attribution.py`, replace docstring lines 18 to 21:

```python
lead_source is written on the source taxonomy (service/leads/sources.py):
utm:{source}/{campaign} when the touch has a utm_source, else
referral:{code} when an invite code came with it, else site:{host} for the
referring host. NULL when the touch has none of them. A source the
onboardee already carries (a couple tool's or the marriage checklist's,
set at /check-otp) is kept.
"""
```

Add under the existing imports (after line 27):

```python
from service.leads.sources import referral_source, site_source, utm_label
```

Replace `lead_source_from` (lines 85 to 94):

```python
def lead_source_from(touch: Optional[dict]) -> Optional[str]:
    if not touch:
        return None
    if touch.get('utm_source'):
        return utm_label(touch['utm_source'], touch.get('utm_campaign'))
    if touch.get('code'):
        return referral_source(touch['code'])
    if touch.get('referrer_host'):
        return site_source(touch['referrer_host'])
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_sources.py tests/test_onboarding_attribution.py -q -p no:warnings`
Expected: all pass (`34 passed`: 25 in the new file, 9 in the attribution file).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/leads/__init__.py service/leads/sources.py service/person/attribution.py tests/test_lead_sources.py tests/test_onboarding_attribution.py
git -c user.email=admin@techbaseltd.com commit -m "feat(attribution): every source is written on one taxonomy" -m "Refs: TEC-1845"
```

---

### Task 3: Recording and confirming a lead

**Files:**
- Modify: `service/leads/__init__.py` (replace the placeholder with the module below)
- Test: `tests/test_leads.py` (create)

**Interfaces:**
- Consumes: `is_lead_source` (Task 2); `antiabuse.antispam.signupemail.normalize_email(email: str) -> str`; the `lead` table (Task 1).
- Produces, in `service.leads`: `CONFIRM_TTL = timedelta(days=7)`, `RETENTION_DAYS = 365`, `CONFIRMED_VIA = ('otp', 'link')`, `clean_email(email: object) -> Optional[tuple[str, str]]`, `token_hash(token: str) -> str`, `new_token() -> tuple[str, str]`, `record_lead(tx, *, email: str, source: str, marketing_consent: bool = False, consent_wording: Optional[str] = None) -> Optional[int]` (raises `ValueError('bad_source' | 'bad_email' | 'consent_wording_required')`), `confirm_lead(tx, lead_id: int, via: str) -> None` (raises `ValueError('bad_via')`), `issue_confirm_token(tx, lead_id: int) -> str`, `confirm_by_token(tx, token: object) -> Optional[int]`, `touch_lead(tx, lead_id: int) -> None`, `lead_unsubscribed(tx, lead_id: int) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_leads.py`:

```python
"""Leads: an email given to Ahavah before joining (TEC-1845).

One row per address and source; a member is never a lead; marketing
consent is a ticked box stored with its wording and never withdrawn by a
later unticked one; a confirm link is stored as a hash, works more than
once while it lasts and confirms nothing once it has lapsed or if it was
never issued.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest

from database import api_tx
from service.leads import (confirm_by_token, confirm_lead, issue_confirm_token,
                           lead_unsubscribed, record_lead, touch_lead)

pytestmark = pytest.mark.usefixtures('growth_schema')


@pytest.fixture
def addresses():
    made: list[str] = []

    def keep(address: str) -> str:
        made.append(address.lower())
        return address

    def new(domain: str = 'example.org') -> str:
        return keep(f'lead{uuid4().hex[:10]}@{domain}')

    yield SimpleNamespace(new=new, keep=keep)
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s) OR normalized_email = ANY(%(e)s)',
                   dict(e=made))


def _lead(lead_id: int) -> dict:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT * FROM lead WHERE id = %(i)s', dict(i=lead_id)).fetchone()


def test_a_new_address_is_one_lead_per_source(addresses):
    email = addresses.new()
    with api_tx() as tx:
        a = record_lead(tx, email=email, source='tool:game-me')
        b = record_lead(tx, email=email, source='event:sukkot-2027')
        again = record_lead(tx, email=f'  {email.upper()} ', source='tool:game-me')
    assert a != b and again == a
    row = _lead(a)
    assert row['email'] == email and row['source'] == 'tool:game-me'
    assert row['marketing_consent'] is False and row['confirmed_at'] is None


def test_one_address_written_two_ways_is_one_lead(addresses):
    name = f'ann{uuid4().hex[:8]}'
    plain = addresses.keep(f'{name}@gmail.com')
    dotted = addresses.keep(f'{name[:3]}.{name[3:]}+tools@gmail.com')
    with api_tx() as tx:
        first = record_lead(tx, email=plain, source='alert:visitor')
        second = record_lead(tx, email=dotted, source='alert:visitor')
    assert first == second


def test_a_member_is_not_a_lead(addresses, make_person):
    person = make_person(name='LeadMember')
    with api_tx() as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=person['id'])).fetchone()['email']
    addresses.keep(email)
    with api_tx() as tx:
        assert record_lead(tx, email=email, source='tool:game-us') is None
        n = tx.execute('SELECT count(*) AS n FROM lead WHERE email = %(e)s',
                       dict(e=email.lower())).fetchone()['n']
    assert n == 0


def test_consent_needs_its_wording(addresses):
    with pytest.raises(ValueError, match='consent_wording_required'):
        with api_tx() as tx:
            record_lead(tx, email=addresses.new(), source='event:sukkot-2027',
                        marketing_consent=True)


def test_a_later_unticked_box_never_withdraws_consent(addresses):
    email = addresses.new()
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source='event:sukkot-2027',
                              marketing_consent=True, consent_wording='rsvp-2026-11')
        record_lead(tx, email=email, source='event:sukkot-2027')
    row = _lead(lead_id)
    assert row['marketing_consent'] is True
    assert row['consent_wording'] == 'rsvp-2026-11'
    assert row['consented_at'] is not None


def test_a_fresh_tick_after_unsubscribing_waits_for_a_new_confirm_link(addresses):
    # Anyone can type an address into a form and tick the box, so a tick
    # after an unsubscribe counts only once the address itself taps a
    # confirm link issued after that tick.
    email = addresses.new()
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source='alert:visitor',
                              marketing_consent=True, consent_wording='alert-2026-11')
        old_token = issue_confirm_token(tx, lead_id)
        confirm_by_token(tx, old_token)
        tx.execute('UPDATE lead SET unsubscribed_at = NOW() WHERE id = %(i)s', dict(i=lead_id))
    with api_tx() as tx:
        record_lead(tx, email=email, source='alert:visitor',
                    marketing_consent=True, consent_wording='alert-2026-12')
        assert lead_unsubscribed(tx, lead_id) is True
        assert confirm_by_token(tx, old_token) == lead_id
        assert lead_unsubscribed(tx, lead_id) is True, 'a link issued before the tick proves nothing'
    with api_tx() as tx:
        new_token = issue_confirm_token(tx, lead_id)
    with api_tx() as tx:
        assert confirm_by_token(tx, new_token) == lead_id
        assert lead_unsubscribed(tx, lead_id) is False
    row = _lead(lead_id)
    assert row['consent_wording'] == 'alert-2026-12'
    assert row['consent_pending_wording'] is None and row['consent_pending_at'] is None


@pytest.mark.parametrize('email,source,error', [
    ('someone@example.org', 'utm:facebook/event', 'bad_source'),
    ('someone@example.org', 'intro', 'bad_source'),
    ('not-an-address', 'tool:game-me', 'bad_email'),
    ('a@b', 'tool:game-me', 'bad_email'),
    ('two@at@example.org', 'tool:game-me', 'bad_email'),
    (None, 'tool:game-me', 'bad_email'),
])
def test_bad_input_is_refused(email, source, error):
    with pytest.raises(ValueError, match=error):
        with api_tx() as tx:
            record_lead(tx, email=email, source=source)


def test_a_confirm_link_confirms_and_works_twice(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='event:sukkot-2027')
        token = issue_confirm_token(tx, lead_id)
    assert len(token) == 32
    with api_tx() as tx:
        assert confirm_by_token(tx, token) == lead_id
        assert confirm_by_token(tx, token) == lead_id
    row = _lead(lead_id)
    assert row['confirmed_at'] is not None and row['confirmed_via'] == 'link'
    assert row['confirm_token_hash'] != token and len(row['confirm_token_hash']) == 64


def test_a_lapsed_forged_or_odd_token_confirms_nothing(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='alert:visitor')
        token = issue_confirm_token(tx, lead_id)
        tx.execute("""UPDATE lead SET confirm_token_expires_at = NOW() - interval '1 minute'
                       WHERE id = %(i)s""", dict(i=lead_id))
    with api_tx() as tx:
        assert confirm_by_token(tx, token) is None
        assert confirm_by_token(tx, secrets.token_urlsafe(24)) is None
        for odd in ('', 'x', None, 42, 'a' * 200):
            assert confirm_by_token(tx, odd) is None
    assert _lead(lead_id)['confirmed_at'] is None


def test_a_code_confirmation_is_recorded_as_otp_and_kept(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='tool:checklist')
        confirm_lead(tx, lead_id, 'otp')
        token = issue_confirm_token(tx, lead_id)
        confirm_by_token(tx, token)
        with pytest.raises(ValueError, match='bad_via'):
            confirm_lead(tx, lead_id, 'carrier-pigeon')
    assert _lead(lead_id)['confirmed_via'] == 'otp'


def test_a_visit_moves_last_seen(addresses):
    with api_tx() as tx:
        lead_id = record_lead(tx, email=addresses.new(), source='tool:game-me')
        tx.execute("UPDATE lead SET last_seen_at = NOW() - interval '200 days' WHERE id = %(i)s",
                   dict(i=lead_id))
        touch_lead(tx, lead_id)
        age = tx.execute('SELECT NOW() - last_seen_at AS a FROM lead WHERE id = %(i)s',
                         dict(i=lead_id)).fetchone()['a']
    assert age.total_seconds() < 60


def test_an_unknown_lead_reads_as_unsubscribed():
    with api_tx() as tx:
        assert lead_unsubscribed(tx, -1) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_leads.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'confirm_by_token' from 'service.leads'`.

- [ ] **Step 3: Write the implementation**

Replace `service/leads/__init__.py` with:

```python
"""Leads: people who gave Ahavah an email before joining (TEC-1845).

docs/superpowers/plans/2026-10-16-growth-foundations.md. One table
(migration 0066) shared by the couple tools, gathering RSVPs and visitor
alerts, so the dashboard counts them one way and the privacy page
describes one thing.

  - One row per address and source. The address is matched on its
    normalised form (antiabuse normalize_email), so Ann.Lee+x@gmail.com
    and annlee@gmail.com are one lead.
  - A member is not a lead: record_lead writes nothing for an address that
    has an account and answers None.
  - Marketing consent is a ticked box, stored with the key of the wording
    shown. A later visit with the box unticked never withdraws it; the
    unsubscribe link does (scope 'news', service/unsubscribe), on every row
    of the address. A fresh tick after that is only pending: the form needs
    no proof of the address, so it counts once a confirm link issued after
    it is tapped (confirm_by_token).
  - A confirm link's token is stored only as its sha256. It works for
    CONFIRM_TTL and may be tapped more than once.
  - Rows go RETENTION_DAYS after last_seen_at, or a day after the confirm
    link lapsed if never confirmed (service/cron/leadretention), or with
    the member's account (service/hard_delete.py).

Every function takes the caller's transaction and never opens one, unless
its docstring says otherwise.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from antiabuse.antispam.signupemail import normalize_email
from service.leads.sources import is_lead_source

CONFIRM_TTL = timedelta(days=7)
RETENTION_DAYS = 365
CONFIRMED_VIA = ('otp', 'link')
_TOKEN_MIN, _TOKEN_MAX = 16, 64


def clean_email(email: object) -> Optional[tuple[str, str]]:
    """(lower-cased address, normalised address), or None for anything that
    is not plausibly an address."""
    if not isinstance(email, str):
        return None
    address = email.strip().lower()
    if address.count('@') != 1 or len(address) > 254 or any(c.isspace() for c in address):
        return None
    local, _, domain = address.partition('@')
    if not local or '.' not in domain:
        return None
    return address, normalize_email(address)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """An unguessable URL-safe token of 32 characters, and the hash to store."""
    token = secrets.token_urlsafe(24)
    return token, token_hash(token)


_Q_IS_MEMBER = """
    SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1
"""

_Q_UPSERT = """
    INSERT INTO lead (email, normalized_email, source, marketing_consent,
                      consent_wording, consented_at)
    VALUES (%(e)s, %(ne)s, %(src)s, %(mc)s, %(cw)s,
            CASE WHEN %(mc)s::boolean THEN NOW() END)
    ON CONFLICT (normalized_email, source) DO UPDATE SET
        email             = EXCLUDED.email,
        last_seen_at      = NOW(),
        marketing_consent = lead.marketing_consent
                            OR (EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL),
        consent_wording   = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL
                                 THEN EXCLUDED.consent_wording ELSE lead.consent_wording END,
        consented_at      = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NULL
                                 THEN NOW() ELSE lead.consented_at END,
        -- An unsubscribed address stays unsubscribed: whoever ticked the box
        -- has not proved the address is theirs. The tick waits here until a
        -- confirm link issued after it is tapped (_Q_CONFIRM_BY_TOKEN).
        consent_pending_wording = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NOT NULL
                                       THEN EXCLUDED.consent_wording ELSE lead.consent_pending_wording END,
        consent_pending_at      = CASE WHEN EXCLUDED.marketing_consent AND lead.unsubscribed_at IS NOT NULL
                                       THEN NOW() ELSE lead.consent_pending_at END
    RETURNING id
"""


def record_lead(tx, *, email: str, source: str, marketing_consent: bool = False,
                consent_wording: Optional[str] = None) -> Optional[int]:
    """Record (or refresh) the lead for this address and source and return
    its id, or None when the address belongs to a member. Raises ValueError
    'bad_source', 'bad_email' or 'consent_wording_required'."""
    if not is_lead_source(source):
        raise ValueError('bad_source')
    consent = marketing_consent is True
    if consent and not (isinstance(consent_wording, str) and consent_wording.strip()):
        raise ValueError('consent_wording_required')
    cleaned = clean_email(email)
    if cleaned is None:
        raise ValueError('bad_email')
    address, normalised = cleaned
    if tx.execute(_Q_IS_MEMBER, dict(ne=normalised)).fetchone():
        return None
    row = tx.execute(_Q_UPSERT, dict(e=address, ne=normalised, src=source, mc=consent,
                                     cw=consent_wording.strip() if consent else None)).fetchone()
    return row['id']


def confirm_lead(tx, lead_id: int, via: str) -> None:
    """The address is proved: by a sign-in code ('otp') or a link ('link').
    The first proof is the one kept."""
    if via not in CONFIRMED_VIA:
        raise ValueError('bad_via')
    tx.execute(
        """UPDATE lead SET confirmed_at = COALESCE(confirmed_at, NOW()),
                           confirmed_via = COALESCE(confirmed_via, %(via)s),
                           last_seen_at = NOW()
            WHERE id = %(id)s""",
        dict(id=lead_id, via=via))


def issue_confirm_token(tx, lead_id: int) -> str:
    """A new confirm token for the link in a confirmation email. Replaces
    any earlier one; only its hash is stored."""
    token, hashed = new_token()
    tx.execute(
        """UPDATE lead SET confirm_token_hash = %(h)s,
                           confirm_token_expires_at = NOW() + %(ttl)s
            WHERE id = %(id)s""",
        dict(h=hashed, ttl=CONFIRM_TTL, id=lead_id))
    return token


# A token was issued at confirm_token_expires_at - CONFIRM_TTL. Only one
# issued at or after a pending tick (record_lead on an unsubscribed address)
# turns that tick into consent and lifts the unsubscribe.
_Q_CONFIRM_BY_TOKEN = """
    UPDATE lead SET
        confirmed_at            = COALESCE(lead.confirmed_at, NOW()),
        confirmed_via           = COALESCE(lead.confirmed_via, 'link'),
        last_seen_at            = NOW(),
        marketing_consent       = lead.marketing_consent OR t.resume,
        consent_wording         = CASE WHEN t.resume THEN lead.consent_pending_wording
                                       ELSE lead.consent_wording END,
        consented_at            = CASE WHEN t.resume THEN NOW() ELSE lead.consented_at END,
        unsubscribed_at         = CASE WHEN t.resume THEN NULL ELSE lead.unsubscribed_at END,
        consent_pending_wording = CASE WHEN t.resume THEN NULL ELSE lead.consent_pending_wording END,
        consent_pending_at      = CASE WHEN t.resume THEN NULL ELSE lead.consent_pending_at END
      FROM (SELECT id,
                   (consent_pending_at IS NOT NULL
                    AND confirm_token_expires_at - %(ttl)s >= consent_pending_at) AS resume
              FROM lead
             WHERE confirm_token_hash = %(h)s AND confirm_token_expires_at > NOW()) AS t
     WHERE lead.id = t.id
    RETURNING lead.id
"""


def confirm_by_token(tx, token: object) -> Optional[int]:
    """The lead a confirm link names, now confirmed, or None for a token
    that is malformed, lapsed or was never issued. Tapping it again while it
    lasts answers the same lead. A token issued after a pending tick also
    turns that tick into consent and lifts the unsubscribe."""
    if not isinstance(token, str) or not _TOKEN_MIN <= len(token) <= _TOKEN_MAX:
        return None
    row = tx.execute(_Q_CONFIRM_BY_TOKEN, dict(h=token_hash(token), ttl=CONFIRM_TTL)).fetchone()
    return row['id'] if row else None


def touch_lead(tx, lead_id: int) -> None:
    """A visit: restarts the 12 month clock."""
    tx.execute('UPDATE lead SET last_seen_at = NOW() WHERE id = %(id)s', dict(id=lead_id))


def lead_unsubscribed(tx, lead_id: int) -> bool:
    """True when this lead has left the news mail, or no longer exists
    (fails towards not mailing)."""
    row = tx.execute('SELECT unsubscribed_at IS NOT NULL AS u FROM lead WHERE id = %(id)s',
                     dict(id=lead_id)).fetchone()
    return True if row is None else bool(row['u'])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_leads.py -q -p no:warnings`
Expected: `17 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/leads/__init__.py tests/test_leads.py
git -c user.email=admin@techbaseltd.com commit -m "feat(leads): record, confirm and refresh a lead, one per address and source" -m "Refs: TEC-1845"
```

---

### Task 4: Leads at sign-in and sign-up

**Files:**
- Modify: `duotypes/__init__.py:495` (`PostCheckOtp.source`)
- Modify: `service/person/__init__.py` (imports, after `from service import signupguard`; in `post_check_otp`, the block from the comment `# Qualified-lead attribution` through the onboardee `UPDATE` call that ends `dict(source=req.source, email=s.email),` and `)`; in `post_finish_onboarding`, before the comment `# Where the member came from (finding 42)`. Measured near lines 16, 551 to 565 and 937 on 16 Oct; hints only)
- Modify: `service/leads/__init__.py` (append `TOOL_LEADS_ENV`, `tool_leads_enabled` and `link_leads_to_person`)
- Modify: `docker-compose.production.yml` (the `api` service's `environment`, after `AHAVAH_PHOTO_GATE_ENABLED`)
- Modify: `tests/conftest.py` (`finish_onboarding._finish` gains `email`, lines 351 to 356)
- Test: `tests/test_lead_signup.py` (create)

**Interfaces:**
- Consumes: `record_lead`, `confirm_lead` (Task 3); `canonical_tool_source` (Task 2).
- Produces: `POST /check-otp` body `source` accepts `'marriage_checklist' | 'tool:game-me' | 'tool:game-us' | 'tool:knows-me' | 'tool:checklist'`; for a new address it stores the canonical value on `onboardee.lead_source` and, only while `tool_leads_enabled()`, a lead confirmed `via='otp'`. `service.leads.TOOL_LEADS_ENV = 'AHAVAH_TOOL_LEADS_ENABLED'`; `service.leads.tool_leads_enabled() -> bool`, read on every request, true for `1`, `true`, `yes` or `on`, off by default and in production until Task 14's paragraph is live. `service.leads.link_leads_to_person(tx, person_id: int) -> None`. Precedence of `person.lead_source`: onboardee tag, then the earliest confirmed lead, then the first touch. Fixture `finish_onboarding(body=None, lead_source=None, photo='pending', email=None)`.

The live marriage checklist already sends `source: "marriage_checklist"` to `/check-otp` (ahavah-web `checklist-client.tsx`), so recording leads there would start storing data, kept 12 months, that the privacy page does not yet describe and that the checklist page says is never stored. The switch keeps those writes off until the release that carries Task 14's paragraph and the checklist's new wording (see the release rule at the end of Task 14).

- [ ] **Step 1: Write the failing test**

In `tests/conftest.py`, change the `_finish` signature and its first line (lines 351 to 356):

```python
    def _finish(body: dict | None = None, lead_source: str | None = None,
                photo: str | None = 'pending', email: str | None = None):
        # `photo`: the moderation status of the one photo the onboardee
        # uploaded (an upload starts 'pending'), or None for no photo. The
        # server requires one to finish (finding 94). `email`: the address
        # to sign up with, when the test needs to prepare something for it.
        email = email or f'onboard-{uuid4()}@example.com'
```

Create `tests/test_lead_signup.py`:

```python
"""Leads at sign-in and sign-up (TEC-1845).

A couple tool confirms the player's address with the sign-in code the
marriage checklist already uses (/request-otp, /check-otp). That code is
the proof, so /check-otp records the tool's lead as confirmed. When the
player later finishes sign-up, their confirmed leads are linked to the new
member and name where they came from, ahead of the device's first touch;
the onboardee's own tag still comes first.

Recording a tool's lead at /check-otp is behind AHAVAH_TOOL_LEADS_ENABLED,
off until the privacy page describes it. These tests turn it on, except the
one that pins the off state.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx
from service.leads import confirm_lead, record_lead

pytestmark = pytest.mark.usefixtures('growth_schema')


@pytest.fixture(autouse=True)
def _tool_leads_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')


@pytest.fixture
def lead_emails():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=[m.lower() for m in made]))


def _leads_of(email: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT source, confirmed_at, confirmed_via, person_id, converted_at
                 FROM lead WHERE email = %(e)s ORDER BY id""",
            dict(e=email.lower())).fetchall()]


def _check(client, token: str, source):
    body = dict(otp='000000')
    if source is not None:
        body['source'] = source
    return client.post('/check-otp', json=body, headers={'Authorization': f'Bearer {token}'})


def _new_address(lead_emails) -> str:
    # A new example.com address is given 000000 in the dev environment the
    # tests run in, and is never mailed or looked up.
    email = f'tool-{uuid4().hex[:12]}@example.com'
    lead_emails.append(email)
    return email


def test_a_tool_player_confirming_by_code_becomes_a_confirmed_lead(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    r = _check(client, token, 'tool:game-us')
    assert r.status_code == 200, r.get_data(as_text=True)
    leads = _leads_of(email)
    assert [(x['source'], x['confirmed_via']) for x in leads] == [('tool:game-us', 'otp')]
    assert leads[0]['confirmed_at'] is not None and leads[0]['person_id'] is None
    with api_tx('read committed') as tx:
        tag = tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                         dict(e=email)).fetchone()['lead_source']
    assert tag == 'tool:game-us'


def test_the_checklist_old_name_is_stored_as_tool_checklist(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'marriage_checklist').status_code == 200
    assert [x['source'] for x in _leads_of(email)] == ['tool:checklist']
    with api_tx('read committed') as tx:
        tag = tx.execute('SELECT lead_source FROM onboardee WHERE email = %(e)s',
                         dict(e=email)).fetchone()['lead_source']
    assert tag == 'tool:checklist'


def test_a_member_signing_in_from_a_tool_is_not_a_lead(client, signup_env, make_person, lead_emails):
    person = make_person(name='ToolMember')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=person['id'])).fetchone()['email']
    lead_emails.append(email)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'tool:game-me').status_code == 200
    assert _leads_of(email) == []


def test_while_the_switch_is_off_the_live_checklist_records_no_lead(
        client, signup_env, lead_emails, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'marriage_checklist').status_code == 200
    assert _leads_of(email) == []


def test_a_sign_in_with_no_source_records_no_lead(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, None).status_code == 200
    assert _leads_of(email) == []


def test_an_unknown_source_is_refused(client, signup_env, lead_emails):
    email = _new_address(lead_emails)
    token = signup_env.request(email).get_json()['session_token']
    assert _check(client, token, 'tool:roulette').status_code == 400
    assert _leads_of(email) == []


def _confirmed_lead(email: str, source: str) -> int:
    with api_tx() as tx:
        lead_id = record_lead(tx, email=email, source=source)
        confirm_lead(tx, lead_id, 'link')
    return lead_id


def test_finishing_sign_up_links_the_lead_and_takes_its_source(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    _confirmed_lead(email, 'event:sukkot-2027')
    r, pid = finish_onboarding(dict(first_touch={'utm_source': 'instagram'}), email=email)
    assert r.status_code == 200, r.get_data(as_text=True)
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'event:sukkot-2027'
    [lead] = _leads_of(email)
    assert lead['person_id'] == pid and lead['converted_at'] is not None


def test_an_unconfirmed_lead_neither_links_nor_names_the_source(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    with api_tx() as tx:
        record_lead(tx, email=email, source='alert:visitor')
    r, pid = finish_onboarding(dict(first_touch={'utm_source': 'instagram'}), email=email)
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'utm:instagram'
    assert _leads_of(email)[0]['person_id'] is None


def test_the_onboardees_own_tag_comes_before_a_lead(finish_onboarding, lead_emails):
    email = f'onboard-{uuid4()}@example.com'
    lead_emails.append(email)
    _confirmed_lead(email, 'event:sukkot-2027')
    r, pid = finish_onboarding({}, lead_source='tool:checklist', email=email)
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        source = tx.execute('SELECT lead_source FROM person WHERE id = %(i)s',
                            dict(i=pid)).fetchone()['lead_source']
    assert source == 'tool:checklist'
    assert _leads_of(email)[0]['person_id'] == pid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_signup.py -q -p no:warnings`
Expected: 5 fail. `test_a_tool_player_confirming_by_code...` answers 400 (the Literal refuses `tool:game-us`); `test_a_member_signing_in_from_a_tool...` answers 400 too (the Literal refuses `tool:game-me`); the checklist test fails on `[] == ['tool:checklist']`; `test_finishing_sign_up_links...` reads `utm:instagram`; `test_the_onboardees_own_tag...` finds the lead unlinked. The switch-off, no-source, unknown-source and unconfirmed-lead tests pass already, as controls.

- [ ] **Step 3: Write the implementation**

In `duotypes/__init__.py`, replace lines 493 to 495:

```python
    # Optional acquisition tag. Only stamped onto NEW onboardees (never
    # existing members): a couple tool's source, or the marriage
    # checklist's old name, which is stored as tool:checklist (TEC-1845).
    source: Optional[Literal['marriage_checklist', 'tool:game-me', 'tool:game-us',
                             'tool:knows-me', 'tool:checklist']] = None
```

In `service/person/__init__.py`, directly after the import line `from service import signupguard`:

```python
from service.leads import confirm_lead, record_lead, tool_leads_enabled
from service.leads.sources import canonical_tool_source
```

In `post_check_otp`, replace the whole attribution block. It starts at the comment `# Qualified-lead attribution: tag NEW onboardees created via a` and ends with the `tx.execute(...)` call whose last argument is `dict(source=req.source, email=s.email),`, including that call's closing `)`. It sits after `tx.execute(Q_UPDATE_LAST, dict(person_uuid=row['person_uuid']))` and before `signupguard.record_entered(s.session_token_hash)`. Leave the club join and `clubs = tx.execute(Q_GET_SESSION_CLUBS, club_params).fetchone()` above it untouched. The replacement:

```python
        # Qualified-lead attribution: tag NEW onboardees created via a
        # tagged flow (a couple tool or the marriage checklist). Existing
        # members (person_id set) and already-tagged rows are untouched,
        # so an organic lead is never downgraded. The code just entered
        # proves the address, so the tool's lead is recorded confirmed
        # (TEC-1845, service/leads), but only once the privacy page says
        # so: AHAVAH_TOOL_LEADS_ENABLED stays off until then.
        source = canonical_tool_source(req.source)
        if source and row['person_id'] is None:
            tx.execute(
                """
                UPDATE onboardee
                   SET lead_source = %(source)s
                 WHERE email = %(email)s
                   AND lead_source IS NULL
                """,
                dict(source=source, email=s.email),
            )
            if tool_leads_enabled():
                lead_id = record_lead(tx, email=s.email, source=source)
                if lead_id is not None:
                    confirm_lead(tx, lead_id, 'otp')
```

In `post_finish_onboarding`, insert immediately before the comment line `# Where the member came from (finding 42): the first touch and the` (after the `attribute_signup(tx, row['person_id'], req.spotlight_ref)` call):

```python
        # A confirmed lead's source (a tool, an RSVP, an alert) comes before
        # the first touch: it was recorded on the server against this very
        # address, where the touch lives on one device (TEC-1845). The
        # onboardee's own tag, already copied onto the person, comes first.
        # Never fails the sign-up.
        from service.leads import link_leads_to_person
        link_leads_to_person(tx, row['person_id'])

```

Append to `service/leads/__init__.py` (and add `import os` to its imports):

```python
# The live marriage checklist, and later the couple tools, confirm an
# address with a sign-in code. Recording that as a lead stores data the
# privacy page must describe first, so it is off until the release that
# carries that paragraph (TEC-1845, plan Task 14). Read on every request, as
# service/photo_gate.py reads its switch, so a test can flip it and a
# restart is all production needs.
TOOL_LEADS_ENV = 'AHAVAH_TOOL_LEADS_ENABLED'


def tool_leads_enabled() -> bool:
    return os.environ.get(TOOL_LEADS_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


_Q_LINK = """
    UPDATE lead SET person_id = %(pid)s, converted_at = NOW(), last_seen_at = NOW()
     WHERE normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
       AND confirmed_at IS NOT NULL
       AND person_id IS NULL
"""

_Q_SOURCE_FROM_LEADS = """
    UPDATE person
       SET lead_source = COALESCE(lead_source, (
             SELECT source FROM lead WHERE person_id = %(pid)s
              ORDER BY created_at, id LIMIT 1))
     WHERE id = %(pid)s
"""


def link_leads_to_person(tx, person_id: int) -> None:
    """At finish-onboarding: the new member's confirmed leads point at them,
    and the earliest names where they came from unless the onboardee already
    carried a tag. Rolled back to a savepoint and ignored on any failure, so
    it can never undo the sign-up."""
    tx.execute('SAVEPOINT link_leads')
    try:
        tx.execute(_Q_LINK, dict(pid=person_id))
        tx.execute(_Q_SOURCE_FROM_LEADS, dict(pid=person_id))
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT link_leads')
    else:
        tx.execute('RELEASE SAVEPOINT link_leads')
```

In `docker-compose.production.yml`, in the `api` service's `environment`, directly after `AHAVAH_PHOTO_GATE_ENABLED: ${AHAVAH_PHOTO_GATE_ENABLED:-0}`:

```yaml
      # Leads from a sign-in code on the checklist or a couple tool
      # (TEC-1845, service/leads). Off until the privacy page's "Before you
      # join" paragraph and the checklist's new wording are live; 1 turns
      # it on.
      AHAVAH_TOOL_LEADS_ENABLED: ${AHAVAH_TOOL_LEADS_ENABLED:-0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_signup.py tests/test_onboarding_attribution.py tests/test_otp_request_metric.py -q -p no:warnings`
Expected: all pass (9 new, the attribution and code-metric suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add duotypes/__init__.py service/person/__init__.py service/leads/__init__.py docker-compose.production.yml tests/conftest.py tests/test_lead_signup.py
git -c user.email=admin@techbaseltd.com commit -m "feat(leads): a tool's sign-in code confirms its lead, and sign-up links it" -m "Refs: TEC-1845"
```

---

### Task 5: Mail for a lead

**Files:**
- Modify: `service/campaigns/outbox.py` (imports; new `_Q_ENQUEUE_FOR_LEAD` and `enqueue_for_lead` after `enqueue`; `mark_accepted`; `_refusal`)
- Modify: `service/unsubscribe/__init__.py` (imports; line 24 `_SCOPES`; `_Q_UNSUB`; `stamp_unsubscribed`)
- Modify: `service/leads/__init__.py` (append `news_refusal` and `mail_refusal`)
- Modify: `tests/conftest.py` (`outbox_drain._drain`, lines 311 to 315)
- Test: `tests/test_lead_mail.py` (create)

**Interfaces:**
- Consumes: `clean_email`, `record_lead`, `confirm_lead` (Task 3); `normalize_email`; `email_outbox.lead_id` (Task 1); `service.signupguard.new_address_refusal(*, normalized_email, ip, stamp=None, listed_bad=False) -> Optional[str]`, `signupguard.on_bad_domain_list(email) -> bool`.
- Produces: `service.leads.news_refusal(tx, lead_id: int, *, requested: bool = False) -> Optional[str]` returning `'unsubscribed' | 'unconfirmed' | 'no_consent' | None`. `service.campaigns.outbox.enqueue_for_lead(tx, *, campaign: str, campaign_id: str, lead_id: int, email: str, subject: str, html: str, from_addr: Optional[str], list_unsubscribe: Optional[str] = None, marketing: bool = False, requested: bool = False, not_before: Optional[datetime] = None) -> Optional[int]` (row id, or None when this lead already has this run or, for `marketing=True`, when `news_refusal` refuses it). `requested=True` is passed only by the alerts feature for an `alert:visitor` lead's own alert: it lifts the `no_consent` refusal and nothing else. Lead rows are drained like member rows: an exempt row (`marketing=False`) is refused only for suppression; a marketing row is refused for suppression and again by `news_refusal` (unsubscribed, unconfirmed or no ticked box unless requested); no `email_send_log` row for a lead. Unsubscribe scope `'news'` (stamps every lead row of the normalised address). `service.leads.mail_refusal(*, email: str, ip: Optional[str], stamp: Optional[str] = None, website: Optional[str] = None) -> Optional[str]` returning `'honeypot' | 'bad_email' | 'stamp_forged' | 'stamp_too_fast' | 'stamp_expired' | 'stamp_missing' | 'ip_hour' | 'ip_day' | 'network_day' | 'network_addresses' | 'bad_domain' | 'no_mx' | None`.

- [ ] **Step 1: Write the failing test**

In `tests/conftest.py`, replace lines 311 to 315, the whole `with api_tx() as tx:` block at the start of `outbox_drain._drain` (the `with` line and its `tx.execute(...)` parking statement), with:

```python
        with api_tx() as tx:
            tx.execute(
                """UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                    WHERE state = 'queued'
                      AND (person_id IS NULL OR NOT (person_id = ANY(%(ids)s)))""",
                dict(ids=list(person_ids)))
```

Create `tests/test_lead_mail.py`:

```python
"""Mail for a lead (TEC-1845).

A lead has no person row, so its mail rides the same outbox with lead_id in
place of person_id: queued once per run, drained by the one drain, refused
for a suppressed address. News mail goes only to a lead whose address is
confirmed and who ticked the box (or, for an alert, asked for it), and
stops once the lead has left it. A confirmation the visitor asked for still
goes. No member send log is written for a lead, since it is keyed on a
person.

Confirmation emails to strangers draw complaints, so a lead flow asks
mail_refusal first: the free defences sign-in codes already have.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import outbox
from service.leads import confirm_lead, mail_refusal, record_lead
from service.unsubscribe import make_token, stamp_unsubscribed

pytestmark = pytest.mark.usefixtures('growth_schema')

CAMPAIGN = 'test-lead-mail'


class _StubSmtp:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, **kw):
        self.sent.append(kw)
        return f'mid-{len(self.sent)}'


@pytest.fixture
def lead():
    """A mailable lead (ahavah-test.invalid is not suppressed), deleted with
    its mail afterwards. `consent` ticks the news box; `confirmed` proves
    the address."""
    made: list[str] = []

    def _make(source: str = 'alert:visitor', *, consent: bool = False,
              confirmed: bool = False) -> tuple[int, str]:
        email = f'leadmail-{uuid4().hex[:10]}@ahavah-test.invalid'
        made.append(email)
        with api_tx() as tx:
            lead_id = record_lead(tx, email=email, source=source, marketing_consent=consent,
                                  consent_wording='test-2026-11' if consent else None)
            if confirmed:
                confirm_lead(tx, lead_id, 'link')
        return lead_id, email

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _queue(lead_id, email, *, run='run-1', marketing=False, requested=False):
    with api_tx() as tx:
        return outbox.enqueue_for_lead(
            tx, campaign=CAMPAIGN, campaign_id=run, lead_id=lead_id, email=email,
            subject='Please confirm', html='<p>Confirm</p>', from_addr=None,
            marketing=marketing, requested=requested)


def _insert_news_row(lead_id: int, email: str, run: str) -> int:
    """A news row written straight to the outbox, past enqueue_for_lead's own
    check, so the drain's re-check is what decides."""
    payload = dict(subject='News', html='<p>News</p>', from_addr=None, list_unsubscribe=None,
                   post_send=None, cap_days=0, requires_spotlight_opt_in=False, requested=False)
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO email_outbox (campaign, campaign_id, lead_id, email, payload, exempt,
                                         unsub_scope)
               VALUES (%(c)s, %(r)s, %(l)s, %(e)s, %(p)s::jsonb, FALSE, 'news') RETURNING id""",
            dict(c=CAMPAIGN, r=run, l=lead_id, e=email, p=json.dumps(payload))).fetchone()['id']


def _drain_only(lead_id: int) -> list[dict]:
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND lead_id IS DISTINCT FROM %(l)s""",
                   dict(l=lead_id))
    smtp = _StubSmtp()
    outbox.drain(api_tx, smtp)
    return smtp.sent


def _state(row_id: int) -> tuple[str, str]:
    with api_tx('read committed') as tx:
        r = tx.execute('SELECT state, last_error FROM email_outbox WHERE id = %(i)s',
                       dict(i=row_id)).fetchone()
    return r['state'], r['last_error']


def test_lead_mail_is_queued_once_per_run(lead):
    lead_id, email = lead()
    assert _queue(lead_id, email) is not None
    assert _queue(lead_id, email) is None
    assert _queue(lead_id, email, run='run-2') is not None


def test_the_drain_sends_lead_mail_and_writes_no_member_send_log(lead):
    lead_id, email = lead()
    row_id = _queue(lead_id, email)
    sent = _drain_only(lead_id)
    assert [s['to_addr'] for s in sent] == [email]
    assert _state(row_id)[0] == 'accepted'
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM email_send_log WHERE campaign = %(c)s',
                       dict(c=CAMPAIGN)).fetchone()['n']
    assert n == 0


def test_news_to_a_lead_that_left_is_skipped_but_a_confirmation_still_goes(lead):
    lead_id, email = lead(consent=True, confirmed=True)
    news = _queue(lead_id, email, run='news-1', marketing=True)
    confirmation = _queue(lead_id, email, run='confirm-1')
    with api_tx() as tx:
        stamp_unsubscribed(tx, 'news', email)
    sent = _drain_only(lead_id)
    assert _state(news) == ('skipped', 'unsubscribed')
    assert _state(confirmation)[0] == 'accepted'
    assert len(sent) == 1


def test_news_to_a_lead_who_never_ticked_the_box_is_refused(lead):
    # Every tool player is such a lead: the tools have no news box.
    lead_id, email = lead('tool:game-me', confirmed=True)
    assert _queue(lead_id, email, run='news-1', marketing=True) is None
    row_id = _insert_news_row(lead_id, email, 'news-2')
    _drain_only(lead_id)
    assert _state(row_id) == ('skipped', 'no_consent')
    alert_id, alert_email = lead('alert:visitor', confirmed=True)
    asked = _queue(alert_id, alert_email, run='alert-1', marketing=True, requested=True)
    assert asked is not None, 'an alert the visitor asked for needs no news box'
    _drain_only(alert_id)
    assert _state(asked)[0] == 'accepted'


def test_news_to_a_ticked_but_unconfirmed_lead_is_refused(lead):
    # Anyone can type someone else's address into a form and tick the box.
    lead_id, email = lead(consent=True)
    assert _queue(lead_id, email, run='news-1', marketing=True) is None
    assert _queue(lead_id, email, run='alert-1', marketing=True, requested=True) is None
    row_id = _insert_news_row(lead_id, email, 'news-2')
    _drain_only(lead_id)
    assert _state(row_id) == ('skipped', 'unconfirmed')


def test_an_exempt_confirmation_to_an_unconfirmed_lead_still_goes(lead):
    lead_id, email = lead()
    row_id = _queue(lead_id, email, run='confirm-1')
    sent = _drain_only(lead_id)
    assert _state(row_id)[0] == 'accepted'
    assert [s['to_addr'] for s in sent] == [email]


def test_the_unsubscribe_link_reaches_every_row_of_the_address(client, lead):
    first_id, email = lead('alert:visitor')
    with api_tx() as tx:
        second_id = record_lead(tx, email=email, source='event:sukkot-2027')
    r = client.post(f"/u/{make_token('news', email)}")
    assert r.status_code == 200
    with api_tx('read committed') as tx:
        stamped = tx.execute(
            'SELECT count(*) AS n FROM lead WHERE id = ANY(%(i)s) AND unsubscribed_at IS NOT NULL',
            dict(i=[first_id, second_id])).fetchone()['n']
    assert stamped == 2


def test_the_unsubscribe_link_reaches_the_address_however_it_was_typed(client):
    name = f'ann{uuid4().hex[:8]}'
    plain = f'{name}@gmail.com'
    variant = f'{name[:3]}.{name[3:]}+news@gmail.com'
    with api_tx() as tx:
        first_id = record_lead(tx, email=variant, source='alert:visitor')
        second_id = record_lead(tx, email=plain, source='event:sukkot-2027')
    try:
        assert client.post(f"/u/{make_token('news', variant)}").status_code == 200
        with api_tx('read committed') as tx:
            stamped = tx.execute(
                'SELECT count(*) AS n FROM lead WHERE id = ANY(%(i)s) AND unsubscribed_at IS NOT NULL',
                dict(i=[first_id, second_id])).fetchone()['n']
        assert stamped == 2
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE normalized_email = %(ne)s', dict(ne=plain))


def test_member_mail_still_writes_its_send_log(make_person):
    person = make_person(name='OutboxControl', email=f'oc-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx() as tx:
        row_id = outbox.enqueue(
            tx, campaign=CAMPAIGN, campaign_id='member-1', person_id=person['id'],
            email=f'oc-control@ahavah-test.invalid', subject='s', html='<p>h</p>',
            from_addr=None, unsub_scope='campaigns', exempt=True)
    with api_tx() as tx:
        tx.execute("""UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                       WHERE state = 'queued' AND id <> %(i)s""", dict(i=row_id))
    outbox.drain(api_tx, _StubSmtp())
    with api_tx('read committed') as tx:
        n = tx.execute("""SELECT count(*) AS n FROM email_send_log
                           WHERE person_id = %(p)s AND campaign = %(c)s""",
                       dict(p=person['id'], c=CAMPAIGN)).fetchone()['n']
    assert n == 1


def test_a_filled_hidden_field_is_refused(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1',
                        website='https://spam.example') == 'honeypot'


def test_a_forged_stamp_is_refused(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1',
                        stamp='123.abc') == 'stamp_forged'


def test_a_domain_that_takes_no_mail_is_refused(signup_env):
    signup_env.dns['nomail-lead.example'] = False
    assert mail_refusal(email=f'x{uuid4().hex[:6]}@nomail-lead.example',
                        ip='10.184.8.1') == 'no_mx'


def test_one_client_asking_too_often_is_refused(signup_env):
    # A public address, as tests/test_signup_new_address_limits.py uses:
    # private ones, and the documentation ranges Python counts as private,
    # are exempt from the limits.
    email = signup_env.new_email()
    answers = [mail_refusal(email=email, ip='45.33.10.8') for _ in range(6)]
    assert answers[:5] == [None] * 5
    assert answers[5] == 'ip_hour'


def test_a_plausible_request_is_let_through(signup_env):
    assert mail_refusal(email=signup_env.new_email(), ip='10.184.8.1') is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_mail.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'mail_refusal' from 'service.leads'`.

- [ ] **Step 3: Write the implementation**

In `service/campaigns/outbox.py`, add to the imports (after `from service.campaigns import campaign_unsubscribed, can_send, log_send`):

```python
from service.leads import news_refusal
```

Add after `_Q_ENQUEUE`:

```python
# Lead mail (TEC-1845): the same table with lead_id in place of person_id.
# Its own partial unique index (migration 0066) is the idempotency point.
_Q_ENQUEUE_FOR_LEAD = """
    INSERT INTO email_outbox (campaign, campaign_id, lead_id, email, payload, exempt, unsub_scope,
                              next_attempt_at)
    VALUES (%(c)s, %(cid)s, %(lid)s, %(email)s, %(payload)s, %(exempt)s, 'news',
            COALESCE(%(at)s, NOW()))
    ON CONFLICT (campaign, campaign_id, lead_id) WHERE lead_id IS NOT NULL DO NOTHING
    RETURNING id
"""
```

Add after the `enqueue` function:

```python
def enqueue_for_lead(tx, *, campaign: str, campaign_id: str, lead_id: int, email: str,
                     subject: str, html: str, from_addr: Optional[str],
                     list_unsubscribe: Optional[str] = None, marketing: bool = False,
                     requested: bool = False,
                     not_before: Optional[datetime] = None) -> Optional[int]:
    """Queue one message for a lead: someone with no account who gave an
    email (service/leads). Returns the new row id, or None when this exact
    (campaign, campaign_id, lead_id) is already in the outbox or, for
    marketing mail, when service.leads.news_refusal refuses it.

    `marketing` is False for mail the visitor asked for in that very request
    (a confirmation, a reminder of a gathering they said they would attend),
    which goes even after they leave the news mail, and True for news (an
    alert, gatherings near them). News goes only to a confirmed address
    whose box was ticked, and stops once the lead leaves it. `requested` is
    True only for an alert:visitor lead's own alert: the visitor asked for
    that mail, so it needs no ticked box, though it still needs a confirmed
    address. The drain checks all of this again (_refusal). A lead has no
    frequency cap, no send log and no post-send hook: all three are keyed
    on a member."""
    if marketing and news_refusal(tx, lead_id, requested=requested):
        return None
    payload = dict(subject=subject, html=html, from_addr=from_addr,
                   list_unsubscribe=list_unsubscribe, post_send=None, cap_days=0,
                   requires_spotlight_opt_in=False, requested=requested is True)
    row = tx.execute(_Q_ENQUEUE_FOR_LEAD, dict(
        c=campaign, cid=campaign_id, lid=lead_id, email=email,
        payload=json.dumps(payload), exempt=not marketing, at=not_before)).fetchone()
    return row['id'] if row else None
```

In `mark_accepted`, insert after `if not row: return`:

```python
    # Lead mail (TEC-1845) has no member: the send log and the hooks are
    # keyed on person_id. The accepted outbox row is its record.
    if row['person_id'] is None:
        return
```

In `_refusal`, insert directly after `payload = row['payload'] or {}`:

```python
    # Lead mail (TEC-1845): there is no member to read consent, campaign
    # scopes or caps from. Suppression applies to every address. Mail the
    # visitor asked for (exempt) still goes; news is re-checked here as at
    # enqueue: refused once the lead has left it, while the address is
    # unconfirmed, and without a ticked box unless the visitor requested it.
    if row.get('lead_id') is not None:
        if is_suppressed_send(row['email']):
            return 'suppressed'
        if not row['exempt']:
            return news_refusal(tx, row['lead_id'], requested=payload.get('requested') is True)
        return None
```

In `service/unsubscribe/__init__.py`, line 24:

```python
_SCOPES = ("waitlist", "beta", "notifications", "claim", "community", "campaigns", "news")
```

and add to `_Q_UNSUB`, after the `"campaigns"` entry:

```python
    # News for leads (TEC-1845, service/leads): an address with no account
    # that ticked a box at a gathering RSVP or asked for a visitor alert.
    # Every row of the address is stamped, whichever box the link came from
    # and however the address was typed on each (dots, a plus tag,
    # googlemail): a lead is keyed on its normalised address.
    "news": """
        UPDATE lead
           SET unsubscribed_at = COALESCE(unsubscribed_at, NOW())
         WHERE normalized_email = %(ne)s
        RETURNING id
    """,
```

Add to the imports of `service/unsubscribe/__init__.py`:

```python
from antiabuse.antispam.signupemail import normalize_email
```

and in `stamp_unsubscribed`, replace the line `row = tx.execute(_Q_UNSUB[scope], dict(email=email.strip().lower())).fetchone()` with:

```python
    params = dict(email=email.strip().lower())
    if scope == 'news':
        params['ne'] = normalize_email(params['email'])
    row = tx.execute(_Q_UNSUB[scope], params).fetchone()
```

Append to `service/leads/__init__.py`:

```python
def news_refusal(tx, lead_id: int, *, requested: bool = False) -> Optional[str]:
    """Why news (mail the visitor did not ask for in that very request) may
    not go to this lead, or None to send it. Checked at enqueue and again at
    send (service/campaigns/outbox.py).

      'unsubscribed'  the lead has left the news mail, or no longer exists
                      (fails towards not mailing)
      'unconfirmed'   the address never proved itself: anyone can type an
                      address into a form, so nothing goes to it unasked
      'no_consent'    the unticked box is the only answer the visitor gave
                      (events spec: the box is the only marketing consent;
                      owner, 13 Oct: no cold outreach). `requested` lifts
                      this one refusal: an alert:visitor lead's own alert is
                      mail the visitor asked for."""
    row = tx.execute(
        """SELECT unsubscribed_at, confirmed_at, marketing_consent
             FROM lead WHERE id = %(id)s""",
        dict(id=lead_id)).fetchone()
    if row is None or row['unsubscribed_at'] is not None:
        return 'unsubscribed'
    if row['confirmed_at'] is None:
        return 'unconfirmed'
    if not row['marketing_consent'] and requested is not True:
        return 'no_consent'
    return None


def mail_refusal(*, email: str, ip: Optional[str], stamp: Optional[str] = None,
                 website: Optional[str] = None) -> Optional[str]:
    """Why a confirmation email to this address should not be sent, or None
    to send it. The free defences sign-in codes for new addresses already
    have (service/signupguard; owner, 13 Oct: free only): the hidden
    `website` field, the page stamp, the per-address and per-network limits,
    the bad-domain list and the mail-domain check. They count against the
    same per-network budget as sign-in codes. The caller answers a refusal
    exactly as it answers a send, so a refused caller learns nothing.

    Opens its own read (the bad-domain list): call it before the caller's
    transaction, never inside one."""
    if website:
        return 'honeypot'
    cleaned = clean_email(email)
    if cleaned is None:
        return 'bad_email'
    _, normalised = cleaned
    from service import signupguard
    return signupguard.new_address_refusal(
        normalized_email=normalised, ip=ip, stamp=stamp,
        listed_bad=signupguard.on_bad_domain_list(normalised))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_mail.py tests/test_campaigns.py tests/test_campaign_runner.py tests/test_unsubscribe_routes.py tests/test_unsubscribe_campaigns.py -q -p no:warnings`
Expected: all pass (14 new; the campaign and unsubscribe suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/campaigns/outbox.py service/unsubscribe/__init__.py service/leads/__init__.py tests/conftest.py tests/test_lead_mail.py
git -c user.email=admin@techbaseltd.com commit -m "feat(outbox): mail for a lead goes through the outbox, with its own unsubscribe and bot rules" -m "Refs: TEC-1845"
```

---

### Task 6: Deleting leads after 12 months and with an account

**Files:**
- Create: `service/cron/leadretention/__init__.py`
- Modify: `service/cron/__init__.py` (import and `asyncio.gather` entry)
- Modify: `service/hard_delete.py` (append `Q_DELETE_LEADS_OF`)
- Modify: `service/cron/pendingdeletion/__init__.py` (import list lines 19 to 25; after line 172)
- Modify: `service/api/admin/users_action_routes.py` (import list near line 37; after line 318)
- Test: `tests/test_lead_retention.py` (create)

**Interfaces:**
- Consumes: `RETENTION_DAYS`, `CONFIRM_TTL` (Task 3); `normalize_email`; `hard_delete_expired_once()` (pendingdeletion); `DELETE /admin/users/<uuid>`.
- Produces: `service.cron.leadretention.purge_stale_leads(tx) -> int` (a lead unseen for `RETENTION_DAYS`, or never confirmed and created more than `CONFIRM_TTL` plus 1 day ago); `lead_retention_forever() -> Coroutine`; `service.hard_delete.Q_DELETE_LEADS_OF` (bind `nes: list[str]`, each address passed through `normalize_email` by the caller).

- [ ] **Step 1: Write the failing test**

Create `tests/test_lead_retention.py`:

```python
"""Leads go 12 months after the last visit, or with the account (TEC-1845).

The specs promise: "Rows are deleted 12 months after the last visit, or on
request." A lead linked at sign-up goes with the person row; one that never
was (unconfirmed, or from a flow the member used before joining) is found
by its normalised address, however it was typed. Both hard deletes, the
deletion cron and the admin's, do it. An address nobody confirmed goes a
day after its confirm link lapsed: it has no use once that link is dead.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from typing import Optional
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import outbox
from service.cron.leadretention import purge_stale_leads
from service.cron.pendingdeletion import hard_delete_expired_once

pytestmark = pytest.mark.usefixtures('growth_schema')


def _insert_lead(tx, email: str, source: str, *, person_id=None, days_since_visit: int = 0,
                 days_since_created: int = 0, confirmed: bool = False,
                 normalized: Optional[str] = None) -> int:
    return tx.execute(
        """INSERT INTO lead (email, normalized_email, source, person_id, last_seen_at,
                             created_at, confirmed_at)
           VALUES (%(e)s, %(ne)s, %(s)s, %(p)s, NOW() - make_interval(days => %(d)s),
                   NOW() - make_interval(days => %(c)s), CASE WHEN %(conf)s THEN NOW() END)
           RETURNING id""",
        dict(e=email.lower(), ne=normalized or email.lower(), s=source, p=person_id,
             d=days_since_visit, c=days_since_created, conf=confirmed)).fetchone()['id']


def _exists(lead_id: int) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT 1 FROM lead WHERE id = %(i)s', dict(i=lead_id)).fetchone() is not None


def test_a_lead_unseen_for_a_year_goes_with_its_mail_and_a_recent_one_stays():
    stale_email = f'stale-{uuid4().hex[:10]}@ahavah-test.invalid'
    fresh_email = f'fresh-{uuid4().hex[:10]}@ahavah-test.invalid'
    with api_tx() as tx:
        stale = _insert_lead(tx, stale_email, 'alert:visitor', days_since_visit=366)
        fresh = _insert_lead(tx, fresh_email, 'alert:visitor', days_since_visit=364)
        mail = outbox.enqueue_for_lead(tx, campaign='test-retention', campaign_id='r1',
                                       lead_id=stale, email=stale_email, subject='s',
                                       html='<p>h</p>', from_addr=None)
    try:
        with api_tx() as tx:
            assert purge_stale_leads(tx) >= 1
        assert not _exists(stale)
        assert _exists(fresh)
        with api_tx('read committed') as tx:
            assert tx.execute('SELECT 1 FROM email_outbox WHERE id = %(i)s',
                              dict(i=mail)).fetchone() is None
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)',
                       dict(e=[stale_email, fresh_email]))


def test_an_address_never_confirmed_goes_once_its_link_has_lapsed():
    # Seen today, so only the unconfirmed rule can take it.
    lapsed_email = f'unproved-{uuid4().hex[:10]}@ahavah-test.invalid'
    proved_email = f'proved-{uuid4().hex[:10]}@ahavah-test.invalid'
    with api_tx() as tx:
        lapsed = _insert_lead(tx, lapsed_email, 'event:sukkot-2027', days_since_created=9)
        proved = _insert_lead(tx, proved_email, 'event:sukkot-2027', days_since_created=9,
                              confirmed=True)
    try:
        with api_tx() as tx:
            purge_stale_leads(tx)
        assert not _exists(lapsed)
        assert _exists(proved)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)',
                       dict(e=[lapsed_email, proved_email]))


def _email_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return tx.execute('SELECT email FROM person WHERE id = %(i)s',
                          dict(i=person_id)).fetchone()['email']


def test_the_deletion_cron_deletes_a_leavers_leads(make_person):
    p = make_person(name='LeadLeaver', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        linked = _insert_lead(tx, email, 'tool:game-me', person_id=p['id'])
        unlinked = _insert_lead(tx, email, 'event:sukkot-2027')
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))
    asyncio.run(hard_delete_expired_once())
    assert not _exists(linked)
    assert not _exists(unlinked)


def test_a_leavers_lead_typed_another_way_goes_too(make_person):
    name = f'leaver{uuid4().hex[:8]}'
    p = make_person(name='LeadLeaverGmail', gender='Woman', email=f'{name}@gmail.com')
    variant = f'{name[:3]}.{name[3:]}+tools@gmail.com'
    with api_tx() as tx:
        unlinked = _insert_lead(tx, variant, 'tool:game-me', normalized=f'{name}@gmail.com')
        tx.execute(
            "UPDATE person SET activated = FALSE, "
            "deletion_requested_at = NOW() - INTERVAL '8 days', "
            "sign_in_time = NOW() - INTERVAL '9 days' "
            "WHERE id = %(p)s", dict(p=p['id']))
    asyncio.run(hard_delete_expired_once())
    assert not _exists(unlinked)


def _admin_headers(make_person) -> dict:
    admin = make_person(name='LeadAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=admin['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=admin['id']))
    return {'Authorization': f'Bearer {tok}'}


def test_the_admin_hard_delete_deletes_the_members_leads(make_person, client):
    headers = _admin_headers(make_person)
    p = make_person(name='LeadAdminDeleted', gender='Woman')
    email = _email_of(p['id'])
    with api_tx() as tx:
        linked = _insert_lead(tx, email, 'tool:game-us', person_id=p['id'])
        unlinked = _insert_lead(tx, email, 'alert:visitor')
    r = client.delete(f"/admin/users/{p['uuid']}",
                      json={'confirm_email': email, 'reason': 'test'}, headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert not _exists(linked)
    assert not _exists(unlinked)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_retention.py -q -p no:warnings`
Expected: collection error, `ModuleNotFoundError: No module named 'service.cron.leadretention'`.

- [ ] **Step 3: Write the implementation**

Create `service/cron/leadretention/__init__.py`:

```python
"""Leads are deleted 12 months after their last visit (TEC-1845).

The growth specs promise it: "Rows are deleted 12 months after the last
visit, or on request." A visit is anything that records the lead again or
calls service.leads.touch_lead. An address nobody confirmed goes sooner, a
day after its confirm link lapsed: anyone can type an address into a form,
and anyone retyping it moves last_seen_at, so only created_at counts for
it. Mail queued for a deleted lead goes with it (email_outbox.lead_id
cascades). The feature plans add their own tables' sweeps here (tool
sessions, RSVPs, alerts), on the same clock. Daily.
"""
from __future__ import annotations

import asyncio
import random

from database import api_tx
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.leads import CONFIRM_TTL, RETENTION_DAYS

LEAD_RETENTION_POLL_SECONDS = env_int('DUO_CRON_LEAD_RETENTION_POLL_SECONDS', 60 * 60 * 24)

print(f'Hello from cron module: {__name__}')

_Q_PURGE = """
    DELETE FROM lead
     WHERE last_seen_at < NOW() - make_interval(days => %(days)s)
        OR (confirmed_at IS NULL AND created_at < NOW() - %(ttl)s - interval '1 day')
"""


def purge_stale_leads(tx) -> int:
    return tx.execute(_Q_PURGE, dict(days=RETENTION_DAYS, ttl=CONFIRM_TTL)).rowcount


def _purge_once() -> None:
    with api_tx() as tx:
        n = purge_stale_leads(tx)
    if n:
        print(f'lead_retention: {n} lead(s) deleted after {RETENTION_DAYS} days without a visit')


async def lead_retention_forever() -> None:
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_purge_once))
        await asyncio.sleep(LEAD_RETENTION_POLL_SECONDS)
```

In `service/cron/__init__.py`, add after the `referral_intro_forever` import:

```python
from service.cron.leadretention import lead_retention_forever
```

and add to the `asyncio.gather(...)` call, after `referral_intro_forever(),`:

```python
        # Leads (TEC-1845): deleted 12 months after their last visit, with
        # any mail still queued for them. Daily.
        lead_retention_forever(),
```

Append to `service/hard_delete.py`:

```python
# lead: an address given before joining (TEC-1845). A lead linked at
# sign-up cascades off person; one that never was (unconfirmed, or from
# another flow) is keyed on the address only. A lead's identity is its
# normalised address (service/leads), so the caller binds `nes`: each
# address passed through antiabuse normalize_email. Rows typed another way
# (dots, a plus tag, googlemail) go too.
Q_DELETE_LEADS_OF = """
    DELETE FROM lead WHERE normalized_email = ANY(%(nes)s::text[])
"""
```

In `service/cron/pendingdeletion/__init__.py`, add `Q_DELETE_LEADS_OF,` to the `from service.hard_delete import (...)` list, add the import `from antiabuse.antispam.signupemail import normalize_email`, and after line 172 (`await tx.execute(Q_DELETE_BETA_SIGNUP_OF, dict(emails=emails))`), inside the same `if emails:` block:

```python
                # Leads (TEC-1845): the linked ones went with the person
                # row; this takes the ones only the address names, however
                # it was typed.
                await tx.execute(Q_DELETE_LEADS_OF,
                                 dict(nes=[normalize_email(e) for e in emails]))
```

In `service/api/admin/users_action_routes.py`, add `Q_DELETE_LEADS_OF,` to the `from service.hard_delete import (...)` list (`normalize_email` is already imported there), and after line 318 (`tx.execute(Q_DELETE_BETA_SIGNUP_OF, ...)`), inside the same `if row['email']:` block:

```python
            tx.execute(Q_DELETE_LEADS_OF, dict(nes=[normalize_email(row['email'])]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_lead_retention.py tests/test_pendingdeletion.py -q -p no:warnings`
Expected: all pass (5 new, the pending deletion suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/cron/leadretention/__init__.py service/cron/__init__.py service/hard_delete.py service/cron/pendingdeletion/__init__.py service/api/admin/users_action_routes.py tests/test_lead_retention.py
git -c user.email=admin@techbaseltd.com commit -m "feat(leads): deleted 12 months after the last visit and with the account" -m "Refs: TEC-1845"
```

---

### Task 7: Three new publishing kinds, held to the owner's calendar

**Files:**
- Modify: `service/spotlight/queue.py:12-24` (kind constants)
- Modify: `service/spotlight/dispatch.py:23,113`
- Modify: `service/api/admin/spotlight_routes.py` (imports lines 50 to 55; `_Q_ROWS` lines 307 to 387; `_queue_row` lines 586 to 640; `get_growth_queue` line 656 to 658; image route line 857; `BRAND_CAPTION_MAX` line 1212; `_approval_slot` line 1308; retry lines 1700 to 1701; reschedule line 1729)
- Test: `tests/test_growth_kinds.py` (create)

**Interfaces:**
- Consumes: `create_candidate`, `slot_problem`, `is_beyond_known`, the image route, `claim_spotlight_posts`.
- Produces, in `service.spotlight.queue`: `KINDS` adds `'event', 'prompt', 'tool'`; `SUBJECTLESS_KINDS = ('roundup', 'brand', 'event', 'prompt', 'tool')`; `CALENDAR_HELD_KINDS = ('brand', 'event', 'prompt', 'tool')`; `TEMPLATE_KINDS = ('event', 'prompt')`; `CAPTION_MAX = 2000`. `GET /admin/growth/queue?template_render=1` lists rows of `TEMPLATE_KINDS` still waiting for artwork; `?needs_render=1` no longer lists any held kind. Each queue row gains `created_at: str`, `week: str | None` (ISO week of `scheduled_for`, `'2027-W01'`), `age_days: int | None`, and, for template kinds, `template_data: dict` (the row's payload).

- [ ] **Step 1: Write the failing test**

Create `tests/test_growth_kinds.py`:

```python
"""The scheduler's three new kinds: event, prompt and tool (TEC-1845).

Each is about nobody and held to the owner's calendar exactly as a brand
post is: portrait artwork only, a late approval rolls forward (an event
post moves earlier instead, tests/test_event_posts.py), nothing is
dispatched past the known calendar or on a rest day. The render tick draws
member cards and roundups only, so it must never be handed one of these;
event and prompt rows wait for their template renderer on a listing of
their own. Helpers are copied from tests/test_brand_posts.py on purpose:
test files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from PIL import Image

import service.spotlight.restdays as rd
from database import api_tx
from service.spotlight.dispatch import dispatch_check
from service.spotlight.queue import create_candidate, set_setting

pytestmark = pytest.mark.usefixtures('growth_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}
NEW_KINDS = ('event', 'prompt', 'tool')


def _jpeg(w=1080, h=1350) -> str:
    buf = io.BytesIO()
    Image.new('RGB', (w, h), 'white').save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _candidate(kind: str) -> str:
    with api_tx() as tx:
        return create_candidate(tx, kind=kind, subject_person_id=None, caption='c', created_by='t')


def _rows(rk: str) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id, kind, platform, status, subject_person_id, scheduled_for
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def _cancel(rk: str) -> None:
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET status = 'cancelled', updated_at = NOW()
                       WHERE request_key = %(rk)s
                         AND status IN ('scheduled', 'processing', 'review', 'awaiting_render', 'awaiting_member')""",
                   dict(rk=rk))


def _render(client, monkeypatch, rk, w=1080, h=1350):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    for platform in ('facebook', 'instagram'):
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform=platform, image_base64=_jpeg(w, h), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _admin_headers(make_person) -> dict:
    p = make_person(name='KindsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _listed(client, query: str) -> list[dict]:
    r = client.get(f'/admin/growth/queue?{query}', headers=H)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


@contextmanager
def _publication_on():
    with api_tx() as tx:
        set_setting(tx, 'publication_enabled', 'true')
        set_setting(tx, 'external_access_enabled', 'true')
    try:
        yield
    finally:
        with api_tx() as tx:
            set_setting(tx, 'publication_enabled', 'false')
            set_setting(tx, 'external_access_enabled', 'true')


def _claimed(tx, rk):
    tx.execute("""UPDATE publishing_queue SET status = 'scheduled',
                         scheduled_for = NOW() - interval '1 minute'
                   WHERE request_key = %(rk)s""", dict(rk=rk))
    return [r for r in tx.execute('SELECT * FROM claim_spotlight_posts(10)').fetchall()
            if r['request_key'] == rk]


@pytest.mark.parametrize('kind', NEW_KINDS)
def test_a_new_kind_is_about_nobody_and_waits_for_its_artwork(kind):
    rk = _candidate(kind)
    try:
        rows = _rows(rk)
        assert [r['platform'] for r in rows] == ['facebook', 'instagram']
        assert {(r['kind'], r['status'], r['subject_person_id']) for r in rows} == {
            (kind, 'awaiting_render', None)}
    finally:
        _cancel(rk)


@pytest.mark.parametrize('kind', NEW_KINDS)
def test_a_new_kind_with_a_subject_is_refused(kind, make_person):
    p = make_person(name='KindSubject')
    with pytest.raises(ValueError, match='roundup_has_no_subject'):
        with api_tx() as tx:
            create_candidate(tx, kind=kind, subject_person_id=p['id'], caption='c', created_by='t')


def test_the_tick_sees_none_of_them_and_the_template_listing_sees_event_and_prompt(client):
    keys = {kind: _candidate(kind) for kind in (*NEW_KINDS, 'roundup')}
    try:
        tick = {r['request_key'] for r in _listed(client, 'needs_render=1')}
        template = {r['request_key'] for r in _listed(client, 'template_render=1')}
        assert keys['roundup'] in tick, 'negative control: an artless roundup is listed'
        assert not {keys['event'], keys['prompt'], keys['tool']} & tick
        assert {keys['event'], keys['prompt']} <= template
        assert keys['tool'] not in template and keys['roundup'] not in template
    finally:
        for rk in keys.values():
            _cancel(rk)


@pytest.mark.parametrize('w,h,ok', [(1080, 1350, True), (1080, 1080, False)])
def test_a_new_kind_takes_portrait_artwork_only(client, monkeypatch, w, h, ok):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    rk = _candidate('tool')
    try:
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform='facebook', image_base64=_jpeg(w, h), content_type='image/jpeg'),
                        headers=H)
        if ok:
            assert r.status_code == 200, r.get_json()
        else:
            assert r.status_code == 400 and r.get_json() == dict(error='invalid_image', reason='bad_dimensions')
    finally:
        _cancel(rk)


def test_a_late_approval_of_a_new_kind_rolls_forward(client, monkeypatch, make_person):
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    headers = _admin_headers(make_person)
    rk = _candidate('tool')
    try:
        _render(client, monkeypatch, rk)
        with api_tx() as tx:
            tx.execute("UPDATE publishing_queue SET scheduled_for = NOW() - interval '2 days' WHERE request_key = %(rk)s",
                       dict(rk=rk))
        before = datetime.now(timezone.utc)
        r = client.post(f"/admin/growth/queue/{_rows(rk)[0]['id']}/approve", json={}, headers=headers)
        assert r.status_code == 200, r.get_json()
        slot = _rows(rk)[0]['scheduled_for']
        assert slot > before and rd.slot_problem(slot, before) is None
    finally:
        _cancel(rk)


def test_dispatch_refuses_a_new_kind_past_the_known_calendar(client, monkeypatch):
    rk = _candidate('event')
    try:
        _render(client, monkeypatch, rk)
        with _publication_on(), api_tx() as tx:
            rows = _claimed(tx, rk)
            assert len(rows) == 2
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (True, '')
            monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() - timedelta(days=2))
            for r in rows:
                assert dispatch_check(tx, r['id'], r['lease_token']) == (False, 'calendar_unknown')
    finally:
        _cancel(rk)


def test_the_queue_shows_week_age_and_template_data(client):
    event, tool = _candidate('event'), _candidate('tool')
    slot = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue SET scheduled_for = %(w)s,
                             payload = '{"title": "Sukkot gathering"}'::jsonb
                       WHERE request_key = ANY(%(k)s)""", dict(w=slot, k=[event, tool]))
    try:
        rows = {(r['request_key'], r['platform']): r for r in _listed(client, '')}
        e, t = rows[(event, 'facebook')], rows[(tool, 'facebook')]
        assert e['week'] == '2027-W01' and e['age_days'] == 0 and e['created_at']
        assert e['template_data'] == {'title': 'Sukkot gathering'}
        assert 'template_data' not in t
    finally:
        _cancel(event)
        _cancel(tool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_growth_kinds.py -q -p no:warnings`
Expected: the parametrised creation tests fail with `ValueError: bad_kind`; the others fail on the same error in `_candidate`.

- [ ] **Step 3: Write the implementation**

In `service/spotlight/queue.py`, replace line 12 and line 24:

```python
KINDS = ('welcome', 'roundup', 'member_of_week', 'highlight', 'brand', 'event', 'prompt', 'tool')
```

```python
SUBJECTLESS_KINDS = ('roundup', 'brand', 'event', 'prompt', 'tool')
# Kinds held to the owner's calendar at creation, approval, retry,
# reschedule and dispatch, whose artwork is portrait and never comes from
# the tick's renderer (TEC-945 for brand; TEC-1845 for the scheduler's
# own kinds: event, prompt and tool).
CALENDAR_HELD_KINDS = ('brand', 'event', 'prompt', 'tool')
# Held kinds whose artwork is drawn from a Claude Design template filled
# with the row's payload (growth spec, Scheduler). tool and brand arrive as
# finished artwork from the calendar run instead.
TEMPLATE_KINDS = ('event', 'prompt')
# Instagram's caption limit is 2,200 characters and create_candidate
# appends a campaign link of roughly forty. The margin is deliberate.
CAPTION_MAX = 2000
```

In `service/spotlight/dispatch.py`, line 23 becomes:

```python
from service.spotlight.queue import CALENDAR_HELD_KINDS, SUBJECTLESS_KINDS, settings
```

and line 113 becomes:

```python
    if row['kind'] in CALENDAR_HELD_KINDS and is_beyond_known(now):
```

In `service/api/admin/spotlight_routes.py`:

Imports (lines 50 to 55) become:

```python
from service.spotlight.queue import (CALENDAR_HELD_KINDS, CAPTION_MAX, TEMPLATE_KINDS,
                                     create_candidate,
                                     lock_request_rows, set_status, settings, set_setting,
                                     reap_expired_leases, reconcile_published,
                                     record_receipt, OUTCOMES,
                                     OUTCOME_DELIVERY_STATE, PLATFORMS,
                                     SETTING_KEYS, FREE_KEYS)
```

In `_Q_ROWS`, add `q.created_at,` after `q.request_key,` (line 309), and replace lines 356 to 373 with:

```python
       AND (%(needs_render)s::bool IS NOT TRUE
            OR (r.asset_hash IS NULL
                AND q.status NOT IN ('cancelled', 'published', 'processing', 'scheduled')
                -- A held kind's artwork never comes from the tick's
                -- renderer: brand and tool arrive from the calendar run,
                -- event and prompt from their template renderer below. The
                -- tick knows member cards and roundups only: handed a
                -- subject-less row with no tiles, it draws a roundup card
                -- reading "0 new members across 0 countries" (TEC-945).
                AND q.kind <> ALL(%(held)s::text[])))
       -- The template renderer's own listing (TEC-1845): event and prompt
       -- rows still waiting for artwork.
       AND (%(template_render)s::bool IS NOT TRUE
            OR (r.asset_hash IS NULL
                AND q.status NOT IN ('cancelled', 'published', 'processing', 'scheduled')
                AND q.kind = ANY(%(template)s::text[])))
       -- Wave 3d Task 4 (acceptance 8c): a card whose render was reported
       -- failed sits out its backoff (`post_growth_queue_render_failed`), so
       -- one that keeps failing cannot hold a place in either render listing.
       AND ((%(needs_render)s::bool IS NOT TRUE AND %(template_render)s::bool IS NOT TRUE)
            OR q.render_next_attempt_at IS NULL
            OR q.render_next_attempt_at <= NOW())
```

Add two helpers above `_queue_row`:

```python
def _iso_week(v: Optional[datetime]) -> Optional[str]:
    """The ISO week a slot falls in, as the Growth tab groups posts."""
    if v is None:
        return None
    year, week, _ = v.astimezone(timezone.utc).isocalendar()
    return f'{year}-W{week:02d}'


def _age_days(v: Optional[datetime]) -> Optional[int]:
    if v is None:
        return None
    return (datetime.now(timezone.utc) - v).days
```

In `_queue_row`, add to the `row = dict(...)` after `request_key=r['request_key'],`:

```python
        created_at=_plain(r['created_at']),
        week=_iso_week(r['scheduled_for']),
        age_days=_age_days(r['created_at']),
```

and after the roundup payload block (after line 639):

```python
    # The data a template kind's renderer fills its Claude Design template
    # with (TEC-1845). Every other kind leaves the key out.
    if r['kind'] in TEMPLATE_KINDS and r['payload']:
        row['template_data'] = r['payload']
```

In `get_growth_queue`, replace lines 656 to 658:

```python
    needs_render = request.args.get('needs_render') in ('1', 'true', 'yes')
    template_render = request.args.get('template_render') in ('1', 'true', 'yes')
    with api_tx('read committed') as tx:
        rows = tx.execute(_Q_ROWS, dict(status=status, due=due, needs_render=needs_render,
                                        template_render=template_render,
                                        held=list(CALENDAR_HELD_KINDS),
                                        template=list(TEMPLATE_KINDS))).fetchall()
```

Image route, line 857: `    if known['kind'] in CALENDAR_HELD_KINDS:` (update the comment above it to read "A held kind's artwork is drawn at 1080x1350 ...").

Line 1212: `BRAND_CAPTION_MAX = CAPTION_MAX` (delete the two comment lines above it that `CAPTION_MAX` now carries).

`_approval_slot`, line 1308: `    if kind not in CALENDAR_HELD_KINDS:`

Retry, lines 1700 to 1701:

```python
        if row and row['kind'] in CALENDAR_HELD_KINDS:
            when, problem = _approval_slot(row['kind'], None, row['scheduled_for'])
```

Reschedule, line 1729: `        if kind and kind['kind'] in CALENDAR_HELD_KINDS:`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_growth_kinds.py tests/test_brand_posts.py tests/test_spotlight_dispatch.py -q -p no:warnings`
Expected: all pass (12 new; brand and dispatch suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/spotlight/queue.py service/spotlight/dispatch.py service/api/admin/spotlight_routes.py tests/test_growth_kinds.py
git -c user.email=admin@techbaseltd.com commit -m "feat(publishing): event, prompt and tool posts, held to the owner's calendar" -m "Refs: TEC-1845"
```

---

### Task 8: Every post link lands tagged

**Files:**
- Modify: `service/campaigns/__init__.py` (imports line 11; new functions after `caption_for_platform`)
- Modify: `service/spotlight/queue.py` (`create_candidate` signature and link line 148)
- Modify: `service/api/campaign_link_routes.py`
- Test: `tests/test_post_links_utm.py` (create)

**Interfaces:**
- Consumes: `make_campaign_link`, `PLATFORMS`, `WEB_BASE_URL`.
- Produces, in `service.campaigns`: `valid_target_path(path: object) -> bool`, `post_target_url(path: str, campaign: str, content: str) -> str` (raises `ValueError('bad_target_path')`), `with_utm_source(target: str, platform: Optional[str]) -> str`. `create_candidate(tx, *, kind, subject_person_id, caption, created_by, platforms=PLATFORMS, request_key=None, target_path: str = '/', utm_content: Optional[str] = None) -> str` (raises `ValueError('bad_target_path')`). A post's link target is `{WEB_BASE_URL}{target_path}?utm_campaign={kind}&utm_content={content}`, content defaulting to the request key after its first colon. `GET /s/<key>?p=facebook|instagram` adds `utm_source` first, only on a tagged target.

- [ ] **Step 1: Write the failing test**

Create `tests/test_post_links_utm.py`:

```python
"""Every post link carries UTM tags (growth spec, Scheduler; TEC-1845).

utm_campaign is the post's kind and utm_content its slug, set when the link
is minted. utm_source is the platform the click came from, added at the
redirect, because one link key is shared by both platform rows. First-touch
capture on the web then credits the post as utm:{source}/{kind}.
"""
from __future__ import annotations

import re
from uuid import uuid4

import pytest

from database import api_tx
from service.campaigns import post_target_url, valid_target_path, with_utm_source
from service.config import WEB_BASE_URL
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('growth_schema')

BASE = WEB_BASE_URL.rstrip('/')


def _post(kind='brand', **kw) -> tuple[str, str, dict]:
    slug = f'utm-{uuid4().hex[:8]}'
    with api_tx() as tx:
        rk = create_candidate(tx, kind=kind, subject_person_id=None, caption='A caption.',
                              created_by='t', request_key=f'{kind}:{slug}', **kw)
        target = tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                            dict(k=f'post:{rk}')).fetchone()['target_url']
        captions = {r['platform']: r['caption'] for r in tx.execute(
            'SELECT platform, caption FROM publishing_queue WHERE request_key = %(rk)s',
            dict(rk=rk)).fetchall()}
    return slug, target, captions


def _cancel_all(prefix: str) -> None:
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'cancelled' WHERE request_key LIKE %(p)s",
                   dict(p=f'{prefix}%'))


def _key(facebook_caption: str) -> str:
    return re.search(r'/s/([A-Za-z0-9_-]+)\?p=facebook', facebook_caption).group(1)


def test_a_post_link_lands_on_its_page_tagged_with_its_kind_and_slug():
    slug, target, _ = _post()
    try:
        assert target == f'{BASE}/?utm_campaign=brand&utm_content={slug}'
    finally:
        _cancel_all(f'brand:{slug}')


def test_a_path_and_content_can_be_chosen():
    slug, target, _ = _post(kind='tool', target_path='/together', utm_content='game')
    try:
        assert target == f'{BASE}/together?utm_campaign=tool&utm_content=game'
    finally:
        _cancel_all(f'tool:{slug}')


def test_a_click_from_facebook_names_the_source_first(client):
    slug, _, captions = _post()
    try:
        r = client.get(f"/s/{_key(captions['facebook'])}?p=facebook")
        assert r.status_code == 302
        assert r.headers['Location'] == (
            f'{BASE}/?utm_source=facebook&utm_campaign=brand&utm_content={slug}')
    finally:
        _cancel_all(f'brand:{slug}')


def test_a_click_with_no_or_an_unknown_platform_adds_no_source(client):
    slug, target, captions = _post()
    key = _key(captions['facebook'])
    try:
        for query in ('', '?p=tiktok', '?p='):
            r = client.get(f'/s/{key}{query}')
            assert r.status_code == 302 and r.headers['Location'] == target, query
    finally:
        _cancel_all(f'brand:{slug}')


def test_an_email_link_is_never_tagged(client, make_campaign_link):
    r = client.get(f'/s/{make_campaign_link()}?p=facebook')
    assert r.status_code == 302 and r.headers['Location'] == f'{BASE}/discover'


def test_instagram_rows_still_carry_no_link():
    slug, _, captions = _post()
    try:
        assert '/s/' not in captions['instagram'] and 'http' not in captions['instagram']
        assert '/s/' in captions['facebook']
    finally:
        _cancel_all(f'brand:{slug}')


@pytest.mark.parametrize('path', ['https://evil.example/', '//evil.example', 'together',
                                  '/a b', '/x?y=1', '', None, 7])
def test_a_target_that_is_not_a_path_on_the_site_is_refused(path):
    assert valid_target_path(path) is False
    with pytest.raises(ValueError, match='bad_target_path'):
        post_target_url(path, 'brand', 'x')
    with pytest.raises(ValueError, match='bad_target_path'):
        with api_tx() as tx:
            create_candidate(tx, kind='brand', subject_person_id=None, caption='c',
                             created_by='t', target_path=path)


def test_a_source_already_on_the_target_is_kept():
    tagged = f'{BASE}/?utm_source=newsletter&utm_campaign=brand&utm_content=x'
    assert with_utm_source(tagged, 'facebook') == tagged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_post_links_utm.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'post_target_url' from 'service.campaigns'`.

- [ ] **Step 3: Write the implementation**

In `service/campaigns/__init__.py`, replace the line `from urllib.parse import urlparse` (near line 11):

```python
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
```

and add after `caption_for_platform`:

```python
# A page on the web app a post may land on: a path of letters, digits,
# hyphens, underscores and slashes, nothing else (TEC-1845). No query and no
# host, so a post's link can only ever point at our own site.
_TARGET_PATH_RE = re.compile(r'^/[A-Za-z0-9/_-]*$')


def valid_target_path(path: object) -> bool:
    return (isinstance(path, str) and bool(_TARGET_PATH_RE.match(path))
            and not path.startswith('//'))


def post_target_url(path: str, campaign: str, content: str) -> str:
    """Where a post's link lands, tagged so first-touch capture credits it
    (growth spec, Scheduler: utm_campaign is the kind, utm_content the slug).
    utm_source is added per click by `with_utm_source`, since both platform
    rows share one link key."""
    if not valid_target_path(path):
        raise ValueError('bad_target_path')
    query = urlencode({'utm_campaign': campaign, 'utm_content': content})
    return f"{WEB_BASE_URL.rstrip('/')}{path}?{query}"


def with_utm_source(target: str, platform: Optional[str]) -> str:
    """A click on a tagged post link from a named platform lands with
    utm_source set to it, first. Anything else (no platform, an unknown one,
    a link that is not a post's, a target that already names a source) is
    returned untouched."""
    if platform not in PLATFORMS:
        return target
    parts = urlsplit(target)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = {k for k, _ in pairs}
    if 'utm_campaign' not in keys or 'utm_source' in keys:
        return target
    return urlunsplit(parts._replace(query=urlencode([('utm_source', platform), *pairs])))
```

In `service/spotlight/queue.py`, replace the import line that brings `PLATFORMS`, `caption_for_platform` and `make_campaign_link` from `service.campaigns` (near line 7) with:

```python
from service.campaigns import (PLATFORMS, caption_for_platform, make_campaign_link,
                               post_target_url, valid_target_path)
```

Replace the `create_candidate` signature and first check, from `def create_candidate(tx, *, kind: str, subject_person_id: Optional[int], caption: str, created_by: str,` through the first `raise ValueError('bad_kind')` (four lines; measured at 79 to 82 before Task 7 added about 13 lines above them):

```python
def create_candidate(tx, *, kind: str, subject_person_id: Optional[int], caption: str, created_by: str,
                     platforms=PLATFORMS, request_key: Optional[str] = None,
                     target_path: str = '/', utm_content: Optional[str] = None) -> str:
    if kind not in KINDS:
        raise ValueError('bad_kind')
    if not valid_target_path(target_path):
        raise ValueError('bad_target_path')
```

In `create_candidate`, replace the line `link = make_campaign_link(tx, f'post:{rk}', f"{WEB_BASE_URL}/", None)` (measured at 148 before Task 7) with:

```python
    # TEC-1845: the link lands tagged (utm_campaign = kind, utm_content =
    # the slug, by default the request key after its first colon) on the
    # page the post is about; the redirect adds utm_source per click.
    content = utm_content or (rk.split(':', 1)[1] if ':' in rk else rk)
    link = make_campaign_link(tx, f'post:{rk}', post_target_url(target_path, kind, content), None)
```

In `service/api/campaign_link_routes.py`, replace everything after the module docstring and `from __future__ import annotations` (from `from flask import abort, redirect, request` to the end of `get_campaign_link`, lines 12 to 29) with:

```python
from flask import abort, redirect, request

from database import api_tx
from service.api.decorators import get
from service.campaigns import record_click, with_utm_source

@get('/s/<key>')
def get_campaign_link(key: str):
    platform = request.args.get('p')
    with api_tx() as tx:
        target, receipt = record_click(
            tx, key, request.headers.get('User-Agent', ''), platform=platform)
    if not target:
        abort(404)
    # TEC-1845: a post's link names the platform the click came from, so
    # first-touch capture on the web credits utm:{platform}/{kind}.
    response = redirect(with_utm_source(target, platform), code=302)
    if receipt:
        response.headers['X-Spotlight-Receipt'] = receipt
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_post_links_utm.py tests/test_campaigns.py tests/test_brand_posts.py tests/test_e1_links_tracked.py -q -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/campaigns/__init__.py service/spotlight/queue.py service/api/campaign_link_routes.py tests/test_post_links_utm.py
git -c user.email=admin@techbaseltd.com commit -m "feat(publishing): every post link lands tagged with its platform, kind and slug" -m "Refs: TEC-1845"
```

---

### Task 9: Tool posts through the calendar route

**Files:**
- Modify: `service/api/admin/spotlight_routes.py` (the calendar slug constants above `post_growth_brand`; `post_growth_brand`; import `valid_target_path`. Anchored on quoted code below: Task 7 adds about 30 lines above this region, so the line numbers measured before it are hints only)
- Test: `tests/test_tool_posts.py` (create)

**Interfaces:**
- Consumes: `create_candidate(..., target_path=...)`, `valid_target_path` (Task 8); `CALENDAR_HELD_KINDS` (Task 7).
- Produces: `POST /admin/growth/brand` body `{slug, caption, scheduled_for, platforms?, kind?: 'brand' | 'tool', target_path?: str}`; `kind` defaults to `'brand'`, `target_path` to `'/'`; request key `{kind}:{slug}` of at most 64 characters; errors `bad_kind`, `bad_slug`, `bad_target_path` (400). Admin follow-up (not in this repo, an Ahavah Admin issue created in Task 15): the social-queue run sends `kind` and `target_path` when a calendar entry has them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_posts.py`:

```python
"""A tool post: the monthly game or checklist promotion (TEC-1845).

Growth spec, Scheduler: "a monthly game or checklist promotion from static
Claude Design artwork, through the existing brand path". It is a brand post
with its own kind, so the Sources table and the queue can tell them apart,
and its link lands on the tools page.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from database import api_tx
from service.config import WEB_BASE_URL

pytestmark = pytest.mark.usefixtures('growth_schema')

H = {'X-Growth-Cron': 'test-cron-secret'}


def _slug() -> str:
    return f'test-{secrets.token_hex(4)}'


def _soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()


def _post(client, **body):
    payload = dict(slug=_slug(), caption='How well do you fit with someone?',
                   scheduled_for=_soon(), **body)
    return client.post('/admin/growth/brand', json=payload, headers=H), payload['slug']


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            'SELECT kind, status FROM publishing_queue WHERE request_key = %(rk)s',
            dict(rk=rk)).fetchall()]


def _target(rk):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                          dict(k=f'post:{rk}')).fetchone()['target_url']


def _cancel(rk):
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'cancelled' WHERE request_key = %(rk)s",
                   dict(rk=rk))


def test_a_tool_post_is_queued_with_its_own_kind_and_landing_page(client):
    r, slug = _post(client, kind='tool', target_path='/together')
    assert r.status_code == 200, r.get_json()
    rk = r.get_json()['request_key']
    try:
        assert rk == f'tool:{slug}'
        assert {(x['kind'], x['status']) for x in _rows(rk)} == {('tool', 'awaiting_render')}
        assert _target(rk) == (f"{WEB_BASE_URL.rstrip('/')}/together"
                               f"?utm_campaign=tool&utm_content={slug}")
    finally:
        _cancel(rk)


def test_without_a_kind_it_is_a_brand_post_as_before(client):
    r, slug = _post(client)
    rk = r.get_json()['request_key']
    try:
        assert rk == f'brand:{slug}'
        assert {x['kind'] for x in _rows(rk)} == {'brand'}
    finally:
        _cancel(rk)


def test_a_brand_and_a_tool_post_may_share_a_slug(client):
    slug = _slug()
    body = dict(slug=slug, caption='c', scheduled_for=_soon())
    a = client.post('/admin/growth/brand', json=body, headers=H).get_json()['request_key']
    b = client.post('/admin/growth/brand', json=dict(body, kind='tool'), headers=H).get_json()['request_key']
    try:
        assert (a, b) == (f'brand:{slug}', f'tool:{slug}')
    finally:
        _cancel(a)
        _cancel(b)


@pytest.mark.parametrize('extra,error', [
    (dict(kind='event'), 'bad_kind'),
    (dict(kind='prompt'), 'bad_kind'),
    (dict(kind=['tool']), 'bad_kind'),
    (dict(kind='tool', target_path='https://evil.example/'), 'bad_target_path'),
    (dict(kind='tool', target_path='/together?x=1'), 'bad_target_path'),
    (dict(kind='tool', slug='a' * 60), 'bad_slug'),
])
def test_bad_input_is_refused_before_anything_is_written(client, extra, error):
    body = dict(slug=_slug(), caption='c', scheduled_for=_soon())
    body.update(extra)
    r = client.post('/admin/growth/brand', json=body, headers=H)
    assert r.status_code == 400 and r.get_json() == dict(error=error)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_posts.py -q -p no:warnings`
Expected: the tool tests fail (`rk == 'brand:...'`), the bad-kind and bad-path cases answer 200 instead of 400.

- [ ] **Step 3: Write the implementation**

In `service/api/admin/spotlight_routes.py`, add to the imports:

```python
from service.campaigns import valid_target_path
```

Replace the slug comment and constants, from the comment line `# A calendar slug, as the admin's social calendar writes it. Lowercase words` through `_BRAND_SLUG_MAX = 64 - len('brand:')` (five lines, measured at 1205 to 1209 before Task 7), with:

```python
# A calendar slug, as the admin's social calendar writes it. Lowercase words
# joined by hyphens, and short enough that `<kind>:<slug>` fits the queue's
# 64 character request key (see queue._REQUEST_KEY_RE).
_BRAND_SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
_REQUEST_KEY_MAX = 64
# The kinds the owner's social calendar sends through this route. A tool
# post is the monthly game or checklist promotion from static Claude Design
# artwork (growth spec, Scheduler; TEC-1845): a brand post with its own kind
# and its own utm_campaign.
_CALENDAR_ROUTE_KINDS = ('brand', 'tool')
```

In `post_growth_brand`, extend the docstring's body line to read `Body: {slug, caption, scheduled_for, platforms?, kind?, target_path?}. kind is 'brand' (the default) or 'tool'; target_path is the page the post's link lands on, '/' by default.` Then replace the validation and creation: from the line `s = _gate()` directly after the docstring, through the end of the `rk = create_candidate(tx, kind='brand', ...)` call (the line ending `request_key=request_key)`), with the block below. The replacement starts with `s = _gate()` and `body = _body()`, so both original lines go too; do not keep a second copy of either. The `tx.execute("UPDATE publishing_queue SET scheduled_for = ...")` call after it stays.

```python
    s = _gate()
    body = _body()
    slug = body.get('slug')
    caption = body.get('caption')
    kind = body.get('kind', 'brand')
    target_path = body.get('target_path', '/')
    # Absent means every platform. An explicit empty list is a caller bug and
    # is refused below, rather than quietly read as "all of them".
    platforms = body.get('platforms')
    if platforms is None:
        platforms = list(PLATFORMS)
    if not isinstance(kind, str) or kind not in _CALENDAR_ROUTE_KINDS:
        return dict(error='bad_kind'), 400
    if (not isinstance(slug, str) or not _BRAND_SLUG_RE.match(slug)
            or len(f'{kind}:{slug}') > _REQUEST_KEY_MAX):
        return dict(error='bad_slug'), 400
    if not isinstance(caption, str) or not caption.strip() or len(caption) > BRAND_CAPTION_MAX:
        return dict(error='bad_caption'), 400
    if not valid_target_path(target_path):
        return dict(error='bad_target_path'), 400
    # isinstance first: set() of a list holding a dict raises TypeError,
    # which would surface as a 500 rather than the caller's mistake.
    if (not isinstance(platforms, list) or not platforms
            or not all(isinstance(p, str) for p in platforms)
            or len(set(platforms)) != len(platforms)
            or any(p not in PLATFORMS for p in platforms)):
        return dict(error='bad_platforms'), 400
    when = _parse_dt(body.get('scheduled_for'))
    if when is None:
        return dict(error='scheduled_for_required'), 400
    problem = slot_problem(when)
    if problem:
        return dict(error='slot_unavailable', reason=problem), 409

    request_key = f'{kind}:{slug}'
    # Same race handling as the roundup: racing calls can all pass the
    # `already` read together, and the losers then fail on the
    # (request_key, platform) unique key. The post exists, so a loser gets
    # the same answer a later duplicate would, not a 500.
    try:
        with api_tx() as tx:
            if tx.execute("SELECT 1 FROM publishing_queue WHERE request_key = %(rk)s LIMIT 1",
                          dict(rk=request_key)).fetchone():
                return dict(request_key=request_key, already=True)
            rk = create_candidate(tx, kind=kind, subject_person_id=None, caption=caption.strip(),
                                  created_by=_actor(s), platforms=platforms, request_key=request_key,
                                  target_path=target_path)
```

and change the audit call below it, `_audit(tx, s, 'growth.queue.brand', request_key=rk, platforms=platforms,` and its continuation line, to:

```python
            _audit(tx, s, f'growth.queue.{kind}', request_key=rk, platforms=platforms,
                   scheduled_for=when.isoformat())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_posts.py tests/test_brand_posts.py -q -p no:warnings`
Expected: all pass (9 new; the brand suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/api/admin/spotlight_routes.py tests/test_tool_posts.py
git -c user.email=admin@techbaseltd.com commit -m "feat(publishing): the calendar route queues tool posts with their own landing page" -m "Refs: TEC-1845"
```

---

### Task 10: Event posts, 10 days and 2 days before

**Files:**
- Create: `service/spotlight/growthposts.py`
- Modify: `service/api/admin/spotlight_routes.py` (imports; `_approval_slot`; the row read in `post_growth_queue_approve` and in the retry route, as changed by Task 7)
- Test: `tests/test_event_posts.py` (create)

**Interfaces:**
- Consumes: `create_candidate(..., request_key, target_path, utm_content)` (Task 8); `CAPTION_MAX`, `CALENDAR_HELD_KINDS` (Task 7); `event_source` (Task 2); `slot_problem`; the image and approve routes.
- Produces, in `service.spotlight.growthposts`: `EVENT_OFFSETS_DAYS = (10, 2)`, `SLOT_HOURS = (12, 18)`, `EVENT_EARLIER_DAYS = 2`, `event_request_key(slug: str, starts_at: datetime, offset_days: int) -> str` (`event:{slug}:{yyyymmdd}:d{offset}`), `queue_event_posts(tx, *, slug: str, starts_at: datetime, caption: str, payload: dict, created_by: str, now: Optional[datetime] = None) -> list[str]` (request keys created; raises `ValueError('bad_slug' | 'naive datetime' | 'bad_caption' | 'bad_payload')`; each row's payload is the caller's plus `offset_days: int` and `starts_at: str`, the start in UTC as ISO 8601), `cancel_event_posts(tx, slug: str) -> int` (platform rows cancelled), `event_approval_slot(payload: dict, requested: Optional[datetime], stored: Optional[datetime], now: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[str]]`. In `spotlight_routes`, `_approval_slot(kind, requested, stored, payload=None)`: for kind `event`, approval and retry keep a stored slot that is still valid, else take the latest valid slot before it, no more than `EVENT_EARLIER_DAYS` before the post's own day and before the gathering starts, else answer 409 `{"error": "slot_unavailable", "reason": "too_late"}`; an event post never rolls forward. The events plan calls `queue_event_posts` when an Ahavah-run or approved gathering publishes and `cancel_event_posts` when it moves or is cancelled.

- [ ] **Step 1: Write the failing test**

Create `tests/test_event_posts.py`:

```python
"""Event posts (growth spec, Scheduler; TEC-1845).

When a gathering publishes, two feed posts are queued: 10 days and 2 days
before, at 12:00 UTC. A post whose day has passed is skipped; one whose day
is a rest day moves up to 2 days earlier, never later and never after the
gathering starts. A gathering months away is queued anyway, and approval
waits until the owner's calendar has been read that far. Approval and retry
hold to the same rule: a slot that has gone or turned out to be a rest day
moves earlier, never later, and a post with no slot left before the
gathering is refused as too late. The posts link to the gathering's own
page. Helpers are copied from tests/test_growth_kinds.py on purpose: test
files in this suite do not import from each other.
"""
from __future__ import annotations

import base64
import hashlib
import io
import secrets
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from PIL import Image

import service.spotlight.restdays as rd
from database import api_tx
from service.config import WEB_BASE_URL
from service.spotlight.growthposts import cancel_event_posts, queue_event_posts

pytestmark = pytest.mark.usefixtures('growth_schema')

CAPTION = 'Gathering for Sukkot in Atlanta. Singles welcome.'
H = {'X-Growth-Cron': 'test-cron-secret'}


@pytest.fixture
def slug():
    s = f'ev{uuid4().hex[:8]}'
    yield s
    with api_tx() as tx:
        keys = [r['request_key'] for r in tx.execute(
            'SELECT DISTINCT request_key FROM publishing_queue WHERE request_key LIKE %(p)s',
            dict(p=f'event:{s}:%')).fetchall()]
        tx.execute('DELETE FROM publishing_queue WHERE request_key = ANY(%(k)s)', dict(k=keys))
        tx.execute('DELETE FROM spotlight_revision WHERE request_key = ANY(%(k)s)', dict(k=keys))
        tx.execute('DELETE FROM campaign_link WHERE kind = ANY(%(k)s)',
                   dict(k=[f'post:{k}' for k in keys]))


def _starts(days: int) -> datetime:
    day = (datetime.now(timezone.utc) + timedelta(days=days)).date()
    return datetime.combine(day, time(19, 0), timezone.utc)


def _queue(slug, starts_at, **kw):
    with api_tx() as tx:
        return queue_event_posts(tx, slug=slug, starts_at=starts_at, caption=CAPTION,
                                 payload=dict(title='Sukkot gathering', city='Atlanta'),
                                 created_by='test', **kw)


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT id, kind, platform, status, scheduled_for, payload, subject_person_id
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def _jpeg() -> str:
    buf = io.BytesIO()
    Image.new('RGB', (1080, 1350), 'white').save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _rendered(client, monkeypatch, rk) -> None:
    """Artwork on both platform rows, so the post waits in review."""
    import service.spotlight.storage as st
    monkeypatch.setattr(st, 'put_card_image', lambda key, data, content_type, public=False: None)
    monkeypatch.setattr(st, 'make_public', lambda key: None)
    for platform in ('facebook', 'instagram'):
        r = client.post(f'/admin/growth/queue/{rk}/image',
                        json=dict(platform=platform, image_base64=_jpeg(), content_type='image/jpeg'),
                        headers=H)
        assert r.status_code == 200, r.get_json()


def _admin_headers(make_person) -> dict:
    p = make_person(name='EventAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


def _approve(client, headers, rk):
    """Approves the facebook row, the first of _rows."""
    return client.post(f"/admin/growth/queue/{_rows(rk)[0]['id']}/approve", json={}, headers=headers)


def test_a_gathering_gets_two_posts_ten_and_two_days_before(slug, monkeypatch):
    # No rest days and a calendar read far ahead, so only the offsets decide
    # the slot whatever day this runs.
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    starts = _starts(20)
    keys = _queue(slug, starts)
    stamp = f'{starts:%Y%m%d}'
    assert keys == [f'event:{slug}:{stamp}:d10', f'event:{slug}:{stamp}:d2']
    for rk, offset in zip(keys, (10, 2)):
        rows = _rows(rk)
        assert {(r['kind'], r['status'], r['subject_person_id']) for r in rows} == {
            ('event', 'awaiting_render', None)}
        want = datetime.combine(starts.date() - timedelta(days=offset), time(12, 0), timezone.utc)
        assert {r['scheduled_for'] for r in rows} == {want}
        assert rows[0]['payload'] == dict(title='Sukkot gathering', city='Atlanta',
                                          offset_days=offset, starts_at=starts.isoformat())
    with api_tx('read committed') as tx:
        target = tx.execute('SELECT target_url FROM campaign_link WHERE kind = %(k)s',
                            dict(k=f'post:{keys[0]}')).fetchone()['target_url']
    assert target == f"{WEB_BASE_URL.rstrip('/')}/e/{slug}?utm_campaign=event&utm_content={slug}"


def test_queuing_twice_changes_nothing(slug):
    starts = _starts(20)
    first = _queue(slug, starts)
    assert _queue(slug, starts) == []
    assert all(len(_rows(rk)) == 2 for rk in first)


def test_an_offset_already_past_is_skipped(slug):
    keys = _queue(slug, _starts(5))
    assert [k.rsplit(':', 1)[1] for k in keys] == ['d2']


def test_a_gathering_tomorrow_gets_no_post(slug):
    assert _queue(slug, datetime.now(timezone.utc) + timedelta(days=1)) == []


def test_a_rest_day_moves_the_post_earlier(slug, monkeypatch):
    starts = _starts(20)
    rest = starts.date() - timedelta(days=10)
    monkeypatch.setattr(rd, 'REST_DAYS', (rest,))
    keys = _queue(slug, starts)
    moved = {r['scheduled_for'] for r in _rows(keys[0])}
    assert moved == {datetime.combine(rest - timedelta(days=1), time(12, 0), timezone.utc)}


def test_a_gathering_past_the_known_calendar_is_still_queued(slug, monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=3))
    keys = _queue(slug, _starts(30))
    assert len(keys) == 2
    for rk in keys:
        slot = _rows(rk)[0]['scheduled_for']
        assert rd.slot_problem(slot) == 'unknown'


def test_a_moved_gathering_gets_new_posts_and_the_old_ones_are_cancelled(slug):
    old = _queue(slug, _starts(20))
    with api_tx() as tx:
        tx.execute("UPDATE publishing_queue SET status = 'published' WHERE request_key = %(rk)s",
                   dict(rk=old[1]))
        assert cancel_event_posts(tx, slug) == 2
    assert {r['status'] for r in _rows(old[0])} == {'cancelled'}
    assert {r['status'] for r in _rows(old[1])} == {'published'}, 'a post already out stays'
    new = _queue(slug, _starts(25))
    assert len(new) == 2 and not set(new) & set(old)


def test_a_late_approval_of_the_d2_post_is_refused_never_moved_after_the_gathering(
        slug, client, monkeypatch, make_person):
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    headers = _admin_headers(make_person)
    rk = _queue(slug, _starts(20))[1]
    _rendered(client, monkeypatch, rk)
    # The approval comes late: the gathering starts in 3 hours and every
    # slot the d2 post may take, on its day or up to 2 days before, is gone.
    soon = datetime.now(timezone.utc) + timedelta(hours=3)
    with api_tx() as tx:
        tx.execute("""UPDATE publishing_queue
                         SET scheduled_for = %(w)s,
                             payload = payload || jsonb_build_object('starts_at', %(s)s::text)
                       WHERE request_key = %(rk)s""",
                   dict(w=soon - timedelta(days=2), s=soon.isoformat(), rk=rk))
    r = _approve(client, headers, rk)
    assert r.status_code == 409
    assert r.get_json() == dict(error='slot_unavailable', reason='too_late')
    assert {x['status'] for x in _rows(rk)} == {'review'}


def test_a_slot_that_turns_out_to_be_a_rest_day_moves_earlier_on_approval(
        slug, client, monkeypatch, make_person):
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=3))
    headers = _admin_headers(make_person)
    starts = _starts(30)
    rk = _queue(slug, starts)[0]
    stored = _rows(rk)[0]['scheduled_for']
    assert rd.slot_problem(stored) == 'unknown'
    _rendered(client, monkeypatch, rk)
    # The owner's calendar is read further, and the post's day is a rest day.
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    monkeypatch.setattr(rd, 'REST_DAYS', (stored.date(),))
    r = _approve(client, headers, rk)
    assert r.status_code == 200, r.get_json()
    slot = _rows(rk)[0]['scheduled_for']
    assert slot == datetime.combine(stored.date() - timedelta(days=1), time(12, 0), timezone.utc)
    assert slot < starts


@pytest.mark.parametrize('kw,error', [
    (dict(slug='Not A Slug'), 'bad_slug'),
    (dict(caption=''), 'bad_caption'),
    (dict(caption='x' * 2001), 'bad_caption'),
    (dict(payload=['title']), 'bad_payload'),
    (dict(starts_at=datetime(2027, 1, 1, 19, 0)), 'naive datetime'),
])
def test_bad_input_is_refused(slug, kw, error):
    args = dict(slug=slug, starts_at=_starts(20), caption=CAPTION, payload={}, created_by='test')
    args.update(kw)
    with pytest.raises(ValueError, match=error):
        with api_tx() as tx:
            queue_event_posts(tx, **args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_event_posts.py -q -p no:warnings`
Expected: collection error, `ModuleNotFoundError: No module named 'service.spotlight.growthposts'`.

- [ ] **Step 3: Write the implementation**

Create `service/spotlight/growthposts.py`:

```python
"""The scheduler's own kinds: gatherings and the question of the week (TEC-1845).

docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md,
Scheduler. Each post is about nobody, waits in awaiting_render for artwork
drawn from its Claude Design template with the row's payload
(queue.TEMPLATE_KINDS; GET /admin/growth/queue?template_render=1), then
waits in review for the owner's approval like every other post. Nothing
here publishes, and every slot is held to the owner's rest days
(service/spotlight/restdays.py).

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from service.leads.sources import event_source
from service.spotlight.queue import CAPTION_MAX, create_candidate
from service.spotlight.restdays import slot_problem

# Days before a gathering that its two feed posts go out (growth spec).
EVENT_OFFSETS_DAYS = (10, 2)
# The feed's two slots, 08:00 and 14:00 in Barbados (restdays.next_valid_slot).
SLOT_HOURS = (12, 18)
# How many days earlier a post may move when its own day is a rest day.
# Never later: a post after the gathering is no use to anyone.
EVENT_EARLIER_DAYS = 2

_Q_KEY_TAKEN = """
    SELECT 1 FROM publishing_queue WHERE request_key = %(rk)s LIMIT 1
"""

_Q_SET_SLOT = """
    UPDATE publishing_queue SET scheduled_for = %(w)s, payload = %(p)s::jsonb
     WHERE request_key = %(rk)s
"""

_Q_CANCEL_EVENT = """
    UPDATE publishing_queue SET status = 'cancelled', error = 'event_changed', updated_at = NOW()
     WHERE kind = 'event' AND request_key LIKE %(prefix)s
       AND status IN ('awaiting_render', 'review', 'scheduled', 'failed')
"""


def _check_caption(caption: object) -> str:
    if not isinstance(caption, str) or not caption.strip() or len(caption) > CAPTION_MAX:
        raise ValueError('bad_caption')
    return caption.strip()


def event_request_key(slug: str, starts_at: datetime, offset_days: int) -> str:
    """event:{slug}:{yyyymmdd of the start in UTC}:d{offset}. The date is in
    the key so a gathering moved to a new date gets new posts: a cancelled
    key stays taken, as a brand post's does."""
    return f"event:{slug}:{starts_at.astimezone(timezone.utc):%Y%m%d}:d{offset_days}"


def _event_slot(target_day: date, starts_at: datetime, now: datetime, *,
                latest: Optional[datetime] = None, strict: bool = False) -> Optional[datetime]:
    """The first slot on the post's own day, then up to EVENT_EARLIER_DAYS
    before it, that is before the gathering starts and no later than
    `latest`. At queueing (strict False) 'unknown' is allowed: a gathering
    months away is queued now, and approval and dispatch refuse it until
    the owner's calendar has been read that far (the brand rule,
    CALENDAR_HELD_KINDS). At approval (strict True) only a valid slot will
    do."""
    allowed = (None,) if strict else (None, 'unknown')
    for back in range(EVENT_EARLIER_DAYS + 1):
        day = target_day - timedelta(days=back)
        for hour in SLOT_HOURS:
            slot = datetime.combine(day, time(hour, 0), timezone.utc)
            if slot >= starts_at or (latest is not None and slot > latest):
                continue
            if slot_problem(slot, now) in allowed:
                return slot
    return None


def event_approval_slot(payload: dict, requested: Optional[datetime],
                        stored: Optional[datetime],
                        now: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[str]]:
    """Where an approval or a retry puts an event post, and why not if it
    cannot (spotlight_routes._approval_slot). Never later than the stored
    slot and never at or after the gathering's start: a post after the
    gathering is no use to anyone, so unlike a brand post it never rolls
    forward. An explicit slot is held to the calendar and to the start. A
    stored slot still valid is kept; else the latest valid slot before it,
    no more than EVENT_EARLIER_DAYS before the post's own day; else
    'too_late'. A row without the start or offset its payload should carry
    is 'too_late' as well, so it can never be published blind."""
    now = now or datetime.now(timezone.utc)
    try:
        starts_at = datetime.fromisoformat(payload['starts_at'])
        offset = int(payload['offset_days'])
    except (KeyError, TypeError, ValueError):
        return None, 'too_late'
    if starts_at.tzinfo is None or offset not in EVENT_OFFSETS_DAYS:
        return None, 'too_late'
    if requested is not None:
        problem = slot_problem(requested, now)
        if problem:
            return None, problem
        return (requested, None) if requested < starts_at else (None, 'too_late')
    if stored is None:
        return None, 'too_late'
    if stored < starts_at and slot_problem(stored, now) is None:
        return stored, None
    target_day = (starts_at - timedelta(days=offset)).astimezone(timezone.utc).date()
    slot = _event_slot(target_day, starts_at, now, latest=stored, strict=True)
    return (slot, None) if slot else (None, 'too_late')


def queue_event_posts(tx, *, slug: str, starts_at: datetime, caption: str, payload: dict,
                      created_by: str, now: Optional[datetime] = None) -> list[str]:
    """Queue a published gathering's feed posts and return the request keys
    created. A key already queued is left alone, so a repeat call changes
    nothing. `payload` is the template's data (title, date, place,
    organiser, as the events plan names them); `offset_days` and
    `starts_at` (UTC, ISO 8601) are added, and approval reads them
    (event_approval_slot)."""
    event_source(slug)
    if not isinstance(starts_at, datetime) or starts_at.tzinfo is None:
        raise ValueError('naive datetime')
    text = _check_caption(caption)
    if not isinstance(payload, dict):
        raise ValueError('bad_payload')
    now = now or datetime.now(timezone.utc)
    made: list[str] = []
    for offset in EVENT_OFFSETS_DAYS:
        rk = event_request_key(slug, starts_at, offset)
        if tx.execute(_Q_KEY_TAKEN, dict(rk=rk)).fetchone():
            continue
        target_day = (starts_at - timedelta(days=offset)).astimezone(timezone.utc).date()
        slot = _event_slot(target_day, starts_at, now)
        if slot is None:
            continue
        create_candidate(tx, kind='event', subject_person_id=None, caption=text,
                         created_by=created_by, request_key=rk,
                         target_path=f'/e/{slug}', utm_content=slug)
        tx.execute(_Q_SET_SLOT, dict(w=slot, rk=rk, p=json.dumps({
            **payload, 'offset_days': offset,
            'starts_at': starts_at.astimezone(timezone.utc).isoformat()})))
        made.append(rk)
    return made


def cancel_event_posts(tx, slug: str) -> int:
    """A gathering moved or was cancelled: every post of it not yet out (or
    on its way out) is cancelled. Returns the platform rows cancelled. A post
    already published stays; taking it down is the operator's removal."""
    event_source(slug)
    return tx.execute(_Q_CANCEL_EVENT, dict(prefix=f'event:{slug}:%')).rowcount
```

In `service/api/admin/spotlight_routes.py`, add to the imports:

```python
from service.spotlight.growthposts import event_approval_slot
```

Change the signature of `_approval_slot` from `def _approval_slot(kind: str, requested: Optional[datetime],` / `stored: Optional[datetime]) -> tuple[Optional[datetime], Optional[str]]:` to:

```python
def _approval_slot(kind: str, requested: Optional[datetime],
                   stored: Optional[datetime],
                   payload: Optional[dict] = None) -> tuple[Optional[datetime], Optional[str]]:
```

add this paragraph at the end of its docstring:

```python
    An event post (TEC-1845) is held to the calendar too, but never moves
    later: a post after the gathering is no use. It keeps a valid stored
    slot, else takes the latest valid one before it and before the
    gathering, else is `too_late` (growthposts.event_approval_slot, which
    reads the start and offset from the row's payload).
```

and directly after the line `if kind not in CALENDAR_HELD_KINDS:` and its `return requested or stored or _default_slot(), None` (as Task 7 left them), insert:

```python
    if kind == 'event':
        return event_approval_slot(payload or {}, requested, stored)
```

In `post_growth_queue_approve`, the row read becomes:

```python
        row = tx.execute("SELECT kind, scheduled_for, image_key, payload FROM publishing_queue WHERE id = %(id)s",
                         dict(id=queue_id)).fetchone()
```

and the call `when, problem = _approval_slot(row['kind'], requested, row['scheduled_for'])` becomes:

```python
        when, problem = _approval_slot(row['kind'], requested, row['scheduled_for'], row['payload'])
```

In the retry route (the function holding `if row and row['kind'] in CALENDAR_HELD_KINDS:` after Task 7), the row read `row = tx.execute("SELECT kind, scheduled_for FROM publishing_queue WHERE id = %(id)s",` becomes:

```python
        row = tx.execute("SELECT kind, scheduled_for, payload FROM publishing_queue WHERE id = %(id)s",
                         dict(id=queue_id)).fetchone()
```

and its call `when, problem = _approval_slot(row['kind'], None, row['scheduled_for'])` becomes:

```python
            when, problem = _approval_slot(row['kind'], None, row['scheduled_for'], row['payload'])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_event_posts.py tests/test_growth_kinds.py tests/test_brand_posts.py -q -p no:warnings`
Expected: all pass (`14 passed` in `test_event_posts.py`; the kinds and brand suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/spotlight/growthposts.py service/api/admin/spotlight_routes.py tests/test_event_posts.py
git -c user.email=admin@techbaseltd.com commit -m "feat(publishing): a published gathering queues its posts 10 days and 2 days before" -m "Refs: TEC-1845"
```

---

### Task 11: The question of the week

**Files:**
- Modify: `service/spotlight/growthposts.py` (append)
- Create: `service/cron/questionofweek/__init__.py`
- Modify: `service/cron/__init__.py` (import and `asyncio.gather` entry)
- Modify: `docker-compose.production.yml` (the `cron` service's `environment`, after `DUO_CRON_REFERRAL_INTRO_POLL_SECONDS`)
- Test: `tests/test_question_of_week.py` (create)

**Interfaces:**
- Consumes: `prompt_bank` (Task 1); `create_candidate` (Task 8); `SLOT_HOURS`, `_Q_KEY_TAKEN`, `_Q_SET_SLOT` (Task 10).
- Produces, in `service.spotlight.growthposts`: `QUESTION_CAPTION = 'Question of the week: {text}'`, `week_key(day: date) -> str` (`'2027-W05'`), `queue_question_of_week(tx, *, now: Optional[datetime] = None, created_by: str = 'cron') -> Optional[str]` (the request key `prompt:{week}` for next ISO week, new or already queued; None when the bank has no active prompt or the week has no free valid day). `service.cron.questionofweek.question_of_week_forever() -> Coroutine`, off unless `DUO_CRON_QUESTION_OF_WEEK_ENABLED` is `1`, `true`, `yes` or `on`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_of_week.py`:

```python
"""The question of the week (growth spec, Scheduler; TEC-1845).

"one 'Question of the week' a week, drawn from the prompt bank in rotation,
on the slot the brand calendar leaves empty". Next ISO week gets one prompt
post on its first day with nothing else scheduled and no rest day, the
least recently posted prompt first. An empty bank, a week with no free
day, or a week past the owner's known calendar queues nothing.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.spotlight.growthposts import queue_question_of_week, week_key
from service.spotlight.queue import create_candidate

pytestmark = pytest.mark.usefixtures('growth_schema')

# The real last date the owner's calendar has been read for, kept before any
# test moves it.
_KNOWN_THROUGH = rd.KNOWN_THROUGH


@pytest.fixture
def bank(monkeypatch):
    """Only this test's prompts are active while it runs; every other row's
    `active` is put back afterwards. The tests drive the clock months ahead,
    past the real KNOWN_THROUGH, so the calendar is read far enough for
    them; test_a_week_past_the_known_calendar_queues_nothing puts it back."""
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(weeks=60))
    with api_tx() as tx:
        was = [r['key'] for r in tx.execute('SELECT key FROM prompt_bank WHERE active').fetchall()]
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE active')
    made: list[str] = []

    def add(text: str, sort: int = 0) -> str:
        key = f'qw-{uuid4().hex[:8]}'
        with api_tx() as tx:
            tx.execute("""INSERT INTO prompt_bank (key, text, category, sort)
                          VALUES (%(k)s, %(t)s, 'test', %(s)s)""", dict(k=key, t=text, s=sort))
        made.append(key)
        return key

    yield add
    with api_tx() as tx:
        tx.execute('DELETE FROM prompt_bank WHERE key = ANY(%(k)s)', dict(k=made))
        tx.execute('UPDATE prompt_bank SET active = TRUE WHERE key = ANY(%(k)s)', dict(k=was))


@pytest.fixture
def keys():
    made: list[str] = []
    yield made
    with api_tx() as tx:
        tx.execute('DELETE FROM publishing_queue WHERE request_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM spotlight_revision WHERE request_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM campaign_link WHERE kind = ANY(%(k)s)',
                   dict(k=[f'post:{k}' for k in made]))


def _now(weeks_ahead: int) -> datetime:
    """A clock this many weeks ahead, so each test owns its target week."""
    return datetime.now(timezone.utc) + timedelta(weeks=weeks_ahead)


def _monday_after(now: datetime):
    ahead = (now + timedelta(days=7)).date()
    return ahead - timedelta(days=ahead.weekday())


def _queue(now, keys) -> str | None:
    with api_tx() as tx:
        rk = queue_question_of_week(tx, now=now, created_by='test')
    if rk:
        keys.append(rk)
    return rk


def _rows(rk):
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT kind, platform, status, caption, scheduled_for, payload
                 FROM publishing_queue WHERE request_key = %(rk)s ORDER BY platform""",
            dict(rk=rk)).fetchall()]


def test_one_question_a_week_is_queued_from_the_bank(bank, keys):
    key = bank('How I keep Sabbath')
    now = _now(21)
    monday = _monday_after(now)
    rk = _queue(now, keys)
    assert rk == f'prompt:{week_key(monday)}'
    rows = _rows(rk)
    assert {(r['kind'], r['status']) for r in rows} == {('prompt', 'awaiting_render')}
    assert rows[0]['caption'].startswith('Question of the week: How I keep Sabbath')
    assert rows[0]['payload'] == dict(prompt_key=key, text='How I keep Sabbath')
    slot = rows[0]['scheduled_for']
    assert monday <= slot.date() <= monday + timedelta(days=6)
    assert slot.time() in (time(12, 0), time(18, 0))


def test_a_second_run_in_the_same_week_changes_nothing(bank, keys):
    bank('The home I hope to build')
    # Wednesday 12:00 UTC of a fixed week, so the second run 6 hours later
    # targets the same week whatever time of day this runs.
    day = _now(24).date()
    wednesday = day - timedelta(days=day.weekday()) + timedelta(days=2)
    now = datetime.combine(wednesday, time(12, 0), timezone.utc)
    first = _queue(now, keys)
    assert first is not None
    assert _queue(now + timedelta(hours=6), keys) == first
    assert len(_rows(first)) == 2


def test_the_bank_rotates_least_recently_posted_first(bank, keys):
    a = bank('The feast I look forward to most, and why', sort=1)
    b = bank('What I am studying in Torah right now', sort=2)
    now = _now(27)
    picked = []
    for week in range(3):
        rk = _queue(now + timedelta(weeks=week), keys)
        picked.append(_rows(rk)[0]['payload']['prompt_key'])
    assert picked == [a, b, a]


def test_an_empty_bank_queues_nothing(bank, keys):
    assert _queue(_now(30), keys) is None


def test_a_day_the_calendar_already_uses_is_left_to_it(bank, keys):
    bank('My family would describe me as')
    now = _now(33)
    monday = _monday_after(now)
    with api_tx() as tx:
        brand = create_candidate(tx, kind='brand', subject_person_id=None, caption='c', created_by='t',
                                 request_key=f'brand:qw-{uuid4().hex[:8]}')
        tx.execute('UPDATE publishing_queue SET scheduled_for = %(w)s WHERE request_key = %(rk)s',
                   dict(w=datetime.combine(monday, time(12, 0), timezone.utc), rk=brand))
    keys.append(brand)
    rk = _queue(now, keys)
    assert _rows(rk)[0]['scheduled_for'].date() != monday


def test_a_rest_day_is_skipped(bank, keys, monkeypatch):
    bank('Something I am learning to do well')
    now = _now(36)
    monday = _monday_after(now)
    monkeypatch.setattr(rd, 'REST_DAYS', (monday,))
    rk = _queue(now, keys)
    assert _rows(rk)[0]['scheduled_for'].date() != monday


def test_a_week_with_no_free_day_queues_nothing(bank, keys, monkeypatch):
    bank('A verse that carried me through my single season')
    now = _now(39)
    monday = _monday_after(now)
    monkeypatch.setattr(rd, 'REST_DAYS', tuple(monday + timedelta(days=i) for i in range(7)))
    assert _queue(now, keys) is None


def test_a_week_past_the_known_calendar_queues_nothing(bank, keys, monkeypatch):
    bank('What I hope my home will feel like')
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', _KNOWN_THROUGH)
    now = datetime.combine(max(date.today(), _KNOWN_THROUGH) + timedelta(days=14),
                           time(12, 0), timezone.utc)
    assert _queue(now, keys) is None


def test_the_cron_does_nothing_until_switched_on(monkeypatch):
    import service.cron.questionofweek as cron
    monkeypatch.setattr(cron, 'ENABLED', False)
    assert asyncio.run(asyncio.wait_for(cron.question_of_week_forever(), timeout=2)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_of_week.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'queue_question_of_week' from 'service.spotlight.growthposts'`.

- [ ] **Step 3: Write the implementation**

Append to `service/spotlight/growthposts.py`:

```python
# The caption the owner approves with each post. Wording to be confirmed by
# the owner (copy pass) before the cron is switched on.
QUESTION_CAPTION = 'Question of the week: {text}'

_Q_NEXT_PROMPT = """
    SELECT b.key, b.text
      FROM prompt_bank b
     WHERE b.active
     ORDER BY (SELECT max(q.created_at) FROM publishing_queue q
                WHERE q.kind = 'prompt' AND q.payload->>'prompt_key' = b.key) ASC NULLS FIRST,
              b.sort, b.key
     LIMIT 1
"""

# A day "the brand calendar leaves empty" is a day with nothing scheduled
# that is not cancelled: brand posts, member cards and roundups all count.
_Q_DAY_TAKEN = """
    SELECT 1 FROM publishing_queue
     WHERE status <> 'cancelled'
       AND scheduled_for >= %(start)s AND scheduled_for < %(end)s
     LIMIT 1
"""


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def _free_slot_in_week(tx, monday: date, now: datetime) -> Optional[datetime]:
    for i in range(7):
        day = monday + timedelta(days=i)
        start = datetime.combine(day, time(0, 0), timezone.utc)
        if tx.execute(_Q_DAY_TAKEN, dict(start=start, end=start + timedelta(days=1))).fetchone():
            continue
        for hour in SLOT_HOURS:
            slot = datetime.combine(day, time(hour, 0), timezone.utc)
            if slot_problem(slot, now) is None:
                return slot
    return None


def queue_question_of_week(tx, *, now: Optional[datetime] = None,
                           created_by: str = 'cron') -> Optional[str]:
    """Queue next ISO week's prompt post and return its request key, or the
    key already queued for that week. None when the bank holds no active
    prompt or no day of the week is free and valid. Unlike a gathering's
    post, a slot past the known calendar is not taken: nothing makes this
    post urgent enough to queue before the owner's calendar is read."""
    now = now or datetime.now(timezone.utc)
    ahead = (now + timedelta(days=7)).astimezone(timezone.utc).date()
    monday = ahead - timedelta(days=ahead.weekday())
    rk = f'prompt:{week_key(monday)}'
    if tx.execute(_Q_KEY_TAKEN, dict(rk=rk)).fetchone():
        return rk
    prompt = tx.execute(_Q_NEXT_PROMPT).fetchone()
    if prompt is None:
        return None
    slot = _free_slot_in_week(tx, monday, now)
    if slot is None:
        return None
    create_candidate(tx, kind='prompt', subject_person_id=None,
                     caption=QUESTION_CAPTION.format(text=prompt['text']),
                     created_by=created_by, request_key=rk,
                     target_path='/', utm_content=prompt['key'])
    tx.execute(_Q_SET_SLOT, dict(
        w=slot, p=json.dumps(dict(prompt_key=prompt['key'], text=prompt['text'])), rk=rk))
    return rk
```

Create `service/cron/questionofweek/__init__.py`:

```python
"""The weekly "Question of the week" post (TEC-1845).

Queues next week's prompt post once a day; the request key is the ISO week,
so every run after the first that week changes nothing. The post waits for
its artwork and the owner's approval like every other. Off unless
DUO_CRON_QUESTION_OF_WEEK_ENABLED is set to 1, true, yes or on: the owner
confirms the caption and the bank's wording first.
"""
from __future__ import annotations

import asyncio
import os
import random

from database import api_tx
from service.cron.cronutil import MAX_RANDOM_START_DELAY, env_int, print_stacktrace
from service.spotlight.growthposts import queue_question_of_week

ENABLED = os.environ.get('DUO_CRON_QUESTION_OF_WEEK_ENABLED', '').strip().lower() in (
    '1', 'true', 'yes', 'on')
POLL_SECONDS = env_int('DUO_CRON_QUESTION_OF_WEEK_POLL_SECONDS', 60 * 60 * 24)

print(f'Hello from cron module: {__name__}')


def _queue_once() -> None:
    with api_tx() as tx:
        rk = queue_question_of_week(tx)
    print(f'question_of_week: {rk or "nothing queued (empty bank or no free day)"}')


async def question_of_week_forever() -> None:
    if not ENABLED:
        print('question_of_week: disabled, set DUO_CRON_QUESTION_OF_WEEK_ENABLED=1')
        return
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(lambda: asyncio.to_thread(_queue_once))
        await asyncio.sleep(POLL_SECONDS)
```

In `service/cron/__init__.py`, add after the `lead_retention_forever` import:

```python
from service.cron.questionofweek import question_of_week_forever
```

and after `lead_retention_forever(),` in `asyncio.gather(...)`:

```python
        # The weekly "Question of the week" post (TEC-1845): next week's,
        # queued once, waiting for artwork and approval. Off unless
        # DUO_CRON_QUESTION_OF_WEEK_ENABLED=1. Daily.
        question_of_week_forever(),
```

In `docker-compose.production.yml`, in the `cron` service's `environment`, after `DUO_CRON_REFERRAL_INTRO_POLL_SECONDS: ${DUO_CRON_REFERRAL_INTRO_POLL_SECONDS:-86400}`:

```yaml
      # The weekly prompt post (TEC-1845). Off until the owner confirms the
      # caption and the prompt bank's wording.
      DUO_CRON_QUESTION_OF_WEEK_ENABLED: ${DUO_CRON_QUESTION_OF_WEEK_ENABLED:-0}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_of_week.py tests/test_event_posts.py -q -p no:warnings`
Expected: all pass (9 new, the event suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/spotlight/growthposts.py service/cron/questionofweek/__init__.py service/cron/__init__.py docker-compose.production.yml tests/test_question_of_week.py
git -c user.email=admin@techbaseltd.com commit -m "feat(publishing): one question of the week from the prompt bank, on a free day" -m "Refs: TEC-1845"
```

---

### Task 12: The Sources table

**Files:**
- Create: `service/growth/sources.py`
- Modify: `service/api/admin/growth_routes.py` (import after line 17; route after `get_admin_growth_stats`)
- Test: `tests/test_growth_sources.py` (create)

**Interfaces:**
- Consumes: `person.lead_source` (Tasks 1, 2, 4); `lead` (Task 1); `service.admin.queries.engagement._SENT_MESSAGES`; `service.admin.queries.members.member_sql`; `service.growth.queries._excluded`; `source_kind` (Task 2).
- Produces: `service.growth.sources.source_rows(tx) -> list[dict]`; `GET /admin/growth/sources` (admin only) returning `{"sources": [{"source": str, "kind": str, "leads": int, "confirmed_leads": int, "signups": int, "conversed": int}]}`, sorted by sign-ups, then leads, then source. `signups` counts members (staff and test accounts out); `conversed` counts those with at least one conversation both people have written in; `source` is `'unknown'` for members with no source.

- [ ] **Step 1: Write the failing test**

Create `tests/test_growth_sources.py`:

```python
"""The Sources table (growth spec, Dashboard; TEC-1845).

One row per source on the taxonomy, with the leads it brought, how many of
them confirmed, the members who signed up from it and how many of those
reached a conversation both people have written in. Members only: staff
and test accounts are left out, as on the rest of the Growth tab. Message
content is never read; this counts rows, as engagement.py does.
"""
from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('growth_schema')

_MAM_SEQ = [0]


def _uuid_of(person_id: int) -> str:
    with api_tx('read committed') as tx:
        return str(tx.execute('SELECT uuid FROM person WHERE id = %(i)s',
                              dict(i=person_id)).fetchone()['uuid'])


def _message(sender, recipient) -> None:
    """Two rows, one in each archive, as the chat service writes them
    (copied from tests/test_admin_engagement.py)."""
    _MAM_SEQ[0] += 1
    sender_uuid, recipient_uuid = _uuid_of(sender['id']), _uuid_of(recipient['id'])
    with api_tx() as tx:
        mam_id = tx.execute(
            "SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::bigint * 256 + %(seq)s AS id",
            dict(seq=_MAM_SEQ[0] % 256)).fetchone()['id']
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'O', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id, pid=sender['id'], jid=recipient_uuid))
        tx.execute(
            """INSERT INTO mam_message (id, direction, message, person_id, from_jid, remote_bare_jid)
               VALUES (%(id)s, 'I', ''::bytea, %(pid)s, '', %(jid)s)""",
            dict(id=mam_id + 1, pid=recipient['id'], jid=sender_uuid))


def _headers(person, admin: bool) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                       dict(i=person['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=person['id']))
    return {'Authorization': f'Bearer {tok}'}


def _set_source(person, source):
    with api_tx() as tx:
        tx.execute('UPDATE person SET lead_source = %(s)s WHERE id = %(i)s',
                   dict(s=source, i=person['id']))


@pytest.fixture
def leads():
    made: list[str] = []

    def add(source: str, confirmed: bool) -> None:
        email = f'src-{uuid4().hex[:10]}@example.org'
        made.append(email)
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO lead (email, normalized_email, source, confirmed_at)
                   VALUES (%(e)s, %(e)s, %(s)s, CASE WHEN %(c)s THEN NOW() END)""",
                dict(e=email, s=source, c=confirmed))

    yield add
    with api_tx() as tx:
        tx.execute('DELETE FROM lead WHERE email = ANY(%(e)s)', dict(e=made))


def _sources(client, headers) -> dict:
    r = client.get('/admin/growth/sources', headers=headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    return {row['source']: row for row in r.get_json()['sources']}


def test_each_source_counts_its_leads_sign_ups_and_conversations(client, make_person, leads):
    headers = _headers(make_person(name='SrcAdmin'), admin=True)
    source = f'event:src-{uuid4().hex[:8]}'
    a, b = make_person(name='SrcA', gender='Woman'), make_person(name='SrcB', gender='Woman')
    other = make_person(name='SrcOther')
    _set_source(a, source)
    _set_source(b, source)
    leads(source, confirmed=True)
    leads(source, confirmed=False)
    _message(a, other)
    _message(other, a)      # a's conversation has both voices
    _message(b, other)      # b's has one: not a conversation yet
    row = _sources(client, headers)[source]
    assert row == dict(source=source, kind='event', leads=2, confirmed_leads=1,
                       signups=2, conversed=1)


def test_a_source_with_leads_and_no_sign_ups_yet_is_listed(client, make_person, leads):
    headers = _headers(make_person(name='SrcAdmin2'), admin=True)
    source = f'event:src-{uuid4().hex[:8]}'
    leads(source, confirmed=True)
    row = _sources(client, headers)[source]
    assert (row['leads'], row['signups'], row['conversed']) == (1, 0, 0)


def test_staff_are_not_counted(client, make_person):
    headers = _headers(make_person(name='SrcAdmin3'), admin=True)
    source = f'tool:src-{uuid4().hex[:8]}'
    staff = make_person(name='SrcStaff')
    _headers(staff, admin=True)
    _set_source(staff, source)
    assert source not in _sources(client, headers)


def test_members_with_no_source_are_one_unknown_row(client, make_person):
    headers = _headers(make_person(name='SrcAdmin4'), admin=True)
    make_person(name='SrcUnknown')
    row = _sources(client, headers)['unknown']
    assert row['kind'] == 'unknown' and row['signups'] >= 1


def test_the_table_is_for_admins_only(client, make_person):
    member = _headers(make_person(name='SrcMember'), admin=False)
    assert client.get('/admin/growth/sources', headers=member).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_growth_sources.py -q -p no:warnings`
Expected: every test fails with status 404 for `/admin/growth/sources`.

- [ ] **Step 3: Write the implementation**

Create `service/growth/sources.py`:

```python
"""The Sources table on the Growth tab (growth spec, Dashboard; TEC-1845).

One row per source on the taxonomy (service/leads/sources.py): the leads it
brought and how many confirmed, the members who signed up from it, and how
many of those reached a conversation both people have written in. Members
are counted as the rest of the Growth tab counts them: activated, not
staff, not a test address. Message content is never read; conversations
come from the same _SENT_MESSAGES the Overview uses.
"""
from __future__ import annotations

from service.admin.queries.engagement import _SENT_MESSAGES
from service.admin.queries.members import member_sql
from service.growth.queries import _excluded
from service.leads.sources import source_kind

_Q_SOURCES = f"""
    WITH members AS (
        SELECT p.id, COALESCE(p.lead_source, 'unknown') AS source
          FROM person p
         WHERE p.activated AND {member_sql('p')} AND lower(p.email) <> ALL(%(ex)s)
    ),
    sent AS ({_SENT_MESSAGES}),
    answered AS (
        SELECT lo, hi FROM sent GROUP BY lo, hi HAVING count(DISTINCT sender_id) >= 2
    ),
    conversed AS (
        SELECT lo AS id FROM answered UNION SELECT hi FROM answered
    ),
    signups AS (
        SELECT m.source, count(*) AS signups,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM conversed c WHERE c.id = m.id)) AS conversed
          FROM members m
         GROUP BY m.source
    ),
    leads AS (
        SELECT source, count(*) AS leads,
               count(*) FILTER (WHERE confirmed_at IS NOT NULL) AS confirmed_leads
          FROM lead
         GROUP BY source
    )
    SELECT COALESCE(s.source, l.source)        AS source,
           COALESCE(l.leads, 0)::int            AS leads,
           COALESCE(l.confirmed_leads, 0)::int  AS confirmed_leads,
           COALESCE(s.signups, 0)::int          AS signups,
           COALESCE(s.conversed, 0)::int        AS conversed
      FROM signups s
      FULL OUTER JOIN leads l ON l.source = s.source
     ORDER BY signups DESC, leads DESC, source
"""


def source_rows(tx) -> list[dict]:
    rows = tx.execute(_Q_SOURCES, dict(ex=_excluded())).fetchall()
    return [dict(r, kind=source_kind(None if r['source'] == 'unknown' else r['source']))
            for r in rows]
```

In `service/api/admin/growth_routes.py`, after line 17 (`from service.growth.queries import growth_stats`):

```python
from service.growth.sources import source_rows
```

and after `get_admin_growth_stats`:

```python
@aget('/admin/growth/sources')
def get_admin_growth_sources(s: t.SessionInfo):
    """The Sources table (TEC-1845): leads, sign-ups and members who reached
    a two-sided conversation, per source on one taxonomy."""
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(sources=source_rows(tx))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_growth_sources.py tests/test_admin_engagement.py -q -p no:warnings`
Expected: all pass (5 new; the engagement suite, which reads `engagement.py` for content columns, unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/growth/sources.py service/api/admin/growth_routes.py tests/test_growth_sources.py
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): a Sources table of leads, sign-ups and conversations per source" -m "Refs: TEC-1845"
```

---

### Task 13: The share-image helper (web)

**Files (ahavah-web, branch `growth-foundations`):**
- Create: `src/lib/share-image/sizes.ts`, `src/lib/share-image/mark.tsx`, `src/lib/share-image/templates.tsx`, `src/lib/share-image/render.tsx`, `src/lib/share-image/summary.ts`
- Modify: `src/app/apple-icon.tsx`
- Test: `tests/lib/share-image.test.ts` (create)

**Interfaces:**
- Consumes: `apiOrigin()` from `src/lib/api-origin.ts`; `ImageResponse` from `next/og`.
- Produces: `SHARE_SIZES: { link: {width: 1200, height: 630}, feed: {width: 1080, height: 1350}, story: {width: 1080, height: 1920} }`, `type ShareSizeName = 'link' | 'feed' | 'story'`; `BRAND_NAVY = '#0E0040'`, `BRAND_LIME = '#D7FF81'`, `AhavahMark({ size }: { size: number }): JSX.Element`; `type ShareTemplate = (props: { size: { width: number; height: number }; data: Record<string, unknown> }) => React.ReactElement`, `SHARE_TEMPLATES: Record<string, ShareTemplate>` (holds `fallback`; each Claude Design template is registered here at handoff), `templateFor(name: string): ShareTemplate`; `SHARE_IMAGE_CACHE: string`, `renderShareImage(opts: { template: string; size: ShareSizeName; data?: Record<string, unknown> }): ImageResponse`; `fetchPublicSummary<T>(path: string, parse: (raw: unknown) => T | null, timeoutMs?: number): Promise<T | null>`. A feature's `opengraph-image.tsx` calls `fetchPublicSummary` for its public summary (for example `/tools/r/{share_token}`), then `renderShareImage` with its template, falling back to `fallback` when the summary is null.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/share-image.test.ts`:

```ts
// @vitest-environment node
//
// The share-image helper (TEC-1845, growth foundations). Every feature's
// opengraph-image route draws through it: one set of sizes, one mark, one
// template registry with a fallback, one way to read a public summary from
// the API that never throws. The templates themselves come from Claude
// Design; only the fallback (the app icon's mark on its navy) ships here.
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiOrigin } from "@/lib/api-origin";
import { renderShareImage, SHARE_IMAGE_CACHE } from "@/lib/share-image/render";
import { SHARE_SIZES } from "@/lib/share-image/sizes";
import { fetchPublicSummary } from "@/lib/share-image/summary";
import { BRAND_NAVY } from "@/lib/share-image/mark";
import { SHARE_TEMPLATES, templateFor } from "@/lib/share-image/templates";

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

describe("share sizes", () => {
  it("are the link preview, the feed card and the story card", () => {
    expect(SHARE_SIZES).toEqual({
      link: { width: 1200, height: 630 },
      feed: { width: 1080, height: 1350 },
      story: { width: 1080, height: 1920 },
    });
  });
});

describe("templates", () => {
  it("falls back for a name nobody registered, including an inherited one", () => {
    expect(templateFor("no-such-template")).toBe(SHARE_TEMPLATES.fallback);
    expect(templateFor("__proto__")).toBe(SHARE_TEMPLATES.fallback);
    expect(templateFor("toString")).toBe(SHARE_TEMPLATES.fallback);
  });

  it("draws the fallback on the brand navy", () => {
    const element = templateFor("fallback")({ size: SHARE_SIZES.link, data: {} });
    expect((element.props as { style: { background: string } }).style.background).toBe(BRAND_NAVY);
  });
});

describe("renderShareImage", () => {
  it.each(["link", "feed", "story"] as const)("renders a %s image at its size, cached", async (size) => {
    const res = renderShareImage({ template: "fallback", size });
    expect(res.headers.get("content-type")).toBe("image/png");
    expect(res.headers.get("cache-control")).toBe(SHARE_IMAGE_CACHE);
    const bytes = Buffer.from(await res.arrayBuffer());
    expect([...bytes.subarray(0, 8)]).toEqual(PNG_SIGNATURE);
    expect(bytes.readUInt32BE(16)).toBe(SHARE_SIZES[size].width);
    expect(bytes.readUInt32BE(20)).toBe(SHARE_SIZES[size].height);
  });
});

describe("fetchPublicSummary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const parse = (raw: unknown) =>
    raw && typeof raw === "object" && typeof (raw as { score?: unknown }).score === "number"
      ? (raw as { score: number })
      : null;

  it("reads a summary from the API and parses it", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ score: 82 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchPublicSummary("/tools/r/abc123", parse)).resolves.toEqual({ score: 82 });
    expect(fetchMock).toHaveBeenCalledWith(`${apiOrigin()}/tools/r/abc123`, expect.any(Object));
  });

  it("answers null for a missing summary, a bad body, a parse refusal or a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("gone", { status: 404 })));
    await expect(fetchPublicSummary("/tools/r/x", parse)).resolves.toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not json", { status: 200 })));
    await expect(fetchPublicSummary("/tools/r/x", parse)).resolves.toBeNull();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ score: "high" }), { status: 200 })));
    await expect(fetchPublicSummary("/tools/r/x", parse)).resolves.toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(fetchPublicSummary("/tools/r/x", parse)).resolves.toBeNull();
  });

  it("gives up after its time limit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new Error("aborted")));
          }),
      ),
    );
    await expect(fetchPublicSummary("/tools/r/x", parse, 20)).resolves.toBeNull();
  });

  it("refuses a path that is not a plain API path, without calling anything", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const path of ["https://evil.example/x", "//evil.example/x", "tools/r/x", "/tools/r/x?y=1", "/a/../b"]) {
      await expect(fetchPublicSummary(path, parse)).resolves.toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/share-image.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/share-image/render"`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/share-image/sizes.ts`:

```ts
// The three share images every growth feature draws (growth spec; couple
// tools and events specs): the link preview, the feed card and the story
// card saved to a phone.
export const SHARE_SIZES = {
  link: { width: 1200, height: 630 },
  feed: { width: 1080, height: 1350 },
  story: { width: 1080, height: 1920 },
} as const;

export type ShareSizeName = keyof typeof SHARE_SIZES;
```

Create `src/lib/share-image/mark.tsx`:

```tsx
// Satori (the renderer behind ImageResponse) reads JSX as a layout
// description, not real DOM, and inline `style` is its documented API. The
// design-system rule against inline styles does not apply here.
/* eslint-disable no-restricted-syntax */

// The Ahavah mark and its two colours, exactly as src/app/apple-icon.tsx has
// always drawn them, kept in one place so every share image and the app
// icon agree.
export const BRAND_NAVY = "#0E0040";
export const BRAND_LIME = "#D7FF81";

const OUTER =
  "M67.7677 29.1329C74.8346 28.497 82.1993 30.1794 88.4938 33.3976C97.8192 38.1597 104.86 46.4444 108.057 56.4154C112.848 71.3487 109.488 82.3457 102.728 95.5076C107.944 96.8715 110.019 97.1291 115.192 98.1545C115.403 100.551 115.866 106.267 114.443 108.047C110.694 112.732 98.3044 107.959 94.5211 105.082C91.4563 107.766 88.0684 110.06 84.4359 111.907C70.5855 118.866 50.7145 118.44 39.1702 107.318C30.9223 99.37 29.1828 89.0905 32.7669 78.5538C33.6752 76.5657 34.8513 74.711 36.2624 73.0417C44.0893 63.7896 57.7061 62.928 68.0198 68.1619C73.8877 71.1396 77.5088 75.5554 82.0833 80.0588C85.4134 83.3521 88.875 86.5098 92.4598 89.5241C96.8002 82.0263 98.8984 74.8331 97.6724 66.0881C94.9604 46.7454 74.566 35.2311 57.2677 45.6514C52.898 48.2837 50.3703 52.357 47.4033 56.3705C42.1762 54.8322 40.4335 54.2021 36.2436 50.9248C42.0286 37.5872 53.8697 30.9664 67.7677 29.1329Z";
const INNER =
  "M54.1348 77.7702C65.0972 77.4352 69.2156 84.1011 76.2181 91.1931C78.9263 93.9358 81.0222 95.8002 84.0349 98.2127C80.1833 100.455 77.3305 101.887 73.1084 103.258C65.39 105.146 55.6735 104.485 49.2626 99.5276C44.3941 95.7625 40.7496 87.4988 45.1307 82.0646C47.5332 79.0849 50.5075 78.1993 54.1348 77.7702Z";

// Called as a function (`AhavahMark({ size })`) inside ImageResponse trees,
// so the renderer is handed a plain <svg> element.
export function AhavahMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 145 145" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d={OUTER} fill={BRAND_LIME} />
      <path d={INNER} fill={BRAND_NAVY} />
    </svg>
  );
}
```

Create `src/lib/share-image/templates.tsx`:

```tsx
// Same eslint rationale as mark.tsx: Satori layout, inline style is its API.
/* eslint-disable no-restricted-syntax */
import type { ReactElement } from "react";

import { AhavahMark, BRAND_NAVY } from "@/lib/share-image/mark";

export type ShareTemplate = (props: {
  size: { width: number; height: number };
  data: Record<string, unknown>;
}) => ReactElement;

// Drawn when a feature's template is missing or its summary could not be
// read: the app icon's mark on its navy, at 40 per cent of the shorter side.
// It carries no words and no answers, so it can never show anything private.
const fallback: ShareTemplate = ({ size }) => (
  <div
    style={{
      width: "100%",
      height: "100%",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: BRAND_NAVY,
    }}
  >
    {AhavahMark({ size: Math.round(Math.min(size.width, size.height) * 0.4) })}
  </div>
);

// Each Claude Design template from the "Growth social set" brief is added
// here at handoff, under the name its feature's opengraph-image asks for.
export const SHARE_TEMPLATES: Record<string, ShareTemplate> = { fallback };

export function templateFor(name: string): ShareTemplate {
  return Object.prototype.hasOwnProperty.call(SHARE_TEMPLATES, name)
    ? SHARE_TEMPLATES[name]
    : SHARE_TEMPLATES.fallback;
}
```

Create `src/lib/share-image/render.tsx`:

```tsx
import { ImageResponse } from "next/og";

import { SHARE_SIZES, type ShareSizeName } from "@/lib/share-image/sizes";
import { templateFor } from "@/lib/share-image/templates";

// A share image changes only when its result does. An hour in the browser,
// a day at the edge, and a week of serving the old one while a new one is
// drawn; a deleted result's image is gone within the day.
export const SHARE_IMAGE_CACHE = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800";

export function renderShareImage({
  template,
  size,
  data = {},
}: {
  template: string;
  size: ShareSizeName;
  data?: Record<string, unknown>;
}): ImageResponse {
  const dims = SHARE_SIZES[size];
  // Called as a function so the renderer is handed plain elements.
  const element = templateFor(template)({ size: dims, data });
  return new ImageResponse(element, { ...dims, headers: { "Cache-Control": SHARE_IMAGE_CACHE } });
}
```

Create `src/lib/share-image/summary.ts`:

```ts
import { apiOrigin } from "@/lib/api-origin";

// A plain API path: slashes, letters, digits, hyphens and underscores. No
// host, no query, no dots, so a share image can only ever read our own API.
const SAFE_PATH = /^\/[A-Za-z0-9_\-/]*$/;

// Reads a public summary (a result's score and archetype, a gathering's
// title and date) for a share image. Never throws: a missing, slow, broken
// or refused summary is null, and the caller draws the fallback, because an
// image route that errors leaves a link with no preview at all.
export async function fetchPublicSummary<T>(
  path: string,
  parse: (raw: unknown) => T | null,
  timeoutMs = 3000,
): Promise<T | null> {
  if (!SAFE_PATH.test(path) || path.startsWith("//")) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${apiOrigin()}${path}`, {
      signal: controller.signal,
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return parse(await res.json());
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
```

Replace `src/app/apple-icon.tsx` with:

```tsx
// Satori (the renderer behind ImageResponse) consumes JSX as a layout
// description, not real DOM: there is no className/cva path here, and
// inline `style` is the documented API. The design-system lint rule
// against inline styles does not apply. The mark and its colours live in
// src/lib/share-image/mark.tsx, shared with every share image.
/* eslint-disable no-restricted-syntax */
import { ImageResponse } from "next/og";

import { AhavahMark, BRAND_NAVY } from "@/lib/share-image/mark";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: BRAND_NAVY,
          borderRadius: 40,
        }}
      >
        {AhavahMark({ size: 145 })}
      </div>
    ),
    { ...size },
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/share-image.test.ts`
Expected: PASS, 10 tests. Then `cd /d/Antigravity/ahavah-web && npx eslint src/lib/share-image src/app/apple-icon.tsx` reports no errors.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/share-image/sizes.ts src/lib/share-image/mark.tsx src/lib/share-image/templates.tsx src/lib/share-image/render.tsx src/lib/share-image/summary.ts src/app/apple-icon.tsx tests/lib/share-image.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(share): one share-image helper, with the app icon's mark as its fallback" -m "Refs: TEC-1845"
```

---

### Task 14: The privacy paragraph for leads (web, held for the owner)

**Files (ahavah-web, branch `growth-privacy`, from `master`):**
- Create: `src/lib/legal-leads-copy.ts`
- Modify: `src/app/privacy/page.tsx` (`SECTIONS`, after the `how-you-found-us` entry)
- Modify: `src/app/legal/privacy/page.tsx` (`sections`, after the `how-you-found-us` entry)
- Test: `tests/app/legal-leads.test.tsx` (create)

**Interfaces:**
- Consumes: `type LegalCopy` from `src/lib/legal-spotlight-copy.ts`.
- Produces: `LEADS_PRIVACY: LegalCopy`, shown on both privacy pages under the slug `before-you-join`. Each feature plan adds its own paragraph (tool results, RSVPs, alerts, introductions, mentor links, shared conversations) the same way, in the release that starts storing it.

- [ ] **Step 1: Get the wording approved**

Run the draft below through `/copy-pass` (ux-writing for the heading, humanizer for the body), then hand it to the owner in the session and wait for his yes or his changes. Nothing below is committed until then.

Heading: `Before you join`

Body: `If you give us your email before you join, to save a game or marriage checklist result or to hear when someone who fits joins, we keep it with a note of which of these you used and when. We use your email only to send what you asked for. Other members never see it, and every email has a link to stop them. We delete it 12 months after your last visit, or sooner if you ask at support@ahavah.app. If you later join, we note which of these brought you, to see which outreach works.`

Gathering replies are left out on purpose. Organisers see a guest's name and party size, and see the email only if the guest ticks the share box. The news box is on the reply form only. The events plan adds its own paragraph, saying who sees what, in the release that starts storing replies.

Expected: the owner's approved text. Where it differs from the draft, use his text in Steps 2 and 4 and adjust the test's matched phrases to his words.

- [ ] **Step 2: Write the failing test**

Create `tests/app/legal-leads.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { it, expect, vi } from "vitest";

// Same router stub as tests/app/legal-spotlight.test.tsx: the /legal pages
// call useRequireSession(), which needs a mounted App Router.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
}));

import PublicPrivacyPage from "@/app/privacy/page";
import PrivacyPage from "@/app/legal/privacy/page";
import { LEADS_PRIVACY } from "@/lib/legal-leads-copy";

// Both pages render the same paragraph, and the shells may duplicate a
// section for mobile and desktop, so the assertions count "at least one".
it.each([
  ["the public privacy page", PublicPrivacyPage],
  ["the signed-in privacy page", PrivacyPage],
])("%s says what is kept before joining, for how long and how to delete it", (_name, Page) => {
  render(<Page />);
  expect(screen.getAllByText(LEADS_PRIVACY.title).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/12 months after your last visit/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/Other members never see it/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/support@ahavah\.app/).length).toBeGreaterThan(0);
});

// Organisers see some of a gathering reply, so "Other members never see it"
// would be false for one. Replies get the events plan's own paragraph.
it("leaves gathering replies to the events plan's paragraph", () => {
  expect(LEADS_PRIVACY.body).not.toMatch(/gathering/i);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-leads.test.tsx`
Expected: FAIL, `Failed to resolve import "@/lib/legal-leads-copy"`.

- [ ] **Step 4: Write the implementation**

Create `src/lib/legal-leads-copy.ts`:

```ts
/**
 * What Ahavah keeps about someone who gives an email before joining
 * (TEC-1845, the API's lead table: a game or checklist result saved, an
 * alert). Gathering replies have their own paragraph, added by the events
 * plan, because organisers see some of them. The same paragraph is on /privacy and
 * /legal/privacy; edit it here, never in a page. Wording approved by the
 * owner on the date in the commit that last changed it.
 */
import type { LegalCopy } from "@/lib/legal-spotlight-copy";

export const LEADS_PRIVACY: LegalCopy = {
  title: "Before you join",
  body: "If you give us your email before you join, to save a game or marriage checklist result or to hear when someone who fits joins, we keep it with a note of which of these you used and when. We use your email only to send what you asked for. Other members never see it, and every email has a link to stop them. We delete it 12 months after your last visit, or sooner if you ask at support@ahavah.app. If you later join, we note which of these brought you, to see which outreach works.",
};
```

In `src/app/privacy/page.tsx`, import it beside `SPOTLIGHT_PRIVACY`:

```tsx
import { LEADS_PRIVACY } from "@/lib/legal-leads-copy";
```

and add to `SECTIONS`, directly after the `how-you-found-us` entry:

```tsx
  {
    slug: "before-you-join",
    heading: LEADS_PRIVACY.title,
    body: LEADS_PRIVACY.body,
  },
```

In `src/app/legal/privacy/page.tsx`, the same import, and in `sections`, directly after the `how-you-found-us` entry:

```tsx
        {
          slug: "before-you-join",
          heading: LEADS_PRIVACY.title,
          body: LEADS_PRIVACY.body,
        },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-leads.test.tsx tests/app/legal-spotlight.test.tsx`
Expected: PASS, 6 tests.

- [ ] **Step 6: Commit on the held branch**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/legal-leads-copy.ts src/app/privacy/page.tsx src/app/legal/privacy/page.tsx tests/app/legal-leads.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(legal): the privacy pages say what is kept before someone joins" -m "Refs: TEC-1845"
```

Release rule. Foundations writes no lead in production: Task 4 records a lead at `/check-otp` only while `AHAVAH_TOOL_LEADS_ENABLED` is on, and it ships off (`docker-compose.production.yml`, `:-0`), so the live marriage checklist stores nothing new until then. `growth-privacy` is merged and pushed, `AHAVAH_TOOL_LEADS_ENABLED=1` is set on the production api, and the checklist's "We never store your answers" and "Answers never stored" lines (ahavah-web `checklist-client.tsx`) change, all in one release: the first that writes a lead, the couple tools. Never one without the others: the paragraph alone would describe data Ahavah does not collect, and the switch alone would store data the privacy page does not name.

---

### Task 15: The ahavah-admin follow-ups become issues

Event and prompt posts are "rendered from its template", and the publishing queue shows the new kinds "with their week and age". This plan builds only the API half of each. Without the admin half, event and prompt rows wait in `awaiting_render` indefinitely, and the calendar run cannot send `kind` or `target_path` (ahavah-admin `src/lib/growth-server.ts` types the brand entry as `{ slug, caption, scheduled_for, platforms }`). The repo's rule is that what remains becomes issues.

**Files:**
- Modify: `docs/superpowers/plans/2026-10-16-growth-foundations.md` (item 8 of "Spec conflicts and decisions needing the owner")

**Interfaces:**
- Consumes: `GET /admin/growth/queue?template_render=1`, `template_data`, `week`, `age_days`, `created_at` (Task 7); `POST /admin/growth/brand` with `kind` and `target_path` (Task 9); `GET /admin/growth/sources` (Task 12).
- Produces: three Linear issues in the Ahavah Admin project, each referencing TEC-1845, their ids recorded in item 8.

- [ ] **Step 1: Create the three issues**

With the Linear tools (`mcp__linear-server__save_issue`), team `Techbase Solutions LLC`, project `Ahavah Admin`, label `Client: Ahavah`, state Backlog, one issue each:

1. Title `Growth: render event and prompt posts from their Claude Design templates`. Description: `Follow-up to TEC-1845 (ahavah-api docs/superpowers/plans/2026-10-16-growth-foundations.md, Tasks 7, 10 and 11). The API lists event and prompt rows still waiting for artwork at GET /admin/growth/queue?template_render=1, each with template_data (the row's payload). Build the renderer that fills the Growth social set's templates with that data and uploads the artwork through POST /admin/growth/queue/<request_key>/image at 1080 x 1350, as the tick does for member cards. Waits for the Growth social set from Claude Design. Until it ships, event and prompt rows stay in awaiting_render.`
2. Title `Growth: the calendar run sends kind and target_path to the brand route`. Description: `Follow-up to TEC-1845 (Task 9). POST /admin/growth/brand now takes kind ('brand' or 'tool', default 'brand') and target_path (a path on the web app, default '/'). Add both to the brand entry type in src/lib/growth-server.ts and send them when a calendar entry has them, so the monthly tool post lands on its own page with utm_campaign=tool.`
3. Title `Growth: show each post's week and age on the queue, and the Sources table`. Description: `Follow-up to TEC-1845 (Tasks 7 and 12). Queue rows now carry created_at, week (ISO week of scheduled_for, e.g. 2027-W01) and age_days; show them with the new kinds (event, prompt, tool) on the publishing queue. GET /admin/growth/sources returns one row per source with leads, confirmed_leads, signups and conversed; show it as the Sources table on the Growth tab. Screens come from Claude Design through a brief.`

Expected: three issue ids, each in the Ahavah Admin project.

- [ ] **Step 2: Record the ids in item 8**

In item 8 of "Spec conflicts and decisions needing the owner", replace the sentence `Issues: renderer TEC-1894, calendar run TEC-1895, queue display and Sources table TEC-1896.` with the three ids in the order above, for example `Issues: renderer <id 1>, calendar run <id 2>, queue display and Sources table <id 3>.`, using the ids Step 1 returned.

- [ ] **Step 3: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add docs/superpowers/plans/2026-10-16-growth-foundations.md
git -c user.email=admin@techbaseltd.com commit -m "docs(growth): the admin follow-ups of the foundations are issues" -m "Refs: TEC-1845"
```

---

## Spec conflicts and decisions needing the owner

1. **Story variant of event posts.** The spec asks for "the story variant on the day". The publisher and `POST /admin/growth/queue/<rk>/image` post 1080 x 1350 or 1080 x 1080 feed cards only; nothing posts a story. This plan queues the two feed posts and leaves the story out. It needs a publisher change in ahavah-admin (and a 1080 x 1920 size here) once the Growth social set returns; the events plan is the place for it.
2. **Taxonomy rewrites existing data.** Migration 0066 rewrites `person.lead_source` for existing members (`facebook`, `invite`, `marriage_checklist`, referring hosts) and adds a `site:{host}` kind the spec does not list. Any other legacy value stays as it is and shows as its own row.
3. **Lead before first touch.** A confirmed lead's source wins over the device's first touch at sign-up (the onboardee's own tag still wins over both). Someone who clicked an Instagram post and then played the game is counted under the game.
4. **No marketing consent from the tools.** The couple tools spec has no news box, so a tool player's lead carries no consent and can only be sent what they asked for. If the owner wants news to tool players, the tools need the same unticked box as the RSVP.
5. **Question of the week caption.** `Question of the week: {text}` is a placeholder for the owner's approval; the cron stays off until he confirms it and the prompt bank's wording.
6. **Privacy wording.** Task 14's paragraph waits for the owner and publishes with the couple tools, in the same release that turns on `AHAVAH_TOOL_LEADS_ENABLED` and changes the checklist's "never stored" lines (Task 14's release rule). Until then the live checklist's sign-in code records no lead. The checklist's new wording and the terms' organiser section belong to the couple tools and events plans, and gathering replies get the events plan's own privacy paragraph.
7. **Instagram clicks.** Instagram posts carry no link, so their clicks come from the profile link. If the owner sets that link to `https://ahavah.app/?utm_source=instagram&utm_campaign=profile`, those visitors are credited `utm:instagram/profile`; today they arrive untagged.
8. **ahavah-admin follow-ups (not in this repo):** the social-queue run passes `kind` and `target_path` from a calendar entry to `/admin/growth/brand`; a template renderer reads `GET /admin/growth/queue?template_render=1` once the Growth social set returns, and until it ships event and prompt rows wait in `awaiting_render`; the Sources table and the queue's week and age display come from the admin brief, and the feature rows come with their feature plans. Issues: renderer TEC-1894, calendar run TEC-1895, queue display and Sources table TEC-1896.
9. **Unverified:** `next/og`'s `ImageResponse` loads WebAssembly; that it renders under vitest's node environment (Task 13's PNG test) was not run while writing this plan.

## Self-review

**Spec coverage.**

| Spec requirement | Task |
|---|---|
| First-touch capture end to end (findings 24, 42) | Live before this plan (owner decisions, web 01d57d7); Task 2 puts its output on the taxonomy, Task 8 tags every post link so it has something to capture |
| One `opengraph-image` helper with the brand's templates | Task 13 (helper, registry, fallback; templates added at handoff) |
| One leads table with consent and source, shared by tools, RSVPs and visitor alerts | Tasks 1, 3 |
| Confirmed email via the existing OTP flow | Task 4 (behind `AHAVAH_TOOL_LEADS_ENABLED`, off until Task 14's release rule) |
| Marketing consent only from the unticked box; no cold outreach | Tasks 3 and 5 (`news_refusal`: news needs a confirmed address and a ticked box, an alert needs a confirmed address; a tick after an unsubscribe waits for a new confirm link) |
| Confirmation by link (RSVP, visitor alert), tokens | Task 3 |
| Rate limits and free bot protection for lead mail | Task 5 (`mail_refusal`); per-recipient limits stay on the feature routes (`shared_recipient_limit`) |
| Emails through the durable outbox | Task 5 |
| Deletion after 12 months or on request | Task 6 (sweep, both hard deletes, by normalised address; an unconfirmed address goes a day after its link lapsed); a non-member's request is `DELETE FROM lead` by normalised address via `Q_DELETE_LEADS_OF`, run by support |
| New publishing kinds `event`, `prompt`, `tool`, subjectless, rendered, approved | Tasks 7, 9, 10, 11 (API side); the template renderer is an Ahavah Admin issue from Task 15 |
| `event` 10 days and 2 days before | Task 10, at queueing and at approval (story variant: conflict 1) |
| `prompt` weekly, bank rotation, empty slot | Task 11 (bank schema in Task 1) |
| `tool` monthly through the brand path | Task 9 (cadence is the calendar's content) |
| UTM tags on every post link | Task 8 |
| Publishing queue shows new kinds with week and age | Task 7 (API fields); the display is an Ahavah Admin issue from Task 15 |
| Sources table on one taxonomy, sign-ups and first conversations per source | Tasks 2, 12 (API); the table on the Growth tab is an Ahavah Admin issue from Task 15 |
| Privacy page | Task 14 (leads paragraph, released with the switch in Task 4 turned on); feature paragraphs, including gathering replies, in their plans |
| Instagram captions carry no link | Kept by `caption_for_platform`; pinned in Task 8 |
| Rows for Couple tools, Events, Alerts, Introductions, Mentors; Events tab; Moderation > Text; user drawer; Overview funnel | Not Foundations: each feature plan adds its row with its tables; the funnel is the remediation's admin brief |
| Parent or mentor role groundwork | Not Foundations (matchmaker step 3 puts it on `mentor_account`) |
| Brand calendar extended past 4 Nov with one open invitation in three | Content in ahavah-admin, not code |

**Placeholder scan.** Searched the plan for "TBD", "TODO", "implement later", "handle errors", "similar to task" and steps without code: none. The `service/leads/__init__.py` line in Task 2 is a one-line docstring Task 3 replaces in full, named as such. Task 5 Step 4 names a conditional suite (`test_unsubscribe_scopes.py`) and how to find the right one; fixed to say exactly what to run instead.

**Type consistency.** Checked across tasks: `record_lead(tx, *, email, source, marketing_consent=False, consent_wording=None) -> Optional[int]` (Tasks 3, 4, 5, 12 tests); `confirm_lead(tx, lead_id, via)` with `'otp' | 'link'` (Tasks 3, 4, 5); `lead_unsubscribed` (Task 3); `news_refusal(tx, lead_id, *, requested=False)` defined in Task 5 and used by `enqueue_for_lead` and `_refusal`; `enqueue_for_lead(..., marketing=False, requested=False, not_before=None)` (Tasks 5, 6); `tool_leads_enabled()` and `AHAVAH_TOOL_LEADS_ENABLED` (Task 4, its tests, the compose file and Task 14's release rule); `consent_pending_wording`, `consent_pending_at` in the migration (Task 1), `_Q_UPSERT`, `_Q_CONFIRM_BY_TOKEN` and the Task 3 test; `Q_DELETE_LEADS_OF` bound with `nes` by both callers (Task 6); unsubscribe scope `news` in the migration test, `enqueue_for_lead`, `_Q_UNSUB` (matched on `normalized_email`, bound `ne` in `stamp_unsubscribed`), the leads docstring and Task 5's tests (the first draft used `leads` in Task 1's test; fixed to `news`); `create_candidate(..., target_path='/', utm_content=None)` (Tasks 8, 9, 10, 11); `CALENDAR_HELD_KINDS`, `TEMPLATE_KINDS`, `CAPTION_MAX` defined in Task 7 and used in Tasks 9, 10; `event_approval_slot(payload, requested, stored, now=None)` and the payload's `starts_at` and `offset_days` (Task 10), called from `_approval_slot(kind, requested, stored, payload=None)` by approval and retry; `KNOWN_THROUGH` and `REST_DAYS` patched wherever a test's result would otherwise depend on the run date (Tasks 10, 11); `EVENT_SLUG_MAX = 45` (Task 2) matches `event_request_key`'s 64 character budget (6 + 45 + 1 + 8 + 4 = 64); `SLOT_HOURS`, `_Q_KEY_TAKEN`, `_Q_SET_SLOT` defined in Task 10 and reused in Task 11; `source_kind` (Task 2) used by Task 12; `finish_onboarding(..., email=None)` added in Task 4 before its first use; `growth_schema` added in Task 1 before any module asks for it; every API test command carries `-p ahavah-api`. The test counts in each Step 4 match the tests written in that task (Task 4: 9, Task 5: 14, Task 6: 5, Task 10: 14, Task 11: 9, Task 14: 6 with the Spotlight suite).
