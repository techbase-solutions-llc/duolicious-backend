# Matchmaker, release 1: alerts, introductions and read-only mentors
Linear: TEC-1845

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A member or a visitor is told, once and by count only, when someone who fits joins; anyone can recommend Ahavah to a single and a member can suggest 2 members they can already see, matched only when both accept and with nobody told of a no; a single can invite one mentor who sees only their matches and the conversations they share, read only, with the other person always told; `/families` explains it to parents and elders. All of it stays dark behind one master switch until the owner has seen every proof.

**Architecture:** The API gains migration 0073 (`match_alert`, `match_alert_notice`, `recommendation`, `introduction`, `mentor_account`, `mentor_link`, `mentor_session`, `shared_conversation`, `mentor_note`, `person.no_mentor_shared_matches` and 2 new outbox recipients) and a `service/matchmaker` package. Alerts match new members with SQL fragments shared with the deck's search (`service/search/predicates.py`); every email goes through the durable outbox on the brand shell; a visitor is a `lead` with source `alert:visitor`. Thirteen switches, all off: the master `matchmaker_live`, 4 for the surfaces in the spec's rollout order, 6 for the emails and 2 for the pushes. The web transcribes `Ahavah Matchmaker.html`, the landing's "Not ready to join?" section and `/families`; the admin gains the Alerts, Introductions and Mentors tiles, the member drawer's Connections and Moderation > Text for introduction notes. The chaperone (phase 3b) is release 2.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pydantic, erlastic, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16, React 19, `next/og` `ImageResponse`, vitest and Testing Library (ahavah-web); Next.js and `node --test` (ahavah-admin).

**Spec:** `docs/superpowers/specs/2026-10-13-matchmaker-design.md`, with the Matchmaker, marketing, visitor-alert and ops parts of `docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md`. Brief: `ahavah-web/docs/design-briefs/2026-10-13-matchmaker.md`. Source of truth for screens: `ahavah-web/Claude Design/Ahavah Matchmaker.html` (`pages/p09-matchmaker.js`, `pages/p09-mm.js`) and `Ahavah Matchmaker Emails.html` (`pages/p09-emails.js`); every string in `Claude Design/handoff/copy/09-matchmaker.md` and `09-matchmaker-emails.md`. Marketing: `docs/design-briefs/2026-10-13-marketing-pages-and-landing.md` and `Ahavah Marketing Pages and Landing.html` (`pages/p11-mk.js` `notReady()`, `footer()`, `PAGES.families`, `OGP`), copy `handoff/copy/11-marketing-pages-and-landing.md` 1.9, 2.10, 3.6 and 3.10. Admin: `docs/design-briefs/2026-10-13-admin-growth-features.md`, `Ahavah Admin Growth Features.html`, copy `handoff/copy/13-admin-growth-features.md` G.1, G.2, 4 and 6. Social: `Ahavah Growth Social Set.html` section 5, copy `12-growth-social-set.md` 5.1 and 5.2.

## Before you start

- Migration number: **0073**. 0069 is reserved for TEC-1897, 0070 is Unmatch (live), 0071 is Events (`.worktrees/events/migrations/0071_events.sql`) and 0072 is the admin fixes branch's (`.worktrees/admin-fixes/migrations/0072_admin_serious_fixes.sql`). The deploy script (`scripts/apply-deploy-migrations.sh`) tracks files by name, so a gap applies cleanly.
- 0073 rewrites `email_outbox_one_recipient_check` to name `organiser_id`, which 0071 adds. So the API branch starts from `ahavah/main` **after Events' API (its Tasks 1 to 13) has merged**. If the owner wants Matchmaker first, see "Spec conflicts", item 24, before writing Task 1.
- ahavah-api: branch `matchmaker` from `ahavah/main`. ahavah-web: branch `matchmaker` from `master`. ahavah-admin: branch `matchmaker` from `master`. Use superpowers:using-git-worktrees. `service/campaigns/switches.py`, `docker-compose.production.yml`, `tests/conftest.py`, `tests/email_samples.py`, `service/campaigns/outbox.py`, `service/cron/returnmail/__init__.py`, `service/person/__init__.py` (finish-onboarding), `src/components/app/marketing-footer.tsx`, `src/app/sitemap.ts`, `src/app/robots.ts` and both privacy pages are also edited by Events and TEC-1897: on a rebase keep every side's lines.
- API tests run with (the "API test command" below):
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. The database is the shared `ahavah-api-postgres-1`; never remove, reset or recreate it or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Web tests: `cd /d/Antigravity/ahavah-web && npx vitest run <file>`. Admin tests: `cd /d/Antigravity/ahavah-admin && node --test tests/<file>.test.mjs`.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845`, no attribution trailers. Never push until Task 30 says so, and then only with the owner's go.
- Line numbers are hints measured on 20 Oct. Every edit is anchored on the code it names; trust the code over the number.
- Read `ahavah-web/AGENTS.md` and `node_modules/next/dist/docs/` before the web tasks (Next 16: `params` is a promise).
- The web and admin tasks transcribe the export with `/sot-sync` once their tests pass. The plan fixes behaviour, data and copy; markup and kit classes come from the frame each task names.

## Global Constraints

Every task's requirements include these. Quoted lines are verbatim from the specs, the briefs or the owner's rules.

- Copy: sentence case, British spelling, no em dashes, digits for numbers, no serial comma, "Marriage and courtship; never 'dating'", "Torah-observant believers, never Jewish framing", "Respectful of families without pressure: the single is in control in every line, and nothing implies a parent decides", "Never tell anyone about a decline", "no urgency, no exclamation marks". This covers UI strings, email text, push text, captions, code comments and commit messages. Strings come verbatim from `09-matchmaker.md`, `09-matchmaker-emails.md`, `11-marketing-pages-and-landing.md` and `13-admin-growth-features.md`; every line this plan adds is marked `NEW LINE` in code and listed under "Spec conflicts", item 21, for `/copy-pass` (ux-writing for screens, humanizer for emails) and the owner.
- Principles: "Nobody browses anyone they could not already see as a member." "Every introduction needs both people to accept." "A mentor sees only what the single chooses to share, and the other person is always told." "Mentor accounts are a role on a new `mentor_account` table, not a `person` row, so no search or count query can include them."
- Privacy: the admin shows counts only, never a message, a mentor's note or who said no ("Counts only. Nobody, the admin included, sees who said no."); the one exception is the text of a flagged introduction note in Moderation > Text, without the recipients. An alert notice names nobody. Plural marriage is left out of every tool: no criterion, filter or line reads `polygyny`.
- Leads: a visitor's alert is a lead with source `alert:visitor` (`service.leads.record_lead`) under the leads retention rules (12 months after the last visit, 8 days if never confirmed, or on request); a member is never a lead. The visitor's own alert goes as requested mail (`enqueue_for_lead(..., marketing=True, requested=True)`).
- Mail: every email goes through the durable outbox (`service/campaigns/outbox.py`) on the brand shell (`emails/base.py render()`), behind its own switch in `service/campaigns/switches.py`, off by default, passed through as `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}` in both the api and cron blocks of `docker-compose.production.yml`; each needs `matchmaker_live` too. Display type is a title image (`title_image()`) in the phone line breaks of `Ahavah Email Titles for Phones.html`, rendered with `ahavah-web/scripts/render-email-titles.mjs`, never a typed headline (`tests/test_email_renders_on_a_phone.py` enforces it); every new email gets a row in `tests/email_samples.py`. Names and notes are escaped with `html.escape`. Proofs go to `scripts/send_proofs.PROOF_TO` only, never through the outbox.
- Dark launch: while `matchmaker_live` is off every `/matchmaker`, `/alerts`, `/introductions`, `/recommendations`, `/mentor` and `/conversations/<uuid>/share` route except `GET /matchmaker/status` answers 404; the web shows no Matchmaker row, sheet, card, notice or page; `/families`, `/mentor` and `/alerts/...` are not found; the sitemap has none of them; the landing section draws nothing; the footer has no For families.
- Abuse: the free defences only (`service.leads.mail_refusal`, the honeypot, the page stamp, `shared_recipient_limit` and per-IP limits), as Together and Events; Turnstile is not used. Every refusal a sender could learn from (a member's address, a block, a decline, a repeat) answers exactly as a send.
- Screens: "Design each screen at 390 first", "Nothing scrolls sideways on a phone: criteria rows stack, region pills wrap, match cards stack", touch targets at least 44 px, dark first with the light variant, checked at 320, 390, 768 and 1440. Dashboards are a bento: rows full width, tiles level, no holes.
- Social: Instagram captions carry no link and never say "link below"; no faces of members; the owner's rest days (`service/spotlight/restdays.py`, admin `src/lib/rest-days.ts`, read only to 9 Nov 2026) hold the alert notices and block promotional posts, and this plan changes neither file.

## Review Focus

The five inputs the spec implies but no requirement names, most likely to bite a member, a visitor or a mentor first. Each has a test in the task named.

1. An email security scanner opening the visitor's "Turn on my alert" link or the mentor's "Accept and sign in" link before the person does: each email links to a web page that confirms by a script call, so a bare GET confirms nothing. Task 4, `test_the_email_links_are_web_pages_not_the_api`; Task 20, `does not confirm until the page has loaded`; Task 25, `does not accept the invitation until the page has loaded`.
2. An introducer probing for who is a member, who blocked them or who said no: recommending a member's address, suggesting someone who has blocked either person or is no longer visible, a repeat and a decline all answer exactly as a send. Task 8, `test_every_refusal_answers_as_a_send`; Task 9, `test_a_hidden_refusal_answers_as_a_send`.
3. A mentor after removal, or reaching past what was shared: a removed mentor's next call answers "access ended" at once, and a mentor cannot read an unshared conversation, another single's matches or a match by guessing a uuid. Task 12, `test_a_removed_mentor_sees_nothing_at_once` and `test_a_mentor_reaches_only_what_was_shared`.
4. The alert count including the wrong people: the owner themselves, staff accounts, members hidden from strangers, members held for verification, members with no approved photo, blocked or unmatched pairs and mentors. Task 7, `test_the_count_leaves_out_who_the_deck_leaves_out`.
5. Both people accepting at the same moment, or accepting after the introduction closed, after a block or after an unmatch: one match at most, and a closed answer otherwise. Task 10, `test_both_accepting_at_once_makes_one_match` and `test_accepting_a_closed_or_blocked_introduction_matches_nobody`.

## Decisions taken

The owner may change any of these; each is also in "Spec conflicts and decisions needing the owner" with its default.

From the brief's "Owner decisions this brief needs", the options the export marks recommended (`rec:1` in `p09-matchmaker.js`):

1. Criteria: option A, Filters unchanged; the 4 new controls (Countries, Willing to relocate, Sabbath, Wants children) live in the alert sheet only, reached from Filters by one row (1.6).
2. "See who joined" lands on Discover with the new members who fit first (1.13).
3. The visitor form is on the landing page only; the member alert is on the empty deck (3.1).
4. Visitor regions are the Map's continents (3.1).
5. A non-member who recommends confirms their own email with the 6-digit code first; the same limits apply (5a.7).
6. Option B: the second person comes from the introducer's matches, likes either way and profile views, members on their map and members in the weekly Spotlight (5b.2). The export marks neither option; option A is "usually empty" (5b.3).
7. An introduction closes 14 days after it is sent, and the card says the date (5c.1).
8. The introducer is told only when both accept: a push and, on their next visit, the toast "Miriam and Daniel both said yes." (5c.8).
9. A viewer held by the photo gate sees the name-seeded gradient on the card (5c.5).
10. A line in the conversation when sharing starts and stops, as well as the header notice (8.1, 8.4).
11. The mentor is always "mentor" to the other person (8.1).
12. "Do not match me with members who share conversations with a mentor" is off by default (6.10).
13. The single reads the mentor's notes on their own view of that match (8.5).

Choices this plan makes where the spec leaves one:

- **Rollout by switch, in the spec's order.** `matchmaker_live` is the master; `matchmaker_alerts` (members), `matchmaker_visitor_alerts`, `matchmaker_introductions` (recommend and suggest) and `matchmaker_mentors` (mentors, sharing and `/families`) each need it.
- **How often.** A member's notice goes at most once a day, at the first hourly tick at or after 12:00 UTC; a visitor's at most once a week, Thursday from 12:00 UTC, since 4.5 says "this week". Neither is queued inside one of the owner's rest periods; the count carries to the next run.
- **Channels.** A member's notice goes by push when the alert's push switch is on and the member has a live subscription, and by email when the alert's email switch is on, or when push is on but cannot reach them (1.5: "Until then we will email you").
- **One email for both reasons.** The alert job runs before `likes_waiting` in the same tick. When a member's alert email goes and they have likes the weekly likes email would count, it carries the 4.3 block and sets `match_alert.likes_told_at`; that week's likes email then skips them. A member with an alert whose email is on gets the likes email without its new-fit line.
- **Who counts as a new member who fits**: someone who joined since the alert's last count and whom the deck would show the owner (the base predicates of `Q_UNCACHED_SEARCH_2`: activated, a member, not hidden from strangers, not held for verification, an approved photo, no block or unmatch with the owner), inside the criteria. For a visitor the same without the pair checks.
- **Limits**: a sender recommends at most 5 singles a week, and an address is emailed once ever, whoever sends; an introducer suggests at most 5 pairs a week and each person once ever. A week starts Monday 00:00 UTC.
- **Flagged notes** (`antiabuse.antirude.profile.is_rude`, or 0.5 or more on `antiabuse.romancescam.analyze_message`, or a URL, email address or phone number) hold the recommendation or introduction for Moderation > Text. Approving sends it; rejecting sends nothing and tells nobody.
- **Introduction notices** follow the member's Matches switches in Settings > Notifications (push and email), since the export draws no Introductions row and 5.2's footer points there.
- **Both accept**: likes both ways and an `ahavah_match` row, in the second acceptance's transaction under the introduction's row lock; the existing match notice goes to the first acceptor; the introducer is told.
- **One mentor per single.** A mentor signs in first from the invitation link (it proves the address), later with the 6-digit code (`/request-otp`, `/check-otp`) exchanged for a mentor token. A mentor token (header `X-Mentor-Token`) is 32 characters, stored as its sha256, valid 30 days.
- **What a mentor reads**: the whole shared conversation as the single sees it, text only; a voice message shows as a line. Prompts show once the profile prompts release ships; until then the profile's About.
- **The new outbox recipients**: `email_outbox.recommendation_id` (the recommended single is neither a member nor a lead: "nobody gives their own email there", `service/leads/sources.py`) and `email_outbox.mentor_link_id`.
- **Retention**: a recommended single's address and the note are erased 7 days after the email settles, keeping a keyed hash for 12 months so they hear from Ahavah only once; an introduction's note stays while the pair is matched (it is the chat's context line) and is erased 30 days after an unmatched introduction closes; removing a mentor ends the link and every share at once and deletes the mentor's notes; a mentor account serving nobody for 30 days is deleted; stopped visitor alerts are deleted at once and paused member alerts kept. The privacy paragraph says so (Task 27).

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `migrations/0073_matchmaker.sql` | Create | The 9 tables, the person setting and the 2 outbox recipients |
| `service/matchmaker/__init__.py` | Create | `live()`, `surface_on()`, `switch_on()`, `CAMPAIGN_SWITCHES`, `MatchmakerError`, `address_key()`, `first_name()` |
| `service/matchmaker/regions.py`, `continents.json` | Create | Alpha-2 code to continent |
| `service/search/predicates.py` | Create | SQL fragments shared by the deck and the alerts |
| `service/search/sql/__init__.py` | Modify | `Q_UNCACHED_SEARCH_2` built from the fragments; `new_fit_ids` ranking; the shared-conversation exclusion |
| `service/matchmaker/criteria.py` | Create | Criteria rules, the words for them, the fit query |
| `service/matchmaker/mail.py` | Create | Every Matchmaker email and push, queueing, previews |
| `service/matchmaker/alerts.py`, `notices.py` | Create | Member and visitor alerts; the daily and weekly jobs |
| `service/matchmaker/recommend.py`, `introductions.py` | Create | Recommend a single; suggest, respond, close |
| `service/matchmaker/mentors.py`, `mentor_view.py` | Create | The single's side; the mentor's side |
| `service/matchmaker/moderation.py`, `admin.py`, `retention.py` | Create | Held notes; counts and connections; the sweep and deletion |
| `service/api/matchmaker_routes.py`, `service/api/mentor_routes.py`, `service/api/admin/matchmaker_routes.py` | Create | Every route |
| `service/api/__init__.py`, `duotypes/__init__.py` | Modify | Registration; request models |
| `service/campaigns/switches.py`, `docker-compose.production.yml` | Modify | 13 switches and their pass-throughs |
| `service/campaigns/outbox.py` | Modify | `enqueue_for_recommendation`, `enqueue_for_mentor_link`, Matchmaker switches and the 2 recipients at send time |
| `emails/likes_waiting_weekly.py` | Modify | Skips a member whose alert carried the likes; no fit line beside an alert |
| `service/decisions/__init__.py` (`Q_LIST_MATCHES`), `service/person/__init__.py` (profile-info field, finish-onboarding) | Modify | `introduced_by`; the privacy field; linking at sign-up |
| `service/cron/returnmail/__init__.py`, `service/cron/leadretention/__init__.py`, `service/hard_delete.py`, `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py` | Modify | Jobs, sweep, deletion |
| `emails/assets/title-alert-*.png`, `title-recommend*.png`, `title-introduction*.png`, `title-mentor-invite*.png` | Add | Synced from ahavah-web (Task 17) |
| `scripts/send_matchmaker_proofs.py` | Create | Proofs to the owner only |
| `tests/conftest.py`, `tests/email_samples.py` | Modify | Fixtures; the new emails |
| `tests/test_migration_0073.py`, `test_matchmaker_switches.py`, `test_search_predicates.py`, `test_matchmaker_criteria.py`, `test_matchmaker_mail.py`, `test_member_alerts.py`, `test_visitor_alerts.py`, `test_alert_notices.py`, `test_recommendations.py`, `test_introductions_suggest.py`, `test_introductions_respond.py`, `test_mentor_single.py`, `test_mentor_view.py`, `test_admin_matchmaker.py`, `test_matchmaker_retention.py`, `test_send_matchmaker_proofs.py` | Create | One file per task |

ahavah-web:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/matchmaker/api.ts`, `status.ts`, `server.ts`, `criteria.ts`, `copy.ts`, `mentor-token.ts`, `nav.ts` | Create | Calls and types, the live check, server reads, the words for criteria, every string, the mentor's token, the footer flag |
| `public/email/title-alert-fits.png` and the other 11 | Create | The 6 email titles, light and dark |
| `src/components/matchmaker/*` | Create | Every screen's parts |
| `src/components/app/filters-sheet.tsx`, `deck-end.tsx`, `src/app/discover/page.tsx` | Modify | The way in, the 7 rows, new fits first |
| `src/app/settings/notifications/page.tsx`, `src/app/settings/privacy/page.tsx`, `src/app/settings/mentor/page.tsx` | Modify, create | The alert row; the matching setting; Your mentor |
| `src/app/page.tsx`, `src/app/alerts/confirm/[token]/page.tsx`, `src/app/alerts/stop/[token]/page.tsx` | Modify, create | The landing section; confirming and stopping |
| `src/app/invite/page.tsx`, `src/app/profile/[uuid]/page.tsx`, `src/app/matches/page.tsx`, `src/app/match/page.tsx` | Modify | Recommend; Suggest an introduction; the card; "Introduced by" |
| `src/components/app/chat-header.tsx`, `chat-more-menu.tsx`, `chat-thread-view.tsx` | Modify | The notice, Share with your mentor, the lines in the conversation, the introducer's note |
| `src/app/mentor/page.tsx`, `src/app/mentor/[single]/[match]/page.tsx`, `src/app/mentor/[single]/[match]/conversation/page.tsx` | Create | The mentor's view |
| `src/app/families/page.tsx`, `opengraph-image.tsx`, `src/lib/share-image/matchmaker-templates.tsx`, `src/lib/share-image/templates.tsx` | Create, modify | `/families` and its share image |
| `src/components/app/marketing-footer.tsx`, `src/app/sitemap.ts`, `src/app/robots.ts` | Modify | For families, the sitemap, robots |
| `src/lib/legal-matchmaker-copy.ts`, `src/lib/legal-leads-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` | Create, modify | Privacy |

ahavah-admin:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/matchmaker-api.ts`, `src/lib/matchmaker-queries.ts` | Create | Pure helpers and the hooks |
| `src/components/admin/growth-matchmaker.tsx`, `user-drawer-connections.tsx`, `moderation-text.tsx` | Create | The 3 tiles, Connections, Text |
| `src/components/admin/tab-growth.tsx`, `user-drawer.tsx`, `tab-moderation.tsx`, `sidebar-nav.tsx` | Modify | Where they mount; the waiting count |
| `tests/matchmaker-api.test.mjs` | Create | Tests |

---

## Release 1 API (ahavah-api)

### Task 1: Migration 0073, the Matchmaker tables

**Files:**
- Create: `migrations/0073_matchmaker.sql`
- Modify: `tests/conftest.py` (append `matchmaker_schema`)
- Test: `tests/test_migration_0073.py` (create)

**Interfaces:**
- Consumes: `lead` (0066), `email_outbox.organiser_id` (0071).
- Produces: the tables below; `email_outbox_one_recipient_check` now `num_nonnulls(person_id, lead_id, organiser_id, recommendation_id, mentor_link_id) = 1` with the partial unique indexes `idx__email_outbox__recommendation_run` and `idx__email_outbox__mentor_link_run`; fixture `matchmaker_schema` (session scope, applies 0066, 0071 and 0073 the way `together_schema` applies 0068).

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0073.py`:

