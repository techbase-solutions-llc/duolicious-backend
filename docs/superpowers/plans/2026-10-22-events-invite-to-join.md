# Gatherings: inviting guests who are not members to join Ahavah
Linear: TEC-1845 (a follow-up to the events release; open its own issue at the start, see Task 11 Step 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner, 22 Oct 2026 (paraphrased): gatherings are a tool for Torah-observant people to organise and share events and get registration confirmations, and because they run on Ahavah, Ahavah should capture the guests as leads and try to get them to sign up once. He approved two things, and neither ever reaches someone who is already a member:

1. A short "Join Ahavah" block for non-members on the RSVP confirmed page (frames 2.10 and 2.11) and in the confirm and reminder emails (3.1 to 3.3), which are sent anyway.
2. One invitation-to-join email, the day after the gathering, only to guests who ticked the existing box "Tell me about Ahavah events and members near me", at most once per person across all gatherings, never to members and never to anyone who unsubscribed.

A guest who joins from either is credited `lead_source = event:{slug}`.

**Architecture:** One new module, `service/events/join.py`, holds the join link, who may see a block and the invitation's eligibility. The link is `{WEB_BASE_URL}/auth/sign-up?src=event%3A{slug}`. The web's sign-up page keeps that source on the device for 30 days (as Together's carry does) and `verify-email` sends it to `/check-otp` as `source`, which today accepts only the tool sources; the API learns to accept `event:{slug}` for a gathering that exists and stamps it on the new onboardee, which `finish-onboarding` already copies to `person.lead_source`. A guest who signs up with the RSVP's own address is already credited by `link_leads_to_person` (events plan Task 12); the link covers a different address. `rsvp_view` gains `rsvp.join_offer`, which the confirmed page reads. The confirm and reminder builders take an optional join block. The invitation is a new outbox campaign, `event_join_invite`, queued by an hourly job in the return-mail cron and sent to the RSVP's `event:{slug}` lead as news (`marketing=True`), so the outbox's existing news rules (confirmed address, ticked box, not unsubscribed, not suppressed) apply at queue and at send. "Once per person" is a row per normalised address in a new table, `lead_join_invite` (migration 0076), kept while Ahavah holds any lead row for that address. Two new switches, both off.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pydantic, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16, React 19, vitest and Testing Library (ahavah-web). No admin change: Admin > Events already counts sign-ups whose `lead_source` is `event:{slug}`.

**Sources:** The events plan, `docs/superpowers/plans/2026-10-21-events-release-1.md` (Task 8 RSVPs and leads, Task 9 the emails and the outbox, Task 10 rest days, Task 12 crediting a sign-up, "Spec conflicts" item 8, the confirmed page's line). The growth plan, `docs/superpowers/plans/2026-10-16-growth-foundations.md` (the lead table, sources and news consent). Code read on 22 Oct: `service/events/rsvp.py`, `mail.py`, `jobs.py`, `retention.py`, `__init__.py`; `service/leads/__init__.py`, `sources.py`; `service/campaigns/outbox.py` (`enqueue_for_lead`, `_refusal`), `switches.py`, `held.py`; `service/spotlight/restdays.py`; `service/person/__init__.py` (the `/check-otp` source, `finish-onboarding`) and `attribution.py`; `duotypes/__init__.py` (`PostCheckOtp`); `emails/base.py`; `tests/email_samples.py`; `scripts/send_event_proofs.py`; ahavah-web `src/components/events/rsvp-status.tsx`, `src/lib/events/copy.ts`, `src/lib/events/api.ts`, `src/app/auth/sign-up/page.tsx`, `src/app/onboarding/verify-email/page.tsx`, `src/lib/auth-otp.ts`, `src/lib/together/carry.ts`, `src/lib/first-touch.ts`, `src/lib/legal-events-copy.ts`, `src/lib/legal-leads-copy.ts`. Designed frames: `ahavah-web/Claude Design/Ahavah Events.html` (`pages/p10-events.js`, frames 2.10 and 2.11), `Ahavah Events Emails.html` (`pages/p10-emails.js`, frames 3.1 to 3.3), copy `handoff/copy/10-events.md` and `10-events-emails.md`; title recipe `Ahavah Email Titles for Phones.html`.

## What the design covers, and what it does not

- **Nothing here is designed yet.** Frames 2.10 and 2.11 carry "one quiet line" (owner decision 8 of the events plan: "Ahavah is matchmaking for Torah-observant believers who hope to marry." and "See how it works"). Frames 3.1 to 3.3 carry no word about joining. There is no frame for an invitation email. So all three come from a brief first (Task 1), and the web and email markup waits for the handoff.
- **The `/invite-ahavah` page ("For leaders") was removed from the web on 22 Oct** (ahavah-web 0ae5e55). It plays no part here. The API's `events_invite` switch and `POST /invite-ahavah` are left as they are; tidying them is not in this plan.

## Before you start

- ahavah-api: branch `events-invite-to-join` from `ahavah/main` (it holds the merged events release). ahavah-web: branch `events-invite-to-join` from `master`. Use superpowers:using-git-worktrees. `service/campaigns/switches.py`, `docker-compose.production.yml`, `tests/conftest.py`, `tests/email_samples.py` and `service/cron/returnmail/__init__.py` are edited by other branches too (the gatherings-in-member-emails plan among them): on a rebase keep every side's lines.
- Migration number: **0076**. `migrations/` ends at `0075_admin_community.sql` on 22 Oct and no worktree holds a later one. Check `ls migrations .worktrees/*/migrations` before writing it and take the next free number if that has changed.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. The database is the shared `ahavah-api-postgres-1`; never remove, reset or recreate it or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Web tests: `cd /d/Antigravity/ahavah-web && npx vitest run <file>`. Read `ahavah-web/AGENTS.md` first (Next 16).
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845` (or the new issue once opened), no attribution trailers. Never push until Task 11 says so, and then only with the owner's go.
- The `events_live` fixture in `tests/conftest.py` turns on every variable in `_EVENT_SWITCH_VARS`. Do **not** add the 2 new switches to that list: existing tests would then see join blocks they do not expect. New tests set the new variables themselves.
- Line numbers are hints measured on 22 Oct. Trust the code over the number.

## Global Constraints

Every task's requirements include these.

- **Members never.** No block, no flag and no invitation for an RSVP with `person_id`, or whose normalised address belongs to a `person` at the moment of building, queueing or sending. The outbox refuses the invitation at send time as `member_now` if the address has joined since it was queued.
- **Consent.** The block needs no consent: it sits in emails and on a page the guest asked for. The invitation is news: it goes only to a lead whose RSVP for that gathering ticked the box (`event_rsvp.marketing_consent`) and which `service.leads.news_refusal` passes (address confirmed, consent recorded, not unsubscribed), checked at queue and again at send. A lead who has left the news mail sees no block either (Owner decision 7).
- **Once.** At most one invitation per normalised address, across all gatherings, enforced by the primary key of `lead_join_invite` in the same transaction as the queue.
- **Display type.** Email titles are pre-rendered title images through `emails.base.title_image()`, never typed headlines; `tests/test_email_renders_on_a_phone.py` rejects `<h1>` to `<h4>` and any type of 20 px or more. The blocks are body-size; any display type Task 1 returns is an image.
- **Samples and the phone check.** Every new email state gets a row in `tests/email_samples.py`.
- **Switches.** `events_join_block` (the page flag and both email blocks) and `events_join_invite_email` (the invitation), each in `service/campaigns/switches.py`, off unless its variable is 1, true, yes or on, passed through as `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}` in both the api and the cron blocks of `docker-compose.production.yml`, each counting only while `events_live` is on (`service.events.switch_on`). The drain re-reads the invitation's switch at send time through `CAMPAIGN_SWITCHES`.
- **Proofs.** To `scripts/send_proofs.PROOF_TO` only, through `scripts/send_event_proofs.py`, never the outbox, sample data only, every token and unsubscribe link inert, no switch read or changed. No switch flips before the owner confirms the proofs.
- **Rest days.** `service/spotlight/restdays.py` is known only to 9 Nov 2026 (`KNOWN_THROUGH`). The invitation is never queued inside a rest period, nor in the 2 hours before one starts, nor at any moment beyond `KNOWN_THROUGH`; it waits and goes at the first allowed hour inside its window. The join block is left out of any confirm or reminder email built inside a rest period or beyond `KNOWN_THROUGH` (the email itself still goes, as today). **After 9 Nov, until the owner's calendar is re-read and both `restdays.py` and `ahavah-admin/src/lib/rest-days.ts` are extended, no invitation is queued and no email carries the block; an invitation whose 7 day window closes in that time is never sent.** This plan edits neither file. The confirmed page is not mail and shows its block on any day.
- **Copy.** Sentence case, British spelling, no em dashes, digits for numbers, no serial comma. Never "dating"; never "diaspora" in an email. Torah-observant believers, never Jewish framing. Describe the service, not the reader (no "Single and looking?"). No countdowns, no urgency, no exclamation marks. Strings come from Task 1's returned copy; every line not in the export is marked `NEW LINE` (`# NEW LINE` in Python, `// NEW LINE` in TypeScript) and listed in Task 10 for `/copy-pass` and the owner. The invitation should speak about what the guest agreed to hear about: Ahavah's gatherings and members near them.
- **Privacy.** No venue, call link or other guest's detail in any block or in the invitation. Everything a guest or organiser typed (the gathering's title, the organiser's name) is escaped with `html.escape`. The sign-up link carries the gathering's slug only, never an address or a token.

## Review focus

The inputs most likely to bite first. Each has a test in the task named.

1. A guest who joined between the RSVP and the reminder, or between the invitation's queueing and its send: no block in the reminder, and the queued invitation is skipped `member_now`. Task 6, `test_no_block_once_the_address_has_joined`; Task 7, `test_an_address_that_joins_after_queueing_is_skipped`.
2. The same address at two gatherings that end on the same day, or the job running twice in one hour: one invitation. Task 7, `test_one_invitation_per_address_across_gatherings` and `test_two_ticks_queue_one`.
3. A rest period starting in the evening of the day after: nothing queued in the 2 hours before it, and the invitation goes after it ends, inside the 7 days. Task 7, `test_held_before_and_during_a_rest_period`.
4. A `src` value someone typed: `/check-otp` with `src=event:<script>` or a slug that names no gathering is ignored, never a 400 that blocks sign-up. Task 4, `test_an_unknown_or_malformed_event_source_is_ignored`; and the web never sends a value that fails the pattern, Task 9.
5. Unsubscribing from the invitation stops every later news email to that address and does not cancel the guest's place at a later gathering. Task 7, `test_unsubscribe_leaves_the_news_and_keeps_the_place`.

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `ahavah-web/docs/design-briefs/2026-10-22-events-invite-to-join.md` | Create (Task 1) | The brief, as sent |
| `service/campaigns/switches.py`, `docker-compose.production.yml`, `service/events/__init__.py` | Modify | 2 switches, their pass-throughs, `CAMPAIGN_SWITCHES['event_join_invite']` |
| `migrations/0076_lead_join_invite.sql` | Create | The once-per-address record |
| `service/events/retention.py`, `service/cron/leadretention/__init__.py` | Modify | The record goes with the address's last lead row |
| `duotypes/__init__.py`, `service/person/__init__.py`, `service/leads/sources.py` | Modify | `/check-otp` accepts `event:{slug}` |
| `service/events/join.py` | Create | The link, who sees a block, the invitation's eligibility and timing |
| `service/events/rsvp.py` | Modify | `rsvp.join_offer` in `rsvp_view` |
| `service/events/mail.py` | Modify | The block in confirm and reminder; the invitation's builder, queue and previews; `TITLES['join_invite']` |
| `service/events/jobs.py`, `service/cron/returnmail/__init__.py` | Modify | `queue_join_invites` hourly |
| `service/campaigns/outbox.py` | Modify | `member_now` for the invitation at send |
| `emails/assets/title-event-join-invite*.png` (and any image Task 1 returns), `tests/email_assets_manifest.txt` | Add, modify | Synced from `ahavah-web/public/email/` |
| `scripts/send_event_proofs.py`, `tests/test_send_event_proofs.py`, `tests/email_samples.py` | Modify | Proofs and samples |
| `tests/test_event_join_switches.py`, `tests/test_migration_0076.py`, `tests/test_event_join_credit.py`, `tests/test_event_join_block.py`, `tests/test_event_join_invite.py` | Create | One or two per task |
| `tests/test_event_rsvp.py` | Modify | The view's exact `rsvp` dict gains `join_offer` |

ahavah-web:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/events/api.ts` | Modify | `RsvpView.rsvp.join_offer` |
| `src/lib/events/join.ts` | Create | `joinHref(slug)`, the event source carry (write, read, clear), `EVENT_SOURCE` pattern |
| `src/lib/events/copy.ts` | Modify | The block's strings from Task 1 |
| `src/components/events/join-ahavah.tsx`, `src/components/events/rsvp-status.tsx` | Create, modify | The block on 2.10 and 2.11 |
| `src/app/auth/sign-up/page.tsx`, `src/app/onboarding/verify-email/page.tsx`, `src/app/onboarding/complete/page.tsx`, `src/lib/auth-otp.ts` | Modify | Keep the source, send it, clear it |
| `tests/app/rsvp-pages.test.tsx`, `tests/lib/events-join.test.ts`, `tests/app/event-join-signup.test.tsx` | Modify, create | Tests |

---

## Task 1: The Claude Design brief, then the handoff

Owner-facing; no code. The house rule: all new UI, emails included, comes from a brief into the existing Claude Design project `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`, never a new one.

- [ ] **Step 1: Save the brief** below to `ahavah-web/docs/design-briefs/2026-10-22-events-invite-to-join.md`, run its prose through `/copy-pass` (humanizer), then send it with `/brief` into project `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`. Attach `Ahavah Events.html` (frames 2.10 and 2.11), `Ahavah Events Emails.html` (frames 3.1 to 3.3), `Ahavah Email Titles for Phones.html`, `handoff/copy/10-events.md` and `handoff/copy/10-events-emails.md` as context.
- [ ] **Step 2: When it returns, `/handoff`** the frames into `ahavah-web/Claude Design/` (`pages/p10-*.js`, `handoff/copy/10-events*.md`) and the title PNGs (light and `-wht`) into `ahavah-web/public/email/`; then in ahavah-api run `./scripts/sync_email_assets.sh`, add the new files to `tests/email_assets_manifest.txt` and note each image's natural CSS width. Audit the handoff against the brief before building: every state drawn, every string listed, nothing typed at 20 px or more in an email.
- [ ] **Step 3: The owner reads the frames and every string** (Task 10 lists them). Tasks 2 to 5 may start before he does; Tasks 6, 7 and 9 build their markup only from the returned frames.
- [ ] **Step 4: Commit** the brief and the handoff in ahavah-web (`docs(design): brief and handoff for inviting gathering guests to join`), and the synced assets in ahavah-api (`feat(email): the invitation-to-join title`).

The brief's text:

```markdown
# Design brief: inviting gathering guests to join Ahavah

Date: 2026-10-22. Repo target: `ahavah-web` (`src/components/events/rsvp-status.tsx`, `public/email/`) and `ahavah-api` (`service/events/mail.py`, `emails/assets/`). Linear TEC-1845. Builds on `Ahavah Events.html` (frames 2.10 and 2.11, the confirmed page) and `Ahavah Events Emails.html` (frames 3.1 to 3.3, the confirm and reminder emails), with copy in `handoff/copy/10-events.md` and `10-events-emails.md`. Title recipe: `Ahavah Email Titles for Phones.html`. Voice: `briefs/ahavah-audience-and-voice.md`.

## Goal

Gatherings let assemblies and fellowship leaders run an event and collect RSVPs with a confirmation, without an account. Most guests are not members. The owner wants Ahavah to invite them to join once, gently, in 3 places: the page a guest sees after confirming, the emails they already get about the gathering, and one email the day after it. People who are already members never see any of it.

## Scope

1. **A "Join Ahavah" block on the confirmed page** (2.10 in person, 2.11 online), for guests who are not members. Today the page ends with one quiet line: "Ahavah is matchmaking for Torah-observant believers who hope to marry." and "See how it works". Redraw that end of the page so a guest who is not a member sees a short block: what Ahavah is, in a sentence, and a "Join Ahavah" action that goes to sign-up. It stays below "Add to calendar", "Cancel my place" and the safety note, and quieter than them: the guest came for the gathering. Keep frame 2.10 as drawn for members (the quiet line stays) and show both versions.
2. **The same block in the confirm and reminder emails** (3.1 confirm, 3.2 reminder in person, 3.3 reminder online), for guests who are not members. In 3.1, "Confirm my place" must stay the only button and the first thing the eye finds; the block sits below it, after "We share the address once you confirm.", as a text link or a quiet secondary style. In 3.2 and 3.3 it sits after "Cancel my place" and the safety note, before the footer. Body size only: no type of 20 px or more, so no new title image unless you judge one is needed, in which case draw it as an image.
3. **A new email, "Invitation to join"** (number it 3.9), sent once, the day after a gathering, to a guest who ticked "Tell me about Ahavah events and members near me" when they RSVPed. It needs a title image (Ultra 400, tracking -0.022em, line height 1.0, 2x, light PNG in #5524F5 and dark PNG in #FFFFFF, transparent, trimmed to the ink, wrapped to about 280 px as the phone titles are), a body line naming the gathering they went to (the gathering's title changes per email, so it is body text, not part of the image), a few lines on what Ahavah is and what members do (marriage and courtship among Torah-observant believers; gatherings and members near them, which is what they asked to hear about), one "Join Ahavah" button and a footer with the reason they are getting it and "Unsubscribe". Suggested title, only a suggestion: "Meet the community." The guest may not have gone in the end: do not thank them for coming or assume they attended.

## States

Page: 2.10 and 2.11, each for a guest who is not a member (with the block) and for a member (as today). Emails: 3.1 in person and online with the block; 3.2 and 3.3 with the block; 3.9 for an in-person and for an online gathering, with a long gathering title (120 characters) to show it wraps. Each at 390 first, then 600 for the emails and 768 and 1440 for the page, dark and light, with Gmail's forced dark mode noted where a title image sits. Nothing scrolls sideways at 320 or 390. Touch targets at least 44 px.

## Copy

Reuse approved strings where they fit: "Ahavah is matchmaking for Torah-observant believers who hope to marry.", "See how it works", "You are getting this because you RSVPed to a gathering on Ahavah.". Every other line is new: propose it, mark it new and list it. Sentence case. Never an em dash. British spelling. Digits for numbers. No serial comma. Marriage and courtship, never "dating". Never "diaspora". Torah-observant believers, never Jewish framing. Describe the service, not the reader: no "Single?", no "Looking for your spouse?". Warm and unhurried: no countdowns, no urgency, no exclamation marks, no figures typed in as facts (no member counts). Do not greet the guest by name: the name on an RSVP may be a family or a nickname.

## Layout

- The email shell in `emails/base.py` (600 px container, fluid on a phone). The page uses the events kit (`events.css`, `tg-*` classes) as 2.10 does.
- No typed headline in an email: nothing at 20 px or more.

## Open questions for the owner (draw the default, mark the alternative)

1. On the confirmed page, does the block replace the quiet line for guests who are not members, or sit under it? Default: replaces it.
2. Should 3.9 name the organiser ("Hosted by Grace Fellowship") as well as the gathering? Default: the gathering's title only.

## Definition of done

- 2.10 and 2.11 for a guest who is not a member, beside the member version, at 390, 768 and 1440, light and dark.
- 3.1, 3.2 and 3.3 with the block, and 3.9 in both states, at 390 and 600, light and dark.
- The 3.9 title image (and any other image you drew), light and dark PNG at 2x, exported to `export/email/` with its natural CSS width and line breaks.
- Reply with every string used, screen by screen, each new one marked.
```

## Task 2: The two switches

**Files:**
- Modify: `service/campaigns/switches.py` (after `'events_manage_email'`), `docker-compose.production.yml` (the api block after `AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED`, near line 166, and the cron block after the same, near line 382), `service/events/__init__.py`
- Test: `tests/test_event_join_switches.py` (create)

**Interfaces:**
- `SWITCHES` gains, with a comment in the file's style ("inviting gathering guests who are not members to join (TEC-1845): the block on the confirmed page and in the confirm and reminder emails, and the one invitation the day after; each off until the owner has seen its proof, each needs events_live"):
  - `'events_join_block': 'AHAVAH_EVENTS_JOIN_BLOCK_ENABLED'`
  - `'events_join_invite_email': 'AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED'`
- `docker-compose.production.yml`: `AHAVAH_EVENTS_JOIN_BLOCK_ENABLED: ${AHAVAH_EVENTS_JOIN_BLOCK_ENABLED:-0}` and `AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED: ${AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED:-0}` in both blocks. The block is read by the api (the page and the confirm email) and the cron (the reminder); the invitation is queued by the cron and drained by both.
- `service.events.CAMPAIGN_SWITCHES` gains `'event_join_invite': 'events_join_invite_email'`, so the drain's existing check (`outbox._refusal`) stops a queued invitation when the switch goes off. The block has no campaign of its own: it rides in `event_confirm` and `event_reminder` and is read when they are built.

- [ ] **Step 1: Write the failing test** `tests/test_event_join_switches.py`, in the shape of `tests/test_events_switches.py`: `test_the_switches_and_their_variables`; `test_the_compose_file_passes_each_to_the_api_and_the_cron` (each `X: ${X:-0}` exactly twice); `test_off_by_default` (`switch_on` False for both with no variable); `test_each_needs_events_live` (own variable alone: False; with `AHAVAH_EVENTS_LIVE_ENABLED`: True); `test_the_invitation_has_a_campaign_switch` (`CAMPAIGN_SWITCHES['event_join_invite'] == 'events_join_invite_email'`).
- [ ] **Step 2: Run it to verify it fails.** Expected: `KeyError` or assertion failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_events_switches.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/campaigns/switches.py docker-compose.production.yml service/events/__init__.py tests/test_event_join_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): switches for inviting guests to join, both off" -m "Refs: TEC-1845"
```

## Task 3: Migration 0076, one invitation per address

**Files:**
- Create: `migrations/0076_lead_join_invite.sql`
- Modify: `tests/conftest.py` (a `join_invite_schema` fixture after the events block, session scope, depending on `events_schema`, executing 0076 the way `events_schema` executes 0071), `service/events/retention.py`, `service/cron/leadretention/__init__.py` (`_purge_once` prints the new count)
- Test: `tests/test_migration_0076.py` (create), `tests/test_event_retention.py` (one new test)

**Interfaces:**

```sql
-- 0076_lead_join_invite.sql
-- One invitation to join per address, across all gatherings (TEC-1845,
-- docs/superpowers/plans/2026-10-22-events-invite-to-join.md). Kept while
-- Ahavah holds any lead row for the address; the lead retention sweep
-- deletes it with the last one, as the privacy page's 12 months say.
CREATE TABLE IF NOT EXISTS lead_join_invite (
  normalized_email  TEXT         PRIMARY KEY,
  event_id          BIGINT       REFERENCES event(id) ON DELETE SET NULL,
  invited_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

- `service.events.retention.purge_event_data` gains `join_invites`: `DELETE FROM lead_join_invite j WHERE NOT EXISTS (SELECT 1 FROM lead l WHERE l.normalized_email = j.normalized_email)`.

- [ ] **Step 1: Write the failing tests.** `tests/test_migration_0076.py`: `test_runs_twice`, `test_one_row_per_address` (a second insert of the same address raises `UniqueViolation`), `test_the_gathering_may_go_and_the_record_stays` (delete the event: `event_id` NULL, the row stays). In `tests/test_event_retention.py`: `test_the_invitation_record_goes_with_the_last_lead_row` (two lead rows for one address and a record; delete one lead and sweep: the record stays; delete the other and sweep: it goes).
- [ ] **Step 2: Run them to verify they fail.** Expected: `fixture 'join_invite_schema' not found`.
- [ ] **Step 3: Implement** the migration, the fixture and the sweep line.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_lead_retention.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add migrations/0076_lead_join_invite.sql tests/conftest.py service/events/retention.py service/cron/leadretention/__init__.py tests/test_migration_0076.py tests/test_event_retention.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): migration 0076, one invitation to join per address" -m "Refs: TEC-1845"
```

## Task 4: A sign-up from the join link is credited to the gathering

**Files:**
- Modify: `duotypes/__init__.py` (`PostCheckOtp.source`), `service/leads/sources.py`, `service/person/__init__.py` (the source block in `/check-otp`, near line 573)
- Test: `tests/test_event_join_credit.py` (create)

**Interfaces:**
- `PostCheckOtp.source` becomes `Optional[str] = Field(None, max_length=60)`, so a value the web did not expect is ignored, never a 400 that blocks sign-in. The tool values keep working exactly as today.
- `service.leads.sources.signup_source(value: object) -> Optional[str]`: `canonical_tool_source(value)` for a tool value; the value itself when it is `event:{slug}` with a well-formed slug (`is_lead_source`); else None.
- In `/check-otp`, `source = signup_source(req.source)`; an event source counts only when `SELECT 1 FROM event WHERE slug = %(s)s` finds the gathering (any status: a guest may join after it ended). The `UPDATE onboardee SET lead_source ... WHERE lead_source IS NULL` is unchanged and runs for both kinds. The tool lead (`record_lead` and `confirm_lead`, behind `tool_leads_enabled()`) runs **only** for a tool source: a sign-up from the join link writes no lead.
- No change to `finish-onboarding`: `Q_FINISH_ONBOARDING` already copies `onboardee.lead_source` to the person; `link_leads_to_person` and `record_attribution` keep it (`COALESCE`). So the join link's credit wins over the first touch and over an older lead of another source (Owner decision 5).

- [ ] **Step 1: Write the failing tests** `tests/test_event_join_credit.py`, using `tests/test_lead_signup.py`'s helpers for the code flow and the `published` fixture:
  - `test_a_new_member_from_the_join_link_is_credited_to_the_gathering` (request and check a code with `source=f'event:{slug}'`, finish onboarding: `person.lead_source == f'event:{slug}'`)
  - `test_a_different_address_from_the_rsvp_is_still_credited` (RSVP as a@, sign up as b@ with the source: credited)
  - `test_the_join_link_beats_the_first_touch` (`first_touch` with `utm_source=facebook`: still `event:{slug}`)
  - `test_an_existing_member_is_not_retagged`
  - `test_an_unknown_or_malformed_event_source_is_ignored` (`event:no-such-gathering`, `event:<script>`, `event:` and a 61 character value: 200, `lead_source` from the first touch or NULL)
  - `test_the_join_link_writes_no_lead` (with `AHAVAH_TOOL_LEADS_ENABLED=1`: no new `lead` row)
  - `test_the_tool_sources_still_work` (`marriage_checklist` and `tool:game-me` as today)
- [ ] **Step 2: Run them to verify they fail.** Expected: 400 from pydantic for the event value, then assertion failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_lead_signup.py`, `tests/test_onboarding_attribution.py`, `tests/test_lead_sources.py` and `tests/test_event_retention.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add duotypes/__init__.py service/leads/sources.py service/person/__init__.py tests/test_event_join_credit.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): a sign-up from a gathering's join link is credited to it" -m "Refs: TEC-1845"
```

## Task 5: The join link and who sees a block

**Files:**
- Create: `service/events/join.py`
- Modify: `service/events/rsvp.py` (`rsvp_view`), `tests/test_event_rsvp.py` (line 83's exact dict)
- Test: `tests/test_event_join_block.py` (create; Task 6 adds to it)

**Interfaces:**
- In `service.events.join`:
  - `join_url(slug: str) -> str`: `f'{WEB_BASE_URL}/auth/sign-up?src=' + quote(event_source(slug), safe='')`, so `src=event%3A{slug}`. Raises `ValueError` for a bad slug (from `event_source`).
  - `is_member_address(tx, normalized_email: Optional[str]) -> bool`.
  - `offers_join(tx, r: dict) -> bool`, for one `event_rsvp` row: `switch_on('events_join_block')`, `r['person_id'] is None`, `r['lead_id'] is not None`, not `is_member_address(tx, r['normalized_email'])`, not `lead_unsubscribed(tx, r['lead_id'])`. Mail adds the rest-day rule (`mail_block_allowed`) on top.
  - `mail_block_allowed(now: datetime) -> bool`: `not restdays.is_rest_period(now) and not restdays.is_beyond_known(now)`.
- `rsvp_view` returns `rsvp.join_offer: bool`: `offers_join(tx, r)` when the RSVP is confirmed and going, else False. The page needs nothing else: it builds the link from `event.slug`.

- [ ] **Step 1: Write the failing tests** in `tests/test_event_join_block.py`, with `events_live`, `published`, `confirmed_guest` and `make_person`:
  - `test_the_link_carries_the_gathering` (`join_url('marriage-evening-a1b2c3')` ends `/auth/sign-up?src=event%3Amarriage-evening-a1b2c3`)
  - `test_off_by_default_the_view_offers_nothing`
  - `test_a_confirmed_guest_who_is_not_a_member_is_offered` (switch on: `join_offer` True)
  - `test_a_member_is_never_offered` (a signed-in member's RSVP; and a visitor RSVP made with a member's address)
  - `test_no_offer_once_the_address_has_joined` (confirmed visitor, then a person row for the address)
  - `test_no_offer_to_an_address_that_left_the_news` (lead `unsubscribed_at` set)
  - `test_no_offer_before_confirming_or_after_cancelling`
  Change `tests/test_event_rsvp.py` line 83's expected dict to include `join_offer=False`.
- [ ] **Step 2: Run them to verify they fail.** Expected: `ModuleNotFoundError: service.events.join`.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_event_rsvp.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/join.py service/events/rsvp.py tests/test_event_join_block.py tests/test_event_rsvp.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the join link and the confirmed page's offer, for guests who are not members" -m "Refs: TEC-1845"
```

## Task 6: The block in the confirm and reminder emails

Markup from Task 1's frames 3.1 to 3.3. Until the handoff, build against the brief's placement with placeholder strings marked `NEW LINE` and keep the switch off.

**Files:**
- Modify: `service/events/mail.py`
- Test: `tests/test_event_join_block.py`

**Interfaces:**
- `join_block(url: str) -> str`: the returned block, body size, no `<h1>` to `<h4>`, nothing at 20 px or more; its link `_e(url)`.
- `confirm_email(view, token, *, join_url: Optional[str] = None)` and `reminder_email(view, token, *, join_url: Optional[str] = None)`: the block where the frames put it when `join_url` is given; without it each email is byte for byte as it was.
- `_join_url_for(tx, r: dict, now: datetime) -> Optional[str]`: `join.join_url(slug)` when `join.offers_join(tx, r)` and `join.mail_block_allowed(now)`, else None. `queue_confirm` and `queue_reminder` call it and pass the result. `offers_join` does not look at `confirmed_at` (Task 5 keeps that condition in `rsvp_view`), so it serves the confirm email, which is built before the RSVP is confirmed.
- `preview_confirm_join`, `preview_confirm_online_join`, `preview_reminder_join`, `preview_reminder_online_join` (`to -> (subject, html)`), sample data only, the link built from the sample slug.

- [ ] **Step 1: Write the failing tests** in `tests/test_event_join_block.py`, with `outbox_rows`:
  - `test_off_the_confirm_and_reminder_are_unchanged` (switch off: queued HTML has no `/auth/sign-up`)
  - `test_on_a_visitors_confirm_email_carries_the_block_below_the_button` (`/auth/sign-up?src=event%3A{slug}` present and after `Confirm my place` in the HTML)
  - `test_on_the_reminder_carries_it_for_a_visitor`
  - `test_a_member_guest_gets_no_block` (both emails)
  - `test_no_block_once_the_address_has_joined` (confirmed visitor, person row created, reminder job: no block)
  - `test_no_block_inside_a_rest_period_or_beyond_the_calendar` (set `REST_DAYS` as `tests/test_event_jobs.py` does and build the confirm email inside it; then a `now` after `KNOWN_THROUGH`: the email is queued, without the block)
  - `test_the_block_carries_no_venue_and_escapes_the_title` (title `<b>x</b> & "y"`: escaped; no venue string)
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces and the frames.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_event_mail.py`, `tests/test_event_jobs.py` and `tests/test_event_emails_outbox.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/mail.py tests/test_event_join_block.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the join block in the confirm and reminder emails, behind its switch" -m "Refs: TEC-1845"
```

## Task 7: The invitation to join, the day after

Markup from Task 1's frame 3.9.

**Files:**
- Modify: `service/events/join.py`, `service/events/mail.py`, `service/events/jobs.py`, `service/cron/returnmail/__init__.py` (`JOBS`, after `event_digest`), `service/campaigns/outbox.py` (`_refusal`)
- Test: `tests/test_event_join_invite.py` (create)

**Interfaces:**
- `service.events.mail`:
  - `CAMPAIGN_JOIN_INVITE = 'event_join_invite'`; `TITLES['join_invite'] = ('title-event-join-invite', <alt from Task 1>, <width from Task 1>)`.
  - `join_invite_email(event: dict, join_url: str, unsubscribe_url: str) -> tuple[str, str]`: the title image, the gathering's title (escaped) as a body line, the lines from 3.9, one `button('Join Ahavah', join_url)` (or the returned label) and `held.footer(<reason from 3.9>, unsubscribe_url)`. Subject from Task 1 (`NEW LINE`). No organiser name unless the owner chose it (brief question 2). No guest name.
  - `queue_join_invite(tx, rsvp: dict, event: dict, now: datetime) -> Optional[int]`, behind a savepoint (`_guarded`): returns None unless all of these hold, in this order: `_on(CAMPAIGN_JOIN_INVITE)`; `rsvp['marketing_consent']`; `rsvp['lead_id']` and no `person_id`; not `join.is_member_address`; not `is_suppressed_send(rsvp['email'])`; `news_refusal(tx, rsvp['lead_id']) is None`. Then `INSERT INTO lead_join_invite (normalized_email, event_id) VALUES (...) ON CONFLICT DO NOTHING RETURNING normalized_email`; no row means this address was invited before, so return None. Then `outbox.enqueue_for_lead(campaign=CAMPAIGN_JOIN_INVITE, campaign_id=str(event['id']), lead_id=rsvp['lead_id'], email=rsvp['email'], subject, html, from_addr=FROM_ADDR, list_unsubscribe=held.list_unsubscribe(unsub), marketing=True)` with `unsub = make_url('news', rsvp['email'], WEB_BASE_URL)`; if it returns None, raise inside the savepoint so the record is rolled back with it.
  - `preview_join_invite(to)` and `preview_join_invite_online(to)`, sample data only.
- `service.events.join`:
  - `INVITE_HOURS = (10, 20)`: local hours in the gathering's own zone (`event.tz`).
  - `INVITE_WINDOW = timedelta(days=7)` after `ends_at`.
  - `REST_MARGIN = timedelta(hours=2)`.
  - `invite_due(ends_at: datetime, tz: str, now: datetime) -> bool`: the local date of `now` is after the local date of `ends_at`; the local hour is in `INVITE_HOURS`; `now < ends_at + INVITE_WINDOW`; and none of `is_rest_period(now)`, `is_rest_period(now + REST_MARGIN)`, `is_beyond_known(now + REST_MARGIN)`.
- `service.events.jobs.queue_join_invites(tx, now) -> int`: nothing unless the switch is on. Reads gatherings with `status = 'published'`, `paused_at IS NULL`, `ends_at <= now` and `ends_at > now - INVITE_WINDOW`; for each where `invite_due`, its RSVPs with `status = 'going'`, `confirmed_at IS NOT NULL`, `erased_at IS NULL`, `marketing_consent`, `person_id IS NULL` and `lead_id IS NOT NULL`, ordered by id; calls `queue_join_invite` for each. A gathering that was cancelled sends none.
- `JOBS` gains `('event_join_invite', event_jobs.queue_join_invites)`.
- `outbox._refusal`, in the lead branch before the news check: `if row['campaign'] == 'event_join_invite' and _is_member_address(tx, row['email']): return 'member_now'`.

- [ ] **Step 1: Write the failing tests** `tests/test_event_join_invite.py`, with `events_live`, `published`, `confirmed_guest`, `outbox_rows`, `outbox_drain` and `make_person`, setting `AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED` per test:
  - `test_off_by_default_nothing_is_queued`
  - `test_the_day_after_in_the_gatherings_own_time` (a Dallas gathering ending Saturday 22:00 Central: nothing on Sunday 09:00 Central, one at Sunday 10:00 Central, none at 11:00)
  - `test_only_guests_who_ticked_the_box` (two confirmed guests, one ticked: one row)
  - `test_never_a_member` (a member RSVP; a visitor RSVP whose address belongs to a person)
  - `test_never_an_unsubscribed_or_suppressed_address`
  - `test_never_an_unconfirmed_or_cancelled_guest_nor_a_cancelled_or_paused_gathering`
  - `test_one_invitation_per_address_across_gatherings` (the same address ticked at two gatherings ending the same day, and again a week later: one row in all)
  - `test_two_ticks_queue_one`
  - `test_held_before_and_during_a_rest_period` (a rest period from 17:00 Barbados time on the day after: nothing at 15:30 Barbados time, nothing inside it, one at the first allowed hour after it, inside the 7 days)
  - `test_nothing_beyond_the_known_calendar` (`now` after `KNOWN_THROUGH`: nothing queued, no `lead_join_invite` row)
  - `test_lapsed_after_7_days`
  - `test_it_is_news_with_an_unsubscribe_and_list_unsubscribe` (`exempt` False, `unsub_scope` 'news', `payload['list_unsubscribe']` holds the `/u/` link, the HTML holds the same link and `src=event%3A{slug}`)
  - `test_an_address_that_joins_after_queueing_is_skipped` (queue, create the person, drain: `skipped`, `last_error` 'member_now')
  - `test_switching_off_stops_what_is_queued` (queue, unset the variable, drain: `switched_off`)
  - `test_unsubscribe_leaves_the_news_and_keeps_the_place` (stamp 'news' through `service.unsubscribe`; a later `queue_join_invite` for another gathering refuses; the guest's reminder at another gathering is still queued)
  - `test_the_title_is_escaped_and_no_venue_or_name_appears`
  - `test_the_job_is_in_the_return_mail_cron`
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces and frame 3.9.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_event_jobs.py`, `tests/test_email_outbox.py`, `tests/test_email_outbox_cron.py` and `tests/test_event_emails_outbox.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/join.py service/events/mail.py service/events/jobs.py service/cron/returnmail/__init__.py service/campaigns/outbox.py tests/test_event_join_invite.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): one invitation to join, the day after, to guests who asked for news" -m "Refs: TEC-1845"
```

## Task 8: The samples, the phone check and the proofs

**Files:**
- Modify: `tests/email_samples.py` (section 8b, the gatherings loop), `scripts/send_event_proofs.py`, `tests/test_send_event_proofs.py`

**Interfaces:**
- `tests/email_samples.py`, 6 rows in the 8b loop, each `sent_now` `'HELD: AHAVAH_EVENTS_LIVE_ENABLED + <switch>, off until launch'`: `event_confirm_join`, `event_confirm_online_join`, `event_reminder_join`, `event_reminder_online_join` (audience `lead`, `AHAVAH_EVENTS_JOIN_BLOCK_ENABLED`), `event_join_invite`, `event_join_invite_online` (audience `lead`, `AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED`).
- `scripts/send_event_proofs.py` `plan()` gains the same 6, after `event_live`, labelled "Confirm your place with the join block (3.1)", "... online", "Reminder with the join block (3.2)", "... online (3.3)", "Invitation to join (3.9)", "Invitation to join, online gathering". `_inert_event_links` also replaces `{WEB_BASE_URL}/auth/sign-up?src=...` with `PROOF_LINK_DISABLED`, so a proof click credits nothing. `missing_titles()` already reads `TITLES`, so the send refuses while `title-event-join-invite` is missing.
- `tests/test_send_event_proofs.py`: the expected list grows from 10 to 16; `test_the_join_links_are_inert`.

- [ ] **Step 1: Add the rows and the proof changes**, then run `tests/test_email_renders_on_a_phone.py` and `tests/test_send_event_proofs.py`. Expected: all pass, including `test_no_typed_headlines` and `test_nothing_is_wider_than_a_phone` for each new row.
- [ ] **Step 2: Run the whole API suite**: `tests/run.sh -q -p no:warnings`. Expected: all pass.
- [ ] **Step 3: Commit**

```bash
git add tests/email_samples.py scripts/send_event_proofs.py tests/test_send_event_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "test(events): the join emails in the phone check, and their proofs to the owner" -m "Refs: TEC-1845"
```

## Task 9: The web: the block on the confirmed page and the join link's credit

Markup from Task 1's frames 2.10 and 2.11, transcribed with `/sot-sync` once the tests pass, at 390 first, then 768 and 1440, dark and light, checked at 320 and 390 for sideways scroll.

**Files:**
- Create: `src/lib/events/join.ts`, `src/components/events/join-ahavah.tsx`
- Modify: `src/lib/events/api.ts`, `src/lib/events/copy.ts`, `src/components/events/rsvp-status.tsx`, `src/app/auth/sign-up/page.tsx`, `src/app/onboarding/verify-email/page.tsx`, `src/app/onboarding/complete/page.tsx`, `src/lib/auth-otp.ts`
- Test: `tests/lib/events-join.test.ts`, `tests/app/event-join-signup.test.tsx` (create); `tests/app/rsvp-pages.test.tsx` (modify)

**Interfaces:**
- `api.ts`: `RsvpView.rsvp` gains `join_offer?: boolean` (optional, so an API deployed before this reads as no offer).
- `join.ts`: `EVENT_SOURCE = /^event:[a-z0-9]+(?:-[a-z0-9]+)*$/` with a 51 character cap (`event:` plus the API's 45); `joinHref(slug) => "/auth/sign-up?src=" + encodeURIComponent("event:" + slug)`; `writeEventSource(value, now)` (stores `{source, at}` under `ahavah.events.join.v1` only when the value passes the pattern), `readEventSource(now)` (null after 30 days or when unreadable), `clearEventSource()`. Every storage call wrapped in try/catch, as `together/carry.ts` does.
- `copy.ts`: the block's strings under `"2.10"` (`joinTitle`, `joinBody`, `joinAction` or whatever Task 1 names), each `// NEW LINE`.
- `join-ahavah.tsx`: the block from the frame, its action a `Link` to `joinHref(slug)`.
- `rsvp-status.tsx` `YouAreGoing`: when `view.rsvp.join_offer`, render `JoinAhavah` where the frame puts it (by default in place of the quiet line, brief question 1); otherwise the quiet line as today.
- `sign-up/page.tsx`: after mount, `writeEventSource(new URLSearchParams(location.search).get("src"))`. No visible change to the page.
- `auth-otp.ts`: `checkOtp`'s `source` type gains `` `event:${string}` ``.
- `verify-email/page.tsx`: `const source = carriedSource() ?? readEventSource();` (a Together carry, when present, came from a tool the visitor used on purpose and keeps its credit).
- `onboarding/complete/page.tsx`: `clearEventSource()` beside `clearCarry()`.
- Order matters: the web must not send an event source before the API from Task 4 is live, or `/check-otp` answers 400 under the old type. Task 11 ships the API first.

- [ ] **Step 1: Write the failing tests.** `tests/lib/events-join.test.ts`: `builds the link with the source encoded`; `keeps a well-formed source for 30 days`; `ignores a malformed source` (`event:<b>`, `event:`, `tool:game-me`, 52 characters); `survives blocked storage`. `tests/app/rsvp-pages.test.tsx`: `shows the join block when the API offers it` (link `href` `/auth/sign-up?src=event%3A{slug}`), `shows the quiet line and no block for a member`, `shows no block when the field is missing`. `tests/app/event-join-signup.test.tsx`: `the sign-up page keeps the source from the link`; `verify-email sends the event source`; `a Together carry wins over an event source`; `onboarding complete clears it`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces, then `/sot-sync` frames 2.10 and 2.11 (both versions) for the markup.
- [ ] **Step 4: Run them to verify they pass**, with `tests/app/together-carry-onboarding.test.tsx`, `tests/app/sign-up-honeypot.test.tsx` and `tests/components/first-touch-capture.test.tsx`; then `npx vitest run` and `npx tsc --noEmit`. Expected: all pass.
- [ ] **Step 5: Check the rendered page** at 320, 390, 768 and 1440, dark and light, against the frames, with a test RSVP whose view has `join_offer` true and one with false.
- [ ] **Step 6: Commit**

```bash
git add src/lib/events/join.ts src/components/events/join-ahavah.tsx src/lib/events/api.ts src/lib/events/copy.ts src/components/events/rsvp-status.tsx src/app/auth/sign-up/page.tsx src/app/onboarding/verify-email/page.tsx src/app/onboarding/complete/page.tsx src/lib/auth-otp.ts tests/lib/events-join.test.ts tests/app/event-join-signup.test.tsx tests/app/rsvp-pages.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the join block on the confirmed page and the join link's credit" -m "Refs: TEC-1845"
```

## Task 10: The new lines, through /copy-pass and the owner

Owner-facing; no code unless he changes a line.

- [ ] **Step 1: Run `/copy-pass`** on every line marked `NEW LINE` and every new string Task 1 returned: ux-writing for the page block, humanizer for the email block and the invitation (subject, title, body lines, button, footer reason). Reused approved lines are listed but not rewritten.
- [ ] **Step 2: Check each line by hand** against the copy rules (no em dash, no serial comma, sentence case, British spelling, never "dating", never "diaspora", no exclamation marks, describes the service not the reader, does not assume the guest attended), then run `node ~/.claude/skills/avoid-ai-writing/bin/avoid-ai-writing-gate.js --threshold 6 <scratch file of the lines>`.
- [ ] **Step 3: Privacy check, no change expected.** The events paragraph (`ahavah-web/src/lib/legal-events-copy.ts`) already says the email is used "for news only if you ticked 'Tell me about Ahavah events and members near me'", and the leads paragraph (`legal-leads-copy.ts`) says "If you later join, we note which of these brought you". The `lead_join_invite` record lives no longer than the address's lead rows (12 months after the last visit). Confirm both paragraphs still read true; if the owner chooses Owner decision 2's alternative, a privacy line is needed and goes through the same pass.
- [ ] **Step 4: Hand him the list** with the "Owner decisions" below. His changes go into Tasks 6, 7 and 9 and their tests, committed as `fix(events): the owner's wording for the join block and the invitation`.

## Task 11: The launch, in order

Operational. Each step names who acts. Nothing reaches a guest before the owner confirms its proof.

- [ ] **Step 1: Ship the API, dark.** With the owner's go, merge to `ahavah/main`; the push deploys and `scripts/apply-deploy-migrations.sh` applies 0076. Both new switches are `0`. Check that `GET /rsvp/<a test token>` returns `"join_offer": false` and that a code check with `source=event:<a real slug>` succeeds.
- [ ] **Step 2: Ship the web.** Only after Step 1 is live (Task 9's order note). With both switches off the page shows no block, and the sign-up page only keeps a `src` when one arrives.
- [ ] **Step 3: Proofs to the owner.** Inside the api container: `python -m scripts.send_event_proofs` (dry run: 16 listed, no missing title), then `python -m scripts.send_event_proofs --send`. He checks the 6 new ones at 390 and 600, light and dark, Gmail's forced dark mode included, and reads every line.
- [ ] **Step 4: Check the calendar before any switch.** `restdays.KNOWN_THROUGH` is 9 Nov 2026. Past it, the switches do nothing visible in mail (no block, no invitation) until the owner's calendar is re-read and `restdays.py` and `rest-days.ts` are extended (their own change, not this plan's). Tell him so when he is asked to switch on.
- [ ] **Step 5: Switch on, after he confirms the proofs.** In the production environment `docker-compose.production.yml` reads, for both api and cron, then restart both: `AHAVAH_EVENTS_JOIN_BLOCK_ENABLED=1`; later, or together if he says so, `AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED=1`.
- [ ] **Step 6: A real check.** RSVP to a test gathering from a fresh address with the box ticked, confirm on a phone: the block shows on the confirmed page and in the confirm email; tap "Join Ahavah" and sign up with a second fresh address: Admin > Events shows 1 sign-up for that gathering. After the test gathering ends, the invitation arrives the next day in the allowed hours, with a working unsubscribe link. Repeat with a member's address: no block, no invitation.
- [ ] **Step 7: If anything is wrong**, set the switch back to `0` and restart: queued invitations are skipped `switched_off` at send; confirm and reminder emails already queued keep the block they were built with. Linear: open the issue for this follow-up at the start, move it as tasks land and run `/linear-sync` before the session's final commit.

---

## Owner decisions

Each has the default this plan builds. He may change any of them.

1. **Who gets the invitation among the guests.** Default: every confirmed guest who did not cancel and ticked the box, whether or not the organiser marked attendance (few organisers will). The alternative is only guests marked as attended when the organiser marked anyone.
2. **What "once ever" means.** Default: once per address for as long as Ahavah holds any record of that address, which the privacy page limits to 12 months after the last visit; after that a returning guest is a new guest. The alternative is a permanent record (a hash of the address kept forever), which needs a new line on the privacy page.
3. **When the invitation goes.** Default: the gathering's local day after it ends, between 10:00 and 20:00 gathering time, at the first hour not inside or within 2 hours of a rest period, and no later than 7 days after it ends; if no such hour comes in 7 days it is not sent.
4. **After 9 Nov 2026.** The rest-day calendar is known only to 9 Nov. Default: beyond that date no invitation is queued and no confirm or reminder email carries the block, until he has the calendar re-read and both rest-day files extended; invitations whose 7 days pass in that time are lost. The confirm and reminder emails themselves keep going, as today. The alternative (treating unknown days as free) goes against the rest-day rule and is not recommended.
5. **Which credit wins.** Default: a sign-up through a gathering's join link is credited `event:{slug}` even when the person first came from an ad or tagged link (`utm:...`) or an earlier tool, and even when they sign up with an address other than the RSVP's, for 30 days on that device. A Together carry on the same device still wins over it. The alternative is "first touch wins", as the rest of attribution does, which would credit many of these guests to the post that brought them.
6. **Members' confirmed page.** Default: unchanged for members (the quiet line and "See how it works"); guests who are not members see the join block in its place. The alternative is no line at all for members.
7. **Guests who left the news mail.** He asked that the invitation never reach anyone who unsubscribed. Default: the block is also left out of their confirm and reminder emails and their confirmed page.
8. **One switch for the page and the email blocks.** Default: one (`events_join_block`), turned on after he has seen the email proofs and the page. The alternative is a separate switch for the page so it can go first.
9. **The block in the confirm email.** He approved it. Design keeps "Confirm my place" the only button; the block is a quiet line below it (brief scope 2). Noted so he sees it in the proof: the confirm email goes to an address not yet proved.
10. **Naming the organiser in the invitation.** Default: the gathering's title only (brief question 2).
11. **Which surface brought the sign-up.** Default: not measured; Admin > Events counts sign-ups per gathering, not whether they came from the page, the confirm email, the reminder or the invitation. Adding that needs a new field carried through sign-up.

## Self-review

**Coverage.**

| Requirement | Task |
|---|---|
| Join block for non-members on the confirmed page | 1, 5, 9 |
| Join block for non-members in the confirm and reminder emails | 1, 6 |
| One invitation the day after, only to those who ticked the box | 1, 7 |
| At most once per person across all gatherings | 3, 7, decision 2 |
| Never to members; never to anyone who unsubscribed | 5, 6, 7, decision 7 |
| Sign-up credited `event:{slug}` through the link | 4, 9, decision 5 |
| All new UI from a Claude Design brief into bd2e1ca9-f678-4567-a6eb-79afd75b2ef7 | 1 |
| Email titles only as title images; samples and the phone check | 1, 7, 8 |
| Switches default 0, through compose for api and cron | 2 |
| Proofs to PROOF_TO only before switching on | 8, 11 |
| Rest days respected, known only to 9 Nov, and what happens after | Global Constraints, 7, decision 4 |
| Unsubscribe link and List-Unsubscribe on the invitation | 7 |
| Copy rules and new lines through /copy-pass | 10 |

**Unverified while writing this plan:** the exact wording, title and widths (Task 1 returns them); whether `events_live` is on in production today (the owner's note of 22 Oct says gatherings went live; the production `.env` is not readable from the repo); that no other branch has taken migration 0076 by the time this starts (Before you start); how often the outbox drain runs, which is why the invitation keeps a 2 hour margin before a rest period rather than relying on the drain.

## Build notes (Tasks 2 to 5)

Built 22 Oct 2026 on branch `events-invite-to-join` (from `origin/ahavah/main`; the local `ahavah/main` ref was 346 commits behind and had no `service/events/`). Each owner decision was built to its stated default; this is where a different answer would go.

- Decision 2 (once while any lead row exists): `migrations/0076_lead_join_invite.sql` keys on `normalized_email`; `service/events/retention.py` `_Q_JOIN_INVITES` deletes the record once no `lead` row has the address (run after the lead sweep in `service/cron/leadretention`). A permanent record would drop that query and hash the address instead.
- Decision 5 (the join link wins, 30 days on the device): `service/person/__init__.py` `/check-otp` stamps `event:{slug}` on a new onboardee with `lead_source IS NULL`, so it beats the first touch and an older lead's source at finish-onboarding (`COALESCE`). "First touch wins" would mean not stamping it here. The 30 days live in the web (`src/lib/events/join.ts`); a Together carry wins there (`verify-email`).
- Decision 7 (no block for an address that left the news): `service/events/join.py` `offers_join` checks `lead_unsubscribed` and, since the review of 23 Oct, `address_unsubscribed`. One condition to remove.
- Decision 8 (one switch for the page and both email blocks): `events_join_block` is read by `offers_join`, which the page flag and the email blocks share. A separate page switch would be a second name in `SWITCHES` and a second check in `rsvp_view`.
- Decisions 3 and 4 (10:00 to 20:00 gathering time, 2 hours before a rest period, 7 days, nothing past `KNOWN_THROUGH`): `service/events/join.py` `INVITE_HOURS`, `REST_MARGIN`, `INVITE_WINDOW`, `invite_due`, and `mail_block_allowed` for the email block. (Task 7.)
- Decision 1 (every confirmed guest who ticked the box, attendance ignored): `service/events/jobs.py` `queue_join_invites` does not read `attended_at`. (Task 7.)
- Decisions 6 and 10: members keep the quiet line (web `rsvp-status.tsx`); the invitation names the gathering only (`mail.join_invite_line`).
- Decisions 9 and 11 need no code.

Rulings on the plan:

- Task 4 says `PostCheckOtp.source` is `Field(None, max_length=60)` and that a 61 character value answers 200. A plain `max_length` answers 400, so a `mode='before'` validator turns any value that is not a string of at most 60 characters into None. The cap and the "never a 400" both hold.
- That change makes `tests/test_lead_signup.py::test_an_unknown_source_is_refused` (a 400 for `tool:roulette`) wrong by design; it is now `test_an_unknown_source_is_ignored` (200, no lead).
- The `join_invite_schema` fixture is session-scoped and autouse (the plan did not say autouse): `purge_event_data` now reads `lead_join_invite`, and `tests/test_tool_retention.py` runs the whole sweep without asking for the gathering tables.
- The email block is 15 px, not the frame's 14.5: the phone type scale in `emails.base` reads whole pixels only. The handoff gives no subject for 3.9; `An invitation to join Ahavah` is marked `NEW LINE` for Task 10.

## Owner's answer (22 Oct 2026)

Asked directly: "Should I build to every suggested answer in all three plans: the 8 in-app decisions, the 11 for inviting gathering guests to join and the 13 for gatherings in the emails?" He chose "Yes, all suggestions". Build to every suggested default here; any he later changes is applied then. He also approved deploying the member sign-out fix once its tests and build pass.

## Review fixes (23 Oct 2026)

- Leaving the news is read for the address, not the one lead row. The news unsubscribe stamps the rows an address has at that moment, and a later gathering's RSVP makes a fresh `event:{slug}` row without the stamp. `service.leads.address_unsubscribed` refuses when any lead row of the normalised address has `unsubscribed_at`; `join.offers_join`, `mail.queue_join_invite` and the outbox's `event_join_invite` branch all read it. A tick that resubscribes one row does not lift it while an older row keeps its stamp, which errs towards not mailing.
- The drain reads the rest days and the 7 days again for `event_join_invite`. Past `ends_at + INVITE_WINDOW` it is skipped `lapsed` (the address keeps its record). Inside a rest period it is held, not dropped: back to `queued` with `last_error` 'rest_day', no attempt spent, until the first whole hour of the gathering's zone at which `invite_due` would queue it, never past the window. Past `KNOWN_THROUGH` it is held as 'unknown' an hour at a time, so a calendar extended inside the 7 days lets it go. `join.invite_hold`, `outbox._hold`, `outbox.mark_held`; `drain` reports `held`.
- The join block in a queued confirm or reminder email is checked again at the send. Those emails cannot be built again in the drain (the token exists only in the stored HTML), so the block sits between markers (`join.mark_block`) and `outbox._send_html` cuts it out when the address belongs to a member or has left the news since. The email itself still goes, since the guest asked for it.
- An account's deletion takes the address's `lead_join_invite` record in the same transaction as its lead rows: `Q_DELETE_JOIN_INVITES_OF` (`service/events/retention.py`, named in `service/hard_delete.py`) runs right after `Q_DELETE_LEADS_OF` in the deletion cron and the admin hard delete. The retention sweep already deleted it in the lead sweep's transaction.
- Migration 0076 waits at most 5 seconds for the lock its foreign key takes on `event` (`SET lock_timeout = '5s'` ... `RESET lock_timeout`, as 0077 does).
- The send-time cut of the join block also reads the rest days and the switch. `outbox._send_html` takes the block out of a queued confirm or reminder email when `join.mail_block_allowed(now)` refuses (inside a rest period or past `KNOWN_THROUGH`) or `events_join_block` is off at the send, as well as for a member or an address that left the news. The email itself still goes.
- The drain keeps the invitation to Owner decision 3's hours. Outside 10:00 to 20:00 in the gathering's zone (or on the day it ended) it is held as 'out_of_hours', attempts not counted, until the first hour at which `invite_due` would queue it, never past the window, where it is dropped `lapsed`. `join.in_invite_hours` is the hour test `invite_due` and `invite_hold` share.
- The drain reads the gathering and the guest's place again for `event_join_invite`. A cancelled gathering or a cancelled RSVP is skipped 'cancelled'; a paused, unpublished or deleted gathering, or an erased or missing RSVP (found by the gathering and the RSVP's `event:{slug}` lead, which an erasure keeps), is skipped 'withdrawn'. `outbox._join_invite_withdrawn`.

## Switch-on record (23 Oct 2026)

Task 11 did not run in the order written. On 23 Oct 2026 the owner approved the wording of the join block and the invitation through the copy pass (`ahavah-web/docs/copy/2026-10-23-invite-join-copy-pass.md`, committed in ahavah-web ee50f5d), then said "switch it on". Both switches were set to 1 in production (`AHAVAH_EVENTS_JOIN_BLOCK_ENABLED` and `AHAVAH_EVENTS_JOIN_INVITE_EMAIL_ENABLED`; backup `/root/.env.production.bak-2026-10-23-join`). The proofs of the 6 join emails (Step 3) were sent to the proof address after the switch-on, not before it, so Step 5's gate (no switch before he confirms the proofs) was not kept. His confirmation of the proofs is not recorded here, and Step 6 (the real check with a test gathering and a member's address) had not been run when this was written. Both stay open, with their boxes unticked. Past 9 Nov 2026 (`KNOWN_THROUGH`) no block or invitation goes until the calendar is extended (TEC-1933).
