# Gatherings, release 1: event pages, RSVP without an account, organisers and "Invite Ahavah"
Linear: TEC-1845

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every gathering lives at `ahavah.app/e/{slug}` with its own share image, anyone can RSVP with a name and an email and confirm by an emailed link, approved organisers run their gatherings from a magic link with no account, leaders can ask Ahavah to come, `/events` lists gatherings by region, the landing page shows "Gatherings near you" and the admin gains an Events tab, all dark behind one switch until the owner has seen every proof.

**Architecture:** The API gains migration 0071 (`organiser`, `organiser_link`, `event`, `event_rsvp`, `event_view_day`, `ahavah_invite_request` and an `organiser_id` recipient on `email_outbox`) and a `service/events` package: field rules, organisers and their links, management, the public read, RSVPs with the shared `lead` table, the calendar file, mail through the durable outbox, two hourly jobs, admin actions and retention. Ten switches, all off: four for the surfaces (`events_live` is the master) and six for the emails. Published gatherings feed the existing `event` publishing kind (`service/spotlight/growthposts.py`). The web adds `/e/{slug}`, `/rsvp/...`, `/events`, `/invite-ahavah`, `/host/...` and the landing section, transcribed from the Claude Design export; the admin adds the Events tab and the event post artwork.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pydantic, Pillow, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16, React 19, `next/og` `ImageResponse`, vitest and Testing Library (ahavah-web); Next.js, satori via `next/og`, sharp and `node --test` (ahavah-admin).

**Spec:** `docs/superpowers/specs/2026-10-13-events-design.md`, with the Events, marketing and ops parts of `docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md`. Design brief: `ahavah-web/docs/design-briefs/2026-10-13-events.md`. Source of truth for screens: `ahavah-web/Claude Design/Ahavah Events.html` (`pages/p10-events.js`, `pages/p10-ev.js`) and `Ahavah Events Emails.html` (`pages/p10-emails.js`); every string in `Claude Design/handoff/copy/10-events.md` and `10-events-emails.md`. Marketing: `docs/design-briefs/2026-10-13-marketing-pages-and-landing.md`, `Ahavah Marketing Pages and Landing.html` (`pages/p11-mk.js`, `gather()`, `header()`, `footer()`, `og()`), copy `handoff/copy/11-marketing-pages-and-landing.md`. Admin: `docs/design-briefs/2026-10-13-admin-growth-features.md`, `Ahavah Admin Growth Features.html` (`admin/admin-growth-features.jsx`), copy `handoff/copy/13-admin-growth-features.md` section 3. Event post artwork: `Ahavah Growth Social Set.html` section 4 (`export/src-social/pages/p12-social.js`, `evCard`), copy `handoff/copy/12-growth-social-set.md` section 4. Leader pack and badge: `Claude Design/export/leader-pack/` (binary, referenced by path only; see "Spec conflicts", item 23).

## Before you start

- Migration number: **0071**. 0069 is reserved for TEC-1897 (`docs/superpowers/plans/2026-10-18-admin-community-data.md`) and 0070 is used by the Unmatch branch (`.worktrees/unmatch/migrations/0070_unmatch.sql`). The deploy script (`scripts/apply-deploy-migrations.sh`) tracks files by name, so a gap or a later 0069 applies cleanly. Neither touches `email_outbox`'s recipient check, which 0071 changes.
- ahavah-api: branch `events` from `ahavah/main`. ahavah-web: branch `events` from `master` (75129f0 on 20 Oct). ahavah-admin: branch `events` from `master`. Use superpowers:using-git-worktrees. `service/campaigns/switches.py`, `docker-compose.production.yml` and `tests/conftest.py` are also edited by TEC-1897 and Unmatch: on a rebase keep every side's lines.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. The database is the shared `ahavah-api-postgres-1`; never remove, reset or recreate it or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Web tests: `cd /d/Antigravity/ahavah-web && npx vitest run <file>`. Admin tests: `cd /d/Antigravity/ahavah-admin && node --test tests/<file>.test.mjs`.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845`, no attribution trailers. Never push until Task 27 says so, and then only with the owner's go.
- Line numbers are hints measured on 20 Oct. Every edit is anchored on the code it names; trust the code over the number.
- Read `ahavah-web/AGENTS.md` and `node_modules/next/dist/docs/` before the web tasks (Next 16: `params` is a promise; `opengraph-image` reads fonts with `readFile(join(process.cwd(), ...))`).
- The web and admin tasks transcribe the export with `/sot-sync` once their tests are green. The plan fixes behaviour, data and copy; markup and kit classes come from the frame each task names.

## Global Constraints

Every task's requirements include these. Quoted lines are verbatim from the specs, the briefs or the owner's rules.

- Copy: sentence case, British spelling, no em dashes, digits for numbers, no serial comma, "Gathering" on screen and "event" in routes and data, "Marriage and courtship; never 'dating'", "Torah-observant believers, never Jewish framing", "Feasts by their biblical English names, never the rabbinic ones", "no countdowns, no 'spots filling fast', no exclamation marks". This covers UI strings, email text, captions, code comments and commit messages. Strings come verbatim from `handoff/copy/10-events.md`, `10-events-emails.md`, `11-marketing-pages-and-landing.md` and `13-admin-growth-features.md`; every line this plan adds is marked `NEW LINE` in code and listed under "Spec conflicts", item 12, for `/copy-pass` (ux-writing) and the owner.
- Consent: "The optional box is the only marketing consent", "unticked by default"; "Organisers see names and party sizes. Emails are visible only if the guest ticked 'share my email with the organiser'"; both boxes unticked; the consent wording goes "through the ux-writing skill and the owner".
- Privacy: the admin shows RSVPs as counts only, never names, emails or message content (admin brief decision 7); "Public guest lists" are out of scope; the venue and the call link are never in a public response, a share image, schema.org data, a post or an email sent before the guest confirmed, unless the organiser made the venue public.
- Leads: "Every confirmed RSVP is a lead with a source (`event:{slug}`)" through `service.leads.record_lead`; a member is never a lead.
- Mail: every email goes through the durable outbox (`service/campaigns/outbox.py`) on the brand shell (`emails/base.py render()`), behind its own switch in `service/campaigns/switches.py`, off by default, passed through as `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}` in both the api and cron blocks of `docker-compose.production.yml`; each needs `events_live` too. Display type is a title image (`title_image()`), never a typed headline (`tests/test_email_renders_on_a_phone.py` enforces it); every new email gets a row in `tests/email_samples.py`. Proofs go to `scripts/send_proofs.PROOF_TO` only, never through the outbox.
- Dark launch: while `events_live` is off every `/events`, `/e`, `/rsvp`, `/organiser`, `/host-requests` and `/invite-ahavah` route except `GET /events/status` answers 404; the web pages are not found; the sitemap has none of them; the landing section draws nothing.
- Abuse: "Per-email and per-IP limits"; the free defences only (`service.leads.mail_refusal`, the honeypot and the page stamp), as Together; Turnstile is not used.
- Screens: "Design each screen at 390 first", "Nothing scrolls sideways on a phone: region pills wrap, tags wrap, the RSVP list is rows", touch targets at least 44 px, dark first with the light variant, checked at 320, 390, 768 and 1440. Dashboards are a bento: rows full width, tiles level, no holes.
- Share images: flexbox only, fonts as files, content centred, "Never the venue".
- Social: Instagram captions carry no link and never say "link below"; no faces of members; the owner's rest days (`service/spotlight/restdays.py`, admin `src/lib/rest-days.ts`, read only to 9 Nov 2026) block promotional posts, and this plan changes neither file.

## Review Focus

The five inputs the spec implies but no requirement names, most likely to bite a guest or an organiser first. Each has a test in the task named.

1. An email security scanner opening the confirm link before the guest does: the email links to the web page, which confirms by a script call, so a bare GET of the email's link confirms nothing. Task 8, `test_the_email_link_is_the_web_page_not_the_api`; Task 17, `does not confirm until the page has loaded`.
2. The last places taken between RSVP and confirmation, and two guests confirming the last place at the same moment: places are held only by confirmed RSVPs, the confirm locks the event row and the second guest sees "This gathering is now full". Task 8, `test_two_guests_confirming_the_last_place_get_one_place`.
3. The organiser moving a published gathering to a new date or time zone: confirmed guests are emailed once with before and now in the gathering's own time, its posts are cancelled and requeued and the page says what changed. Task 5, `test_moving_a_published_gathering_emails_guests_once_and_requeues_its_posts`.
4. A title, description, name or note carrying markup, control characters or a link to a scam: escaped everywhere, cleaned at save and flagged text sends the gathering for approval even from an approved organiser. Task 3, `test_text_is_cleaned_and_flagged`; Task 9, `test_names_and_titles_are_escaped_in_every_email`.
5. A guest viewing from another time zone, or a gathering that crosses midnight for the viewer: the gathering's own time leads and "Your time" shows the viewer's day when it differs. Task 14, `shows the viewer's own day when it differs`.

## Decisions taken

The owner may change any of these; each is also in "Spec conflicts and decisions needing the owner" with its default.

From the brief's "Owner decisions this brief needs", the defaults the export marks recommended:

1. Feast label: option B, the organiser picks from the biblical English names (export 1.6, 4.10). Option A is not built.
2. Women among RSVPs: no question on the form; counted among RSVPs from members only (2.1).
3. The venue and the call link appear after the guest confirms, on the confirmed page and in the reminder, never on submit (1.1).
4. "How many are going": a switch for the organiser, off by default (1.1, 4.10).
5. "Share my email with the organiser": unticked by default (2.1).
6. Regions: the Map's continents plus "Online", online gatherings in every region (5.1); the first region comes from the visitor's time zone.
7. The safety note: the export's wording, on every in-person page and in the guest's emails for in-person gatherings.
8. The confirmed page: one quiet line and "See how it works" (2.10).
9. The organiser digest: once a day, only on days with new RSVPs, one email per gathering (3.6).
10. Organisers who are not Ahavah: the organiser's name leads, the Ahavah mark small in the header (1.1).

Admin brief: Events is its own tab after Growth; on a phone the tab is read only ("Needs a desktop"); RSVPs are counts only; invite request statuses New, Contacted, Planned, Declined.

Choices this plan makes where the spec leaves one:

- **Rollout by switch, as the spec's rollout orders it.** `events_live` turns on the event pages, RSVPs and management for organisers Ahavah created; `events_hosting` opens the public request to host; `events_list` opens `/events` and the landing section; `events_invite` opens `/invite-ahavah`. Each needs `events_live`.
- **Ahavah's own organiser** is created by an admin (`POST /admin/events/organisers`, kind `ahavah`, approved), who then receives the manage link, so Ahavah-run gatherings can run before public hosting opens.
- **Host requests use the existing sign-in code**: the web runs `/request-otp` and `/check-otp` (as the checklist does) and posts the request with that session; the request answers with the organiser's token, so a new organiser can save drafts at once (4.7).
- **The organiser's link** is a 32 character token (`service.leads.new_token`), sent as `X-Organiser-Token`, stored only as its sha256, valid 7 days ("This link works for 7 days").
- **One token per RSVP** confirms, shows, cancels and serves the calendar file. It is 32 characters, stored as its sha256. The confirm window is 7 days or until the gathering starts, whichever comes first; after confirming, the token works until the gathering ends.
- **A signed-in member's RSVP is confirmed at once**: the address is already proved, so no confirm email.
- **Places** are held only by confirmed RSVPs; a party is 1 to 10 people; one RSVP per address per gathering.
- **Statuses**: `draft`, `pending`, `published`, `cancelled` as the spec; "ended" is `published` with `ends_at` past; "paused" is `paused_at` set on a published gathering, which the public then cannot find.
- **Flags**: a description, title or cancel note caught by `antiabuse.antirude.profile.is_rude` or scoring 0.5 or more on `antiabuse.romancescam.analyze_message`, or a cover the NSFW check sends to manual review, sends the gathering to `pending` with a `flag_reason`, whoever the organiser is. A cover the check rejects is refused.
- **Organiser mail goes through the outbox** with a third recipient kind, `email_outbox.organiser_id`, since an organiser is neither a member nor a lead.
- **Guest mail** to a member goes as the member (scope `notifications`); to anyone else as their `event:{slug}` lead, exempt, since the guest asked for it. Its footer offers "Cancel my place", not the news unsubscribe.
- **Rest days**: the reminder and the digest are never queued inside one of the owner's rest periods (`restdays.is_rest_period`); the reminder goes earlier or after, always before the gathering. Confirm, change and cancellation mail go when they happen.
- **Page views** are counted by a beacon from the page, once per browser tab session, per gathering per day.
- **Retention**: an RSVP's name and email are erased 90 days after the gathering ends; an RSVP never confirmed is deleted a day after its confirm window closes; organiser links are deleted a day after they lapse; invite requests 12 months after their last change. The privacy paragraph says so (Task 24).
- **Covers** are re-encoded by the API to a 1200 by 630 JPEG (EXIF dropped), stored public under `event-covers/{uuid}.jpg` on the user images CDN.
- **The time zone label** ("Central Time", "UK time") is computed by the organiser's browser when they save (`Intl`, `longGeneric`, with "UK time" for `Europe/London`) and stored as `tz_label`, so the API's emails print the same words as the page.

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `migrations/0071_events.sql` | Create | The 6 tables and the outbox's third recipient |
| `service/events/__init__.py` | Create | `live()`, `surface_on()`, `switch_on()`, `CAMPAIGN_SWITCHES`, `EventError` |
| `service/events/fields.py`, `service/events/continents.json` | Create | Slugs, regions, feasts, tags, draft validation, text flags, time words |
| `service/events/organisers.py` | Create | Host requests, links, the organiser from a token |
| `service/events/manage.py` | Create | Create, edit, cover, publish, cancel, the organiser's lists, RSVP list, attendance |
| `service/events/public.py` | Create | The list by region, one gathering, views |
| `service/events/rsvp.py`, `service/events/ics.py` | Create | RSVP, confirm, view, cancel, resend, the calendar file |
| `service/events/mail.py` | Create | Every event email, its queueing and its proof preview |
| `service/events/jobs.py` | Create | Reminders and digests |
| `service/events/admin.py`, `service/events/invites.py` | Create | Approvals, pause, the badge, figures, invite requests |
| `service/events/retention.py` | Create | The sweep, deleting with the account, linking at sign-up |
| `service/api/events_routes.py`, `service/api/admin/events_routes.py` | Create | Every route |
| `service/api/__init__.py` | Modify | Registers both route modules |
| `duotypes/__init__.py` | Modify | Request models |
| `service/campaigns/switches.py`, `docker-compose.production.yml` | Modify | 10 switches and their pass-throughs |
| `service/campaigns/outbox.py` | Modify | `enqueue_for_organiser`, the event switches and organiser rows at send time |
| `service/cron/returnmail/__init__.py`, `service/cron/leadretention/__init__.py` | Modify | The jobs and the sweep |
| `service/person/__init__.py`, `service/hard_delete.py`, `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py` | Modify | Linking at finish-onboarding; deleting with the account |
| `scripts/send_event_proofs.py` | Create | Proofs to the owner only |
| `tests/conftest.py`, `tests/email_samples.py` | Modify | Fixtures; the new emails |
| `tests/test_migration_0071.py`, `test_events_switches.py`, `test_events_fields.py`, `test_event_organisers.py`, `test_event_manage.py`, `test_event_covers.py`, `test_events_public.py`, `test_event_rsvp.py`, `test_event_ics.py`, `test_event_mail.py`, `test_event_jobs.py`, `test_admin_events.py`, `test_event_retention.py`, `test_send_event_proofs.py` | Create | One or two files per task |