```python
"""Migration 0073, the matchmaker (TEC-1845). Idempotent, as the deploy may
run it more than once."""
from pathlib import Path

import psycopg
import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('matchmaker_schema')
SQL = (Path(__file__).resolve().parent.parent / 'migrations' / '0073_matchmaker.sql').read_text(encoding='utf-8')

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
    assert {'id', 'person_id', 'lead_id', 'first_name', 'criteria', 'notify_push', 'notify_email', 'active',
            'confirmed_at', 'confirm_token_hash', 'confirm_by', 'resends', 'stop_token_hash', 'counted_since',
            'last_sent_at', 'likes_told_at', 'paused_at', 'created_at', 'updated_at'} <= _cols('match_alert')
    assert {'alert_id', 'audience', 'members', 'window_start', 'window_end', 'by_push', 'by_email'} <= _cols('match_alert_notice')
    assert {'sender_person_id', 'sender_key', 'sender_first_name', 'recipient_email', 'recipient_key', 'note',
            'referral_code', 'status', 'flag_reason', 'joined_person_id', 'reviewed_by', 'reviewed_at',
            'sent_at', 'erased_at'} <= _cols('recommendation')
    assert {'introducer_person_id', 'a_person_id', 'b_person_id', 'note', 'status', 'flag_reason',
            'a_response', 'b_response', 'a_responded_at', 'b_responded_at', 'closes_at', 'opened_at',
            'matched_at', 'introducer_told_at', 'reviewed_by', 'reviewed_at', 'note_erased_at'} <= _cols('introduction')
    assert {'email', 'normalized_email', 'last_seen_at'} <= _cols('mentor_account')
    assert {'single_person_id', 'mentor_email', 'mentor_normalized_email', 'relation', 'mentor_account_id',
            'invite_token_hash', 'invite_expires_at', 'confirmed_at', 'revoked_at'} <= _cols('mentor_link')
    assert {'token_hash', 'mentor_account_id', 'expires_at'} <= _cols('mentor_session')
    assert {'single_person_id', 'other_person_id', 'other_person_uuid', 'mentor_link_id', 'shared_at', 'revoked_at'} <= _cols('shared_conversation')
    assert {'mentor_account_id', 'single_person_id', 'about_person_id', 'note'} <= _cols('mentor_note')
    assert 'no_mentor_shared_matches' in _cols('person')
    assert {'recommendation_id', 'mentor_link_id'} <= _cols('email_outbox')

def test_an_alert_has_exactly_one_owner():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO match_alert (criteria) VALUES ('{}'::jsonb)")

def test_an_outbox_row_still_names_exactly_one_recipient():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO email_outbox (campaign, campaign_id, email, payload) "
                       "VALUES ('mm_recommend', 'x', 'x@a.invalid', '{}'::jsonb)")

def test_a_single_has_one_live_mentor_link(make_person):
    p = make_person()
    with pytest.raises(psycopg.errors.UniqueViolation):
        with api_tx() as tx:
            for _ in range(2):
                tx.execute("INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, "
                           "relation, invite_expires_at) VALUES (%(p)s, 'r@a.invalid', 'r@a.invalid', 'parent', NOW())",
                           dict(p=p['id']))
```

- [ ] **Step 2: Run it to verify it fails**

Run: the API test command with `tests/test_migration_0073.py`. Expected: errors, `fixture 'matchmaker_schema' not found`.

- [ ] **Step 3: Write `migrations/0073_matchmaker.sql` and the fixture**

The schema is a decision, so here it is in full. Every statement is idempotent.

```sql
-- 0073_matchmaker.sql
-- Matchmaker, release 1 (TEC-1845, docs/superpowers/plans/2026-10-21-matchmaker-release-1.md).
-- 0069 is reserved for TEC-1897, 0070 is Unmatch, 0071 is Events and 0072
-- is the admin fixes branch's. Needs 0066 (lead) and 0071
-- (email_outbox.organiser_id) applied first.
--
--   match_alert          "Tell me when someone fits": a member's (person_id)
--                        or a visitor's (lead_id, source alert:visitor).
--                        active FALSE is paused. Names nobody.
--   match_alert_notice   one row per notice sent: a count, never who.
--   recommendation       "Introduce a single to Ahavah". The single's address
--                        and the note are erased 7 days after the email
--                        settles; recipient_key (HMAC of the normalised
--                        address) stays 12 months so they hear from us once.
--   introduction         "Suggest two people". A match only if both accept.
--   mentor_account       a role, not a person: no profile, never in search.
--   mentor_link          a single's one mentor, invited by email.
--   mentor_session       a mentor's sign-in, stored as its sha256.
--   shared_conversation  one conversation a single shares, read only. Rows
--                        are revoked, not deleted, so the chat can say when
--                        sharing stopped.
--   mentor_note          a mentor's private note to the single about a match.
--   person.no_mentor_shared_matches   Privacy, Matching (owner decision 12).
--   email_outbox         gains recommendation_id and mentor_link_id: neither
--                        recipient is a member or a lead.

CREATE TABLE IF NOT EXISTS match_alert (
  id                  BIGSERIAL    PRIMARY KEY,
  person_id           INT          REFERENCES person(id) ON DELETE CASCADE,
  lead_id             BIGINT       REFERENCES lead(id) ON DELETE CASCADE,
  first_name          TEXT         CHECK (char_length(first_name) BETWEEN 1 AND 40),
  criteria            JSONB        NOT NULL,
  notify_push         BOOLEAN      NOT NULL DEFAULT TRUE,
  notify_email        BOOLEAN      NOT NULL DEFAULT TRUE,
  active              BOOLEAN      NOT NULL DEFAULT TRUE,
  confirmed_at        TIMESTAMPTZ,
  confirm_token_hash  TEXT         UNIQUE,
  confirm_by          TIMESTAMPTZ,
  resends             INT          NOT NULL DEFAULT 0,
  stop_token_hash     TEXT         UNIQUE,
  counted_since       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  last_sent_at        TIMESTAMPTZ,
  likes_told_at       TIMESTAMPTZ,
  paused_at           TIMESTAMPTZ,
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (num_nonnulls(person_id, lead_id) = 1),
  CHECK (person_id IS NULL OR confirmed_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__match_alert__person ON match_alert (person_id) WHERE person_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx__match_alert__lead ON match_alert (lead_id) WHERE lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__match_alert__due ON match_alert (last_sent_at) WHERE active AND confirmed_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS match_alert_notice (
  id            BIGSERIAL    PRIMARY KEY,
  alert_id      BIGINT       REFERENCES match_alert(id) ON DELETE SET NULL,
  audience      TEXT         NOT NULL CHECK (audience IN ('member', 'visitor')),
  members       INT          NOT NULL CHECK (members >= 1),
  window_start  TIMESTAMPTZ  NOT NULL,
  window_end    TIMESTAMPTZ  NOT NULL,
  by_push       BOOLEAN      NOT NULL DEFAULT FALSE,
  by_email      BOOLEAN      NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__match_alert_notice__alert ON match_alert_notice (alert_id, created_at DESC);

CREATE TABLE IF NOT EXISTS recommendation (
  id                 BIGSERIAL    PRIMARY KEY,
  sender_person_id   INT          REFERENCES person(id) ON DELETE SET NULL,
  sender_key         TEXT         NOT NULL,
  sender_first_name  TEXT         CHECK (char_length(sender_first_name) BETWEEN 1 AND 40),
  recipient_email    TEXT,
  recipient_key      TEXT         NOT NULL,
  note               TEXT         CHECK (char_length(note) BETWEEN 1 AND 500),
  referral_code      TEXT,
  status             TEXT         NOT NULL CHECK (status IN ('held', 'queued', 'sent', 'rejected')),
  flag_reason        TEXT,
  joined_person_id   INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_by        INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_at        TIMESTAMPTZ,
  sent_at            TIMESTAMPTZ,
  erased_at          TIMESTAMPTZ,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (status NOT IN ('held', 'queued') OR recipient_email IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__recommendation__recipient ON recommendation (recipient_key) WHERE status <> 'rejected';
CREATE INDEX IF NOT EXISTS idx__recommendation__sender ON recommendation (sender_key, created_at);

CREATE TABLE IF NOT EXISTS introduction (
  id                    BIGSERIAL    PRIMARY KEY,
  introducer_person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  a_person_id           INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  b_person_id           INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  note                  TEXT         CHECK (char_length(note) <= 500),
  status                TEXT         NOT NULL DEFAULT 'open' CHECK (status IN ('held', 'open', 'matched', 'closed', 'rejected')),
  flag_reason           TEXT,
  a_response            TEXT         CHECK (a_response IN ('accepted', 'declined')),
  b_response            TEXT         CHECK (b_response IN ('accepted', 'declined')),
  a_responded_at        TIMESTAMPTZ,
  b_responded_at        TIMESTAMPTZ,
  closes_at             TIMESTAMPTZ  NOT NULL,
  opened_at             TIMESTAMPTZ,
  matched_at            TIMESTAMPTZ,
  introducer_told_at    TIMESTAMPTZ,
  reviewed_by           INT          REFERENCES person(id) ON DELETE SET NULL,
  reviewed_at           TIMESTAMPTZ,
  note_erased_at        TIMESTAMPTZ,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (a_person_id <> b_person_id),
  CHECK (introducer_person_id NOT IN (a_person_id, b_person_id))
);
CREATE INDEX IF NOT EXISTS idx__introduction__a_open ON introduction (a_person_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx__introduction__b_open ON introduction (b_person_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx__introduction__introducer ON introduction (introducer_person_id, created_at);

CREATE TABLE IF NOT EXISTS mentor_account (
  id                BIGSERIAL    PRIMARY KEY,
  email             TEXT         NOT NULL,
  normalized_email  TEXT         NOT NULL UNIQUE,
  last_seen_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mentor_link (
  id                       BIGSERIAL    PRIMARY KEY,
  single_person_id         INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  mentor_email             TEXT         NOT NULL,
  mentor_normalized_email  TEXT         NOT NULL,
  relation                 TEXT         NOT NULL CHECK (relation IN ('parent', 'elder', 'mentor', 'friend')),
  mentor_account_id        BIGINT       REFERENCES mentor_account(id) ON DELETE SET NULL,
  invite_token_hash        TEXT         UNIQUE,
  invite_expires_at        TIMESTAMPTZ  NOT NULL,
  confirmed_at             TIMESTAMPTZ,
  revoked_at               TIMESTAMPTZ,
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK (confirmed_at IS NULL OR mentor_account_id IS NOT NULL OR revoked_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__mentor_link__single_live ON mentor_link (single_person_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__mentor_link__mentor_email ON mentor_link (mentor_normalized_email) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS mentor_session (
  token_hash         TEXT         PRIMARY KEY,
  mentor_account_id  BIGINT       NOT NULL REFERENCES mentor_account(id) ON DELETE CASCADE,
  expires_at         TIMESTAMPTZ  NOT NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__mentor_session__expires ON mentor_session (expires_at);

CREATE TABLE IF NOT EXISTS shared_conversation (
  id                 BIGSERIAL    PRIMARY KEY,
  single_person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  other_person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  other_person_uuid  UUID         NOT NULL,
  mentor_link_id     BIGINT       NOT NULL REFERENCES mentor_link(id) ON DELETE CASCADE,
  shared_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  revoked_at         TIMESTAMPTZ,
  CHECK (single_person_id <> other_person_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx__shared_conversation__live ON shared_conversation (single_person_id, other_person_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx__shared_conversation__other ON shared_conversation (other_person_id);

CREATE TABLE IF NOT EXISTS mentor_note (
  id                 BIGSERIAL    PRIMARY KEY,
  mentor_account_id  BIGINT       NOT NULL REFERENCES mentor_account(id) ON DELETE CASCADE,
  single_person_id   INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  about_person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  note               TEXT         NOT NULL CHECK (char_length(note) BETWEEN 1 AND 1000),
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  UNIQUE (mentor_account_id, single_person_id, about_person_id)
);

ALTER TABLE person ADD COLUMN IF NOT EXISTS no_mentor_shared_matches BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS recommendation_id BIGINT REFERENCES recommendation(id) ON DELETE CASCADE;
ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS mentor_link_id BIGINT REFERENCES mentor_link(id) ON DELETE CASCADE;
ALTER TABLE email_outbox DROP CONSTRAINT IF EXISTS email_outbox_one_recipient_check;
ALTER TABLE email_outbox ADD CONSTRAINT email_outbox_one_recipient_check
  CHECK (num_nonnulls(person_id, lead_id, organiser_id, recommendation_id, mentor_link_id) = 1);
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__recommendation_run
  ON email_outbox (campaign, campaign_id, recommendation_id) WHERE recommendation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx__email_outbox__mentor_link_run
  ON email_outbox (campaign, campaign_id, mentor_link_id) WHERE mentor_link_id IS NOT NULL;
```

Append to `tests/conftest.py`, after the Gatherings block, a `# Matchmaker (TEC-1845)` block with `matchmaker_schema(events_schema)` (session scope) that executes `0073_matchmaker.sql`.

- [ ] **Step 4: Run it to verify it passes**

Run: the API test command with `tests/test_migration_0073.py`. Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add migrations/0073_matchmaker.sql tests/conftest.py tests/test_migration_0073.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): migration 0073, the alert, introduction and mentor tables" -m "Refs: TEC-1845"
```

### Task 2: The 13 switches, the live checks and `GET /matchmaker/status`

**Files:**
- Modify: `service/campaigns/switches.py` (after the Gatherings block), `docker-compose.production.yml` (api and cron blocks, after the Gatherings pass-throughs)
- Create: `service/matchmaker/__init__.py`, `service/api/matchmaker_routes.py`
- Modify: `service/api/__init__.py` (after the Gatherings imports), `tests/conftest.py` (append `matchmaker_live`, `member_pair`)
- Test: `tests/test_matchmaker_switches.py` (create)

**Interfaces:**
- Consumes: `service.campaigns.switches.enabled`; `service.unsubscribe._secret()`.
- Produces: switch names and variables:

  | Name | Variable |
  |---|---|
  | `matchmaker_live` | `AHAVAH_MATCHMAKER_LIVE_ENABLED` |
  | `matchmaker_alerts` | `AHAVAH_MATCHMAKER_ALERTS_ENABLED` |
  | `matchmaker_visitor_alerts` | `AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED` |
  | `matchmaker_introductions` | `AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED` |
  | `matchmaker_mentors` | `AHAVAH_MATCHMAKER_MENTORS_ENABLED` |
  | `matchmaker_alert_email` | `AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED` |
  | `matchmaker_visitor_confirm_email` | `AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED` |
  | `matchmaker_visitor_alert_email` | `AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED` |
  | `matchmaker_recommend_email` | `AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED` |
  | `matchmaker_intro_email` | `AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED` |
  | `matchmaker_mentor_invite_email` | `AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED` |
  | `matchmaker_alert_push` | `AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED` |
  | `matchmaker_intro_push` | `AHAVAH_MATCHMAKER_INTRO_PUSH_ENABLED` |

- In `service.matchmaker`: `live() -> bool`; `surface_on(name: Literal['matchmaker_alerts', 'matchmaker_visitor_alerts', 'matchmaker_introductions', 'matchmaker_mentors']) -> bool` (live and the surface); `switch_on(name: str) -> bool` (live and the named switch); `CAMPAIGN_SWITCHES: dict[str, str]` = `{'mm_alert': 'matchmaker_alert_email', 'mm_visitor_confirm': 'matchmaker_visitor_confirm_email', 'mm_visitor_alert': 'matchmaker_visitor_alert_email', 'mm_recommend': 'matchmaker_recommend_email', 'mm_intro': 'matchmaker_intro_email', 'mm_mentor_invite': 'matchmaker_mentor_invite_email'}`; `class MatchmakerError(Exception)` with `.reason: str`, `.status: int`, `.extra: dict`; `address_key(normalized_email: str) -> str` (HMAC-SHA256 hex with `service.unsubscribe._secret()`); `first_name(name: Optional[str]) -> str` (the first word, or `'Someone'`, NEW LINE).
- Route `GET /matchmaker/status` -> `{live, alerts, visitor_alerts, introductions, mentors}`, `Cache-Control: no-store`; helper `_off()` -> `({'error': 'not_found'}, 404)` used by every later route.
- Fixtures: `matchmaker_live` (sets all 13 variables to 1; a test of a dark or closed state deletes the one it is about); `member_pair(gender_a='Woman', gender_b='Man') -> (a, b)`: two activated members with an approved photo and gender preferences for each other, made with `make_person` and `add_photo`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matchmaker_switches.py` in the shape of `tests/test_events_switches.py`: `NEW` is the table above; `test_the_switches_and_their_variables`; `test_the_compose_file_passes_each_to_the_api_and_the_cron` (parametrised, `text.count(f'{env}: ${{{env}:-0}}') == 2`); `test_everything_needs_the_live_switch` (with only `AHAVAH_MATCHMAKER_ALERTS_ENABLED` and `AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED` on, `surface_on('matchmaker_alerts')` and `switch_on('matchmaker_alert_email')` are False; with the master on they are True and `surface_on('matchmaker_mentors')` is False); and:

```python
def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/matchmaker/status')
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert r.get_json() == {'live': False, 'alerts': False, 'visitor_alerts': False,
                            'introductions': False, 'mentors': False}
    monkeypatch.setenv('AHAVAH_MATCHMAKER_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MATCHMAKER_MENTORS_ENABLED', '1')
    assert client.get('/matchmaker/status').get_json()['mentors'] is True

def test_the_address_key_is_keyed_not_a_plain_hash():
    import hashlib
    from service.matchmaker import address_key
    assert address_key('hannah@example.com') != hashlib.sha256(b'hannah@example.com').hexdigest()
    assert address_key('hannah@example.com') == address_key('hannah@example.com')
```

- [ ] **Step 2: Run it to verify it fails.** Run: the API test command with `tests/test_matchmaker_switches.py`. Expected: 17 failed or errored (no switches, no compose lines, `No module named 'service.matchmaker'`).

- [ ] **Step 3: Implement**

Add the 13 entries to `SWITCHES` under a comment block in the style of the Together one: the master switch's comment says every Matchmaker route but `/matchmaker/status` answers 404 while it is off; the email and push block says each is off until the owner has seen its proof. Add the 13 pass-throughs in both compose blocks under `# Matchmaker (TEC-1845). Off until launch and until the owner confirms each proof.` Create `service/matchmaker/__init__.py` with a module docstring listing the package's modules and the interfaces above. Create `service/api/matchmaker_routes.py` (docstring: imported at the bottom of `service/api/__init__.py`; every route but `/matchmaker/status` answers 404 while `matchmaker_live` is off) with `get_matchmaker_status`, and register it under `# Matchmaker (TEC-1845).`. Add the fixtures.

- [ ] **Step 4: Run it to verify it passes.** Expected: `17 passed`.

- [ ] **Step 5: Commit**

```bash
git add service/campaigns/switches.py docker-compose.production.yml service/matchmaker/__init__.py service/api/matchmaker_routes.py service/api/__init__.py tests/conftest.py tests/test_matchmaker_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the 13 switches, all off, with GET /matchmaker/status" -m "Refs: TEC-1845"
```

### Task 3: Criteria, continents and the predicates the deck and the alerts share

**Files:**
- Create: `service/search/predicates.py`, `service/matchmaker/regions.py`, `service/matchmaker/continents.json`, `service/matchmaker/criteria.py`
- Modify: `service/search/sql/__init__.py` (`Q_UNCACHED_SEARCH_2` built from the fragments)
- Test: `tests/test_search_predicates.py`, `tests/test_matchmaker_criteria.py` (create)

**Interfaces:**
- Consumes: `Q_UNCACHED_SEARCH_2`'s clauses for gender, Torah level, calendar and the age filter; `service.admin.queries.members.member_sql`; `pycountry`.
- Produces:
  - In `service.search.predicates`, each returning SQL text with the bind names the search already uses: `gender_sql(p: str) -> str` (`%(gender_preference)s`), `torah_level_sql(p)` (`%(torah_levels)s`), `calendar_sql(p)` (`%(calendars)s`), `age_bounds_sql(p)` (`%(age_min)s`, `%(age_max)s`), and new, alert-only so far: `countries_sql(p)` (`%(countries)s`, alpha-2, `upper(p.country) = ANY(...)`, empty = any), `relocation_sql(p)` (`%(relocations)s` against `p.ahavah_extra->>'relocation'`), `shabbat_sql(p)` (`%(shabbats)s` against `->>'shabbat'`), `wants_children_sql(p)` (`%(wants_children)s` TEXT or NULL against `->>'wantsChildren'`). Every one fails open on an unset prospect field, as the deck does ("unknown is not a mismatch"). `deck_base_sql(p: str, owner: Optional[str]) -> str`: activated, `member_sql(p)`, not `hide_me_from_strangers`, not `verification_required`, an approved photo, and when `owner` is given `p.id <> owner`, `NOT is_blocked_pair(owner, p.id)` and `NOT is_unmatched_pair(owner, p.id)`.
  - In `service.matchmaker.regions`: `REGIONS = ('africa', 'asia', 'europe', 'north-america', 'oceania', 'south-america')`; `region_of(code: Optional[str]) -> Optional[str]`; `codes_in(regions: Iterable[str]) -> list[str]`. `continents.json` maps every alpha-2 code in `pycountry.countries` to a region by UN M49, with the Caribbean, Central America and Mexico in `north-america`, Russia in `europe`, Turkey and the Caucasus in `asia`, Egypt in `africa` (the rules of Events' `continents.json`).
  - In `service.matchmaker.criteria`:
    - `MEMBER_KEYS = ('age_min', 'age_max', 'countries', 'regions', 'relocations', 'torah_levels', 'shabbats', 'calendars', 'wants_children')`; `VISITOR_KEYS = ('looking_for', 'age_min', 'age_max', 'region')`. Allowed values are the web's `profile-schema.ts` lists: `RELOCATIONS` (`will-relocate`, `wants-partner-willing`, `local-only`, `international-open`), `TORAH_LEVELS` (`learning`, `beginner`, `intermediate`, `experienced`), `SHABBATS` (`friday-sunset-saturday-sunset`, `luni-solar`, `saturday-only`, `other`), `CALENDARS` (`rabbinic`, `aviv-barley`, `enoch`, `luni-solar`, `observational-new-moon`, `other`), `wants_children` `yes`, `no` or None; ages 18 to 80 (`service.search.AGE_FLOOR`, `AGE_CEILING`), min not above max; countries are alpha-2 codes; `looking_for` `man` or `woman`; `region` one of `REGIONS` or None ("Anywhere").
    - `clean_member_criteria(raw: dict) -> dict` and `clean_visitor_criteria(raw: dict) -> dict`, raising `MatchmakerError('bad_criteria', 400, {'field': key})`. A list with every option counts as no filter and is stored empty. Setting `countries` clears `regions`.
    - `summary_line(c: dict) -> str`: "On. Ages 26 to 34, anywhere." is 1.9's; this returns the part after "On. ": `'Ages 26 to 34, anywhere.'`, `'Ages 26 to 34, in 3 countries.'`, `'Ages 26 to 34, in North America.'` (the last two NEW LINES).
    - `visitor_words(c: dict) -> str`: `'a man aged 26 to 34 in North America'` (4.4), `'a woman aged 30 to 40'` when the region is Anywhere (NEW LINE).
    - `fits_sql(owner: Optional[str]) -> str`: `deck_base_sql('p', owner)` and every fragment above, with `p.sign_up_time > %(since)s AND p.sign_up_time <= %(until)s`; `fit_params(c: dict, *, gender_ids: list[int], since, until, owner_id: Optional[int]) -> dict` (regions become `countries` through `codes_in`; `torah_levels`, `calendars` and the new lists bound under the names above).

`Q_UNCACHED_SEARCH_2` keeps its exact meaning: the refactor only replaces the gender, Torah level, calendar and age clauses with the fragments' text.

- [ ] **Step 1: Write the failing tests**

`tests/test_search_predicates.py`:

```python
def test_the_deck_query_means_what_it_meant():
    """The fragments replace the clauses word for word: the query's text
    with whitespace collapsed is the text it had on 20 Oct."""
    from service.search.sql import Q_UNCACHED_SEARCH_2
    assert _squash(Q_UNCACHED_SEARCH_2) == SNAPSHOT

def test_the_deck_and_the_alert_read_torah_level_the_same_way():
    from service.search import predicates as pr
    from service.search.sql import Q_UNCACHED_SEARCH_2
    assert _squash(pr.torah_level_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)
    assert _squash(pr.calendar_sql('p')) in _squash(Q_UNCACHED_SEARCH_2)
```

`SNAPSHOT` is a module constant: the squashed text of `Q_UNCACHED_SEARCH_2` captured before the refactor (Step 3 records it first). Also `test_an_unset_field_is_not_a_mismatch` (a prospect with no `shabbat` passes `shabbat_sql` with `['saturday-only']`), `test_the_base_leaves_out_who_the_deck_leaves_out` (hidden, held for verification, no photo, staff, blocked, unmatched: each fails `deck_base_sql`).

`tests/test_matchmaker_criteria.py`:

```python
def test_every_country_maps_to_a_continent():
    import json, pycountry
    table = json.loads((ROOT / 'service/matchmaker/continents.json').read_text(encoding='utf-8'))
    assert {c.alpha_2 for c in pycountry.countries} == set(table)
    assert (region_of('US'), region_of('JM'), region_of('MX'), region_of('BR'),
            region_of('UG'), region_of('GB'), region_of('RU'), region_of('TR'), region_of('FJ')) == (
        'north-america', 'north-america', 'north-america', 'south-america',
        'africa', 'europe', 'europe', 'asia', 'oceania')

def test_a_full_list_is_no_filter():
    c = clean_member_criteria(dict(age_min=26, age_max=34, torah_levels=['learning', 'beginner', 'intermediate', 'experienced']))
    assert c['torah_levels'] == []

@pytest.mark.parametrize('raw,field', [
    (dict(age_min=17, age_max=30), 'age_min'), (dict(age_min=40, age_max=30), 'age_min'),
    (dict(countries=['Narnia']), 'countries'), (dict(shabbats=['sunday']), 'shabbats'),
    (dict(polygyny=['open']), 'polygyny'),
])
def test_a_bad_criterion_is_refused(raw, field):
    with pytest.raises(MatchmakerError) as e:
        clean_member_criteria({'age_min': 26, 'age_max': 34, **raw})
    assert e.value.reason == 'bad_criteria' and e.value.extra == {'field': field}

def test_the_words_match_the_export():
    assert summary_line(dict(age_min=26, age_max=34, countries=[], regions=[])) == 'Ages 26 to 34, anywhere.'
    assert visitor_words(dict(looking_for='man', age_min=26, age_max=34, region='north-america')) == \
        'a man aged 26 to 34 in North America'
```

Plus `test_choosing_countries_clears_a_region`.

- [ ] **Step 2: Run them to verify they fail.** Expected: collection errors, `No module named 'service.search.predicates'`.
- [ ] **Step 3: Implement.** First record `_squash(Q_UNCACHED_SEARCH_2)` (whitespace runs to one space) as the test's constant, then move the 4 clauses into `predicates.py` and interpolate them back, then write the rest to the interfaces above.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_search.py` if present and every `tests/test_*search*.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/search/predicates.py service/search/sql/__init__.py service/matchmaker/regions.py service/matchmaker/continents.json service/matchmaker/criteria.py tests/test_search_predicates.py tests/test_matchmaker_criteria.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): criteria, continents and the predicates the deck and the alerts share" -m "Refs: TEC-1845"
```

### Task 4: The emails and pushes, through the outbox, with 2 new recipients

**Files:**
- Create: `service/matchmaker/mail.py`
- Modify: `service/campaigns/outbox.py` (`enqueue_for_recommendation`, `enqueue_for_mentor_link`, `_refusal`), `tests/email_samples.py`, `tests/conftest.py` (`outbox_rows` if Events has not added it)
- Test: `tests/test_matchmaker_mail.py` (create)

**Interfaces:**
- Consumes: `emails.base.render`, `title_image`, `button`, `chip`, `callout`, `is_suppressed_send`; `service.campaigns.held.queue`, `held.para`, `held.footer`, `held.list_unsubscribe`; `outbox.enqueue_for_lead`; `service.unsubscribe.make_url`; `service.config.WEB_BASE_URL`, `EMAIL_DOMAIN`; `criteria.visitor_words`; `service.notifications.send_to_user_safe`, `_has_live_subscription`, `_allowed_for_event`, `_email_allowed_for_event`; `service.campaigns.held.after_commit`.
- Produces:
  - In `service.campaigns.outbox`: `enqueue_for_recommendation(tx, *, campaign, campaign_id, recommendation_id: int, email, subject, html, from_addr) -> Optional[int]` and `enqueue_for_mentor_link(tx, *, campaign, campaign_id, mentor_link_id: int, email, subject, html, from_addr) -> Optional[int]`, both exempt with no List-Unsubscribe, deduped on their 0073 index. `_refusal` reads `service.matchmaker.CAMPAIGN_SWITCHES` for any recipient (`'switched_off'`); a recommendation row is refused `'suppressed'` when suppressed and `'member_now'` when the address has since joined; a mentor link row `'withdrawn'` once the link is revoked.
  - In `service.matchmaker.mail`: `FROM_ADDR = f'support@{EMAIL_DOMAIN}'`; `TITLES: dict[str, tuple[str, str, int]]` (stem, alt, natural CSS width, measured on 20 Oct with `scripts/render-email-titles.mjs`):

    | Key | Stem | Alt | Line breaks | Width | Replaces the drawn heading |
    |---|---|---|---|---|---|
    | alert | `title-alert-fits` | New people who fit. | New people / who fit. | 274 | 4.1, 4.2, 4.3 "2 new members fit what you are looking for" (a count) |
    | visitor_confirm | `title-alert-confirm` | Turn on your alert. | Turn on / your alert. | 252 | 4.4, verbatim with a full stop |
    | visitor_alert | `title-alert-joined` | Someone who fits joined. | Someone who / fits joined. | 329 | 4.5 "Someone who fits what you are looking for joined Ahavah" (too long) |
    | recommend | `title-recommend` | Someone thought of you. | Someone / thought / of you. | 218 | 5.1 "Hannah thinks Ahavah could be right for you" (a name) |
    | intro | `title-introduction` | An introduction. | An / introduction. | 319 | 5.2 "Hannah thinks you and Miriam might be a good fit" (names) |
    | mentor_invite | `title-mentor-invite` | Be a mentor on Ahavah. | Be a mentor / on Ahavah. | 289 | 6.1 "Rivka invited you to be a mentor on Ahavah" (a name) |

    Every title but 4.4's is a NEW LINE. The drawn heading that carries a name or a count becomes the first body line under the title, at body size.
  - Builders, each `-> tuple[str, str]` (subject, html), every name and note through `html.escape`:
    - `alert_email(n: int, cta_url: str, stop_url: str, *, likes: int = 0) -> ...`: chip `New members` (`This week` when `likes`), the line `'1 new member fits what you are looking for'` or `'{n} new members fit what you are looking for'`, `We never name anyone in an email. Open Ahavah to see them.`, button `See who joined` (`{WEB_BASE_URL}/discover?fits=1`); with `likes`, the 4.3 block (`'{likes} people are also waiting for your answer'`, `'1 person is also waiting for your answer'` NEW LINE, link `See who liked you` to `{WEB_BASE_URL}/matches?tab=likes`) and the footer `One email for both, at most once a day. Change it in Settings, under Notifications.`; without, `You set this alert in Ahavah. Change it in Settings, under Notifications.`; both end with `Stop these emails` (`stop_url`). Subject: the count line.
    - `visitor_confirm_email(words: str, confirm_url: str, first_name: Optional[str]) -> ...`: chip `Your alert`, `'Hello {first_name}.'` when given (NEW LINE), `'You asked us to email you when someone who fits joins Ahavah: {words}.'`, button `Turn on my alert`, footer `If this was not you, ignore this email and we will not send anything else.`. Subject `Turn on your Ahavah alert` (NEW LINE).
    - `visitor_alert_email(n: int, first_name: Optional[str], stop_url: str) -> ...`: chip `Your alert`, the greeting, `'1 new member this week. Join to see who, and we will carry over what you are looking for.'` (`'{n} new members this week. ...'` NEW LINE), button `Join to see them` (`{WEB_BASE_URL}/auth/sign-up?from=alert`), `Ahavah is matchmaking for Torah-observant believers who hope to marry.`, footer `You asked us to tell you when someone who fits joins.` and `Stop these emails`. Subject `Someone who fits what you are looking for joined Ahavah`.
    - `recommend_email(sender: str, note: str, cta_url: str) -> ...`: `'{sender} thinks Ahavah could be right for you.'`, the note in quotes in a panel with the sender's first name under it, `Ahavah is matchmaking for Torah-observant believers who hope to marry.`, button `Have a look`, footer `'{sender} gave us your email to send this once. We have not shared anything about you, and we will not email you again unless you join.'`. Subject `'{sender} thinks Ahavah could be right for you'`.
    - `intro_email(introducer: str, other: str, cta_url: str, unsub_url: str) -> ...`: chip `Introduction`, `'{introducer} thinks you and {other} might be a good fit.'`, `'Open Ahavah to see {other} and {introducer}’s note, then decide privately. Nobody is told if you say no.'`, button `See the introduction`, footer `You get introduction emails because you are a member of Ahavah. Change this in Settings, under Notifications.` with the notifications unsubscribe. Subject `'{introducer} thinks you and {other} might be a good fit'`.
    - `mentor_invite_email(single: str, pronoun: Literal['she', 'he', 'they'], accept_url: str) -> ...`: chip `Mentor invitation`, `'{single} invited you to be a mentor on Ahavah.'`, `'As a mentor you see {single}’s matches as {pronoun} sees them, and only the conversations {pronoun} chooses to share, read only. You never see anyone else.'` (`they see` and `they choose` for `they`), button `Accept and sign in`, `'{single} can end this at any time.'`, footer `'If you do not know {single}, ignore this email and nothing will happen.'`. Subject `'{single} invited you to be a mentor on Ahavah'`. The pronoun comes from `person.gender_id` (Woman `she`, Man `he`, else `they`).
  - Links, all to web pages that act by a script call, never to the API: `confirm_url(token) = f'{WEB_BASE_URL}/alerts/confirm/{token}'`, `stop_url(token) = f'{WEB_BASE_URL}/alerts/stop/{token}'`, `mentor_accept_url(token) = f'{WEB_BASE_URL}/mentor?invite={token}'`, `intro_url(intro_id) = f'{WEB_BASE_URL}/matches?intro={intro_id}'`.
  - Pushes, each `-> dict(title, body, url, tag)` with title `Ahavah`: `alert_push(n)` (body 1.11 or 1.12, url `/discover?fits=1`, tag `mm-alert`), `intro_push(introducer, other)` (body the 5c heading, url `/matches?intro={id}`, tag `mm-intro-{id}`), `introducer_push(a, b)` (body `'{a} and {b} both said yes.'`, url `/matches`, tag `mm-told-{id}`). `push_after_commit(person_id: int, push: dict, switch: str) -> None` runs `send_to_user_safe` through `held.after_commit` only while `switch_on(switch)`.
  - Proof previews, each `(to: str) -> tuple[str, str]` with sample data only (Hannah, Miriam, Rivka; 2 members; 5 likes): `preview_alert_several`, `preview_alert_one`, `preview_alert_with_likes`, `preview_visitor_confirm`, `preview_visitor_alert`, `preview_recommend`, `preview_intro`, `preview_mentor_invite`.

- [ ] **Step 1: Write the failing test** `tests/test_matchmaker_mail.py`:

```python
def test_the_email_links_are_web_pages_not_the_api():
    from service.config import API_BASE_URL, WEB_BASE_URL
    from service.matchmaker import mail
    for url in (mail.confirm_url('t' * 32), mail.stop_url('t' * 32), mail.mentor_accept_url('t' * 32)):
        assert url.startswith(WEB_BASE_URL) and API_BASE_URL not in url

def test_names_and_notes_are_escaped_in_every_email():
    from service.matchmaker import mail
    evil = '<script>x</script>'
    for _, html in (mail.recommend_email(evil, evil, 'https://ahavah.app/i/X'),
                    mail.intro_email(evil, evil, 'https://ahavah.app/m', 'https://ahavah.app/u'),
                    mail.mentor_invite_email(evil, 'she', 'https://ahavah.app/mentor')):
        assert '<script>' not in html

def test_the_alert_names_nobody_and_counts():
    subject, html = mail.alert_email(2, 'https://ahavah.app/discover?fits=1', 'https://ahavah.app/alerts/stop/t')
    assert subject == '2 new members fit what you are looking for'
    assert 'We never name anyone in an email.' in html and 'See who joined' in html

def test_the_likes_block_says_one_email_for_both():
    _, html = mail.alert_email(1, 'u', 's', likes=5)
    assert '5 people are also waiting for your answer' in html
    assert 'One email for both, at most once a day.' in html

def test_a_recommendation_goes_to_its_own_recipient_through_the_outbox(matchmaker_schema, outbox_rows): ...
    # a recommendation row, enqueue_for_recommendation -> one row, recommendation_id set, person_id and lead_id None, exempt
def test_a_switched_off_email_is_skipped_at_send_time(outbox_drain, monkeypatch): ...
    # queue an mm_intro row for a member, delenv AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED, drain -> skipped, 'switched_off'
def test_a_revoked_mentor_link_is_not_mailed(outbox_drain): ...      # 'withdrawn'
def test_a_recommended_single_who_joined_is_not_mailed(outbox_drain, make_person): ...   # 'member_now'

def test_every_email_is_in_the_phone_check():
    from tests.email_samples import SAMPLES
    names = {s['name'] for s in SAMPLES}
    assert {'mm_alert_several', 'mm_alert_one', 'mm_alert_with_likes', 'mm_visitor_confirm',
            'mm_visitor_alert', 'mm_recommend', 'mm_intro', 'mm_mentor_invite'} <= names
```

Add the 8 rows to `tests/email_samples.py` from the previews (`add('mm_alert_several', 'service/matchmaker/mail.py alert_email', 'member', ...)`; the visitor emails and the recommendation and mentor invite as `'lead'`).

- [ ] **Step 2: Run them to verify they fail.** Run: `tests/test_matchmaker_mail.py` and `tests/test_email_renders_on_a_phone.py`. Expected: failures; the phone test fails on the 6 missing title images until Task 17 has synced them, so this task's run of it uses `pytest -k "not mm_"` and Task 17 runs it whole.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_email_outbox.py`, `tests/test_email_outbox_cron.py`, `tests/test_tool_mail.py` and `tests/test_event_mail.py` to prove the outbox change broke nothing. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/mail.py service/campaigns/outbox.py tests/email_samples.py tests/conftest.py tests/test_matchmaker_mail.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the alert, introduction and mentor emails and pushes, through the outbox" -m "Refs: TEC-1845"
```

### Task 5: A member's alert: save, pause, resume and stop

**Files:**
- Create: `service/matchmaker/alerts.py`
- Modify: `service/api/matchmaker_routes.py`, `duotypes/__init__.py` (`PutMemberAlert`)
- Test: `tests/test_member_alerts.py` (create)

**Interfaces:**
- Consumes: `criteria.clean_member_criteria`, `summary_line`; `service.search.saved_age_band`; `service.leads.new_token`, `token_hash`.
- Produces, in `service.matchmaker.alerts`:
  - `member_alert(tx, person_id) -> dict`: `{alert: None | {criteria, notify_push, notify_email, state: 'on' | 'paused', summary}, defaults: {age_min, age_max}}`, the defaults from the saved age band (1.1 "filled from the member's current filters and saved age band"; the web adds the filters it holds).
  - `save_member_alert(tx, person_id, raw: dict, *, notify_push: bool, notify_email: bool) -> dict`: creates or replaces; confirmed at once (a member's address is proved); `counted_since` stays when the alert already existed, so a saved change never re-counts; a stop token is issued once. Returns `member_alert`.
  - `pause(tx, person_id)`, `resume(tx, person_id)` (1.10: "What you are looking for is kept"), `delete_member_alert(tx, person_id)`.
- Routes, all 404 while `matchmaker_live` or `matchmaker_alerts` is off, member session: `GET /matchmaker/alert`, `PUT /matchmaker/alert` (body `PutMemberAlert {criteria, notify_push, notify_email}`), `POST /matchmaker/alert/pause`, `POST /matchmaker/alert/resume`, `DELETE /matchmaker/alert`. A 400 carries `{error: 'bad_criteria', field}`.

- [ ] **Step 1: Write the failing test** `tests/test_member_alerts.py`, `pytestmark = pytest.mark.usefixtures('matchmaker_schema', 'matchmaker_live')`: `test_no_alert_offers_the_saved_age_band` (a member with band 26 to 34: `alert` None, `defaults` `{age_min: 26, age_max: 34}`), `test_saving_turns_it_on_and_says_so` (`state 'on'`, `summary 'Ages 26 to 34, anywhere.'`), `test_saving_again_keeps_the_count_window`, `test_pausing_keeps_what_you_are_looking_for`, `test_a_bad_criterion_says_which` (`polygyny` -> 400, `field 'polygyny'`), `test_closed_until_its_switch` (delenv `AHAVAH_MATCHMAKER_ALERTS_ENABLED` -> 404 on all 5 routes), `test_an_onboardee_has_no_alert` (an onboardee session -> 401).
- [ ] **Step 2: Run it to verify it fails.** Expected: 404s and `No module named 'service.matchmaker.alerts'`.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/alerts.py service/api/matchmaker_routes.py duotypes/__init__.py tests/test_member_alerts.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): a member saves, pauses and stops their alert" -m "Refs: TEC-1845"
```

### Task 6: A visitor's alert: ask, confirm by link, stop, and carried into sign-up

**Files:**
- Modify: `service/matchmaker/alerts.py`, `service/api/matchmaker_routes.py`, `duotypes/__init__.py` (`PostVisitorAlert`, `PostAlertToken`), `service/person/__init__.py` (finish-onboarding, after `link_leads_to_person`)
- Test: `tests/test_visitor_alerts.py` (create)

**Interfaces:**
- Consumes: `service.leads.record_lead`, `confirm_lead`, `clean_email`, `mail_refusal`, `new_token`, `token_hash`, `ALERT_VISITOR`; `criteria.clean_visitor_criteria`, `visitor_words`; `mail.visitor_confirm_email`, `confirm_url`, `stop_url`; `outbox.enqueue_for_lead`.
- Produces, in `service.matchmaker.alerts`:
  - `CONFIRM_WINDOW = timedelta(days=7)`; `MAX_RESENDS = 3`.
  - `ask(tx, *, email: str, criteria: dict, first_name: Optional[str], now=None) -> dict`: `{state: 'check_email', email}`. Records the `alert:visitor` lead (no marketing consent: the alert is requested mail), creates or replaces the one alert of that lead (unconfirmed, `confirm_by` 7 days on, a new confirm token), queues `mm_visitor_confirm` through `enqueue_for_lead(marketing=False)` with `campaign_id` `{alert_id}:{resends}`. An address that belongs to a member writes nothing and answers the same (they set alerts in the app). Asking again while unconfirmed is "Send it again": `resends` up, at most 3 (`MatchmakerError('too_many_tries', 429)`, 3.9). Asking again once confirmed replaces the criteria and answers `{state: 'already_on'}` (3.5).
  - `confirm(tx, token, now=None) -> dict`: `{state: 'confirmed' | 'already_on', stop_token}`; past `confirm_by` raises `MatchmakerError('expired', 410)` (3.6); sets `confirmed_at` once, `confirm_lead(tx, lead_id, 'link')`, issues the stop token and returns it so the page can offer "Stop these emails" (3.7).
  - `stop(tx, token) -> dict`: `{state: 'stopped'}`. A visitor's alert is deleted; a member's alert turns its email off and keeps the rest (a member's "Stop these emails" link carries the same kind of token). An unknown token answers `stopped` too.
  - `adopt_visitor_alert(tx, person_id) -> None`: at finish-onboarding, a confirmed visitor alert of a lead that `link_leads_to_person` has just linked becomes the member's alert (`person_id` set, `lead_id` cleared, criteria `{age_min, age_max, regions: [region] or []}`, push off, email on), unless the member already has one; behind a savepoint, never undoing the sign-up.
- Routes, 404 while `matchmaker_live` or `matchmaker_visitor_alerts` is off, no auth, `Cache-Control: no-store`: `POST /alerts` (body `PostVisitorAlert {email, looking_for, age_min, age_max, region?, first_name?, website?, signup_stamp?}`; `'10 per hour; 30 per day'` per IP and `shared_recipient_limit`; a `mail_refusal` refusal answers `{state: 'check_email', email}` and writes nothing; 201), `POST /alerts/confirm` (body `{token}`), `POST /alerts/stop` (body `{token}`; open while live, whichever surface switch is set, so a stop link always works).

- [ ] **Step 1: Write the failing test** `tests/test_visitor_alerts.py`:

```python
def test_a_visitor_asks_and_is_told_to_check_their_email(client, outbox_rows):
    r = client.post('/alerts', json=dict(email='hannah@ahavah-test.invalid', looking_for='man',
                                         age_min=26, age_max=34, region='north-america', first_name='Hannah'))
    assert r.status_code == 201 and r.get_json() == {'state': 'check_email', 'email': 'hannah@ahavah-test.invalid'}
    [row] = outbox_rows('mm_visitor_confirm')
    assert row['lead_id'] is not None and 'a man aged 26 to 34 in North America' in row['payload']['html']
    lead = _lead('hannah@ahavah-test.invalid')
    assert lead['source'] == 'alert:visitor' and lead['marketing_consent'] is False

def test_confirming_turns_it_on_and_confirms_the_lead(client): ...
def test_the_link_used_again_says_already_on(client): ...
def test_an_expired_link_says_so(client): ...                 # confirm_by in the past -> 410 expired
def test_send_it_again_stops_after_3(client): ...             # the 4th ask while unconfirmed -> 429 too_many_tries
def test_stopping_deletes_a_visitor_alert(client): ...
def test_a_members_address_writes_nothing_and_answers_the_same(client, make_person): ...
def test_a_refused_address_is_answered_as_a_send(client, monkeypatch): ...
def test_a_bad_region_or_age_is_refused(client): ...          # 400 bad_criteria with the field
def test_a_visitor_who_joins_keeps_their_alert_as_a_member(client, finish_onboarding): ...
    # confirm, then finish onboarding with the same address -> match_alert.person_id set, criteria regions ['north-america'], notify_push False
def test_closed_until_its_switch(client, monkeypatch): ...    # POST /alerts 404; POST /alerts/stop still 200
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above; `PostVisitorAlert.looking_for` is `Literal['man', 'woman']` and `first_name` 1 to 40 characters through `fields`-style cleaning (control characters stripped, trimmed).
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_leads.py` and `tests/test_finish_onboarding*.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/alerts.py service/api/matchmaker_routes.py duotypes/__init__.py service/person/__init__.py tests/test_visitor_alerts.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): a visitor asks to be told, confirms by link and keeps the alert on joining" -m "Refs: TEC-1845"
```

### Task 7: The notices: daily for members, weekly for visitors, one email for both reasons and new fits first

**Files:**
- Create: `service/matchmaker/notices.py`
- Modify: `service/cron/returnmail/__init__.py` (`JOBS`, before `likes_waiting`), `emails/likes_waiting_weekly.py` (`_Q_DUE`, `queue_due`), `service/search/__init__.py` and `service/search/sql/__init__.py` (`new_fit_ids` ranking), `service/api/__init__.py` (`@aget('/search')`, line 370, reads `fits_first`), `tests/test_search_predicates.py` (the snapshot)
- Test: `tests/test_alert_notices.py` (create)

**Interfaces:**
- Consumes: `criteria.fits_sql`, `fit_params`; `mail.alert_email`, `visitor_alert_email`, `alert_push`, `push_after_commit`, `stop_url`; `held.queue`, `outbox.enqueue_for_lead`; `service.spotlight.restdays.is_rest_period`; `likes_waiting_weekly._Q_DUE`'s likes count; `service.notifications._has_live_subscription`.
- Produces, in `service.matchmaker.notices`:
  - `MEMBER_HOUR_UTC = 12`; `VISITOR_WEEKDAY = 3` (Thursday); `VISITOR_HOUR_UTC = 12`.
  - `queue_member_notices(tx, now) -> int`: at the first tick at or after 12:00 UTC of a UTC day, unless `is_rest_period(now)`, for every active member alert not sent today, counts the members `fits_sql(owner='%(owner)s')` finds with `since = counted_since`, `until = now`; with 1 or more: push (alert push on, a live subscription, `matchmaker_alert_push`), email (`mm_alert`, campaign_id `{alert_id}:{now:%Y%m%d}`, through `held.queue`, scope `notifications`) when the alert's email is on or push could not reach them, with the likes block when the member has likes newer than their last likes-waiting email and `likes_told_at`; writes `match_alert_notice` (`audience 'member'`, the window, the channels), then `counted_since = now`, `last_sent_at = now` and `likes_told_at = now` when the block went. A member whose account is deactivated or deleting gets nothing.
  - `queue_visitor_notices(tx, now) -> int`: on Thursday from 12:00 UTC, unless a rest period, once per ISO week per alert, for confirmed active visitor alerts whose lead is not converted: the count with `owner=None`, gender `looking_for`, region codes; email `mm_visitor_alert` through `enqueue_for_lead(marketing=True, requested=True)`, campaign_id `{alert_id}:{iso week}`; the notice row (`audience 'visitor'`) and the window moved on.
  - `new_fit_ids(tx, person_id) -> list[int]`: the members the latest notice's window counted who still fit, for "See who joined".
  - `JOBS` gains `('mm_member_alerts', notices.queue_member_notices)` and `('mm_visitor_alerts', notices.queue_visitor_notices)` before `('likes_waiting', ...)`.
- In `emails/likes_waiting_weekly.py`: `_Q_DUE`'s "newest like" test also compares with `match_alert.likes_told_at`; `queue_due` passes `new_fits=0` for a member whose alert is active with its email on.
- In search: `GET /search?fits_first=1`; `get_search` and `_uncached_search_results` take `fits_first: bool = False`; when True on the first page, `new_fit_ids` is bound as `%(new_fit_ids)s::INT[]` (an empty array otherwise) and `(p.id = ANY(%(new_fit_ids)s::INT[])) DESC` becomes the first key of `Q_UNCACHED_SEARCH_2`'s ORDER BY; an empty array changes no order. Task 3's snapshot moves: the constant becomes the new squashed text, and the test also asserts that the old text is the new one with exactly this key removed.

- [ ] **Step 1: Write the failing test** `tests/test_alert_notices.py`:

```python
def test_a_new_member_who_fits_brings_one_notice_a_day(member_pair, make_person, add_photo, outbox_rows): ...
    # an alert for a woman 26 to 34; a man of 30 joins with a photo; queue_member_notices at 12:00 UTC -> 1;
    # the email's line '1 new member fits what you are looking for'; a second run that day -> 0

def test_nothing_before_12_or_inside_a_rest_period(monkeypatch): ...

def test_the_count_leaves_out_who_the_deck_leaves_out(make_person, add_photo, sign_in): ...
    # the owner, a staff account, one hidden from strangers, one held for verification, one with no photo,
    # one blocked with the owner, one unmatched with the owner -> 0; one plain newcomer -> 1

def test_criteria_narrow_the_count(make_person): ...
    # wants_children 'yes' leaves out a newcomer who answered 'no' and keeps one who did not answer

def test_push_when_it_can_reach_them_else_email(push_member, monkeypatch): ...
def test_the_likes_ride_in_the_alert_and_the_likes_email_skips_them(make_person, outbox_rows, monkeypatch): ...
    # Thursday 12:00: likes waiting and a new fit -> one mm_alert with the likes block; likes_waiting.queue_due -> 0 for her
def test_beside_an_alert_the_likes_email_drops_its_fit_line(make_person, outbox_rows, monkeypatch): ...

def test_a_visitor_hears_once_a_week(client, make_person, add_photo, outbox_rows): ...
    # a confirmed visitor alert, a fitting man in North America joins; Wednesday 12:00 -> 0; Thursday 12:00 -> 1; again -> 0

def test_a_visitor_who_joined_hears_nothing_as_a_visitor(client, finish_onboarding): ...
def test_see_who_joined_puts_the_new_fits_first(client, sign_in, member_pair): ...
    # after a notice, GET /search?n=10&o=0&fits_first=1 -> the counted newcomer is the first card
def test_both_jobs_run_before_the_likes_email():
    from service.cron.returnmail import JOBS
    names = [n for n, _ in JOBS]
    assert names.index('mm_member_alerts') < names.index('likes_waiting')
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_likes_waiting_weekly.py`, `tests/test_search_predicates.py` and every `tests/test_*search*.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/notices.py service/cron/returnmail/__init__.py emails/likes_waiting_weekly.py service/search/__init__.py service/search/sql/__init__.py service/api/__init__.py tests/test_search_predicates.py tests/test_alert_notices.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the alert notices, one email for both reasons and new fits first" -m "Refs: TEC-1845"
```

### Task 8: Recommend Ahavah to a single

**Files:**
- Create: `service/matchmaker/recommend.py`
- Modify: `service/api/matchmaker_routes.py`, `duotypes/__init__.py` (`PostRecommendation`)
- Test: `tests/test_recommendations.py` (create)

**Interfaces:**
- Consumes: `service.leads.clean_email`, `mail_refusal`; `service.referrals.mint_person_code`; `service.matchmaker.address_key`, `first_name`; `mail.recommend_email`; `outbox.enqueue_for_recommendation`; `antiabuse.antirude.profile.is_rude`, `antiabuse.romancescam.analyze_message`.
- Produces, in `service.matchmaker.recommend`:
  - `WEEKLY_LIMIT = 5`; `DEFAULT_NOTE = 'I think you would be a good fit for Ahavah.'`; `NOTE_MAX = 500`.
  - `note_flag(note: str) -> Optional[str]` (shared with Task 9): `'rude'`, `'scam'` (0.5 or more), `'contact'` (a URL, an email address or 7 or more digits), else None.
  - `week_start(now) -> datetime` (Monday 00:00 UTC) and `next_week_day() -> str` (`'Monday'`).
  - `recommend(tx, *, sender: dict, email: str, note: str, now=None) -> dict`: `sender` is `{person_id, first_name, key}` (a member: `address_key` of their address and their first name; a visitor: the session's address and the first name they typed). Answers `{state: 'sent'}` or `{state: 'held'}` (a flagged note waits for Moderation > Text; the screen shows 5a.4 either way, as the single must not learn of moderation). Refusals that answer `sent` and write nothing: the address belongs to a member, the address was recommended before by anyone (`recipient_key`), the address is the sender's own. `MatchmakerError('limit', 429, {'from': 'Monday'})` at 5 in the sender's week (5a.5). A member's email carries their referral link `{WEB_BASE_URL}/i/{code}`; a visitor's carries `{WEB_BASE_URL}/`. The row stores `recipient_key`, the address and the note until the sweep (Task 14).
  - `send_recommendation(tx, rec_id: int) -> Optional[int]`: queues `mm_recommend` (`campaign_id` `{rec_id}`); used here and by the approval in Task 13.
- Routes, 404 while `matchmaker_live` or `matchmaker_introductions` is off: `POST /recommendations` (body `PostRecommendation {email, note?, first_name?, website?, signup_stamp?}`; auth required with `expected_onboarding_status=None`, so a member or the onboardee session `/check-otp` leaves (5a.8); a visitor must send `first_name`; `'10 per hour'` per IP and `shared_recipient_limit`; `mail_refusal` for the recipient before the transaction, a refusal answered `{state: 'sent'}`); `GET /recommendations/allowance` (`{left, from}` for the form's limit state).

- [ ] **Step 1: Write the failing test** `tests/test_recommendations.py`:

```python
def test_a_member_recommends_a_single_with_their_invite_link(client, make_person, sign_in, outbox_rows): ...
    # 201 {'state': 'sent'}; one mm_recommend row with recommendation_id; '/i/' in the html; the note quoted

def test_every_refusal_answers_as_a_send(client, make_person, sign_in, outbox_rows):
    member = make_person(email='member@ahavah-test.invalid')
    me = sign_in(make_person(name='Hannah Levi', email='hannah@ahavah-test.invalid'))
    bodies = [client.post('/recommendations', headers=me, json=dict(email=e)).get_json()
              for e in ('member@ahavah-test.invalid', 'single@ahavah-test.invalid',
                        'single@ahavah-test.invalid', 'hannah@ahavah-test.invalid')]
    assert bodies == [{'state': 'sent'}] * 4
    assert len(outbox_rows('mm_recommend')) == 1

def test_an_address_hears_from_us_once_whoever_sends(client, make_person, sign_in, outbox_rows): ...
def test_the_sixth_in_a_week_is_refused_until_monday(client, make_person, sign_in): ...   # 429 limit, from 'Monday'
def test_a_flagged_note_waits_and_sends_nothing(client, make_person, sign_in, outbox_rows): ...
    # a note with a phone number -> {'state': 'sent'}; status 'held', flag_reason 'contact'; no outbox row
def test_a_visitor_recommends_after_the_code_step(client, tool_visitor, outbox_rows): ...
    # the onboardee session with first_name 'Ruth' -> sent; the email says 'Ruth thinks Ahavah could be right for you.'
def test_a_visitor_must_give_a_first_name(client, tool_visitor): ...   # 400 bad_first_name
def test_closed_until_its_switch(client, make_person, sign_in, monkeypatch): ...
```

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above. Lock on `pg_advisory_xact_lock(hashtext('mm-rec:' || sender_key))` so two sends at once cannot pass the limit.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/recommend.py service/api/matchmaker_routes.py duotypes/__init__.py tests/test_recommendations.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): recommend Ahavah to a single, once per address" -m "Refs: TEC-1845"
```

### Task 9: Suggest two members: who the introducer can see, the suggestion and its notices

**Files:**
- Create: `service/matchmaker/introductions.py`
- Modify: `service/api/matchmaker_routes.py`, `duotypes/__init__.py` (`PostIntroduction`)
- Test: `tests/test_introductions_suggest.py` (create)

**Interfaces:**
- Consumes: `recommend.note_flag`, `week_start`; `mail.intro_email`, `intro_push`, `push_after_commit`, `intro_url`; `held.queue`; `service.notifications._allowed_for_event`, `_email_allowed_for_event` (the `match` kind); `Q_MAP_MARKERS`'s visibility predicate; `publishing_queue`; `photos_visible_to`.
- Produces, in `service.matchmaker.introductions`:
  - `WEEKLY_LIMIT = 5`; `OPEN_FOR = timedelta(days=14)`.
  - `REACH = ('match', 'liked', 'liked_you', 'viewed_you', 'map', 'spotlight')` with labels `Your match`, `You liked them`, `Liked you` (NEW LINES), `Viewed your profile`, `On the map`, `In the weekly Spotlight` (5b.2). `visible_sql(introducer: str) -> str`: a member the introducer has matched, liked, been liked by or been viewed by, who shows on the introducer's map (the `Q_MAP_MARKERS` predicates), or who was the subject of a published Spotlight post in the last 8 weeks and is still opted in; never blocked or unmatched with the introducer; activated, a member, not hidden from strangers.
  - `candidates(tx, introducer_id, for_uuid, q: str = '', limit: int = 20) -> dict`: `{for: {first_name}, people: [{uuid, first_name, age, place, photo_uuid?, reach: str, suggested_before: bool}], left: int}`, people visible to the introducer whose gender the first person looks for and who look for the first person's gender, excluding the first person and anyone already matched or unmatched with them; `q` matches the first name's start, case-insensitive; `for_uuid` must itself be visible (`MatchmakerError('not_found', 404)` otherwise, the same answer as an unknown uuid). `suggested_before` (5b.6) is true for anyone in an earlier introduction by this introducer.
  - `suggest(tx, introducer_id, a_uuid, b_uuid, note: str, now=None) -> dict`: `{state: 'sent' | 'held', left}`. Checks under `pg_advisory_xact_lock(hashtext('mm-intro:' || introducer_id))`: both visible; `MatchmakerError('limit', 429, {'from': 'Monday'})` at 5 this week (5b.9); `('suggested_before', 409)` when either was in an earlier introduction by this introducer. Hidden refusals, answered `sent` with nothing created: the two are blocked, unmatched or already matched with each other, either has a live open introduction with the other, or either has `no_mentor_shared_matches` while the other shares a conversation. A flagged note: status `held` (5b.10). Otherwise `open`, `opened_at`, `closes_at = now + 14 days`, and `notify_both(tx, intro_id)`.
  - `notify_both(tx, intro_id) -> None`: for each of the two, push `intro_push` (`matchmaker_intro_push`, the member's Matches push setting and a live subscription) and email `mm_intro` through `held.queue` (`campaign_id` `{intro_id}:{a|b}`, scope `notifications`, the member's Matches email setting); used here and by the approval in Task 13.
- Routes, 404 while `matchmaker_live` or `matchmaker_introductions` is off, member session: `GET /introductions/candidates?for=&q=`, `POST /introductions` (body `PostIntroduction {a_uuid, b_uuid, note}`, note 1 to 500 characters), `GET /introductions/allowance` (`{left, from}`).

- [ ] **Step 1: Write the failing test** `tests/test_introductions_suggest.py`: `test_the_picker_lists_only_people_the_introducer_can_see` (a member Daniel the introducer matched shows with reach `match`; a stranger does not; Miriam herself does not), `test_the_picker_offers_people_who_could_fit_the_first_person` (a woman is not offered for Miriam when Miriam looks for men), `test_a_name_search_narrows_the_list` (`q='jo'` keeps Josiah and Joel), `test_someone_suggested_before_is_marked`, `test_a_suggestion_tells_both_privately` (status `open`, 2 `mm_intro` rows, `closes_at` 14 days on, the note not in the email), and:

```python
def test_a_hidden_refusal_answers_as_a_send(client, introducer_with_two, outbox_rows):
    h, miriam, daniel = introducer_with_two()
    _block(miriam, daniel)
    r = client.post('/introductions', headers=h, json=dict(a_uuid=miriam['uuid'], b_uuid=daniel['uuid'], note='Both love the feasts.'))
    assert r.status_code == 201 and r.get_json()['state'] == 'sent'
    assert outbox_rows('mm_intro') == [] and _introductions(h) == []
```

plus `test_each_person_once_per_introducer` (409 `suggested_before`), `test_the_sixth_pair_in_a_week_waits_until_monday`, `test_a_flagged_note_waits_for_review` (`held`, no notices), `test_someone_the_introducer_cannot_see_is_not_found` (404, the same as an unknown uuid), `test_two_suggestions_at_once_cannot_pass_the_limit` (a thread pool at 4 left with 2 at once leaves at most 5).

`introducer_with_two` (in the test file): a member matched with Miriam and with Daniel, Miriam and Daniel looking for each other's gender.

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/introductions.py service/api/matchmaker_routes.py duotypes/__init__.py tests/test_introductions_suggest.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): suggest two members the introducer can already see" -m "Refs: TEC-1845"
```

### Task 10: The accept-or-decline card, the match from two yeses and the introducer told

**Files:**
- Modify: `service/matchmaker/introductions.py`, `service/api/matchmaker_routes.py`, `service/decisions/__init__.py` (`Q_LIST_MATCHES` gains `introduced_by`), `service/cron/returnmail/__init__.py` (`JOBS`)
- Test: `tests/test_introductions_respond.py` (create)

**Interfaces:**
- Consumes: `Q_RECORD_LIKE`'s rules (`is_unmatched_pair`, blocks); `service.notifications.notify` for the match notice; `mail.introducer_push`, `push_after_commit`; `photos_visible_to`; `service.photo_gate.gate_params`.
- Produces, in `service.matchmaker.introductions`:
  - `pending(tx, person_id, now=None) -> list[dict]`: the member's open introductions they have not answered, newest first: `{id, introducer_first_name, other: {uuid, first_name, age?, place, photo_uuids, about, gradient_seed}, note, closes_on}`, age only where the other shows it, photos only where `photos_visible_to(me, other)` (decision 9: an empty list and the seed for the gradient), `closes_on` as `'30 October'`. Also `waiting(tx, person_id)`: the ones they accepted that are still open (5c.2).
  - `respond(tx, person_id, intro_id: int, answer: Literal['accept', 'decline'], now=None) -> dict`: locks the introduction row; `{state: 'waiting'}` after a first accept (5c.2); `{state: 'matched', match_id, other_uuid}` when the second accepts: likes both ways and the `ahavah_match` row (`ON CONFLICT DO NOTHING`), status `matched`, `matched_at`, the match notice to the first acceptor (`notify(..., 'match')`) and the introducer's push (decision 8); `{state: 'gone'}` after a decline (status `closed`, nobody told). `MatchmakerError('closed', 410)` when it is closed, past `closes_at`, or the two are now blocked or unmatched (5c.4). Someone who is neither person answers 404.
  - `close_lapsed(tx, now) -> int`: open introductions past `closes_at` become `closed`, silently. `JOBS` gains `('mm_intro_close', introductions.close_lapsed)`.
  - `told(tx, person_id) -> list[dict]`: `[{id, a_first_name, b_first_name}]` matched introductions this introducer has not been shown, marked shown as they are returned (5c.8's toast).
  - `context(tx, person_id, other_uuid) -> Optional[dict]`: `{introducer_first_name, note}` for the pair's matched introduction, for the line at the top of the chat (5c.7); None when there is none or the note was erased.
- `Q_LIST_MATCHES` gains `introduced_by` (`{first_name}` or null), from the pair's matched introduction, for 5c.6's "Introduced by Hannah".
- Routes, 404 while `matchmaker_live` or `matchmaker_introductions` is off, member session: `GET /introductions/pending` (`{pending, waiting}`), `POST /introductions/<int:iid>/accept`, `POST /introductions/<int:iid>/decline`, `GET /introductions/told`, `GET /introductions/with/<uuid>`.

- [ ] **Step 1: Write the failing test** `tests/test_introductions_respond.py`:

```python
def test_both_accepting_makes_a_match_and_tells_the_introducer(client, open_intro): ...
    # a accepts -> 'waiting'; b accepts -> 'matched'; ahavah_match exists; GET /introductions/told for the introducer
    # -> one row (Miriam, Daniel), then [] on the next call; /matches for a shows introduced_by {'first_name': 'Hannah'}

def test_a_decline_tells_nobody(client, open_intro, outbox_rows): ...
    # b declines -> 'gone'; a's pending is empty; a's waiting is empty; the introducer's told is []; no outbox row, no push

def test_both_accepting_at_once_makes_one_match(client, open_intro):
    intro, ha, hb = open_intro()
    with ThreadPoolExecutor(2) as ex:
        states = sorted(f.result().get_json()['state'] for f in
                        [ex.submit(_accept, ha, intro), ex.submit(_accept, hb, intro)])
    assert states == ['matched', 'waiting'] and _match_count(intro) == 1

def test_accepting_a_closed_or_blocked_introduction_matches_nobody(client, open_intro): ...
    # past closes_at -> 410 closed; blocked after sending -> 410; unmatched pair -> 410; no ahavah_match
def test_the_card_shows_the_gradient_to_a_viewer_held_by_the_photo_gate(client, open_intro, monkeypatch): ...
def test_lapsed_introductions_close_silently(open_intro): ...
def test_someone_else_cannot_answer(client, open_intro, make_person, sign_in): ...   # 404
def test_the_chat_context_line(client, open_intro): ...   # after the match, GET /introductions/with/<b uuid> -> {'introducer_first_name': 'Hannah', 'note': ...}
```

`open_intro` (in the test file) builds Task 9's pair and posts one suggestion, returning `(intro_id, headers_a, headers_b)`.

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_decisions*.py` and `tests/test_unmatch*.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/introductions.py service/api/matchmaker_routes.py service/decisions/__init__.py service/cron/returnmail/__init__.py tests/test_introductions_respond.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): accept or not for me, a match only from two yeses" -m "Refs: TEC-1845"
```

### Task 11: The single's mentor: invite, remove, share a conversation and the notice for both people

**Files:**
- Create: `service/matchmaker/mentors.py`, `service/api/mentor_routes.py`
- Modify: `service/api/__init__.py` (register), `duotypes/__init__.py` (`PostMentorInvite`), `service/person/__init__.py` (the `no_mentor_shared_matches` field of `PATCH /profile-info`, beside `require_verified_prospects`), `service/search/sql/__init__.py` (the exclusion), `service/api/matchmaker_routes.py`, `tests/test_search_predicates.py` (the snapshot)
- Test: `tests/test_mentor_single.py` (create)

**Interfaces:**
- Consumes: `service.leads.clean_email`, `new_token`, `token_hash`, `mail_refusal`; `mail.mentor_invite_email`, `mentor_accept_url`; `outbox.enqueue_for_mentor_link`.
- Produces, in `service.matchmaker.mentors`:
  - `INVITE_TTL = timedelta(days=14)`; `RELATIONS = ('parent', 'elder', 'mentor', 'friend')`.
  - `state(tx, single_id) -> dict`: `{state: 'none' | 'invited' | 'confirmed', email?, relation?, first_name?, since?, shared: [{uuid, first_name, shared_since}]}` (6.1 to 6.5; `first_name` is the part of the mentor's address before the `@`, capitalised, until the mentor gives a name, NEW behaviour, see item 18).
  - `invite(tx, single_id, email: str, relation: str, now=None) -> dict`: one live link per single (`MatchmakerError('has_mentor', 409)`); the single's own address refused (`bad_email`, 400); queues `mm_mentor_invite` (`campaign_id` `{link_id}`). Answers `state`.
  - `cancel_invite(tx, single_id)`, `remove(tx, single_id, now=None)` (revokes the link, every live share and every mentor session's access to this single at once; deletes the mentor's notes about this single's matches; 6.6, 6.7: "They will lose access straight away.").
  - `share(tx, single_id, other_uuid, now=None) -> dict` (`{shared: True}`): needs a confirmed mentor and a match with `other_uuid` (`MatchmakerError('not_found', 404)`); `('no_mentor', 409)` without one; `('cannot_share', 409)` when the other person has `no_mentor_shared_matches` (decision 12; the web says "This conversation cannot be shared.", NEW LINE). `unshare(tx, single_id, other_uuid, now=None)`.
  - `sharing(tx, viewer_id, other_uuid) -> dict`: for either person of the pair: `{shared_by_me: bool, shared_by_them: bool, their_first_name, events: [{kind: 'shared' | 'stopped', by: 'me' | 'them', at}]}`, the events for the lines in the conversation (decision 10).
  - In search: while the searcher has `no_mentor_shared_matches`, `Q_UNCACHED_SEARCH_2` leaves out prospects with a live `shared_conversation` (`NOT EXISTS (... shared_conversation sc WHERE sc.single_person_id = p.id AND sc.revoked_at IS NULL)`, guarded on the searcher's flag); `Q_MAP_MARKERS` does the same. Task 3's snapshot moves again, as in Task 7: the old text is the new one with exactly this clause removed.
- Routes, 404 while `matchmaker_live` or `matchmaker_mentors` is off, member session: `GET /mentor`, `POST /mentor/invite` (body `PostMentorInvite {email, relation}`; `'10 per hour'` per IP and `shared_recipient_limit`; `mail_refusal` before the transaction, a refusal answered as `invited` with nothing sent), `DELETE /mentor/invite`, `DELETE /mentor`, `POST /conversations/<uuid>/share`, `DELETE /conversations/<uuid>/share`, `GET /conversations/<uuid>/sharing` (always open while live, so the notice shows even if mentors are switched off later; answers all false when nothing was ever shared). `PATCH /profile-info` accepts `no_mentor_shared_matches` (bool) whichever way the switches are set.

- [ ] **Step 1: Write the failing test** `tests/test_mentor_single.py`: `test_inviting_sends_one_invitation_and_waits` (`state 'invited'`, one `mm_mentor_invite` row with `mentor_link_id`, the accept link is the web page), `test_one_mentor_at_a_time` (409 `has_mentor`), `test_cancelling_an_invitation_ends_the_link`, `test_sharing_needs_a_confirmed_mentor_and_a_match`, and:

```python
def test_the_other_person_is_always_told(client, single_with_mentor, sign_in):
    single, match, h_single, h_match = single_with_mentor()
    client.post(f"/conversations/{match['uuid']}/share", headers=h_single)
    theirs = client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()
    assert theirs['shared_by_them'] is True and theirs['their_first_name'] == 'Rivka'
    assert [e['kind'] for e in theirs['events']] == ['shared']
    client.delete(f"/conversations/{match['uuid']}/share", headers=h_single)
    assert [e['kind'] for e in client.get(f"/conversations/{single['uuid']}/sharing", headers=h_match).get_json()['events']] == ['shared', 'stopped']
```

plus `test_a_member_who_prefers_not_cannot_have_their_conversation_shared` (409 `cannot_share`), `test_the_setting_keeps_sharers_out_of_the_deck_and_the_map`, `test_removing_a_mentor_ends_every_share_at_once`, `test_an_invitation_to_ones_own_address_is_refused`, `test_closed_until_its_switch` (every route 404, `/sharing` and the profile-info field still work while live).

`single_with_mentor` (in the test file): Rivka matched with Samuel, a confirmed mentor link and account, both signed in.

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_search_predicates.py` and `tests/test_privacy*.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/mentors.py service/api/mentor_routes.py service/api/__init__.py duotypes/__init__.py service/person/__init__.py service/search/sql/__init__.py service/api/matchmaker_routes.py tests/test_search_predicates.py tests/test_mentor_single.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): a single invites a mentor and shares one conversation at a time, and the other person is told" -m "Refs: TEC-1845"
```

### Task 12: The mentor's side: signing in, the single's matches, a note and a shared conversation

**Files:**
- Create: `service/matchmaker/mentor_view.py`
- Modify: `service/api/mentor_routes.py`, `duotypes/__init__.py` (`PostMentorSession`, `PutMentorNote`)
- Test: `tests/test_mentor_view.py` (create)

**Interfaces:**
- Consumes: `mentors` (Task 11); `service.leads.new_token`, `token_hash`, `clean_email`; the onboardee or member session `/check-otp` leaves (`s.email`); `Q_LIST_MATCHES` (as the single); `mam_message` and the unpacking in `antiabuse/lodgereport._decode_last_messages_in_place` (`erlastic.decode(binary)[3][0][3][0][1]`).
- Produces, in `service.matchmaker.mentor_view`:
  - `SESSION_TTL = timedelta(days=30)`; `message_text(binary: bytes) -> Optional[str]` (the lodgereport unpacking; None when it fails).
  - `start_session(tx, *, invite_token: Optional[str] = None, session_email: Optional[str] = None, now=None) -> dict`: `{token}`. With an invitation token (unexpired, not revoked): the address is proved; finds or creates the `mentor_account`, confirms the link, issues a token. With a signed-in session's address: issues a token when the address has a confirmed live link. Otherwise `MatchmakerError('not_a_mentor', 403)`; an expired invitation `('expired', 410)`.
  - `mentor_for(tx, token: Optional[str]) -> dict` (`{id, email}`; `('signed_out', 401)` for a missing, unknown or lapsed token; touches `last_seen_at`).
  - `singles(tx, mentor) -> dict`: `{singles: [{uuid, first_name}], ended: [{first_name}]}`, `ended` the singles whose link was revoked in the last 30 days (7.12).
  - `matches(tx, mentor, single_uuid) -> list[dict]`: the single's matches as `Q_LIST_MATCHES` gives them to the single (first name, age, photos through the single's own photo gate), each with `shared: bool` (7.4). A single this mentor does not serve, or no longer serves, raises `('access_ended', 410)`.
  - `match_detail(tx, mentor, single_uuid, match_uuid) -> dict`: `{first_name, age?, place, photo_uuids, about, shared, note?}` (7.7, 7.9); a uuid that is not one of the single's matches answers 404.
  - `conversation(tx, mentor, single_uuid, match_uuid, before: Optional[int] = None) -> dict`: `{messages: [{id, from: 'single' | 'match', text?, voice: bool, at}], single_first_name, match_first_name}`, 50 at a time from the single's archive (`mam_message.person_id = single`, `remote_bare_jid = match uuid`), oldest first; a voice message has `voice: True` and no text. `('not_shared', 403)` when the share is not live (7.9, and 7.11 when it stops while open).
  - `save_note(tx, mentor, single_uuid, match_uuid, note: str) -> None` (1 to 1000 characters, cleaned; an empty note deletes it), `note_for_single(tx, single_id, match_uuid) -> Optional[str]` (8.5).
- Routes, 404 while `matchmaker_live` or `matchmaker_mentors` is off, `Cache-Control: no-store`: `GET /mentor/invites/<token>` (`{single_first_name, email}` for the sign-in page, 410 when expired), `POST /mentor/session` (body `PostMentorSession {invite_token?}`; with no invitation token it needs the session from `/check-otp`, `expected_onboarding_status=None`), `DELETE /mentor/session`, and with header `X-Mentor-Token`: `GET /mentor/me`, `GET /mentor/singles/<uuid>/matches`, `GET /mentor/singles/<uuid>/matches/<muuid>`, `GET /mentor/singles/<uuid>/matches/<muuid>/conversation?before=`, `PUT /mentor/singles/<uuid>/notes/<muuid>`. For the single, member session: `GET /matches/<uuid>/mentor-note` (`{note}` or 404).

- [ ] **Step 1: Write the failing test** `tests/test_mentor_view.py`:

```python
def test_the_invitation_link_signs_the_mentor_in(client, invited_mentor):
    link, token = invited_mentor()
    r = client.post('/mentor/session', json=dict(invite_token=token))
    assert r.status_code == 201
    me = client.get('/mentor/me', headers={'X-Mentor-Token': r.get_json()['token']}).get_json()
    assert me == {'singles': [{'uuid': link['single_uuid'], 'first_name': 'Rivka'}], 'ended': []}

def test_a_mentor_reaches_only_what_was_shared(client, mentor_session, make_person): ...
    # the shared conversation reads; an unshared match's conversation -> 403 not_shared; a stranger's uuid -> 404;
    # another single's uuid -> 410 access_ended

def test_a_removed_mentor_sees_nothing_at_once(client, mentor_session):
    m, h_single, h_mentor = mentor_session()
    client.delete('/mentor', headers=h_single)
    r = client.get(f"/mentor/singles/{m['single_uuid']}/matches", headers=h_mentor)
    assert r.status_code == 410 and r.get_json()['error'] == 'access_ended'
    assert client.get('/mentor/me', headers=h_mentor).get_json()['ended'] == [{'first_name': 'Rivka'}]

def test_the_conversation_is_read_only_text_and_says_who_wrote(client, mentor_session, chat_messages): ...
    # two stored messages, one voice -> from 'single' then 'match'; the voice one has voice True and no text
def test_a_note_is_seen_by_the_single_and_never_by_the_match(client, mentor_session): ...
def test_signing_in_later_takes_the_code_session(client, mentor_session, tool_visitor): ...
def test_an_address_that_mentors_nobody_cannot_sign_in(client, tool_visitor): ...   # 403 not_a_mentor
def test_a_mentor_is_never_a_person_and_never_in_search(client, mentor_session, sign_in, make_person): ...
    # no person row with the mentor's address; a member's search returns no card for it
```

`chat_messages` (in the test file) inserts `mam_message` rows as `process_store_mam_message_batch` writes them.

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/mentor_view.py service/api/mentor_routes.py duotypes/__init__.py tests/test_mentor_view.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the mentor's read-only view of what the single shares" -m "Refs: TEC-1845"
```

### Task 13: Admin: held notes, the counts and a member's connections

**Files:**
- Create: `service/matchmaker/moderation.py`, `service/matchmaker/admin.py`, `service/api/admin/matchmaker_routes.py`
- Modify: `service/api/__init__.py` (register), `tests/conftest.py` (`admin_headers` if Events has not added it)
- Test: `tests/test_admin_matchmaker.py` (create)

**Interfaces:**
- Consumes: `service.admin.require_admin`, `record_audit`; `recommend.send_recommendation`; `introductions.notify_both`.
- Produces:
  - In `service.matchmaker.moderation`: `held_notes(tx) -> list[dict]`: `[{kind: 'recommendation' | 'introduction', id, note, flag_reason, author_first_name, author_person_id?, created_at}]`, never a recipient's address or the two members' names. `approve(tx, admin, kind, id)` (a recommendation is queued; an introduction opens with a fresh 14 days and its notices; `reviewed_by`, `reviewed_at`), `reject(tx, admin, kind, id)` (`rejected`, nothing sent, nobody told).
  - In `service.matchmaker.admin` (counts only): `counts(tx) -> dict`: `{alerts: {member_on, visitor_confirmed, notices_sent, visitor_signups}, introductions: {recommendations_sent, singles_joined, suggestions_made, accepted_by_both, conversations_followed}, mentors: {invited, confirmed, active, removed, chose_not_to_match}, live: {alerts, introductions, mentors}}`, the G.2 tiles. `visitor_signups` counts members whose `lead_source` is `alert:visitor` or who adopted a visitor alert; `singles_joined` counts `recommendation.joined_person_id`; `conversations_followed` counts matched introductions where both have sent a message (`messaged`); `active` counts mentors seen in the last 30 days; `chose_not_to_match` counts `person.no_mentor_shared_matches`.
  - `connections(tx, person_id) -> dict`: 6.1's groups: `{alert: {on, criteria_line, last_notice_at} | None, introductions: {made, accepted_by_both, not_taken_further, received}, mentor: {since, email, conversations_shared} | None}`; `criteria_line` is `summary_line` with the relocation part ("Age 26 to 34, anywhere, any relocation", 6.1). Never a note or a message.
- Routes, admin session only, working whichever way the switches are set: `GET /admin/matchmaker`, `GET /admin/users/<int:pid>/connections`, `GET /admin/moderation/text`, `POST /admin/moderation/text/<kind>/<int:id>/approve`, `.../reject`. Every change writes `record_audit` (`matchmaker.note.approve`, `matchmaker.note.reject`).

- [ ] **Step 1: Write the failing test** `tests/test_admin_matchmaker.py`: `test_the_counts_are_counts`, `test_nobody_sees_who_said_no` (after a decline: `not_taken_further` 1 and the body names neither person), `test_the_drawer_never_carries_a_note_or_a_message` (`'Ask about' not in body`), `test_approving_a_held_recommendation_sends_it`, `test_approving_a_held_introduction_opens_it_and_tells_both`, `test_rejecting_sends_nothing_and_tells_nobody`, `test_the_text_queue_never_shows_a_recipient` (the recipient's address and the two members' names are not in the body), `test_every_route_needs_an_admin` (a member session -> 403), `test_every_change_is_audited`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/moderation.py service/matchmaker/admin.py service/api/admin/matchmaker_routes.py service/api/__init__.py tests/conftest.py tests/test_admin_matchmaker.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): held notes for review, the counts and a member's connections" -m "Refs: TEC-1845"
```

### Task 14: Retention, deleting with the account and crediting a recommended single

**Files:**
- Create: `service/matchmaker/retention.py`
- Modify: `service/cron/leadretention/__init__.py` (`_purge_once`), `service/hard_delete.py`, `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py`, `service/person/__init__.py` (finish-onboarding, after `adopt_visitor_alert`)
- Test: `tests/test_matchmaker_retention.py` (create)

**Interfaces:**
- Produces, in `service.matchmaker.retention`:
  - `purge_matchmaker_data(tx, now=None) -> dict` `{recommendations_erased, recommendations_deleted, notes_erased, unconfirmed_alerts, mentor_sessions, mentor_accounts, invitations}`: a recommendation's address and note erased 7 days after its outbox row reached `accepted`, `failed` or `skipped` (the outbox row's `email` masked with `mask_email` and its `payload` html emptied in the same statement); recommendation rows deleted 12 months after `created_at`; an introduction's note erased 30 days after it closed unmatched; visitor alerts never confirmed deleted a day after `confirm_by`; mentor sessions deleted a day after they lapse; mentor accounts with no live link deleted 30 days after their last link was revoked; invitations never accepted revoked a day after `invite_expires_at`.
  - `Q_DELETE_MATCHMAKER_DATA_OF` (binds `nes` and `ids`, as `Q_DELETE_TOOL_DATA_OF`): the account's mentor links (cascading shares and their outbox rows), recommendations sent to the address (by `recipient_key`) and a mentor account with the address. Rows keyed on the person go by `ON DELETE CASCADE`.
  - `link_recommendations_to_person(tx, person_id) -> None`: a sent recommendation whose `recipient_key` is the new member's sets `joined_person_id`, and `person.lead_source` becomes `intro` only when it is still NULL (first touch wins, item 26); behind a savepoint.
- `_purge_once` prints a line per count, as it does for Together.

- [ ] **Step 1: Write the failing test** `tests/test_matchmaker_retention.py`: `test_a_recommended_address_is_erased_7_days_after_sending_and_its_key_stays` (and the outbox row's address is masked), `test_the_key_still_stops_a_second_recommendation_after_erasure`, `test_an_unmatched_introductions_note_goes_30_days_after_it_closes`, `test_a_matched_introductions_note_stays`, `test_an_unconfirmed_visitor_alert_goes`, `test_a_lapsed_mentor_session_goes`, `test_a_mentor_account_serving_nobody_goes_after_30_days`, `test_deleting_an_account_deletes_its_matchmaker_data` (through `Q_DELETE_MATCHMAKER_DATA_OF` with the shapes the three callers bind), `test_a_recommended_single_who_joins_is_counted`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above; each of the three deletion callers runs `Q_DELETE_MATCHMAKER_DATA_OF` beside its `Q_DELETE_TOOL_DATA_OF` call.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_tool_retention.py`, `tests/test_event_retention.py` and `tests/test_pendingdeletion.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/matchmaker/retention.py service/cron/leadretention/__init__.py service/hard_delete.py service/cron/pendingdeletion/__init__.py service/api/admin/users_action_routes.py service/person/__init__.py tests/test_matchmaker_retention.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): retention, deleting with the account and counting a recommended single who joins" -m "Refs: TEC-1845"
```

### Task 15: Proofs of the 8 emails and 3 pushes, to the owner only

**Files:**
- Create: `scripts/send_matchmaker_proofs.py`
- Test: `tests/test_send_matchmaker_proofs.py` (create)

**Interfaces:**
- Consumes: `scripts.send_proofs.PROOF_TO`, `PUSH_PERSON_ID`, `PROOF_LINK_DISABLED`, `_inert`, `_smtp`; the `preview_*` functions and push builders of Task 4; `emails.base.ASSETS_DIR`; `mail.TITLES`.
- Produces: `plan() -> list[dict]` (name, label, subject prefixed `[PROOF] `, html with inert links, from_addr), in this order: new members who fit, several (4.1); 1 (4.2); with the likes (4.3); confirm your alert (4.4); someone who fits joined (4.5); the recommendation (5.1); an introduction (5.2); the mentor invitation (6.1). `pushes() -> list[dict]`: the alert, the introduction and the introducer's, sample names. `missing_titles() -> list[str]`; `main(argv)` with `--send` (emails to `PROOF_TO`, refused while a title image is missing: prints the stems and exits 1) and `--push` (the 3 pushes to `PUSH_PERSON_ID` only). It reads and changes no switch.

- [ ] **Step 1: Write the failing test**, as `tests/test_send_together_proofs.py` does: `test_every_proof_goes_to_the_owner_only`, `test_every_link_in_a_proof_is_inert`, `test_the_plan_lists_the_8_emails_in_order`, `test_the_pushes_go_to_the_owners_device_only`, `test_no_switch_is_read` (monkeypatch `service.campaigns.switches.enabled` to raise), `test_it_will_not_send_while_a_title_image_is_missing`.
- [ ] **Step 2: Run it to verify it fails.** Expected: `No module named 'scripts.send_matchmaker_proofs'`.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add scripts/send_matchmaker_proofs.py tests/test_send_matchmaker_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): proofs of the emails and pushes, to the owner only" -m "Refs: TEC-1845"
```

## Release 1 web (ahavah-web)

Every screen here is transcribed from `Ahavah Matchmaker.html` (frames by their number, 1.1 to 10.1) or `Ahavah Marketing Pages and Landing.html` with `/sot-sync` once its tests pass, at 390 first, then 768 and 1440, dark and light, and checked at 320 and 390 for sideways scroll. Section 9 (phase 3b) is not built.

### Task 16: The Matchmaker library: calls, the live check, words for criteria, the mentor's token and the copy

**Files:**
- Create: `src/lib/matchmaker/api.ts`, `status.ts`, `server.ts`, `criteria.ts`, `copy.ts`, `mentor-token.ts`, `nav.ts`
- Test: `tests/lib/matchmaker-criteria.test.ts`, `tests/lib/matchmaker-api.test.ts`, `tests/lib/matchmaker-mentor-token.test.ts` (create)

**Interfaces:**
- Consumes: `apiClient` with its `headers` option (`src/lib/api-client.ts`); `fetchPublicSummary` (`src/lib/share-image/summary.ts`); `AntibotPayload`, `signupStampForRequest`; `TORAH_LEVELS`, `SHABBATS`, `CALENDARS`, `RELOCATIONS`, `WANTS_CHILDREN` (`src/lib/profile-schema.ts`); `src/lib/countries.ts`.
- Produces:
  - `api.ts`: types `Criteria`, `MemberAlert`, `VisitorAsk`, `Candidate`, `PendingIntro`, `MentorState`, `Sharing`, `MentorMatch`, `MentorMessage`, `Region = "africa" | "asia" | "europe" | "north-america" | "oceania" | "south-america"`; calls `getMemberAlert`, `saveMemberAlert`, `pauseAlert`, `resumeAlert`, `deleteAlert`, `askVisitorAlert`, `confirmAlert`, `stopAlert`, `recommend`, `recommendAllowance`, `introCandidates`, `suggestIntro`, `introAllowance`, `pendingIntros`, `acceptIntro`, `declineIntro`, `introsTold`, `introContext`, `getMentor`, `inviteMentor`, `cancelMentorInvite`, `removeMentor`, `shareConversation`, `unshareConversation`, `conversationSharing`, `mentorNoteFor`, and the mentor's `mentorInvite(token)`, `startMentorSession(body)`, `mentorMe`, `mentorMatches`, `mentorMatch`, `mentorConversation`, `saveMentorNote`, `endMentorSession`, each mentor call sending `X-Mentor-Token`. Each throws `ApiError` with the API's `error` and its extra fields (`field`, `from`).
  - `status.ts`: `matchmakerStatus(): Promise<{live, alerts, visitorAlerts, introductions, mentors}>`, dark when the API cannot be read; `useMatchmakerStatus()` for client components.
  - `server.ts`: `matchmakerStatusForPage()` through `fetchPublicSummary`.
  - `criteria.ts`: `rowValue(key, c: Criteria): string` (the right-hand words of 1.1: `"26 to 34"`, `"Anywhere"`, `"North America"`, `"3 countries"` NEW LINE, `"Any"`, the label of one choice or `"{n} chosen"` NEW LINE), `summaryLine(c)` (the API's `summary_line`, prefixed `"On. "`), `REGIONS` with the Map's labels in 3.1's order.
  - `mentor-token.ts`: `rememberMentorToken(token)`, `mentorToken()`, `forgetMentorToken()`; `localStorage` key `ahavah.mentor`, every read and write in `try`.
  - `copy.ts`: `MM_COPY`, every string of `09-matchmaker.md` sections 1 to 3, 5a to 8 and 10 under its frame number, with the NEW LINES of this plan each marked `// NEW LINE`.
  - `nav.ts`: `export const FAMILIES_IN_NAV = false;` (Task 30 flips it).

- [ ] **Step 1: Write the failing tests**

```ts
// tests/lib/matchmaker-criteria.test.ts
it("says the rows as the export does", () => {
  const c = { age_min: 26, age_max: 34, countries: [], regions: [], relocations: [], torah_levels: [],
              shabbats: [], calendars: [], wants_children: "yes" } as Criteria;
  expect(rowValue("age", c)).toBe("26 to 34");
  expect(rowValue("countries", c)).toBe("Anywhere");
  expect(rowValue("relocations", c)).toBe("Any");
  expect(rowValue("wants_children", c)).toBe("Yes");
  expect(summaryLine(c)).toBe("On. Ages 26 to 34, anywhere.");
});
it("names a carried region on the Countries row", () => {
  expect(rowValue("countries", { ...BASE, regions: ["north-america"] })).toBe("North America");
});
it("never offers plural marriage", () => {
  expect(JSON.stringify(MM_COPY)).not.toMatch(/polyg/i);
});
```

`tests/lib/matchmaker-api.test.ts`: `sends the mentor's token on every mentor call and on no other`, `carries the API's field and day on an error`. `tests/lib/matchmaker-mentor-token.test.ts`: `remembers and forgets the token`, `survives storage that throws`.

- [ ] **Step 2: Run them to verify they fail.** Run: `npx vitest run tests/lib/matchmaker-criteria.test.ts tests/lib/matchmaker-api.test.ts tests/lib/matchmaker-mentor-token.test.ts`. Expected: failures, the modules do not exist.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/matchmaker tests/lib/matchmaker-criteria.test.ts tests/lib/matchmaker-api.test.ts tests/lib/matchmaker-mentor-token.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the Matchmaker library, criteria words and the mentor's token" -m "Refs: TEC-1845"
```

### Task 17: The 6 email titles, rendered with the calibrated recipe

**Files:**
- Create (ahavah-web): `public/email/title-alert-fits.png`, `title-alert-fits-wht.png`, `title-alert-confirm.png`, `title-alert-confirm-wht.png`, `title-alert-joined.png`, `title-alert-joined-wht.png`, `title-recommend.png`, `title-recommend-wht.png`, `title-introduction.png`, `title-introduction-wht.png`, `title-mentor-invite.png`, `title-mentor-invite-wht.png`
- Add (ahavah-api): the same 12 files in `emails/assets/`, synced with `scripts/sync_email_assets.sh`
- Test: `tests/test_email_renders_on_a_phone.py` (ahavah-api, existing), `tests/test_send_matchmaker_proofs.py`

**Interfaces:**
- Consumes: `scripts/render-email-titles.mjs` (Ultra 400, tracking -0.022em, line height 1.0, 79 px at 2x, `#5524F5` light and `#FFFFFF` dark, trimmed; it renders `title-quick-questions.png` byte for byte); Task 4's `TITLES`.
- Produces: the 12 PNGs. The words, breaks and widths are Task 4's table; the widths there were measured on 20 Oct with this command into a scratch folder, and Step 2 checks they still hold.

- [ ] **Step 1: Render them**

```bash
cd /d/Antigravity/ahavah-web
node scripts/render-email-titles.mjs public/email '[{"name":"title-alert-fits","lines":["New people","who fit."]},{"name":"title-alert-confirm","lines":["Turn on","your alert."]},{"name":"title-alert-joined","lines":["Someone who","fits joined."]},{"name":"title-recommend","lines":["Someone","thought","of you."]},{"name":"title-introduction","lines":["An","introduction."]},{"name":"title-mentor-invite","lines":["Be a mentor","on Ahavah."]}]'
```

Expected output, one line per title: `title-alert-confirm.png 505 x 158 natural CSS width 252`, `title-alert-fits.png 549 x 138 ... 274`, `title-alert-joined.png 658 x 158 ... 329`, `title-introduction.png 638 x 138 ... 319`, `title-mentor-invite.png 578 x 138 ... 289`, `title-recommend.png 437 x 238 ... 218`.

- [ ] **Step 2: Check the widths** against Task 4's `TITLES`; if any differs, change `TITLES` to the printed width in the same commit.
- [ ] **Step 3: Sync and run the phone check.** In ahavah-api: `./scripts/sync_email_assets.sh`, then the API test command with `tests/test_email_renders_on_a_phone.py` and `tests/test_send_matchmaker_proofs.py`. Expected: all pass, the `mm_` samples included, and `python -m scripts.send_matchmaker_proofs` no longer reports missing titles.
- [ ] **Step 4: Look at them** at 390 in a light and a dark mail client preview (the proof script's dry run writes the HTML); no title wraps or clips.
- [ ] **Step 5: Commit both repos**

```bash
cd /d/Antigravity/ahavah-web
git add public/email/title-alert-fits.png public/email/title-alert-fits-wht.png public/email/title-alert-confirm.png public/email/title-alert-confirm-wht.png public/email/title-alert-joined.png public/email/title-alert-joined-wht.png public/email/title-recommend.png public/email/title-recommend-wht.png public/email/title-introduction.png public/email/title-introduction-wht.png public/email/title-mentor-invite.png public/email/title-mentor-invite-wht.png
git -c user.email=admin@techbaseltd.com commit -m "feat(email): the matchmaker email titles" -m "Refs: TEC-1845"
cd /d/Antigravity/ahavah-api
git add emails/assets/title-alert-fits.png emails/assets/title-alert-fits-wht.png emails/assets/title-alert-confirm.png emails/assets/title-alert-confirm-wht.png emails/assets/title-alert-joined.png emails/assets/title-alert-joined-wht.png emails/assets/title-recommend.png emails/assets/title-recommend-wht.png emails/assets/title-introduction.png emails/assets/title-introduction-wht.png emails/assets/title-mentor-invite.png emails/assets/title-mentor-invite-wht.png service/matchmaker/mail.py
git -c user.email=admin@techbaseltd.com commit -m "feat(email): the matchmaker email titles, synced" -m "Refs: TEC-1845"
```

### Task 18: The alert sheet, its way in from Filters, the empty deck's 7 rows and new fits first

**Files:**
- Create: `src/components/matchmaker/alert-sheet.tsx`, `criterion-sheet.tsx`
- Modify: `src/components/app/filters-sheet.tsx` (one row, 1.6), `src/components/app/deck-end.tsx` (rows 2 and 5), `src/app/discover/page.tsx` (mounts the sheet; `?fits=1`)
- Test: `tests/components/matchmaker-alert-sheet.test.tsx`, `tests/components/deck-end.test.tsx` (create or extend), `tests/app/discover-fits-first.test.tsx` (create)

**Interfaces:**
- Consumes: `getMemberAlert`, `saveMemberAlert`, `rowValue`, `useMatchmakerStatus`; `useFilters()` (the filters the deck holds, to fill a new alert); `use-push-subscription` (`Notification.permission`, a live subscription); the Together status (`src/lib/together/status`).
- Produces:
  - `alert-sheet.tsx`: frame 1.1: heading "Tell me when someone who fits joins", the 7 rows (Age range, Countries, Willing to relocate, Torah observance stage, Sabbath, Calendar, Wants children) each opening `criterion-sheet.tsx`, "Notify me by" with Push and Email switches, the rule line "At most one notice a day. We never name anyone.", "Save"; 1.3 saving; 1.4 failed ("Could not save. Your previous alert still applies. Please try again.", the sheet keeps the edit); 1.5 when push is denied or there is no subscription ("Turned off for Ahavah in this browser" and the line under it; the Push switch disabled). A new alert is filled from the saved age band and the deck's age, Torah level and calendar filters.
  - `criterion-sheet.tsx`: 1.2's pills that wrap ("Pick any.", "Clear", "Done") for the list criteria, the age range slider, and a single choice for Wants children ("Any", "Yes", "No", NEW LINES for the last two as labels of `WANTS_CHILDREN`). No plural marriage criterion.
  - `filters-sheet.tsx`: the row "Tell me when someone who fits joins" (1.6, a bell, the tinted card) above "Reset filters" and "Apply", shown only while `alerts` is on.
  - `deck-end.tsx`: row 2 "Tell me when someone who fits joins", or "Your alert is on" with "Edit" (2.2), while `alerts` is on; row 5 "See how well you and a friend fit" to `/together/game`, while Together is live. The order of 2.1 otherwise unchanged.
  - `discover/page.tsx`: `?fits=1` adds `fits_first=1` to the first `GET /search` and shows 1.13's line "New members who fit what you are looking for come first." above the deck once.

- [ ] **Step 1: Write the failing tests**: `alert sheet`: `fills a new alert from the saved band and the deck's filters`, `shows each row's words`, `saves the criteria and both switches`, `keeps the edit and says so when saving fails`, `says push is off in this browser and keeps email`, `wraps the country pills`, `never offers plural marriage`. `deck-end`: `adds the alert row second and the game row fifth`, `says your alert is on with Edit`, `hides the alert row while alerts are off`, `hides the game row while Together is dark`. `discover-fits-first`: `asks for new fits first once and says so`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 1.1 to 1.7, 1.13 and 2.1 to 2.3.
- [ ] **Step 4: Run them to verify they pass**, with `tests/app/discover-page.test.tsx` and `tests/lib/use-filters.test.ts`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/matchmaker/alert-sheet.tsx src/components/matchmaker/criterion-sheet.tsx src/components/app/filters-sheet.tsx src/components/app/deck-end.tsx src/app/discover/page.tsx tests/components/matchmaker-alert-sheet.test.tsx tests/components/deck-end.test.tsx tests/app/discover-fits-first.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the alert sheet, from Filters and the empty deck, and new fits first" -m "Refs: TEC-1845"
```

### Task 19: Settings > Notifications, "New members who fit"

**Files:**
- Modify: `src/app/settings/notifications/page.tsx`
- Test: `tests/app/notifications-alert-row.test.tsx` (create)

**Interfaces:**
- Consumes: `getMemberAlert`, `saveMemberAlert`, `pauseAlert`, `resumeAlert`, `summaryLine`, `AlertSheet`.
- Produces: under the existing Activity rows, frame 1.8's "New members" group: "New members who fit" with its push and email switches (the alert's own `notify_push` and `notify_email`) and the state line ("Off", "On. Ages 26 to 34, anywhere." 1.9, "Paused. What you are looking for is kept." with "Resume" 1.10), "Edit what I am looking for" opening the sheet, and the rule line. Turning both switches off pauses the alert; turning one on with no alert opens the sheet. Shown only while `alerts` is on. The existing rows are untouched.

- [ ] **Step 1: Write the failing test**: `says off with no alert`, `says on with the summary`, `pauses and resumes`, `opens the sheet to edit`, `leaves the existing rows as they were`, `draws nothing while alerts are off`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 1.8 to 1.10.
- [ ] **Step 4: Run it to verify it passes**, with `tests/app/notifications-settings.test.tsx` and `tests/app/notifications-questions-row.test.tsx`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/settings/notifications/page.tsx tests/app/notifications-alert-row.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): New members who fit in Settings, Notifications" -m "Refs: TEC-1845"
```

### Task 20: The visitor form, the landing's "Not ready to join?" and the confirm and stop pages

**Files:**
- Create: `src/components/matchmaker/visitor-form.tsx`, `src/components/matchmaker/not-ready-section.tsx`, `src/app/alerts/confirm/[token]/page.tsx`, `src/app/alerts/stop/[token]/page.tsx`
- Modify: `src/app/page.tsx` (after `#verified`, before the CTA band, `p11-mk.js` `landing()` order), `src/app/robots.ts` (`/alerts` disallowed)
- Test: `tests/components/matchmaker-visitor-form.test.tsx`, `tests/app/alert-pages.test.tsx` (create)

**Interfaces:**
- Consumes: `askVisitorAlert`, `confirmAlert`, `stopAlert`, `REGIONS`, `matchmakerStatusForPage`; `AntibotFields`, `signupStampForRequest`.
- Produces:
  - `visitor-form.tsx`: frame 3.1's fields ("Your email", "I am looking for" A man or A woman, "Aged" with the range, "Region" pills that wrap with Anywhere first, "First name (optional)" with "So we can greet you"), the consent line, "Tell me"; 3.2 for an address without `@` and a dot after it and for `bad_email`; 3.3 sending; 3.4 sent with the address and "Use a different email" (the answers kept); 3.5 `already_on`; 3.9 `too_many_tries` and HTTP 429; 3.10 otherwise.
  - `not-ready-section.tsx`: `notReady()`: the section head "Not ready to join?" and "Tell us who you are looking for, and we will email you when someone who fits joins." (marketing 1.9) beside the card holding the form; stacked on a phone. Renders nothing unless `live` and `visitorAlerts`.
  - `/alerts/confirm/[token]` (client page, `robots: noindex`): calls `confirmAlert` once in an effect, then 3.7 ("You are on the list." with "Stop these emails", which calls `stopAlert` with the returned stop token and shows 3.8), 3.5 for `already_on`, 3.6 for `expired` with the form below it.
  - `/alerts/stop/[token]` (client page, `robots: noindex`): calls `stopAlert` once in an effect and shows 3.8.

- [ ] **Step 1: Write the failing tests**: form: `shows every field and Tell me`, `asks for a full email address`, `sends what the visitor is looking for`, `shows check your email with the address`, `keeps the answers to use a different email`, `says too many tries`, `wraps the region pills`. Pages:

```tsx
it("does not confirm until the page has loaded", async () => {
  const confirm = vi.spyOn(api, "confirmAlert").mockResolvedValue({ state: "confirmed", stop_token: "s".repeat(32) });
  renderToString(<ConfirmPage params={Promise.resolve({ token: "t".repeat(32) })} />);
  expect(confirm).not.toHaveBeenCalled();
  render(<ConfirmPage params={Promise.resolve({ token: "t".repeat(32) })} />);
  await screen.findByText("You are on the list.");
  expect(confirm).toHaveBeenCalledTimes(1);
});
```

plus `says the link has expired and offers the form`, `says it is already on`, `stops from the confirmed page`, `stops from the email's link`, and `the landing draws no section while visitor alerts are off`.

- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 3.1 to 3.10 and the marketing section 1.9 at 320, 390, 768 and 1440.
- [ ] **Step 4: Run them to verify they pass**, with `tests/app/landing-signup-form.test.tsx`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/matchmaker/visitor-form.tsx src/components/matchmaker/not-ready-section.tsx "src/app/alerts/confirm/[token]/page.tsx" "src/app/alerts/stop/[token]/page.tsx" src/app/page.tsx src/app/robots.ts tests/components/matchmaker-visitor-form.test.tsx tests/app/alert-pages.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): Not ready to join on the landing, and confirming and stopping an alert" -m "Refs: TEC-1845"
```

### Task 21: "Introduce a single to Ahavah" on `/invite`

**Files:**
- Create: `src/components/matchmaker/recommend-form.tsx`
- Modify: `src/app/invite/page.tsx` (after the share choices)
- Test: `tests/components/matchmaker-recommend-form.test.tsx` (create)

**Interfaces:**
- Consumes: `recommend`, `recommendAllowance`.
- Produces: `RecommendForm({ mode: "member" | "visitor" })`: member mode is frame 5a.1 ("Introduce a single to Ahavah", "We email them once, with your note and your invite link.", "Their email", "Your note" filled with "I think you would be a good fit for Ahavah.", "Send"); 5a.2 invalid email; 5a.3 sending; 5a.4 sent with "Introduce someone else" (which clears the form); 5a.5 for `limit` with the API's day; 5a.6 failed (3.10's line). Visitor mode is Task 26's. Shown on `/invite` only while `introductions` is on.

- [ ] **Step 1: Write the failing test**: `fills the note with the spec's line`, `sends the email and the note`, `says sent and lets you introduce someone else`, `says when you can send more`, `asks for a full email address`, `draws nothing while introductions are off`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 5a.1 to 5a.6.
- [ ] **Step 4: Run it to verify it passes**, with `tests/app/invite-page.test.tsx`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/matchmaker/recommend-form.tsx src/app/invite/page.tsx tests/components/matchmaker-recommend-form.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): Introduce a single to Ahavah on the invite page" -m "Refs: TEC-1845"
```

### Task 22: "Suggest an introduction" from a profile

**Files:**
- Create: `src/components/matchmaker/profile-more-sheet.tsx`, `intro-picker.tsx`, `intro-note-sheet.tsx`
- Modify: `src/app/profile/[uuid]/page.tsx` ("More options" at line 621 opens the new sheet; "Report" in it opens the existing `BlockReportSheet`)
- Test: `tests/components/matchmaker-suggest.test.tsx` (create)

**Interfaces:**
- Consumes: `introCandidates`, `suggestIntro`, `introAllowance`; `BlockReportSheet`.
- Produces: `profile-more-sheet.tsx`: 5b.1 ("More options", "Suggest an introduction" with "Suggest {first name} to someone you think would be a good fit", "Report"); without `introductions` on, "More options" opens the report sheet as today. `intro-picker.tsx`: 5b.2 ("Who would you introduce {first name} to?", "Search by first name", rows with the reach label, "Next"), 5b.4 loading, 5b.3 when the list is empty, 5b.5 no results, 5b.6 a disabled row with "You have suggested {name} before." `intro-note-sheet.tsx`: 5b.7 ("Suggest an introduction", "{A} and {B}", "Your note", "Both will see this at the top of their chat if both accept.", "{left} of 5 introductions left this week", "Send"), 5b.8 the field above the keyboard, 5b.9 at the limit with the API's day, 5b.10 for `held`, 5b.11 for `sent`.

- [ ] **Step 1: Write the failing test**: `opens More options with Suggest an introduction and Report`, `keeps the report sheet as today while introductions are off`, `lists who you can see with where you see them`, `searches by first name`, `says when nobody fits yet`, `disables someone suggested before`, `counts what is left this week`, `says the note is being checked`, `says sent`, `the note stays on screen above the keyboard at 390`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 5b.1 to 5b.11.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/matchmaker/profile-more-sheet.tsx src/components/matchmaker/intro-picker.tsx src/components/matchmaker/intro-note-sheet.tsx "src/app/profile/[uuid]/page.tsx" tests/components/matchmaker-suggest.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): suggest an introduction from a profile" -m "Refs: TEC-1845"
```

### Task 23: The card on Matches, the match moment, the note in the chat and the introducer told

**Files:**
- Create: `src/components/matchmaker/intro-card.tsx`, `intro-context-line.tsx`, `told-toast.tsx`
- Modify: `src/app/matches/page.tsx` (cards at the top of Matches; `?intro=` scrolls to one), `src/app/match/page.tsx` ("Introduced by"), `src/components/app/chat-thread-view.tsx` (the line at the top), `src/app/discover/page.tsx` (mounts the toast)
- Test: `tests/components/matchmaker-intro-card.test.tsx`, `tests/app/match-introduced-by.test.tsx` (create)

**Interfaces:**
- Consumes: `pendingIntros`, `acceptIntro`, `declineIntro`, `introsTold`, `introContext`; `photo-or-gradient.ts` and `profile-gradients.ts` for the gradient.
- Produces: `intro-card.tsx`: 5c.1 ("Introduction", "{introducer} thinks you and {first name} might be a good fit", the other's photo, first name, age, place and their About until prompts ship, the note, "This introduction closes on {date}", "Not for me" and "Accept"), 5c.2 after Accept, 5c.3 the card goes after Not for me with nothing else said, 5c.4 for `closed`, 5c.5 the gradient where no photo may show. On `matched` it goes to `/match` with the peer. `/match` shows "Introduced by {first name}" (5c.6) when the match carries `introduced_by`. `intro-context-line.tsx`: 5c.7, the introducer's note as the first line of the conversation. `told-toast.tsx`: 5c.8's toast once per told row.

- [ ] **Step 1: Write the failing tests**: `shows who introduced you, the other person and both buttons on the first screen at 390`, `says we will let you know after accepting`, `takes the card away after not for me and says nothing`, `says the introduction has closed`, `shows the gradient to a viewer held by the photo gate`, `goes to the match moment when both said yes`, `says introduced by on the match moment`, `puts the introducer's note at the top of the chat`, `tells the introducer once`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 5c.1 to 5c.8.
- [ ] **Step 4: Run them to verify they pass**, with `tests/app/matches-tab.test.tsx`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/matchmaker/intro-card.tsx src/components/matchmaker/intro-context-line.tsx src/components/matchmaker/told-toast.tsx src/app/matches/page.tsx src/app/match/page.tsx src/components/app/chat-thread-view.tsx src/app/discover/page.tsx tests/components/matchmaker-intro-card.test.tsx tests/app/match-introduced-by.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the introduction card, two yeses to a match and the introducer told" -m "Refs: TEC-1845"
```

### Task 24: Your mentor: Settings, sharing from the chat, the notice for both people and the privacy setting

**Files:**
- Create: `src/app/settings/mentor/page.tsx`, `src/components/matchmaker/mentor-settings.tsx`, `remove-mentor-sheet.tsx`, `sharing-notice.tsx`, `about-sharing-sheet.tsx`, `mentor-note-line.tsx`
- Modify: `src/app/settings/page.tsx` (a "Your mentor" row), `src/components/app/chat-more-menu.tsx` (Share with your mentor or Stop sharing), `src/components/app/chat-header.tsx` (the notice), `src/components/app/chat-thread-view.tsx` (the lines where sharing began and stopped), `src/app/settings/privacy/page.tsx` (the Matching switch), `src/app/profile/[uuid]/page.tsx` ("From your mentor" on a match)
- Test: `tests/components/matchmaker-mentor-settings.test.tsx`, `tests/components/matchmaker-sharing.test.tsx`, `tests/lib/privacy-mentor-setting.test.tsx` (create)

**Interfaces:**
- Consumes: `getMentor`, `inviteMentor`, `cancelMentorInvite`, `removeMentor`, `shareConversation`, `unshareConversation`, `conversationSharing`, `mentorNoteFor`; the privacy page's existing save pattern.
- Produces:
  - `mentor-settings.tsx`: 6.1 ("Your mentor", the lede, "Their email", "How do you know them?" Parent, Elder, Mentor or Friend with "Only you see this.", "They will see" and "They will never see" lists, "Send invitation"), 6.2 failed, 6.3 waiting with "Invited as a {relation}" and "Cancel invitation", 6.4 confirmed with "Shared conversations", "Shared since {date}", "Stop sharing", "Remove mentor" and "They will lose access straight away.", 6.5 nothing shared, 6.6 the remove sheet ("Remove {name} as your mentor?", "Keep"), 6.7's toast.
  - `chat-more-menu.tsx`: "Share with your mentor" with "{mentor} can read it, and {other} is told" (6.8) or "Stop sharing" with "{mentor} will no longer be able to read this conversation" (6.9), only with a confirmed mentor; `cannot_share` shows "This conversation cannot be shared." (NEW LINE).
  - `sharing-notice.tsx`: in the chat header, "{single}’s mentor can read this conversation" for the other person (8.1, tapping opens `about-sharing-sheet.tsx`, 8.2, with "Privacy settings" to `/settings/privacy` and "Close") and "Shared with your mentor" for the single (8.3); the same in the desktop thread pane's header. The conversation shows "{single}’s mentor can now read this conversation" (the single sees "Your mentor can now read this conversation") and "{single} stopped sharing this conversation" (8.4) at their times, merged with the messages by time.
  - Privacy, Matching: "Do not match me with members who share conversations with a mentor" (6.10 to 6.13), saved with `no_mentor_shared_matches`, failing with the page's existing line. Shown only while `mentors` is on.
  - `mentor-note-line.tsx`: 8.5 ("From your mentor", the note, "Only you see this. {match} never does.") on the single's view of that match, above "Message".

- [ ] **Step 1: Write the failing tests**: settings: `invites with how you know them and shows what they will and will not see`, `waits for the mentor and can cancel`, `lists shared conversations and stops one`, `removes the mentor after asking`, `says it could not send`. Sharing: `shares from the chat's More and tells the single it is shared`, `tells the other person in the header and explains it when tapped`, `puts the lines in the conversation where sharing began and stopped`, `says a conversation cannot be shared`, `shows the mentor's note to the single only`. Privacy: `saves the setting off by default and on`, `keeps the previous setting when saving fails`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 6.1 to 6.13 and 8.1 to 8.5.
- [ ] **Step 4: Run them to verify they pass**, with `tests/lib/privacy-save.test.tsx`, `tests/components/chat-unmatch.test.tsx` and `tests/components/chat-play-us.test.tsx`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/settings/mentor/page.tsx src/components/matchmaker/mentor-settings.tsx src/components/matchmaker/remove-mentor-sheet.tsx src/components/matchmaker/sharing-notice.tsx src/components/matchmaker/about-sharing-sheet.tsx src/components/matchmaker/mentor-note-line.tsx src/app/settings/page.tsx src/components/app/chat-more-menu.tsx src/components/app/chat-header.tsx src/components/app/chat-thread-view.tsx src/app/settings/privacy/page.tsx "src/app/profile/[uuid]/page.tsx" tests/components/matchmaker-mentor-settings.test.tsx tests/components/matchmaker-sharing.test.tsx tests/lib/privacy-mentor-setting.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): your mentor, sharing a conversation and the notice both people see" -m "Refs: TEC-1845"
```

### Task 25: The mentor's view, `/mentor`

**Files:**
- Create: `src/app/mentor/page.tsx`, `src/app/mentor/[single]/[match]/page.tsx`, `src/app/mentor/[single]/[match]/conversation/page.tsx`, `src/components/matchmaker/mentor-sign-in.tsx`, `mentor-matches.tsx`, `mentor-match-detail.tsx`, `mentor-conversation.tsx`
- Modify: `src/app/robots.ts` (`/mentor` disallowed)
- Test: `tests/app/mentor-pages.test.tsx` (create)

**Interfaces:**
- Consumes: `mentorInvite`, `startMentorSession`, `mentorMe`, `mentorMatches`, `mentorMatch`, `mentorConversation`, `saveMentorNote`, `endMentorSession`, `rememberMentorToken`, `mentorToken`; `requestOtp` and `checkOtp` (`src/lib/auth-otp.ts`).
- Produces: every page is `robots: noindex` and answers not found while `mentors` is off. `/mentor?invite=` calls `startMentorSession({ invite_token })` once in an effect and goes to the list. Without a token: 7.1 ("Mentor", "Sign in as a mentor", "Use the email {single} invited. We will send you a 6-digit code." with the name from the invitation when known, NEW LINE "Use the email you were invited with." otherwise), 7.2 the code, 7.3 wrong or expired, then `startMentorSession({})`. With a token: 7.4 ("{single}’s matches", "As {single} sees them.", each match with "Conversation shared" or "Conversation not shared", "Sign out"), 7.5 the switcher when serving more than one single, 7.6 no matches, 7.12 access ended. The match page: 7.7 (the match as the single sees them, "Your note", "Only {single} sees your notes.", "Save", "Saved", "Read the shared conversation"), 7.8 the note failed, 7.9 not shared. The conversation: 7.10 ("{single} and {match}", "Shared by {single}", the read-only line, the messages with no box to write in, "Only {single} and {match} can write here.", a voice message as "A voice message", NEW LINE), 7.11 when sharing stops while open, with "Back to {single}’s matches".

- [ ] **Step 1: Write the failing test** `tests/app/mentor-pages.test.tsx`:

```tsx
it("does not accept the invitation until the page has loaded", async () => {
  const start = vi.spyOn(api, "startMentorSession").mockResolvedValue({ token: "m".repeat(32) });
  renderToString(<MentorPage searchParams={Promise.resolve({ invite: "i".repeat(32) })} />);
  expect(start).not.toHaveBeenCalled();
  render(<MentorPage searchParams={Promise.resolve({ invite: "i".repeat(32) })} />);
  await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
});
```

plus `signs in with the code`, `says the code is wrong or expired`, `lists the single's matches and which are shared`, `switches between singles`, `saves a private note`, `reads a shared conversation with nowhere to write`, `says when sharing stopped while open`, `says access has ended`, `shows a voice message as a line`.

- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 7.1 to 7.12.
- [ ] **Step 4: Run it to verify it passes.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/mentor "src/app/mentor/[single]/[match]/page.tsx" "src/app/mentor/[single]/[match]/conversation/page.tsx" src/components/matchmaker/mentor-sign-in.tsx src/components/matchmaker/mentor-matches.tsx src/components/matchmaker/mentor-match-detail.tsx src/components/matchmaker/mentor-conversation.tsx src/app/robots.ts tests/app/mentor-pages.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the mentor's read-only view" -m "Refs: TEC-1845"
```

### Task 26: `/families`, its share image, the recommend form for visitors, the footer link and the sitemap

**Files:**
- Create: `src/app/families/page.tsx`, `src/app/families/opengraph-image.tsx`, `src/components/matchmaker/families-page.tsx`, `src/lib/share-image/matchmaker-templates.tsx`
- Modify: `src/components/matchmaker/recommend-form.tsx` (visitor mode), `src/lib/share-image/templates.tsx` (register), `src/components/app/marketing-footer.tsx` (Community column and its phone accordion), `src/app/sitemap.ts`
- Test: `tests/app/families-page.test.tsx`, `tests/app/matchmaker-sitemap.test.ts` (create), `tests/components/marketing-footer.test.tsx` (create or extend)

**Interfaces:**
- Consumes: `matchmakerStatusForPage`, `FAMILIES_IN_NAV`, `RecommendForm`, `requestOtp`, `checkOtp`; `renderShareImage`, `loadShareFonts`, `AhavahMark`, `SHARE_SIZES.link`; the marketing header and footer; `json-ld.ts`.
- Produces:
  - `/families` (server page): not found unless `live` and `mentors`; metadata from the marketing brief's table (title "For parents and elders", description "How a parent, elder or mentor can help a single believer towards marriage on Ahavah and what they can and cannot see.", canonical `/families`, the image route); the body is 10.1 in its order (the kicker "For parents, elders and mentors", "Help someone you love find a spouse.", How a family can help, What a mentor sees, What a mentor never sees, The single decides, The other person is always told, How to start with "Ask your son or daughter to invite you from Settings.", Questions with the 4 answers of 10.1), with the FAQPage JSON-LD for those 4. No member faces, no figures. The headline and what a mentor sees fit the first screen at 390.
  - `RecommendForm` visitor mode (5a.7 to 5a.9): "Your first name", "Your email", "Their email", "Your note", "We email them once, with your note.", "We will email you a 6-digit code first, to confirm it is you.", "Send code"; the code step ("Confirm it is you", the line with the address, "Confirm and send", "Resend code") through `requestOtp`/`checkOtp`, then `recommend` with the first name; on `/families` under "Introduce someone", only while `introductions` is on.
  - `page-families` share template (`p11-mk.js` `og()` with `OGP.families`): "For parents and elders", "Matchmaking for Torah-observant believers who hope to marry." and `AHAVAH.APP`; flexbox only.
  - `marketing-footer.tsx`: For families (`/families`) in the Community column and its accordion when `FAMILIES_IN_NAV`, after whatever Events added (footer only: the marketing brief puts For families in the footer, not the header). If Events' `communityLinks(eventsInNav)` exists, add a `familiesInNav = FAMILIES_IN_NAV` parameter; if not, introduce `communityLinks(familiesInNav = FAMILIES_IN_NAV)`.
  - `sitemap.ts`: `/families` (0.6, monthly) while `live` and `mentors`.

- [ ] **Step 1: Write the failing tests**: families: `answers not found while mentors are dark`, `shows the headline and what a mentor sees first`, `says what a mentor never sees`, `carries the 4 questions as FAQ data`, `offers the recommend form only while introductions are on`, `asks for a code before sending a visitor's recommendation`. Footer: `adds For families to Community when it is in the nav, and not before`. Sitemap: `lists /families only once it is live`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` frames 10.1 and 5a.7 to 5a.9, the footer 2.10 and the share image 3.10, at 320, 390, 768 and 1440.
- [ ] **Step 4: Run them to verify they pass**, then the whole web suite `npx vitest run`, `npx tsc --noEmit`, `npx eslint .` and `npx next build`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/app/families/page.tsx src/app/families/opengraph-image.tsx src/components/matchmaker/families-page.tsx src/components/matchmaker/recommend-form.tsx src/lib/share-image/matchmaker-templates.tsx src/lib/share-image/templates.tsx src/components/app/marketing-footer.tsx src/app/sitemap.ts tests/app/families-page.test.tsx tests/app/matchmaker-sitemap.test.ts tests/components/marketing-footer.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): /families, its share image and the footer link behind a flag" -m "Refs: TEC-1845"
```

### Task 27: The privacy paragraphs, for the owner

**Files:**
- Create: `src/lib/legal-matchmaker-copy.ts`
- Modify: `src/lib/legal-leads-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx`, `tests/app/legal-together.test.tsx` (its `someone who fits joins` guard)
- Test: `tests/app/legal-matchmaker.test.tsx` (create)

**Interfaces:**
- Produces: `MATCHMAKER_PRIVACY: LegalCopy` titled "Alerts, introductions and mentors" (NEW LINE), stating: an alert keeps what you are looking for and when we last told you, never who; a visitor's alert keeps the email, the first name if given and what they are looking for, deleted 12 months after their last visit or at once when they stop it; a recommendation keeps the single's email only until it is sent and then a coded form of it for 12 months so they hear from us once; an introduction keeps who introduced whom, the note and the answers, nobody is told of a no, and the note is deleted 30 days after an introduction closes; a mentor sees only your matches and the conversations you share, the other person is told, you can remove them at any time and that ends their access and deletes their notes; staff see only counts, except a flagged introduction note; ask at support@ahavah.app. `LEADS_PRIVACY.body` gains "or ask to be told when someone who fits joins". Both texts go through `/copy-pass` and the owner before Task 30 Step 6.

- [ ] **Step 1: Write the failing test** `tests/app/legal-matchmaker.test.tsx`: `says what each part keeps, who sees it, for how long and how to delete it` (asserting the phrases above as `legal-together.test.tsx` does), `appears on both privacy pages`. Change `legal-together.test.tsx`'s `not.toMatch(/someone who fits joins/i)` to apply only to `TOGETHER_PRIVACY`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/legal-matchmaker-copy.ts src/lib/legal-leads-copy.ts src/app/privacy/page.tsx src/app/legal/privacy/page.tsx tests/app/legal-together.test.tsx tests/app/legal-matchmaker.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): what alerts, introductions and mentors keep, on the privacy pages" -m "Refs: TEC-1845"
```

## Release 1 admin (ahavah-admin)

### Task 28: Growth's Alerts, Introductions and Mentors tiles, and the member drawer's Connections

**Files:**
- Create: `src/lib/matchmaker-api.ts`, `src/lib/matchmaker-queries.ts`, `src/components/admin/growth-matchmaker.tsx`, `src/components/admin/user-drawer-connections.tsx`
- Modify: `src/components/admin/tab-growth.tsx` (after `<GrowthStats />`), `src/components/admin/user-drawer.tsx` (a Connections tab after Actions)
- Test: `tests/matchmaker-api.test.mjs` (create)

**Interfaces:**
- Consumes: `GET /admin/matchmaker` and `GET /admin/users/<id>/connections` through `api` (session bearer, `/api` proxy), as `questions-queries.ts` does.
- Produces, in `src/lib/matchmaker-api.ts` (pure, no imports, vm-tested like `questions-api.ts`): the wire types; `tiles(counts)` returning the 3 tiles with G.2's labels (Alerts: "Member alerts on", "Visitor alerts confirmed", "Notices sent", "Sign-ups from visitor alerts"; Introductions: "Recommendations sent", "Singles who joined", "Suggestions made", "Accepted by both", "Conversations that followed"; Mentors: "Invited", "Confirmed", "Active", "Removed", "Chose not to be matched with members who share conversations"), each tile "Not live yet. Counts start when alerts launch." (and the introductions and mentors lines, G.1) while its surface is off; `connectionRows(c)` for 6.1 (Alerts "Member alert", "On", "Criteria", "Last notice sent"; Introductions "Made", "Accepted by both", "Not taken further", "Received" with "Counts only. Nobody, the admin included, sees who said no."; Mentor "Active since {date}", "Email", "Conversations shared", "Never the mentor’s notes, never a message."), 6.2 when empty, 6.4 when failed. The tiles are one full-width bento row of 3 level tiles, stacked on a phone and read only there.

- [ ] **Step 1: Write the failing test** `tests/matchmaker-api.test.mjs` (the `questions-api.test.mjs` harness): `labels the three tiles`, `says not live yet per surface`, `lists the drawer's groups`, `says nothing yet when every group is empty`, `never carries a note or a message` (a fixture with no text fields passes through every helper unchanged in shape).
- [ ] **Step 2: Run it to verify it fails.** Run: `node --test tests/matchmaker-api.test.mjs`. Expected: failure, the file does not exist.
- [ ] **Step 3: Implement**, then `/sot-sync` G.1 to G.3 and 6.1 to 6.4 of `Ahavah Admin Growth Features.html`.
- [ ] **Step 4: Run it to verify it passes**, then `node --test tests/*.test.mjs`, `npx tsc --noEmit` and `npx next build`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/lib/matchmaker-api.ts src/lib/matchmaker-queries.ts src/components/admin/growth-matchmaker.tsx src/components/admin/user-drawer-connections.tsx src/components/admin/tab-growth.tsx src/components/admin/user-drawer.tsx tests/matchmaker-api.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): the Alerts, Introductions and Mentors tiles and a member's connections, as counts" -m "Refs: TEC-1845"
```

### Task 29: Moderation > Text, with introduction notes

**Files:**
- Create: `src/components/admin/moderation-text.tsx`
- Modify: `src/components/admin/tab-moderation.tsx` (`SUBS` gains `{ key: "text", label: "Text" }`), `src/lib/matchmaker-api.ts` (`textRows`), `src/lib/matchmaker-queries.ts`, `src/components/admin/sidebar-nav.tsx` (the waiting count on Moderation)
- Test: `tests/matchmaker-api.test.mjs` (extend)

**Interfaces:**
- Consumes: `GET /admin/moderation/text`, `POST /admin/moderation/text/<kind>/<id>/approve` and `/reject`.
- Produces: `textRows(held)` mapping each row to 4.1's columns (When, Kind "Introduction note", Author, Flagged by "Contact details filter", "Scam pattern filter" or "Rude words filter", Context "If rejected: The introduction is not sent."), never the recipients. `moderation-text.tsx`: 4.1 with "Approve" and "Reject", the phone read-only note, 4.3 approving, 4.6 reviewed, 4.7 "No text waiting for review.", 4.9 failed. The other kinds of 4.1 (prompt answers, opening questions, like comments, gathering descriptions) are not built; the filter chips show only "All" and "Introduction note".

- [ ] **Step 1: Write the failing test**: in `tests/matchmaker-api.test.mjs`, `maps a held note to its columns and never a recipient`, `names each filter as the export does`.
- [ ] **Step 2: Run it to verify it fails.** Expected: failures.
- [ ] **Step 3: Implement**, then `/sot-sync` section 4.
- [ ] **Step 4: Run it to verify it passes**, then `node --test tests/*.test.mjs` and `npx next build`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add src/components/admin/moderation-text.tsx src/components/admin/tab-moderation.tsx src/lib/matchmaker-api.ts src/lib/matchmaker-queries.ts src/components/admin/sidebar-nav.tsx tests/matchmaker-api.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(matchmaker): Moderation, Text, for flagged introduction notes" -m "Refs: TEC-1845"
```

## The launch

### Task 30: The launch, in order: API dark, web dark, admin, proofs, then the switches

An operational task: no code beyond one flag. Each step names who acts. Nothing reaches a member, a visitor, a mentor or social before the owner confirms its proof.

**Files:**
- Modify (web, Step 9 only): `src/lib/matchmaker/nav.ts` (`FAMILIES_IN_NAV = true`)
- Modify (admin, Step 12 only): `content/social-calendar.json`; Add: `assets/social/matchmaker-introduce-fb.jpg`, `-ig.jpg`, `assets/social/matchmaker-families-*-fb.jpg`, `-ig.jpg`

- [ ] **Step 1: Ship the API, dark.** With the owner's go, merge Tasks 1 to 15 (and Task 17's ahavah-api commit) to `ahavah/main`; the push deploys through GitHub Actions and applies 0073. With every switch at its default `0`: `curl -s https://api.ahavah.app/matchmaker/status` answers `{"alerts":false,"introductions":false,"live":false,"mentors":false,"visitor_alerts":false}`; `curl -s -o /dev/null -w '%{http_code}' -X POST https://api.ahavah.app/alerts` and `https://api.ahavah.app/mentor/me` answer `404`; the deck still answers as before for a test member.

- [ ] **Step 2: Ship the web, dark.** Merge Tasks 16 to 26 (not 27) to `master`; Vercel deploys. Check: `/families`, `/mentor`, `/alerts/stop/x` answer 404; the landing has no "Not ready to join?"; the footer has no For families; the sitemap has none of them; Filters, the empty deck, Notifications, Privacy, a profile's More options, Matches and a chat's More look as they did.

- [ ] **Step 3: Ship the admin.** Merge Tasks 28 and 29 to the admin's `master`. Check: the 3 tiles say "Not live yet", Moderation > Text says "No text waiting for review.", a member's Connections says 6.2's line.

- [ ] **Step 4: The owner reads what the export did not have.** Hand him "Spec conflicts and decisions needing the owner" items 1 to 21 and 25 to 28, run through `/copy-pass` (ux-writing for the screens, humanizer for the emails and the privacy text) first. His changes go into the code (Tasks 4, 16, 18, 22, 24, 25, 26, 27) and ship before Step 6.

- [ ] **Step 5: Proofs to the owner.** Inside the api container: `python -m scripts.send_matchmaker_proofs` (dry run), then `python -m scripts.send_matchmaker_proofs --send` and `--push`. He checks the 8 emails at 390 and 600, light and dark, Gmail's forced dark mode included, reads every line, and sees the 3 pushes on his phone.

- [ ] **Step 6: Privacy goes live.** On his yes to its wording, merge Task 27. Check both privacy pages show "Alerts, introductions and mentors".

- [ ] **Step 7: Switch on, in the spec's rollout order, each on his word.** In the production environment `docker-compose.production.yml` reads, for both api and cron, then restart both:
  1. Step 1 for members: `AHAVAH_MATCHMAKER_LIVE_ENABLED=1`, `AHAVAH_MATCHMAKER_ALERTS_ENABLED=1`, and the proofs he confirmed: `AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED`, `AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED`.
  2. Step 1 for visitors: `AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED=1` with `AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED` and `AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED` (a visitor cannot confirm without the first).
  3. Step 2: `AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED=1` with `AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED`, `AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED` and `AHAVAH_MATCHMAKER_INTRO_PUSH_ENABLED`.
  4. Step 3 read-only: `AHAVAH_MATCHMAKER_MENTORS_ENABLED=1` with `AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED`.
  After each, `curl -s https://api.ahavah.app/matchmaker/status` shows the surface on, and Step 8's round for that surface passes before the next.

- [ ] **Step 8: A real round on production, by the operator and the owner, per surface.** On two phones, at 320 and 390 with nothing scrolling sideways: save an alert from the empty deck and from Filters; sign up a test member who fits and see the next day's single notice and "See who joined" leading with them. As a visitor, ask from the landing, confirm by the link, see the Thursday email, stop it. Recommend a test address from `/invite` and, as a visitor, from `/families` after the code; check the email arrives once. Suggest two test members to each other; one declines (nobody hears), then a fresh pair both accept (the match moment says "Introduced by", the note heads the chat, the introducer gets the toast and the push). Invite a mentor, accept from the email, share one conversation (the other phone shows the notice and the line), read it as the mentor, leave a note, see it as the single, then remove the mentor (the mentor's next tap says access ended). Paste `/families` into WhatsApp and check the preview. Then delete every test alert, recommendation, introduction, mentor link and test account.

- [ ] **Step 9: The For families link.** With mentors on and Step 8 passed, set `FAMILIES_IN_NAV = true` in `src/lib/matchmaker/nav.ts`, run `npx vitest run tests/components/marketing-footer.test.tsx`, and commit (`feat(marketing): For families in the footer`, `Refs: TEC-1845`); check the sitemap lists `/families`.

- [ ] **Step 10: Linear.** Move TEC-1845's Matchmaker release 1 work to Done once Step 8 passes for every surface. Open follow-ups as their own issues: the chaperone (phase 3b, item 1), the other kinds of Moderation > Text (item 22), prompts on the introduction card and the mentor's view once prompts ship (item 17), the families Questions answers if the owner wants his own (item 27). Run `/linear-sync` before the session's final commit.

- [ ] **Step 11: Each week after.** Read Growth's 3 tiles (the spec's measures: alerts created and sign-ups from visitor alerts; introductions suggested, accepted by both and conversations from them; mentors invited and active; members choosing not to be matched with shared conversations) and Moderation > Text.

- [ ] **Step 12: The social posts, after the owner approves them.** Export "Know someone single? Introduce them." (5.1) and the families carousel (5.2) from `Ahavah Growth Social Set.html` with `/handoff` into `ahavah-admin/assets/social/` (1080 by 1350 JPEG; neither is exported on 20 Oct). Captions (NEW LINES, for `/copy-pass` and the owner), Instagram without a link or "link below": "Know a single believer who hopes to marry? Introduce them to Ahavah." and "How a parent, elder or mentor can help, and what they never see."; Facebook's with `https://ahavah.app/families?utm_source=facebook&utm_campaign=brand&utm_content=families`. Append the entries to `content/social-calendar.json`, run `node --test tests/social-calendar.test.mjs`, commit (`content(social): the matchmaker launch posts`, `Refs: TEC-1845`). A post after 9 Nov cannot be approved until he extends his rest-day calendar (`restdays.py` and `rest-days.ts`, which this plan does not touch).

---

## Owner's answers (21 Oct 2026)

These override the defaults below where they differ.

- **Item 30, what a mentor reads: changed from the default.** A mentor sees only messages sent after the single shares the conversation, never the history before it, and the other member is told that a mentor is reading. They see a line in the conversation, worded with /copy-pass and sent to the owner before launch (for example "{name} shared this conversation with their mentor. Messages from now on can be read by them."). Text only, voice messages as a line, no images or translations, as the default says. The tasks that build the mentor's view and the sharing line must apply this: store the share's start time and read only messages after it, and add the notice to both people's views and the other member's push or email if the plan sends one. Tests: a message from before the share is never returned to the mentor, and the other member's view shows the notice.
- **Item 7, who an introducer can pick from:** the default, option B (matches, likes either way, profile views, the map and Spotlight in the last 8 weeks).
- **Item 12, the matching setting:** the default, built and off by default; an existing match is untouched.
- **Item 20, limits:** the default, 5 recommendations and 5 suggested pairs a week, an address once ever, each person once per introducer.
- **All other items:** the defaults as written. New lines go through /copy-pass and to the owner before launch.

## Spec conflicts and decisions needing the owner

Each item has the default this plan builds. The owner may change any of them.

1. **Release 1 scope.** Default: steps 1, 2 and 3 read-only, each behind its own switch in the spec's rollout order. The chaperone (phase 3b, section 9) is release 2: it needs group conversations in the chat server and "ships after the read-only sharing has proved itself".
2. **Criteria in Filters (brief decision 1).** Default: option A; the 4 new controls live in the alert sheet only, and Filters gains one row into it (1.6). Option B (1.7) changes the deck and is not built.
3. **"See who joined" (2).** Default: Discover with the new members who fit first, and 1.13's line once.
4. **Where the visitor form lives (3).** Default: the landing page only; the empty deck carries the member alert.
5. **Visitor regions (4).** Default: the Map's 6 continents with "Anywhere" first; the first region is not guessed.
6. **Recommendations from non-members (5).** Default: the 6-digit code first; the same weekly limit, counted per address.
7. **Who an introducer can pick from (6).** Default: option B: matches, likes either way, profile views, members on the introducer's map and members in a published Spotlight post in the last 8 weeks. The export marks neither option; option A "is usually empty" (5b.3).
8. **How long an introduction stays open (7).** Default: 14 days, then it closes silently and the card says the date.
9. **The introducer told (8).** Default: only when both accept, by push and a toast; never of a decline, an expiry or a rejection.
10. **A viewer held by the photo gate (9).** Default: the name-seeded gradient.
11. **The line in the conversation (10) and "mentor" (11).** Default: both, as drawn.
12. **The matching setting (12).** Default: off. When on, members with a live shared conversation leave that member's deck and map, cannot be introduced to them, and cannot share a conversation with them ("This conversation cannot be shared.", NEW LINE). An existing match is untouched.
13. **Where the single reads the mentor's notes (13).** Default: on their view of that match (8.5).
14. **How often.** Default: members at most once a day (first tick from 12:00 UTC), visitors at most once a week (Thursday from 12:00 UTC, as 4.5 says "this week"); neither inside one of his rest periods, the count carrying over. He may prefer a member's own morning.
15. **One email for both reasons.** Default: the alert email carries the likes block (4.3) when both are due and that week's likes email then skips the member; beside an active alert with email on, the likes email drops its new-fit line. The two never arrive on one day.
16. **Sabbath.** The export's sample "Keeps the seventh-day Sabbath" is not a profile answer. Default: the row offers the profile's 4 Sabbath answers (`SHABBATS`) as pills; empty is Any.
17. **Prompts on the card and in the mentor's view.** Profile prompts are not built (no table on 20 Oct). Default: the profile's About until the prompts release, then prompts.
18. **The mentor's name.** A mentor has no profile, yet 6.4 and 6.6 name "Ruth". Default: the part of the mentor's address before the `@`, capitalised, until a follow-up lets the mentor give a first name; the single can see the address beside it.
19. **Channels and settings.** Default: an alert's push and email are its own switches (1.1, 1.8), with email when push cannot reach the member (1.5). Introduction notices follow the Matches switches in Notifications, since the export draws no Introductions row and 5.2's footer points to Notifications.
20. **Limits.** Default: 5 recommendations a week per sender and 5 suggested pairs a week per introducer, counted separately, the week from Monday 00:00 UTC; an address is recommended once ever; each person is suggested once ever by one introducer. 5a.5 calls recommendations "introductions"; the counters are still separate.
21. **Lines the export does not have**, marked `NEW LINE` in the code, for `/copy-pass` and the owner: 5 of the 6 email titles ("New people who fit.", "Someone who fits joined.", "Someone thought of you.", "An introduction.", "Be a mentor on Ahavah."); the subject "Turn on your Ahavah alert"; "Hello {first name}." in the visitor emails (the form promises "So we can greet you"); the plural "{n} new members this week."; "1 person is also waiting for your answer"; "Ages 26 to 34, in 3 countries." and "in North America."; "3 countries" and "{n} chosen" on a row; "Any", "Yes", "No" for Wants children; "a woman aged 30 to 40" without a region; the reach labels "Your match", "You liked them", "Liked you"; "Someone" when a name is missing; "This conversation cannot be shared."; "A voice message"; "Use the email you were invited with."; the privacy title "Alerts, introductions and mentors" and paragraph; the 2 social captions. The consent line (3.1) and the disclosure lines (8.1, 8.2) go through ux-writing as the spec asks.
22. **Moderation > Text** serves 5 features in the admin brief. Default: built with the introduction note kinds only; the others join with their features.
23. **Flagged notes.** Default: a recommendation or introduction note caught by the rude words, scam or contact details filter waits for review; the sender sees 5a.4 for a recommendation (the single must not learn of moderation) and 5b.10 for an introduction; rejecting tells nobody.
24. **0073 depends on 0071.** Its outbox check names `email_outbox.organiser_id`. Default: Events' API merges first. If Matchmaker must ship first, Task 1 drops `organiser_id` from the check, and Events' 0071 must then name `recommendation_id` and `mentor_link_id` in its own rewrite before it deploys, or its `ADD CONSTRAINT` fails on any Matchmaker outbox row.
25. **Email headings that carry a name or a count** cannot be title images, and typed headlines are not allowed. Default: a fixed title (Task 4's table) with the drawn heading as the first body line; 4.5's heading becomes the subject and the shorter title.
26. **Credit for a recommended single.** Default: first touch wins, as for every source: a single who arrives through the member's `/i/{code}` link is a referral, and `intro` is written only when nothing else was. "Singles who joined" counts recommendations by address, whatever the source says.
27. **`/families` content.** Brief 9 (10.1) and brief 11 (`PAGES.families`) draw different heads, and brief 11's Questions say "[Answer, written by the owner]". Default: 10.1's head, body and its 4 written questions and answers, with brief 11's title, description and share image line; he may replace the answers.
28. **The mentor's sign-in.** Default: the invitation link signs the mentor in once (it proves the address); later sign-ins use the standard 6-digit code, whose email says "Sign in to Ahavah". A mentor-worded code email means a purpose on `/request-otp`, the sign-in path every member uses; a follow-up if he wants it.
29. **One mentor per single.** Default: one, as drawn. The mentor's switcher (7.5) serves a mentor with several singles.
30. **What a mentor reads.** Default: the whole shared conversation as the single sees it, text only; voice messages as a line; images or translations are not shown. The conversation's history before sharing is included, since 7.10 draws earlier messages.
31. **Retention the spec does not set.** Default: a recommended address and note erased 7 days after sending (its keyed hash kept 12 months), recommendation rows deleted after 12 months; an unmatched introduction's note erased 30 days after it closes, a matched one kept while the match is the chat's context; a visitor's alert follows its lead, deleted at once when stopped; removing a mentor deletes their notes and ends every share; a mentor account serving nobody deleted after 30 days; mentor sessions 30 days. Stated on the privacy page.
32. **Reports.** Default: no new report button on the introduction card; a member reports the introducer or the other person from their profile as today ("reports go to moderation").
33. **The visitor's "Join to see them".** Default: `/auth/sign-up?from=alert`; the criteria carry over only when the visitor joins with the same address (the alert is found through its lead at finish-onboarding).
34. **Columns and tables beyond the spec's data list**: `match_alert.lead_id` (the spec's "email"), `first_name`, `notify_push`, `notify_email`, the confirm and stop tokens, `resends`, `counted_since`, `likes_told_at`, `paused_at`; the tables `match_alert_notice`, `recommendation`, `mentor_session`; `introduction.status`, `flag_reason`, the response times, `closes_at`, `opened_at`, `introducer_told_at`, the review columns, `note_erased_at`; `mentor_link.mentor_normalized_email`, `relation`, the invitation token; `shared_conversation.other_person_id` and `mentor_link_id` beside the spec's `other_person_uuid`; `mentor_note.about_person_id` in place of `about_person_uuid`, so a deleted account takes its notes; `person.no_mentor_shared_matches`; `email_outbox.recommendation_id` and `mentor_link_id`.
35. **Routes beyond the spec**: the spec names none. Every route in Tasks 2 and 5 to 13 is this plan's.
36. **Unverified while writing this plan**: that the lodgereport unpacking (`[3][0][3][0][1]`) reads every stored text message, voice notes included (Task 12 tests both shapes); that `Q_MAP_MARKERS`'s predicates can be lifted into `visible_sql` without its cache (Task 9); that a `/check-otp` onboardee session for an address with no account leaves no onboarding row behind that a later sign-up trips on (Task 12 checks, as `tool_visitor` does); that pycountry knows every code `person.country` holds (Task 3 pins it); that the 2 social artworks export from the design project (Step 12).

## Self-review

**Spec coverage.**

| Requirement (matchmaker spec, growth spec, briefs) | Task |
|---|---|
| Nobody browses anyone they could not already see | 9, 12 |
| Every introduction needs both people to accept | 10 |
| A mentor sees only what the single shares; the other person is always told | 11, 12, 24, 25 |
| Members save criteria from the empty deck or Filters: age band, countries, relocation, observance, Sabbath and calendar, wants children | 3, 5, 18 |
| One notice, email and push, at most one a day, batched, names nobody, a count and "See who joined" | 4, 7, 18 |
| The likes-waiting email carries the same line, never two emails for one reason | 4, 7 |
| Visitors on the landing: email confirmed by link, a man or a woman, an age band, a region, an optional first name | 6, 20 |
| The visitor's one email with a count and sign-up with the criteria carried over; source `alert:visitor` | 4, 6, 7 |
| `match_alert`; a cron using the search query's own predicates; the outbox; proofs first | 1, 3, 7, 15 |
| Recommend Ahavah to a single, with the referral code for a member, one email, nothing shared | 8, 21, 26 |
| Suggest two members the introducer can see; private notices; Accept or Not for me; matched only if both accept, the note at the top of the chat; silent declines | 9, 10, 22, 23 |
| Limits: each person once, 5 pairs a week | 9 |
| `introduction` | 1 |
| A single invites a mentor by email from Settings; the mentor confirms; no profile, never in search; removable at any time | 11, 12, 24, 25 |
| The mentor sees matches as the single sees them, shared conversations one at a time read only, and leaves private notes | 12, 25 |
| The notice in the chat header; "Do not match me with members who share conversations" | 11, 24 |
| `mentor_link`, `shared_conversation`, `mentor_note`, `mentor_account` as a role | 1 |
| Screens mobile first at 390 | 18 to 26 |
| Measurement: alerts and visitor sign-ups; introductions, both accepted, conversations; mentors invited and active; members choosing not to be matched | 13, 28 |
| Rollout: members, visitors, introductions, mentors read-only; 3b after | 2, 30 |
| Risks: the single in control; weekly limits, one suggestion per person, silent declines, reports to moderation | 9, 10, 11, 13, 29 |
| Landing "Not ready? Tell me when someone who fits joins" | 20 |
| `/families` as a trust page with its title, description, share image and sitemap entry; For families in the footer | 26, 30 |
| Social: "Know someone single? Introduce them" and the families carousel | 30 |
| Sources `alert:visitor`, `intro`, `mentor`; Growth rows for Alerts, Introductions and Mentors; the user drawer's alerts, introductions and mentor links; Moderation > Text for introduction notes | 6, 13, 14, 28, 29 |
| Privacy page names alerts, introductions, mentor links and shared conversations; consent wording through ux-writing and the owner | 27, 30 |
| Retention and deletion of what is stored | 14, 27 |

Not covered by decision, each in the list above: the chaperone (1), the other kinds of Moderation > Text (22), prompts (17), the `mentor` source, which release 1 writes for nobody since every mentor is invited by an existing member (26).

**Step scan.** Each code step names its file, signatures and the spec's values; the migration, the titles and the copy are written out because they are decisions. The bodies left to the implementer are the ones the signatures and tests fix.

**Type consistency.** `MatchmakerError(reason, status, extra)` is raised by every module and read by the routes' error answer; `fits_sql(owner)` and `fit_params(...)` (Task 3) are what Task 7 binds; `note_flag` and `week_start` (Task 8) are reused by Task 9; `notify_both` (Task 9) and `send_recommendation` (Task 8) are what Task 13's approvals call; `CAMPAIGN_SWITCHES` (Task 2) names the campaigns Task 4 queues; `Criteria` keys in `api.ts` are `MEMBER_KEYS`; `Region` ids are `regions.REGIONS`; the mentor's `X-Mentor-Token` is issued by Task 12 and sent by Task 16's calls.

**Review Focus.** Each of the 5 lines has its test in the task named.

**Proportion.** The plan writes out the schema, the titles, the copy and the tests' assertions; the rest is signatures.

## Owner's answers, second round (21 Oct 2026)

- **Who a member can recommend:** only people they have interacted with in the last 8 weeks, from every source: matches, likes, views, the map and Spotlight. Before this answer, the limit applied to Spotlight only.
- **Admin drawer:** keep both Grant mod and Clear onboardee.