ahavah-web:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/events/api.ts`, `status.ts`, `server.ts`, `format.ts`, `region.ts`, `organiser-token.ts`, `copy.ts`, `nav.ts` | Create | Calls and types, the live check, server reads, time words, regions, the organiser's token, every string, the nav flag |
| `src/lib/share-image/events-templates.tsx`, `src/lib/share-image/templates.tsx` | Create, modify | The event link preview and the 2 page previews |
| `src/app/e/[slug]/page.tsx`, `opengraph-image.tsx` | Create | The event page and its image |
| `src/app/rsvp/confirm/[token]/page.tsx`, `src/app/rsvp/[token]/page.tsx` | Create | Confirming, the confirmed page, cancelling |
| `src/app/events/page.tsx`, `opengraph-image.tsx`; `src/app/invite-ahavah/page.tsx`, `opengraph-image.tsx` | Create | The list and the leaders' page |
| `src/app/host/page.tsx`, `src/app/host/gatherings/page.tsx`, `src/app/host/gatherings/[slug]/page.tsx`, `src/app/host/gatherings/[slug]/guests/page.tsx` | Create | Hosting |
| `src/components/events/*` | Create | Every screen's parts |
| `src/app/page.tsx`, `src/components/app/marketing-header.tsx`, `src/components/app/marketing-footer.tsx`, `src/app/sitemap.ts`, `src/app/robots.ts` | Modify | Landing section, links, sitemap, robots |
| `src/lib/legal-events-copy.ts`, `src/lib/legal-leads-copy.ts`, `src/lib/legal-organiser-terms-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx`, `src/app/terms/page.tsx` | Create, modify | Privacy and terms |
| `public/events/*` | Create | The stock photos the page previews use, copied from `Claude Design/assets/stock/` |

ahavah-admin:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/events-api.ts`, `src/lib/events-queries.ts` | Create | Pure helpers and the hooks |
| `src/components/admin/tab-events.tsx`, `events-waiting.tsx`, `events-table.tsx`, `events-requests.tsx` | Create | The Events tab |
| `src/lib/tabs.ts`, `src/components/admin/tab-router.tsx`, `src/components/admin/sidebar-nav.tsx` | Modify | The tab and its count |
| `src/lib/event-card.tsx`, `src/lib/tick.ts`, `src/lib/growth-server.ts` | Create, modify | The event post artwork and its render step |
| `tests/events-api.test.mjs`, `tests/event-card.test.mjs`, `tests/tick.test.mjs` | Create, modify | Tests |

---

## Release 1 API (ahavah-api)

### Task 1: Migration 0071, the event tables

**Files:**
- Create: `migrations/0071_events.sql`
- Modify: `tests/conftest.py` (append `events_schema`)
- Test: `tests/test_migration_0071.py` (create)

**Interfaces:**
- Consumes: `lead` and `email_outbox.lead_id` (0066).
- Produces: the tables below; `email_outbox.organiser_id` with `email_outbox_one_recipient_check` now `num_nonnulls(person_id, lead_id, organiser_id) = 1` and the partial unique index `idx__email_outbox__organiser_run`; fixture `events_schema` (session scope, applies 0066, 0068 and 0071).

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0071.py`:

```python
"""Migration 0071, gatherings (TEC-1845). Idempotent, as the deploy may run
it more than once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('events_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0071_events.sql').read_text(encoding='utf-8')

def _cols(table):
    with api_tx() as tx:
        return {r['column_name'] for r in tx.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %(t)s",
            dict(t=table)).fetchall()}

def test_runs_twice():
    with api_tx() as tx:
        tx.execute(SQL)
        tx.execute(SQL)

def test_the_tables_and_their_columns():
    assert {'id', 'name', 'kind', 'email', 'normalized_email', 'city', 'country', 'about',
            'verified_at', 'approved_at', 'approved_by', 'revoked_at', 'created_at'} <= _cols('organiser')
    assert {'organiser_id', 'token_hash', 'expires_at'} <= _cols('organiser_link')
    assert {'id', 'slug', 'organiser_id', 'title', 'starts_at', 'ends_at', 'tz', 'tz_label', 'mode',
            'city', 'country', 'region', 'venue', 'venue_visibility', 'online_url', 'description',
            'capacity', 'tags', 'feast', 'show_going', 'cover_key', 'status', 'flag_reason',
            'paused_at', 'ahavah_attending', 'cancel_note', 'changed_at', 'change_before',
            'change_after', 'published_at', 'created_at', 'updated_at'} <= _cols('event')
    assert {'id', 'event_id', 'name', 'email', 'normalized_email', 'party_size', 'status',
            'confirmed_at', 'token_hash', 'confirm_by', 'share_email_with_organiser',
            'marketing_consent', 'source', 'person_id', 'lead_id', 'new_address', 'attended_at',
            'resends', 'digested_at', 'erased_at', 'created_at'} <= _cols('event_rsvp')
    assert {'event_id', 'day', 'views'} <= _cols('event_view_day')
    assert {'gathering', 'dates', 'place', 'numbers', 'contact_name', 'contact_email', 'status',
            'notes', 'created_at', 'updated_at'} <= _cols('ahavah_invite_request')
    assert 'organiser_id' in _cols('email_outbox')

def test_status_and_mode_are_checked():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO organiser (name, kind, email, normalized_email) "
                       "VALUES ('X', 'church', 'x@a.invalid', 'x@a.invalid')")

def test_an_outbox_row_names_exactly_one_recipient():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO email_outbox (campaign, campaign_id, email, payload) "
                       "VALUES ('event_digest', 'x', 'x@a.invalid', '{}'::jsonb)")
```

- [ ] **Step 2: Run it to verify it fails**

Run: the API test command with `tests/test_migration_0071.py`.
Expected: errors, `fixture 'events_schema' not found`.

- [ ] **Step 3: Write `migrations/0071_events.sql` and the fixture**

The schema is a decision, so here it is in full. Every statement is idempotent.

```sql
-- 0071_events.sql
-- Gatherings (TEC-1845, docs/superpowers/plans/2026-10-21-events-release-1.md).
-- 0069 is reserved for TEC-1897 and 0070 is the Unmatch branch's.
--
--   organiser             who may host. Approved once by an admin; later
--                         gatherings publish without review unless flagged.
--   organiser_link        the 7 day magic link, stored as its sha256.
--   event                 a gathering. "ended" is published with ends_at past;
--                         "paused" is paused_at set.
--   event_rsvp            one per address per gathering. A place is held only
--                         once confirmed. Name and email are erased 90 days
--                         after the gathering ends (erased_at).
--   event_view_day        page views per gathering per day.
--   ahavah_invite_request leaders asking Ahavah to come.
--   email_outbox          gains organiser_id: an organiser is neither a member
--                         nor a lead.

CREATE TABLE IF NOT EXISTS organiser (
  id                BIGSERIAL    PRIMARY KEY,
  name              TEXT         NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  kind              TEXT         NOT NULL CHECK (kind IN ('assembly', 'fellowship_leader', 'ministry', 'other', 'ahavah')),
  email             TEXT         NOT NULL,
  normalized_email  TEXT         NOT NULL UNIQUE,
  city              TEXT         CHECK (char_length(city) <= 80),
  country           TEXT         CHECK (char_length(country) <= 80),
  about             TEXT         CHECK (char_length(about) <= 1000),
  verified_at       TIMESTAMPTZ,
  approved_at       TIMESTAMPTZ,
  approved_by       INT          REFERENCES person(id) ON DELETE SET NULL,
  revoked_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organiser_link (
  id            BIGSERIAL    PRIMARY KEY,
  organiser_id  BIGINT       NOT NULL REFERENCES organiser(id) ON DELETE CASCADE,
  token_hash    TEXT         NOT NULL UNIQUE,
  expires_at    TIMESTAMPTZ  NOT NULL,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__organiser_link__expires_at ON organiser_link (expires_at);

CREATE TABLE IF NOT EXISTS event (
  id                BIGSERIAL    PRIMARY KEY,
  slug              TEXT         NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 45),
  organiser_id      BIGINT       NOT NULL REFERENCES organiser(id) ON DELETE CASCADE,
  title             TEXT         NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
  starts_at         TIMESTAMPTZ  NOT NULL,
  ends_at           TIMESTAMPTZ  NOT NULL,
  tz                TEXT         NOT NULL,
  tz_label          TEXT         NOT NULL CHECK (char_length(tz_label) BETWEEN 1 AND 40),
  mode              TEXT         NOT NULL CHECK (mode IN ('in_person', 'online')),
  city              TEXT         CHECK (char_length(city) <= 80),
  country           TEXT         CHECK (char_length(country) <= 80),
  region            TEXT         NOT NULL CHECK (region IN ('africa', 'asia', 'europe', 'north-america',
                                                          'oceania', 'south-america', 'online')),
  venue             TEXT         CHECK (char_length(venue) <= 200),
  venue_visibility  TEXT         NOT NULL DEFAULT 'confirmed' CHECK (venue_visibility IN ('public', 'confirmed')),
  online_url        TEXT         CHECK (online_url ~ '^https://' AND char_length(online_url) <= 500),
  description       TEXT         NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  capacity          INT          CHECK (capacity BETWEEN 1 AND 5000),
  tags              TEXT[]       NOT NULL DEFAULT '{}',
  feast             TEXT         CHECK (feast IN ('passover', 'unleavened_bread', 'firstfruits', 'pentecost',
                                                  'trumpets', 'atonement', 'tabernacles', 'last_great_day')),
  show_going        BOOLEAN      NOT NULL DEFAULT FALSE,
  cover_key         TEXT,
  status            TEXT         NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending', 'published', 'cancelled')),
  flag_reason       TEXT,
  paused_at         TIMESTAMPTZ,
  ahavah_attending  BOOLEAN      NOT NULL DEFAULT FALSE,
  cancel_note       TEXT         CHECK (char_length(cancel_note) <= 500),
  changed_at        TIMESTAMPTZ,
  change_before     JSONB,
  change_after      JSONB,
  published_at      TIMESTAMPTZ,
  cancelled_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (ends_at > starts_at),
  CHECK (mode = 'online' OR (city IS NOT NULL AND country IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx__event__listing ON event (region, starts_at) WHERE status = 'published' AND paused_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__event__organiser ON event (organiser_id);

CREATE TABLE IF NOT EXISTS event_rsvp (
  id                          BIGSERIAL    PRIMARY KEY,
  event_id                    BIGINT       NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  name                        TEXT         CHECK (char_length(name) BETWEEN 1 AND 80),
  email                       TEXT,
  normalized_email            TEXT,
  party_size                  INT          NOT NULL CHECK (party_size BETWEEN 1 AND 10),
  status                      TEXT         NOT NULL DEFAULT 'going' CHECK (status IN ('going', 'cancelled')),
  confirmed_at                TIMESTAMPTZ,
  token_hash                  TEXT         UNIQUE,
  confirm_by                  TIMESTAMPTZ  NOT NULL,
  share_email_with_organiser  BOOLEAN      NOT NULL DEFAULT FALSE,
  marketing_consent           BOOLEAN      NOT NULL DEFAULT FALSE,
  source                      TEXT         NOT NULL,
  person_id                   INT          REFERENCES person(id) ON DELETE SET NULL,
  lead_id                     BIGINT       REFERENCES lead(id) ON DELETE SET NULL,
  new_address                 BOOLEAN      NOT NULL DEFAULT FALSE,
  attended_at                 TIMESTAMPTZ,
  resends                     INT          NOT NULL DEFAULT 0,
  digested_at                 TIMESTAMPTZ,
  cancelled_at                TIMESTAMPTZ,
  erased_at                   TIMESTAMPTZ,
  created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (event_id, normalized_email),
  CHECK (erased_at IS NOT NULL OR (name IS NOT NULL AND email IS NOT NULL AND normalized_email IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx__event_rsvp__normalized_email ON event_rsvp (normalized_email);
CREATE INDEX IF NOT EXISTS idx__event_rsvp__person_id ON event_rsvp (person_id) WHERE person_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_view_day (
  event_id  BIGINT  NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  day       DATE    NOT NULL,
  views     INT     NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, day)
);

CREATE TABLE IF NOT EXISTS ahavah_invite_request (
  id             BIGSERIAL    PRIMARY KEY,
  gathering      TEXT         NOT NULL CHECK (char_length(gathering) BETWEEN 1 AND 200),
  dates          TEXT         NOT NULL CHECK (char_length(dates) BETWEEN 1 AND 120),
  place          TEXT         NOT NULL CHECK (char_length(place) BETWEEN 1 AND 200),
  numbers        INT          CHECK (numbers BETWEEN 1 AND 100000),
  contact_name   TEXT         NOT NULL CHECK (char_length(contact_name) BETWEEN 1 AND 80),
  contact_email  TEXT         NOT NULL,
  status         TEXT         NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'planned', 'declined')),
  notes          TEXT         CHECK (char_length(notes) <= 2000),
  created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS organiser_id BIGINT REFERENCES organiser(id) ON DELETE CASCADE;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id, organiser_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__organiser_run
  ON email_outbox (campaign, campaign_id, organiser_id) WHERE organiser_id IS NOT NULL;
```

Append to `tests/conftest.py`, after the Together block, a `# Gatherings (TEC-1845)` block with `events_schema(together_schema)` (session scope) that executes `0071_events.sql` the way `together_schema` executes 0068.

- [ ] **Step 4: Run it to verify it passes**

Run: the API test command with `tests/test_migration_0071.py`.
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add migrations/0071_events.sql tests/conftest.py tests/test_migration_0071.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): migration 0071, the gathering tables" -m "Refs: TEC-1845"
```

### Task 2: The 10 switches, the live checks and `GET /events/status`

**Files:**
- Modify: `service/campaigns/switches.py` (after `'together_summary_email'`)
- Modify: `docker-compose.production.yml` (api block after `AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED`, line 155; cron block after the same, line 338)
- Create: `service/events/__init__.py`, `service/api/events_routes.py`
- Modify: `service/api/__init__.py` (after `import service.api.tools_routes`)
- Modify: `tests/conftest.py` (append `events_live`, `organiser`)
- Test: `tests/test_events_switches.py` (create)

**Interfaces:**
- Consumes: `service.campaigns.switches.enabled`.
- Produces: switch names `events_live`, `events_hosting`, `events_list`, `events_invite`, `events_confirm_email`, `events_reminder_email`, `events_change_email`, `events_cancel_email`, `events_digest_email`, `events_manage_email` (variables `AHAVAH_EVENTS_LIVE_ENABLED`, `AHAVAH_EVENTS_HOSTING_ENABLED`, `AHAVAH_EVENTS_LIST_ENABLED`, `AHAVAH_EVENTS_INVITE_ENABLED`, `AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED`, `AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED`, `AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED`, `AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED`, `AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED`, `AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED`). In `service.events`: `live() -> bool`; `surface_on(name: Literal['events_hosting','events_list','events_invite']) -> bool`; `switch_on(name: str) -> bool` (live and the named switch); `CAMPAIGN_SWITCHES: dict[str, str]` = `{'event_confirm': 'events_confirm_email', 'event_reminder': 'events_reminder_email', 'event_change': 'events_change_email', 'event_cancelled': 'events_cancel_email', 'event_digest': 'events_digest_email', 'event_manage': 'events_manage_email', 'event_organiser_note': 'events_manage_email'}`; `class EventError(Exception)` with `.reason: str`, `.status: int`. Route `GET /events/status` -> `{live, hosting, list, invite}`, `Cache-Control: no-store`; helper `_off()` -> `({'error': 'not_found'}, 404)` used by every later route. Fixtures: `events_live` (sets all 10 variables to 1, the release as it is after launch; a test of a dark or closed state deletes the one it is about), and `organiser`, a factory `organiser(kind='fellowship_leader', approved=True) -> dict(id, email, token, headers={'X-Organiser-Token': token})` that deletes its rows afterwards.

- [ ] **Step 1: Write the failing test**

Create `tests/test_events_switches.py`:

```python
"""The gathering switches (TEC-1845). events_live keeps the whole release
dark; each surface and each email has its own switch and needs events_live
too. Every variable is passed to the api and the cron, defaulting to 0."""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'events_live': 'AHAVAH_EVENTS_LIVE_ENABLED',
    'events_hosting': 'AHAVAH_EVENTS_HOSTING_ENABLED',
    'events_list': 'AHAVAH_EVENTS_LIST_ENABLED',
    'events_invite': 'AHAVAH_EVENTS_INVITE_ENABLED',
    'events_confirm_email': 'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED',
    'events_reminder_email': 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED',
    'events_change_email': 'AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED',
    'events_cancel_email': 'AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED',
    'events_digest_email': 'AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED',
    'events_manage_email': 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED',
}

def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW

@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2

def test_everything_needs_the_live_switch(monkeypatch):
    from service.events import live, surface_on, switch_on
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED', '1')
    assert not live() and not surface_on('events_list') and not switch_on('events_confirm_email')
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    assert live() and surface_on('events_list') and switch_on('events_confirm_email')
    assert not surface_on('events_hosting') and not switch_on('events_digest_email')

def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/events/status')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'live': False, 'hosting': False, 'list': False, 'invite': False}
    monkeypatch.setenv('AHAVAH_EVENTS_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_EVENTS_INVITE_ENABLED', '1')
    assert client.get('/events/status').get_json() == {'live': True, 'hosting': False, 'list': False, 'invite': True}
```

- [ ] **Step 2: Run it to verify it fails**

Run: the API test command with `tests/test_events_switches.py`.
Expected: 13 failed (no switches, no compose lines, `No module named 'service.events'`, 404).

- [ ] **Step 3: Implement**

Add the 10 entries to `SWITCHES` under a comment block in the style of the Together one: the master switch's comment says every route but `/events/status` answers 404 while it is off; the email block says each is off until the owner has seen its proof. Add the 10 pass-throughs in both compose blocks under `# Gatherings (TEC-1845). Off until launch and until the owner confirms each proof.` Create `service/events/__init__.py` with a module docstring listing the package's modules (as `service/tools/__init__.py` does) and the interfaces above. Create `service/api/events_routes.py` (docstring: imported at the bottom of `service/api/__init__.py`; organisers prove who they are with the `X-Organiser-Token` header; every route but `/events/status` answers 404 while `events_live` is off) with `get_events_status`. Register it after the Together import with `# Gatherings (TEC-1845).`. Add the fixtures to `tests/conftest.py`; `organiser` inserts the row directly (verified and, when asked, approved now) and a link through `service.events.organisers.issue_link` once Task 4 exists, until then by inserting `organiser_link` with `service.leads.new_token()`.

- [ ] **Step 4: Run it to verify it passes**

Run: the API test command with `tests/test_events_switches.py`.
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/campaigns/switches.py docker-compose.production.yml service/events/__init__.py service/api/events_routes.py service/api/__init__.py tests/conftest.py tests/test_events_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gathering switches, all off, with GET /events/status" -m "Refs: TEC-1845"
```

### Task 3: Field rules: slugs, regions, feasts, tags, a draft, text flags and time words

**Files:**
- Create: `service/events/fields.py`, `service/events/continents.json`
- Test: `tests/test_events_fields.py` (create)

**Interfaces:**
- Consumes: `service.leads.sources.EVENT_SLUG_MAX` (45) and `SLUG_RE`; `antiabuse.antirude.profile.is_rude(s) -> bool`; `antiabuse.romancescam.analyze_message(text).total_score`.
- Produces, in `service.events.fields`:
  - `KINDS = ('assembly', 'fellowship_leader', 'ministry', 'other', 'ahavah')`; `MODES = ('in_person', 'online')`; `TAGS = ('singles_welcome', 'marriage_preparation')`; `REGIONS = ('africa', 'asia', 'europe', 'north-america', 'oceania', 'south-america', 'online')`.
  - `FEASTS: dict[str, str]`, in this order: `passover` Passover, `unleavened_bread` Unleavened Bread, `firstfruits` Firstfruits, `pentecost` Pentecost, `trumpets` Trumpets, `atonement` Day of Atonement, `tabernacles` Tabernacles, `last_great_day` Last Great Day (export 4.10).
  - `slug_for(title: str, suffix: Optional[str] = None) -> str`: lower-case words of the title joined by hyphens, cut on a word to at most 38 characters, then `-` and a 6 character suffix (`secrets.token_hex(3)` unless given). A title with no letters or digits gives `gathering-{suffix}`.
  - `region_for(country: str) -> str` (raises `ValueError('bad_country')`); `countries() -> list[dict]` (`{name, region}`, sorted by name).
  - `clean_text(value: object, max_len: int, *, multiline: bool = False) -> str`: strips control characters (keeps `\n` when multiline, collapses 3 or more newlines to 2), trims, refuses empty or over-length with `EventError('bad_text', 400)`.
  - `text_flag(*texts: str) -> Optional[str]`: `'rude'` when any is rude, `'scam'` when any scores 0.5 or more, else None.
  - `clean_draft(raw: dict, *, partial: bool = False) -> dict`: the organiser's fields made safe, raising `EventError(reason, 400)` with reasons `bad_title`, `bad_time`, `bad_tz`, `bad_tz_label`, `bad_mode`, `bad_country`, `bad_venue`, `bad_online_url`, `bad_description`, `bad_capacity`, `bad_tags`, `bad_feast`. Rules: `starts_at` and `ends_at` aware ISO 8601, end after start, at most 7 days long; `tz` in `zoneinfo.available_timezones()`; `tz_label` 1 to 40 letters, spaces, hyphens and full stops; in person needs city and country, online needs an `https://` call link and drops city, country and venue; `region` is set from the country or `online`; capacity empty or 1 to 5000; tags a subset of `TAGS`; feast empty or a key of `FEASTS`; venue at most 200 characters. With `partial=True` only the keys given are checked, for an edit.
  - `when_words(starts_at: datetime, ends_at: datetime, tz: str, tz_label: str) -> tuple[str, str]`: `('Saturday 7 November 2026', '6pm to 9pm, Central Time')`. Minutes show as `7.15pm`; midnight is `midnight`; an end on another day is `6pm to 2am`; a gathering over more than one day gives `('Friday 4 December 2026', '9am, East Africa Time, to Sunday 6 December, 4pm')`.

`continents.json` maps every distinct `country` in `locations/locations.json` (243 names) to one of the six continents by the UN M49 regions (so Russia is `europe`, Turkey and the Caucasus `asia`, Egypt `africa`, the Pacific islands `oceania`), with the Americas split as the Map splits them: the Caribbean, Central America and Mexico go to `north-america`. The test pins that every country maps.

- [ ] **Step 1: Write the failing test**

Create `tests/test_events_fields.py` with these tests:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from service.events import EventError
from service.events import fields as f

ROOT = Path(__file__).resolve().parent.parent
GOOD = dict(title='Marriage preparation evening', starts_at='2026-11-08T00:00:00+00:00',
            ends_at='2026-11-08T03:00:00+00:00', tz='America/Chicago', tz_label='Central Time',
            mode='in_person', city='Dallas', country='United States',
            venue='Grace Fellowship hall, 14 Elm Street, Dallas', venue_visibility='confirmed',
            description='An evening for single believers who hope to marry.', capacity=40,
            tags=['singles_welcome', 'marriage_preparation'], feast=None, show_going=False)

def test_every_country_in_the_location_list_has_a_continent():
    countries = {r['country'] for r in json.loads((ROOT / 'locations/locations.json').read_text(encoding='utf-8'))}
    table = json.loads((ROOT / 'service/events/continents.json').read_text(encoding='utf-8'))
    assert countries == set(table)
    assert set(table.values()) <= set(f.REGIONS) - {'online'}
    assert (f.region_for('United States'), f.region_for('Jamaica'), f.region_for('Brazil'),
            f.region_for('Uganda'), f.region_for('United Kingdom'), f.region_for('Fiji')) == (
        'north-america', 'north-america', 'south-america', 'africa', 'europe', 'oceania')

def test_slugs_fit_the_source_taxonomy():
    from service.leads.sources import event_source
    s = f.slug_for('A marriage preparation weekend for singles and the families who support them', 'a1b2c3')
    assert s == 'a-marriage-preparation-weekend-for-a1b2c3' and len(s) <= 45
    assert event_source(s) == f'event:{s}'
    assert f.slug_for('!!!', 'a1b2c3') == 'gathering-a1b2c3'
    assert f.slug_for('Sukkot: Atlanta', 'ff0011') == 'sukkot-atlanta-ff0011'

def test_a_good_draft_is_kept_and_gets_its_region():
    d = f.clean_draft(GOOD)
    assert d['region'] == 'north-america' and d['title'] == GOOD['title']

@pytest.mark.parametrize('change,reason', [
    (dict(title=''), 'bad_title'),
    (dict(ends_at='2026-11-07T23:00:00+00:00'), 'bad_time'),
    (dict(starts_at='2026-11-08T00:00:00'), 'bad_time'),
    (dict(ends_at='2026-11-20T00:00:00+00:00'), 'bad_time'),
    (dict(tz='Mars/Olympus'), 'bad_tz'),
    (dict(country='Atlantis'), 'bad_country'),
    (dict(mode='online', online_url='http://meet.example.com/x'), 'bad_online_url'),
    (dict(capacity=0), 'bad_capacity'),
    (dict(tags=['adults_only']), 'bad_tags'),
    (dict(feast='hanukkah'), 'bad_feast'),
])
def test_a_bad_field_is_refused(change, reason):
    with pytest.raises(EventError) as e:
        f.clean_draft({**GOOD, **change})
    assert e.value.reason == reason and e.value.status == 400

def test_an_online_gathering_drops_the_place():
    d = f.clean_draft({**GOOD, 'mode': 'online', 'online_url': 'https://meet.example.com/ahavah-talk'})
    assert d['region'] == 'online' and d['city'] is None and d['venue'] is None

def test_text_is_cleaned_and_flagged():
    assert f.clean_text('  Hello\x00 <b>there</b>\n\n\n\nfriends ', 200, multiline=True) == 'Hello <b>there</b>\n\nfriends'
    assert f.text_flag('A shared meal and time to talk.') is None
    assert f.text_flag('Send me money by Western Union and gift cards, my darling') == 'scam'

def test_the_feasts_are_the_biblical_english_names_in_order():
    assert list(f.FEASTS.values()) == ['Passover', 'Unleavened Bread', 'Firstfruits', 'Pentecost',
                                       'Trumpets', 'Day of Atonement', 'Tabernacles', 'Last Great Day']

def test_time_words_match_the_export():
    s = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
    e = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)
    assert f.when_words(s, e, 'America/Chicago', 'Central Time') == ('Saturday 7 November 2026', '6pm to 9pm, Central Time')
    s2 = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)
    e2 = datetime(2026, 11, 12, 20, 15, tzinfo=timezone.utc)
    assert f.when_words(s2, e2, 'Europe/London', 'UK time') == ('Thursday 12 November 2026', '7pm to 8.15pm, UK time')
    s3 = datetime(2026, 11, 7, 23, 0, tzinfo=timezone.utc)
    assert f.when_words(s3, s3.replace(hour=23, minute=59), 'Europe/London', 'UK time')[1] == '11pm to 11.59pm, UK time'
    assert f.when_words(datetime(2026, 11, 8, 6, tzinfo=timezone.utc), datetime(2026, 11, 8, 9, tzinfo=timezone.utc),
                        'America/Chicago', 'Central Time')[1] == 'midnight to 3am, Central Time'
```

The scam sample must score 0.5 or more on today's `analyze_message`; if it does not, pick a sentence from `antiabuse/romancescam`'s own tests that does and say so in the test.

- [ ] **Step 2: Run it to verify it fails**

Run: the API test command with `tests/test_events_fields.py`. Expected: collection error, `No module named 'service.events.fields'`.

- [ ] **Step 3: Implement `service/events/fields.py` and `continents.json`** to the interfaces above. `when_words` uses `zoneinfo.ZoneInfo(tz)`, `%-d` is not portable, so build the day with `str(local.day)`.

- [ ] **Step 4: Run it to verify it passes**

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add service/events/fields.py service/events/continents.json tests/test_events_fields.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): field rules, regions, feasts and the words for a gathering's time" -m "Refs: TEC-1845"
```

### Task 4: Organisers: the request to host, the magic link and Ahavah's own organiser

**Files:**
- Create: `service/events/organisers.py`, `service/events/mail.py` (stubs only, filled in Task 9)
- Modify: `service/api/events_routes.py`, `duotypes/__init__.py` (`PostHostRequest`, `PostOrganiserLink`), `tests/conftest.py` (`outbox_rows`)
- Test: `tests/test_event_organisers.py` (create)

**Interfaces:**
- Consumes: `service.leads.new_token`, `token_hash`, `clean_email`, `mail_refusal`; `service.events.fields.KINDS`, `clean_text`; the onboardee or member session `/check-otp` leaves (`s.email`, `s.signed_in`).
- Produces, in `service.events.organisers`:
  - `LINK_TTL = timedelta(days=7)`; `PUBLIC_KINDS = ('assembly', 'fellowship_leader', 'ministry', 'other')`.
  - `request_host(tx, *, email: str, name: str, kind: str, city: Optional[str], country: Optional[str], about: Optional[str]) -> dict`: `{state, token}`, `state` one of `'created'` (new organiser, verified now, not approved), `'pending'` (already waiting, export 4.5) or `'approved'`. `token` is a fresh link token in every state, since the address has just been proved. A revoked organiser raises `EventError('revoked', 403)`.
  - `issue_link(tx, organiser_id: int) -> str`; `organiser_for(tx, token: Optional[str]) -> dict` (the organiser row plus `approved: bool`; raises `EventError('expired', 401)` for a missing, unknown, lapsed or revoked token, export 4.9).
  - `send_new_link(tx, email: str) -> None`: queues `event_manage` (Task 9) with a new token for a non-revoked organiser with this address; does nothing otherwise.
  - `create_organiser(tx, *, name: str, email: str, kind: str, admin_person_id: int) -> dict`: verified and approved now; the admin uses it for Ahavah's own organiser (Task 11).
- In `service.events.mail`, stubs that later tasks fill: `queue_manage_link(tx, organiser_id: int, token: str, *, note: Optional[str] = None) -> Optional[int]`, `queue_confirm(tx, rsvp_id: int, token: str) -> Optional[int]`, `queue_change(tx, event_id: int) -> int`, `queue_cancelled(tx, event_id: int) -> int`, `confirm_url(token: str) -> str` (`{WEB_BASE_URL}/rsvp/confirm/{token}`, real from now), `manage_url(token: str) -> str` (`{WEB_BASE_URL}/host/gatherings?t={token}`, real from now).
- Routes, all 404 while `events_live` is off:
  - `POST /host-requests` (`apost`, `expected_onboarding_status=None`, so the onboardee session from `/check-otp` qualifies; 404 while `events_hosting` is off too). Body `PostHostRequest {name, kind, city?, country?, about?}`; the address is the session's. 201 `{state, token}`.
  - `POST /organisers/link` (no auth). Body `PostOrganiserLink {email, website?, signup_stamp?}`. Limits `shared_recipient_limit` and `'10 per hour'` per IP. Always 202 `{}`; a `mail_refusal` refusal is silent.
  - `GET /organiser/me` (header `X-Organiser-Token`): `{name, kind, approved, email}`; Task 5 adds `groups`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_event_organisers.py` with `pytestmark = pytest.mark.usefixtures('events_schema', 'events_live', 'no_limits')`:

```python
def test_a_request_to_host_makes_a_waiting_organiser_and_lets_them_in(client, tool_visitor, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_HOSTING_ENABLED', '1')
    email, headers = tool_visitor()
    r = client.post('/host-requests', headers=headers, json=dict(
        name='Grace Fellowship', kind='fellowship_leader', city='Dallas', country='United States',
        about='We meet every Sabbath.'))
    assert r.status_code == 201 and r.get_json()['state'] == 'created'
    me = client.get('/organiser/me', headers={'X-Organiser-Token': r.get_json()['token']}).get_json()
    assert me == dict(name='Grace Fellowship', kind='fellowship_leader', approved=False, email=email)

def test_asking_again_says_the_request_is_waiting(client, tool_visitor, monkeypatch):
    # a second POST with the same session answers state 'pending' and a token that works

def test_hosting_is_closed_until_its_switch(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_EVENTS_HOSTING_ENABLED', raising=False)
    _, headers = tool_visitor()
    assert client.post('/host-requests', headers=headers, json=dict(name='X', kind='other')).status_code == 404

def test_the_kind_ahavah_cannot_be_asked_for(client, tool_visitor, monkeypatch):
    # kind 'ahavah' -> 400

def test_a_link_lapses_after_7_days(organiser):
    # expires_at set to NOW() - 1 second -> organiser_for raises EventError, reason 'expired', status 401

def test_a_revoked_organiser_is_locked_out(organiser):
    # revoked_at set -> 'expired'; request_host for the address raises 'revoked'

def test_asking_for_a_new_link_answers_the_same_whether_or_not_the_address_hosts(client, organiser):
    o = organiser()
    a = client.post('/organisers/link', json=dict(email=o['email']))
    b = client.post('/organisers/link', json=dict(email='nobody-here@ahavah-test.invalid'))
    assert (a.status_code, a.get_json()) == (b.status_code, b.get_json()) == (202, {})
```

`outbox_rows(campaign)` (conftest, added here) returns the `email_outbox` rows of one campaign. That a manage link was queued is tested in Task 9, once the email exists.

- [ ] **Step 2: Run it to verify it fails.** Run: the API test command with `tests/test_event_organisers.py`. Expected: failures (404 on every route, `No module named 'service.events.organisers'`).

- [ ] **Step 3: Implement** `organisers.py`, the mail stubs, the 3 routes and the 2 models to the interfaces above. `PostHostRequest.kind` is `Literal['assembly', 'fellowship_leader', 'ministry', 'other']`; `name` 1 to 80, `city` and `country` up to 80, `about` up to 1000, each through `fields.clean_text`. `PostOrganiserLink` carries `website` and `signup_stamp` as `PostRequestOtp` does, and the route calls `mail_refusal` before its transaction.

- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add service/events/organisers.py service/events/mail.py service/api/events_routes.py duotypes/__init__.py tests/conftest.py tests/test_event_organisers.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the request to host and the organiser's magic link" -m "Refs: TEC-1845"
```

### Task 5: Managing gatherings: create, edit, publish, cancel, the lists and the posts

**Files:**
- Create: `service/events/manage.py`
- Modify: `service/api/events_routes.py`, `duotypes/__init__.py` (`EventDraftBody`, `PostEventCancel`, `PostAttended`), `tests/conftest.py` (`published`, `confirmed_guest`)
- Test: `tests/test_event_manage.py` (create)

**Interfaces:**
- Consumes: `fields.clean_draft`, `slug_for`, `text_flag`, `when_words`; `organisers.organiser_for`; `service.spotlight.growthposts.queue_event_posts(tx, *, slug, starts_at, caption, payload, created_by, now)` and `cancel_event_posts(tx, slug)`; the mail stubs `queue_change`, `queue_cancelled`.
- Produces, in `service.events.manage` (each takes the organiser dict from `organiser_for`):
  - `create_event(tx, organiser, raw: dict) -> dict` (status `draft`; the slug is fixed at creation).
  - `update_event(tx, organiser, slug, raw: dict, now=None) -> dict` `{event, notified}`. On a published gathering a change to `starts_at`, `ends_at`, `tz`, `mode`, `city`, `country`, `venue` or `online_url` sets `changed_at`, `change_before` and `change_after` (each `{date, time, place}`: `when_words` and the city, "Online" or the venue as the guest saw it) and calls `queue_change` for confirmed going guests; when the start moved, `cancel_event_posts` then `queue_event_posts` for the new date. New text that `text_flag` catches sends a published gathering back to `pending` with the flag.
  - `publish(tx, organiser, slug, now=None) -> dict` `{status}`: `published` when the organiser is approved and `flag_reason` is None, with `published_at` and the posts queued (`created_by='events'`); otherwise `pending` with `flag_reason` `'new_organiser'`, `'rude'`, `'scam'` or `'cover_review'`. A gathering that has started raises `EventError('started', 409)`.
  - `cancel_event(tx, organiser, slug, note: Optional[str]) -> dict` `{notified}`: status `cancelled`, `cancelled_at`, the note cleaned to 500 characters; a flagged note is dropped and its flag kept in `flag_reason` for the admin; `cancel_event_posts`; `queue_cancelled`.
  - `organiser_view(tx, organiser, now=None) -> dict` `{organiser, groups: {drafts, waiting, published, cancelled, ended}}`, each item `{slug, title, starts_at, status, paused, going, confirmed}` (export 4.6).
  - `rsvp_list(tx, organiser, slug, now=None) -> dict` `{going: [{id, name, party_size, email?, attended}], waiting: [{id, name, party_size}], total_going, can_mark}`; `email` only when the guest ticked the box; `can_mark` once the gathering has started (export 4.23, 4.24).
  - `mark_attended(tx, organiser, slug, rsvp_id: int, attended: bool) -> None` (`EventError('not_started', 409)` before the start).
  - `post_caption(event: dict) -> str`: `'{title}. {date}, {place}. Hosted by {organiser}.'`, place the city or `Online` (NEW LINE). `post_payload(event: dict) -> dict`: `{slug, event_title, date, city_or_online, organiser_name, tags: [labels], feast_label, ahavah_attending}`, the slot names of the social set's card 4.1. Never the venue.
  - `organiser_preview(tx, organiser, slug) -> dict`: the public view of any of the organiser's gatherings, with `preview: True` (export 1.12).
- Routes, header `X-Organiser-Token`, all 404 while `events_live` is off: `GET /organiser/me` (now with `groups`), `POST /organiser/events` (201 `{slug}`), `PATCH /organiser/events/<slug>`, `POST /organiser/events/<slug>/publish`, `POST /organiser/events/<slug>/cancel`, `GET /organiser/events/<slug>`, `GET /organiser/events/<slug>/rsvps`, `POST /organiser/events/<slug>/rsvps/<int:rid>/attended`. Another organiser's slug answers 404.
- Fixtures: `published(**over) -> str` (an approved organiser's published gathering 30 days ahead, the slug); `confirmed_guest(slug, *, name='Hannah Okafor', email=None, party_size=1, share=False) -> dict` (a confirmed going row with a token, inserted directly).

- [ ] **Step 1: Write the failing test**

Create `tests/test_event_manage.py`; `draft(**over)` returns Task 3's `GOOD` moved 30 days ahead:

```python
def test_a_new_organisers_first_gathering_waits_for_approval(client, organiser):
    o = organiser(approved=False)
    slug = client.post('/organiser/events', headers=o['headers'], json=draft()).get_json()['slug']
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'pending'}
    assert _row(slug)['flag_reason'] == 'new_organiser'
    assert client.get(f'/events/{slug}').status_code == 404

def test_an_approved_organiser_publishes_and_the_two_posts_are_queued(client, organiser):
    o = organiser()
    slug = client.post('/organiser/events', headers=o['headers'], json=draft()).get_json()['slug']
    assert client.post(f'/organiser/events/{slug}/publish', headers=o['headers']).get_json() == {'status': 'published'}
    keys = _post_keys(slug)
    assert sorted(k.rsplit(':', 1)[1] for k in keys) == ['d10', 'd2']
    payload = _post_payload(keys[0])
    assert payload['event_title'] == 'Marriage preparation evening' and 'Elm Street' not in json.dumps(payload)

def test_flagged_text_waits_even_for_an_approved_organiser(client, organiser):
    # description = Task 3's scam sentence -> pending, flag 'scam', no posts queued

def test_moving_a_published_gathering_emails_guests_once_and_requeues_its_posts(client, organiser, confirmed_guest, monkeypatch):
    calls = []
    monkeypatch.setattr('service.events.mail.queue_change', lambda tx, eid: calls.append(eid) or 1)
    o, slug = _published(client, organiser)
    confirmed_guest(slug)
    r = client.patch(f'/organiser/events/{slug}', headers=o['headers'],
                     json=dict(starts_at=_iso(days=31, hour=1), ends_at=_iso(days=31, hour=4)))
    assert r.get_json()['notified'] == 1 and len(calls) == 1
    row = _row(slug)
    assert row['changed_at'] is not None and row['change_before']['date'] != row['change_after']['date']
    assert _post_statuses(slug) == {'cancelled': 2, 'awaiting_render': 2}

def test_editing_only_the_description_tells_nobody(client, organiser, confirmed_guest, monkeypatch):
    # notified 0, changed_at None

def test_cancelling_tells_confirmed_guests_and_cancels_the_posts(client, organiser, confirmed_guest, monkeypatch):
    # status cancelled, note kept, queue_cancelled called once, both posts cancelled

def test_a_flagged_cancel_note_is_dropped_but_the_cancellation_goes(client, organiser, monkeypatch):
    # cancel_note None, flag_reason 'scam', status cancelled

def test_the_lists_group_by_status(client, organiser):
    # one draft, one pending, one published, one cancelled, one ended -> each group holds its one slug

def test_the_rsvp_list_shows_an_email_only_where_the_guest_shared_it(client, organiser, confirmed_guest):
    o, slug = _published(client, organiser)
    confirmed_guest(slug, name='Hannah Okafor', party_size=2, share=True)
    confirmed_guest(slug, name='Lydia Cruz', share=False)
    rows = {g['name']: g for g in client.get(f'/organiser/events/{slug}/rsvps', headers=o['headers']).get_json()['going']}
    assert 'email' in rows['Hannah Okafor'] and 'email' not in rows['Lydia Cruz']

def test_attendance_is_marked_only_once_it_has_started(client, organiser, confirmed_guest):
    # before the start 409 not_started; with starts_at moved into the past, 204 and attended True

def test_another_organisers_gathering_is_not_found(client, organiser):
    # organiser B's token on organiser A's slug -> 404 for GET, PATCH, publish, cancel and rsvps
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures, `No module named 'service.events.manage'`.

- [ ] **Step 3: Implement** `manage.py`, the routes, the models and the fixtures to the interfaces above. Lock the event row (`SELECT ... FOR UPDATE`) in `update_event`, `publish` and `cancel_event`. `EventDraftBody` makes every field optional; `PATCH` passes `partial=True`.

- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add service/events/manage.py service/api/events_routes.py duotypes/__init__.py tests/conftest.py tests/test_event_manage.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): organisers create, change, publish and cancel gatherings" -m "Refs: TEC-1845"
```

### Task 6: The cover image

**Files:**
- Modify: `service/events/manage.py` (`set_cover`, `remove_cover`, `cover_url`), `service/api/events_routes.py`, `duotypes/__init__.py` (`PostEventCover`), `tests/conftest.py` (`fake_bucket`)
- Test: `tests/test_event_covers.py` (create)

**Interfaces:**
- Consumes: `service.photo_moderation.moderate_image_bytes(bytes) -> ModerationVerdict` (`status` approved, rejected or manual_review); `service.spotlight.storage._bucket()`; `service.config.USER_IMAGES_BASE_URL`.
- Produces: `COVER_SIZE = (1200, 630)`, `COVER_MAX_BYTES = 10 * 1024 * 1024`; `set_cover(tx, organiser, slug, data: bytes, content_type: str) -> dict` `{cover_url}`: refuses anything but a decodable JPEG or PNG under 10 MB and a rejected verdict (`EventError('bad_image', 400)`, export 4.14); re-encodes to a 1200 by 630 JPEG, centre-cropped, EXIF dropped; sets `flag_reason = 'cover_review'` on manual review; uploads public-read under `event-covers/{uuid4}.jpg` before the transaction that stores the key, and deletes the old key best effort. `remove_cover(tx, organiser, slug) -> None`. `cover_url(key: Optional[str]) -> Optional[str]`. Routes `POST /organiser/events/<slug>/cover` (body `{image: base64, content_type}`) and `DELETE /organiser/events/<slug>/cover`. `fake_bucket` replaces `service.spotlight.storage._bucket` with an object that records `put_object` and `delete_objects`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_cover_is_cropped_to_1200_by_630_and_stored_public(client, organiser, fake_bucket, monkeypatch):
    monkeypatch.setattr('service.photo_moderation.moderate_image_bytes', lambda b: Verdict('approved'))
    o, slug = _draft(client, organiser)
    r = client.post(f'/organiser/events/{slug}/cover', headers=o['headers'],
                    json=dict(image=_png_b64(3000, 2000), content_type='image/png'))
    assert r.status_code == 200
    assert r.get_json()['cover_url'].startswith('https://user-images.ahavah.app/event-covers/')
    key, body, acl = fake_bucket.puts[-1]
    assert acl == 'public-read' and Image.open(io.BytesIO(body)).size == (1200, 630)

def test_a_file_that_is_not_an_image_is_refused(client, organiser, fake_bucket): ...        # 400 bad_image
def test_a_rejected_cover_is_refused_and_nothing_is_stored(client, organiser, fake_bucket, monkeypatch): ...
def test_a_borderline_cover_sends_the_gathering_for_approval(client, organiser, fake_bucket, monkeypatch): ...
def test_replacing_a_cover_deletes_the_old_one(client, organiser, fake_bucket, monkeypatch): ...
```

- [ ] **Step 2: Run it to verify it fails.** Expected: 404s.
- [ ] **Step 3: Implement** with Pillow (`ImageOps.fit(img.convert('RGB'), COVER_SIZE)`, JPEG quality 85).
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/manage.py service/api/events_routes.py duotypes/__init__.py tests/conftest.py tests/test_event_covers.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): a gathering's cover, cropped, checked and stored" -m "Refs: TEC-1845"
```

### Task 7: The public read: by region, one gathering, views and the country list

**Files:**
- Create: `service/events/public.py`
- Modify: `service/api/events_routes.py`
- Test: `tests/test_events_public.py` (create)

**Interfaces:**
- Consumes: `fields.countries`, `fields.FEASTS`, `manage.cover_url`.
- Produces, in `service.events.public`:
  - A card: `{slug, title, starts_at, ends_at, tz, tz_label, mode, city, country, region, organiser: {name, kind}, tags, feast, feast_label, cover_url, ahavah_attending, going?}`, `going` only when `show_going`.
  - `list_events(tx, *, region: Optional[str], limit: int = 20, now=None) -> list[dict]`: published, not paused, not ended; `region = %(r)s OR region = 'online'` when a region is given (decision 6), every region when none; by `starts_at`; `limit` 1 to 50.
  - `event_view(tx, slug, now=None) -> dict`: the card plus `description`, `capacity`, `places_left` (when a capacity is set: capacity minus confirmed going parties), `state` (`'open' | 'full' | 'cancelled' | 'ended'`), `changed` (`{before, after}` while `changed_at` is within 14 days and the gathering has not started), `cancel_note` and `venue` only when `venue_visibility = 'public'`. `online_url` is never in it. A draft, pending, paused or unknown slug raises `EventError('not_found', 404)`; a cancelled gathering is shown (export 1.9).
  - `count_view(tx, slug, day: date) -> None`.
- Routes, all 404 while `events_live` is off:
  - `GET /events?region=&limit=` (404 while `events_list` is off; 400 `bad_region`), `Cache-Control: public, max-age=60`.
  - `GET /events/<slug>`, `Cache-Control: no-store`.
  - `POST /events/<slug>/view` (204; `'60 per hour'` per IP; a user agent containing `bot`, `crawler`, `spider` or `preview` is not counted).
  - `GET /events/countries` `{countries: [{name, region}]}`, `Cache-Control: public, max-age=86400`.

- [ ] **Step 1: Write the failing test** `tests/test_events_public.py`:

```python
def test_a_region_shows_its_own_and_every_online_gathering(client, published, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    dallas = published(country='United States', city='Dallas')
    kampala = published(country='Uganda', city='Kampala')
    talk = published(mode='online', online_url='https://meet.example.com/a', city=None, country=None)
    slugs = [e['slug'] for e in client.get('/events?region=north-america').get_json()['events']]
    assert dallas in slugs and talk in slugs and kampala not in slugs

def test_the_public_never_sees_the_venue_or_the_call_link_unless_made_public(client, published, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_LIST_ENABLED', '1')
    hidden = published(venue='14 Elm Street', venue_visibility='confirmed')
    shown = published(venue='Grace Fellowship hall, 14 Elm Street, Dallas', venue_visibility='public')
    talk = published(mode='online', online_url='https://meet.example.com/secret', city=None, country=None)
    assert 'venue' not in client.get(f'/events/{hidden}').get_json()
    assert client.get(f'/events/{shown}').get_json()['venue'] == 'Grace Fellowship hall, 14 Elm Street, Dallas'
    assert 'meet.example.com' not in client.get(f'/events/{talk}').get_data(as_text=True)
    assert 'Elm Street' not in client.get('/events').get_data(as_text=True)

def test_going_shows_only_when_the_organiser_shows_it(client, published, confirmed_guest): ...
def test_full_cancelled_and_ended_say_so(client, published, confirmed_guest): ...
def test_a_draft_pending_or_paused_gathering_is_not_found(client, organiser, published): ...
def test_a_change_shows_for_14_days_and_not_after_the_start(client, published): ...
def test_views_are_counted_per_day_and_bots_are_not(client, published): ...
def test_the_list_is_closed_until_its_switch_but_a_gathering_page_is_not(client, published, monkeypatch): ...

def test_everything_is_dark_until_live(client, published, monkeypatch):
    slug = published()
    monkeypatch.delenv('AHAVAH_EVENTS_LIVE_ENABLED')
    for path in ('/events', f'/events/{slug}', '/events/countries'):
        assert client.get(path).status_code == 404
    assert client.get('/events/status').status_code == 200
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/public.py service/api/events_routes.py tests/test_events_public.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): gatherings by region and one gathering's public page" -m "Refs: TEC-1845"
```

### Task 8: RSVP without an account, confirming, cancelling and the calendar file

**Files:**
- Create: `service/events/rsvp.py`, `service/events/ics.py`
- Modify: `service/api/events_routes.py`, `duotypes/__init__.py` (`PostEventRsvp`)
- Test: `tests/test_event_rsvp.py`, `tests/test_event_ics.py` (create)

**Interfaces:**
- Consumes: `service.leads.record_lead`, `confirm_lead`, `clean_email`, `new_token`, `token_hash`, `mail_refusal`; `service.leads.sources.event_source`; `public.event_view`; the mail stub `queue_confirm`.
- Produces, in `service.events.rsvp`:
  - `PARTY_MAX = 10`; `CONFIRM_WINDOW = timedelta(days=7)`; `NEWS_WORDING = 'events-rsvp-news-v1'`, the key of the wording "Tell me about Ahavah events and members near me" (a new wording gets a new key).
  - `rsvp(tx, slug, *, name: str, email: Optional[str], party_size: int, share_email: bool, news: bool, member: Optional[SessionInfo], now=None) -> dict`: `{state: 'check_email', email}` for a visitor; `{state: 'confirmed', token}` for a signed-in member (item 19). Refusals, as `EventError`: `not_found` 404; `closed` 409 (cancelled or ended); `full` 409 with `places_left: 0`; `too_many` 409 with `places_left: n` (export 2.5); `bad_email`, `bad_name`, `bad_party` 400. A visitor's RSVP records the lead (`event:{slug}`; `marketing_consent=news` with `NEWS_WORDING` when ticked), sets `new_address` when the address had no account and no lead of any source, sets `confirm_by` to the earlier of 7 days and the start and calls `queue_confirm`. The same address again replaces the party size, the boxes and the token on its one row; a cancelled row becomes going and unconfirmed again. While a row is unconfirmed, RSVPing again is the export's "Send it again" (2.9): `resends` goes up and the confirm email is queued again under `campaign_id` `{rsvp_id}:{resends}`, at most 3 times (`EventError('too_many_tries', 429)`, export 2.7). The visitor holds no token before confirming, so there is no separate resend route.
  - `confirm(tx, token: str, now=None) -> dict`: locks the event row; `EventError('expired', 410)` past `confirm_by` (export 2.14), `('full_now', 409)` (2.15), `('cancelled_now', 409)` (2.16); else sets `confirmed_at` once, calls `confirm_lead(tx, lead_id, 'link')` and returns `rsvp_view`. Confirming again returns the same view (2.10 note).
  - `rsvp_view(tx, token) -> dict`: `{event, rsvp: {name, party_size, status, confirmed}}`, with `venue` and `online_url` in `event` once confirmed. An unknown token, or one whose gathering has ended a day ago, raises `not_found` 404.
  - `cancel(tx, token) -> dict` (status `cancelled`, `cancelled_at`; the place is free).
  - `service.events.ics.calendar_file(event: dict, *, location: Optional[str], url: str, now: datetime) -> str`: RFC 5545 with CRLF line ends, `UID:{slug}@ahavah.app`, `DTSTAMP`, `DTSTART` and `DTEND` in UTC, `SUMMARY` with commas, semicolons, backslashes and newlines escaped, `LOCATION` only for a confirmed guest, `URL`, `STATUS:CANCELLED` when cancelled, lines folded at 75 octets.
- Routes, all 404 while `events_live` is off, each `Cache-Control: no-store`:
  - `POST /events/<slug>/rsvp` (auth optional, `expected_onboarding_status=None`; `'10 per hour; 30 per day'` per IP and `shared_recipient_limit`). Body `PostEventRsvp {name, email?, party_size, share_email = False, news = False, website?, signup_stamp?}`. A visitor's `mail_refusal` refusal answers `{state: 'check_email', email}` and writes nothing. 201.
  - `GET /rsvp/me` (a member session; `{name, email}`, the member's first name and address, for the form's 2.3), `GET /rsvp/confirm/<token>` (the spec's route; the web page calls it from a script, and no email links to it), `GET /rsvp/<token>`, `POST /rsvp/<token>/cancel`, `GET /rsvp/<token>/calendar.ics` (`text/calendar; charset=utf-8`, `Content-Disposition: attachment; filename="gathering.ics"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_event_rsvp.py`:

```python
def test_a_visitor_rsvps_and_is_asked_to_check_their_email(client, published):
    slug = published()
    r = client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah Okafor', email='hannah@ahavah-test.invalid', party_size=2))
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': 'hannah@ahavah-test.invalid'}
    row = _rsvp(slug, 'hannah@ahavah-test.invalid')
    assert row['confirmed_at'] is None and row['source'] == f'event:{slug}' and row['new_address'] is True
    lead = _lead(row['lead_id'])
    assert lead['source'] == f'event:{slug}' and lead['marketing_consent'] is False and lead['confirmed_at'] is None

def test_the_box_is_the_only_marketing_consent(client, published):
    slug = published()
    client.post(f'/events/{slug}/rsvp', json=dict(name='A', email='a@ahavah-test.invalid', party_size=1, news=True))
    lead = _lead(_rsvp(slug, 'a@ahavah-test.invalid')['lead_id'])
    assert lead['marketing_consent'] is True and lead['consent_wording'] == 'events-rsvp-news-v1'

def test_confirming_holds_the_place_and_confirms_the_lead(client, published): ...
def test_the_venue_and_link_appear_only_once_confirmed(client, published): ...

def test_two_guests_confirming_the_last_place_get_one_place(client, published):
    slug = published(capacity=2)
    t1 = _rsvp_token(slug, 'a@ahavah-test.invalid', 2)
    t2 = _rsvp_token(slug, 'b@ahavah-test.invalid', 2)
    with ThreadPoolExecutor(2) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(_confirm, t1), ex.submit(_confirm, t2)])
    assert codes == [200, 409]

def test_more_guests_than_places_left_says_how_many_are_left(client, published, confirmed_guest):
    # capacity 5, a confirmed party of 2, an RSVP for 5 -> 409, error 'too_many', places_left 3

def test_an_expired_confirm_link_says_so(client, published): ...
def test_a_gathering_cancelled_before_the_guest_confirms(client, published, organiser): ...
def test_cancelling_frees_the_place(client, published): ...
def test_rsvping_again_keeps_one_row(client, published): ...
def test_a_signed_in_member_is_confirmed_at_once_and_is_not_a_lead(client, published, make_person, sign_in): ...

def test_a_refused_address_is_answered_as_a_send_and_nothing_is_written(client, published, monkeypatch):
    monkeypatch.setattr('service.leads.mail_refusal', lambda **k: 'honeypot')
    # the same 201 body; no event_rsvp row, no lead, no outbox row

def test_the_email_link_is_the_web_page_not_the_api():
    from service.config import WEB_BASE_URL
    from service.events.mail import confirm_url
    assert confirm_url('tok') == f'{WEB_BASE_URL}/rsvp/confirm/tok'

def test_sending_it_again_stops_after_3(client, published): ...   # the 4th RSVP for one unconfirmed address -> 429 too_many_tries
def test_party_size_and_name_are_checked(client, published): ...   # 0, 11 and '' -> 400
```

`tests/test_event_ics.py`: `test_the_file_is_valid_rfc_5545` (CRLF, `BEGIN:VCALENDAR`, `VERSION:2.0`, `PRODID`, one `VEVENT`, UTC times ending `Z`), `test_text_is_escaped_and_folded` (a 120 character title with a comma: `\,` and no line over 75 octets), `test_a_cancelled_gathering_says_cancelled`, `test_the_location_is_left_out_until_confirmed` (through `GET /rsvp/<token>/calendar.ics` before and after confirming).

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above. `rsvp` checks places against confirmed parties without a lock; the place is taken in `confirm`, under the event row's lock.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/rsvp.py service/events/ics.py service/api/events_routes.py duotypes/__init__.py tests/test_event_rsvp.py tests/test_event_ics.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): RSVP without an account, confirming by link and the calendar file" -m "Refs: TEC-1845"
```

### Task 9: The emails, through the outbox, with an organiser as a recipient

**Files:**
- Modify: `service/events/mail.py` (replace the stubs), `service/campaigns/outbox.py` (`enqueue_for_organiser`, `_refusal`), `service/events/organisers.py` (`send_new_link` now queues), `tests/email_samples.py`
- Test: `tests/test_event_mail.py` (create)

**Interfaces:**
- Consumes: `emails.base.render`, `title_image`, `button`, `chip`, `SANS`, `INK`, `MUTED`, `is_suppressed_send`; `service.campaigns.held.queue`, `held.para`, `held.footer`, `held.list_unsubscribe`; `outbox.enqueue_for_lead`; `service.unsubscribe.make_url`; `service.config.WEB_BASE_URL`, `API_BASE_URL`, `EMAIL_DOMAIN`; `fields.when_words`; `rsvp.rsvp_view`.
- Produces:
  - In `service.campaigns.outbox`: `enqueue_for_organiser(tx, *, campaign: str, campaign_id: str, organiser_id: int, email: str, subject: str, html: str, from_addr: Optional[str]) -> Optional[int]` (exempt, deduped on the 0071 partial index). `_refusal` reads `service.events.CAMPAIGN_SWITCHES` for any recipient, as it reads Together's, answering `'switched_off'` when `switch_on` is off; an organiser row is refused only when suppressed.
  - In `service.events.mail`: the campaign names `event_confirm`, `event_reminder`, `event_change`, `event_cancelled`, `event_digest`, `event_manage`, `event_organiser_note`; `FROM_ADDR = f'support@{EMAIL_DOMAIN}'`; `SAFETY = 'Meet in a public place, tell a friend where you are going and never send money to someone you met online.'`; `TITLES: dict[str, tuple[str, str, int]]` (stem, alt, natural CSS width, the width filled in from the handoff's table):

    | Key | Stem | Alt | Source |
    |---|---|---|---|
    | confirm | `title-event-confirm` | Tap to confirm your place. | 3.1 heading |
    | reminder | `title-event-reminder` | See you tomorrow. | 3.2 heading |
    | change | `title-event-change` | This gathering changed. | page 1.10 |
    | cancelled | `title-event-cancelled` | This gathering was cancelled. | page 1.9 |
    | digest | `title-event-digest` | New RSVPs. | NEW LINE |
    | manage | `title-event-manage` | Manage your gatherings. | 3.8 heading |

  - Builders, each `-> tuple[str, str]` (subject, html), names escaped with `html.escape` everywhere: `confirm_email(view, token)`, `reminder_email(view, token)`, `change_email(view, token, before, after)`, `cancelled_email(view, token)`, `digest_email(event, new_rsvps, total_going, manage_token)`, `manage_email(token, note: Optional[str] = None)`.
  - The design's headings that carry a title or a number become a body line under the title image, at body size: `change_line(title, before, after) -> str` (`'{title} now starts at {time}'` when only the time moved, export 3.4; `'{title} is now on {date}'`, `'{title} is now at {place}'`, `'{title} is now online'` otherwise, NEW LINES); `'{title} was cancelled'` (3.5); `'{n} new RSVPs for {title}'` (3.6; `'1 new RSVP for {title}'` NEW LINE).
  - Subjects (NEW LINES): `Confirm your place at {title}`, `Tomorrow: {title}`, `A change to {title}`, `{title} was cancelled`, `{n} new RSVPs for {title}`, `Manage your gatherings on Ahavah`, `Your request to host on Ahavah is approved`, `{title} is live on Ahavah`.
  - Each email's other lines, verbatim from `10-events-emails.md`: overlines as chips (`Tomorrow`, `A change`, `Cancelled`, `Today`), dropped where they repeat the title (confirm, manage), as the checklist invite does; the facts panel (title, date and time, the city or "Online" before confirming and the venue or link after, "Hosted by {organiser}"); buttons `Confirm my place`, `Add to calendar` (`{API_BASE_URL}/rsvp/{token}/calendar.ics`), `Cancel my place` (`{WEB_BASE_URL}/rsvp/{token}`), `See other gatherings` (`{WEB_BASE_URL}/events`), `Manage your gathering` and `Manage your gatherings` (`manage_url`); lines `We share the address once you confirm.` (online: `We share the link once you confirm.`, NEW LINE), `Everything else stays the same. Your place is still saved.`, `{n} going in total.`, `Use this button to create, change and cancel your gatherings and see who is coming. No password needed.`, `This link works for 7 days. You can ask for a new one at any time.`; footers `If you did not RSVP, ignore this email and nothing will happen.`, `You are getting this because you RSVPed to a gathering on Ahavah.`, `We send this once a day, only on days with new RSVPs.`, `Only forward this email to people you trust to run your gatherings.`. The safety note goes in the reminder and the change email for in-person gatherings, never in the confirm email (3.1 note). The organiser notes are `manage_email` with a lead line: `Ahavah has approved your request to host.` or `{title} is live.` (NEW LINES).
  - Queueing, each behind a savepoint so a mail failure never undoes the caller: `queue_confirm(tx, rsvp_id, token) -> Optional[int]`, `queue_change(tx, event_id) -> int`, `queue_cancelled(tx, event_id) -> int`, `queue_reminder(tx, rsvp_id, token) -> Optional[int]`, `queue_digest(tx, event_id, day: date) -> Optional[int]`, `queue_manage_link(tx, organiser_id, token, *, note=None) -> Optional[int]`. A guest who is a member is queued with `held.queue` (scope `notifications`); anyone else through `enqueue_for_lead` with `marketing=False` and no List-Unsubscribe; an organiser through `enqueue_for_organiser`. Change, cancelled and reminder mail needs a token per guest: the queue function issues a new token for each confirmed guest (`rsvp.reissue_token(tx, rsvp_id) -> str`, added here, which replaces the hash), so every link in a later email works and an earlier one is retired. `campaign_id`s: confirm `{rsvp_id}:{resends}`, change `{rsvp_id}:{changed_at:%Y%m%d%H%M%S}`, cancelled `{rsvp_id}`, reminder `{rsvp_id}:{starts_at:%Y%m%d%H%M}`, digest `{event_id}:{day}`, manage `{organiser_id}:{token_hash[:12]}`.
  - Proof previews for Task 13, each `(to: str) -> tuple[str, str]` with sample data only (Grace Fellowship, Marriage preparation evening, Hannah Okafor): `preview_confirm`, `preview_confirm_online`, `preview_reminder`, `preview_reminder_online`, `preview_change`, `preview_cancelled`, `preview_digest`, `preview_manage`, `preview_approved`, `preview_live`.

- [ ] **Step 1: Write the failing test** `tests/test_event_mail.py`:

```python
def test_a_visitors_rsvp_queues_the_confirm_email_to_their_lead(client, published, outbox_rows):
    slug = published()
    client.post(f'/events/{slug}/rsvp', json=dict(name='Hannah Okafor', email='hannah@ahavah-test.invalid', party_size=2))
    [row] = outbox_rows('event_confirm')
    assert row['lead_id'] is not None and row['person_id'] is None and row['exempt'] is True
    html = row['payload']['html']
    assert f'{WEB_BASE_URL}/rsvp/confirm/' in html and '/rsvp/confirm/' not in html.replace(WEB_BASE_URL, '')
    assert 'Elm Street' not in html and 'Confirm my place' in html

def test_the_reminder_carries_the_venue_and_the_safety_note(published, confirmed_guest): ...
def test_an_online_reminder_carries_the_link_and_no_safety_note(published, confirmed_guest): ...
def test_a_change_says_before_and_now_and_each_guest_gets_a_fresh_link(published, confirmed_guest): ...
def test_the_cancelled_email_quotes_the_organisers_note(published, confirmed_guest): ...
def test_the_digest_lists_names_and_party_sizes_never_emails(published, confirmed_guest): ...
def test_the_manage_link_goes_to_the_organiser_through_the_outbox(client, organiser, outbox_rows):
    o = organiser()
    client.post('/organisers/link', json=dict(email=o['email']))
    [row] = outbox_rows('event_manage')
    assert row['organiser_id'] == o['id'] and '/host/gatherings?t=' in row['payload']['html']

def test_a_switched_off_email_is_skipped_at_send_time(published, confirmed_guest, outbox_drain, monkeypatch):
    # queue a reminder, delenv AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED, drain -> state 'skipped', last_error 'switched_off'

def test_names_and_titles_are_escaped_in_every_email():
    from service.events import mail
    evil = '<script>x</script>'
    for subject, html in [mail.confirm_email(_view(title=evil, organiser=evil), 'tok'),
                          mail.digest_email(_event(title=evil), [dict(name=evil, party_size=1)], 1, 'tok')]:
        assert '<script>' not in html

def test_every_email_uses_title_images_and_no_typed_headline():
    from tests.email_samples import SAMPLES
    names = {s['name'] for s in SAMPLES}
    assert {'event_confirm', 'event_confirm_online', 'event_reminder', 'event_reminder_online', 'event_change',
            'event_cancelled', 'event_digest', 'event_manage', 'event_approved', 'event_live'} <= names
```

Add the 10 rows to `tests/email_samples.py` (`add('event_confirm', 'service/events/mail.py confirm_email', 'lead', ...)` and so on, from the previews), so `tests/test_email_renders_on_a_phone.py` checks every one at 320 px and for typed headlines.

- [ ] **Step 2: Run them to verify they fail.** Run: `tests/test_event_mail.py` and `tests/test_email_renders_on_a_phone.py`. Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above. Every switch read lives in `_refusal` and in the queue functions (`switch_on(CAMPAIGN_SWITCHES[campaign])` before queueing), so an email that is off is neither queued nor sent.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_tool_mail.py`, `tests/test_email_outbox.py` and `tests/test_email_outbox_cron.py` to prove the outbox change broke nothing. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/mail.py service/events/rsvp.py service/events/organisers.py service/campaigns/outbox.py tests/email_samples.py tests/test_event_mail.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the guest and organiser emails, through the outbox" -m "Refs: TEC-1845"
```

### Task 10: Reminders and the organiser digest, held out of the owner's rest days

**Files:**
- Create: `service/events/jobs.py`
- Modify: `service/cron/returnmail/__init__.py` (`JOBS`)
- Test: `tests/test_event_jobs.py` (create)

**Interfaces:**
- Consumes: `mail.queue_reminder`, `mail.queue_digest`; `service.spotlight.restdays.is_rest_period(at) -> bool`; the conftest autouse `_calendar_without_rest_days` (a test that needs a rest day sets `REST_DAYS` itself).
- Produces, in `service.events.jobs`:
  - `REMINDER_HOURS = (8, 21)`: a reminder is due on the gathering's local day before its start, from 08:00 to 21:00 local time, at the first hourly tick that is not inside a rest period. A gathering whose day before has no such hour gets no reminder (the calendar file is the guest's reminder). `queue_reminders(tx, now) -> int`.
  - `DIGEST_HOUR_UTC = 12`: `queue_digests(tx, now) -> int`: at the first tick at or after 12:00 UTC that is not inside a rest period, one digest per published gathering not ended more than a day ago, holding every confirmed going RSVP with `digested_at` NULL; those rows get `digested_at` in the same transaction. A day inside a rest period is skipped, and its RSVPs wait for the next digest.
  - `JOBS` gains `('event_reminder', jobs.queue_reminders)` and `('event_digest', jobs.queue_digests)`.

- [ ] **Step 1: Write the failing test** `tests/test_event_jobs.py`:

```python
def test_the_reminder_goes_on_the_local_day_before(published, confirmed_guest, outbox_rows, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED', '1')
    slug = published(starts_at='2026-11-08T00:00:00+00:00', ends_at='2026-11-08T03:00:00+00:00', tz='America/Chicago')
    confirmed_guest(slug)
    with api_tx() as tx:
        assert jobs.queue_reminders(tx, datetime(2026, 11, 6, 13, tzinfo=timezone.utc)) == 0   # Friday 7am Dallas
        assert jobs.queue_reminders(tx, datetime(2026, 11, 6, 14, tzinfo=timezone.utc)) == 1   # Friday 8am Dallas
        assert jobs.queue_reminders(tx, datetime(2026, 11, 6, 15, tzinfo=timezone.utc)) == 0   # already queued

def test_a_rest_period_holds_the_reminder_until_it_ends(published, confirmed_guest, monkeypatch): ...
def test_no_reminder_when_the_whole_day_before_is_a_rest_day(published, confirmed_guest, monkeypatch): ...
def test_a_moved_gathering_gets_a_new_reminder(published, confirmed_guest, monkeypatch): ...
def test_an_unconfirmed_or_cancelled_guest_gets_none(published, confirmed_guest, monkeypatch): ...
def test_the_digest_goes_once_a_day_and_only_with_new_rsvps(published, confirmed_guest, outbox_rows, monkeypatch): ...
def test_the_digest_skips_a_rest_day_and_carries_its_rsvps_forward(published, confirmed_guest, monkeypatch): ...
def test_both_jobs_are_in_the_return_mail_cron():
    from service.cron.returnmail import JOBS
    assert {'event_reminder', 'event_digest'} <= {n for n, _ in JOBS}
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/jobs.py service/cron/returnmail/__init__.py tests/test_event_jobs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the reminder the day before and the organiser's daily digest" -m "Refs: TEC-1845"
```

### Task 11: Admin: approvals, pausing, the badge, figures and invite requests, with `POST /invite-ahavah`

**Files:**
- Create: `service/events/admin.py`, `service/events/invites.py`, `service/api/admin/events_routes.py`
- Modify: `service/api/events_routes.py` (`POST /invite-ahavah`), `service/api/__init__.py` (register the admin routes), `tests/conftest.py` (`admin_headers`), `duotypes/__init__.py` (`PostInviteAhavah`, `PostAdminOrganiser`, `PostAdminApproveOrganiser`, `PatchInviteRequest`, `PostAhavahAttending`)
- Test: `tests/test_admin_events.py` (create)

**Interfaces:**
- Consumes: `service.admin.require_admin`, `record_audit`; `organisers.create_organiser`, `issue_link`; `manage.publish` internals (`_publish_now(tx, event_row, now)` factored out in this task so the admin's approval runs the same path); `growthposts.cancel_event_posts`; `mail.queue_manage_link`.
- Produces, in `service.events.admin` (all counts, never a guest's name or email):
  - `overview(tx, now=None) -> dict`: `{waiting: {organisers: [{id, name, kind, email, city, country, about, created_at}], events: [{slug, title, organiser, starts_at, flag_reason, created_at}]}, requests: [{id, gathering, dates, place, numbers, contact_name, contact_email, status, notes, created_at}], events: [{slug, title, starts_at, status, paused, ahavah_attending, views, rsvps, confirmed, attended, signups, new_addresses, member_rsvps, women_members}], organisers: [{id, name, kind, approved_at, events}], waiting_count}`. `rsvps` counts every RSVP row, `confirmed` the confirmed going ones, `signups` the members whose `lead_source` is `event:{slug}`, `new_addresses` the RSVPs with `new_address`, `women_members` the confirmed RSVPs whose `person.gender` is `Woman` and `member_rsvps` those with any `person_id` (decision 2).
  - `event_weeks(tx, slug) -> list[dict]`: per ISO week `{week, views, rsvps, confirmed, signups}` (admin 3.4).
  - `approve_organiser(tx, admin, organiser_id, kind: Optional[str] = None) -> None` (kind may become `ahavah`; queues `manage_email` with the approved note and a new link; publishes nothing by itself). `decline_organiser` and `revoke_organiser` set `revoked_at` and pause every published gathering of theirs (item 16). `create_organiser` (route) for Ahavah's own organiser, queues the manage link.
  - `approve_event(tx, admin, slug)` (published through `_publish_now`, `flag_reason` cleared, the live note queued), `decline_event(tx, admin, slug)` (back to `draft`, `flag_reason = 'declined'`), `pause_event`, `resume_event` (posts cancelled on pause and requeued on resume), `set_attending(tx, admin, slug, on: bool)` (Ahavah-kind organisers' gatherings start with it on).
  - `set_request(tx, admin, request_id, *, status: Optional[str], notes: Optional[str]) -> dict`.
  - In `service.events.invites`: `record_request(tx, body: dict) -> int`.
- Routes: `GET /admin/events`, `GET /admin/events/<slug>/weeks`, `POST /admin/events/organisers`, `POST /admin/events/organisers/<int:oid>/approve`, `.../decline`, `.../revoke`, `POST /admin/events/<slug>/approve`, `.../decline`, `.../pause`, `.../resume`, `.../attending`, `PATCH /admin/events/requests/<int:rid>`. Every change writes `record_audit` (`events.organiser.approve` and so on) in its own transaction. Admin routes work whichever way the switches are set, so the owner can prepare before launch.
- Public: `POST /invite-ahavah` (404 while `events_live` or `events_invite` is off; `'5 per hour'` per IP; honeypot answered 201 and nothing stored). Body `PostInviteAhavah {gathering, dates, place, numbers?, contact_name, contact_email, website?, signup_stamp?}`. 201 `{}`. No email is sent; the request waits in the admin.

- [ ] **Step 1: Write the failing test** `tests/test_admin_events.py`, with an `admin_headers` fixture added to `tests/conftest.py` here, built as `tests/test_admin_tool_counts.py`'s `_headers` builds one (a person with roles `['admin']`):

```python
def test_the_overview_counts_without_names(client, admin_headers, published, confirmed_guest):
    slug = published()
    confirmed_guest(slug, name='Hannah Okafor', email='hannah@ahavah-test.invalid')
    body = client.get('/admin/events', headers=admin_headers).get_data(as_text=True)
    assert 'Hannah' not in body and 'hannah@' not in body
    row = next(e for e in client.get('/admin/events', headers=admin_headers).get_json()['events'] if e['slug'] == slug)
    assert (row['rsvps'], row['confirmed']) == (1, 1)

def test_approving_an_organiser_lets_their_next_gathering_publish(client, admin_headers, organiser): ...
def test_approving_a_pending_gathering_publishes_it_and_queues_its_posts(client, admin_headers, organiser): ...
def test_pausing_hides_the_page_and_cancels_the_posts(client, admin_headers, published): ...
def test_revoking_an_organiser_pauses_their_gatherings_and_ends_their_links(client, admin_headers, organiser): ...
def test_ahavahs_own_organiser_is_created_approved_and_gets_a_link(client, admin_headers, outbox_rows): ...
def test_the_badge_is_set_by_the_admin(client, admin_headers, published): ...
def test_women_are_counted_among_member_rsvps_only(client, admin_headers, published, make_person): ...
def test_a_leader_asks_ahavah_to_come_and_it_waits_in_the_admin(client, admin_headers, monkeypatch):
    monkeypatch.setenv('AHAVAH_EVENTS_INVITE_ENABLED', '1')
    r = client.post('/invite-ahavah', json=dict(gathering='Sukkot at Lake Lanier', dates='26 to 30 September 2027',
                    place='Georgia, United States', numbers=120, contact_name='Daniel', contact_email='daniel@ahavah-test.invalid'))
    assert r.status_code == 201
    req = client.get('/admin/events', headers=admin_headers).get_json()['requests'][0]
    assert req['status'] == 'new' and req['gathering'] == 'Sukkot at Lake Lanier'
    assert client.patch(f"/admin/events/requests/{req['id']}", headers=admin_headers,
                        json=dict(status='contacted', notes='Called on Monday')).status_code == 200

def test_every_admin_route_needs_an_admin(client, sign_in): ...   # a member session -> 403 on each route
def test_every_change_is_audited(client, admin_headers, organiser): ...
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_event_manage.py` (the factored publish). Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/admin.py service/events/invites.py service/events/manage.py service/api/admin/events_routes.py service/api/events_routes.py service/api/__init__.py duotypes/__init__.py tests/conftest.py tests/test_admin_events.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the admin's approvals, pause, badge, figures and invite requests" -m "Refs: TEC-1845"
```

### Task 12: Retention, deleting with the account and linking at sign-up

**Files:**
- Create: `service/events/retention.py`
- Modify: `service/cron/leadretention/__init__.py` (`_purge_once`), `service/hard_delete.py`, `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py`, `service/person/__init__.py` (after `link_tool_sessions_to_person`, line 959)
- Test: `tests/test_event_retention.py` (create)

**Interfaces:**
- Produces, in `service.events.retention`:
  - `ERASE_AFTER_END = timedelta(days=90)`; `purge_event_data(tx, now=None) -> dict` `{erased, unconfirmed, links, requests}`: erases name, email and normalized email (`erased_at` set, counts kept) of RSVPs whose gathering ended 90 days ago; deletes RSVPs never confirmed a day after `confirm_by`; deletes `organiser_link` rows a day after they lapse; deletes invite requests 12 months after `updated_at`.
  - `Q_DELETE_EVENT_DATA_OF` (binds `nes` and `ids`, as `Q_DELETE_TOOL_DATA_OF`): deletes the RSVPs of the address or the account. Organiser rows are not accounts and stay (privacy paragraph: ask support).
  - `link_rsvps_to_person(tx, person_id: int) -> None`: confirmed RSVPs with the member's normalised address get `person_id`; behind a savepoint, never undoing the sign-up. The member's `lead_source` of `event:{slug}` comes from `link_leads_to_person`, which already runs first.
- `_purge_once` prints a line per count, as it does for Together.

- [ ] **Step 1: Write the failing test** `tests/test_event_retention.py`: `test_names_and_emails_go_90_days_after_the_gathering_and_the_counts_stay`, `test_an_rsvp_never_confirmed_goes_a_day_after_its_window`, `test_lapsed_links_go`, `test_old_invite_requests_go`, `test_deleting_an_account_deletes_its_rsvps` (through `Q_DELETE_EVENT_DATA_OF` with the shapes the three callers bind), `test_a_guest_who_joins_is_linked_and_credited_to_the_gathering` (a confirmed visitor RSVP, then `finish_onboarding` for the same address: `event_rsvp.person_id` set and `person.lead_source == f'event:{slug}'`).
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above; each of the three deletion callers runs `Q_DELETE_EVENT_DATA_OF` beside its `Q_DELETE_TOOL_DATA_OF` call.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_tool_retention.py` and `tests/test_pendingdeletion.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/retention.py service/cron/leadretention/__init__.py service/hard_delete.py service/cron/pendingdeletion/__init__.py service/api/admin/users_action_routes.py service/person/__init__.py tests/test_event_retention.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): RSVP retention, deleting with the account and crediting a sign-up to its gathering" -m "Refs: TEC-1845"
```

### Task 13: Proofs of the 10 emails, to the owner only

**Files:**
- Create: `scripts/send_event_proofs.py`
- Test: `tests/test_send_event_proofs.py` (create)

**Interfaces:**
- Consumes: `scripts.send_proofs.PROOF_TO`, `PROOF_LINK_DISABLED`, `_inert`, `_smtp`; the `preview_*` functions of Task 9; `emails.base.ASSETS_DIR`; `mail.TITLES`.
- Produces: `plan() -> list[dict]` (name, label, subject prefixed `[PROOF] `, html with inert links, from_addr), in this order: confirm in person (3.1), confirm online, reminder in person (3.2), reminder online (3.3), change (3.4), cancelled (3.5), digest (3.6), manage link (3.8), request approved, gathering live; `missing_titles() -> list[str]`; `main(argv)` with `--send`, which refuses to send while a title image is missing (prints the stems and exits 1). It reads and changes no switch.

- [ ] **Step 1: Write the failing test**, as `tests/test_send_together_proofs.py` does: `test_every_proof_goes_to_the_owner_only`, `test_every_link_in_a_proof_is_inert`, `test_the_plan_lists_the_10_emails_in_order`, `test_no_switch_is_read` (monkeypatch `service.campaigns.switches.enabled` to raise), `test_it_will_not_send_while_a_title_image_is_missing` (monkeypatch `ASSETS_DIR` to an empty folder; `main(['--send'])` exits 1 and sends nothing).
- [ ] **Step 2: Run it to verify it fails.** Expected: `No module named 'scripts.send_event_proofs'`.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add scripts/send_event_proofs.py tests/test_send_event_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): proofs of the gathering emails, to the owner only" -m "Refs: TEC-1845"
```

## Release 1 web (ahavah-web)

Every page here is transcribed from `Ahavah Events.html` (frames named by their number, 1.1 to 7.6) or `Ahavah Marketing Pages and Landing.html` with `/sot-sync` once its tests pass, at 390 first, then 768 and 1440, dark and light, and checked at 320 and 390 for sideways scroll. The shared marketing frame (`p11-mk.js` `shared()`) gives `/events`, `/e/{slug}` and `/invite-ahavah` the marketing header and footer; its "Questions" section waits for the owner's answers and is not built (item 24).

### Task 14: The events library: calls, the live check, time words, regions, the organiser's token and the copy

**Files:**
- Create: `src/lib/events/api.ts`, `status.ts`, `server.ts`, `format.ts`, `region.ts`, `organiser-token.ts`, `copy.ts`, `nav.ts`
- Test: `tests/lib/events-format.test.ts`, `tests/lib/events-region.test.ts`, `tests/lib/events-api.test.ts`, `tests/lib/events-organiser-token.test.ts` (create)

**Interfaces:**
- Consumes: `apiClient` with its `headers` option (`src/lib/api-client.ts`); `fetchPublicSummary` (`src/lib/share-image/summary.ts`); `AntibotPayload`; `signupStampForRequest`.
- Produces:
  - `api.ts`: types `EventCard`, `EventView` (Task 7's fields), `RsvpView`, `OrganiserMe`, `OrganiserGroups`, `GatheringItem`, `RsvpList`, `EventDraft`, `Region = "africa" | "asia" | "europe" | "north-america" | "oceania" | "south-america" | "online"`; calls `listEvents(region?: Region, limit?: number)`, `getEvent(slug)`, `countView(slug)` (once per tab, `sessionStorage` key `ahavah.event-view.{slug}`, failures ignored), `rsvp(slug, body)`, `confirmRsvp(token)`, `getRsvp(token)`, `cancelRsvp(token)`, `rsvpMe()` (a signed-in member's `{name, email}`), `calendarHref(token)` (`/api/rsvp/{token}/calendar.ics`), `hostRequest(body)`, `requestOrganiserLink(email, antibot)`, `inviteAhavah(body)`, `countries()` and the organiser calls `organiserMe`, `createGathering`, `updateGathering`, `publishGathering`, `cancelGathering`, `previewGathering`, `uploadCover`, `removeCover`, `rsvpList`, `markAttended`, each sending `X-Organiser-Token` from `organiser-token.ts`. Each throws `ApiError` with the API's `error` as its reason.
  - `status.ts`: `eventsStatus(): Promise<{live, hosting, list, invite}>`, dark (all false) when the API cannot be read, as `togetherStatus` is.
  - `server.ts`: `getEventForPage(slug): Promise<EventView | null>`, `listEventsForPage(region?: Region, limit?: number): Promise<EventCard[]>`, both through `fetchPublicSummary`, so a server read never throws.
  - `format.ts`: `tzLabel(tz: string): string` (`Intl.DateTimeFormat("en-GB", { timeZone, timeZoneName: "longGeneric" })`, with `Europe/London` as `UK time`); `whenLines(e: { starts_at, ends_at, tz, tz_label }, viewerTz?: string): { date: string; time: string; yours: string | null }`, the same words as the API's `when_words`, plus `yours` (`"Your time: midnight to 3am, Sunday, UK time"`, export 1.1) when the viewer's zone shows a different clock, with the day named only when the viewer's date differs; `shortDate(iso, tz)`, `"Sat 7 Nov"` for the landing cards (`p11-mk.js` `GS`).
  - `region.ts`: `REGIONS: ReadonlyArray<{ id: Region; label: string }>` in the export's order (Africa, Asia, Europe, North America, Oceania, South America, Online); `regionFromTimeZone(tz?: string): Region | null` (`Africa/` africa; `Asia/` asia; `Europe/` europe; `Australia/`, `Pacific/` oceania; `America/` south-america for the zones of Argentina, Bolivia, Brazil, Chile, Colombia, Ecuador, French Guiana, Guyana, Paraguay, Peru, Suriname, Uruguay and Venezuela, else north-america; anything else null); `regionLabel(id)`.
  - `organiser-token.ts`: `captureOrganiserToken(url: URL): string | null` (reads `t`, stores it with its 7 day expiry and the time it was stored, returns the URL to `replace` with `t` removed), `organiserToken(): string | null`, `rememberOrganiserEmail(email)`, `organiserEmail()`, `forgetOrganiser()`; `localStorage` key `ahavah.organiser`, every read and write in `try`.
  - `copy.ts`: `EVENT_COPY`, every string of `10-events.md` sections 1, 2 and 4 to 6 under the frame number it comes from, plus the NEW LINES of this plan, each with a `// NEW LINE` comment.
  - `nav.ts`: `export const EVENTS_IN_NAV = false;` (Task 27 flips it).

- [ ] **Step 1: Write the failing tests**

```ts
// tests/lib/events-format.test.ts
const EV = { starts_at: "2026-11-08T00:00:00Z", ends_at: "2026-11-08T03:00:00Z", tz: "America/Chicago", tz_label: "Central Time" };

it("formats the gathering's own time as the export does", () => {
  const w = whenLines(EV, "America/Chicago");
  expect([w.date, w.time, w.yours]).toEqual(["Saturday 7 November 2026", "6pm to 9pm, Central Time", null]);
});

it("shows the viewer's own day when it differs", () => {
  expect(whenLines(EV, "Europe/London").yours).toBe("Your time: midnight to 3am, Sunday, UK time");
});

it("names minutes with a full stop and leaves the day out when it is the same", () => {
  const talk = { starts_at: "2026-11-12T19:00:00Z", ends_at: "2026-11-12T20:15:00Z", tz: "Europe/London", tz_label: "UK time" };
  expect(whenLines(talk, "Europe/London").time).toBe("7pm to 8.15pm, UK time");
  expect(whenLines(talk, "America/Chicago").yours).toBe("Your time: 1pm to 2.15pm, Central Time");
});

it("labels the zones as the export does", () => {
  expect(tzLabel("Europe/London")).toBe("UK time");
  expect(tzLabel("America/Chicago")).toBe("Central Time");
});
```

`tests/lib/events-region.test.ts`: `maps a time zone to the Map's continents` with the 6 cases named above and `UTC` to null; `lists the regions in the export's order`. `tests/lib/events-api.test.ts`: `sends the organiser's token on every organiser call` and `sends no token on the public calls`, with `fetch` mocked. `tests/lib/events-organiser-token.test.ts`: `takes the token from the link and removes it from the address`, `forgets a token after 7 days`, `survives storage that throws`.

- [ ] **Step 2: Run them to verify they fail.** Run: `npx vitest run tests/lib/events-format.test.ts tests/lib/events-region.test.ts tests/lib/events-api.test.ts tests/lib/events-organiser-token.test.ts`. Expected: failures, the modules do not exist.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/events tests/lib/events-format.test.ts tests/lib/events-region.test.ts tests/lib/events-api.test.ts tests/lib/events-organiser-token.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gatherings library, time words, regions and the organiser's link" -m "Refs: TEC-1845"
```

### Task 15: The share images: a gathering's link preview and the two page previews

**Files:**
- Create: `src/lib/share-image/events-templates.tsx`, `src/app/e/[slug]/opengraph-image.tsx`, `src/app/events/opengraph-image.tsx`, `src/app/invite-ahavah/opengraph-image.tsx`, `public/events/family-home.jpg`, `public/events/couple-seniors.jpg` (copied from `Claude Design/assets/stock/`)
- Modify: `src/lib/share-image/templates.tsx` (register, as Together does)
- Test: `tests/lib/events-share-images.test.ts`, `tests/app/events-images.test.ts` (create)

**Interfaces:**
- Consumes: `renderShareImage`, `loadShareFonts`, `AhavahMark`, `SHARE_SIZES.link`; `getEventForPage`; `eventsStatus`; `whenLines`.
- Produces: templates `event-link` (frames 7.1 to 7.6: title, date, city or "Online", "Hosted by {organiser}", the Ahavah mark, the feast label and the "Ahavah will be there" chip when they apply, the cover or the brand pattern; never the venue; flexbox only, content centred), `page-events` and `page-invite` (`p11-mk.js` `og()` with `OGP.events` and `OGP.invite`: the line, "Matchmaking for Torah-observant believers who hope to marry." and `AHAVAH.APP`). Each route answers `notFound()` while its page is dark (`live`; `live` and `list` for `/events`; `live` and `invite` for `/invite-ahavah`); `/e/{slug}` draws the fallback when the gathering cannot be read.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/lib/events-share-images.test.ts
it("never draws the venue, even when the data carries one", () => {
  const tree = JSON.stringify(SHARE_TEMPLATES["event-link"]({ size: SHARE_SIZES.link, data: { ...SHORT, venue: "14 Elm Street" } }));
  expect(tree).not.toContain("Elm Street");
});
it("draws the feast label and the badge only when they apply", () => { /* SHORT with feast_label "Tabernacles" and ahavah_attending true, then without */ });
it("says Online for an online gathering", () => { /* ONL: "Online", no city */ });
it("fits the longest title from the export", () => { /* LONG's 75 character title at the smaller size step */ });
```

`tests/app/events-images.test.ts`: `answers not found while gatherings are dark` for the three routes; `draws the fallback when the gathering cannot be read`.

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above; render 7.1 to 7.6 and the two page previews locally and compare them with the export by eye.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/share-image/events-templates.tsx src/lib/share-image/templates.tsx "src/app/e/[slug]/opengraph-image.tsx" src/app/events/opengraph-image.tsx src/app/invite-ahavah/opengraph-image.tsx public/events tests/lib/events-share-images.test.ts tests/app/events-images.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(events): link previews for a gathering, the list and the leaders' page" -m "Refs: TEC-1845"
```

### Task 16: The event page, `/e/{slug}`

**Files:**
- Create: `src/app/e/[slug]/page.tsx`, `src/app/e/[slug]/not-found.tsx`, `src/lib/events/schema.ts`, `src/components/events/event-page.tsx`, `event-head.tsx`, `event-tags.tsx`, `safety-note.tsx`, `sticky-rsvp.tsx`, `event-banner.tsx`
- Test: `tests/lib/events-schema.test.ts`, `tests/app/event-page.test.tsx` (create)

**Interfaces:**
- Consumes: `eventsStatus`, `getEventForPage`, `whenLines`, `countView`, `EVENT_COPY`; the marketing header and footer (`active="Gatherings"`).
- Produces:
  - `page.tsx` (server): `notFound()` while dark or when the gathering cannot be found; `generateMetadata` with the title, the description `"{date}, {time}. {place}. Hosted by {organiser}."` (the shape of `p11-mk.js` `PAGES.e`), canonical `/e/{slug}`, Open Graph and Twitter cards pointing at the image route; the JSON-LD script from `eventJsonLd`; `<EventPage view={...} />`.
  - `not-found.tsx`: frame 1.13 ("We could not find this gathering", "The link may be mistyped, or the gathering may have been removed.", "See gatherings near you" to `/events`).
  - `schema.ts`: `eventJsonLd(view: EventView, url: string): Record<string, unknown>`: `@type: "Event"`, `name`, `startDate` and `endDate` with the zone's offset, `eventAttendanceMode` (`OfflineEventAttendanceMode` or `OnlineEventAttendanceMode`), `eventStatus` (`EventScheduled`, `EventCancelled` or `EventRescheduled` while a date change shows), `location` (`Place` with `address: { addressLocality: city, addressCountry: country }`, and `name` the venue only when public; `VirtualLocation` with the page's own URL for online), `organizer: { "@type": "Organization", name }`, `image` (the cover), `description`, `isAccessibleForFree: true`. Never the venue unless public, never the call link.
  - `event-page.tsx` (client): the head (cover or the brand pattern, title, date and time with "Your time", place line with "The address is shared when you confirm your place." or "The link is shared when you confirm your place.", "Hosted by", the organiser's kind chip), tags that wrap ("Singles welcome", "Marriage preparation", the feast label, "Ahavah will be there"), "{n} going" when given, the banner for full (1.8, with "See other gatherings"), cancelled (1.9, the organiser's note in quotes and the organiser's name), changed (1.10, "It now starts at {time}, not {old}." and the NEW LINES of item 12 for a date or place), ended (1.11) and preview (1.12), "About this gathering" and the description (plain text, line breaks kept, no links made), the safety note on every in-person gathering (1.2), the RSVP form (Task 17) unless full, cancelled or ended; on a phone, the sticky "RSVP" button that scrolls to the form. Calls `countView` once on mount. The organiser leads; the Ahavah mark stays small in the header (decision 10).

- [ ] **Step 1: Write the failing tests**

```ts
// tests/lib/events-schema.test.ts
it("never puts the venue or the call link in the event data", () => {
  const ld = JSON.stringify(eventJsonLd({ ...VIEW, venue: undefined }, URL_));
  expect(ld).not.toMatch(/Elm Street|meet\.example\.com/);
});
it("names the venue only when the organiser made it public", () => { /* venue present -> location.name */ });
it("uses a virtual location for an online gathering", () => { /* location["@type"] === "VirtualLocation", url === URL_ */ });
it("says cancelled and rescheduled", () => { /* state cancelled -> EventCancelled; changed date -> EventRescheduled */ });
```

`tests/app/event-page.test.tsx`, rendering `EventPage` with the export's sample gatherings (`EV` and `ONL` of `p10-ev.js`): `hides the venue until the guest confirms`, `shows the venue when the organiser made it public`, `says the link is shared on confirming for an online gathering`, `shows how many are going only when the organiser shows it`, `shows the safety note on in-person pages only`, `says full and offers other gatherings`, `shows the organiser's note on a cancelled gathering and no form`, `says what changed`, `says it has ended`, `wraps the tags`, `leads with the organiser, the mark small`, `counts one view per tab`.

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above, then `/sot-sync` frames 1.1 to 1.14.
- [ ] **Step 4: Run them to verify they pass**, then `npx tsc --noEmit` and `npx eslint src/app/e src/components/events src/lib/events`. Expected: all pass, no errors.
- [ ] **Step 5: Commit**

```bash
git add "src/app/e/[slug]/page.tsx" "src/app/e/[slug]/not-found.tsx" src/lib/events/schema.ts src/components/events tests/lib/events-schema.test.ts tests/app/event-page.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gathering page, with its schema.org data" -m "Refs: TEC-1845"
```

### Task 17: RSVP, checking your email, confirming and cancelling

**Files:**
- Create: `src/components/events/rsvp-form.tsx`, `check-email.tsx`, `rsvp-status.tsx`, `cancel-place-sheet.tsx`; `src/app/rsvp/confirm/[token]/page.tsx`, `src/app/rsvp/[token]/page.tsx`
- Modify: `src/components/events/event-page.tsx` (mounts the form)
- Test: `tests/app/rsvp-form.test.tsx`, `tests/app/rsvp-pages.test.tsx` (create)

**Interfaces:**
- Consumes: `rsvp`, `confirmRsvp`, `getRsvp`, `cancelRsvp`, `calendarHref`; `AntibotFields` (`src/components/app/antibot-fields.tsx`), `signupStampForRequest`; `useMember()` (`src/components/together/kit.tsx`) and `rsvpMe()` for "Filled in from your Ahavah account".
- Produces:
  - `rsvp-form.tsx`: frame 2.1: "Name" ("Your name"), "Email", "How many are coming, including you" (a stepper from 1 to 10), the two unticked boxes "Share my email with the organiser" and "Tell me about Ahavah events and members near me", "RSVP", "We will email you a link to confirm your place."; a signed-in member sees 2.3 ("Filled in from your Ahavah account", the email read only). Errors: 2.4 for an address without `@` and a dot after it (and the API's `bad_email`), 2.5 "Only {n} places left" for `too_many`, 2.7 for `too_many_tries` and HTTP 429, 2.8 for anything else; 2.6 while sending. On `check_email` it shows `check-email.tsx`; on `confirmed` (a member) it goes to `/rsvp/{token}`.
  - `check-email.tsx`: frame 2.9 with the address typed; "Send it again" posts the same RSVP again; "Use a different email" returns to the form with the name and party kept.
  - `/rsvp/confirm/[token]` (client page, `robots: noindex`): calls `confirmRsvp` once in an effect, then shows 2.10 or 2.11, 2.14 for `expired` (with "Back to the gathering"), 2.15 for `full_now`, 2.16 for `cancelled_now`, and 1.13's lines for an unknown token.
  - `/rsvp/[token]` (client page, `robots: noindex`): `getRsvp`; the confirmed page 2.10 or 2.11 ("You are going", the date, the venue or the link, "Add to calendar" to `calendarHref`, "Cancel my place", "Ahavah is matchmaking for Torah-observant believers who hope to marry." and "See how it works" to `/#how`); "Cancel my place" opens 2.12 ("Keep my place" or confirm), then 2.13.

- [ ] **Step 1: Write the failing tests**

`tests/app/rsvp-form.test.tsx`: `starts with both boxes unticked`, `sends the party size and the two boxes`, `asks for a full email address`, `says how many places are left`, `says too many tries`, `shows check your email with the address`, `sends it again with the same answers`, `fills in a signed-in member and goes straight to their place`. `tests/app/rsvp-pages.test.tsx`:

```tsx
it("does not confirm until the page has loaded", async () => {
  const confirm = vi.spyOn(api, "confirmRsvp").mockResolvedValue(CONFIRMED);
  renderToString(<ConfirmPage params={Promise.resolve({ token: "t".repeat(32) })} />);
  expect(confirm).not.toHaveBeenCalled();
  render(<ConfirmPage params={Promise.resolve({ token: "t".repeat(32) })} />);
  await screen.findByText("You are going");
  expect(confirm).toHaveBeenCalledTimes(1);
});
```

plus `shows the venue once confirmed`, `shows the call link for an online gathering`, `says the link has expired`, `says it filled up before you confirmed`, `cancels after asking`, `links the calendar file`.

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above, then `/sot-sync` frames 2.1 to 2.16.
- [ ] **Step 4: Run them to verify they pass**, with `npx tsc --noEmit`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/events "src/app/rsvp/confirm/[token]/page.tsx" "src/app/rsvp/[token]/page.tsx" tests/app/rsvp-form.test.tsx tests/app/rsvp-pages.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): RSVP, check your email, confirm and cancel" -m "Refs: TEC-1845"
```

### Task 18: `/events`, by region

**Files:**
- Create: `src/app/events/page.tsx`, `src/components/events/events-list.tsx`, `src/components/events/gathering-card.tsx`
- Test: `tests/app/events-list.test.tsx` (create)

**Interfaces:**
- Consumes: `eventsStatus`, `listEvents`, `REGIONS`, `regionFromTimeZone`, `regionLabel`, `whenLines`.
- Produces: `page.tsx` (server): `notFound()` unless `live` and `list`; metadata from the marketing brief's table (title "Gatherings", description "Gatherings for Torah-observant believers preparing for marriage, in person and online.", canonical `/events`, the image route). `events-list.tsx` (client): the pills that wrap (5.1, the chosen one marked `aria-pressed`), the first region from `?region=` or the visitor's time zone, else North America; "Showing gatherings in {region}" ("Showing online gatherings" for Online, NEW LINE); cards (cover, title, date, city or "Online", organiser, tags, "{n} going" where shown); 5.2 for an empty region with "Invite Ahavah to your gathering" (to `/invite-ahavah`, only while `invite` is on) and "Host a gathering" (to `/host`, only while `hosting` is on); 5.4 loading; 5.5 failed with "Try again". Choosing a region updates `?region=` with `router.replace`.

- [ ] **Step 1: Write the failing test** `tests/app/events-list.test.tsx`: `starts in the visitor's region`, `wraps the region pills`, `says which region it shows`, `shows online gatherings in every region`, `offers to invite Ahavah or host when a region is empty`, `hides an offer whose page is not open`, `says it could not load and tries again`, `keeps the region in the address`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 5.1 to 5.5.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/events/page.tsx src/components/events/events-list.tsx src/components/events/gathering-card.tsx tests/app/events-list.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): gatherings by region at /events" -m "Refs: TEC-1845"
```

### Task 19: `/invite-ahavah`, for leaders

**Files:**
- Create: `src/app/invite-ahavah/page.tsx`, `src/components/events/invite-ahavah.tsx`
- Test: `tests/app/invite-ahavah.test.tsx` (create)

**Interfaces:**
- Consumes: `eventsStatus`, `inviteAhavah`, `AntibotFields`, `signupStampForRequest`.
- Produces: `page.tsx`: `notFound()` unless `live` and `invite`; metadata from the marketing brief's table (title "Invite Ahavah to your gathering", its description, canonical, image); `active="For leaders"`. `invite-ahavah.tsx`: frame 6.1 ("For leaders", the headline, "We can come to your assembly, fellowship or feast site, or join by call.", "Request a visit" which scrolls to the form, "What Ahavah can bring" with the 4 offers, the form "The gathering", "Dates", "Expected numbers", "Place", "Your name", "Your email", "Request a visit"), "Download the leader pack (PDF)" only when `LEADER_PACK_URL` (in the component, `null` until the PDF exists, item 23) is set, "Running your own gathering? Host it on Ahavah." to `/host` only while `hosting` is on; 6.2 sending, 6.3 sent, 6.4 failed (2.8's line), 6.5 too many tries (2.7's line).

- [ ] **Step 1: Write the failing test** `tests/app/invite-ahavah.test.tsx`: `shows the 4 offers and the form`, `sends the request and thanks the leader`, `hides the leader pack until it exists`, `links to hosting only when hosting is open`, `says too many tries`, `says it could not send`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 6.1 to 6.5.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/invite-ahavah/page.tsx src/components/events/invite-ahavah.tsx tests/app/invite-ahavah.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the leaders' page, Invite Ahavah to your gathering" -m "Refs: TEC-1845"
```

### Task 20: Hosting: the request, the code step and "Your gatherings"

**Files:**
- Create: `src/app/host/page.tsx`, `src/app/host/gatherings/page.tsx`, `src/components/events/host-request.tsx`, `src/components/events/my-gatherings.tsx`
- Test: `tests/app/host-request.test.tsx`, `tests/app/my-gatherings.test.tsx` (create)

**Interfaces:**
- Consumes: `requestEmailOtp` and `checkOtp` (`src/lib/auth-otp.ts`, as the checklist's gate uses them, no source), `hostRequest`, `organiserMe`, `requestOrganiserLink`, `captureOrganiserToken`, `organiserToken`, `rememberOrganiserEmail`, `organiserEmail`.
- Produces:
  - `/host` (`notFound()` unless `live` and `hosting`, `robots: noindex`): 4.1 to 4.5. "Send code" sends the sign-in code (the standard sign-in email, item 13); 4.2 the 6 boxes with "Change" and "Send a new code"; 4.3 a wrong or expired code; "Send request" posts the request with the session the code left; `created` shows 4.4 and stores the token; `pending` shows 4.5; `approved` goes to `/host/gatherings`.
  - `/host/gatherings` (`notFound()` unless `live`, `robots: noindex`): takes `t` from the link (`captureOrganiserToken`, then `router.replace`), loads `organiserMe`; 4.6 grouped as Drafts, Waiting for approval, Published, Cancelled and Ended with "New gathering" (to `/host/gatherings/new`); 4.7 above the list while not approved; 4.8 empty; 4.9 for `expired`, where "Send me a new link" posts the remembered address, or asks for it with the RSVP form's "Email" field when none is remembered.

- [ ] **Step 1: Write the failing tests**: `host-request.test.tsx`: `sends the code then the request`, `says the code is wrong`, `thanks a new organiser and keeps their link`, `says a request is already waiting`, `goes straight in when already approved`, `refuses the kind Ahavah` (the four kinds only). `my-gatherings.test.tsx`: `takes the link from the address and removes it`, `groups gatherings by status`, `says the request is waiting and drafts can be saved`, `says there are no gatherings yet`, `offers a new link when this one has expired`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 4.1 to 4.9.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/host/page.tsx src/app/host/gatherings/page.tsx src/components/events/host-request.tsx src/components/events/my-gatherings.tsx tests/app/host-request.test.tsx tests/app/my-gatherings.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): asking to host and the organiser's gatherings" -m "Refs: TEC-1845"
```

### Task 21: The gathering form: every field, the cover, publishing, changing and cancelling

**Files:**
- Create: `src/app/host/gatherings/[slug]/page.tsx`, `src/app/host/gatherings/[slug]/preview/page.tsx`, `src/components/events/gathering-form.tsx`, `cover-field.tsx`, `change-sheet.tsx`, `cancel-gathering-sheet.tsx`
- Test: `tests/app/gathering-form.test.tsx` (create)

**Interfaces:**
- Consumes: `createGathering`, `updateGathering`, `publishGathering`, `cancelGathering`, `previewGathering`, `uploadCover`, `removeCover`, `countries`, `tzLabel`, `EventPage` (for the preview); the existing cropper (`cropImageToBlob`, `src/lib/crop-image.ts`) for the dashed 1200 by 630 crop.
- Produces: `/host/gatherings/new` and `/host/gatherings/{slug}` (`robots: noindex`): frame 4.10 with "Feast (optional)" from the 8 names (option B), the time zone picker over `Intl.supportedValuesOf("timeZone")` labelled by `tzLabel`, the organiser's own zone first; "Where" In person (city, the country from `countries()`, "Venue", "Show the address only to people who confirm", on by default) or Online ("Call link", "Shown only to people who confirm."); "Capacity" empty means no limit; "Show how many are going" off ("Off suits small gatherings."). The form sends `tz_label` with `tz`. Cover: 4.13 uploading, 4.14 failed, "Change" and "Remove". Saving 4.15 and "Saved" 4.16; "Publish" for an approved organiser and "Send for approval" otherwise (4.18 then shows its line); 4.17 publish failed; 4.19 paused (read only, "Paused" chip). Changing the date, time or place of a published gathering opens 4.20 before saving; "Cancel this gathering" opens 4.21 (the note is optional) then 4.22. "Preview" opens `/host/gatherings/{slug}/preview`, the event page with banner 1.12 for a draft or pending gathering.

- [ ] **Step 1: Write the failing test** `tests/app/gathering-form.test.tsx`: `shows every field with the feast list in order`, `sends the time zone with its label`, `asks for a call link when online and drops the place`, `offers Publish to an approved organiser and Send for approval otherwise`, `warns before changing the time of a published gathering`, `does not warn for a description change`, `cancels with a note`, `says the cover could not be uploaded`, `shows a paused gathering read only`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 4.10 to 4.22.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add "src/app/host/gatherings/[slug]" src/components/events/gathering-form.tsx src/components/events/cover-field.tsx src/components/events/change-sheet.tsx src/components/events/cancel-gathering-sheet.tsx tests/app/gathering-form.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gathering form, covers, publishing, changing and cancelling" -m "Refs: TEC-1845"
```

### Task 22: The RSVP list and marking attendance

**Files:**
- Create: `src/app/host/gatherings/[slug]/guests/page.tsx`, `src/components/events/rsvp-list.tsx`
- Test: `tests/app/rsvp-list.test.tsx` (create)

**Interfaces:**
- Consumes: `rsvpList`, `markAttended`.
- Produces: frames 4.23 to 4.25 as rows (never a table that scrolls): "Going" with the total, "Not yet confirmed", each row the name and "1 person" or "{n} people", the email where shared or "Email not shared", "Waiting for them to confirm"; once started, "The gathering has started. Mark who came." and "Mark attended" toggling to "Attended"; "No one has RSVPed yet." when empty. `robots: noindex`.

- [ ] **Step 1: Write the failing test**: `lists guests with party sizes`, `shows an email only where the guest shared it`, `marks attendance only once it has started`, `says no one has RSVPed yet`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 4.23 to 4.25.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add "src/app/host/gatherings/[slug]/guests/page.tsx" src/components/events/rsvp-list.tsx tests/app/rsvp-list.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the organiser's RSVP list and attendance" -m "Refs: TEC-1845"
```

### Task 23: "Gatherings near you" on the landing, the header and footer links, the sitemap and robots

**Files:**
- Create: `src/components/events/gatherings-near-you.tsx`
- Modify: `src/app/page.tsx` (after the "Who it's for" section, before "What's different"), `src/components/app/marketing-header.tsx` (`NEW_LINKS`), `src/components/app/marketing-footer.tsx` (`COMMUNITY_LINKS`), `src/app/sitemap.ts`, `src/app/robots.ts`
- Test: `tests/components/gatherings-near-you.test.tsx` (create), `tests/components/marketing-header.test.tsx` (extend), `tests/app/events-sitemap.test.ts` (create)

**Interfaces:**
- Consumes: `listEvents`, `regionFromTimeZone`, `regionLabel`, `shortDate`, `EVENTS_IN_NAV`, `eventsStatus`, `listEventsForPage`.
- Produces:
  - `gatherings-near-you.tsx` (`p11-mk.js` `gather()`, copy 1.3 to 1.8): heading "Gatherings near you", "Near {region}", up to 3 compact cards (the date block, title, city or "Online", organiser, "Ahavah will be there" where it applies), "See all gatherings" to `/events` and "Invite Ahavah to your gathering" to `/invite-ahavah`. One gathering shows one card; when every card is online and a region was asked, the line is "Nothing near you yet. These are online."; with none at all, or when the call fails, the section shows only "Invite Ahavah to your gathering"; while gatherings are dark (`listEvents` answers 404) the section renders nothing. Loading holds the section's height. Cards stack on a phone.
  - `marketing-header.tsx`: `export function siteNewLinks(eventsInNav = EVENTS_IN_NAV): ReadonlyArray<SiteLink>` returning Together, then Gatherings (`/events`) and For leaders (`/invite-ahavah`) when `eventsInNav`; `NEW_LINKS` stays exported as `siteNewLinks()` so the existing callers and tests keep working; the header's comment loses "join NEW_LINKS when their pages exist" for Gatherings and For leaders (For families still waits for Matchmaker).
  - `marketing-footer.tsx`: `communityLinks(eventsInNav = EVENTS_IN_NAV)`, the same two added to the Community column and its phone accordion.
  - `sitemap.ts`: while `live` and `list`, `/events` (0.7, weekly) and each upcoming gathering `/e/{slug}` (0.6, weekly, `lastModified` its start) from `listEventsForPage(undefined, 50)`; while `live` and `invite`, `/invite-ahavah` (0.6, monthly).
  - `robots.ts`: `/host`, `/rsvp` added to `disallow`.

- [ ] **Step 1: Write the failing tests**

`tests/components/gatherings-near-you.test.tsx`: `shows the next 3 near the visitor`, `shows one gathering`, `says nothing is near and shows online ones`, `shows only the invite with no gatherings`, `shows only the invite when the call fails`, `draws nothing while gatherings are dark`, `holds its height while loading`. In `tests/components/marketing-header.test.tsx` add:

```tsx
it("adds Gatherings and For leaders when the gatherings are in the nav", () => {
  expect(siteNewLinks(true).map((l) => l.label)).toEqual(["Together", "Gatherings", "For leaders"]);
  expect(siteNewLinks(false).map((l) => l.label)).toEqual(["Together"]);
});
```

and the footer's `communityLinks` the same way. `tests/app/events-sitemap.test.ts`: `lists the gatherings only once they are live` (as `together-sitemap.test.ts` does), `lists each upcoming gathering`, `lists the leaders' page only once it is open`.

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` the landing section 1.3 to 1.8 and the header and footer 2.1 to 2.10 with the links on, at 320, 390, 768 and 1440.
- [ ] **Step 4: Run them to verify they pass**, then the whole web suite `npx vitest run`, `npx tsc --noEmit`, `npx eslint .` and `npx next build`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/events/gatherings-near-you.tsx src/app/page.tsx src/components/app/marketing-header.tsx src/components/app/marketing-footer.tsx src/app/sitemap.ts src/app/robots.ts tests/components/gatherings-near-you.test.tsx tests/components/marketing-header.test.tsx tests/app/events-sitemap.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(events): Gatherings near you on the landing, the nav links behind a flag, and the sitemap" -m "Refs: TEC-1845"
```

### Task 24: The privacy paragraphs and the organiser terms, for the owner

**Files:**
- Create: `src/lib/legal-events-copy.ts`, `src/lib/legal-organiser-terms-copy.ts`
- Modify: `src/lib/legal-leads-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx`, `src/app/terms/page.tsx`, `tests/app/legal-together.test.tsx` (its "not gathering" line)
- Test: `tests/app/legal-events.test.tsx` (create)

**Interfaces:**
- Produces: `EVENTS_PRIVACY: LegalCopy` titled "Gatherings": you can RSVP without an account; we keep your name, email, how many are coming, the two boxes you ticked or left and, if the organiser marks it, that you came; the organiser sees names and party sizes and sees your email only if you ticked the box; other guests never see who is coming; staff see only counts; we use your email for this gathering's confirmation, reminder and any change, and for news only if you ticked the box; we erase your name and email 90 days after the gathering, and an RSVP you never confirmed after 8 days; cancel your place from any of our emails, or ask at support@ahavah.app; organisers' details are kept while they host and deleted on request. `LEADS_PRIVACY.body` gains "or RSVP to a gathering". `ORGANISER_TERMS: LegalCopy & { approved: boolean }` titled "Hosting a gathering", `approved: false`, a draft for the owner (organisers give true details, keep guests safe, take no payments through Ahavah, use guests' details only for their gathering and accept that Ahavah may pause or remove a gathering); the terms page renders it only when `approved`. Both texts go through `/copy-pass` and the owner before Task 27 Step 5.

- [ ] **Step 1: Write the failing test** `tests/app/legal-events.test.tsx`: `says what an RSVP keeps, who sees it, for how long and how to delete it` (asserting the phrases above as `legal-together.test.tsx` does), `appears on both privacy pages`, `keeps the organiser terms off the page until the owner approves them`. Change `legal-together.test.tsx`'s `not.toMatch(/gathering|someone who fits joins/i)` to `not.toMatch(/someone who fits joins/i)`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/legal-events-copy.ts src/lib/legal-organiser-terms-copy.ts src/lib/legal-leads-copy.ts src/app/privacy/page.tsx src/app/legal/privacy/page.tsx src/app/terms/page.tsx tests/app/legal-together.test.tsx tests/app/legal-events.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): what an RSVP keeps on the privacy pages, and the organiser terms for the owner" -m "Refs: TEC-1845"
```

## Release 1 admin (ahavah-admin)

### Task 25: The Events tab

**Files:**
- Create: `src/lib/events-api.ts`, `src/lib/events-queries.ts`, `src/components/admin/tab-events.tsx`, `events-waiting.tsx`, `events-table.tsx`, `events-requests.tsx`
- Modify: `src/lib/tabs.ts` (`TabId` and `TABS`, after `growth`), `src/components/admin/tab-router.tsx`, `src/components/admin/sidebar-nav.tsx` (the count)
- Test: `tests/events-api.test.mjs` (create)

**Interfaces:**
- Consumes: Task 11's routes through `api` (session bearer, `/api` proxy), as `questions-queries.ts` does.
- Produces, in `src/lib/events-api.ts` (pure, no imports, vm-tested like `questions-api.ts`): the wire types of `GET /admin/events`; `kindLabel(kind)` (Assembly, Fellowship leader, Ministry, Other, Ahavah); `flagLabel(reason)` ("A new organiser’s first gathering", "Flagged by the scam pattern filter", "Flagged by the rude words filter", "The cover needs a look" NEW LINE, "Declined" NEW LINE); `requestStatusLabel` (New, Contacted, Planned, Declined); `figureRow(event)` (`confirmedShare` as a whole per cent of RSVPs or `null` with none, `women` as "{n} of {m} members" or `null`); `waitingCount(overview)`. The tab (copy 3.1 to 3.7, `admin-growth-features.jsx`): "Events", "Gatherings, organisers and requests from leaders"; a bento of full-width rows with level tiles: "Waiting for you" (organisers to approve and gatherings to approve, each with "Approve" and "Decline"; on a phone "Needs a desktop" in their place), "Invite requests" (status select, "Notes, only you see these", saved on blur), "Gatherings" (Gathering, Date, Page views, RSVPs, Confirmed, Attended, Sign-ups, "Paused"; "Attended is as the organiser marked it. RSVPs are counts only; names stay with the organiser."), each opening its detail (3.4: per week, "Show “Ahavah will be there”", "On the gathering page, the list and its posts", "Pause this gathering"), "Organisers" with "Revoke" and "Add Ahavah as an organiser" (name and email, NEW LINE); "Nothing to approve." (3.3); failures 3.6. The sidebar shows `waitingCount` on Events.

- [ ] **Step 1: Write the failing test** `tests/events-api.test.mjs` (the `questions-api.test.mjs` harness): `labels kinds and flags`, `gives the confirmed share and leaves it out with no RSVPs`, `counts women among member RSVPs only`, `counts what waits`, `never carries a guest's name` (a fixture overview with no name fields passes through every helper unchanged in shape).
- [ ] **Step 2: Run it to verify it fails.** Run: `node --test tests/events-api.test.mjs`. Expected: failure, the file does not exist.
- [ ] **Step 3: Implement**, then `/sot-sync` section 3 of `Ahavah Admin Growth Features.html`.
- [ ] **Step 4: Run it to verify it passes**, then `node --test tests/*.test.mjs`, `npx tsc --noEmit` and `npx next build`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/events-api.ts src/lib/events-queries.ts src/components/admin/tab-events.tsx src/components/admin/events-waiting.tsx src/components/admin/events-table.tsx src/components/admin/events-requests.tsx src/lib/tabs.ts src/components/admin/tab-router.tsx src/components/admin/sidebar-nav.tsx tests/events-api.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the Events tab, approvals, requests and figures as counts" -m "Refs: TEC-1845"
```

### Task 26: The event post artwork and its render step

**Files:**
- Create: `src/lib/event-card.tsx`
- Modify: `src/lib/tick.ts` (a step after step 4), `src/lib/growth-server.ts` (`queue` takes `templateRender`)
- Test: `tests/event-card.test.mjs` (create), `tests/tick.test.mjs` (extend)

**Interfaces:**
- Consumes: the queue rows' `template_data` (Task 5's `post_payload` plus `offset_days` and `starts_at`); `GET /admin/growth/queue?template_render=1`; `growthApi.queueImage`, `growthApi.renderFailed`; the fonts and logo loaders of `spotlight-card.tsx`.
- Produces: `renderEventCard(data: EventCardData, platform: "facebook" | "instagram"): Promise<Buffer>`, a 1080 by 1350 JPEG of the social set's card 4.1 (`p12-social.js` `evCard`, feed): the lime ground, the logo, "A gathering · all welcome", the title at the export's size steps (`evFs`: 160, 104 or 78 px by length), the tags and the feast label, the "Date", "Where" and "Hosted by" tiles, "RSVP at ahavah.app/e/{slug}", and the badge when `ahavah_attending`. It reads only the named slots, so a venue can never reach it. `growthServer.queue(status, { templateRender: true })` adds `template_render=1`. The tick's new step lists those rows, renders the `event` rows grouped by `request_key` and uploads each platform's image; `prompt` rows are left for their own renderer and are neither rendered nor reported failed.

- [ ] **Step 1: Write the failing tests**: `tests/event-card.test.mjs`: `draws a 1080 by 1350 JPEG`, `fits the longest title from the export`, `ignores any field that is not a slot` (data with `venue: "14 Elm Street"`: the rendered element tree has no "Elm Street"). In `tests/tick.test.mjs`: `renders and uploads event posts waiting for artwork`, `leaves prompt posts alone`, `reports a failed event render`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above, rendering the export's three 4.1 samples and comparing them by eye.
- [ ] **Step 4: Run them to verify they pass**, with `node --test tests/*.test.mjs`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/event-card.tsx src/lib/tick.ts src/lib/growth-server.ts tests/event-card.test.mjs tests/tick.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gathering post artwork, rendered by the tick" -m "Refs: TEC-1845"
```

## The launch

### Task 27: The launch, in order: API dark, web dark, admin, proofs, then the switches

An operational task: no code beyond two one-line flags. Each step names who acts. Nothing reaches a guest, an organiser or social before the owner confirms its proof.

**Files:**
- Modify (web, Step 11 only): `src/lib/events/nav.ts` (`EVENTS_IN_NAV = true`); (web, Step 7, only on his yes): `src/lib/legal-organiser-terms-copy.ts` (`approved: true`)
- Add (Step 4): `ahavah-web/public/email/title-event-*.png` and `-wht.png` (12 files), synced into `ahavah-api/emails/assets/` with `scripts/sync_email_assets.sh`; `mail.TITLES` widths from the handoff's table

- [ ] **Step 1: Ship the API, dark.** With the owner's go, merge Tasks 1 to 13 to `ahavah/main`; the push deploys through GitHub Actions and applies 0071. With every switch at its default `0`: `curl -s https://api.ahavah.app/events/status` answers `{"hosting":false,"invite":false,"list":false,"live":false}`; `curl -s -o /dev/null -w '%{http_code}' https://api.ahavah.app/events` and `-X POST https://api.ahavah.app/invite-ahavah` answer `404`.

- [ ] **Step 2: Ship the web, dark.** Merge Tasks 14 to 23 (not 24) to `master`; Vercel deploys. Check: `/e/anything`, `/events`, `/invite-ahavah`, `/host` and `/host/gatherings` answer 404; the sitemap has none of them; the landing page shows no "Gatherings near you"; the header and footer have no Gatherings or For leaders.

- [ ] **Step 3: Ship the admin.** Merge Tasks 25 and 26 to the admin's `master`. Check: Events shows "Nothing to approve." and an empty Gatherings table; the Growth tick reports no render failures.

- [ ] **Step 4: The email title images.** Write a short `/brief` into the existing Claude Design project (never a new one) for the 6 titles in Task 9's `TITLES`, in the family and phone line breaks of `Ahavah Email Titles for Phones.html`; when it returns, `/handoff` the 12 PNGs into `ahavah-web/public/email/`, run `./scripts/sync_email_assets.sh` in ahavah-api, fill the widths, and commit both repos (`feat(email): the gathering email titles`). `python -m scripts.send_event_proofs` stops refusing.

- [ ] **Step 5: The owner reads what the export did not have.** Hand him "Spec conflicts and decisions needing the owner" items 12 to 16, 25 and 27, run through `/copy-pass` (ux-writing for the screens, humanizer for the emails and the privacy and terms text) first. His changes go into the code (Tasks 5, 9, 14, 18, 24, 25) and ship before Step 8.

- [ ] **Step 6: Proofs to the owner.** Inside the api container: `python -m scripts.send_event_proofs` (dry run), then `python -m scripts.send_event_proofs --send`. He checks the 10 emails at 390 and 600, light and dark, Gmail's forced dark mode included, and reads every line.

- [ ] **Step 7: Privacy and terms go live.** On his yes to their wording, merge Task 24 (with `approved: true` on the organiser terms if he approved them). Check both privacy pages show "Gatherings" and the terms show "Hosting a gathering".

- [ ] **Step 8: Switch on, in order, after he confirms.** In the production environment `docker-compose.production.yml` reads, for both api and cron, then restart both:
  1. `AHAVAH_EVENTS_LIVE_ENABLED=1`.
  2. Each email whose proof he confirmed: `AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED`, `AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED`, `AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED`, `AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED`, `AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED`, `AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED`. RSVPs need the confirm email: without it no visitor can confirm.
  Check `curl -s https://api.ahavah.app/events/status` answers `{"hosting":false,"invite":false,"list":false,"live":true}`.

- [ ] **Step 9: Ahavah's first gathering (spec rollout 2).** In Admin > Events, "Add Ahavah as an organiser" with the owner's address; he receives the manage link, creates the first Ahavah-run gathering and publishes it. Its two posts appear in the Growth queue with artwork, waiting for his approval; a post after 9 Nov cannot be approved until he extends his rest-day calendar (`restdays.py` and `rest-days.ts`, which this plan does not touch).

- [ ] **Step 10: A real round on production, by the operator and the owner.** On two phones: RSVP as a visitor (the confirm email arrives; the link opens the page and confirms; "You are going" shows the venue; "Add to calendar" opens the calendar file); RSVP as a signed-in member (confirmed at once); the owner changes the time (each confirmed guest gets "A change"), sees the RSVP list with names and party sizes and gets the next day's digest; cancel one place. Paste `/e/{slug}` into WhatsApp and check the preview; run it through Google's Rich Results Test for the `Event` data; at 320 and 390 nothing scrolls sideways. Then cancel the test gathering and delete the test RSVPs.

- [ ] **Step 11: Open the rest, in the spec's order, each on his word.** `AHAVAH_EVENTS_HOSTING_ENABLED=1` (spec rollout 3; only once the organiser terms are live), then `AHAVAH_EVENTS_LIST_ENABLED=1` (rollout 4), then `AHAVAH_EVENTS_INVITE_ENABLED=1` (rollout 5). With both list and invite on, set `EVENTS_IN_NAV = true` in `src/lib/events/nav.ts`, run `npx vitest run tests/components/marketing-header.test.tsx`, and commit (`feat(marketing): Gatherings and For leaders in the header and footer`, `Refs: TEC-1845`); check the sitemap now lists `/events`, the upcoming gatherings and `/invite-ahavah`.

- [ ] **Step 12: Linear.** Move TEC-1845's Events work to Done once Step 10 passes. Open follow-ups as their own issues: the weekly email's "Gatherings near you" and the welcome mention (item 20), Moderation > Text (item 21), the "Today" story (item 22), the leader pack and badge download (item 23), the Questions sections (item 24), the hosting variant of the code email (item 13). Run `/linear-sync` before the session's final commit.

- [ ] **Step 13: Each week after.** Read Admin > Events: RSVPs per gathering, the confirmed share, new addresses among RSVPs, sign-ups credited to `event:{slug}` and women among member RSVPs (the spec's 5 measures).

---

## Spec conflicts and decisions needing the owner

Each item has the default this plan builds. The owner may change any of them.

1. **Feast labels (brief decision 1).** Default: option B, the organiser picks from the 8 biblical English names (export 1.6, 4.10). Option A (from Ahavah's calendar, 1.5, 4.11) is not built: the code holds rest days only, through 9 Nov 2026, with no feast names by date, and a label from his calendar can contradict an organiser's own reckoning.
2. **Women among RSVPs (2).** Default: no question on the form (2.1); counted among RSVPs from members only, so the figure is "{n} of {m} members". The optional question (2.2) is not built.
3. **When the venue and the link appear (3).** Default: once the guest confirms, on the confirmed page and in the reminder and change emails; never on submit.
4. **"How many are going" (4).** Default: the organiser's switch, off.
5. **"Share my email with the organiser" (5).** Default: unticked.
6. **Regions on `/events` (6).** Default: the Map's continents plus Online; online gatherings in every region; the first region from the visitor's time zone, else North America.
7. **The safety note (7).** Default: "Meet in a public place, tell a friend where you are going and never send money to someone you met online." on every in-person page and in the reminder and change emails.
8. **The confirmed page's line (8).** Default: "Ahavah is matchmaking for Torah-observant believers who hope to marry." with "See how it works" to `/#how` (the target is this plan's).
9. **The digest (9).** Default: once a day, only on days with new RSVPs, one email per gathering.
10. **Who leads an organiser's page (10).** Default: the organiser; the Ahavah mark small in the header.
11. **Admin (admin brief 1, 3, 7, 8).** Default: Events is its own tab after Growth; read only on a phone ("Needs a desktop"); RSVPs as counts only; invite statuses New, Contacted, Planned, Declined.
12. **Lines the export does not have**, marked `NEW LINE` in the code, for `/copy-pass` and the owner: the 8 email subjects (Task 9); "We share the link once you confirm."; "1 new RSVP for {title}"; "{title} is now on {date}", "{title} is now at {place}", "{title} is now online" and the page's matching change lines (Tasks 9, 16); "New RSVPs." (a title); "Ahavah has approved your request to host." and "{title} is live." (Task 9); the post caption "{title}. {date}, {place}. Hosted by {organiser}." (Task 5); "Showing online gatherings" (Task 18); "The cover needs a look", "Declined" and "Add Ahavah as an organiser" (Task 25); the privacy paragraph and the organiser terms (Task 24). The consent box "Tell me about Ahavah events and members near me" and "Share my email with the organiser" go through ux-writing as the spec asks; a changed wording gets a new `NEWS_WORDING` key.
13. **The host's code email (3.7, "Hosting on Ahavah") is not built.** Default: the request to host uses the standard sign-in code email, which says "Sign in to Ahavah". Building 3.7 means a purpose on `/request-otp`, the sign-in path every member uses; it is a follow-up if he wants it.
14. **Email headings that carry a title or a number** ("Marriage preparation evening now starts at 6pm", "3 new RSVPs for ...", "... was cancelled") cannot be title images, and typed headlines are not allowed. Default: a fixed title image ("This gathering changed.", "New RSVPs.", "This gathering was cancelled.", from the page's own lines where they exist) with the sentence as a body line under it. The 6 titles need a Claude Design brief (Task 27 Step 4) before any proof.
15. **Organiser notes the export does not draw**: "your request is approved" and "your gathering is live", both promised on screen (4.4, 4.18). Default: 3.8's manage email with one line above the button.
16. **Declining, revoking and pausing.** Default: declining an organiser revokes them (their links stop working and their gathering pages pause) and sends no email; a declined gathering returns to drafts; pausing sends no email to the organiser or the guests ("We will email you" is the owner writing himself). Cancelling stays the organiser's.
17. **Rest days.** Default: the reminder and the digest are never queued inside one of his rest periods; the reminder goes on the local day before, 08:00 to 21:00, and a gathering whose whole day before is a rest day gets none (the calendar file stands in). Confirm, change and cancellation mail go when they happen, since the guest or the organiser caused them. Gatherings themselves may fall on a Sabbath. Posts follow the existing rest-day rules and wait for his calendar after 9 Nov.
18. **Retention the spec does not set.** Default: a guest's name and email erased 90 days after the gathering (the counts stay); an RSVP never confirmed deleted a day after its window; lapsed organiser links after a day; invite requests 12 months after their last change; organisers kept while they host, deleted on request. Stated on the privacy page.
19. **A signed-in member's RSVP** is confirmed at once, with no confirm email, since the address is proved.
20. **The weekly community email's "Gatherings near you" and "Play with your match", and the welcome's mention** (growth spec, marketing brief section 4) are changed member emails with their own proofs. Default: not in this release; a follow-up.
21. **Moderation > Text** (growth spec, admin brief section 4) serves 5 features. Default: not in this release; a flagged gathering waits in Admin > Events with its reason ("Flagged by the scam pattern filter").
22. **The "Today" story and the story card** (social set 4.2, 4.3; growth spec "the story variant on the day"). Default: not in this release. The publisher posts feed images only and `growthposts` queues the posts 10 and 2 days before; the story waits for story publishing.
23. **The leader pack and the badge files are not on disk.** `Claude Design/export/leader-pack/` did not exist on 20 Oct (`export/` holds `social` and `src-social`; `Ahavah Leader Pack.html` is in the project but not exported). Default: `/invite-ahavah` hides "Download the leader pack (PDF)" (`LEADER_PACK_URL = null`) and the badge is drawn in code from the social set's `BADGE`. Both follow a `/handoff`.
24. **The shared frame's "Questions"** on `/events`, `/e/{slug}` and `/invite-ahavah` need answers written by the owner (`p11-mk.js` `PAGES`). Default: not built until he writes them, as with Together.
25. **The event post caption** is not designed. Default: Task 5's line; Instagram's carries no link, Facebook's gets the tagged link.
26. **"Ahavah will be there".** Default: the admin's toggle on any published gathering, on by default for Ahavah's own.
27. **The organiser terms** (growth spec: "Terms gain an organiser section"). Default: a draft in Task 24, shown only once he approves it; public hosting opens only after.
28. **Turnstile** ("Turnstile once keys exist") is not used: bot protection is free only (owner, 13 Oct), as for Together.
29. **Routes beyond the spec's list**: `GET /events/status`, `POST /events/{slug}/view`, `GET /events/countries`, `GET /rsvp/{token}`, `GET /rsvp/me`, `GET /rsvp/{token}/calendar.ics`, `POST /organisers/link`, the `/organiser/...` routes and the `/admin/events/...` routes. The spec's `GET /rsvp/confirm/{token}` stays, called by the web page's script; no email links to it, so a mail scanner opening a link confirms nothing.
30. **The outbox gains a third recipient**, `email_outbox.organiser_id` (0071), since an organiser is neither a member nor a lead and the spec puts every event email through the outbox.
31. **Columns beyond the spec's data list**: `event.tz_label`, `region`, `online_url`, `show_going`, `feast`, `flag_reason`, `paused_at`, `ahavah_attending`, `cancel_note`, `changed_at`, `change_before`, `change_after`, `published_at`, `cancelled_at`, `updated_at`; `event_rsvp.normalized_email`, `token_hash`, `confirm_by`, `lead_id`, `new_address`, `attended_at`, `resends`, `digested_at`, `cancelled_at`, `erased_at`; `organiser.normalized_email`, `city`, `country`, `about`, `revoked_at`; `ahavah_invite_request.notes`, `updated_at`; and the tables `organiser_link` and `event_view_day`.
32. **Credit for a post click.** A click on an event post is first-touch `utm:facebook/event`, not `event:{slug}`, so the spec's "sign-ups with lead_source = event:*" counts guests who RSVPed, and post clicks show under tagged links. He may want post clicks credited to the gathering.
33. **The spec's rollout** (Ahavah-run first, then requests, the list, the invite page) is kept with 4 surface switches (Task 27 Steps 8 to 11), and the header links wait for both the list and the invite page.
34. **Unverified while writing this plan**: that Task 3's scam sentence scores 0.5 or more today; that Node's ICU on Vercel gives "Central Time" for `longGeneric` (Task 14 pins it; if not, `tzLabel` needs a table); that `Intl.supportedValuesOf` exists in every browser the organisers use (Task 21 falls back to the organiser's own zone and UTC); that satori draws the middle dot and the spark icon of the post card (Task 26 renders them); that the header at 768 holds 3 new links beside More (export 2.5, checked at `/sot-sync`).

## Self-review

**Spec coverage.**

| Requirement (events spec, growth spec, briefs) | Task |
|---|---|
| `organiser`, `event`, `event_rsvp`, `ahavah_invite_request` in one migration (0071) | 1 |
| A dark launch; every switch off; passed to api and cron | 2 |
| Title, date and time with zone, in person or online, description, capacity, cover, the two tags | 3, 5, 6, 21 |
| Feast days by their biblical names (option B) | 3, 16, 21 |
| `ahavah.app/e/{slug}` with a share image of title, date, place, organiser and the mark | 15, 16 |
| Date, place, organiser, description, how many are going (optional), RSVP form | 7, 16, 17 |
| RSVP with name, email and guests; one unticked box, the only marketing consent; confirm by emailed link | 8, 9, 17 |
| Add-to-calendar file, a reminder the day before, a note on change or cancellation | 8, 9, 10, 17 |
| Every confirmed RSVP a lead with `event:{slug}` | 8 |
| "Invite Ahavah": offers, the request form, requests in the admin, the leader pack when it exists | 11, 19, 25 |
| "Ahavah will be there" on approved gatherings | 11, 15, 16, 25, 26 |
| Anyone can ask to host with a verified email; approval once; later gatherings publish unless flagged | 4, 5, 11 |
| Organisers manage through a magic link; names and party sizes; emails only if shared | 4, 5, 20, 21, 22 |
| Every listed public, organiser and admin route | 2, 4, 5, 7, 8, 11 |
| Emails through the durable outbox on the brand shell; proofs before each switch | 9, 13, 27 |
| Admin Events tab: approvals, requests, per-gathering views, RSVPs, confirmed, attended, sign-ups | 11, 25 |
| Measures: RSVPs, confirmation rate, new emails, `event:*` sign-ups, women among RSVPs | 11, 25 |
| Rollout: Ahavah-run first, then requests, the list, the invite page | 2, 27 |
| Fake organisers: approval once and a flag to pull any gathering | 5, 11 |
| Safety: venue only after RSVP, safety guidance on every in-person page | 7, 8, 9, 16 |
| Spam: per-email and per-IP limits | 4, 7, 8, 11 |
| `/events` and `/e/{slug}` with schema.org `Event`; `/invite-ahavah`; titles, descriptions, images, sitemap | 15, 16, 18, 19, 23 |
| Landing "Gatherings near you"; header and footer Gatherings and For leaders | 23, 27 |
| `event` publishing kind, 10 and 2 days before, UTM tags, owner approval, rest days | 5, 26 (growthposts and the queue exist) |
| Privacy page names RSVPs; terms gain an organiser section; consent wording through ux-writing and the owner | 24, 27 |
| Admin Events tab design, bento, phone read only | 25 |
| Retention and deletion of what is stored | 12, 24 |

Not covered by design or decision, each in the list above: the 3.7 code email (13), the weekly email block (20), Moderation > Text (21), the "Today" story (22), the leader pack files (23), the Questions sections (24).

**Step scan.** Each code step names its file, signatures and the spec's values; the bodies left to the implementer are the ones the signature and tests fix. The migration and the copy are written out because they are decisions.

**Type consistency.** `organiser_for` returns the dict every `manage` function takes; `queue_confirm(tx, rsvp_id, token)` is stubbed in Task 4 and filled in Task 9 with the same signature; `post_payload`'s slot names (`event_title`, `date`, `city_or_online`, `organiser_name`, `tags`, `feast_label`, `ahavah_attending`, `slug`) are what Task 26's `EventCardData` reads; `Region` ids match `fields.REGIONS`; `tz_label` is sent by Task 21 and read by Task 3's `when_words` and Task 14's `whenLines`.

**Review Focus.** Each of the 5 lines has its test in the task named.

**Proportion.** The plan writes out the schema, the copy and the tests' assertions; the rest is signatures.
