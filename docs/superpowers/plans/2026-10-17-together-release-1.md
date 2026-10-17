Linear: TEC-1845

# Together, release 1: the compatibility game in 3 modes and the marriage checklist v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Visitors play a 2 minute compatibility game alone (Me), with one person (Us) or with friends (Who knows me best), and couples answer the marriage checklist privately and then compare, all without an account; saving a result or inviting someone needs an email confirmed by the existing 6-digit code, every result has a share image that never shows an answer, and the whole release stays dark behind one switch until launch.

**Architecture:** The API gains four tables (migration 0068) and a `service/tools` package: a Python port of the web's 9-rule scoring engine pinned by a cross-repo test, pure result functions (archetype, guesses, checklist comparison), a session store keyed on per-player tokens (only their sha256 is stored), saves through the onboardee or member session `/check-otp` already issues, a public summary for share links, a tombstone delete, a 12 month sweep and three emails through the outbox plus a direct invite email held by `signupguard`. Five switches, all off: one dark-launch switch (`together_live`, like `questions_live`) and four sends. The web adds `/together`, `/together/game`, `/tools/i/{token}`, `/tools/r/{token}` with its images, checklist v2 at `/marriage-checklist` (v1 still served while dark), "Play Us together" in a match's chat and the carry of game answers into sign-up, all transcribed from the Claude Design export.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pydantic, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16.2.6, React 19, `next/og` `ImageResponse`, vitest and Testing Library (ahavah-web); Next.js and `node --test` (ahavah-admin).

**Spec:** `docs/superpowers/specs/2026-10-13-couple-tools-design.md`, with the shared `docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md`. Design brief: `ahavah-web/docs/design-briefs/2026-10-13-together-couple-tools.md`. Source of truth for screens and copy: `ahavah-web/Claude Design/Ahavah Together.html` (`pages/p07-together.js`), `Ahavah Together Share Images.html` (`pages/p07b-share-images.js`, `kit/ahv-arch.js`), every string in `Claude Design/handoff/copy/07-together.md`, the kit `Claude Design/kit/*`. Builds on `docs/superpowers/plans/2026-10-16-growth-foundations.md` (leads, the source taxonomy, the outbox for lead mail, `src/lib/share-image/`, the `tool` post kind) and follows the patterns of `docs/superpowers/plans/2026-10-16-quick-questions-release-1.md` (switches, proofs, the dark-launch switch, privacy paragraphs, the launch runbook).

## Before you start

- Production's last migration is 0067 (`ahavah/main` at 13698f2 on 17 Oct). This plan adds 0068 only.
- ahavah-api: branch `together` from `ahavah/main`. ahavah-web: branch `together` from `master` (8fec051 on 17 Oct). ahavah-admin: branch `together` from `master` (940b7f2). Use superpowers:using-git-worktrees.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. Every test command uses the shared `ahavah-api-postgres-1` database, which other sessions also use. Never remove, reset or recreate that container or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Web tests run with `cd /d/Antigravity/ahavah-web && npx vitest run <file>`. Admin tests run with `cd /d/Antigravity/ahavah-admin && node --test tests/<file>.test.mjs`.
- Task 16's cross-repo test reads `../ahavah-api/tests/fixtures/together_scoring_cases.json`, so the two checkouts must sit side by side under `/d/Antigravity/`, as they do.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845`, no attribution trailers.
- Line numbers are hints measured on 17 Oct (ahavah-api `origin/ahavah/main` 13698f2, ahavah-web `origin/master` 8fec051). Every edit is anchored on the code it quotes; trust the quote over the number.
- Read `ahavah-web/AGENTS.md` and `node_modules/next/dist/docs/` before the web tasks: Next 16.2 differs from older versions (`params` is a promise; `opengraph-image` reads fonts with `readFile(join(process.cwd(), ...))`).
- The web tasks transcribe the export with `/sot-sync` once their tests are green. The code below fixes behaviour, data and copy; the markup and kit classes come from the export frame each task names.

## Global Constraints

Every task's requirements include these. Quoted lines are verbatim from the specs, the brief or the owner's decisions of 17 Oct.

- Copy: sentence case, British spelling, no em dashes, digits for numbers, no serial comma, "Marriage, courtship and spouse; never 'dating'", "Torah-observant believers, never Jewish framing", "Feasts by their biblical English names", "no countdowns, no urgency, no exclamation marks". This covers UI strings, email text, captions, code comments and commit messages. Strings come verbatim from `handoff/copy/07-together.md`; every line this plan had to add is listed under "Spec conflicts" and goes through `/copy-pass` (ux-writing) and the owner before launch.
- Plural marriage: "The game has no question, area, bar or archetype for it, and no frame mentions it. The engine keeps that area at weight 0."
- Privacy: "Answers are only readable by the two players through their tokens, and by no admin screen except as counts." "Rows are deleted 12 months after the last visit, or on request." "No answers are ever on public cards, and results are behind unguessable tokens." "Guests in 'knows me' give only a display name."
- Identity: "Playing needs nothing: no email, no account." Saving, comparing and the image need "the same one-time code and onboardee session the checklist already uses (`POST /request-otp`, `/check-otp`, `expected_onboarding_status=None`), so no new auth."
- Leads: written only while `AHAVAH_TOOL_LEADS_ENABLED` is on (`service.leads.tool_leads_enabled`), with the sources `tool:game-me`, `tool:game-us`, `tool:knows-me`, `tool:checklist`. A member is never a lead. No marketing consent box on the tools (owner decision 11).
- Mail: every new or changed email is behind its own switch in `service/campaigns/switches.py`, off by default, passed through "in the form `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}`, in both environment blocks of `docker-compose.production.yml`" (api and cron), and each needs `together_live` as well. Proofs go to `harrigan.tennyson@gmail.com` only, never through the outbox. Mail to a player goes through the outbox; any endpoint that sends mail is held by `signupguard` (`service.leads.mail_refusal`) and the per-recipient limit ("5 an hour per recipient for invite emails").
- Dark launch: while `together_live` is off every `/tools` route except `GET /tools/status` answers 404, `/together` is not found and `/marriage-checklist` serves today's checklist unchanged.
- Screens: every visual comes from the Claude Design export; mobile first at 390; "Nothing scrolls sideways on a phone: answers stack, the comparison stacks, the leaderboard is a list"; touch targets at least 44 px; dark first with the light variant; the checklist goes dark-first with the paper canvas as its light variant.
- Share images: "It never shows answers." "Every value is a slot." Flexbox only, fonts as ttf or woff, 500 KB bundle cap.
- Social: "captions carry no link and never say 'link below'"; Instagram posts carry no link; no stock or staged faces; nothing that says dating.

## Review Focus

The five inputs the spec implies but does not test, most likely to bite a player first. Each has a test in the task named.

1. A player who skips questions, up to every one: scored the way the engine scores an empty profile field, never an error; Me with nothing answered still gets an archetype and no "why". Task 3, `test_the_port_scores_each_shared_case_as_the_web_engine_does[partial]`; Task 4, `test_no_answers_gives_the_sabbath_keeper_with_no_why`; Task 16, `scores a player who skipped almost everything`.
2. An invite link opened twice, on a second phone or by a third person in an Us game or checklist: the first guest keeps the seat, a second join is refused as full and the page offers to play alone. Task 7, `test_a_second_guest_is_refused_in_a_two_player_mode`; Task 22, `says the game is full and offers to play alone`.
3. The person who started opening their own invite link while signed in: refused, so nobody compares with themselves. Task 7, `test_the_owner_cannot_join_their_own_game`.
4. Two players finishing at the same moment: one result, computed once, and the answered email goes only to whoever finished first. Task 6, `test_us_reveals_nothing_until_both_have_finished`; Task 10, `test_the_answered_email_goes_to_whoever_finished_first`.
5. A display name that is blank, very long, all spaces or carries control characters or markup: refused or cleaned before it reaches a board, an image or an email. Task 6, `test_a_display_name_is_cleaned_or_refused`; Task 10, `test_names_are_escaped_in_every_email`.

## Decisions taken

The owner may still change any of these.

Owner defaults, 17 Oct. The numbers are the brief's ("Owner decisions this brief needs"), and every "decision N" in this plan means the brief's number:

1. **Name.** "Together" is the short label (overline, chip, nav); "For couples and the single season" is the page title.
2. **Archetypes.** The 8 archetypes and their lines as the export draws them (4.2), approved through the owner's proofs.
3. **Questions.** The questions as the export draws them, approved through the proofs. The spring feasts are the export's default frame (3.3), without Hanukkah and Purim; the 3.5 variant is not used.
4. **The second player.** The lighter version: the second player sees the result through the invite link and is asked for an email only to save it or get the image. The strict frame (4.6) is not used for the second player; its two lines are reused only where a player reopens a saved result on another device (Task 21).
5. **Telling the first player.** One email through the outbox when the second player finishes ("Rivka has answered. See how you fit."), proofed first, behind `together_answered_email`.
6. **Right answers for friends.** Friends in Who knows me best see their own score and the board, never the answers.
7. **The knows-me share image.** The invitation only; it never names the top friend.
8. **The app's pill.** Keeps its current weights. Only the game uses weight 0 for plural marriage; nothing in `src/lib/scoring/weights.ts` or `compat-pill.tsx` changes.
9. **Exodus 21:10-11.** Stays in the checklist as today. The export's "without Exodus 21" variants are not used.
10. **Stored-answers wording.** Changes everywhere it appears, with the export's wording (6.1 and 5.1).
11. **Consent box.** None on the tools.
12. **Checklist results email.** Stays as today, plus a "your comparison is ready" email (6.12). In v2 the summary goes to the player who finished (they now answer separately), with the stored-answers line in place of "never stored".
13. **Checklist in dark.** Dark first, with the paper canvas as its light variant.

Choices this plan makes where the spec leaves one:

- **A `tool_player` table** sits beside the spec's three: answers are keyed on a player, so a knows-me board can hold any number of friends with their own tokens. The spec's `tool_answer.player` becomes `player_id`.
- **Tokens.** A player token is 32 characters (`service.leads.new_token`), sent as the `X-Tool-Token` header and stored only as its sha256. Share and invite tokens are 22 characters (`secrets.token_urlsafe(16)`), stored as they are, because the owner must be able to send them again. A player who saved may also reopen with a signed-in session for that address.
- **Endpoints beyond the spec's list:** `GET /tools/status`, `GET /tools/sessions/{id}`, `POST .../finish`, `POST /tools/i/{token}/players` (joining), `POST .../invite-email`, `DELETE` and `POST .../players/{id}` (removing and restoring a name on the board), `POST /tools/r/{token}/open` (counting a share opening) and `GET /admin/growth/tools` (counts).
- **Claiming uses the session, not a raw code:** the web runs `/request-otp` and `/check-otp` with the tool's source, then `POST /tools/sessions/{id}/claim` with that session and the player token. A member skips the code.
- **Guest names.** Every guest gives a name when they start (Us, the checklist partner and knows-me friends), so the owner's screens, the reveal and the share image can name them. See "Spec conflicts", item 2.
- **Language order.** The language rule divides by the first person's languages, so the server always scores with the owner as the first person. Both players see that one score.
- **Areas and bars.** The 8 areas are the engine's axes without plural marriage, labelled as the export labels them. "Where you align most" is the 3 highest, "Worth talking about" the 2 lowest of the rest, ties in the export's order. A round's bar is the mean of its axes (rounds 1 and 5 have two).
- **The Me archetype** is the archetype whose round the player answered most strongly, on a points rule written in Task 4; ties go to the export's order; nothing answered gives The Sabbath Keeper with no "why".
- **Who knows me best** scores the 14 scored questions the player answered: a friend's guess is right when it equals the answer (a multiple choice as a set). Light questions are guessed for fun and not counted.
- **The checklist comparison** compares the passages both rated: a different stance is tagged "Different stance", otherwise importance 2 or more apart is tagged "Importance 2 apart", otherwise it is in "Where you agree". Own items are listed per person. Comments show to the other person, as the export says (6.6, 6.8).
- **Retention:** saved sessions go 12 months after the last visit by a player; a session nobody saved goes after 30 days; a deleted session is a tombstone (no names, emails, answers or results, only its tokens, so a link can say "deleted") for 30 days, then goes.
- **Account deletion** deletes every session the address owns and every Us or checklist session it joined (a comparison is shared).
- **Checklist v1 while dark.** `/marriage-checklist` keeps serving today's client while `together_live` is off and serves v2 once it is on, so the live page never shows v2 copy before v2 stores anything. Task 24 Step 8 removes v1 after launch.
- **The invite email** goes straight to the mailer after the request commits, as the checklist's spouse email does today: its recipient is neither a member nor a lead, so the outbox (which needs one) cannot hold it. It is held by `signupguard`, the per-account limit and the shared per-recipient limit.
- **Share links** carry `utm_source=share`, `utm_medium=together`, `utm_campaign` = the source without `tool:` (`game-us`), so first-touch capture credits them as `utm:share/game-us`.

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `migrations/0068_together.sql` | Create | `tool_session`, `tool_player`, `tool_answer`, `tool_result` |
| `service/tools/__init__.py` | Create | `live()`, `switch_on()` |
| `service/tools/questions.py` | Create | The game's question keys and options, answer checks |
| `service/tools/scoring.py` | Create | The port of the web engine, answers to profile, the Us result |
| `service/tools/results.py` | Create | The Me archetype, knows-me guesses, the board order |
| `service/tools/checklist.py` | Create | Checklist keys, answer checks, the comparison, the top items |
| `service/tools/sessions.py` | Create | Start, answer, finish, read, claim, join, public summary, delete, link at sign-up |
| `service/tools/mail.py` | Create | The answered, ready, summary and invite emails |
| `service/tools/retention.py` | Create | The sweep |
| `service/tools/admin.py` | Create | Counts for the Growth tab |
| `service/api/tools_routes.py` | Create | Every `/tools` route |
| `service/api/__init__.py` | Modify | Registers the routes |
| `service/api/admin/growth_routes.py` | Modify | `GET /admin/growth/tools` |
| `duotypes/__init__.py` | Modify | Request models |
| `service/campaigns/switches.py` | Modify | 5 switches |
| `docker-compose.production.yml` | Modify | 5 pass-throughs in api and cron |
| `service/person/__init__.py` | Modify | Links sessions at finish-onboarding; the checklist send docstring |
| `service/api/__init__.py` (the checklist route docstring), `duotypes/__init__.py` (`MarriageChecklistAnswer` docstring) | Modify | Stored-answers wording |
| `emails/marriage_checklist.py` | Modify | The stored variant of the summary |
| `service/cron/leadretention/__init__.py` | Modify | Runs the tool sweep |
| `service/hard_delete.py`, `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py` | Modify | `Q_DELETE_TOOL_DATA_OF` with the account |
| `scripts/send_together_proofs.py` | Create | Proofs to the owner only |
| `tests/fixtures/together_scoring_cases.json` | Create | Cases both engines must score alike |
| `tests/conftest.py` | Modify | `together_schema`, `together_live`, `no_limits`, `tool_visitor` |
| `tests/test_migration_0068.py`, `test_together_switches.py`, `test_together_scoring.py`, `test_together_results.py`, `test_together_checklist.py`, `test_tool_sessions.py`, `test_tool_invites.py`, `test_tool_claim.py`, `test_tool_public.py`, `test_tool_mail.py`, `test_tool_invite_email.py`, `test_send_together_proofs.py`, `test_tool_retention.py`, `test_admin_tool_counts.py` | Create | One file per task |

ahavah-web:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/api-client.ts` | Modify | An optional `headers` argument |
| `src/lib/auth-otp.ts` | Modify | `checkOtp` takes the tool sources |
| `src/lib/together/api.ts`, `storage.ts`, `status.ts` | Create | API calls with the player token, device storage, the live check |
| `src/lib/together/questions.ts`, `profile.ts`, `sentence.ts`, `share.ts`, `carry.ts` | Create | Questions and copy, answers to profile, "You in a sentence", share text and links, the sign-up carry |
| `src/lib/share-image/fonts.ts`, `src/lib/share-image/fonts/*` | Create | Ultra and Plus Jakarta Sans for the images |
| `src/lib/share-image/together-templates.tsx` | Create | The 5 templates, link preview and story |
| `src/lib/share-image/templates.tsx`, `render.tsx` | Modify | Registers them; passes fonts |
| `src/app/together/page.tsx`, `src/app/together/game/page.tsx`, `src/app/tools/i/[token]/page.tsx`, `src/app/tools/r/[token]/page.tsx`, `opengraph-image.tsx`, `story/route.ts` | Create | Pages and images |
| `src/components/together/*` | Create | Hub, mode choice, questions, save step, share panel, results, second player, delete |
| `src/components/app/marriage-checklist/checklist-v2.tsx`, `comparison.tsx` | Create | Checklist v2 |
| `src/components/app/marriage-checklist/checklist-client.tsx`, `src/app/marriage-checklist/page.tsx`, `content.ts`, `marriage-checklist.css` | Modify | Shared screens exported; v1 or v2 by the switch; stored wording; dark first |
| `src/components/app/chat-more-menu.tsx`, `src/components/app/chat-thread-view.tsx` | Create, modify | "Play Us together" |
| `src/app/auth/sign-up/page.tsx`, `src/app/onboarding/verify-email/page.tsx`, `src/app/onboarding/relocation/page.tsx`, `src/app/onboarding/complete/page.tsx`, `src/components/together/from-your-game.tsx` | Modify, create | Answers carried into sign-up |
| `src/lib/legal-leads-copy.ts`, `src/lib/legal-together-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` | Create, modify | The privacy paragraphs |
| `src/app/sitemap.ts` | Modify | `/together` |
| `tests/lib/together-*.test.ts`, `tests/components/together-*.test.tsx`, `tests/app/together-*.test.tsx`, `tests/app/legal-together.test.tsx` | Create | Tests per task |

ahavah-admin:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/together-launch.ts`, `scripts/together-launch-entries.mjs`, `tests/together-launch.test.mjs` | Create | The launch posts for the calendar |
| `content/social-calendar.json`, `assets/social/together-launch-*.jpg` | Modify, add | Only at launch, after the owner confirms (Task 29) |

---

## Release 1 API (ahavah-api)

### Task 1: Migration 0068, the Together tables

**Files:**
- Create: `migrations/0068_together.sql`
- Create: `tests/test_migration_0068.py`
- Modify: `tests/conftest.py` (append the `together_schema` fixture after `questions_schema`)

**Interfaces:**
- Consumes: `person` (FK targets), `growth_schema` (0066).
- Produces: tables `tool_session(id bigserial, uuid uuid unique, kind, mode, owner_email, owner_normalized_email, owner_person_id -> person ON DELETE CASCADE, owner_display 1..40, share_token unique, invite_token unique, source in the 4 tool sources, utm jsonb, share_opens int, invite_emails int, created_at, claimed_at, completed_at, deleted_at, last_visit_at)`, `tool_player(id, session_id -> tool_session CASCADE, seat 'owner'|'guest', token_hash unique, display 1..40, role 'husband'|'wife', email, normalized_email, person_id -> person CASCADE, finished_at, removed_at, created_at)` with one owner per session, `tool_answer(session_id, player_id, question_key slug <= 64, answer jsonb, answered_at)` keyed on `(player_id, question_key)`, `tool_result(id, session_id, player_id null for the session's own result, score 0..100, breakdown jsonb, archetype, computed_at)` unique on `(session_id, COALESCE(player_id, 0))`; session fixture `together_schema`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0068.py`:

```python
"""Migration 0068: the Together tables (TEC-1845).

Pins what later tasks rely on: a mode belongs to its tool, a session's
source is a tool source, one owner per session and any number of guests,
one answer per player and question, results bounded, display names 1 to 40
characters, and deleting a session takes everything under it. The deploy
may run the file more than once, so every test runs it twice first.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_MIGRATION = (Path(__file__).resolve().parent.parent
              / 'migrations' / '0068_together.sql')


def _apply() -> None:
    with api_tx() as tx:
        tx.execute(_MIGRATION.read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice(growth_schema):
    _apply()
    _apply()


def _session(tx, kind: str = 'game', mode: str = 'us', source: str = 'tool:game-us') -> int:
    return tx.execute(
        """INSERT INTO tool_session (kind, mode, source) VALUES (%(k)s, %(m)s, %(s)s)
           RETURNING id""", dict(k=kind, m=mode, s=source)).fetchone()['id']


def _player(tx, sid: int, seat: str = 'owner', display: str | None = None) -> int:
    return tx.execute(
        """INSERT INTO tool_player (session_id, seat, token_hash, display)
           VALUES (%(s)s, %(seat)s, %(h)s, %(d)s) RETURNING id""",
        dict(s=sid, seat=seat, h=uuid4().hex, d=display)).fetchone()['id']


def _drop(sid: int) -> None:
    with api_tx() as tx:
        tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))


@pytest.mark.parametrize('kind,mode', [('game', 'couple'), ('checklist', 'us'), ('game', 'dating')])
def test_a_mode_belongs_to_its_tool(kind, mode):
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            _session(tx, kind, mode)


def test_a_session_source_is_a_tool_source():
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            _session(tx, source='utm:facebook')


def test_one_owner_per_session_and_any_number_of_guests():
    with api_tx() as tx:
        sid = _session(tx, mode='knows_me', source='tool:knows-me')
        _player(tx, sid)
        _player(tx, sid, 'guest')
        _player(tx, sid, 'guest')
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                _player(tx, sid)
    finally:
        _drop(sid)


def test_an_answer_key_is_a_slug_and_one_per_player_and_question():
    with api_tx() as tx:
        sid = _session(tx)
        pid = _player(tx, sid)
        tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                      VALUES (%(s)s, %(p)s, 'calendar', '"enoch"')""", dict(s=sid, p=pid))
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                              VALUES (%(s)s, %(p)s, 'calendar', '"other"')""", dict(s=sid, p=pid))
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                              VALUES (%(s)s, %(p)s, 'Not A Key', '1')""", dict(s=sid, p=pid))
    finally:
        _drop(sid)


def test_deleting_a_session_takes_its_players_answers_and_results():
    with api_tx() as tx:
        sid = _session(tx)
        pid = _player(tx, sid)
        tx.execute("""INSERT INTO tool_answer (session_id, player_id, question_key, answer)
                      VALUES (%(s)s, %(p)s, 'move', '"local-only"')""", dict(s=sid, p=pid))
        tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 82)", dict(s=sid))
    _drop(sid)
    with api_tx() as tx:
        left = [tx.execute(f'SELECT count(*) AS n FROM {t} WHERE session_id = %(s)s',
                           dict(s=sid)).fetchone()['n']
                for t in ('tool_player', 'tool_answer', 'tool_result')]
    assert left == [0, 0, 0]


def test_a_score_stays_between_0_and_100_and_one_result_per_player():
    with api_tx() as tx:
        sid = _session(tx)
        tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 100)", dict(s=sid))
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 101)",
                           dict(s=sid))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO tool_result (session_id, score) VALUES (%(s)s, 50)",
                           dict(s=sid))
    finally:
        _drop(sid)


def test_a_display_name_is_1_to_40_characters():
    with api_tx() as tx:
        sid = _session(tx)
    try:
        for bad in ('', 'x' * 41):
            with pytest.raises(psycopg.errors.CheckViolation):
                with api_tx() as tx:
                    _player(tx, sid, 'guest', bad)
    finally:
        _drop(sid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0068.py -q -p no:warnings`
Expected: every test errors in `_applied_twice` with `FileNotFoundError` for `0068_together.sql`.

- [ ] **Step 3: Write the migration and the fixture**

Create `migrations/0068_together.sql`:

```sql
-- 0068_together.sql
-- Together, release 1 (TEC-1845,
-- docs/superpowers/specs/2026-10-13-couple-tools-design.md; plan
-- docs/superpowers/plans/2026-10-17-together-release-1.md).
--
--   tool_session  one game (me, us, knows_me) or one checklist (couple,
--                 single). The owner's email, account and display name
--                 are set when they save. share_token opens the public
--                 summary (never an answer); invite_token starts a second
--                 player. A deleted session keeps only its tokens and
--                 deleted_at, so a link can say it was deleted.
--   tool_player   the owner and every guest. Only the sha256 of a
--                 player's token is stored. A guest in knows_me gives only
--                 a display name.
--   tool_answer   one answer per player and question, readable only by
--                 the players (service/tools/sessions.py).
--   tool_result   the session's result (player_id NULL) or a knows_me
--                 friend's score.
--
-- No column, mode or area for plural marriage. Deleted 12 months after
-- the last visit, 30 days after creation if never saved, or on request
-- (service/tools/retention.py). Idempotent: the deploy may run this file
-- more than once.

CREATE TABLE IF NOT EXISTS tool_session (
  id                      BIGSERIAL    PRIMARY KEY,
  uuid                    UUID         NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  kind                    TEXT         NOT NULL CHECK (kind IN ('game', 'checklist')),
  mode                    TEXT         NOT NULL,
  owner_email             TEXT,
  owner_normalized_email  TEXT,
  owner_person_id         INT          REFERENCES person(id) ON DELETE CASCADE,
  owner_display           TEXT         CHECK (owner_display IS NULL
                                              OR char_length(owner_display) BETWEEN 1 AND 40),
  share_token             TEXT         UNIQUE,
  invite_token            TEXT         UNIQUE,
  source                  TEXT         NOT NULL CHECK (source IN ('tool:game-me', 'tool:game-us',
                                                                  'tool:knows-me', 'tool:checklist')),
  utm                     JSONB,
  share_opens             INT          NOT NULL DEFAULT 0,
  invite_emails           INT          NOT NULL DEFAULT 0,
  created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  claimed_at              TIMESTAMPTZ,
  completed_at            TIMESTAMPTZ,
  deleted_at              TIMESTAMPTZ,
  last_visit_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CHECK ((kind = 'game' AND mode IN ('me', 'us', 'knows_me'))
      OR (kind = 'checklist' AND mode IN ('couple', 'single')))
);

CREATE INDEX IF NOT EXISTS idx__tool_session__owner_ne
  ON tool_session (owner_normalized_email) WHERE owner_normalized_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx__tool_session__last_visit_at ON tool_session (last_visit_at);

CREATE TABLE IF NOT EXISTS tool_player (
  id                BIGSERIAL    PRIMARY KEY,
  session_id        BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  seat              TEXT         NOT NULL CHECK (seat IN ('owner', 'guest')),
  token_hash        TEXT         NOT NULL UNIQUE,
  display           TEXT         CHECK (display IS NULL OR char_length(display) BETWEEN 1 AND 40),
  role              TEXT         CHECK (role IN ('husband', 'wife')),
  email             TEXT,
  normalized_email  TEXT,
  person_id         INT          REFERENCES person(id) ON DELETE CASCADE,
  finished_at       TIMESTAMPTZ,
  removed_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx__tool_player__one_owner
  ON tool_player (session_id) WHERE seat = 'owner';
CREATE INDEX IF NOT EXISTS idx__tool_player__session ON tool_player (session_id);
CREATE INDEX IF NOT EXISTS idx__tool_player__ne
  ON tool_player (normalized_email) WHERE normalized_email IS NOT NULL;

CREATE TABLE IF NOT EXISTS tool_answer (
  session_id    BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  player_id     BIGINT       NOT NULL REFERENCES tool_player(id) ON DELETE CASCADE,
  question_key  TEXT         NOT NULL CHECK (question_key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'
                                             AND char_length(question_key) <= 64),
  answer        JSONB        NOT NULL,
  answered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (player_id, question_key)
);

CREATE INDEX IF NOT EXISTS idx__tool_answer__session ON tool_answer (session_id);

CREATE TABLE IF NOT EXISTS tool_result (
  id           BIGSERIAL    PRIMARY KEY,
  session_id   BIGINT       NOT NULL REFERENCES tool_session(id) ON DELETE CASCADE,
  player_id    BIGINT       REFERENCES tool_player(id) ON DELETE CASCADE,
  score        INT          CHECK (score BETWEEN 0 AND 100),
  breakdown    JSONB        NOT NULL DEFAULT '{}'::jsonb,
  archetype    TEXT,
  computed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx__tool_result__session_player
  ON tool_result (session_id, COALESCE(player_id, 0));
```

Append to `tests/conftest.py`, after the `questions_schema` fixture:

```python
# ---------------------------------------------------------------------------
# Together (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0068 is idempotent, so applying it here is what the deploy does.
# A module that reads the tool tables asks for it with
#     pytestmark = pytest.mark.usefixtures('together_schema')

@pytest.fixture(scope='session')
def together_schema(growth_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0068_together.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0068.py -q -p no:warnings`
Expected: `9 passed`.

- [ ] **Step 5: Apply the migration to the shared test database**

Later suites that do not ask for `together_schema` (finish-onboarding, the deletion cron) run code that touches these tables. The file is idempotent, so apply it alone:
Run: `docker exec -i ahavah-api-postgres-1 psql -X -v ON_ERROR_STOP=1 -U postgres -d duo_api < /d/Antigravity/ahavah-api/migrations/0068_together.sql`
Expected: a list of `CREATE TABLE` and `CREATE INDEX` notices, exit code 0. Never remove, reset or recreate the container.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add migrations/0068_together.sql tests/test_migration_0068.py tests/conftest.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the tool session, player, answer and result tables" -m "Refs: TEC-1845"
```

---

### Task 2: The 5 switches, the live check and `GET /tools/status`

**Files:**
- Modify: `service/campaigns/switches.py` (`SWITCHES`, after the `'questions_launch_push'` entry)
- Modify: `docker-compose.production.yml` (api block after `AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED`; cron block after `AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED`)
- Create: `service/tools/__init__.py`, `service/api/tools_routes.py`
- Modify: `service/api/__init__.py` (register the routes after the questions routes)
- Modify: `tests/conftest.py` (append `together_live`, `no_limits`, `tool_visitor`)
- Test: `tests/test_together_switches.py` (create)

**Interfaces:**
- Consumes: `service.campaigns.switches.enabled`.
- Produces: switch names `together_live`, `together_invite_email`, `together_answered_email`, `together_ready_email`, `together_summary_email`; `service.tools.live() -> bool`; `service.tools.switch_on(name) -> bool` (live and the named switch); `GET /tools/status` -> `{live: bool, invite_email: bool}`, `Cache-Control: no-store`; fixtures `together_live` (sets `AHAVAH_TOGETHER_LIVE_ENABLED=1`), `no_limits` (Flask-Limiter off), `tool_visitor()` -> `(email, headers)` for an onboardee session with no account.

- [ ] **Step 1: Write the failing test**

Create `tests/test_together_switches.py`:

```python
"""The Together switches (TEC-1845).

together_live keeps the whole release dark until launch, as questions_live
did for the quick questions. Each email has its own switch and needs
together_live too. Each variable is passed through to both the api and the
cron containers, defaulting to 0: without the pass-through a switch can
never be turned on.
"""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'together_live': 'AHAVAH_TOGETHER_LIVE_ENABLED',
    'together_invite_email': 'AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED',
    'together_answered_email': 'AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED',
    'together_ready_email': 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
    'together_summary_email': 'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2, (
        f'{env} must be passed through in both the api and the cron blocks, defaulting to 0')


def test_each_send_needs_the_live_switch(monkeypatch):
    from service.tools import live, switch_on
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    assert live() is False and switch_on('together_invite_email') is False
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    assert live() is True and switch_on('together_invite_email') is True
    assert switch_on('together_ready_email') is False


def test_status_says_dark_until_live(client, monkeypatch):
    for env in NEW.values():
        monkeypatch.delenv(env, raising=False)
    r = client.get('/tools/status')
    assert r.status_code == 200
    assert r.get_json() == {'live': False, 'invite_email': False}
    assert r.headers['Cache-Control'] == 'no-store'
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    assert client.get('/tools/status').get_json() == {'live': True, 'invite_email': True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_switches.py -q -p no:warnings`
Expected: `8 failed` (no switches, no compose lines, `ModuleNotFoundError: No module named 'service.tools'`, `/tools/status` 404).

- [ ] **Step 3: Write the implementation**

In `service/campaigns/switches.py`, add at the end of `SWITCHES`, after `'questions_launch_push': 'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED',`:

```python
    # Together (TEC-1845), the master switch: until launch every /tools
    # route but /tools/status answers 404, /together is not found and the
    # marriage checklist stays as it was. Nothing below sends while it is
    # off, whichever way its own switch is set (service.tools.switch_on).
    'together_live': 'AHAVAH_TOGETHER_LIVE_ENABLED',
    # Together's emails, each off until the owner has seen its proof: the
    # invite a player sends, the note that the other person has answered
    # (game), the note that the comparison is ready (checklist) and the
    # checklist summary a player gets when they finish.
    'together_invite_email': 'AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED',
    'together_answered_email': 'AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED',
    'together_ready_email': 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
    'together_summary_email': 'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED',
```

In `docker-compose.production.yml`, in the `api` service's environment, replace:

```yaml
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      # Meta Conversions API (service/metapixel.py) — no-op when blank.
```

with:

```yaml
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      # Together (TEC-1845). Off until launch (live) and until the owner
      # confirms each email's proof. The api serves the routes and queues
      # the emails.
      AHAVAH_TOGETHER_LIVE_ENABLED: ${AHAVAH_TOGETHER_LIVE_ENABLED:-0}
      AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED: ${AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED: ${AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_READY_EMAIL_ENABLED: ${AHAVAH_TOGETHER_READY_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED: ${AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED:-0}
      # Meta Conversions API (service/metapixel.py) — no-op when blank.
```

The `# Meta Conversions API` line is existing text and keeps its punctuation. In the `cron` service's environment, replace:

```yaml
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      DUO_CRON_MAX_RANDOM_START_DELAY: ${DUO_CRON_MAX_RANDOM_START_DELAY:-15}
```

with:

```yaml
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      # Together (TEC-1845): the cron drains the queued emails and runs the
      # 12 month sweep. Off until launch and each proof.
      AHAVAH_TOGETHER_LIVE_ENABLED: ${AHAVAH_TOGETHER_LIVE_ENABLED:-0}
      AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED: ${AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED: ${AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_READY_EMAIL_ENABLED: ${AHAVAH_TOGETHER_READY_EMAIL_ENABLED:-0}
      AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED: ${AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED:-0}
      DUO_CRON_MAX_RANDOM_START_DELAY: ${DUO_CRON_MAX_RANDOM_START_DELAY:-15}
```

Create `service/tools/__init__.py`:

```python
"""Together, release 1: the couple tools (TEC-1845).

docs/superpowers/specs/2026-10-13-couple-tools-design.md and
docs/superpowers/plans/2026-10-17-together-release-1.md.

  questions  the game's question keys and options
  scoring    the port of the web's scoring engine, the Us result
  results    the Me archetype, knows-me guesses, the board
  checklist  checklist keys, the comparison, the top items
  sessions   start, answer, finish, read, save, join, share, delete
  mail       the invite, answered, ready and summary emails
  retention  the 12 month sweep
  admin      counts for Admin > Growth, never answers

Dark until launch: while the together_live switch is off
(AHAVAH_TOGETHER_LIVE_ENABLED, service/campaigns/switches.py) every /tools
route but /tools/status answers 404 and no Together email is queued or
sent, whichever way its own switch is set. The proofs
(scripts/send_together_proofs.py) and the admin counts work either way.
"""
from service.campaigns.switches import enabled


def live() -> bool:
    """Together is launched: the routes answer."""
    return enabled('together_live')


def switch_on(name: str) -> bool:
    """An email's own switch, which counts only once Together is live."""
    return live() and enabled(name)
```

Create `service/api/tools_routes.py`:

```python
"""Together, the public routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as questions_routes is.
Playing needs no account: a player proves who they are with the
X-Tool-Token header the device keeps. Saving uses the onboardee or member
session /check-otp already issues. Every route but /tools/status answers
404 while together_live is off.
"""
from __future__ import annotations

from service.api.decorators import get


@get('/tools/status')
def get_tools_status():
    """What the web needs before it shows Together: whether it is live, and
    whether the invite email may be offered."""
    from service.tools import live, switch_on
    return (dict(live=live(), invite_email=switch_on('together_invite_email')),
            200, {'Cache-Control': 'no-store'})
```

In `service/api/__init__.py`, after:

```python
# Quick questions (TEC-1845).
import service.api.questions_routes  # noqa: E402,F401
import service.api.admin.questions_routes  # noqa: E402,F401
```

add:

```python
# Together, the couple tools (TEC-1845).
import service.api.tools_routes  # noqa: E402,F401
```

Append to `tests/conftest.py`, after `together_schema`:

```python
@pytest.fixture
def together_live(monkeypatch):
    """The master switch on (AHAVAH_TOGETHER_LIVE_ENABLED): Together as
    players see it after launch. tests/test_tool_sessions.py tests the
    dark state."""
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')


@pytest.fixture
def no_limits(monkeypatch):
    """Flask-Limiter off, so a test sees only the rules it is about."""
    from service.api.decorators import limiter
    monkeypatch.setattr(limiter, 'enabled', False)


@pytest.fixture
def tool_visitor():
    """A visitor with no account who confirmed an address with a sign-in
    code: an onboardee session, as /check-otp leaves it. Returns
    (email, headers). Sessions, onboardees and leads for the address are
    deleted afterwards."""
    import hashlib
    import secrets
    from uuid import uuid4

    from database import api_tx

    made: list[str] = []

    def _make(email: str | None = None) -> tuple[str, dict]:
        address = email or f'visitor-{uuid4().hex[:12]}@ahavah-test.invalid'
        tok = secrets.token_hex(32)
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO duo_session (session_token_hash, email, signed_in, otp)
                   VALUES (%(h)s, %(e)s, TRUE, '123456')""",
                dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=address))
        made.append(address)
        return address, {'Authorization': f'Bearer {tok}'}

    yield _make

    with api_tx() as tx:
        for address in made:
            tx.execute('DELETE FROM duo_session WHERE email = %(e)s', dict(e=address))
            tx.execute('DELETE FROM lead WHERE email = %(e)s', dict(e=address))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_switches.py tests/test_question_switches.py tests/test_return_mail_cron.py -q -p no:warnings`
Expected: all pass (8 new, the two existing switch suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/campaigns/switches.py docker-compose.production.yml service/tools/__init__.py service/api/tools_routes.py service/api/__init__.py tests/conftest.py tests/test_together_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): 5 switches off by default, passed to the api and the cron, and /tools/status" -m "Refs: TEC-1845"
```

---

### Task 3: The game's questions and the scoring port, pinned to the web engine

**Files:**
- Create: `service/tools/questions.py`, `service/tools/scoring.py`
- Create: `tests/fixtures/together_scoring_cases.json`
- Test: `tests/test_together_scoring.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `questions.GAME_QUESTIONS: tuple[Question, ...]`, `questions.BY_KEY`, `questions.SCORED_KEYS` (14 keys), `questions.clean_game_answer(key: str, answer) -> str | list[str]` raising `ValueError('bad_question' | 'bad_answer')`; `scoring.answers_to_profile(answers: dict) -> dict` (the web `Profile` field names), `scoring.compute_compatibility(a: dict, b: dict, weights=GAME_WEIGHTS) -> {'score': int, 'breakdown': dict[str, float]}`, `scoring.GAME_WEIGHTS`, `scoring.js_round(x: float) -> int`, `scoring.AREAS` (8 axes, display order), `scoring.ROUND_AXES`, `scoring.us_result(owner_answers: dict, guest_answers: dict) -> {'score': int, 'areas': dict[str, float], 'align': list[str], 'talk': list[str], 'bars': list[{'round': str, 'pct': int}]}`; the shared fixture `tests/fixtures/together_scoring_cases.json` that Task 16 reads from the web.

The question keys and option keys below are the contract with the web (`src/lib/together/questions.ts`, Task 17). The labels live on the web only.

| Key | Round | Options (key) | Multi | Light | Fills |
|---|---|---|---|---|---|
| `calendar` | sabbath | rabbinic, aviv-barley, enoch, luni-solar, observational-new-moon, other | | | `calendar` |
| `torah-walk` | sabbath | learning, beginner, intermediate, experienced | | | `torahLevel` |
| `sabbath-afternoon` | sabbath | walk, guests, study, quiet | | yes | |
| `spring-feasts` | feasts | passover, unleavened-bread, first-fruits, shavuot | yes | | `feastDays` |
| `autumn-feasts` | feasts | trumpets, yom-kippur, sukkot | yes | | `feastDays` |
| `favourite-feast` | feasts | the 7 above | | yes | |
| `has-children` | family | yes, no | | | `familyViews` (yes: has-children) |
| `children-hope` | family | yes, open-to-more, large-family, blended, no | | | `familyViews` (wants-children, open-to-more, interested-large-family, open-blended, does-not-want) |
| `city-or-country` | home | city, country | | | `livingPreferences` (urban, rural) |
| `homestead` | home | homestead, off-grid, neither | | | `livingPreferences` |
| `community` | home | yes, no | | | `livingPreferences` (yes: community-living) |
| `sabbath-host` | home | me, spouse, both, less-tired | | yes | |
| `country` | moving | an ISO code from the country list | | | `country` |
| `move` | moving | will-relocate, wants-partner-willing, local-only, international-open | | | `relocation` |
| `languages` | moving | language codes from the language list, at most 10 | yes | | `languages` |
| `pace` | talk | frequent, slow-paced-courtship | | | `communicationPrefs` |
| `talk-how` | talk | video-calls, texting, in-person | yes | | `communicationPrefs` |

- [ ] **Step 1: Write the shared fixture**

Create `tests/fixtures/together_scoring_cases.json`:

```json
{
  "about": "Together (TEC-1845). Game answers both engines must score alike: ahavah-api service/tools/scoring.py (tests/test_together_scoring.py) and ahavah-web src/lib/scoring with src/lib/together/profile.ts (tests/lib/together-scoring-parity.test.ts). The owner is the first person. Expected values worked by hand from the web rules on 17 Oct 2026; change them only with both engines.",
  "cases": [
    {
      "name": "identical",
      "owner": {"calendar": "aviv-barley", "torah-walk": "intermediate", "sabbath-afternoon": "walk", "spring-feasts": ["passover", "unleavened-bread", "first-fruits", "shavuot"], "autumn-feasts": ["trumpets", "yom-kippur", "sukkot"], "has-children": "no", "children-hope": "large-family", "city-or-country": "country", "homestead": "homestead", "community": "yes", "country": "US", "move": "will-relocate", "languages": ["en"], "pace": "frequent", "talk-how": ["video-calls", "in-person"]},
      "guest": {"calendar": "aviv-barley", "torah-walk": "intermediate", "sabbath-afternoon": "quiet", "spring-feasts": ["passover", "unleavened-bread", "first-fruits", "shavuot"], "autumn-feasts": ["trumpets", "yom-kippur", "sukkot"], "has-children": "no", "children-hope": "large-family", "city-or-country": "country", "homestead": "homestead", "community": "yes", "country": "US", "move": "will-relocate", "languages": ["en"], "pace": "frequent", "talk-how": ["video-calls", "in-person"]},
      "score": 100,
      "breakdown": {"calendar": 1.0, "polygyny": 0.5, "family": 1.0, "relocation": 1.0, "lifestyle": 1.0, "communication": 1.0, "observance": 1.0, "feast": 1.0, "language": 1.0}
    },
    {
      "name": "apart",
      "owner": {"calendar": "rabbinic", "torah-walk": "learning", "spring-feasts": ["passover"], "has-children": "no", "children-hope": "no", "city-or-country": "city", "homestead": "neither", "community": "no", "country": "GB", "move": "local-only", "languages": ["en", "fr"], "pace": "slow-paced-courtship", "talk-how": ["texting"]},
      "guest": {"calendar": "aviv-barley", "torah-walk": "experienced", "spring-feasts": ["passover", "unleavened-bread"], "autumn-feasts": ["sukkot"], "has-children": "yes", "children-hope": "yes", "city-or-country": "country", "homestead": "homestead", "community": "yes", "country": "US", "move": "local-only", "languages": ["en"], "pace": "frequent", "talk-how": ["video-calls"]},
      "score": 21,
      "breakdown": {"calendar": 0.4, "polygyny": 0.5, "family": 0.0, "relocation": 0.0, "lifestyle": 0.0, "communication": 0.2, "observance": 0.2, "feast": 0.383333333333, "language": 0.5}
    },
    {
      "name": "partial",
      "owner": {"calendar": "luni-solar"},
      "guest": {"calendar": "observational-new-moon", "torah-walk": "beginner", "spring-feasts": ["passover"], "has-children": "no", "children-hope": "open-to-more", "city-or-country": "city", "homestead": "neither", "community": "no", "country": "BB", "move": "international-open", "languages": ["en", "es"], "pace": "frequent", "talk-how": ["texting"]},
      "score": 41,
      "breakdown": {"calendar": 0.7, "polygyny": 0.5, "family": 0.4, "relocation": 0.5, "lifestyle": 0.4, "communication": 0.4, "observance": 0.5, "feast": 0.4, "language": 0.0}
    },
    {
      "name": "order-matters",
      "owner": {"calendar": "enoch", "torah-walk": "beginner", "spring-feasts": ["passover", "unleavened-bread", "first-fruits", "shavuot"], "autumn-feasts": ["trumpets"], "has-children": "yes", "children-hope": "open-to-more", "city-or-country": "city", "homestead": "off-grid", "community": "yes", "country": "JM", "move": "wants-partner-willing", "languages": ["en"], "pace": "frequent", "talk-how": ["video-calls", "texting"]},
      "guest": {"calendar": "other", "torah-walk": "intermediate", "spring-feasts": ["passover", "shavuot"], "autumn-feasts": ["trumpets", "yom-kippur"], "has-children": "no", "children-hope": "blended", "city-or-country": "country", "homestead": "off-grid", "community": "no", "country": "JM", "move": "will-relocate", "languages": ["en", "es", "fr"], "pace": "frequent", "talk-how": ["texting", "in-person"]},
      "score": 59,
      "reversed_score": 50,
      "breakdown": {"calendar": 0.3, "polygyny": 0.5, "family": 0.0, "relocation": 1.0, "lifestyle": 0.35, "communication": 0.6, "observance": 0.8, "feast": 0.65, "language": 1.0}
    }
  ]
}
```

How the expected values were reached, for whoever changes them: "apart" sums 0.4 + 0 + 0 + 0 + 0.2 + 0.2 + 0.3833 + 0.5 = 1.6833 over 8 axes, 21.04, so 21; "partial" sums 3.3 over 8, 41.25, so 41; "order-matters" sums 4.7 over 8, 58.75, so 59, and with the guest first the language rule gives 1 of 3, so 4.0333 over 8, 50.42, so 50. Plural marriage has weight 0, so its 0.5 is in the breakdown and not in the score.

- [ ] **Step 2: Write the failing test**

Create `tests/test_together_scoring.py`:

```python
"""The game's scoring, ported from the web (TEC-1845).

Spec: "The rules are ported to Python in the API, with a cross-repo test
that both copies give identical scores for the same answers." Both copies
read tests/fixtures/together_scoring_cases.json; the web's half is
ahavah-web tests/lib/together-scoring-parity.test.ts. The game gives plural
marriage weight 0 and asks nothing about it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.tools import questions, scoring

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json'
CASES = json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_the_port_scores_each_shared_case_as_the_web_engine_does(case):
    a = scoring.answers_to_profile(case['owner'])
    b = scoring.answers_to_profile(case['guest'])
    r = scoring.compute_compatibility(a, b)
    assert r['score'] == case['score']
    assert set(r['breakdown']) == set(case['breakdown'])
    for axis, want in case['breakdown'].items():
        assert r['breakdown'][axis] == pytest.approx(want, abs=1e-9), axis
    if 'reversed_score' in case:
        assert scoring.compute_compatibility(b, a)['score'] == case['reversed_score']


def test_plural_marriage_has_weight_0_and_no_question():
    assert scoring.GAME_WEIGHTS['polygyny'] == 0
    assert all(w == 1 for axis, w in scoring.GAME_WEIGHTS.items() if axis != 'polygyny')
    assert not [q.key for q in questions.GAME_QUESTIONS if 'polyg' in q.key or 'wife' in q.key]
    assert 'polygyny' not in scoring.AREAS
    full = {q.key: (q.options[:1] if q.multi else q.options[0]) for q in questions.GAME_QUESTIONS
            if q.options}
    assert 'polygyny' not in scoring.answers_to_profile(full)


def test_js_round_rounds_halves_up_as_math_round_does():
    assert [scoring.js_round(x) for x in (20.5, 21.5, 58.75, 41.25, 0.0)] == [21, 22, 59, 41, 0]


def test_light_questions_never_score():
    assert scoring.answers_to_profile(
        {'sabbath-afternoon': 'walk', 'favourite-feast': 'sukkot', 'sabbath-host': 'both'}) == {}
    assert questions.SCORED_KEYS == (
        'calendar', 'torah-walk', 'spring-feasts', 'autumn-feasts', 'has-children',
        'children-hope', 'city-or-country', 'homestead', 'community', 'country', 'move',
        'languages', 'pace', 'talk-how')


def test_answers_map_onto_the_profile_fields():
    owner = next(c for c in CASES if c['name'] == 'order-matters')['owner']
    assert scoring.answers_to_profile(owner) == {
        'calendar': 'enoch', 'torahLevel': 'beginner',
        'feastDays': ['passover', 'unleavened-bread', 'first-fruits', 'shavuot', 'trumpets'],
        'familyViews': ['has-children', 'open-to-more'],
        'livingPreferences': ['urban', 'off-grid', 'community-living'],
        'country': 'JM', 'relocation': 'wants-partner-willing', 'languages': ['en'],
        'communicationPrefs': ['frequent', 'video-calls', 'texting'],
    }


@pytest.mark.parametrize('key,answer,reason', [
    ('nope', 'x', 'bad_question'),
    ('calendar', 'julian', 'bad_answer'),
    ('spring-feasts', [], 'bad_answer'),
    ('spring-feasts', ['hanukkah'], 'bad_answer'),
    ('country', 'usa', 'bad_answer'),
    ('languages', ['en', 'es', 'fr', 'de', 'it', 'nl', 'ru', 'pl', 'uk', 'he', 'yi'], 'bad_answer'),
])
def test_a_bad_answer_is_refused(key, answer, reason):
    with pytest.raises(ValueError, match=reason):
        questions.clean_game_answer(key, answer)


def test_a_clean_answer_keeps_order_and_drops_repeats():
    assert questions.clean_game_answer('talk-how', ['texting', 'texting', 'in-person']) == [
        'texting', 'in-person']
    assert questions.clean_game_answer('country', 'BB') == 'BB'


def test_the_us_result_names_areas_and_round_bars():
    case = next(c for c in CASES if c['name'] == 'order-matters')
    r = scoring.us_result(case['owner'], case['guest'])
    assert r['score'] == 59
    assert r['align'] == ['relocation', 'language', 'observance']
    assert r['talk'] == ['family', 'calendar']
    assert r['bars'] == [
        {'round': 'sabbath', 'pct': 55}, {'round': 'feasts', 'pct': 65},
        {'round': 'family', 'pct': 0}, {'round': 'home', 'pct': 35},
        {'round': 'moving', 'pct': 100}, {'round': 'talk', 'pct': 60}]
    assert set(r['areas']) == set(scoring.AREAS)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_scoring.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'questions' from 'service.tools'`.

- [ ] **Step 4: Write the implementation**

Create `service/tools/questions.py`:

```python
"""The game's questions, as keys (TEC-1845).

Mirrors ahavah-web src/lib/together/questions.ts: the same question keys,
rounds and option keys, in the same order. The words players read live on
the web only; the API checks keys. Each scored question fills a profile
field the scoring engine reads, so a game result and a profile score mean
the same thing. Light questions ("Just for fun") never score. No question
about plural marriage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

ROUNDS = ('sabbath', 'feasts', 'family', 'home', 'moving', 'talk')

FEASTS_SPRING = ('passover', 'unleavened-bread', 'first-fruits', 'shavuot')
FEASTS_AUTUMN = ('trumpets', 'yom-kippur', 'sukkot')


@dataclass(frozen=True)
class Question:
    key: str
    round: str
    options: tuple[str, ...]
    multi: bool = False
    light: bool = False
    long_list: Optional[str] = None  # 'country' or 'language': the web's lists


GAME_QUESTIONS: tuple[Question, ...] = (
    Question('calendar', 'sabbath', ('rabbinic', 'aviv-barley', 'enoch', 'luni-solar',
                                     'observational-new-moon', 'other')),
    Question('torah-walk', 'sabbath', ('learning', 'beginner', 'intermediate', 'experienced')),
    Question('sabbath-afternoon', 'sabbath', ('walk', 'guests', 'study', 'quiet'), light=True),
    Question('spring-feasts', 'feasts', FEASTS_SPRING, multi=True),
    Question('autumn-feasts', 'feasts', FEASTS_AUTUMN, multi=True),
    Question('favourite-feast', 'feasts', FEASTS_SPRING + FEASTS_AUTUMN, light=True),
    Question('has-children', 'family', ('yes', 'no')),
    Question('children-hope', 'family', ('yes', 'open-to-more', 'large-family', 'blended', 'no')),
    Question('city-or-country', 'home', ('city', 'country')),
    Question('homestead', 'home', ('homestead', 'off-grid', 'neither')),
    Question('community', 'home', ('yes', 'no')),
    Question('sabbath-host', 'home', ('me', 'spouse', 'both', 'less-tired'), light=True),
    Question('country', 'moving', (), long_list='country'),
    Question('move', 'moving', ('will-relocate', 'wants-partner-willing', 'local-only',
                                'international-open')),
    Question('languages', 'moving', (), multi=True, long_list='language'),
    Question('pace', 'talk', ('frequent', 'slow-paced-courtship')),
    Question('talk-how', 'talk', ('video-calls', 'texting', 'in-person'), multi=True),
)

BY_KEY = {q.key: q for q in GAME_QUESTIONS}
SCORED_KEYS = tuple(q.key for q in GAME_QUESTIONS if not q.light)

LANGUAGES_MAX = 10
_COUNTRY = re.compile(r'^[A-Z]{2}$')
_LANGUAGE = re.compile(r'^[a-z]{2,3}$')


def clean_game_answer(key: str, answer: Any) -> Any:
    """The answer as it is stored: an option key, or a list of them with
    repeats dropped and the order kept. Raises ValueError('bad_question')
    for a key the game does not ask, ValueError('bad_answer') for anything
    else that is not one of its options."""
    q = BY_KEY.get(key)
    if q is None:
        raise ValueError('bad_question')
    if q.multi:
        if not isinstance(answer, list) or not answer or len(answer) > LANGUAGES_MAX:
            raise ValueError('bad_answer')
        if q.long_list == 'language':
            ok = all(isinstance(a, str) and _LANGUAGE.match(a) for a in answer)
        else:
            ok = all(isinstance(a, str) and a in q.options for a in answer)
        if not ok:
            raise ValueError('bad_answer')
        out: list[str] = []
        for a in answer:
            if a not in out:
                out.append(a)
        return out
    if q.long_list == 'country':
        if not isinstance(answer, str) or not _COUNTRY.match(answer):
            raise ValueError('bad_answer')
        return answer
    if not isinstance(answer, str) or answer not in q.options:
        raise ValueError('bad_answer')
    return answer
```

Create `service/tools/scoring.py`:

```python
"""The game's scoring: a port of ahavah-web src/lib/scoring (TEC-1845).

Spec: "Reuses the existing engine (compute-compatibility.ts, 9 axes). ...
The plural marriage axis has weight 0 and no question. The rules are
ported to Python in the API, with a cross-repo test that both copies give
identical scores for the same answers ... so a stored result is computed
on the server and cannot be tampered with."

Each rule below is the TypeScript rule of the same name, line for line,
and returns a number from 0 to 1. Change one only with its twin and the
shared fixture (tests/fixtures/together_scoring_cases.json). JavaScript's
Math.round rounds halves up, Python's round() rounds them to even, so the
composite uses js_round. The web's app pill keeps its own weights
(owner decision 8); only the game uses GAME_WEIGHTS.

The language rule divides by the first person's languages, so a game is
always scored with its owner first.
"""
from __future__ import annotations

import math
from typing import Any

from service.tools.questions import ROUNDS

AXES = ('calendar', 'polygyny', 'family', 'relocation', 'lifestyle', 'communication',
        'observance', 'feast', 'language')
# BALANCED with plural marriage at 0: excluded from both sides of the mean.
GAME_WEIGHTS = {axis: (0 if axis == 'polygyny' else 1) for axis in AXES}

# The 8 areas a player sees, in the export's order (Calendar, Torah walk,
# The feasts, Children, Home, Moving, Language, How you talk).
AREAS = ('calendar', 'observance', 'feast', 'family', 'lifestyle', 'relocation', 'language',
         'communication')
# The 6 bars, one per round: the mean of the round's axes.
ROUND_AXES = {
    'sabbath': ('calendar', 'observance'),
    'feasts': ('feast',),
    'family': ('family',),
    'home': ('lifestyle',),
    'moving': ('relocation', 'language'),
    'talk': ('communication',),
}

_LUNI_SOLAR_FAMILY = frozenset({'luni-solar', 'observational-new-moon', 'aviv-barley'})
_PRO_CREATION = ('wants-children', 'has-children', 'open-to-more', 'interested-large-family')
_CORE_FEASTS = frozenset({'passover', 'unleavened-bread', 'first-fruits', 'shavuot',
                          'trumpets', 'yom-kippur', 'sukkot'})
_RANK = {'learning': 0, 'beginner': 1, 'intermediate': 2, 'experienced': 3}
_PROXIMITY = {0: 1.0, 1: 0.8, 2: 0.5, 3: 0.2}
_POLYGYNY = {
    'monogamy-only|monogamy-only': 1.0, 'open|open': 0.9, 'supports|supports': 1.0,
    'undecided|undecided': 0.7, 'open|supports': 0.8, 'monogamy-only|supports': 0.0,
    'supports|undecided': 0.5, 'monogamy-only|open': 0.4, 'open|undecided': 0.6,
    'monogamy-only|undecided': 0.5,
}
_RELOCATION = {
    'will-relocate|will-relocate': 1.0, 'wants-partner-willing|will-relocate': 1.0,
    'local-only|will-relocate': 0.8, 'international-open|will-relocate': 0.9,
    'wants-partner-willing|wants-partner-willing': 0.5, 'local-only|wants-partner-willing': 0.2,
    'international-open|wants-partner-willing': 0.7,
    'international-open|international-open': 1.0, 'international-open|local-only': 0.5,
}
_CHILDREN_HOPE = {'yes': 'wants-children', 'open-to-more': 'open-to-more',
                  'large-family': 'interested-large-family', 'blended': 'open-blended',
                  'no': 'does-not-want'}


def js_round(x: float) -> int:
    """JavaScript's Math.round for the non-negative numbers scores are."""
    return math.floor(x + 0.5)


def _list(profile: dict, field: str) -> list:
    return list(profile.get(field) or [])


def score_calendar(a: dict, b: dict) -> float:
    ca, cb = a.get('calendar'), b.get('calendar')
    if not ca or not cb:
        return 0.3
    if ca == cb:
        return 1.0
    if ca == 'other' or cb == 'other':
        return 0.3
    if ca in _LUNI_SOLAR_FAMILY and cb in _LUNI_SOLAR_FAMILY:
        return 0.7
    return 0.4


def score_polygyny(a: dict, b: dict) -> float:
    pa, pb = a.get('polygyny'), b.get('polygyny')
    if not pa or not pb:
        return 0.5
    return _POLYGYNY['|'.join(sorted((pa, pb)))]


def score_family(a: dict, b: dict) -> float:
    av, bv = _list(a, 'familyViews'), _list(b, 'familyViews')
    if not av and not bv:
        return 0.5
    if not av or not bv:
        return 0.4
    a_dnw, b_dnw = 'does-not-want' in av, 'does-not-want' in bv
    a_pro = any(v in _PRO_CREATION for v in av)
    b_pro = any(v in _PRO_CREATION for v in bv)
    if (a_dnw and b_pro) or (b_dnw and a_pro):
        return 0.0
    aset, bset = set(av), set(bv)
    inter = len(aset & bset)
    union = len(aset | bset)
    base = 0 if union == 0 else inter / union
    return min(base + (0.1 if inter > 0 else 0), 1.0)


def score_relocation(a: dict, b: dict) -> float:
    ra, rb = a.get('relocation'), b.get('relocation')
    if not ra or not rb:
        return 0.5
    if ra == 'local-only' and rb == 'local-only':
        ca, cb = a.get('country'), b.get('country')
        if not ca or not cb:
            return 0.5
        return 1.0 if ca == cb else 0.0
    return _RELOCATION.get('|'.join(sorted((ra, rb))), 0.5)


def score_lifestyle(a: dict, b: dict) -> float:
    pa, pb = _list(a, 'livingPreferences'), _list(b, 'livingPreferences')
    if not pa and not pb:
        return 0.5
    if not pa or not pb:
        return 0.4
    sa, sb = set(pa), set(pb)
    inter = len(sa & sb)
    union = len(sa | sb)
    base = 0 if union == 0 else inter / union
    return min(1.0, base + (0.1 if inter > 0 else 0))


def score_communication(a: dict, b: dict) -> float:
    ap, bp = _list(a, 'communicationPrefs'), _list(b, 'communicationPrefs')
    if not ap and not bp:
        return 0.5
    if not ap or not bp:
        return 0.4
    sa, sb = set(ap), set(bp)
    inter = len(sa & sb)
    union = len(sa | sb)
    base = 0 if union == 0 else inter / union
    conflict = (('frequent' in sa and 'slow-paced-courtship' in sb)
                or ('slow-paced-courtship' in sa and 'frequent' in sb))
    if conflict and inter == 0:
        return 0.2
    return min(base + (0.1 if inter > 0 else 0), 1.0)


def score_observance(a: dict, b: dict) -> float:
    la, lb = a.get('torahLevel'), b.get('torahLevel')
    if not la or not lb:
        return 0.5
    return _PROXIMITY[abs(_RANK[la] - _RANK[lb])]


def score_feast(a: dict, b: dict) -> float:
    sa, sb = set(_list(a, 'feastDays')), set(_list(b, 'feastDays'))
    if not sa and not sb:
        return 0.5
    if not sa or not sb:
        return 0.4
    inter = [f for f in _list(a, 'feastDays') if f in sb]
    inter = list(dict.fromkeys(inter))
    jaccard = len(inter) / len(sa | sb)
    bonus = 0.0
    for f in inter:
        if f in _CORE_FEASTS:
            bonus += 0.05
    bonus = min(0.35, bonus)
    return min(1.0, jaccard + bonus)


def score_language(viewer: dict, candidate: dict) -> float:
    v = _list(viewer, 'languages')
    if not v:
        return 0.0
    c = set(_list(candidate, 'languages'))
    return sum(1 for lang in v if lang in c) / len(v)


_RULES = {
    'calendar': score_calendar, 'polygyny': score_polygyny, 'family': score_family,
    'relocation': score_relocation, 'lifestyle': score_lifestyle,
    'communication': score_communication, 'observance': score_observance,
    'feast': score_feast, 'language': score_language,
}


def compute_compatibility(a: dict, b: dict, weights: dict = GAME_WEIGHTS) -> dict:
    """computeCompatibility(a, b, weights): each axis 0 to 1, and the
    weighted mean of the axes with a weight above 0 as a whole number from
    0 to 100."""
    breakdown = {axis: _RULES[axis](a, b) for axis in AXES}
    weighted = 0.0
    total = 0.0
    for axis in AXES:
        w = weights[axis]
        if w <= 0 or not math.isfinite(breakdown[axis]):
            continue
        weighted += w * breakdown[axis]
        total += w
    normalized = weighted / total if total > 0 else 0
    return dict(score=js_round(normalized * 100), breakdown=breakdown)


def answers_to_profile(answers: dict[str, Any]) -> dict:
    """The profile fields a set of game answers fills (the web's
    answersToProfile). A skipped question leaves its field out, so the
    engine scores it as it scores an empty profile field. Light questions
    fill nothing."""
    p: dict[str, Any] = {}
    if answers.get('calendar'):
        p['calendar'] = answers['calendar']
    if answers.get('torah-walk'):
        p['torahLevel'] = answers['torah-walk']
    feasts = list(answers.get('spring-feasts') or []) + list(answers.get('autumn-feasts') or [])
    if feasts:
        p['feastDays'] = feasts
    family = []
    if answers.get('has-children') == 'yes':
        family.append('has-children')
    if answers.get('children-hope') in _CHILDREN_HOPE:
        family.append(_CHILDREN_HOPE[answers['children-hope']])
    if family:
        p['familyViews'] = family
    living = []
    if answers.get('city-or-country') == 'city':
        living.append('urban')
    elif answers.get('city-or-country') == 'country':
        living.append('rural')
    if answers.get('homestead') in ('homestead', 'off-grid'):
        living.append(answers['homestead'])
    if answers.get('community') == 'yes':
        living.append('community-living')
    if living:
        p['livingPreferences'] = living
    if answers.get('country'):
        p['country'] = answers['country']
    if answers.get('move'):
        p['relocation'] = answers['move']
    if answers.get('languages'):
        p['languages'] = list(answers['languages'])
    comm = []
    if answers.get('pace'):
        comm.append(answers['pace'])
    comm.extend(answers.get('talk-how') or [])
    if comm:
        p['communicationPrefs'] = comm
    return p


def us_result(owner_answers: dict, guest_answers: dict) -> dict:
    """The Us reveal: the score, each area, the 3 areas that align most,
    the 2 worth talking about and a bar per round. Ties go to the order of
    AREAS."""
    r = compute_compatibility(answers_to_profile(owner_answers), answers_to_profile(guest_answers))
    areas = {axis: r['breakdown'][axis] for axis in AREAS}
    align = sorted(AREAS, key=lambda ax: (-areas[ax], AREAS.index(ax)))[:3]
    talk = [ax for ax in sorted(AREAS, key=lambda ax: (areas[ax], AREAS.index(ax)))
            if ax not in align][:2]
    bars = []
    for rnd in ROUNDS:
        axes = ROUND_AXES[rnd]
        bars.append(dict(round=rnd, pct=js_round(sum(areas[ax] for ax in axes) / len(axes) * 100)))
    return dict(score=r['score'], areas={k: round(v, 4) for k, v in areas.items()},
                align=align, talk=talk, bars=bars)
```

A note on `score_feast`: the web computes the intersection as `[...aSet].filter((f) => bSet.has(f))`, which walks the first person's feasts in their order without repeats; `dict.fromkeys` keeps that order and drops repeats the same way.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_scoring.py -q -p no:warnings`
Expected: `16 passed`.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/questions.py service/tools/scoring.py tests/fixtures/together_scoring_cases.json tests/test_together_scoring.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the game's questions and the scoring engine ported from the web" -m "Refs: TEC-1845"
```

---

### Task 4: The Me archetype, knows-me guesses and the board

**Files:**
- Create: `service/tools/results.py`
- Test: `tests/test_together_results.py` (create)

**Interfaces:**
- Consumes: `questions.SCORED_KEYS`, `questions.BY_KEY`, `scoring.js_round` (Task 3).
- Produces: `results.ARCHETYPES` (8 keys in the export's order: `sabbath`, `feast`, `family`, `builder`, `student`, `peace`, `explorer`, `bridge`), `results.archetype_for(answers: dict) -> tuple[str, list[str]]` (the archetype and its "why", 0 to 2 archetype keys), `results.points(answers) -> dict[str, int]`, `results.guess_score(owner_answers: dict, guess_answers: dict) -> tuple[int, int]` (right, total), `results.board_order(rows: list[dict]) -> list[dict]` (rows with `right`, `finished_at`, `player_id`).

The points rule (0 to 10 per archetype, whole numbers so ties are exact). The owner approves this rule with the archetypes (brief: "how the archetype is picked is a rule engineering writes and the owner approves"):

| Archetype | Points from the player's own answers |
|---|---|
| The Sabbath Keeper (`sabbath`) | calendar answered: 6, or 3 for "Other" |
| The Feast Host (`feast`) | feasts kept, out of 7, times 10, rounded |
| The Family Founder (`family`) | hoped-for children: a large family 10, yes 7, open to more 7, blended 6, no 0; plus 1 if they have children (at most 10) |
| The Steady Builder (`builder`) | a homestead or off the grid 5, community yes 3, country 2 |
| The Faithful Student (`student`) | Torah walk: learning 8, beginner 8, intermediate 5, experienced 3 |
| The Peacemaker (`peace`) | pace: talk often 4, slow and careful 2; plus 2 for each way they like to talk |
| The Explorer (`explorer`) | open to another country 10, would move 8, otherwise 0 |
| The Bridge Builder (`bridge`) | 3 or more languages 10, 2 languages 8, otherwise 0 |

The archetype is the highest; ties go to the order above. "Why this fits you" is the archetype and the next highest with points above 0. With nothing answered the archetype is The Sabbath Keeper and there is no "why".

- [ ] **Step 1: Write the failing test**

Create `tests/test_together_results.py`:

```python
"""The Me archetype, knows-me guesses and the board (TEC-1845)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from service.tools import results

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}


def test_the_feast_host_case_matches_the_export():
    # The export's Me result (4.1): The Feast Host, why "The feasts" and
    # "Family and children".
    assert results.archetype_for(CASES['identical']['owner']) == ('feast', ['feast', 'family'])


def test_ties_go_to_the_export_order():
    # family, builder, student and peace all score 8 here.
    assert results.points(CASES['order-matters']['owner'])['family'] == 8
    assert results.archetype_for(CASES['order-matters']['owner']) == ('family', ['family', 'builder'])


def test_no_answers_gives_the_sabbath_keeper_with_no_why():
    assert results.archetype_for({}) == ('sabbath', [])
    assert results.archetype_for({'sabbath-host': 'both'}) == ('sabbath', [])


@pytest.mark.parametrize('answers,want', [
    ({'calendar': 'enoch'}, 'sabbath'),
    ({'spring-feasts': ['passover', 'unleavened-bread', 'first-fruits', 'shavuot'],
      'autumn-feasts': ['trumpets', 'yom-kippur', 'sukkot']}, 'feast'),
    ({'children-hope': 'large-family'}, 'family'),
    ({'homestead': 'homestead', 'community': 'yes', 'city-or-country': 'country'}, 'builder'),
    ({'torah-walk': 'learning'}, 'student'),
    ({'pace': 'frequent', 'talk-how': ['video-calls', 'texting', 'in-person']}, 'peace'),
    ({'move': 'international-open'}, 'explorer'),
    ({'languages': ['en', 'es', 'fr']}, 'bridge'),
])
def test_every_archetype_can_be_reached(answers, want):
    key, why = results.archetype_for(answers)
    assert key == want and why == [want]


def test_a_friend_scores_right_answers_of_the_questions_the_player_answered():
    owner = CASES['order-matters']['owner']
    guess = dict(owner)
    guess['talk-how'] = ['texting', 'video-calls']        # same set: right
    guess['move'] = 'local-only'                           # wrong
    guess.pop('country')                                   # skipped: wrong
    assert results.guess_score(owner, guess) == (12, 14)


def test_light_questions_and_skips_are_left_out_of_the_total():
    owner = {'calendar': 'enoch', 'move': 'local-only', 'pace': 'frequent',
             'sabbath-host': 'both'}
    guess = {'calendar': 'enoch', 'move': 'local-only', 'sabbath-host': 'both'}
    assert results.guess_score(owner, guess) == (2, 3)


def test_the_board_ranks_by_score_then_who_finished_first():
    t = datetime(2026, 11, 1, tzinfo=timezone.utc)
    rows = [dict(player_id=1, right=10, finished_at=t),
            dict(player_id=2, right=12, finished_at=t + timedelta(minutes=5)),
            dict(player_id=3, right=12, finished_at=t)]
    assert [r['player_id'] for r in results.board_order(rows)] == [3, 2, 1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_results.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'results' from 'service.tools'`.

- [ ] **Step 3: Write the implementation**

Create `service/tools/results.py`:

```python
"""The Me archetype, knows-me guesses and the board (TEC-1845).

Spec, Me: "an archetype from your strongest axes". With no second person
there is nothing to score against, so each archetype earns points from
the player's own answers in its round (the plan's table, approved by the
owner with the archetypes). Whole numbers, so ties are exact, and ties go
to the export's order. "Why this fits you" names the archetype's round and
the next strongest, so the result reads as what the player said. No
archetype draws on plural marriage.

Who knows me best: a friend's guess is right when it equals the player's
answer (a multiple choice as a set). Only the scored questions the player
answered count; light questions are guessed for fun.
"""
from __future__ import annotations

from typing import Any

from service.tools.questions import BY_KEY, SCORED_KEYS
from service.tools.scoring import js_round

ARCHETYPES = ('sabbath', 'feast', 'family', 'builder', 'student', 'peace', 'explorer', 'bridge')

_FAMILY = {'large-family': 10, 'yes': 7, 'open-to-more': 7, 'blended': 6}
_STUDENT = {'learning': 8, 'beginner': 8, 'intermediate': 5, 'experienced': 3}
_PACE = {'frequent': 4, 'slow-paced-courtship': 2}
_EXPLORER = {'international-open': 10, 'will-relocate': 8}


def points(answers: dict[str, Any]) -> dict[str, int]:
    cal = answers.get('calendar')
    feasts = set(answers.get('spring-feasts') or []) | set(answers.get('autumn-feasts') or [])
    languages = len(answers.get('languages') or [])
    return {
        'sabbath': 6 if cal and cal != 'other' else (3 if cal == 'other' else 0),
        'feast': js_round(10 * len(feasts) / 7),
        'family': min(10, _FAMILY.get(answers.get('children-hope'), 0)
                      + (1 if answers.get('has-children') == 'yes' else 0)),
        'builder': ((5 if answers.get('homestead') in ('homestead', 'off-grid') else 0)
                    + (3 if answers.get('community') == 'yes' else 0)
                    + (2 if answers.get('city-or-country') == 'country' else 0)),
        'student': _STUDENT.get(answers.get('torah-walk'), 0),
        'peace': min(10, _PACE.get(answers.get('pace'), 0) + 2 * len(answers.get('talk-how') or [])),
        'explorer': _EXPLORER.get(answers.get('move'), 0),
        'bridge': 10 if languages >= 3 else (8 if languages == 2 else 0),
    }


def archetype_for(answers: dict[str, Any]) -> tuple[str, list[str]]:
    pts = points(answers)
    ranked = sorted(ARCHETYPES, key=lambda k: (-pts[k], ARCHETYPES.index(k)))
    top = ranked[0]
    if pts[top] == 0:
        return 'sabbath', []
    why = [top] + [k for k in ranked[1:2] if pts[k] > 0]
    return top, why


def _same(q_key: str, a: Any, b: Any) -> bool:
    if b is None:
        return False
    if BY_KEY[q_key].multi:
        return set(a) == set(b if isinstance(b, list) else [])
    return a == b


def guess_score(owner_answers: dict, guess_answers: dict) -> tuple[int, int]:
    keys = [k for k in SCORED_KEYS if k in owner_answers]
    right = sum(1 for k in keys if _same(k, owner_answers[k], guess_answers.get(k)))
    return right, len(keys)


def board_order(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r['right'], r['finished_at'], r['player_id']))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_results.py -q -p no:warnings`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/results.py tests/test_together_results.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the Me archetype, knows-me guesses and the board" -m "Refs: TEC-1845"
```

---

### Task 5: The checklist's answers, comparison and top items

**Files:**
- Create: `service/tools/checklist.py`
- Test: `tests/test_together_checklist.py` (create)

**Interfaces:**
- Consumes: `duotypes.MarriageChecklistAnswer` (the existing answer model, reused as the stored shape).
- Produces: `checklist.PASSAGES` (`{'p1': ('Genesis 2:18-24', ('husband', 'wife')), ...}`, the 9 passages of `content.ts`), `checklist.clean_checklist_answer(key: str, answer, role: str | None) -> dict` raising `ValueError('bad_question' | 'bad_answer' | 'role_required')`, `checklist.compare(owner: dict, guest: dict) -> {'agree': int, 'total': int, 'agree_items': list, 'talk_items': list, 'own': {'owner': list, 'guest': list}}`, `checklist.top_items(answers: dict, n=3) -> list[dict]`, `checklist.to_summary_answers(answers: dict) -> list[dict]` (the shape `emails.marriage_checklist.checklist_results_html` takes).

Keys: a passage is its id (`p1` to `p9`; `p2`, Exodus 21:10-11, is the husband's only, as today). A player's own item is `own-` followed by 6 to 40 lowercase letters, digits or hyphens, at most 20 per section.

- [ ] **Step 1: Write the failing test**

Create `tests/test_together_checklist.py`:

```python
"""The checklist v2's answers and comparison (TEC-1845).

Spec: "'Where you agree', item by item, with the importance each person
gave it. 'Talk about these', for differing stances or importance two or
more points apart. Each person's own items side by side." Exodus 21:10-11
stays as today, the husband's passage only (owner decision 9).
"""
from __future__ import annotations

import pytest

from service.tools import checklist


def _p(importance, stance='agree', **kw):
    return dict(section='biblical', importance=importance, stance=stance, **kw)


def _own(title, importance, section='nice-to-have', **kw):
    return dict(section=section, title=title, importance=importance, **kw)


def test_the_passages_are_todays_nine_with_exodus_for_the_husband_only():
    assert list(checklist.PASSAGES) == [f'p{i}' for i in range(1, 10)]
    assert checklist.PASSAGES['p2'] == ('Exodus 21:10-11', ('husband',))


@pytest.mark.parametrize('key,answer,role,reason', [
    ('p2', _p(4), 'wife', 'bad_question'),
    ('p1', _p(4), None, 'role_required'),
    ('p10', _p(4), 'wife', 'bad_question'),
    ('p1', _p(6), 'wife', 'bad_answer'),
    ('p1', dict(section='nice-to-have', importance=3), 'wife', 'bad_answer'),
    ('own-garden1', dict(section='nice-to-have', importance=3), 'wife', 'bad_answer'),
    ('own-garden1', _own('A garden', 3, section='biblical'), 'wife', 'bad_answer'),
    ('own-x', _own('A garden', 3), 'wife', 'bad_question'),
])
def test_a_bad_checklist_answer_is_refused(key, answer, role, reason):
    with pytest.raises(ValueError, match=reason):
        checklist.clean_checklist_answer(key, answer, role)


def test_a_clean_answer_keeps_what_the_email_needs_and_drops_blanks():
    clean = checklist.clean_checklist_answer(
        'own-garden1', _own('  A garden we grow together ', 4, comment='', examples=['', ' tomatoes ']),
        'husband')
    assert clean == dict(section='nice-to-have', title='A garden we grow together', importance=4,
                         examples=['tomatoes'])


def test_the_comparison_tags_what_to_talk_about():
    owner = {'p1': _p(4), 'p3': _p(5), 'p4': _p(3), 'p5': _p(2), 'p2': _p(5),
             'own-garden1': _own('A garden we grow together', 4)}
    guest = {'p1': _p(5), 'p3': _p(5, 'other', other_note='Near my parents'), 'p4': _p(5),
             'p5': _p(2), 'own-host1': _own('Hosting the feasts at home', 5),
             'own-hours1': _own('My work hours', 3, section='challenge', stance='agree')}
    c = checklist.compare(owner, guest)
    assert (c['agree'], c['total']) == (2, 4)
    assert [i['key'] for i in c['agree_items']] == ['p1', 'p5']
    assert [(i['key'], i['tag']) for i in c['talk_items']] == [('p3', 'stance'), ('p4', 'importance')]
    assert c['talk_items'][0]['guest']['other_note'] == 'Near my parents'
    assert [i['title'] for i in c['own']['owner']] == ['A garden we grow together']
    assert [i['title'] for i in c['own']['guest']] == ['Hosting the feasts at home', 'My work hours']


def test_nothing_to_talk_about_and_no_own_items():
    c = checklist.compare({'p1': _p(4)}, {'p1': _p(5)})
    assert (c['agree'], c['total'], c['talk_items'], c['own']) == (
        1, 1, [], {'owner': [], 'guest': []})


def test_the_top_items_leave_challenges_out():
    answers = {'p1': _p(3), 'p3': _p(5), 'own-pray1': _own('We pray together every evening', 5),
               'own-hours1': _own('My work hours', 5, section='challenge', stance='agree'),
               'p9': _p(4)}
    top = checklist.top_items(answers)
    assert [t['key'] for t in top] == ['p3', 'own-pray1', 'p9']
    assert top[0]['ref'] == 'Proverbs 5:15-19' and top[1]['title'] == 'We pray together every evening'


def test_the_summary_answers_carry_each_passage_reference():
    out = checklist.to_summary_answers({'p2': _p(5, comment='Provide'), 'own-pray1': _own('Pray', 4)})
    assert out[0]['ref'] == 'Exodus 21:10-11' and out[0]['comment'] == 'Provide'
    assert out[1]['title'] == 'Pray' and 'ref' not in out[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_checklist.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'checklist' from 'service.tools'`.

- [ ] **Step 3: Write the implementation**

Create `service/tools/checklist.py`:

```python
"""The marriage checklist, version 2: answers and the comparison (TEC-1845).

The passages are today's (ahavah-web src/app/marriage-checklist/content.ts),
with Exodus 21:10-11 for the husband only, as today (owner decision 9).
A stored answer has the shape of duotypes.MarriageChecklistAnswer, so the
existing summary email reads it unchanged. Comments and own items are free
text the player wrote: they show to the other player in the comparison
(export 6.6 and 6.8) and nowhere else, and every email escapes them.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import ValidationError

PASSAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    'p1': ('Genesis 2:18-24', ('husband', 'wife')),
    'p2': ('Exodus 21:10-11', ('husband',)),
    'p3': ('Proverbs 5:15-19', ('husband', 'wife')),
    'p4': ('1 Corinthians 7:2-5', ('husband', 'wife')),
    'p5': ('Ephesians 5:22-33', ('husband', 'wife')),
    'p6': ('Colossians 3:18-19', ('husband', 'wife')),
    'p7': ('1 Peter 3:1-7', ('husband', 'wife')),
    'p8': ('Malachi 2:14-16', ('husband', 'wife')),
    'p9': ('Hebrews 13:4', ('husband', 'wife')),
}
_OWN = re.compile(r'^own-[a-z0-9-]{6,40}$')
_ORDER = {k: i for i, k in enumerate(PASSAGES)}
OWN_PER_SECTION = 20
_SIDE = ('importance', 'stance', 'frequency', 'comment', 'examples', 'other_note')


def clean_checklist_answer(key: str, answer: Any, role: Optional[str]) -> dict:
    from duotypes import MarriageChecklistAnswer
    if key in PASSAGES:
        if role is None:
            raise ValueError('role_required')
        if role not in PASSAGES[key][1]:
            raise ValueError('bad_question')
    elif not _OWN.match(key):
        raise ValueError('bad_question')
    try:
        model = MarriageChecklistAnswer.model_validate(answer)
    except ValidationError:
        raise ValueError('bad_answer')
    data = model.model_dump(exclude_none=True)
    data['examples'] = [e.strip() for e in data.get('examples', []) if e and e.strip()]
    if not data['examples']:
        data.pop('examples')
    for field in ('comment', 'other_note', 'title'):
        if field in data:
            data[field] = data[field].strip()
            if not data[field]:
                data.pop(field)
    if key in PASSAGES:
        if data['section'] != 'biblical' or 'stance' not in data:
            raise ValueError('bad_answer')
        data.pop('title', None)
        data.pop('ref', None)
    else:
        if data['section'] == 'biblical' or not data.get('title'):
            raise ValueError('bad_answer')
        data.pop('ref', None)
    return data


def _side(a: dict) -> dict:
    return {k: a[k] for k in _SIDE if k in a}


def _own(answers: dict) -> list[dict]:
    items = [dict(key=k, **a) for k, a in answers.items() if k.startswith('own-')]
    items.sort(key=lambda i: (i['section'] != 'nice-to-have', -i['importance'], i['key']))
    return items


def compare(owner: dict, guest: dict) -> dict:
    shared = sorted((k for k in PASSAGES if k in owner and k in guest), key=_ORDER.get)
    agree_items, talk_items = [], []
    for k in shared:
        a, b = owner[k], guest[k]
        item = dict(key=k, ref=PASSAGES[k][0], owner=_side(a), guest=_side(b))
        if a.get('stance') != b.get('stance'):
            talk_items.append(dict(item, tag='stance'))
        elif abs(a['importance'] - b['importance']) >= 2:
            talk_items.append(dict(item, tag='importance'))
        else:
            agree_items.append(item)
    return dict(agree=len(agree_items), total=len(shared), agree_items=agree_items,
                talk_items=talk_items, own=dict(owner=_own(owner), guest=_own(guest)))


def top_items(answers: dict, n: int = 3) -> list[dict]:
    """The single's "What matters most to you": scripture and own
    nice-to-haves by importance; challenges are obstacles, not hopes."""
    items = []
    for k, a in answers.items():
        if k in PASSAGES:
            items.append(dict(key=k, ref=PASSAGES[k][0], importance=a['importance'],
                              order=_ORDER[k]))
        elif a.get('section') == 'nice-to-have':
            items.append(dict(key=k, title=a['title'], importance=a['importance'], order=100))
    items.sort(key=lambda i: (-i['importance'], i['order'], i['key']))
    return [{k: v for k, v in i.items() if k != 'order'} for i in items[:n]]


def to_summary_answers(answers: dict) -> list[dict]:
    """The answers as emails.marriage_checklist.checklist_results_html
    takes them: scripture with its reference, own items with their title."""
    out = []
    for k in sorted(answers, key=lambda k: (_ORDER.get(k, 100), k)):
        a = dict(answers[k])
        if k in PASSAGES:
            a['ref'] = PASSAGES[k][0]
        out.append(a)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_together_checklist.py -q -p no:warnings`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/checklist.py tests/test_together_checklist.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the checklist's stored answers, comparison and top items" -m "Refs: TEC-1845"
```

---

### Task 6: Sessions: start, answer, finish and read

**Files:**
- Create: `service/tools/sessions.py`
- Modify: `service/api/tools_routes.py` (append the session routes)
- Modify: `duotypes/__init__.py` (append the request models after `PutAnswer`)
- Test: `tests/test_tool_sessions.py` (create)

**Interfaces:**
- Consumes: `service.tools.live` (Task 2); `questions.clean_game_answer` (Task 3); `scoring.us_result` (Task 3); `results.archetype_for`, `results.guess_score`, `results.board_order` (Task 4); `checklist.clean_checklist_answer`, `checklist.compare`, `checklist.top_items` (Task 5); `service.leads.new_token`, `token_hash`; `service.person.attribution.clean_first_touch`.
- Produces:
  - `sessions.ToolError(reason, status=400)`; `sessions.SOURCE`, `MODES`, `TWO_PLAYER = ('us', 'couple')`, `WITH_INVITE = ('us', 'knows_me', 'couple')`; `sessions.clean_display(value) -> str`; `sessions.new_link_token() -> str`; `sessions.new_player(tx, session_pk, seat, **fields) -> str`; `sessions.players_of(tx, session_pk) -> list[dict]`.
  - `sessions.start(tx, *, kind, mode, member=None, utm=None) -> {'session_id': str (uuid), 'player_token': str (32)}`.
  - `sessions.player_for(tx, session_id, token, s=None) -> dict` with keys `session_id` (bigint), `session_uuid`, `kind`, `mode`, `source`, `deleted_at`, `claimed_at`, `completed_at`, `owner_display`, `owner_email`, `owner_person_id`, `owner_normalized_email`, `share_token`, `invite_token`, `player_id`, `seat`, `role`, `display`, `email`, `person_id`, `normalized_email`, `finished_at`, `removed_at`; raises `ToolError('not_found', 404)` or `ToolError('deleted', 410)`; refreshes `last_visit_at`.
  - `sessions.answers_of(tx, player_id) -> dict`, `sessions.save_answers(tx, player, answers: list[dict], role=None) -> int`, `sessions.finish(tx, player) -> {'view': dict, 'event': dict | None}` (event `{'notify_player_id': int}` when the second of two players finishes), `sessions.view(tx, session_pk, player_id) -> dict`.
  - The view: `{session_id, kind, mode, seat, role, state: 'playing' | 'waiting' | 'ready', claimed, member, share_token, invite_token, owner_display, guest_display, my_display, my_answers, result, board}`. Results: Me `{archetype, why}`; Us `{score, areas, align, talk, bars}`; knows-me friend `{right, total, place}`; couple `checklist.compare(...)`; single `{top}`. Board (knows-me): owner `[{player_id, display, right, total, removed}]`, friend `[{display, right, total, me}]`.
  - Routes: `POST /tools/sessions` (optional sign-in) `{kind, mode, first_touch?}` -> 201; `POST /tools/sessions/{id}/answers` `{role?, answers: [{question_key, answer}]}` (an `answer` of null removes it, which is "Skip this one") -> `{saved}`; `POST /tools/sessions/{id}/finish` -> the view; `GET /tools/sessions/{id}` -> the view. The player is the `X-Tool-Token` header, or a signed-in session for an address that saved the seat.
  - duotypes: `PostToolSession`, `ToolAnswerIn`, `PostToolAnswers`, `PostToolClaim`, `PostToolJoin`, `PostToolInviteEmail` (the last three used from Task 7).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_sessions.py`:

```python
"""Together sessions: start, answer, finish and read (TEC-1845).

Playing needs no account. The device's X-Tool-Token is the player; a
saved player may also come back signed in with that address. Nothing of
an Us game shows until both have answered, and neither player ever reads
the other's answers.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from database import api_tx
from service.leads import new_token

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _start(client, mode='us', kind='game', headers=None):
    r = client.post('/tools/sessions', json=dict(kind=kind, mode=mode), headers=headers or {})
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    _MADE.append(body['session_id'])
    return body['session_id'], body['player_token']


def _h(token):
    return {'X-Tool-Token': token}


def _answer(client, sid, token, answers: dict, **extra):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    return client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, **extra),
                       headers=_h(token))


def _finish(client, sid, token):
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _add_guest(sid, display='Rivka') -> str:
    token, hashed = new_token()
    with api_tx() as tx:
        tx.execute(
            """INSERT INTO tool_player (session_id, seat, token_hash, display)
               SELECT id, 'guest', %(h)s, %(d)s FROM tool_session WHERE uuid = %(u)s""",
            dict(h=hashed, d=display, u=sid))
    return token


def test_every_tool_route_is_dark_until_live(client, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOGETHER_LIVE_ENABLED', raising=False)
    r = client.post('/tools/sessions', json=dict(kind='game', mode='me'))
    assert (r.status_code, r.get_json()) == (404, {'error': 'not_found'})
    sid = str(uuid.uuid4())
    assert client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=[])).status_code == 404
    assert client.get(f'/tools/sessions/{sid}').status_code == 404


def test_a_visitor_starts_a_game_with_no_account(client):
    sid, token = _start(client)
    assert str(uuid.UUID(sid)) == sid and len(token) == 32
    with api_tx() as tx:
        s = tx.execute("""SELECT kind, mode, source, owner_person_id, claimed_at
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
        p = tx.execute("""SELECT seat, token_hash FROM tool_player
                           WHERE session_id = (SELECT id FROM tool_session WHERE uuid = %(u)s)""",
                       dict(u=sid)).fetchone()
    assert dict(s) == dict(kind='game', mode='us', source='tool:game-us', owner_person_id=None,
                           claimed_at=None)
    assert p['seat'] == 'owner' and p['token_hash'] != token


def test_a_bad_mode_is_refused(client):
    r = client.post('/tools/sessions', json=dict(kind='game', mode='couple'))
    assert (r.status_code, r.get_json()) == (400, {'error': 'bad_mode'})
    assert client.post('/tools/sessions', json=dict(kind='game', mode='dating')).status_code == 400


def test_answers_need_the_players_token(client):
    sid, _ = _start(client)
    assert client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=[])).status_code == 404
    assert _answer(client, sid, 'x' * 32, {'calendar': 'enoch'}).status_code == 404
    assert client.get('/tools/sessions/not-a-uuid', headers=_h('x' * 32)).status_code == 404


def test_an_answer_is_checked_saved_and_skipped(client):
    sid, token = _start(client)
    r = _answer(client, sid, token, {'calendar': 'enoch'})
    assert (r.status_code, r.get_json()) == (200, {'saved': 1})
    bad = _answer(client, sid, token, {'calendar': 'julian'})
    assert (bad.status_code, bad.get_json()) == (400, {'error': 'bad_answer'})
    assert _answer(client, sid, token, {'calendar': None}).status_code == 200
    assert client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()['my_answers'] == {}


def test_a_finished_player_cannot_change_answers(client):
    sid, token = _start(client, mode='me')
    _answer(client, sid, token, {'calendar': 'enoch'})
    assert _finish(client, sid, token).status_code == 200
    r = _answer(client, sid, token, {'calendar': 'other'})
    assert (r.status_code, r.get_json()) == (409, {'error': 'finished'})


def test_me_finishes_with_its_archetype(client):
    sid, token = _start(client, mode='me')
    _answer(client, sid, token, CASES['identical']['owner'])
    v = _finish(client, sid, token).get_json()
    assert v['state'] == 'ready'
    assert v['result'] == {'archetype': 'feast', 'why': ['feast', 'family']}
    assert v['share_token'] is None and v['claimed'] is False


def test_us_reveals_nothing_until_both_have_finished(client):
    case = CASES['order-matters']
    sid, owner = _start(client)
    _answer(client, sid, owner, case['owner'])
    v = _finish(client, sid, owner).get_json()
    assert (v['state'], v['result']) == ('waiting', None)
    guest = _add_guest(sid)
    g = client.get(f'/tools/sessions/{sid}', headers=_h(guest)).get_json()
    assert (g['seat'], g['state'], g['my_answers'], g['result']) == ('guest', 'playing', {}, None)
    _answer(client, sid, guest, case['guest'])
    g = _finish(client, sid, guest).get_json()
    o = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()
    for view in (g, o):
        assert view['state'] == 'ready'
        assert view['result']['score'] == 59
        assert view['result']['align'] == ['relocation', 'language', 'observance']
        assert (view['owner_display'], view['guest_display']) == (None, 'Rivka')
    assert o['my_answers'] == case['owner'] and g['my_answers'] == case['guest']
    assert 'wants-partner-willing' not in json.dumps(g), 'the guest must never read the owner answers'
    with api_tx() as tx:
        n = tx.execute("""SELECT count(*) AS n FROM tool_result
                           WHERE session_id = (SELECT id FROM tool_session WHERE uuid = %(u)s)""",
                       dict(u=sid)).fetchone()['n']
    assert n == 1


def test_a_member_who_starts_owns_the_session(client, make_person, sign_in):
    member = make_person(name='ToolMember')
    sid, token = _start(client, mode='me', headers=sign_in(member))
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
    assert owner == member['id']
    assert client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()['member'] is True


def _saved_by(sid, email):
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET owner_email = %(e)s, owner_normalized_email = %(e)s,
                             owner_display = 'Daniel', claimed_at = NOW()
                       WHERE uuid = %(u)s""", dict(e=email, u=sid))


def test_a_signed_in_player_can_reopen_with_their_email(client, tool_visitor):
    email, headers = tool_visitor()
    sid, _ = _start(client)
    _saved_by(sid, email)
    r = client.get(f'/tools/sessions/{sid}', headers=headers)
    assert r.status_code == 200 and r.get_json()['seat'] == 'owner'


def test_someone_elses_session_never_opens(client, tool_visitor):
    email, _ = tool_visitor()
    _, stranger = tool_visitor()
    sid, _ = _start(client)
    _saved_by(sid, email)
    assert client.get(f'/tools/sessions/{sid}', headers=stranger).status_code == 404


def test_a_display_name_is_cleaned_or_refused():
    from service.tools.sessions import ToolError, clean_display
    assert clean_display('  Rivka   Ann ') == 'Rivka Ann'
    assert clean_display('R.') == 'R.'
    for bad in ('', '   ', 'x' * 41, 'Ri\x07', '<b>R</b>', 'Ri\nka', None, 7):
        with pytest.raises(ToolError, match='bad_display'):
            clean_display(bad)
```

The `tool_visitor` addresses are `@ahavah-test.invalid`, which `normalize_email` leaves as written, so `_saved_by` can store the address as its own normalised form.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_sessions.py -q -p no:warnings`
Expected: most tests fail on `POST /tools/sessions` answering 404 or 405; `test_a_display_name_is_cleaned_or_refused` errors with `ModuleNotFoundError: No module named 'service.tools.sessions'`.

- [ ] **Step 3: Add the request models**

Append to `duotypes/__init__.py`, after `class PutAnswer`:

```python
class PostToolSession(BaseModel):
    """POST /tools/sessions (TEC-1845). `first_touch` is the device's
    first touch, typed Any as for /finish-onboarding: the server keeps only
    what service.person.attribution.clean_first_touch accepts."""
    kind: Literal['game', 'checklist']
    mode: Literal['me', 'us', 'knows_me', 'couple', 'single']
    first_touch: Optional[Any] = None


class ToolAnswerIn(BaseModel):
    question_key: str = Field(min_length=1, max_length=64)
    # Checked against the question by service.tools; null removes it.
    answer: Optional[Any] = None


class PostToolAnswers(BaseModel):
    role: Optional[Literal['husband', 'wife']] = None
    answers: List[ToolAnswerIn] = Field(default_factory=list, max_length=60)


class PostToolClaim(BaseModel):
    display: str = Field(min_length=1, max_length=80)


class PostToolJoin(BaseModel):
    display: str = Field(min_length=1, max_length=80)


class PostToolInviteEmail(BaseModel):
    email: EmailStr
    website: Optional[str] = None
    signup_stamp: Optional[str] = None
```

`display` allows 80 here so a long name reaches `clean_display`, which collapses spaces and answers `bad_display` for anything over 40.

- [ ] **Step 4: Write the session store**

Create `service/tools/sessions.py`:

```python
"""Together sessions: play, save, share and delete (TEC-1845).

docs/superpowers/specs/2026-10-13-couple-tools-design.md and
docs/superpowers/plans/2026-10-17-together-release-1.md.

A session is one game (me, us, knows_me) or one checklist (couple,
single). Each player holds a token the device keeps; only its sha256 is
stored (service.leads.new_token). A player who saved may also come back
with a signed-in session for the address they saved with. Answers are
read only by the players, through their token or that session: the view
carries the player's own answers and, once both have finished a couple
checklist, the comparison the two of them share. No admin route reads
them (service/tools/admin.py counts only). The share token opens the
public summary, which never carries an answer.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid as _uuid
from typing import Any, Optional

from antiabuse.antispam.signupemail import normalize_email
from service.leads import new_token, token_hash
from service.tools import checklist, questions, results, scoring

SOURCE = {'me': 'tool:game-me', 'us': 'tool:game-us', 'knows_me': 'tool:knows-me',
          'couple': 'tool:checklist', 'single': 'tool:checklist'}
MODES = {'game': ('me', 'us', 'knows_me'), 'checklist': ('couple', 'single')}
TWO_PLAYER = ('us', 'couple')
WITH_INVITE = ('us', 'knows_me', 'couple')
MAX_ANSWERS = 60
KNOWS_ME_MAX_FRIENDS = 200
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')


class ToolError(Exception):
    """A refusal the route answers as {'error': reason} with its status."""

    def __init__(self, reason: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def clean_display(value: object) -> str:
    """A first name or initials as a player chose to show it: spaces
    collapsed, 1 to 40 characters, no control characters and no angle
    brackets, since it reaches boards, share images and emails."""
    if not isinstance(value, str) or any(ord(c) < 32 or c in '<>' for c in value):
        raise ToolError('bad_display')
    text = ' '.join(value.split())
    if not 1 <= len(text) <= 40:
        raise ToolError('bad_display')
    return text


def new_link_token() -> str:
    """A share or invite token: 22 URL-safe characters, stored as it is so
    the owner can send it again."""
    return secrets.token_urlsafe(16)


_Q_START = """
    INSERT INTO tool_session (kind, mode, source, utm, owner_person_id, owner_email,
                              owner_normalized_email)
    VALUES (%(k)s, %(m)s, %(src)s, %(utm)s::jsonb, %(pid)s, %(e)s, %(ne)s)
    RETURNING id, uuid::text AS uuid
"""


def new_player(tx, session_pk: int, seat: str, **fields: Any) -> str:
    """Adds a player and returns its token. `fields` are tool_player
    columns named in code, never by a caller's input."""
    token, hashed = new_token()
    cols = dict(session_id=session_pk, seat=seat, token_hash=hashed, **fields)
    names = ', '.join(cols)
    values = ', '.join(f'%({c})s' for c in cols)
    tx.execute(f'INSERT INTO tool_player ({names}) VALUES ({values})', cols)
    return token


def start(tx, *, kind: str, mode: str, member=None, utm: Optional[dict] = None) -> dict:
    """A new session and its owner's token. `member` is the signed-in
    member's SessionInfo, or None for a visitor."""
    if mode not in MODES.get(kind, ()):
        raise ToolError('bad_mode')
    email = member.email if member is not None else None
    row = tx.execute(_Q_START, dict(
        k=kind, m=mode, src=SOURCE[mode], utm=json.dumps(utm) if utm else None,
        pid=member.person_id if member is not None else None, e=email,
        ne=normalize_email(email) if email else None)).fetchone()
    token = new_player(tx, row['id'], 'owner')
    return dict(session_id=row['uuid'], player_token=token)


_COLS = """s.id AS session_id, s.uuid::text AS session_uuid, s.kind, s.mode, s.source,
           s.deleted_at, s.claimed_at, s.completed_at, s.owner_display, s.owner_email,
           s.owner_person_id, s.owner_normalized_email, s.share_token, s.invite_token,
           p.id AS player_id, p.seat, p.role, p.display, p.email, p.person_id,
           p.normalized_email, p.finished_at, p.removed_at"""

_Q_BY_TOKEN = f"""
    SELECT {_COLS} FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.uuid = %(sid)s::uuid AND p.token_hash = %(h)s
"""

# A saved seat, for a signed-in session of the same address or account.
_Q_BY_ACCOUNT = f"""
    SELECT {_COLS} FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.uuid = %(sid)s::uuid
       AND ((p.seat = 'owner'
             AND ((%(pid)s::int IS NOT NULL AND s.owner_person_id = %(pid)s)
                  OR (s.claimed_at IS NOT NULL AND s.owner_normalized_email = %(ne)s)))
         OR (p.seat = 'guest' AND p.removed_at IS NULL
             AND ((%(pid)s::int IS NOT NULL AND p.person_id = %(pid)s)
                  OR p.normalized_email = %(ne)s)))
     ORDER BY (p.seat = 'owner') DESC, p.id
     LIMIT 1
"""


def _session_uuid(value: object) -> str:
    try:
        return str(_uuid.UUID(str(value)))
    except ValueError:
        raise ToolError('not_found', 404)


def player_for(tx, session_id: object, token: Optional[str], s=None) -> dict:
    sid = _session_uuid(session_id)
    row = None
    if isinstance(token, str) and _TOKEN_RE.match(token):
        row = tx.execute(_Q_BY_TOKEN, dict(sid=sid, h=token_hash(token))).fetchone()
    if row is None and s is not None and s.signed_in:
        row = tx.execute(_Q_BY_ACCOUNT, dict(sid=sid, pid=s.person_id,
                                             ne=normalize_email(s.email))).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    tx.execute('UPDATE tool_session SET last_visit_at = NOW() WHERE id = %(i)s',
               dict(i=row['session_id']))
    return dict(row)


_Q_ANSWERS = 'SELECT question_key, answer FROM tool_answer WHERE player_id = %(p)s'

_Q_UPSERT_ANSWER = """
    INSERT INTO tool_answer (session_id, player_id, question_key, answer)
    VALUES (%(s)s, %(p)s, %(k)s, %(a)s::jsonb)
    ON CONFLICT (player_id, question_key) DO UPDATE
       SET answer = EXCLUDED.answer, answered_at = NOW()
"""


def answers_of(tx, player_id: int) -> dict:
    return {r['question_key']: r['answer']
            for r in tx.execute(_Q_ANSWERS, dict(p=player_id)).fetchall()}


def save_answers(tx, player: dict, answers: list[dict], role: Optional[str] = None) -> int:
    """Saves or removes each answer; an answer of None removes it ("Skip
    this one"). Refused once the player has finished."""
    if player['finished_at'] is not None:
        raise ToolError('finished', 409)
    if player['kind'] == 'checklist' and role is not None:
        tx.execute('UPDATE tool_player SET role = %(r)s WHERE id = %(p)s',
                   dict(r=role, p=player['player_id']))
        player['role'] = role
    saved = 0
    for item in answers:
        key, raw = item['question_key'], item.get('answer')
        if raw is None:
            tx.execute('DELETE FROM tool_answer WHERE player_id = %(p)s AND question_key = %(k)s',
                       dict(p=player['player_id'], k=key))
            continue
        try:
            clean = (questions.clean_game_answer(key, raw) if player['kind'] == 'game'
                     else checklist.clean_checklist_answer(key, raw, player['role']))
        except ValueError as e:
            raise ToolError(str(e))
        tx.execute(_Q_UPSERT_ANSWER, dict(s=player['session_id'], p=player['player_id'], k=key,
                                          a=json.dumps(clean)))
        saved += 1
    n = tx.execute('SELECT count(*) AS n FROM tool_answer WHERE player_id = %(p)s',
                   dict(p=player['player_id'])).fetchone()['n']
    if n > MAX_ANSWERS:
        raise ToolError('too_many')
    return saved


_Q_PLAYERS = """
    SELECT id, seat, display, email, normalized_email, person_id, role, finished_at, removed_at
      FROM tool_player WHERE session_id = %(s)s ORDER BY id
"""

_Q_SAVE_RESULT = """
    INSERT INTO tool_result (session_id, player_id, score, breakdown, archetype)
    VALUES (%(s)s, %(p)s, %(score)s, %(b)s::jsonb, %(a)s)
    ON CONFLICT (session_id, COALESCE(player_id, 0)) DO UPDATE
       SET score = EXCLUDED.score, breakdown = EXCLUDED.breakdown,
           archetype = EXCLUDED.archetype, computed_at = NOW()
"""


def players_of(tx, session_pk: int) -> list[dict]:
    return [dict(r) for r in tx.execute(_Q_PLAYERS, dict(s=session_pk)).fetchall()]


def _save_result(tx, session_pk: int, player_id: Optional[int], score: Optional[int],
                 breakdown: dict, archetype: Optional[str]) -> None:
    tx.execute(_Q_SAVE_RESULT, dict(s=session_pk, p=player_id, score=score,
                                    b=json.dumps(breakdown), a=archetype))


def _complete(tx, session_pk: int) -> None:
    tx.execute('UPDATE tool_session SET completed_at = COALESCE(completed_at, NOW()) WHERE id = %(i)s',
               dict(i=session_pk))


def finish(tx, player: dict) -> dict:
    """The player has answered. Me and single get their result now; Us
    and couple when the second player finishes, computed once (the session
    row is locked, so two players finishing together cannot both compute
    it); a knows-me friend gets their guess score. Run it in a read
    committed transaction, so the second of two players finishing at once
    waits for the lock and then sees the first one's finish."""
    sid = player['session_id']
    tx.execute('SELECT id FROM tool_session WHERE id = %(i)s FOR UPDATE', dict(i=sid))
    if player['seat'] == 'guest' and player['removed_at'] is not None:
        raise ToolError('not_found', 404)
    tx.execute('UPDATE tool_player SET finished_at = COALESCE(finished_at, NOW()) WHERE id = %(p)s',
               dict(p=player['player_id']))
    mode = player['mode']
    event = None
    if mode == 'me':
        key, why = results.archetype_for(answers_of(tx, player['player_id']))
        _save_result(tx, sid, None, None, dict(why=why), key)
        _complete(tx, sid)
    elif mode == 'single':
        top = checklist.top_items(answers_of(tx, player['player_id']))
        _save_result(tx, sid, None, None, dict(top=len(top)), None)
        _complete(tx, sid)
    elif mode in TWO_PLAYER:
        players = [p for p in players_of(tx, sid) if p['removed_at'] is None]
        owner = next((p for p in players if p['seat'] == 'owner'), None)
        guest = next((p for p in players if p['seat'] == 'guest'), None)
        completed = tx.execute('SELECT completed_at FROM tool_session WHERE id = %(i)s',
                               dict(i=sid)).fetchone()['completed_at']
        if owner and guest and owner['finished_at'] and guest['finished_at'] and completed is None:
            oa, ga = answers_of(tx, owner['id']), answers_of(tx, guest['id'])
            if mode == 'us':
                r = scoring.us_result(oa, ga)
                _save_result(tx, sid, None, r['score'],
                             {k: r[k] for k in ('areas', 'align', 'talk', 'bars')}, None)
            else:
                c = checklist.compare(oa, ga)
                _save_result(tx, sid, None, None, dict(agree=c['agree'], total=c['total']), None)
            _complete(tx, sid)
            first = owner if owner['finished_at'] <= guest['finished_at'] else guest
            if first['id'] != player['player_id']:
                event = dict(notify_player_id=first['id'])
    elif mode == 'knows_me' and player['seat'] == 'guest':
        owner = next(p for p in players_of(tx, sid) if p['seat'] == 'owner')
        right, total = results.guess_score(answers_of(tx, owner['id']),
                                           answers_of(tx, player['player_id']))
        _save_result(tx, sid, player['player_id'], right, dict(right=right, total=total), None)
    return dict(view=view(tx, sid, player['player_id']), event=event)


_Q_SESSION = """
    SELECT id, uuid::text AS uuid, kind, mode, owner_display, owner_person_id, share_token,
           invite_token, claimed_at, completed_at
      FROM tool_session WHERE id = %(i)s
"""

_Q_RESULT = """
    SELECT score, breakdown, archetype FROM tool_result
     WHERE session_id = %(s)s AND COALESCE(player_id, 0) = COALESCE(%(p)s::bigint, 0)
"""

_Q_BOARD = """
    SELECT p.id AS player_id, p.display, p.finished_at, p.removed_at, r.score AS right,
           (r.breakdown->>'total')::int AS total
      FROM tool_player p JOIN tool_result r ON r.player_id = p.id
     WHERE p.session_id = %(s)s AND p.seat = 'guest'
"""


def _result_row(tx, session_pk: int, player_id: Optional[int]) -> Optional[dict]:
    row = tx.execute(_Q_RESULT, dict(s=session_pk, p=player_id)).fetchone()
    return dict(row) if row else None


def _board(tx, session_pk: int, *, for_owner: bool, me_id: int) -> list[dict]:
    rows = [dict(r) for r in tx.execute(_Q_BOARD, dict(s=session_pk)).fetchall()]
    ranked = results.board_order([r for r in rows if r['removed_at'] is None])
    if for_owner:
        removed = results.board_order([r for r in rows if r['removed_at'] is not None])
        return [dict(player_id=r['player_id'], display=r['display'], right=r['right'],
                     total=r['total'], removed=r['removed_at'] is not None)
                for r in ranked + removed]
    return [dict(display=r['display'], right=r['right'], total=r['total'],
                 me=r['player_id'] == me_id) for r in ranked]


def _result(tx, s: dict, me: dict, owner: dict, guest: Optional[dict], mine: dict):
    mode = s['mode']
    if mode == 'me':
        r = _result_row(tx, s['id'], None)
        return dict(archetype=r['archetype'], why=r['breakdown'].get('why', [])) if r else None
    if mode == 'single':
        return dict(top=checklist.top_items(mine))
    if mode == 'us':
        r = _result_row(tx, s['id'], None)
        return dict(score=r['score'], **r['breakdown']) if r else None
    if mode == 'couple':
        return checklist.compare(answers_of(tx, owner['id']), answers_of(tx, guest['id']))
    if me['seat'] == 'owner':
        return None
    r = _result_row(tx, s['id'], me['id'])
    if not r:
        return None
    board = _board(tx, s['id'], for_owner=False, me_id=me['id'])
    place = next((i + 1 for i, b in enumerate(board) if b['me']), None)
    return dict(right=r['breakdown']['right'], total=r['breakdown']['total'], place=place)


def view(tx, session_pk: int, player_id: int) -> dict:
    """What one player sees: their own answers, the state, the result once
    there is one and, in knows-me, the board. Never the other player's
    answers, except in the comparison two checklist players share."""
    s = dict(tx.execute(_Q_SESSION, dict(i=session_pk)).fetchone())
    players = players_of(tx, session_pk)
    me = next(p for p in players if p['id'] == player_id)
    owner = next(p for p in players if p['seat'] == 'owner')
    guest = next((p for p in players if p['seat'] == 'guest' and p['removed_at'] is None), None)
    mode = s['mode']
    mine = answers_of(tx, player_id)
    if me['finished_at'] is None:
        state = 'playing'
    elif mode in TWO_PLAYER:
        state = 'ready' if s['completed_at'] else 'waiting'
    else:
        state = 'ready'
    is_owner = me['seat'] == 'owner'
    claimed = s['claimed_at'] is not None if is_owner else me['email'] is not None
    out = dict(
        session_id=s['uuid'], kind=s['kind'], mode=mode, seat=me['seat'], role=me['role'],
        state=state, claimed=claimed,
        member=(s['owner_person_id'] is not None) if is_owner else (me['person_id'] is not None),
        share_token=s['share_token'] if claimed and s['claimed_at'] else None,
        invite_token=s['invite_token'] if is_owner else None,
        owner_display=s['owner_display'],
        guest_display=guest['display'] if mode in TWO_PLAYER and guest else None,
        my_display=s['owner_display'] if is_owner else me['display'],
        my_answers=mine, result=None, board=None,
    )
    if state == 'ready':
        out['result'] = _result(tx, s, me, owner, guest, mine)
    if mode == 'knows_me':
        out['board'] = _board(tx, session_pk, for_owner=is_owner, me_id=player_id)
    return out
```

- [ ] **Step 5: Add the routes**

Replace the import line `from service.api.decorators import get` at the top of `service/api/tools_routes.py` with:

```python
from typing import Optional

from flask import request

import duotypes as t
from database import api_tx
from service.api.decorators import adelete, aget, apost, get, limiter, post, validate
```

(`adelete` and `post` are used from Tasks 7 and 9.) Then append:

```python
_start_limit = limiter.shared_limit('30 per hour', scope='tools_start')
_answer_limit = limiter.shared_limit('600 per hour', scope='tools_answer')


def _token() -> Optional[str]:
    return request.headers.get('X-Tool-Token') or None


def _off():
    return dict(error='not_found'), 404


def _refused(e):
    return dict(error=e.reason), e.status


@apost('/tools/sessions', auth='optional', expected_onboarding_status=None,
       limiter=_start_limit)
@validate(t.PostToolSession)
def post_tool_session(req: t.PostToolSession, s: Optional[t.SessionInfo]):
    """Start a game or a checklist. No account needed; a signed-in
    member's session is theirs from the start."""
    from service.person.attribution import clean_first_touch
    from service.tools import live, sessions
    if not live():
        return _off()
    member = s if s is not None and s.person_id is not None else None
    try:
        with api_tx() as tx:
            out = sessions.start(tx, kind=req.kind, mode=req.mode, member=member,
                                 utm=clean_first_touch(req.first_touch))
    except sessions.ToolError as e:
        return _refused(e)
    return out, 201


@apost('/tools/sessions/<sid>/answers', auth='optional', expected_onboarding_status=None,
       limiter=_answer_limit)
@validate(t.PostToolAnswers)
def post_tool_answers(req: t.PostToolAnswers, s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            saved = sessions.save_answers(tx, player, [a.model_dump() for a in req.answers],
                                          role=req.role)
    except sessions.ToolError as e:
        return _refused(e)
    return dict(saved=saved)


@apost('/tools/sessions/<sid>/finish', auth='optional', expected_onboarding_status=None,
       limiter=_answer_limit)
def post_tool_finish(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        # Read committed: see sessions.finish.
        with api_tx('read committed') as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            out = sessions.finish(tx, player)
    except sessions.ToolError as e:
        return _refused(e)
    return out['view']


@aget('/tools/sessions/<sid>', auth='optional', expected_onboarding_status=None)
def get_tool_session(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.view(tx, player['session_id'], player['player_id'])
    except sessions.ToolError as e:
        return _refused(e)
```

The handlers return before leaving the `with` block, and a `ToolError` raised inside it rolls the transaction back as it leaves, so a refused request writes nothing.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_sessions.py tests/test_together_switches.py -q -p no:warnings`
Expected: all pass (12 new, the switch suite unchanged).

- [ ] **Step 7: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/sessions.py service/api/tools_routes.py duotypes/__init__.py tests/test_tool_sessions.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): start, answer, finish and read a game or checklist with a device token" -m "Refs: TEC-1845"
```

---

### Task 7: The second player: the invite link, joining and the board

**Files:**
- Modify: `service/tools/sessions.py` (append)
- Modify: `service/api/tools_routes.py` (append)
- Test: `tests/test_tool_invites.py` (create)

**Interfaces:**
- Consumes: `new_player`, `clean_display`, `players_of`, `view`, `ToolError`, `TWO_PLAYER`, `KNOWS_ME_MAX_FRIENDS`, `_TOKEN_RE` (Task 6); `PostToolJoin` (Task 6).
- Produces: `sessions.invite_info(tx, invite_token) -> {kind, mode, owner_display, state: 'open' | 'full' | 'not_ready'}` (404 unknown, 410 deleted); `sessions.join(tx, invite_token, *, display, s=None) -> {session_id, player_token}` (409 `full`, `not_ready`, `own_session`); `sessions.set_removed(tx, player, guest_id: int, removed: bool) -> view`; routes `GET /tools/i/{token}`, `POST /tools/i/{token}/players` `{display}` -> 201, `DELETE /tools/sessions/{id}/players/{player_id}`, `POST /tools/sessions/{id}/players/{player_id}/restore`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_invites.py`:

```python
"""Together's second player (TEC-1845).

An Us game and a couple checklist take one guest; the first keeps the
seat. Knows-me takes many friends, each giving only a display name, once
the player has answered. A friend sees their score and the board, never
the player's answers (owner decision 6). The player cannot join their own
game. A signed-in member joins with no email step.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _h(token):
    return {'X-Tool-Token': token}


def _play(client, sid, token, answers):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items), headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _open(client, mode='us', kind='game', owner_answers=None, finish=True, email=None):
    r = client.post('/tools/sessions', json=dict(kind=kind, mode=mode))
    sid, token = r.get_json()['session_id'], r.get_json()['player_token']
    _MADE.append(sid)
    if finish:
        _play(client, sid, token, owner_answers or {})
    invite = secrets.token_urlsafe(16)
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET invite_token = %(t)s, share_token = %(st)s,
                             owner_display = 'Daniel', claimed_at = NOW(),
                             owner_email = %(e)s, owner_normalized_email = %(e)s
                       WHERE uuid = %(u)s""",
                   dict(t=invite, st=secrets.token_urlsafe(16), e=email, u=sid))
    return sid, token, invite


def _join(client, invite, display='Rivka', headers=None):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display),
                       headers=headers or {})


def test_an_invite_link_says_who_invited_and_whether_it_is_open(client):
    _, _, invite = _open(client)
    assert client.get(f'/tools/i/{invite}').get_json() == {
        'kind': 'game', 'mode': 'us', 'owner_display': 'Daniel', 'state': 'open'}


def test_an_unknown_or_malformed_link_is_not_found(client):
    for token in ('x', secrets.token_urlsafe(16), 'a' * 200):
        assert client.get(f'/tools/i/{token}').status_code == 404


def test_a_deleted_game_says_so(client):
    sid, _, invite = _open(client)
    with api_tx() as tx:
        tx.execute('UPDATE tool_session SET deleted_at = NOW() WHERE uuid = %(u)s', dict(u=sid))
    r = client.get(f'/tools/i/{invite}')
    assert (r.status_code, r.get_json()) == (410, {'error': 'deleted'})
    assert _join(client, invite).status_code == 410


def test_a_guest_joins_with_a_name_and_plays(client):
    sid, _, invite = _open(client)
    r = _join(client, invite, display='  Rivka ')
    assert r.status_code == 201
    body = r.get_json()
    assert body['session_id'] == sid and len(body['player_token']) == 32
    v = client.get(f'/tools/sessions/{sid}', headers=_h(body['player_token'])).get_json()
    assert (v['seat'], v['my_display'], v['guest_display'], v['claimed']) == (
        'guest', 'Rivka', 'Rivka', False)


def test_a_second_guest_is_refused_in_a_two_player_mode(client):
    _, _, invite = _open(client)
    assert _join(client, invite).status_code == 201
    r = _join(client, invite, display='Leah')
    assert (r.status_code, r.get_json()) == (409, {'error': 'full'})
    assert client.get(f'/tools/i/{invite}').get_json()['state'] == 'full'


def test_the_owner_cannot_join_their_own_game(client, tool_visitor):
    email, headers = tool_visitor()
    _, _, invite = _open(client, email=email)
    r = _join(client, invite, headers=headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'own_session'})


def test_a_signed_in_member_joins_with_no_email_step(client, make_person, sign_in):
    member = make_person(name='Samuel')
    sid, _, invite = _open(client)
    token = _join(client, invite, display='Samuel', headers=sign_in(member)).get_json()['player_token']
    v = client.get(f'/tools/sessions/{sid}', headers=_h(token)).get_json()
    assert v['claimed'] is True and v['member'] is True


def test_friends_need_the_player_to_have_finished_and_never_see_their_answers(client):
    owner_answers = CASES['order-matters']['owner']
    _, _, early = _open(client, mode='knows_me', finish=False)
    r = _join(client, early, display='Hannah')
    assert (r.status_code, r.get_json()) == (409, {'error': 'not_ready'})
    sid, owner, invite = _open(client, mode='knows_me', owner_answers=owner_answers)
    hannah = _join(client, invite, display='Hannah').get_json()['player_token']
    josiah = _join(client, invite, display='Josiah').get_json()['player_token']
    _play(client, sid, hannah, owner_answers | {'country': 'BB'})
    _play(client, sid, josiah, owner_answers | {'country': 'BB', 'move': 'local-only'})
    h = client.get(f'/tools/sessions/{sid}', headers=_h(hannah)).get_json()
    assert h['result'] == {'right': 13, 'total': 14, 'place': 1}
    assert h['board'] == [dict(display='Hannah', right=13, total=14, me=True),
                          dict(display='Josiah', right=12, total=14, me=False)]
    assert '"JM"' not in json.dumps(h), 'a friend must never read the player answers'
    o = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()
    assert [(b['display'], b['removed']) for b in o['board']] == [('Hannah', False), ('Josiah', False)]


def test_the_owner_removes_and_restores_a_name(client):
    sid, owner, invite = _open(client, mode='knows_me', owner_answers={'calendar': 'enoch'})
    friend = _join(client, invite, display='Josiah').get_json()['player_token']
    _play(client, sid, friend, {'calendar': 'enoch'})
    gid = client.get(f'/tools/sessions/{sid}', headers=_h(owner)).get_json()['board'][0]['player_id']
    assert client.delete(f'/tools/sessions/{sid}/players/{gid}', headers=_h(friend)).status_code == 403
    o = client.delete(f'/tools/sessions/{sid}/players/{gid}', headers=_h(owner)).get_json()
    assert o['board'][0]['removed'] is True
    assert client.get(f'/tools/sessions/{sid}', headers=_h(friend)).get_json()['board'] == []
    o = client.post(f'/tools/sessions/{sid}/players/{gid}/restore', headers=_h(owner)).get_json()
    assert o['board'][0]['removed'] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_invites.py -q -p no:warnings`
Expected: `9 failed` (the `/tools/i/...` routes answer 404 or 405).

- [ ] **Step 3: Write the implementation**

Append to `service/tools/sessions.py`:

```python
_Q_BY_INVITE = """
    SELECT id, uuid::text AS uuid, kind, mode, owner_display, owner_person_id,
           owner_normalized_email, deleted_at
      FROM tool_session WHERE invite_token = %(t)s
"""


def _by_invite(tx, invite_token: object, *, lock: bool = False) -> dict:
    if not isinstance(invite_token, str) or not _TOKEN_RE.match(invite_token):
        raise ToolError('not_found', 404)
    row = tx.execute(_Q_BY_INVITE + (' FOR UPDATE' if lock else ''),
                     dict(t=invite_token)).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    return dict(row)


def _seat_state(tx, sess: dict) -> str:
    players = players_of(tx, sess['id'])
    owner = next(p for p in players if p['seat'] == 'owner')
    guests = [p for p in players if p['seat'] == 'guest' and p['removed_at'] is None]
    if sess['mode'] in TWO_PLAYER and guests:
        return 'full'
    if sess['mode'] == 'knows_me':
        if owner['finished_at'] is None:
            return 'not_ready'
        if len(guests) >= KNOWS_ME_MAX_FRIENDS:
            return 'full'
    return 'open'


def invite_info(tx, invite_token: object) -> dict:
    """What the second player's start shows. Already played is the web's
    to tell: the device that played keeps its token."""
    sess = _by_invite(tx, invite_token)
    return dict(kind=sess['kind'], mode=sess['mode'], owner_display=sess['owner_display'],
                state=_seat_state(tx, sess))


def _is_owner(sess: dict, s) -> bool:
    if s.person_id is not None and sess['owner_person_id'] == s.person_id:
        return True
    return sess['owner_normalized_email'] == normalize_email(s.email)


def join(tx, invite_token: object, *, display: object, s=None) -> dict:
    """A guest takes a seat. A signed-in guest (a member from the chat, or
    a visitor who confirmed an address before) is saved at once, with no
    email step, except in knows-me, where friends give only a name."""
    sess = _by_invite(tx, invite_token, lock=True)
    signed_in = s is not None and s.signed_in
    if signed_in and _is_owner(sess, s):
        raise ToolError('own_session', 409)
    state = _seat_state(tx, sess)
    if state != 'open':
        raise ToolError(state, 409)
    fields: dict[str, Any] = dict(display=clean_display(display))
    if signed_in and sess['mode'] != 'knows_me':
        fields.update(email=s.email, normalized_email=normalize_email(s.email),
                      person_id=s.person_id)
    token = new_player(tx, sess['id'], 'guest', **fields)
    tx.execute('UPDATE tool_session SET last_visit_at = NOW() WHERE id = %(i)s', dict(i=sess['id']))
    return dict(session_id=sess['uuid'], player_token=token)


def set_removed(tx, player: dict, guest_id: int, removed: bool) -> dict:
    """The player takes a name off their knows-me board, or puts it back
    ("Undo")."""
    if player['seat'] != 'owner' or player['mode'] != 'knows_me':
        raise ToolError('not_allowed', 403)
    n = tx.execute(
        """UPDATE tool_player SET removed_at = CASE WHEN %(r)s THEN NOW() END
            WHERE id = %(g)s AND session_id = %(s)s AND seat = 'guest'""",
        dict(r=removed, g=guest_id, s=player['session_id'])).rowcount
    if n == 0:
        raise ToolError('not_found', 404)
    return view(tx, player['session_id'], player['player_id'])
```

Append to `service/api/tools_routes.py`:

```python
_invite_read_limit = limiter.shared_limit('120 per hour', scope='tools_invite_read')
_join_limit = limiter.shared_limit('60 per hour', scope='tools_join')


@get('/tools/i/<invite>', limiter=_invite_read_limit)
def get_tool_invite(invite: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            return sessions.invite_info(tx, invite)
    except sessions.ToolError as e:
        return _refused(e)


@apost('/tools/i/<invite>/players', auth='optional', expected_onboarding_status=None,
       limiter=_join_limit)
@validate(t.PostToolJoin)
def post_tool_join(req: t.PostToolJoin, s: Optional[t.SessionInfo], invite: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            out = sessions.join(tx, invite, display=req.display, s=s)
    except sessions.ToolError as e:
        return _refused(e)
    return out, 201


def _board_change(s, sid: str, gid: int, removed: bool):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.set_removed(tx, player, gid, removed)
    except sessions.ToolError as e:
        return _refused(e)


@adelete('/tools/sessions/<sid>/players/<int:gid>', auth='optional',
         expected_onboarding_status=None)
def delete_tool_board_name(s: Optional[t.SessionInfo], sid: str, gid: int):
    return _board_change(s, sid, gid, True)


@apost('/tools/sessions/<sid>/players/<int:gid>/restore', auth='optional',
       expected_onboarding_status=None)
def post_tool_board_restore(s: Optional[t.SessionInfo], sid: str, gid: int):
    return _board_change(s, sid, gid, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_invites.py tests/test_tool_sessions.py -q -p no:warnings`
Expected: all pass (9 new, the session suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/sessions.py service/api/tools_routes.py tests/test_tool_invites.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the invite link, one guest or many friends, and the board" -m "Refs: TEC-1845"
```

---

### Task 8: Saving a result with the confirmed email, leads, and linking at sign-up

**Files:**
- Modify: `service/tools/sessions.py` (append `claim`, `link_tool_sessions_to_person`)
- Modify: `service/api/tools_routes.py` (append the claim route)
- Modify: `service/person/__init__.py` (finish-onboarding, after `link_leads_to_person(tx, row['person_id'])`)
- Test: `tests/test_tool_claim.py` (create)

**Interfaces:**
- Consumes: `player_for`, `view`, `clean_display`, `new_link_token`, `WITH_INVITE` (Task 6); `service.leads.record_lead`, `confirm_lead`, `tool_leads_enabled`; `PostToolClaim` (Task 6).
- Produces: `sessions.claim(tx, player, s, display) -> view`; `POST /tools/sessions/{id}/claim` `{display}` with a signed-in session (onboardee or member) and the player's token -> the view, now with `share_token` and, for Us, knows-me and couple, the owner's `invite_token`; 409 `claimed` when the seat was saved with another address; 403 `not_allowed` for a knows-me friend; `sessions.link_tool_sessions_to_person(tx, person_id) -> None`.

The web's save step runs `POST /request-otp` and `POST /check-otp` with the tool's `source` first (Task 20), which records the lead at `/check-otp` while the switch is on (growth foundations Task 4). Claiming records it again, an upsert, so a player who was already signed in is counted too.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_claim.py`:

```python
"""Saving a Together result (TEC-1845).

Spec: "Saving a result, comparing with someone and getting the share image
needs an email confirmed by a 6-digit code. This is the same one-time code
and onboardee session the checklist already uses." The claim reads the
address from that session, never from the request. A lead is written only
while AHAVAH_TOOL_LEADS_ENABLED is on; a member is never a lead.
"""
from __future__ import annotations

import secrets

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _start(client, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    _MADE.append(body['session_id'])
    return body['session_id'], body['player_token']


def _claim(client, sid, token, headers, display='Daniel'):
    return client.post(f'/tools/sessions/{sid}/claim', json=dict(display=display),
                       headers=_h(token, headers))


def test_saving_needs_a_signed_in_session(client):
    sid, token = _start(client)
    assert client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Daniel'),
                       headers=_h(token)).status_code == 400


def test_a_visitor_saves_with_their_confirmed_email(client, tool_visitor):
    email, headers = tool_visitor()
    sid, token = _start(client)
    v = _claim(client, sid, token, headers).get_json()
    assert v['claimed'] is True and len(v['share_token']) == 22 and len(v['invite_token']) == 22
    with api_tx() as tx:
        s = tx.execute("""SELECT owner_email, owner_display, claimed_at IS NOT NULL AS saved
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
    assert dict(s) == dict(owner_email=email, owner_display='Daniel', saved=True)


def test_me_gets_a_share_link_and_no_invite(client, tool_visitor):
    _, headers = tool_visitor()
    sid, token = _start(client, mode='me')
    v = _claim(client, sid, token, headers).get_json()
    assert v['share_token'] and v['invite_token'] is None


def test_saving_twice_is_the_same_save_and_another_address_is_refused(client, tool_visitor):
    _, headers = tool_visitor()
    _, other = tool_visitor()
    sid, token = _start(client)
    first = _claim(client, sid, token, headers).get_json()
    again = _claim(client, sid, token, headers, display='D.').get_json()
    assert (again['share_token'], again['invite_token'], again['my_display']) == (
        first['share_token'], first['invite_token'], 'D.')
    r = _claim(client, sid, token, other)
    assert (r.status_code, r.get_json()) == (409, {'error': 'claimed'})


def test_an_us_guest_saves_their_own_email_and_gets_the_share_link(client, tool_visitor):
    _, owner_headers = tool_visitor()
    _, guest_headers = tool_visitor()
    sid, owner = _start(client)
    invite = _claim(client, sid, owner, owner_headers).get_json()['invite_token']
    guest = client.post(f'/tools/i/{invite}/players', json=dict(display='Rivka')).get_json()['player_token']
    before = client.get(f'/tools/sessions/{sid}', headers=_h(guest)).get_json()
    assert (before['claimed'], before['share_token']) == (False, None)
    after = _claim(client, sid, guest, guest_headers, display='R.').get_json()
    assert after['claimed'] is True and after['share_token'] and after['my_display'] == 'R.'
    assert after['invite_token'] is None


def test_a_knows_me_friend_cannot_save(client, tool_visitor):
    _, owner_headers = tool_visitor()
    _, friend_headers = tool_visitor()
    sid, owner = _start(client, mode='knows_me')
    client.post(f'/tools/sessions/{sid}/finish', headers=_h(owner))
    invite = _claim(client, sid, owner, owner_headers).get_json()['invite_token']
    friend = client.post(f'/tools/i/{invite}/players', json=dict(display='Hannah')).get_json()['player_token']
    r = _claim(client, sid, friend, friend_headers)
    assert (r.status_code, r.get_json()) == (403, {'error': 'not_allowed'})


def _leads(email):
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            'SELECT source, confirmed_via FROM lead WHERE email = %(e)s', dict(e=email)).fetchall()]


def test_a_lead_is_written_only_while_tool_leads_are_on(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    email, headers = tool_visitor()
    sid, token = _start(client)
    _claim(client, sid, token, headers)
    assert _leads(email) == []
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    email2, headers2 = tool_visitor()
    sid2, token2 = _start(client, mode='couple', kind='checklist')
    _claim(client, sid2, token2, headers2)
    assert _leads(email2) == [dict(source='tool:checklist', confirmed_via='otp')]


def test_a_member_saves_to_their_account_and_is_never_a_lead(client, make_person, sign_in,
                                                             monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    member = make_person(name='Samuel', email=f'm-{secrets.token_hex(6)}@ahavah-test.invalid')
    sid, token = _start(client)
    v = _claim(client, sid, token, sign_in(member), display='Samuel').get_json()
    assert v['claimed'] is True and v['member'] is True
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                           dict(i=member['id'])).fetchone()['email']
    assert owner == member['id'] and _leads(email) == []


def test_finishing_sign_up_links_earlier_sessions(client, tool_visitor, finish_onboarding):
    email, headers = tool_visitor(f'join-{secrets.token_hex(6)}@ahavah-test.invalid')
    sid, token = _start(client)
    _claim(client, sid, token, headers)
    r, person_id = finish_onboarding({}, email=email)
    assert r.status_code == 200 and person_id
    with api_tx() as tx:
        owner = tx.execute('SELECT owner_person_id FROM tool_session WHERE uuid = %(u)s',
                           dict(u=sid)).fetchone()['owner_person_id']
    assert owner == person_id
```

The `finish_onboarding` fixture deletes the new person at teardown, and the session's foreign key cascades with it; the autouse cleanup then finds nothing to delete, which is fine.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_claim.py -q -p no:warnings`
Expected: `9 failed`, each on `POST /tools/sessions/{id}/claim` answering 404 (no such route yet).

- [ ] **Step 3: Write the implementation**

Append to `service/tools/sessions.py`:

```python
def claim(tx, player: dict, s, display: object) -> dict:
    """Save a seat with the address the signed-in session proved (a sign-in
    code or a member's account). The owner's save issues the share token
    and, for Us, knows-me and the couple checklist, the invite token. A
    guest in Us or the couple checklist may save too, to get the image; a
    knows-me friend gives only a name. A seat saved with one address is
    never moved to another."""
    from service.leads import confirm_lead, record_lead, tool_leads_enabled
    if s is None or not s.signed_in:
        raise ToolError('sign_in_required', 401)
    name = clean_display(display)
    ne = normalize_email(s.email)
    if player['seat'] == 'owner':
        saved_ne = player['owner_normalized_email'] if player['claimed_at'] else None
        if (saved_ne and saved_ne != ne) or (
                player['owner_person_id'] is not None and player['owner_person_id'] != s.person_id):
            raise ToolError('claimed', 409)
        tx.execute(
            """UPDATE tool_session
                  SET owner_email = %(e)s, owner_normalized_email = %(ne)s,
                      owner_person_id = COALESCE(owner_person_id, %(pid)s),
                      owner_display = %(d)s, claimed_at = COALESCE(claimed_at, NOW()),
                      share_token = COALESCE(share_token, %(st)s),
                      invite_token = CASE WHEN mode = ANY(%(inv)s)
                                          THEN COALESCE(invite_token, %(it)s) END
                WHERE id = %(i)s""",
            dict(e=s.email, ne=ne, pid=s.person_id, d=name, st=new_link_token(),
                 inv=list(WITH_INVITE), it=new_link_token(), i=player['session_id']))
    else:
        if player['mode'] == 'knows_me':
            raise ToolError('not_allowed', 403)
        if player['normalized_email'] and player['normalized_email'] != ne:
            raise ToolError('claimed', 409)
        tx.execute(
            """UPDATE tool_player
                  SET email = %(e)s, normalized_email = %(ne)s,
                      person_id = COALESCE(person_id, %(pid)s), display = %(d)s
                WHERE id = %(p)s""",
            dict(e=s.email, ne=ne, pid=s.person_id, d=name, p=player['player_id']))
    if s.person_id is None and tool_leads_enabled():
        lead_id = record_lead(tx, email=s.email, source=player['source'])
        if lead_id is not None:
            confirm_lead(tx, lead_id, 'otp')
    return view(tx, player['session_id'], player['player_id'])


_Q_LINK_OWNED = """
    UPDATE tool_session SET owner_person_id = %(pid)s
     WHERE owner_person_id IS NULL
       AND owner_normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
"""

_Q_LINK_JOINED = """
    UPDATE tool_player SET person_id = %(pid)s
     WHERE person_id IS NULL
       AND normalized_email = (SELECT normalized_email FROM person WHERE id = %(pid)s)
"""


def link_tool_sessions_to_person(tx, person_id: int) -> None:
    """At finish-onboarding: the sessions the new member saved before
    joining become theirs, so they go with the account. Rolled back to a
    savepoint and ignored on any failure: it can never undo the sign-up."""
    tx.execute('SAVEPOINT link_tool_sessions')
    try:
        tx.execute(_Q_LINK_OWNED, dict(pid=person_id))
        tx.execute(_Q_LINK_JOINED, dict(pid=person_id))
    except Exception:
        tx.execute('ROLLBACK TO SAVEPOINT link_tool_sessions')
    else:
        tx.execute('RELEASE SAVEPOINT link_tool_sessions')
```

Append to `service/api/tools_routes.py`:

```python
@apost('/tools/sessions/<sid>/claim', expected_onboarding_status=None)
@validate(t.PostToolClaim)
def post_tool_claim(req: t.PostToolClaim, s: t.SessionInfo, sid: str):
    """Save a result with the signed-in session's address. The web gets
    that session from /request-otp and /check-otp (with the tool's
    source); a member is already signed in."""
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            return sessions.claim(tx, player, s, req.display)
    except sessions.ToolError as e:
        return _refused(e)
```

In `service/person/__init__.py`, in finish-onboarding, replace:

```python
        from service.leads import link_leads_to_person
        link_leads_to_person(tx, row['person_id'])
```

with:

```python
        from service.leads import link_leads_to_person
        link_leads_to_person(tx, row['person_id'])
        # Together results saved before joining become the member's, so
        # they are deleted with the account (TEC-1845). Never fails the
        # sign-up.
        from service.tools.sessions import link_tool_sessions_to_person
        link_tool_sessions_to_person(tx, row['person_id'])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_claim.py tests/test_lead_signup.py tests/test_onboarding_attribution.py -q -p no:warnings`
Expected: all pass (9 new, the two sign-up suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/sessions.py service/api/tools_routes.py service/person/__init__.py tests/test_tool_claim.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): save a result with the confirmed email, lead only while switched on, linked at sign-up" -m "Refs: TEC-1845"
```

---

### Task 9: The public summary, share openings and deleting

**Files:**
- Modify: `service/tools/sessions.py` (append)
- Modify: `service/api/tools_routes.py` (append)
- Test: `tests/test_tool_public.py` (create)

**Interfaces:**
- Consumes: `players_of`, `_result_row`, `TWO_PLAYER`, `_TOKEN_RE` (Task 6).
- Produces: `sessions.public_summary(tx, share_token) -> {kind, mode, names: list[str], state: 'ready' | 'waiting', score?, archetype?, agree?, total?}` (404, 410 `deleted`); `sessions.count_open(tx, share_token) -> None`; `sessions.delete_session(tx, player) -> None`; routes `GET /tools/r/{token}` (`Cache-Control: no-store`), `POST /tools/r/{token}/open` -> 204, `DELETE /tools/sessions/{id}` -> 204. The web's `fetchPublicSummary` and the share images read the first.

What each mode's summary carries, and never more: Me, the owner's name and the archetype key; Us, both names and, once both have answered, the score; knows-me, the owner's name only (never a friend, owner decision 7); couple, both names and, once both have finished, the agreement counts; single, the owner's name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_public.py`:

```python
"""Together's public summary and deleting (TEC-1845).

Spec: "GET /tools/r/{share_token}: public summary for the result page and
image; no answers." "No answers are ever on public cards." "Either person
can delete the shared comparison." A deleted result keeps only its tokens,
so every link to it says it was deleted.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')

CASES = {c['name']: c for c in json.loads(
    (Path(__file__).resolve().parent / 'fixtures' / 'together_scoring_cases.json')
    .read_text(encoding='utf-8'))['cases']}
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


def _h(token):
    return {'X-Tool-Token': token}


def _play(client, sid, token, answers, role=None):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, role=role),
                headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token)).get_json()


def _saved(client, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    share, invite = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    with api_tx() as tx:
        tx.execute("""UPDATE tool_session SET share_token = %(s)s, invite_token = %(i)s,
                             owner_display = 'Daniel', claimed_at = NOW()
                       WHERE uuid = %(u)s""", dict(s=share, i=invite, u=sid))
    return sid, token, share, invite


def _guest(client, invite, display='Rivka'):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display)).get_json()['player_token']


def test_the_public_summary_never_carries_an_answer(client):
    case = CASES['order-matters']
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, case['owner'])
    _play(client, sid, _guest(client, invite), case['guest'])
    body = client.get(f'/tools/r/{share}').get_json()
    assert body == {'kind': 'game', 'mode': 'us', 'names': ['Daniel', 'Rivka'], 'state': 'ready',
                    'score': 59}
    text = json.dumps(body)
    for value in ('enoch', 'JM', 'wants-partner-willing', 'relocation', 'align'):
        assert value not in text


def test_us_shows_no_score_until_both_have_finished(client):
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, {'calendar': 'enoch'})
    _guest(client, invite)
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'game', 'mode': 'us', 'names': ['Daniel', 'Rivka'], 'state': 'waiting'}


def test_me_shows_the_archetype_and_one_name(client):
    sid, owner, share, _ = _saved(client, mode='me')
    _play(client, sid, owner, CASES['identical']['owner'])
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'game', 'mode': 'me', 'names': ['Daniel'], 'state': 'ready', 'archetype': 'feast'}


def test_knows_me_shows_only_the_player_never_a_friend(client):
    sid, owner, share, invite = _saved(client, mode='knows_me')
    _play(client, sid, owner, {'calendar': 'enoch'})
    _play(client, sid, _guest(client, invite, 'Hannah'), {'calendar': 'enoch'})
    body = client.get(f'/tools/r/{share}').get_json()
    assert body == {'kind': 'game', 'mode': 'knows_me', 'names': ['Daniel'], 'state': 'ready'}


def test_a_checklist_couple_shows_agreement_counts(client):
    sid, owner, share, invite = _saved(client, mode='couple', kind='checklist')
    item = dict(section='biblical', importance=4, stance='agree')
    _play(client, sid, owner, {'p1': item, 'p3': item}, role='husband')
    _play(client, sid, _guest(client, invite), {'p1': item, 'p3': dict(item, stance='other')},
          role='wife')
    assert client.get(f'/tools/r/{share}').get_json() == {
        'kind': 'checklist', 'mode': 'couple', 'names': ['Daniel', 'Rivka'], 'state': 'ready',
        'agree': 1, 'total': 2}


def test_unknown_malformed_and_deleted_links(client):
    assert client.get('/tools/r/x').status_code == 404
    assert client.get(f'/tools/r/{secrets.token_urlsafe(16)}').status_code == 404
    sid, owner, share, _ = _saved(client, mode='me')
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(owner)).status_code == 204
    r = client.get(f'/tools/r/{share}')
    assert (r.status_code, r.get_json(), r.headers['Cache-Control']) == (
        410, {'error': 'deleted'}, 'no-store')


def test_opening_a_share_link_is_counted(client):
    _, _, share, _ = _saved(client, mode='me')
    assert client.post(f'/tools/r/{share}/open').status_code == 204
    client.post(f'/tools/r/{share}/open')
    with api_tx() as tx:
        n = tx.execute('SELECT share_opens FROM tool_session WHERE share_token = %(s)s',
                       dict(s=share)).fetchone()['share_opens']
    assert n == 2


def test_deleting_leaves_only_a_tombstone(client):
    sid, owner, share, invite = _saved(client)
    _play(client, sid, owner, {'calendar': 'enoch'})
    guest = _guest(client, invite)
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(owner)).status_code == 204
    with api_tx() as tx:
        s = tx.execute("""SELECT id, owner_email, owner_display, deleted_at IS NOT NULL AS gone
                            FROM tool_session WHERE uuid = %(u)s""", dict(u=sid)).fetchone()
        left = [tx.execute(f'SELECT count(*) AS n FROM {t} WHERE session_id = %(s)s',
                           dict(s=s['id'])).fetchone()['n'] for t in ('tool_answer', 'tool_result')]
        names = tx.execute("""SELECT count(*) AS n FROM tool_player
                               WHERE session_id = %(s)s AND (display IS NOT NULL OR email IS NOT NULL)""",
                           dict(s=s['id'])).fetchone()['n']
    assert (s['owner_email'], s['owner_display'], s['gone'], left, names) == (None, None, True, [0, 0], 0)
    for r in (client.get(f'/tools/sessions/{sid}', headers=_h(guest)), client.get(f'/tools/r/{share}'),
              client.get(f'/tools/i/{invite}')):
        assert (r.status_code, r.get_json()) == (410, {'error': 'deleted'})


def test_either_player_deletes_a_two_player_result_but_a_friend_cannot(client):
    sid, _, _, invite = _saved(client)
    guest = _guest(client, invite)
    assert client.delete(f'/tools/sessions/{sid}', headers=_h(guest)).status_code == 204
    sid2, owner2, _, invite2 = _saved(client, mode='knows_me')
    _play(client, sid2, owner2, {'calendar': 'enoch'})
    friend = _guest(client, invite2, 'Hannah')
    r = client.delete(f'/tools/sessions/{sid2}', headers=_h(friend))
    assert (r.status_code, r.get_json()) == (403, {'error': 'not_allowed'})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_public.py -q -p no:warnings`
Expected: `9 failed` (`/tools/r/...` and `DELETE /tools/sessions/...` answer 404 or 405).

- [ ] **Step 3: Write the implementation**

Append to `service/tools/sessions.py`:

```python
_Q_BY_SHARE = """
    SELECT id, kind, mode, owner_display, completed_at, deleted_at
      FROM tool_session WHERE share_token = %(t)s
"""


def public_summary(tx, share_token: object) -> dict:
    """What a shared link and its image may show: names and the headline
    number, never an answer, an area or another player's score."""
    if not isinstance(share_token, str) or not _TOKEN_RE.match(share_token):
        raise ToolError('not_found', 404)
    row = tx.execute(_Q_BY_SHARE, dict(t=share_token)).fetchone()
    if row is None:
        raise ToolError('not_found', 404)
    if row['deleted_at'] is not None:
        raise ToolError('deleted', 410)
    mode = row['mode']
    players = players_of(tx, row['id'])
    owner = next(p for p in players if p['seat'] == 'owner')
    names = [row['owner_display']] if row['owner_display'] else []
    if mode in TWO_PLAYER:
        guest = next((p for p in players if p['seat'] == 'guest' and p['removed_at'] is None), None)
        if guest and guest['display']:
            names.append(guest['display'])
        ready = row['completed_at'] is not None
    else:
        ready = owner['finished_at'] is not None
    out: dict[str, Any] = dict(kind=row['kind'], mode=mode, names=names,
                               state='ready' if ready else 'waiting')
    if ready and mode == 'me':
        out['archetype'] = _result_row(tx, row['id'], None)['archetype']
    elif ready and mode == 'us':
        out['score'] = _result_row(tx, row['id'], None)['score']
    elif ready and mode == 'couple':
        b = _result_row(tx, row['id'], None)['breakdown']
        out.update(agree=b['agree'], total=b['total'])
    return out


def count_open(tx, share_token: object) -> None:
    """A share link opened in a browser (Admin > Growth counts them)."""
    if isinstance(share_token, str) and _TOKEN_RE.match(share_token):
        tx.execute("""UPDATE tool_session SET share_opens = share_opens + 1
                       WHERE share_token = %(t)s AND deleted_at IS NULL""", dict(t=share_token))


def delete_session(tx, player: dict) -> None:
    """Delete a result for everyone: its answers, results, names and
    addresses go now. The row and its tokens stay as a tombstone, so every
    link says it was deleted, until the sweep removes it 30 days later
    (service/tools/retention.py). The owner may delete; so may the guest
    of an Us game or a couple checklist, which they share. A knows-me
    friend may not."""
    if player['seat'] == 'guest' and player['mode'] not in TWO_PLAYER:
        raise ToolError('not_allowed', 403)
    sid = player['session_id']
    tx.execute('DELETE FROM tool_answer WHERE session_id = %(s)s', dict(s=sid))
    tx.execute('DELETE FROM tool_result WHERE session_id = %(s)s', dict(s=sid))
    tx.execute("""UPDATE tool_player SET display = NULL, email = NULL, normalized_email = NULL,
                         person_id = NULL, role = NULL
                   WHERE session_id = %(s)s""", dict(s=sid))
    tx.execute("""UPDATE tool_session SET deleted_at = NOW(), owner_email = NULL,
                         owner_normalized_email = NULL, owner_display = NULL,
                         owner_person_id = NULL, utm = NULL
                   WHERE id = %(s)s""", dict(s=sid))
```

Append to `service/api/tools_routes.py`:

```python
_share_read_limit = limiter.shared_limit('300 per hour', scope='tools_share_read')
_share_open_limit = limiter.shared_limit('60 per hour', scope='tools_share_open')


@get('/tools/r/<share>', limiter=_share_read_limit)
def get_tool_public(share: str):
    """The public summary a shared link and its images read. No answers."""
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx('read committed') as tx:
            return sessions.public_summary(tx, share), 200, {'Cache-Control': 'no-store'}
    except sessions.ToolError as e:
        return dict(error=e.reason), e.status, {'Cache-Control': 'no-store'}


@post('/tools/r/<share>/open', limiter=_share_open_limit)
def post_tool_share_open(share: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    with api_tx() as tx:
        sessions.count_open(tx, share)
    return '', 204


@adelete('/tools/sessions/<sid>', auth='optional', expected_onboarding_status=None)
def delete_tool_session(s: Optional[t.SessionInfo], sid: str):
    from service.tools import live, sessions
    if not live():
        return _off()
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            sessions.delete_session(tx, player)
    except sessions.ToolError as e:
        return _refused(e)
    return '', 204
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_public.py tests/test_tool_invites.py tests/test_tool_sessions.py -q -p no:warnings`
Expected: all pass (9 new, the earlier suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/sessions.py service/api/tools_routes.py tests/test_tool_public.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): a public summary with no answers, share openings counted, and deleting for both players" -m "Refs: TEC-1845"
```

---

### Task 10: The emails: answered, comparison ready, the checklist summary and the invite template

**Files:**
- Create: `service/tools/mail.py`
- Modify: `service/tools/sessions.py` (`finish` and `claim` call the mail)
- Modify: `emails/marriage_checklist.py` (`checklist_results_html` gains `stored`)
- Modify: `service/person/__init__.py` (`post_marriage_checklist_send` docstring), `service/api/__init__.py` (the `/marriage-checklist/send` route docstring), `duotypes/__init__.py` (`MarriageChecklistAnswer` docstring)
- Test: `tests/test_tool_mail.py` (create)

**Interfaces:**
- Consumes: `service.tools.switch_on` (Task 2); `checklist.to_summary_answers` (Task 5); `sessions.answers_of`, `finish`, `claim` (Tasks 6, 8); `service.campaigns.held.queue`, `held.footer`, `held.para`, `held.list_unsubscribe`; `service.campaigns.outbox.enqueue_for_lead`; `service.campaigns.campaign_unsubscribed`; `emails.base.render`, `button`, `is_suppressed_send`; `service.leads.tool_leads_enabled`.
- Produces: `mail.CAMPAIGN_ANSWERED = 'together_answered'`, `CAMPAIGN_READY = 'together_ready'`, `CAMPAIGN_SUMMARY = 'together_summary'`, `FROM_ADDR`; `mail.result_url(kind, session_uuid)`, `mail.invite_url(invite_token)`; `mail.answered_subject(name)`, `mail.answered_html(name, cta, unsubscribe_url)`; `mail.invite_subject(kind, name)`, `mail.invite_html(kind, name, cta)`, `mail.GAME_INVITE_LINE`, `mail.CHECKLIST_INVITE_LINE`; `mail.queue_answered(tx, session_pk, notify_player_id) -> int | None`; `mail.queue_summary(tx, session_pk, player_id) -> int | None`; `mail.after_finish(tx, player, event)`; `mail.preview_answered(to)`, `preview_ready(to)`, `preview_invite_game(to)`, `preview_invite_checklist(to)`, `preview_summary(to)` (each `(subject, html)`); `emails.marriage_checklist.checklist_results_html(role, answers, stored=False)` and `STORED_LINE`.

The answered and ready emails share one template, as the export says ("Same template as the checklist's comparison email, 6.12"): heading "{name} has answered. See how you fit.", button "See your comparison", footer "You get this because you invited {name} from ahavah.app/together." The invite email is not drawn in the export; its strings are taken from the second player's start screens (4.5, 6.4) and listed under "Spec conflicts", item 5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_mail.py`:

```python
"""Together's emails (TEC-1845).

Owner decision 5: one email through the outbox to the first player when
the second has finished, proofed first. Owner decision 12: the checklist
summary stays, now sent to each player when they finish, with the
stored-answers line, plus "your comparison is ready". Each is behind its
own switch and needs together_live. Nothing here ever breaks a finish.
"""
from __future__ import annotations

import secrets

import pytest

from database import api_tx
from emails.marriage_checklist import STORED_LINE, checklist_results_html
from service.tools import mail

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute("DELETE FROM email_outbox WHERE campaign_id LIKE %(c)s", dict(c=f'{sid}%'))
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


@pytest.fixture
def switches(monkeypatch):
    for env in ('AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED', 'AHAVAH_TOGETHER_READY_EMAIL_ENABLED',
                'AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED'):
        monkeypatch.setenv(env, '1')


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _mailable(make_person, name):
    return make_person(name=name, email=f'{name.lower()}-{secrets.token_hex(5)}@ahavah-test.invalid')


def _start(client, headers, mode='us', kind='game', display='Daniel'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode), headers=headers).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    v = client.post(f'/tools/sessions/{sid}/claim', json=dict(display=display),
                    headers=_h(token, headers)).get_json()
    return sid, token, v['invite_token']


def _play(client, sid, token, answers, role=None):
    items = [dict(question_key=k, answer=v) for k, v in answers.items()]
    client.post(f'/tools/sessions/{sid}/answers', json=dict(answers=items, role=role),
                headers=_h(token))
    return client.post(f'/tools/sessions/{sid}/finish', headers=_h(token))


def _join(client, invite, display='Rivka'):
    return client.post(f'/tools/i/{invite}/players', json=dict(display=display)).get_json()['player_token']


def _rows(sid):
    with api_tx() as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign, campaign_id, person_id, lead_id, payload FROM email_outbox
                WHERE campaign_id LIKE %(c)s ORDER BY id""", dict(c=f'{sid}%')).fetchall()]


def test_the_answered_email_goes_to_whoever_finished_first(client, make_person, sign_in, switches):
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    guest = _join(client, invite)
    assert _play(client, sid, guest, {'calendar': 'enoch'}).status_code == 200
    rows = [r for r in _rows(sid) if r['campaign'] == mail.CAMPAIGN_ANSWERED]
    assert len(rows) == 1 and rows[0]['person_id'] == owner['id'] and rows[0]['campaign_id'] == sid
    assert rows[0]['payload']['subject'] == 'Rivka has answered. See how you fit.'
    assert f'/together/game?session={sid}' in rows[0]['payload']['html']


def test_a_visitor_owner_is_mailed_as_a_lead_only_while_tool_leads_are_on(client, tool_visitor,
                                                                         switches, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOOL_LEADS_ENABLED', raising=False)
    _, headers = tool_visitor()
    sid, token, invite = _start(client, headers)
    _play(client, sid, token, {'calendar': 'enoch'})
    _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert _rows(sid) == []
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    _, headers2 = tool_visitor()
    sid2, token2, invite2 = _start(client, headers2)
    _play(client, sid2, token2, {'calendar': 'enoch'})
    _play(client, sid2, _join(client, invite2), {'calendar': 'enoch'})
    rows = _rows(sid2)
    assert len(rows) == 1 and rows[0]['lead_id'] is not None and rows[0]['person_id'] is None


def test_nothing_is_queued_while_its_switch_is_off(client, make_person, sign_in):
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert _rows(sid) == []


def test_the_checklist_uses_the_ready_switch_and_link(client, make_person, sign_in, monkeypatch):
    monkeypatch.setenv('AHAVAH_TOGETHER_READY_EMAIL_ENABLED', '1')
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner), mode='couple', kind='checklist')
    item = dict(section='biblical', importance=4, stance='agree')
    _play(client, sid, token, {'p1': item}, role='husband')
    _play(client, sid, _join(client, invite), {'p1': item}, role='wife')
    rows = _rows(sid)
    assert [r['campaign'] for r in rows] == [mail.CAMPAIGN_READY]
    assert f'/marriage-checklist?session={sid}' in rows[0]['payload']['html']


def test_a_checklist_player_gets_their_summary_with_the_stored_wording(client, make_person, sign_in,
                                                                        switches):
    owner = _mailable(make_person, 'Daniel')
    sid, token, _ = _start(client, sign_in(owner), mode='single', kind='checklist')
    _play(client, sid, token, {'p1': dict(section='biblical', importance=5, stance='agree')},
          role='husband')
    rows = [r for r in _rows(sid) if r['campaign'] == mail.CAMPAIGN_SUMMARY]
    assert len(rows) == 1 and rows[0]['person_id'] == owner['id']
    html = rows[0]['payload']['html']
    assert STORED_LINE in html and 'never stored' not in html and 'Genesis 2:18-24' in html
    assert 'We sent the same note to you and your spouse' not in html


def test_a_visitor_who_saves_after_finishing_gets_their_summary(client, tool_visitor, switches,
                                                                 monkeypatch):
    monkeypatch.setenv('AHAVAH_TOOL_LEADS_ENABLED', '1')
    _, headers = tool_visitor()
    body = client.post('/tools/sessions', json=dict(kind='checklist', mode='single')).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    _play(client, sid, token, {'p1': dict(section='biblical', importance=5, stance='agree')},
          role='wife')
    assert _rows(sid) == []
    client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Rivka'), headers=_h(token, headers))
    rows = _rows(sid)
    assert [r['campaign'] for r in rows] == [mail.CAMPAIGN_SUMMARY] and rows[0]['lead_id']


def test_the_first_checklist_summary_is_unchanged():
    html = checklist_results_html('wife', [dict(section='biblical', ref='Hebrews 13:4',
                                                importance=5, stance='agree')])
    assert 'We never stored your answers' in html
    assert 'We sent the same note to you and your spouse' in html


def test_names_are_escaped_in_every_email():
    html = mail.answered_html('R&D <x>', 'https://ahavah.app/together/game', 'https://ahavah.app/u/t')
    assert 'R&amp;D &lt;x&gt; has answered. See how you fit.' in html and '<x>' not in html
    for kind in ('game', 'checklist'):
        html = mail.invite_html(kind, 'R&D', 'https://ahavah.app/tools/i/t')
        assert 'R&amp;D' in html and 'R&D' not in html.replace('R&amp;D', '')
    assert mail.invite_subject('game', 'Rivka') == 'Rivka wants to see how well you fit'
    assert mail.invite_subject('checklist', 'Rivka') == 'Rivka invited you to the Ahavah marriage checklist'


def test_a_failure_to_queue_never_breaks_finishing(client, make_person, sign_in, switches,
                                                    monkeypatch):
    monkeypatch.setattr(mail, '_recipient', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom')))
    owner = _mailable(make_person, 'Daniel')
    sid, token, invite = _start(client, sign_in(owner))
    _play(client, sid, token, {'calendar': 'enoch'})
    r = _play(client, sid, _join(client, invite), {'calendar': 'enoch'})
    assert r.status_code == 200 and r.get_json()['state'] == 'ready'
    assert _rows(sid) == []


def test_the_api_says_where_the_checklist_v2_stores_answers():
    import inspect

    from service import person
    doc = inspect.getdoc(person.post_marriage_checklist_send)
    assert 'service/tools' in doc and 'never persisted' not in doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_mail.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'STORED_LINE' from 'emails.marriage_checklist'`.

- [ ] **Step 3: Give the checklist summary its stored variant**

In `emails/marriage_checklist.py`, add after `SUBJECT = "Your marriage checklist summary"`:

```python
# The checklist v2 keeps answers behind a private link (TEC-1845, owner
# decision 10). The export's wording, 6.1.
STORED_LINE = ("We keep your answers behind a private link so you can come back to them. "
               "Only you and the person you invite can see them. Either of you can delete them "
               "at any time.")
```

Change the signature `def checklist_results_html(role: str | None, answers: list[dict]) -> str:` to:

```python
def checklist_results_html(role: str | None, answers: list[dict], stored: bool = False) -> str:
    """The summary. `stored` is the checklist v2's: each player answers on
    their own and gets their own summary, and the answers are kept, so the
    lede drops "sent to you both" and the footer says where they are kept.
    The first checklist (POST /marriage-checklist/send) sends stored=False,
    word for word as before."""
```

In the same function, after `role_part = ...`, add:

```python
    lede = (f"Here is the summary you completed{role_part}." if stored else
            f"Here is the summary you completed{role_part}. We sent the same note to you and "
            "your spouse, so you can read it side by side and talk it through together.")
```

and in `body_html` replace:

```python
<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:15px;line-height:1.6;color:{INK_SOFT};">Here is the summary you completed{role_part}. We sent the same note to you and your spouse, so you can read it side by side and talk it through together.</p>
```

with:

```python
<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:15px;line-height:1.6;color:{INK_SOFT};">{lede}</p>
```

Replace the `footer_html = (...)` assignment and the `return render(...)` call with:

```python
    kept = (f"{STORED_LINE}<br/>" if stored else
            "We never stored your answers. This summary was composed when you sent "
            "it, then your responses were discarded.<br/>")
    footer_html = (
        kept
        + "Reply to this email to reach a real person. "
        f'<a href="{SITE}" style="color:{INDIGO};font-weight:600;text-decoration:none;">Ahavah</a>, made for Torah-observant believers.'
    )

    return render(
        title=SUBJECT,
        preheader=("The summary you completed." if stored else
                   "The summary you completed, sent to you both. We never stored your answers."),
        body_html=body_html,
        footer_html=footer_html,
    )
```

- [ ] **Step 4: Write the mail module**

Create `service/tools/mail.py`:

```python
"""Together's emails (TEC-1845).

  answered  "{name} has answered. See how you fit." to whoever finished an
            Us game first (together_answered_email); the same template for
            a couple checklist (together_ready_email). Export 4.10 and
            6.12, which share one template.
  summary   the checklist summary (emails/marriage_checklist.py, stored
            wording) to a checklist player once they have finished and
            saved (together_summary_email; owner decision 12).
  invite    the link the player who saved sends to the other person
            (together_invite_email; built here, sent by tools_routes).

A player is mailed as a member (person_id, through the outbox, scope
notifications) or, with no account, as the lead their save recorded
(lead_id, through the outbox, only while AHAVAH_TOOL_LEADS_ENABLED is on).
Someone with neither is not mailed: they see the result when they come
back. Each queue runs behind a savepoint, so a mail failure never undoes a
player's finish or save. Names are escaped everywhere: a player chose
them.
"""
from __future__ import annotations

import html
import threading
import traceback
from typing import Callable, Optional

from antiabuse.antispam.signupemail import normalize_email
from emails.base import INK, SANS, button, is_suppressed_send, render
from service.campaigns import campaign_unsubscribed, held, outbox
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.unsubscribe import make_url as unsub_url

CAMPAIGN_ANSWERED = 'together_answered'
CAMPAIGN_READY = 'together_ready'
CAMPAIGN_SUMMARY = 'together_summary'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = f'support@{EMAIL_DOMAIN}'
REPLY_TO = 'support@ahavah.app'

# Taken from the second player's start screens (export 4.5 and 6.4). The
# game's line avoids 4.5's "hers": the app does not know the sender's
# pronoun, so it uses the mode card's "Neither of you sees the other's
# answers" (2.1). Proofed to the owner before together_invite_email is on.
GAME_INVITE_LINE = ('About 2 minutes. No account needed. Neither of you sees the other’s '
                    'answers. You both see the score.')
CHECKLIST_INVITE_LINE = ('Your answers stay private until you have both finished. Then you each '
                         'see where you agree and what to talk about.')
_PROOF_SESSION = '00000000-0000-0000-0000-000000000000'


def result_url(kind: str, session_uuid: str) -> str:
    path = '/together/game' if kind == 'game' else '/marriage-checklist'
    return f'{WEB_BASE_URL}{path}?session={session_uuid}'


def invite_url(invite_token: str) -> str:
    return f'{WEB_BASE_URL}/tools/i/{invite_token}'


def _heading(text: str) -> str:
    return (f'<h2 class="e-text" style="margin:0 0 22px;font-family:{SANS};font-size:22px;'
            f'font-weight:800;line-height:1.3;color:{INK};">{text}</h2>')


def answered_subject(name: str) -> str:
    return f'{name} has answered. See how you fit.'


def answered_html(name: str, cta: str, unsubscribe_url: str) -> str:
    n = html.escape(name)
    body = _heading(f'{n} has answered. See how you fit.') + button('See your comparison', cta)
    return render(title=html.escape(answered_subject(name)), preheader=f'{n} has answered.',
                  body_html=body,
                  footer_html=held.footer(
                      f'You get this because you invited {n} from ahavah.app/together.',
                      unsubscribe_url))


def invite_subject(kind: str, name: str) -> str:
    return (f'{name} wants to see how well you fit' if kind == 'game'
            else f'{name} invited you to the Ahavah marriage checklist')


def invite_html(kind: str, name: str, cta: str) -> str:
    n = html.escape(name)
    line = GAME_INVITE_LINE if kind == 'game' else CHECKLIST_INVITE_LINE
    body = _heading(html.escape(invite_subject(kind, name))) + held.para(line) + button('Start', cta)
    footer = ('Ahavah &middot; Matchmaking for Torah-observant believers.<br/>'
              f'You get this because {n} sent you a link from ahavah.app/together. '
              'We have not added you to any list.')
    return render(title=html.escape(invite_subject(kind, name)), preheader=html.escape(line),
                  body_html=body, footer_html=footer)


_Q_SEATS = """
    SELECT s.uuid::text AS uuid, s.kind, s.source, s.owner_email, s.owner_normalized_email,
           s.owner_person_id, s.owner_display,
           p.id, p.seat, p.role, p.email, p.normalized_email, p.person_id, p.display,
           p.finished_at
      FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.id = %(s)s AND s.deleted_at IS NULL
"""
_Q_PERSON = 'SELECT id, email FROM person WHERE id = %(i)s'
_Q_MEMBER_BY_NE = 'SELECT id, email FROM person WHERE normalized_email = %(ne)s LIMIT 1'
_Q_LEAD = 'SELECT id FROM lead WHERE normalized_email = %(ne)s AND source = %(src)s'


def _address(row: dict) -> dict:
    if row['seat'] == 'owner':
        return dict(email=row['owner_email'], normalized_email=row['owner_normalized_email'],
                    person_id=row['owner_person_id'])
    return dict(email=row['email'], normalized_email=row['normalized_email'],
                person_id=row['person_id'])


def _recipient(tx, *, email: Optional[str], normalized_email: Optional[str],
               person_id: Optional[int], source: str) -> Optional[dict]:
    from service.leads import tool_leads_enabled
    row = tx.execute(_Q_PERSON, dict(i=person_id)).fetchone() if person_id is not None else None
    if row is None and normalized_email:
        row = tx.execute(_Q_MEMBER_BY_NE, dict(ne=normalized_email)).fetchone()
    if row is not None:
        return dict(person_id=row['id'], email=row['email'])
    if not email or not normalized_email or not tool_leads_enabled():
        return None
    lead = tx.execute(_Q_LEAD, dict(ne=normalized_email, src=source)).fetchone()
    return dict(lead_id=lead['id'], email=email) if lead else None


def _queue(tx, *, campaign: str, campaign_id: str, to: dict, subject: str,
           html_for: Callable[[str], str]) -> Optional[int]:
    if is_suppressed_send(to['email']):
        return None
    if 'person_id' in to:
        if campaign_unsubscribed(tx, to['person_id'], UNSUB_SCOPE):
            return None
        unsub = unsub_url(UNSUB_SCOPE, to['email'], WEB_BASE_URL)
        return held.queue(tx, campaign=campaign, campaign_id=campaign_id,
                          person_id=to['person_id'], email=to['email'], subject=subject,
                          html=html_for(unsub), from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE,
                          unsub_url=unsub)
    unsub = unsub_url('news', to['email'], WEB_BASE_URL)
    return outbox.enqueue_for_lead(tx, campaign=campaign, campaign_id=campaign_id,
                                   lead_id=to['lead_id'], email=to['email'], subject=subject,
                                   html=html_for(unsub), from_addr=FROM_ADDR,
                                   list_unsubscribe=held.list_unsubscribe(unsub), marketing=False)


def _guarded(tx, name: str, fn: Callable[[], Optional[int]]) -> Optional[int]:
    tx.execute(f'SAVEPOINT {name}')
    try:
        out = fn()
    except Exception:
        tx.execute(f'ROLLBACK TO SAVEPOINT {name}')
        print(traceback.format_exc())
        return None
    tx.execute(f'RELEASE SAVEPOINT {name}')
    return out


def queue_answered(tx, session_pk: int, notify_player_id: int) -> Optional[int]:
    """The other player has finished: tell the one who finished first."""
    from service.tools import switch_on
    rows = [dict(r) for r in tx.execute(_Q_SEATS, dict(s=session_pk)).fetchall()]
    me = next((r for r in rows if r['id'] == notify_player_id), None)
    if me is None:
        return None
    other = next((r for r in rows if r['seat'] != me['seat']), None)
    name = (other['owner_display'] if other and other['seat'] == 'owner'
            else other['display'] if other else None)
    game = me['kind'] == 'game'
    if not name or not switch_on('together_answered_email' if game else 'together_ready_email'):
        return None

    def go():
        to = _recipient(tx, source=me['source'], **_address(me))
        if to is None:
            return None
        cta = result_url(me['kind'], me['uuid'])
        return _queue(tx, campaign=CAMPAIGN_ANSWERED if game else CAMPAIGN_READY,
                      campaign_id=me['uuid'], to=to, subject=answered_subject(name),
                      html_for=lambda u: answered_html(name, cta, u))
    return _guarded(tx, 'together_answered', go)


def queue_summary(tx, session_pk: int, player_id: int) -> Optional[int]:
    """A checklist player who has finished and can be reached gets their
    summary, once (the outbox's key: the session and the player)."""
    from service.tools import switch_on
    from service.tools.checklist import to_summary_answers
    from service.tools.sessions import answers_of
    if not switch_on('together_summary_email'):
        return None
    rows = [dict(r) for r in tx.execute(_Q_SEATS, dict(s=session_pk)).fetchall()]
    me = next((r for r in rows if r['id'] == player_id), None)
    if me is None or me['kind'] != 'checklist' or me['finished_at'] is None:
        return None

    def go():
        from emails.marriage_checklist import SUBJECT, checklist_results_html
        to = _recipient(tx, source=me['source'], **_address(me))
        answers = answers_of(tx, player_id)
        if to is None or not answers:
            return None
        body = checklist_results_html(me['role'], to_summary_answers(answers), stored=True)
        return _queue(tx, campaign=CAMPAIGN_SUMMARY, campaign_id=f"{me['uuid']}-{player_id}",
                      to=to, subject=SUBJECT, html_for=lambda _u: body)
    return _guarded(tx, 'together_summary', go)


def after_finish(tx, player: dict, event: Optional[dict]) -> None:
    if player['kind'] == 'checklist':
        queue_summary(tx, player['session_id'], player['player_id'])
    if event:
        queue_answered(tx, player['session_id'], event['notify_player_id'])


def preview_answered(to: str) -> tuple[str, str]:
    return answered_subject('Rivka'), answered_html(
        'Rivka', result_url('game', _PROOF_SESSION), unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))


def preview_ready(to: str) -> tuple[str, str]:
    return answered_subject('Rivka'), answered_html(
        'Rivka', result_url('checklist', _PROOF_SESSION), unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))


def preview_invite_game(to: str) -> tuple[str, str]:
    return invite_subject('game', 'Rivka'), invite_html('game', 'Rivka', invite_url('proof'))


def preview_invite_checklist(to: str) -> tuple[str, str]:
    return invite_subject('checklist', 'Rivka'), invite_html('checklist', 'Rivka', invite_url('proof'))


def preview_summary(to: str) -> tuple[str, str]:
    from emails.marriage_checklist import SUBJECT, checklist_results_html
    sample = [dict(section='biblical', ref='Genesis 2:18-24', importance=5, stance='agree',
                   comment='We leave and cleave, and build our own home.'),
              dict(section='nice-to-have', title='We pray together every evening', importance=5,
                   frequency='daily')]
    return SUBJECT, checklist_results_html('wife', sample, stored=True)
```

`normalize_email` is imported for Task 11's `prepare_invite`, which this module gains there.

In `service/tools/sessions.py`, at the end of `finish`, replace:

```python
    return dict(view=view(tx, sid, player['player_id']), event=event)
```

with:

```python
    from service.tools import mail
    mail.after_finish(tx, player, event)
    return dict(view=view(tx, sid, player['player_id']), event=event)
```

and at the end of `claim`, replace:

```python
    return view(tx, player['session_id'], player['player_id'])
```

(the last line of `claim`) with:

```python
    if player['kind'] == 'checklist' and player['finished_at'] is not None:
        # A single who saves after finishing gets their summary now.
        from service.tools import mail
        mail.queue_summary(tx, player['session_id'], player['player_id'])
    return view(tx, player['session_id'], player['player_id'])
```

- [ ] **Step 5: Say where the checklist v2 keeps answers**

In `service/person/__init__.py`, replace the docstring of `post_marriage_checklist_send`:

```python
    """Email the marriage-checklist results to the respondent and their
    spouse. Stateless by design: the answers are composed into the two
    emails in-request and never persisted (no table write, no answer
    logging). See docs: the checklist page promises 'we do not store
    your answers'."""
```

with:

```python
    """Email the marriage-checklist results to the respondent and their
    spouse. This endpoint stores no answers: it composes the two emails in
    the request and keeps only an anonymous count. It serves the first
    checklist, which the web shows while Together is dark. The checklist
    v2 keeps answers behind a private link, readable only by the two
    players, through service/tools (migration 0068); the privacy page
    says so (TEC-1845)."""
```

In `service/api/__init__.py`, replace the route docstring:

```python
    """Stateless send of the marriage-checklist activity results to the
    authed respondent + their spouse. Onboardees allowed (checklist users
    are onboardees, not full members). Answers are never stored."""
```

with:

```python
    """Send of the first marriage checklist's results to the authed
    respondent and their spouse. Onboardees allowed (checklist users are
    onboardees, not full members). Answers sent here are not stored; the
    checklist v2 stores them through /tools (service/tools)."""
```

In `duotypes/__init__.py`, replace the docstring of `MarriageChecklistAnswer`:

```python
    """One answered checklist item. Composed into the results email and
    then discarded; never persisted. Scripture items carry `ref` (e.g.
    "Ephesians 5:22-33"); the couple's own items carry `title`."""
```

with:

```python
    """One answered checklist item. Sent to /marriage-checklist/send it is
    composed into the results email and discarded. In the checklist v2 it
    is the stored shape of a tool_answer, kept behind a private link
    (service/tools/checklist.py). Scripture items carry `ref` (e.g.
    "Ephesians 5:22-33"); the couple's own items carry `title`."""
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_mail.py tests/test_tool_claim.py tests/test_tool_sessions.py tests/test_marriage_checklist.py -q -p no:warnings`
Expected: all pass (10 new, the earlier suites unchanged). If `tests/test_marriage_checklist.py` does not exist under that name, run `ls /d/Antigravity/ahavah-api/tests | grep -i checklist` and run the suite it lists instead.

- [ ] **Step 7: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/mail.py service/tools/sessions.py emails/marriage_checklist.py service/person/__init__.py service/api/__init__.py duotypes/__init__.py tests/test_tool_mail.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the answered, comparison ready and summary emails, held by their switches" -m "Refs: TEC-1845"
```

---

### Task 11: Sending the invite by email, held by signupguard and the per-recipient limit

**Files:**
- Modify: `service/tools/mail.py` (append `prepare_invite`, `send_invite_later`)
- Modify: `service/api/tools_routes.py` (append the route)
- Test: `tests/test_tool_invite_email.py` (create)

**Interfaces:**
- Consumes: `invite_subject`, `invite_html`, `invite_url`, `FROM_ADDR`, `REPLY_TO` (Task 10); `sessions.player_for`, `ToolError`, `TWO_PLAYER` (Task 6); `service.leads.mail_refusal`; `service.signupguard.record_refusal`; `shared_recipient_limit`, `limiter_account`, `disable_account_rate_limit` from `service.api.decorators`; `PostToolInviteEmail` (Task 6).
- Produces: `mail.prepare_invite(tx, player, to_email, *, count: bool) -> {to, subject, html}` (403 `not_allowed` for a guest, 400 `bad_mode` outside Us and the couple checklist, 409 `not_saved`, 400 `own_address`); `mail.send_invite_later(msg) -> None`; `POST /tools/sessions/{id}/invite-email` `{email, website?, signup_stamp?}` with a signed-in session -> 202 `{sent: true}`, also for a refused address; 404 `{error: 'off'}` while `together_invite_email` is off.

The export draws "Send it by email" for Us (4.3) and the couple checklist (6.2) only; Who knows me best posts a link (4.11), so it has no invite email. Limits: 10 a day per account, and the shared `recipient` scope of `/request-otp` and the checklist send (5 an hour and 20 a day per address), so one inbox is bounded across every send.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_invite_email.py`:

```python
"""Sending a Together invite by email (TEC-1845).

Spec: "Rate limits follow the checklist's (5 an hour per recipient for
invite emails)." Plus the free bot protection every mail-sending endpoint
uses (service.leads.mail_refusal, signupguard): a refused address is
answered exactly as a sent one, and nothing is mailed.
"""
from __future__ import annotations

import pytest

from database import api_tx
from service import leads, signupguard
from service.tools import mail

pytestmark = pytest.mark.usefixtures('together_schema', 'together_live', 'no_limits')
_MADE: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with api_tx() as tx:
        for sid in _MADE:
            tx.execute('DELETE FROM tool_session WHERE uuid = %(u)s', dict(u=sid))
    _MADE.clear()


@pytest.fixture
def outbox(monkeypatch):
    """What would be mailed, what signupguard was asked and what it refused."""
    box = dict(sent=[], asked=[], refused=[], answer=None)
    monkeypatch.setenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', '1')
    monkeypatch.setattr(mail, 'send_invite_later', lambda msg: box['sent'].append(msg))

    def refusal(**kw):
        box['asked'].append(kw)
        return box['answer']
    monkeypatch.setattr(leads, 'mail_refusal', refusal)
    monkeypatch.setattr(signupguard, 'record_refusal',
                        lambda reason, **kw: box['refused'].append(reason))
    return box


def _h(token, headers=None):
    return {'X-Tool-Token': token, **(headers or {})}


def _saved(client, headers, mode='us', kind='game'):
    body = client.post('/tools/sessions', json=dict(kind=kind, mode=mode)).get_json()
    sid, token = body['session_id'], body['player_token']
    _MADE.append(sid)
    invite = client.post(f'/tools/sessions/{sid}/claim', json=dict(display='Daniel'),
                         headers=_h(token, headers)).get_json()['invite_token']
    return sid, token, invite


def _send(client, sid, token, headers, to='rivka@ahavah-test.invalid', **extra):
    return client.post(f'/tools/sessions/{sid}/invite-email', json=dict(email=to, **extra),
                       headers=_h(token, headers))


def _count(sid):
    with api_tx() as tx:
        return tx.execute('SELECT invite_emails FROM tool_session WHERE uuid = %(u)s',
                          dict(u=sid)).fetchone()['invite_emails']


def test_the_invite_email_is_off_until_its_switch(client, tool_visitor, monkeypatch):
    monkeypatch.delenv('AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED', raising=False)
    _, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers)
    assert (r.status_code, r.get_json()) == (404, {'error': 'off'})


def test_only_the_player_who_saved_can_send_it(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    body = client.post('/tools/sessions', json=dict(kind='game', mode='us')).get_json()
    _MADE.append(body['session_id'])
    r = _send(client, body['session_id'], body['player_token'], headers)
    assert (r.status_code, r.get_json()) == (409, {'error': 'not_saved'})
    sid, _, invite = _saved(client, headers)
    guest = client.post(f'/tools/i/{invite}/players', json=dict(display='Rivka')).get_json()['player_token']
    _, guest_headers = tool_visitor()
    assert _send(client, sid, guest, guest_headers).status_code == 403
    sid_me, token_me, _ = _saved(client, headers, mode='me')
    assert _send(client, sid_me, token_me, headers).get_json() == {'error': 'bad_mode'}
    assert outbox['sent'] == []


def test_one_invite_goes_with_the_players_name_and_link(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    sid, token, invite = _saved(client, headers)
    r = _send(client, sid, token, headers, signup_stamp='stamp-1')
    assert (r.status_code, r.get_json()) == (202, {'sent': True})
    [msg] = outbox['sent']
    assert msg['to'] == 'rivka@ahavah-test.invalid'
    assert msg['subject'] == 'Daniel wants to see how well you fit'
    assert f'/tools/i/{invite}' in msg['html'] and 'You both see the score.' in msg['html']
    assert _count(sid) == 1
    assert outbox['asked'][0]['stamp'] == 'stamp-1' and outbox['asked'][0]['email'] == 'rivka@ahavah-test.invalid'


def test_a_refused_address_is_answered_as_a_send_and_nothing_goes(client, tool_visitor, outbox):
    outbox['answer'] = 'bad_domain'
    _, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers)
    assert (r.status_code, r.get_json()) == (202, {'sent': True})
    assert outbox['sent'] == [] and outbox['refused'] == ['bad_domain'] and _count(sid) == 0


def test_a_player_cannot_invite_their_own_address(client, tool_visitor, outbox):
    email, headers = tool_visitor()
    sid, token, _ = _saved(client, headers)
    r = _send(client, sid, token, headers, to=email)
    assert (r.status_code, r.get_json()) == (400, {'error': 'own_address'})


def test_the_checklist_invite_names_the_checklist(client, tool_visitor, outbox):
    _, headers = tool_visitor()
    sid, token, invite = _saved(client, headers, mode='couple', kind='checklist')
    _send(client, sid, token, headers)
    [msg] = outbox['sent']
    assert msg['subject'] == 'Daniel invited you to the Ahavah marriage checklist'
    assert 'Your answers stay private until you have both finished.' in msg['html']
    assert f'/tools/i/{invite}' in msg['html']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_invite_email.py -q -p no:warnings`
Expected: `6 failed` (`/invite-email` answers 404, and `mail` has no `send_invite_later` to patch).

- [ ] **Step 3: Write the implementation**

Append to `service/tools/mail.py`:

```python
def prepare_invite(tx, player: dict, to_email: str, *, count: bool) -> dict:
    """The invite the player who saved an Us game or a couple checklist
    sends to the other person. `count` adds it to the session's tally
    (Admin > Growth); a refused address is not counted."""
    from service.tools.sessions import TWO_PLAYER, ToolError
    if player['seat'] != 'owner':
        raise ToolError('not_allowed', 403)
    if player['mode'] not in TWO_PLAYER:
        raise ToolError('bad_mode')
    if not player['invite_token'] or not player['owner_display']:
        raise ToolError('not_saved', 409)
    if normalize_email(to_email) == player['owner_normalized_email']:
        raise ToolError('own_address')
    if count:
        tx.execute('UPDATE tool_session SET invite_emails = invite_emails + 1 WHERE id = %(i)s',
                   dict(i=player['session_id']))
    name = player['owner_display']
    return dict(to=to_email, subject=invite_subject(player['kind'], name),
                html=invite_html(player['kind'], name, invite_url(player['invite_token'])))


def send_invite_later(msg: dict) -> None:
    """Straight to the mailer once the request has committed, as the
    checklist's spouse email is sent: the recipient is neither a member
    nor a lead, so the outbox, which names one, cannot hold it."""
    def _go():
        try:
            from smtp import aws_smtp
            aws_smtp.send(subject=msg['subject'], body=msg['html'], to_addr=msg['to'],
                          from_addr=FROM_ADDR, reply_to=REPLY_TO)
        except Exception:
            print(traceback.format_exc())
    threading.Thread(target=_go, daemon=True).start()
```

Append to `service/api/tools_routes.py`:

```python
from service.api.decorators import (
    disable_account_rate_limit,
    limiter_account,
    shared_recipient_limit,
)

# 10 a day per account; the shared `recipient` scope (5 an hour, 20 a day
# per address, with /request-otp and the checklist send) bounds one inbox.
_invite_account_limit = limiter.shared_limit(
    '10 per day', scope='tools_invite_email', key_func=limiter_account,
    exempt_when=disable_account_rate_limit)


@apost('/tools/sessions/<sid>/invite-email', expected_onboarding_status=None,
       limiter=[_invite_account_limit, shared_recipient_limit])
@validate(t.PostToolInviteEmail)
def post_tool_invite_email(req: t.PostToolInviteEmail, s: t.SessionInfo, sid: str):
    """Send the invite link by email. A refused address (signupguard's free
    rules: the hidden field, the page stamp, the per-network limits and the
    bad domains) gets the same answer as a sent one, and nothing goes."""
    from service import leads, signupguard
    from service.tools import live, mail, sessions, switch_on
    if not live():
        return _off()
    if not switch_on('together_invite_email'):
        return dict(error='off'), 404
    # mail_refusal opens its own read, so it runs before the transaction.
    refusal = leads.mail_refusal(email=req.email, ip=request.remote_addr,
                                 stamp=req.signup_stamp, website=req.website)
    try:
        with api_tx() as tx:
            player = sessions.player_for(tx, sid, _token(), s)
            msg = mail.prepare_invite(tx, player, req.email, count=refusal is None)
    except sessions.ToolError as e:
        return _refused(e)
    if refusal:
        signupguard.record_refusal(refusal, new_address=True, email=req.email,
                                   ip=request.remote_addr)
        return dict(sent=True), 202
    mail.send_invite_later(msg)
    return dict(sent=True), 202
```

Fold the three decorator names into the module's single decorators import line.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_invite_email.py tests/test_tool_mail.py -q -p no:warnings`
Expected: all pass (6 new, the mail suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/mail.py service/api/tools_routes.py tests/test_tool_invite_email.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): send the invite by email, held by signupguard and the per-recipient limit" -m "Refs: TEC-1845"
```

---

### Task 12: Proofs of the 5 emails, to the owner only

**Files:**
- Create: `scripts/send_together_proofs.py`
- Test: `tests/test_send_together_proofs.py` (create)

**Interfaces:**
- Consumes: `scripts.send_proofs.PROOF_TO`, `PROOF_LINK_DISABLED`, `_inert`, `_smtp`; `mail.preview_answered`, `preview_ready`, `preview_invite_game`, `preview_invite_checklist`, `preview_summary`, `FROM_ADDR` (Task 10).
- Produces: `scripts.send_together_proofs.plan() -> list[dict]` (`name`, `label`, `subject`, `html`, `from_addr`), `main(argv)`; proofs named `together_answered`, `together_ready`, `together_invite_game`, `together_invite_checklist`, `together_summary`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_send_together_proofs.py`:

```python
"""scripts/send_together_proofs.py (TEC-1845): one proof of each Together
email to the owner's address only. A dry run by default; nothing recorded;
no switch read or changed; no live unsubscribe link."""
import os

import pytest

from database import api_tx
from scripts import send_together_proofs as tp

EXPECTED = {'together_answered', 'together_ready', 'together_invite_game',
            'together_invite_checklist', 'together_summary'}
_TABLES = ('email_outbox', 'email_send_log', 'tool_session', 'lead')


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n'] for t in _TABLES}


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def smtp(monkeypatch, together_schema):
    s = _Smtp()
    monkeypatch.setattr(tp, '_smtp', lambda: s)
    return s


def test_the_plan_covers_every_together_email():
    emails = tp.plan()
    assert {e['name'] for e in emails} == EXPECTED
    assert tp.PROOF_TO == 'harrigan.tennyson@gmail.com'


def test_a_dry_run_sends_nothing(smtp, capsys):
    before = _counts()
    tp.main([])
    assert smtp.sent == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    tp.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == len(EXPECTED)
    assert all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert _counts() == before and dict(os.environ) == env_before


def test_no_proof_carries_a_live_unsubscribe_link():
    from service.config import WEB_BASE_URL
    by_name = {e['name']: e['html'] for e in tp.plan()}
    for name, html in by_name.items():
        assert f'{WEB_BASE_URL.rstrip("/")}/u/' not in html, name
    for name in ('together_answered', 'together_ready'):
        assert f'href="{tp.PROOF_LINK_DISABLED}"' in by_name[name], name
    assert 'Rivka has answered. See how you fit.' in by_name['together_answered']
    assert 'We keep your answers behind a private link' in by_name['together_summary']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_send_together_proofs.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'send_together_proofs' from 'scripts'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/send_together_proofs.py`:

```python
"""Send the owner one proof of each Together email (TEC-1845), before any
of their switches is turned on.

    python -m scripts.send_together_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_together_proofs --send     # send the proofs

Run inside the api container (mailer settings). The same rules as
scripts/send_proofs.py, whose address and helpers this reuses: to
PROOF_TO only, straight through the mailer, never the outbox; sample data
only (Rivka); no switch read or changed; every unsubscribe link inert.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from scripts.send_proofs import PROOF_LINK_DISABLED, PROOF_TO, _inert, _smtp

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'plan', 'main']


def plan() -> list[dict]:
    """Every proof email, built. Writes nothing."""
    from service.tools import mail
    builders = [
        ('together_answered', 'Us: the other player has answered (4.10)', mail.preview_answered),
        ('together_ready', 'Checklist: your comparison is ready (6.12)', mail.preview_ready),
        ('together_invite_game', 'Us: the invite sent by email (4.3)', mail.preview_invite_game),
        ('together_invite_checklist', 'Checklist: the invite sent by email (6.2)',
         mail.preview_invite_checklist),
        ('together_summary', 'Checklist summary with the stored-answers line (decision 12)',
         mail.preview_summary),
    ]
    out = []
    for name, label, build in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f'[PROOF] {subject}',
                        html=_inert(name, html), from_addr=mail.FROM_ADDR))
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}")
    for e in emails:
        print(f"  email  {e['name']:26s} {e['subject']}  ({e['label']})")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO,
                        from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")


if __name__ == '__main__':
    main(sys.argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_send_together_proofs.py tests/test_send_proofs.py -q -p no:warnings`
Expected: all pass (4 new, the Wave 3 proof suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add scripts/send_together_proofs.py tests/test_send_together_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): proofs of the 5 Together emails, to the owner only" -m "Refs: TEC-1845"
```

---

### Task 13: The 12 month sweep and deleting with the account

**Files:**
- Create: `service/tools/retention.py`
- Modify: `service/cron/leadretention/__init__.py` (`_purge_once`)
- Modify: `service/hard_delete.py` (add `Q_DELETE_TOOL_DATA_OF` after `Q_DELETE_LEADS_OF`)
- Modify: `service/cron/pendingdeletion/__init__.py`, `service/api/admin/users_action_routes.py` (run it beside `Q_DELETE_LEADS_OF`)
- Test: `tests/test_tool_retention.py` (create)

**Interfaces:**
- Consumes: `service.leads.RETENTION_DAYS` (365).
- Produces: `retention.UNSAVED_DAYS = 30`, `retention.TOMBSTONE_DAYS = 30`, `retention.purge_stale_tool_sessions(tx) -> int`; `hard_delete.Q_DELETE_TOOL_DATA_OF` bound with `nes` (normalised addresses), as `Q_DELETE_LEADS_OF` is.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_retention.py`:

```python
"""Together's retention (TEC-1845).

Spec: "Rows are deleted 12 months after the last visit, or on request."
A session nobody saved goes after 30 days (nothing links it to anyone but
a device); a deleted session's tombstone goes 30 days after the delete.
Deleting an account deletes every session the address saved and every Us
game or couple checklist it joined, since a comparison is shared.
"""
from __future__ import annotations

import pathlib
import secrets

import pytest

from database import api_tx
from service.hard_delete import Q_DELETE_TOOL_DATA_OF
from service.tools.retention import purge_stale_tool_sessions

pytestmark = pytest.mark.usefixtures('together_schema')


def _session(*, mode='us', saved=True, days_ago=0, deleted_days_ago=None, owner_ne=None,
             owner_person_id=None) -> int:
    kind = 'checklist' if mode in ('couple', 'single') else 'game'
    source = {'me': 'tool:game-me', 'us': 'tool:game-us', 'knows_me': 'tool:knows-me',
              'couple': 'tool:checklist', 'single': 'tool:checklist'}[mode]
    with api_tx() as tx:
        return tx.execute(
            """INSERT INTO tool_session (kind, mode, source, claimed_at, last_visit_at, deleted_at,
                                         owner_normalized_email, owner_person_id)
               VALUES (%(k)s, %(m)s, %(src)s, CASE WHEN %(saved)s THEN NOW() END,
                       NOW() - make_interval(days => %(d)s),
                       CASE WHEN %(dd)s::int IS NOT NULL
                            THEN NOW() - make_interval(days => %(dd)s) END,
                       %(ne)s, %(pid)s)
               RETURNING id""",
            dict(k=kind, m=mode, src=source, saved=saved, d=days_ago, dd=deleted_days_ago,
                 ne=owner_ne, pid=owner_person_id)).fetchone()['id']


def _exists(ids):
    with api_tx() as tx:
        return [bool(tx.execute('SELECT 1 FROM tool_session WHERE id = %(i)s', dict(i=i)).fetchone())
                for i in ids]


def _drop(ids):
    with api_tx() as tx:
        tx.execute('DELETE FROM tool_session WHERE id = ANY(%(i)s)', dict(i=list(ids)))


def test_the_sweep_keeps_what_is_recent_and_deletes_what_is_old(make_person):
    member = make_person(name='Keeper')
    keep = [_session(days_ago=364), _session(saved=False, days_ago=29),
            _session(saved=False, days_ago=31, owner_person_id=member['id']),
            _session(days_ago=1, deleted_days_ago=29)]
    gone = [_session(days_ago=366), _session(saved=False, days_ago=31),
            _session(days_ago=1, deleted_days_ago=31)]
    try:
        with api_tx() as tx:
            purge_stale_tool_sessions(tx)
        assert _exists(keep) == [True] * 4 and _exists(gone) == [False] * 3
    finally:
        _drop(keep + gone)


def test_the_daily_cron_runs_the_sweep():
    from service.cron import leadretention
    old = _session(days_ago=400)
    try:
        leadretention._purge_once()
        assert _exists([old]) == [False]
    finally:
        _drop([old])


def test_deleting_an_account_deletes_the_sessions_it_saved_or_shared():
    ne = f'gone-{secrets.token_hex(5)}@ahavah-test.invalid'
    owned = _session(mode='me', owner_ne=ne)
    joined = _session(mode='us')
    friend = _session(mode='knows_me')
    with api_tx() as tx:
        for sid in (joined, friend):
            tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, normalized_email)
                          VALUES (%(s)s, 'guest', %(h)s, %(ne)s)""",
                       dict(s=sid, h=secrets.token_hex(16), ne=ne))
    try:
        with api_tx() as tx:
            tx.execute(Q_DELETE_TOOL_DATA_OF, dict(nes=[ne]))
        assert _exists([owned, joined, friend]) == [False, False, True]
    finally:
        _drop([owned, joined, friend])


def test_both_deletion_paths_run_it():
    for path in ('service/cron/pendingdeletion/__init__.py',
                 'service/api/admin/users_action_routes.py'):
        assert 'Q_DELETE_TOOL_DATA_OF' in pathlib.Path(f'/app/{path}').read_text(), path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_retention.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'Q_DELETE_TOOL_DATA_OF' from 'service.hard_delete'`.

- [ ] **Step 3: Write the implementation**

Create `service/tools/retention.py`:

```python
"""Together's sweep (TEC-1845), run daily by the lead retention cron.

  - A saved session (or one a member started) goes 12 months after the
    last visit by a player (service.leads.RETENTION_DAYS, the leads'
    clock). A visit is any read or write with a player's token or saved
    address (service/tools/sessions.player_for); opening a share link is
    not a visit.
  - A session nobody saved goes after UNSAVED_DAYS: nothing links it to
    anyone but a device.
  - A deleted session's tombstone (its tokens, so links say "deleted")
    goes TOMBSTONE_DAYS after the delete.
Players, answers and results go with their session (ON DELETE CASCADE).
"""
from __future__ import annotations

from service.leads import RETENTION_DAYS

UNSAVED_DAYS = 30
TOMBSTONE_DAYS = 30

_Q_PURGE = """
    DELETE FROM tool_session
     WHERE (deleted_at IS NOT NULL
            AND deleted_at < NOW() - make_interval(days => %(tomb)s))
        OR (deleted_at IS NULL AND claimed_at IS NULL AND owner_person_id IS NULL
            AND last_visit_at < NOW() - make_interval(days => %(unsaved)s))
        OR (deleted_at IS NULL
            AND last_visit_at < NOW() - make_interval(days => %(days)s))
"""


def purge_stale_tool_sessions(tx) -> int:
    return tx.execute(_Q_PURGE, dict(tomb=TOMBSTONE_DAYS, unsaved=UNSAVED_DAYS,
                                     days=RETENTION_DAYS)).rowcount
```

In `service/cron/leadretention/__init__.py`, replace:

```python
def _purge_once() -> None:
    with api_tx() as tx:
        n = purge_stale_leads(tx)
    if n:
        print(f'lead_retention: {n} lead(s) deleted after {RETENTION_DAYS} days without a visit')
```

with:

```python
def _purge_once() -> None:
    from service.tools.retention import purge_stale_tool_sessions
    with api_tx() as tx:
        n = purge_stale_leads(tx)
        n_tools = purge_stale_tool_sessions(tx)
    if n:
        print(f'lead_retention: {n} lead(s) deleted after {RETENTION_DAYS} days without a visit')
    if n_tools:
        print(f'lead_retention: {n_tools} Together session(s) deleted (12 months without a visit, '
              f'30 days unsaved, or 30 days after a delete)')
```

In `service/hard_delete.py`, after the `Q_DELETE_LEADS_OF` string, add:

```python
# Together (TEC-1845): every session the address saved, and every Us game
# or couple checklist it joined, since a comparison is shared. A knows-me
# friend gives no address, so nothing of theirs is found by one. The
# caller binds `nes`, as for Q_DELETE_LEADS_OF. Sessions linked to the
# person go with the person row too (owner_person_id cascades).
Q_DELETE_TOOL_DATA_OF = """
    DELETE FROM tool_session s
     WHERE s.owner_normalized_email = ANY(%(nes)s::text[])
        OR (s.mode IN ('us', 'couple') AND EXISTS (
              SELECT 1 FROM tool_player p
               WHERE p.session_id = s.id AND p.normalized_email = ANY(%(nes)s::text[])))
"""
```

In `service/cron/pendingdeletion/__init__.py`, add `Q_DELETE_TOOL_DATA_OF,` to the import list beside `Q_DELETE_LEADS_OF,`, and replace:

```python
                await tx.execute(Q_DELETE_LEADS_OF,
                                 dict(nes=[normalize_email(e) for e in emails]))
```

with:

```python
                await tx.execute(Q_DELETE_LEADS_OF,
                                 dict(nes=[normalize_email(e) for e in emails]))
                # Together sessions saved or shared by the address (TEC-1845).
                await tx.execute(Q_DELETE_TOOL_DATA_OF,
                                 dict(nes=[normalize_email(e) for e in emails]))
```

In `service/api/admin/users_action_routes.py`, add `Q_DELETE_TOOL_DATA_OF,` to the import list beside `Q_DELETE_LEADS_OF,`, and replace:

```python
            tx.execute(Q_DELETE_LEADS_OF, dict(nes=[normalize_email(row['email'])]))
```

with:

```python
            tx.execute(Q_DELETE_LEADS_OF, dict(nes=[normalize_email(row['email'])]))
            tx.execute(Q_DELETE_TOOL_DATA_OF, dict(nes=[normalize_email(row['email'])]))
```

A non-member who asks for deletion at support@ahavah.app is handled by support running `Q_DELETE_TOOL_DATA_OF` and `Q_DELETE_LEADS_OF` with that address, as for leads; or the player uses "Delete this result".

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_tool_retention.py tests/test_lead_retention.py -q -p no:warnings`
Expected: all pass (4 new, the lead retention suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/retention.py service/cron/leadretention/__init__.py service/hard_delete.py service/cron/pendingdeletion/__init__.py service/api/admin/users_action_routes.py tests/test_tool_retention.py
git -c user.email=admin@techbaseltd.com commit -m "feat(together): delete sessions 12 months after the last visit, unsaved ones after 30 days, and with the account" -m "Refs: TEC-1845"
```

---

### Task 14: Counts for Admin > Growth, and the screen as a Linear issue

**Files:**
- Create: `service/tools/admin.py`
- Modify: `service/api/admin/growth_routes.py` (append the route after `get_admin_growth_sources`)
- Modify: this plan (item 11 of "Spec conflicts and decisions needing the owner")
- Test: `tests/test_admin_tool_counts.py` (create)

**Interfaces:**
- Consumes: `require_admin`; the tool tables (Task 1); `person.lead_source`.
- Produces: `admin.tool_counts(tx) -> {'modes': [{mode, started, completed, saved, links, invite_emails, joined, guests, share_opens}], 'signups': {source: int}}`; `GET /admin/growth/tools` (admin session only); one Linear issue in the Ahavah Admin project.

Spec, Admin: "Growth gets a 'Couple tools' row: started, completed, emails confirmed, invites sent and accepted, shares (link opens from a share token), sign-ups that came from a tool." Counts only: the query reads no answer, name or address.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_tool_counts.py`:

```python
"""Admin > Growth, Couple tools (TEC-1845): counts only, never an answer,
a name or an address."""
from __future__ import annotations

import hashlib
import secrets

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('together_schema')


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


def _us(mode='us') -> int:
    with api_tx() as tx:
        sid = tx.execute(
            """INSERT INTO tool_session (kind, mode, source, claimed_at, completed_at, invite_token,
                                         invite_emails, share_opens, owner_display)
               VALUES ('game', %(m)s, 'tool:game-us', NOW(), NOW(), %(t)s, 2, 3, 'Daniel')
               RETURNING id""", dict(m=mode, t=secrets.token_urlsafe(16))).fetchone()['id']
        tx.execute("""INSERT INTO tool_player (session_id, seat, token_hash, display)
                      VALUES (%(s)s, 'guest', %(h)s, 'Rivka')""", dict(s=sid, h=secrets.token_hex(16)))
    return sid


def _row(body, mode):
    return next(r for r in body['modes'] if r['mode'] == mode)


def test_the_counts_are_for_admins_only(client, make_person):
    r = client.get('/admin/growth/tools', headers=_headers(make_person(name='ToolsMember'), False))
    assert r.status_code == 403


def test_the_counts_move_with_the_sessions(client, make_person):
    headers = _headers(make_person(name='ToolsAdmin'), True)
    before = _row(client.get('/admin/growth/tools', headers=headers).get_json(), 'us')
    sid = _us()
    try:
        after = _row(client.get('/admin/growth/tools', headers=headers).get_json(), 'us')
        assert {k: after[k] - before[k] for k in before if k != 'mode'} == dict(
            started=1, completed=1, saved=1, links=1, invite_emails=2, joined=1, guests=1,
            share_opens=3)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))


def test_the_counts_carry_no_answer_or_name(client, make_person):
    headers = _headers(make_person(name='ToolsAdmin2'), True)
    sid = _us()
    try:
        body = client.get('/admin/growth/tools', headers=headers).get_json()
        assert [r['mode'] for r in body['modes']] == ['me', 'us', 'knows_me', 'couple', 'single']
        assert set(body['signups']) == {'tool:game-me', 'tool:game-us', 'tool:knows-me',
                                        'tool:checklist'}
        assert 'Daniel' not in str(body) and 'Rivka' not in str(body)
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM tool_session WHERE id = %(i)s', dict(i=sid))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_admin_tool_counts.py -q -p no:warnings`
Expected: `3 failed` (`/admin/growth/tools` answers 404).

- [ ] **Step 3: Write the implementation**

Create `service/tools/admin.py`:

```python
"""Together on Admin > Growth (TEC-1845): counts only.

Spec: "Answers are only readable by the two players through their tokens,
and by no admin screen except as counts." The queries here read no answer,
display name or address. Deleted sessions are still counted until the
sweep removes them; the sweep's deletions lower the counts, which is the
cost of keeping nothing for longer than the privacy page says.
"""
from __future__ import annotations

MODES = ('me', 'us', 'knows_me', 'couple', 'single')
SOURCES = ('tool:game-me', 'tool:game-us', 'tool:knows-me', 'tool:checklist')

_Q_MODES = """
    SELECT s.mode,
           count(*) AS started,
           count(*) FILTER (WHERE s.completed_at IS NOT NULL) AS completed,
           count(*) FILTER (WHERE s.claimed_at IS NOT NULL) AS saved,
           count(*) FILTER (WHERE s.invite_token IS NOT NULL) AS links,
           COALESCE(sum(s.invite_emails), 0)::int AS invite_emails,
           count(*) FILTER (WHERE g.n > 0) AS joined,
           COALESCE(sum(g.n), 0)::int AS guests,
           COALESCE(sum(s.share_opens), 0)::int AS share_opens
      FROM tool_session s
      LEFT JOIN LATERAL (SELECT count(*) AS n FROM tool_player p
                          WHERE p.session_id = s.id AND p.seat = 'guest') g ON TRUE
     GROUP BY s.mode
"""

_Q_SIGNUPS = """
    SELECT lead_source AS source, count(*)::int AS n FROM person
     WHERE lead_source = ANY(%(src)s) GROUP BY lead_source
"""

_ZERO = dict(started=0, completed=0, saved=0, links=0, invite_emails=0, joined=0, guests=0,
             share_opens=0)


def tool_counts(tx) -> dict:
    by_mode = {r['mode']: {k: int(v) for k, v in dict(r).items() if k != 'mode'}
               for r in tx.execute(_Q_MODES).fetchall()}
    signups = {r['source']: r['n'] for r in tx.execute(_Q_SIGNUPS, dict(src=list(SOURCES))).fetchall()}
    return dict(modes=[dict(mode=m, **by_mode.get(m, _ZERO)) for m in MODES],
                signups={s: signups.get(s, 0) for s in SOURCES})
```

Append to `service/api/admin/growth_routes.py`, after `get_admin_growth_sources`:

```python
@aget('/admin/growth/tools')
def get_admin_growth_tools(s: t.SessionInfo):
    """Couple tools (TEC-1845): per mode, sessions started, completed,
    saved, invite links made, invite emails sent, sessions a guest joined,
    guests and share-link openings; sign-ups per tool source. Counts only,
    never an answer or a name."""
    require_admin(s)
    from service.tools.admin import tool_counts
    with api_tx('read committed') as tx:
        return tool_counts(tx)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_admin_tool_counts.py tests/test_growth_sources.py -q -p no:warnings`
Expected: all pass (3 new, the Sources suite unchanged).

- [ ] **Step 5: The admin screen becomes an issue**

With the Linear tools (`mcp__linear-server__save_issue`): team `Techbase Solutions LLC`, project `Ahavah Admin`, label `Client: Ahavah`, state Backlog.

Title: `Growth: the Couple tools row`

Description: `Follow-up to TEC-1845 (ahavah-api docs/superpowers/plans/2026-10-17-together-release-1.md, Task 14). Show GET /admin/growth/tools on the Growth tab as the Couple tools row the spec asks for (started, completed, emails confirmed, invites sent and accepted, shares, sign-ups from a tool): per mode (me, us, knows_me, couple, single) started, completed, saved, links, invite_emails, joined, guests, share_opens, and sign-ups per tool source. Counts only; the API never returns an answer or a name. Screens come from the Claude Design admin brief (briefs/2026-10-13-admin-growth-features.md). Admin tables fold into cards at 390.`

Then in item 11 of "Spec conflicts and decisions needing the owner" at the end of this plan, replace the words `the id Task 14 returns` with the new issue's id.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/tools/admin.py service/api/admin/growth_routes.py tests/test_admin_tool_counts.py docs/superpowers/plans/2026-10-17-together-release-1.md
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): Couple tools counts for the Growth tab, never an answer or a name" -m "Refs: TEC-1845"
```

---

## Release 1 web (ahavah-web)

Every web task works on the branch `together` from `master`. Each one ends with `/sot-sync` against the export frames it names, after its tests are green, then runs its tests again. The copy in the code below is the export's, word for word; a line the export does not have is marked `// Not in the export:` in the code and listed under "Spec conflicts".

### Task 15: The API client's headers, the Together API, device storage and the live check

**Files:**
- Modify: `src/lib/api-client.ts` (`request` and `apiClient`)
- Modify: `src/lib/auth-otp.ts` (`checkOtp`'s `source`)
- Create: `src/lib/together/api.ts`, `src/lib/together/storage.ts`, `src/lib/together/status.ts`
- Test: `tests/lib/api-client-headers.test.ts`, `tests/lib/together-api.test.ts`, `tests/lib/together-storage.test.ts` (create)

**Interfaces:**
- Consumes: the API routes of Tasks 2 and 6 to 11; `readFirstTouch` (`src/lib/first-touch.ts`), `firstTouchPayload` (`src/lib/onboarding-attribution.ts`); `fetchPublicSummary` (`src/lib/share-image/summary.ts`).
- Produces:
  - `apiClient.get(path, options?)`, `post(path, body?, options?)`, `put`, `patch`, `delete(path, body?, options?)` with `options: { headers?: Record<string, string> }`; the session's `Authorization` always wins over a caller's header.
  - `checkOtp(email, otp, { source?: "marriage_checklist" | ToolSource })`.
  - `src/lib/together/api.ts`: types `ToolKind`, `ToolMode`, `ToolSource`, `SOURCE_OF: Record<ToolMode, ToolSource>`, `AnswerValue`, `SessionView`, `MeResult`, `UsResult`, `FriendResult`, `Comparison`, `ComparisonItem`, `OwnItem`, `SingleResult`, `BoardRow`, `InviteInfo`, `PublicSummary`; functions `startSession(kind, mode)`, `saveAnswers(sessionId, token, answers, role?)`, `finishSession(sessionId, token)`, `getSession(sessionId, token)`, `claimSession(sessionId, token, display)`, `getInvite(invite)`, `joinSession(invite, display)`, `sendInviteEmail(sessionId, token, email, antibot)`, `deleteSession(sessionId, token)`, `removeFromBoard(sessionId, token, playerId)`, `restoreToBoard(sessionId, token, playerId)`, `countShareOpen(share)`, `getStatus()`.
  - `src/lib/together/storage.ts`: `StoredSession = { sessionId, token, kind, mode, seat, invite?, finished?, savedAt }`, `readSessions()`, `rememberSession(s)`, `markFinished(sessionId)`, `forgetSession(sessionId)`, `sessionById(id)`, `sessionByInvite(invite)`, `unfinished(kind)`; key `ahavah.together.v1`.
  - `src/lib/together/status.ts`: `togetherStatus(): Promise<{ live: boolean; inviteEmail: boolean }>` for server components (dark when the API cannot be read).

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/api-client-headers.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient, setSessionToken } from "@/lib/api-client";

describe("apiClient headers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setSessionToken(null);
  });

  it("sends a caller's header and keeps the session's Authorization", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    setSessionToken("session-1");
    await apiClient.get("/tools/sessions/x", { headers: { "X-Tool-Token": "t".repeat(32), Authorization: "Bearer forged" } });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Tool-Token"]).toBe("t".repeat(32));
    expect(headers.Authorization).toBe("Bearer session-1");
  });

  it("works as before with no options", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await apiClient.post("/x", { a: 1 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
    expect((init.headers as Record<string, string>)["X-Tool-Token"]).toBeUndefined();
  });
});
```

Create `tests/lib/together-api.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { ...actual.apiClient, ...api } };
});
vi.mock("@/lib/first-touch", () => ({ readFirstTouch: () => ({ utm_source: "share", utm_campaign: "game-us" }) }));

import {
  SOURCE_OF,
  claimSession,
  finishSession,
  getSession,
  joinSession,
  saveAnswers,
  sendInviteEmail,
  startSession,
} from "@/lib/together/api";

const T = "t".repeat(32);

describe("the Together API", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.delete.mockReset();
  });

  it("names a source for every mode", () => {
    expect(SOURCE_OF).toEqual({
      me: "tool:game-me", us: "tool:game-us", knows_me: "tool:knows-me",
      couple: "tool:checklist", single: "tool:checklist",
    });
  });

  it("starts a session with the device's first touch", async () => {
    api.post.mockResolvedValue({ session_id: "s", player_token: T });
    await startSession("game", "us");
    expect(api.post).toHaveBeenCalledWith("/tools/sessions", {
      kind: "game", mode: "us", first_touch: { utm_source: "share", utm_campaign: "game-us" },
    });
  });

  it("sends the player token as X-Tool-Token, and none when the device has none", async () => {
    api.post.mockResolvedValue({ saved: 1 });
    await saveAnswers("s", T, [{ question_key: "calendar", answer: "enoch" }], "wife");
    expect(api.post).toHaveBeenCalledWith(
      "/tools/sessions/s/answers",
      { answers: [{ question_key: "calendar", answer: "enoch" }], role: "wife" },
      { headers: { "X-Tool-Token": T } },
    );
    api.get.mockResolvedValue({});
    await getSession("s", null);
    expect(api.get).toHaveBeenCalledWith("/tools/sessions/s", undefined);
  });

  it("finishes, saves, joins and invites through their routes", async () => {
    api.post.mockResolvedValue({});
    await finishSession("s", T);
    await claimSession("s", T, "Daniel");
    await joinSession("inv", "Rivka");
    await sendInviteEmail("s", T, "rivka@example.org", { website: "" });
    expect(api.post.mock.calls.map((c) => c[0])).toEqual([
      "/tools/sessions/s/finish", "/tools/sessions/s/claim", "/tools/i/inv/players",
      "/tools/sessions/s/invite-email",
    ]);
    expect(api.post.mock.calls[1][1]).toEqual({ display: "Daniel" });
    expect(api.post.mock.calls[3][1]).toEqual({ email: "rivka@example.org", website: "" });
  });
});
```

Create `tests/lib/together-storage.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";

import {
  forgetSession,
  markFinished,
  readSessions,
  rememberSession,
  sessionById,
  sessionByInvite,
  unfinished,
} from "@/lib/together/storage";

const T = "t".repeat(32);

describe("Together device storage", () => {
  beforeEach(() => window.localStorage.clear());

  it("remembers, finds and forgets a session", () => {
    rememberSession({ sessionId: "a", token: T, kind: "game", mode: "us", seat: "owner" });
    expect(sessionById("a")?.token).toBe(T);
    forgetSession("a");
    expect(sessionById("a")).toBeNull();
  });

  it("offers the newest unfinished game or checklist to continue", () => {
    rememberSession({ sessionId: "a", token: T, kind: "game", mode: "me", seat: "owner" });
    rememberSession({ sessionId: "b", token: T, kind: "game", mode: "us", seat: "owner" });
    rememberSession({ sessionId: "c", token: T, kind: "checklist", mode: "couple", seat: "owner" });
    expect(unfinished("game")?.sessionId).toBe("b");
    markFinished("b");
    expect(unfinished("game")?.sessionId).toBe("a");
    expect(unfinished("checklist")?.sessionId).toBe("c");
  });

  it("finds the session an invite link already opened on this device", () => {
    rememberSession({ sessionId: "g", token: T, kind: "game", mode: "us", seat: "guest", invite: "inv" });
    expect(sessionByInvite("inv")?.sessionId).toBe("g");
  });

  it("survives broken storage", () => {
    window.localStorage.setItem("ahavah.together.v1", "{not json");
    expect(readSessions()).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/api-client-headers.test.ts tests/lib/together-api.test.ts tests/lib/together-storage.test.ts`
Expected: FAIL. The header test sees no `X-Tool-Token`; the other two fail on `Failed to resolve import "@/lib/together/api"` and `"@/lib/together/storage"`.

- [ ] **Step 3: Write the implementation**

In `src/lib/api-client.ts`, replace the head of `request`:

```ts
async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  payload?: unknown,
): Promise<T> {
  const url = path.startsWith("http") ? path : `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
```

with:

```ts
/** Extra request headers, such as Together's X-Tool-Token (TEC-1845). The
 *  session's Authorization is set after them, so a caller cannot replace
 *  it. */
export type RequestOptions = { headers?: Record<string, string> };

async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  payload?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    ...(options.headers ?? {}),
    "Content-Type": "application/json",
  };
  delete headers.Authorization;
```

and replace the `apiClient` object with:

```ts
export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("POST", path, body ?? {}, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("PUT", path, body ?? {}, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("PATCH", path, body ?? {}, options),
  delete: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>("DELETE", path, body, options),
  postMultipart,
};
```

In `src/lib/auth-otp.ts`, add `import type { ToolSource } from "@/lib/together/api";` and change the `checkOtp` options type to:

```ts
  opts?: {
    /** Acquisition tag stamped onto NEW onboardees only: the first
     *  checklist's old name or a Together tool's source (TEC-1845).
     *  Existing accounts are unaffected. */
    source?: "marriage_checklist" | ToolSource;
  },
```

Create `src/lib/together/api.ts`:

```ts
/**
 * Together's API calls (TEC-1845; ahavah-api service/api/tools_routes.py).
 * A player is the X-Tool-Token the device keeps (src/lib/together/storage);
 * a player who saved may also come back signed in, with no token. Answers
 * are read only through these calls by the players themselves.
 */
import { apiClient } from "@/lib/api-client";
import type { AntibotPayload } from "@/lib/antibot";
import { readFirstTouch } from "@/lib/first-touch";
import { firstTouchPayload } from "@/lib/onboarding-attribution";
import type { AreaKey, ArchetypeKey, RoundKey } from "@/lib/together/questions";

export type ToolKind = "game" | "checklist";
export type ToolMode = "me" | "us" | "knows_me" | "couple" | "single";
export type ToolSource = "tool:game-me" | "tool:game-us" | "tool:knows-me" | "tool:checklist";

export const SOURCE_OF: Record<ToolMode, ToolSource> = {
  me: "tool:game-me",
  us: "tool:game-us",
  knows_me: "tool:knows-me",
  couple: "tool:checklist",
  single: "tool:checklist",
};

export type AnswerValue = string | string[] | Record<string, unknown>;
export type MeResult = { archetype: ArchetypeKey; why: ArchetypeKey[] };
export type UsResult = {
  score: number;
  areas: Record<AreaKey, number>;
  align: AreaKey[];
  talk: AreaKey[];
  bars: { round: RoundKey; pct: number }[];
};
export type FriendResult = { right: number; total: number; place: number | null };
export type Stance = "agree" | "disagree" | "other";
export type ComparisonSide = {
  importance: number;
  stance?: Stance;
  frequency?: string;
  comment?: string;
  examples?: string[];
  other_note?: string;
};
export type ComparisonItem = {
  key: string;
  ref: string;
  owner: ComparisonSide;
  guest: ComparisonSide;
  tag?: "stance" | "importance";
};
export type OwnItem = {
  key: string;
  section: "nice-to-have" | "challenge";
  title: string;
  importance: number;
  stance?: Stance;
  frequency?: string;
  comment?: string;
};
export type Comparison = {
  agree: number;
  total: number;
  agree_items: ComparisonItem[];
  talk_items: ComparisonItem[];
  own: { owner: OwnItem[]; guest: OwnItem[] };
};
export type SingleResult = { top: { key: string; ref?: string; title?: string; importance: number }[] };
export type BoardRow = {
  player_id?: number;
  display: string;
  right: number;
  total: number;
  removed?: boolean;
  me?: boolean;
};
export type SessionView = {
  session_id: string;
  kind: ToolKind;
  mode: ToolMode;
  seat: "owner" | "guest";
  role: "husband" | "wife" | null;
  state: "playing" | "waiting" | "ready";
  claimed: boolean;
  member: boolean;
  share_token: string | null;
  invite_token: string | null;
  owner_display: string | null;
  guest_display: string | null;
  my_display: string | null;
  my_answers: Record<string, AnswerValue>;
  result: MeResult | UsResult | FriendResult | Comparison | SingleResult | null;
  board: BoardRow[] | null;
};
export type InviteInfo = {
  kind: ToolKind;
  mode: ToolMode;
  owner_display: string | null;
  state: "open" | "full" | "not_ready";
};
export type PublicSummary = {
  kind: ToolKind;
  mode: ToolMode;
  names: string[];
  state: "ready" | "waiting";
  score?: number;
  archetype?: ArchetypeKey;
  agree?: number;
  total?: number;
};
export type Started = { session_id: string; player_token: string };

function withToken(token: string | null) {
  return token ? { headers: { "X-Tool-Token": token } } : undefined;
}

export function startSession(kind: ToolKind, mode: ToolMode): Promise<Started> {
  return apiClient.post<Started>("/tools/sessions", {
    kind,
    mode,
    first_touch: firstTouchPayload(readFirstTouch()),
  });
}

export function saveAnswers(
  sessionId: string,
  token: string | null,
  answers: { question_key: string; answer: AnswerValue | null }[],
  role?: "husband" | "wife" | null,
): Promise<{ saved: number }> {
  return apiClient.post(`/tools/sessions/${sessionId}/answers`, { answers, ...(role ? { role } : {}) }, withToken(token));
}

export function finishSession(sessionId: string, token: string | null): Promise<SessionView> {
  return apiClient.post<SessionView>(`/tools/sessions/${sessionId}/finish`, {}, withToken(token));
}

export function getSession(sessionId: string, token: string | null): Promise<SessionView> {
  return apiClient.get<SessionView>(`/tools/sessions/${sessionId}`, withToken(token));
}

export function claimSession(sessionId: string, token: string | null, display: string): Promise<SessionView> {
  return apiClient.post<SessionView>(`/tools/sessions/${sessionId}/claim`, { display }, withToken(token));
}

export function getInvite(invite: string): Promise<InviteInfo> {
  return apiClient.get<InviteInfo>(`/tools/i/${invite}`);
}

export function joinSession(invite: string, display: string): Promise<Started> {
  return apiClient.post<Started>(`/tools/i/${invite}/players`, { display });
}

export async function sendInviteEmail(
  sessionId: string,
  token: string | null,
  email: string,
  antibot: AntibotPayload,
): Promise<void> {
  await apiClient.post(`/tools/sessions/${sessionId}/invite-email`, { email, ...antibot }, withToken(token));
}

export async function deleteSession(sessionId: string, token: string | null): Promise<void> {
  await apiClient.delete(`/tools/sessions/${sessionId}`, undefined, withToken(token));
}

export function removeFromBoard(sessionId: string, token: string | null, playerId: number): Promise<SessionView> {
  return apiClient.delete<SessionView>(`/tools/sessions/${sessionId}/players/${playerId}`, undefined, withToken(token));
}

export function restoreToBoard(sessionId: string, token: string | null, playerId: number): Promise<SessionView> {
  return apiClient.post<SessionView>(`/tools/sessions/${sessionId}/players/${playerId}/restore`, {}, withToken(token));
}

export async function countShareOpen(share: string): Promise<void> {
  try {
    await apiClient.post(`/tools/r/${share}/open`);
  } catch {
    // Counting is best-effort; a failure never shows.
  }
}

export function getStatus(): Promise<{ live: boolean; invite_email: boolean }> {
  return apiClient.get("/tools/status");
}
```

`AntibotPayload` (`src/lib/antibot.ts`) carries `website` and the stamp under the names `/request-otp` takes; check its fields and map them to the invite route's `website` and `signup_stamp` if they differ, so the test's `{ website: "" }` passes through unchanged.

Create `src/lib/together/storage.ts`:

```ts
/**
 * The Together sessions this device holds (TEC-1845): the player token is
 * the device's proof, so it is kept here and nowhere else. Read and
 * written defensively: storage can be full, blocked or hold an old shape.
 */
import type { ToolKind, ToolMode } from "@/lib/together/api";

const KEY = "ahavah.together.v1";
const KEEP = 20;

export type StoredSession = {
  sessionId: string;
  token: string;
  kind: ToolKind;
  mode: ToolMode;
  seat: "owner" | "guest";
  invite?: string;
  finished?: boolean;
  savedAt: number;
};

export function readSessions(): StoredSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((s) => s && typeof s.sessionId === "string") : [];
  } catch {
    return [];
  }
}

function write(list: StoredSession[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list.slice(0, KEEP)));
  } catch {
    /* private mode: this tab still works from memory */
  }
}

export function rememberSession(s: Omit<StoredSession, "savedAt">): void {
  const rest = readSessions().filter((x) => x.sessionId !== s.sessionId);
  write([{ ...s, savedAt: Date.now() }, ...rest]);
}

export function markFinished(sessionId: string): void {
  write(readSessions().map((s) => (s.sessionId === sessionId ? { ...s, finished: true } : s)));
}

export function forgetSession(sessionId: string): void {
  write(readSessions().filter((s) => s.sessionId !== sessionId));
}

export function sessionById(id: string): StoredSession | null {
  return readSessions().find((s) => s.sessionId === id) ?? null;
}

export function sessionByInvite(invite: string): StoredSession | null {
  return readSessions().find((s) => s.invite === invite) ?? null;
}

export function unfinished(kind: ToolKind): StoredSession | null {
  return readSessions().find((s) => s.kind === kind && s.seat === "owner" && !s.finished) ?? null;
}
```

Create `src/lib/together/status.ts`:

```ts
/**
 * Whether Together is live (TEC-1845), for server components. The API's
 * together_live switch keeps it dark until launch; when the API cannot be
 * read the answer is dark too, so a page never offers what cannot work.
 */
import { fetchPublicSummary } from "@/lib/share-image/summary";

export type TogetherStatus = { live: boolean; inviteEmail: boolean };

export async function togetherStatus(): Promise<TogetherStatus> {
  const status = await fetchPublicSummary("/tools/status", (raw) => {
    if (!raw || typeof raw !== "object") return null;
    const r = raw as { live?: unknown; invite_email?: unknown };
    return typeof r.live === "boolean" ? { live: r.live, inviteEmail: r.invite_email === true } : null;
  });
  return status ?? { live: false, inviteEmail: false };
}
```

`src/lib/together/questions.ts` does not exist until Task 16; until then the type import in `api.ts` fails to compile. Create it now with only the three types it needs, which Task 16 fills in:

```ts
export type RoundKey = "sabbath" | "feasts" | "family" | "home" | "moving" | "talk";
export type AreaKey =
  | "calendar" | "observance" | "feast" | "family" | "lifestyle" | "relocation" | "language" | "communication";
export type ArchetypeKey = "sabbath" | "feast" | "family" | "builder" | "student" | "peace" | "explorer" | "bridge";
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/api-client-headers.test.ts tests/lib/together-api.test.ts tests/lib/together-storage.test.ts tests/lib/api-client-expired.test.ts tests/lib/auth-otp.test.ts`
Expected: PASS (2, 4 and 4 new; the two existing suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/api-client.ts src/lib/auth-otp.ts src/lib/together/api.ts src/lib/together/storage.ts src/lib/together/status.ts src/lib/together/questions.ts tests/lib/api-client-headers.test.ts tests/lib/together-api.test.ts tests/lib/together-storage.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the API calls with a device token, device storage and the live check" -m "Refs: TEC-1845"
```

---

### Task 16: The questions, answers to profile, "You in a sentence", share text, and the scoring parity test

**Files:**
- Modify: `src/lib/together/questions.ts` (fill in)
- Create: `src/lib/together/profile.ts`, `src/lib/together/sentence.ts`, `src/lib/together/share.ts`
- Test: `tests/lib/together-scoring-parity.test.ts`, `tests/lib/together-questions.test.ts` (create)

**Interfaces:**
- Consumes: `computeCompatibility`, `BALANCED` (`src/lib/scoring`); `Profile` (`src/lib/profile-schema.ts`); the API's fixture `../ahavah-api/tests/fixtures/together_scoring_cases.json` (Task 3).
- Produces:
  - `questions.ts`: `ROUNDS: { key: RoundKey; name: string; intro: string }[]`, `GAME_QUESTIONS: GameQuestion[]` with `{ key, round, text, options: { key, label }[], multi?, light?, longList? }` (the keys of Task 3's table), `AREA_LABELS: Record<AreaKey, string>`, `BAR_LABELS: Record<RoundKey, string>`, `ARCHETYPES: Record<ArchetypeKey, { name: string; line: string; why: string }>`, `COPY` (the game's export strings).
  - `profile.ts`: `GAME_WEIGHTS` (`BALANCED` with `polygyny: 0`), `answersToProfile(answers) -> Partial<Profile>`.
  - `sentence.ts`: `youInASentence(answers) -> string | null`.
  - `share.ts`: `SITE`, `shareUrl(shareToken, source)`, `inviteUrl(inviteToken)`, `shareText(summary-like)`, `inviteShareText(kind, link)`.

The app's compatibility pill keeps `BALANCED` (owner decision 8): `GAME_WEIGHTS` is a new object, and nothing in `src/lib/scoring/` changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/together-scoring-parity.test.ts`:

```ts
// @vitest-environment node
//
// Together (TEC-1845): the API's Python port and this engine must give the
// same score for the same answers. Both read the API's fixture; its twin
// is ahavah-api tests/test_together_scoring.py. The checkouts sit side by
// side under /d/Antigravity.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import type { Profile } from "@/lib/profile-schema";
import { computeCompatibility } from "@/lib/scoring/compute-compatibility";
import { BALANCED } from "@/lib/scoring/weights";
import { GAME_WEIGHTS, answersToProfile } from "@/lib/together/profile";

const FIXTURE = resolve(process.cwd(), "../ahavah-api/tests/fixtures/together_scoring_cases.json");
type Case = {
  name: string;
  owner: Record<string, string | string[]>;
  guest: Record<string, string | string[]>;
  score: number;
  reversed_score?: number;
  breakdown: Record<string, number>;
};
const cases: Case[] = existsSync(FIXTURE) ? JSON.parse(readFileSync(FIXTURE, "utf8")).cases : [];

describe.skipIf(cases.length === 0)("scoring parity with the API", () => {
  it.each(cases.map((c) => [c.name, c] as const))("scores the %s case as the API does", (_name, c) => {
    const a = answersToProfile(c.owner) as Profile;
    const b = answersToProfile(c.guest) as Profile;
    const r = computeCompatibility(a, b, GAME_WEIGHTS);
    expect(r.score).toBe(c.score);
    for (const [axis, want] of Object.entries(c.breakdown)) {
      expect(r.breakdown[axis as keyof typeof r.breakdown]).toBeCloseTo(want, 9);
    }
    if (c.reversed_score !== undefined) {
      expect(computeCompatibility(b, a, GAME_WEIGHTS).score).toBe(c.reversed_score);
    }
  });

  it("scores a player who skipped almost everything", () => {
    const c = cases.find((x) => x.name === "partial")!;
    expect(answersToProfile(c.owner)).toEqual({ calendar: "luni-solar" });
    expect(computeCompatibility(answersToProfile(c.owner) as Profile, answersToProfile(c.guest) as Profile, GAME_WEIGHTS).score).toBe(41);
  });
});

describe("the game's weights", () => {
  it("give plural marriage weight 0 and leave the app's pill alone", () => {
    expect(GAME_WEIGHTS.polygyny).toBe(0);
    expect(BALANCED.polygyny).toBe(1);
    expect({ ...GAME_WEIGHTS, polygyny: 1 }).toEqual(BALANCED);
  });
});
```

Create `tests/lib/together-questions.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ARCHETYPES, AREA_LABELS, BAR_LABELS, GAME_QUESTIONS, ROUNDS } from "@/lib/together/questions";
import { inviteShareText, inviteUrl, shareText, shareUrl } from "@/lib/together/share";
import { youInASentence } from "@/lib/together/sentence";

const API_KEYS = [
  "calendar", "torah-walk", "sabbath-afternoon", "spring-feasts", "autumn-feasts", "favourite-feast",
  "has-children", "children-hope", "city-or-country", "homestead", "community", "sabbath-host",
  "country", "move", "languages", "pace", "talk-how",
];

describe("the game's questions", () => {
  it("are the API's keys in the API's order, 14 scored and 3 just for fun", () => {
    expect(GAME_QUESTIONS.map((q) => q.key)).toEqual(API_KEYS);
    expect(GAME_QUESTIONS.filter((q) => q.light).map((q) => q.key)).toEqual([
      "sabbath-afternoon", "favourite-feast", "sabbath-host",
    ]);
    expect(ROUNDS.map((r) => r.name)).toEqual([
      "Sabbath and calendar", "The feasts", "Family and children", "Home and roles",
      "Moving and language", "How we talk and decide",
    ]);
  });

  it("use the export's words and the feasts' biblical English names", () => {
    const spring = GAME_QUESTIONS.find((q) => q.key === "spring-feasts")!;
    expect(spring.text).toBe("Which spring feasts do you keep?");
    expect(spring.options.map((o) => o.label)).toEqual(["Passover", "Unleavened Bread", "First Fruits", "Pentecost"]);
    const autumn = GAME_QUESTIONS.find((q) => q.key === "autumn-feasts")!;
    expect(autumn.options.map((o) => o.label)).toEqual(["Feast of Trumpets", "Day of Atonement", "Tabernacles"]);
    expect(GAME_QUESTIONS.find((q) => q.key === "talk-how")!.options.map((o) => o.label)).toEqual([
      "Video calls", "Messages", "In person",
    ]);
  });

  it("never mention plural marriage or dating", () => {
    const text = JSON.stringify({ GAME_QUESTIONS, ROUNDS, ARCHETYPES, AREA_LABELS, BAR_LABELS });
    expect(text).not.toMatch(/polyg|plural|another wife|dating|\u2014/i);
  });

  it("label 8 areas, 6 bars and 8 archetypes as the export does", () => {
    expect(Object.values(AREA_LABELS)).toEqual([
      "Calendar", "Torah walk", "The feasts", "Children", "Home", "Moving", "Language", "How you talk",
    ]);
    expect(Object.values(BAR_LABELS)).toEqual(["Calendar", "The feasts", "Children", "Home", "Moving", "How you talk"]);
    expect(ARCHETYPES.feast).toEqual({
      name: "The Feast Host",
      line: "You look forward to every appointed time and want a full table at each one.",
      why: "The feasts",
    });
  });
});

describe("You in a sentence", () => {
  it("writes the export's example from its answers", () => {
    expect(youInASentence({
      "spring-feasts": ["passover"], "autumn-feasts": ["sukkot"], "children-hope": "large-family",
      move: "international-open",
    })).toBe("You keep the spring and autumn feasts, hope for a large family and would move countries for the right marriage.");
  });

  it("joins two parts with and, and says nothing when there is nothing to say", () => {
    expect(youInASentence({ "spring-feasts": ["passover"], move: "local-only" }))
      .toBe("You keep the spring feasts and want to stay where you are.");
    expect(youInASentence({ calendar: "enoch" })).toBeNull();
  });
});

describe("share text and links", () => {
  it("tags a share link so the visit is credited to the share", () => {
    expect(shareUrl("abc", "tool:game-us")).toBe(
      "https://ahavah.app/tools/r/abc?utm_source=share&utm_medium=together&utm_campaign=game-us",
    );
    expect(inviteUrl("inv")).toBe("https://ahavah.app/tools/i/inv");
  });

  it("uses the export's share text, the score and the archetype in slots", () => {
    expect(shareText({ mode: "us", score: 82 })).toBe(
      "We are 82% aligned on Ahavah. How well do you fit with someone? ahavah.app/together",
    );
    expect(shareText({ mode: "me", archetype: "feast" })).toBe("I am The Feast Host. Which kind are you? ahavah.app/together");
    expect(shareText({ mode: "knows_me" })).toBe("How well do you know me? Play at ahavah.app/together");
    expect(inviteShareText("game", "https://ahavah.app/tools/i/x")).toBe(
      "I played Ahavah’s compatibility game. Want to see how we fit? https://ahavah.app/tools/i/x",
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-scoring-parity.test.ts tests/lib/together-questions.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/together/profile"` and `"@/lib/together/share"`.

- [ ] **Step 3: Write the implementation**

Replace `src/lib/together/questions.ts` with:

```ts
/**
 * The compatibility game's questions and words (TEC-1845). Keys mirror
 * ahavah-api service/tools/questions.py, in the same order; the words are
 * the Claude Design export's (handoff/copy/07-together.md, sections 3
 * and 4) and the brief's question table, for the export draws only some
 * questions. Each scored question fills a profile field the scoring engine
 * reads (src/lib/together/profile.ts). No question, area, bar or
 * archetype about plural marriage.
 */
export type RoundKey = "sabbath" | "feasts" | "family" | "home" | "moving" | "talk";
export type AreaKey =
  | "calendar" | "observance" | "feast" | "family" | "lifestyle" | "relocation" | "language" | "communication";
export type ArchetypeKey = "sabbath" | "feast" | "family" | "builder" | "student" | "peace" | "explorer" | "bridge";
export type Option = { key: string; label: string };
export type GameQuestion = {
  key: string;
  round: RoundKey;
  text: string;
  options: Option[];
  multi?: boolean;
  light?: boolean;
  longList?: "country" | "language";
};

// Only "The feasts" has its intro in the export (3.1). The other 5 are
// this plan's, for the copy pass and the owner (plan, Spec conflicts 3).
export const ROUNDS: ReadonlyArray<{ key: RoundKey; name: string; intro: string }> = [
  { key: "sabbath", name: "Sabbath and calendar", intro: "How you count the days, and where you are in your walk." },
  { key: "feasts", name: "The feasts", intro: "Which appointed times you keep, and the one you wait for all year." },
  { key: "family", name: "Family and children", intro: "The children you have, and the home you hope to fill." },
  { key: "home", name: "Home and roles", intro: "Where you want to live, and who sets the Sabbath table." },
  { key: "moving", name: "Moving and language", intro: "Where you live now, how far you would go and what you speak." },
  { key: "talk", name: "How we talk and decide", intro: "How fast, how often and how you like to talk." },
];

const o = (key: string, label: string): Option => ({ key, label });
const FEASTS: Option[] = [
  o("passover", "Passover"), o("unleavened-bread", "Unleavened Bread"), o("first-fruits", "First Fruits"),
  o("shavuot", "Pentecost"), o("trumpets", "Feast of Trumpets"), o("yom-kippur", "Day of Atonement"),
  o("sukkot", "Tabernacles"),
];

export const GAME_QUESTIONS: ReadonlyArray<GameQuestion> = [
  { key: "calendar", round: "sabbath", text: "Which calendar sets your Sabbaths and feasts?", options: [
    o("rabbinic", "Rabbinic"), o("aviv-barley", "Aviv barley"), o("enoch", "Enoch"), o("luni-solar", "Luni-solar"),
    o("observational-new-moon", "Observational new moon"), o("other", "Other")] },
  { key: "torah-walk", round: "sabbath", text: "Where are you in your Torah walk?", options: [
    o("learning", "Learning"), o("beginner", "Beginner"), o("intermediate", "Intermediate"), o("experienced", "Experienced")] },
  { key: "sabbath-afternoon", round: "sabbath", light: true, text: "Your ideal Sabbath afternoon", options: [
    o("walk", "A long walk"), o("guests", "A table full of guests"), o("study", "Study and a rest"), o("quiet", "Quiet at home")] },
  { key: "spring-feasts", round: "feasts", multi: true, text: "Which spring feasts do you keep?", options: FEASTS.slice(0, 4) },
  { key: "autumn-feasts", round: "feasts", multi: true, text: "Which autumn feasts do you keep?", options: FEASTS.slice(4) },
  { key: "favourite-feast", round: "feasts", light: true, text: "The feast you look forward to most", options: FEASTS },
  { key: "has-children", round: "family", text: "Do you have children?", options: [o("yes", "Yes"), o("no", "No")] },
  { key: "children-hope", round: "family", text: "Children in the home you hope to build?", options: [
    o("yes", "Yes"), o("open-to-more", "Open to more"), o("large-family", "A large family"),
    o("blended", "Open to a blended family"), o("no", "No")] },
  { key: "city-or-country", round: "home", text: "City or country?", options: [o("city", "City"), o("country", "Country")] },
  { key: "homestead", round: "home", text: "A homestead or off the grid?", options: [
    o("homestead", "A homestead"), o("off-grid", "Off the grid"), o("neither", "Neither")] },
  { key: "community", round: "home", text: "Would you live in community with other believers?", options: [
    o("yes", "Yes"), o("no", "No")] },
  { key: "sabbath-host", round: "home", light: true, text: "Who hosts the Sabbath meal?", options: [
    o("me", "Me"), o("spouse", "My spouse"), o("both", "Both of us"), o("less-tired", "Whoever is less tired")] },
  { key: "country", round: "moving", longList: "country", text: "Which country do you live in?", options: [] },
  { key: "move", round: "moving", text: "Would you move for marriage?", options: [
    o("will-relocate", "I would move"), o("wants-partner-willing", "I hope my spouse would"),
    o("local-only", "I want to stay where I am"), o("international-open", "Open to another country")] },
  { key: "languages", round: "moving", multi: true, longList: "language", text: "Which languages do you speak?", options: [] },
  { key: "pace", round: "talk", text: "How fast would you like courtship to go?", options: [
    o("frequent", "Talk often"), o("slow-paced-courtship", "Slow and careful")] },
  { key: "talk-how", round: "talk", multi: true, text: "How do you like to talk?", options: [
    o("video-calls", "Video calls"), o("texting", "Messages"), o("in-person", "In person")] },
];

export const AREA_LABELS: Record<AreaKey, string> = {
  calendar: "Calendar",
  observance: "Torah walk",
  feast: "The feasts",
  family: "Children",
  lifestyle: "Home",
  relocation: "Moving",
  language: "Language",
  communication: "How you talk",
};

export const BAR_LABELS: Record<RoundKey, string> = {
  sabbath: "Calendar",
  feasts: "The feasts",
  family: "Children",
  home: "Home",
  moving: "Moving",
  talk: "How you talk",
};

export const ARCHETYPES: Record<ArchetypeKey, { name: string; line: string; why: string }> = {
  sabbath: { name: "The Sabbath Keeper", line: "Your week turns on the Sabbath, and you want a home that rests with you.", why: "Sabbath and calendar" },
  feast: { name: "The Feast Host", line: "You look forward to every appointed time and want a full table at each one.", why: "The feasts" },
  family: { name: "The Family Founder", line: "Children and a busy home are at the centre of what you hope to build.", why: "Family and children" },
  builder: { name: "The Steady Builder", line: "You know the home you want, town or land, and you are building towards it.", why: "Home" },
  student: { name: "The Faithful Student", line: "You are growing in Torah and want a spouse who will study alongside you.", why: "Torah walk" },
  peace: { name: "The Peacemaker", line: "You talk things through, gently and often, and want a spouse who will too.", why: "How we talk" },
  explorer: { name: "The Explorer", line: "You would cross a border for the right marriage, and you say so plainly.", why: "Moving" },
  bridge: { name: "The Bridge Builder", line: "You carry more than one language and want a home where both families feel welcome.", why: "Language" },
};

/** The game's strings, word for word from the export. */
export const COPY = {
  roundLabel: (n: number, name: string) => `Round ${n} of 6, ${name}`,
  roundOf: (n: number) => `Round ${n} of 6`,
  pickEvery: "Pick every one that fits.",
  pickAtLeastOne: "Pick at least one, or skip",
  justForFun: "Just for fun",
  back: "Back",
  skip: "Skip this one",
  next: "Next",
  begin: "Begin",
  seeResult: "See my result",
  notSaved: "Not saved. Check your connection.",
  retry: "Retry",
  guessing: (name: string) => `What would ${name} say?`,
  startFailed: "We could not start the game. Try again.",
  leave: "Leave the game",
};
```

Create `src/lib/together/profile.ts`:

```ts
/**
 * Game answers as profile fields (TEC-1845). The twin of ahavah-api
 * service/tools/scoring.answers_to_profile: change both, and the shared
 * fixture, together. A skipped question leaves its field out, so the
 * engine scores it as it scores an empty profile field. Light questions
 * fill nothing. Also what "Find people who answered like you" carries into
 * sign-up (src/lib/together/carry.ts).
 */
import type {
  Calendar, CommunicationPref, FamilyView, FeastDay, LivingPreference, Profile, Relocation, TorahLevel,
} from "@/lib/profile-schema";
import { BALANCED, type Weights } from "@/lib/scoring/weights";

/** BALANCED with plural marriage at 0. The app's pill keeps BALANCED. */
export const GAME_WEIGHTS: Weights = { ...BALANCED, polygyny: 0 };

const CHILDREN_HOPE: Record<string, FamilyView> = {
  yes: "wants-children",
  "open-to-more": "open-to-more",
  "large-family": "interested-large-family",
  blended: "open-blended",
  no: "does-not-want",
};

type Answers = Record<string, unknown>;
const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);
const list = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

export function answersToProfile(answers: Answers): Partial<Profile> {
  const p: Partial<Profile> = {};
  if (str(answers.calendar)) p.calendar = answers.calendar as Calendar;
  if (str(answers["torah-walk"])) p.torahLevel = answers["torah-walk"] as TorahLevel;
  const feasts = [...list(answers["spring-feasts"]), ...list(answers["autumn-feasts"])];
  if (feasts.length) p.feastDays = feasts as FeastDay[];
  const family: FamilyView[] = [];
  if (answers["has-children"] === "yes") family.push("has-children");
  const hope = str(answers["children-hope"]);
  if (hope && CHILDREN_HOPE[hope]) family.push(CHILDREN_HOPE[hope]);
  if (family.length) p.familyViews = family;
  const living: LivingPreference[] = [];
  if (answers["city-or-country"] === "city") living.push("urban");
  else if (answers["city-or-country"] === "country") living.push("rural");
  if (answers.homestead === "homestead" || answers.homestead === "off-grid") living.push(answers.homestead);
  if (answers.community === "yes") living.push("community-living");
  if (living.length) p.livingPreferences = living;
  if (str(answers.country)) p.country = answers.country as string;
  if (str(answers.move)) p.relocation = answers.move as Relocation;
  if (list(answers.languages).length) p.languages = list(answers.languages);
  const comm = [...(str(answers.pace) ? [answers.pace as string] : []), ...list(answers["talk-how"])];
  if (comm.length) p.communicationPrefs = comm as CommunicationPref[];
  return p;
}
```

Create `src/lib/together/sentence.ts`:

```ts
/**
 * "You in a sentence" on the Me result (TEC-1845; export 4.1). Built on the
 * device from the player's own answers and shown only there, never on an
 * image or a shared page. The export gives one example; the other parts
 * follow its pattern and go through the copy pass (plan, Spec conflicts 3).
 */
type Answers = Record<string, unknown>;

const FAMILY: Record<string, string> = {
  "large-family": "hope for a large family",
  yes: "hope for children",
  "open-to-more": "are open to more children",
  blended: "are open to a blended family",
  no: "do not hope for children",
};
const MOVE: Record<string, string> = {
  "international-open": "would move countries for the right marriage",
  "will-relocate": "would move for the right marriage",
  "wants-partner-willing": "hope your spouse would move",
  "local-only": "want to stay where you are",
};

export function youInASentence(answers: Answers): string | null {
  const spring = Array.isArray(answers["spring-feasts"]) && answers["spring-feasts"].length > 0;
  const autumn = Array.isArray(answers["autumn-feasts"]) && answers["autumn-feasts"].length > 0;
  const parts: string[] = [];
  if (spring && autumn) parts.push("keep the spring and autumn feasts");
  else if (spring) parts.push("keep the spring feasts");
  else if (autumn) parts.push("keep the autumn feasts");
  const hope = answers["children-hope"];
  if (typeof hope === "string" && FAMILY[hope]) parts.push(FAMILY[hope]);
  const move = answers.move;
  if (typeof move === "string" && MOVE[move]) parts.push(MOVE[move]);
  if (parts.length === 0) return null;
  const joined = parts.length === 1 ? parts[0]
    : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `You ${joined}.`;
}
```

Create `src/lib/together/share.ts`:

```ts
/**
 * Share links and share text (TEC-1845). Links carry utm tags so
 * first-touch capture credits a visit to the share (utm:share/{tool}). The
 * texts are the export's (5.9, 4.11, 9.2) with the score or archetype in a
 * slot; the checklist's two are this plan's (Spec conflicts 3).
 */
import type { ToolKind, ToolMode, ToolSource } from "@/lib/together/api";
import { ARCHETYPES, type ArchetypeKey } from "@/lib/together/questions";

export const SITE = "https://ahavah.app";

export function shareUrl(shareToken: string, source: ToolSource): string {
  const campaign = source.replace(/^tool:/, "");
  return `${SITE}/tools/r/${shareToken}?utm_source=share&utm_medium=together&utm_campaign=${campaign}`;
}

export function inviteUrl(inviteToken: string): string {
  return `${SITE}/tools/i/${inviteToken}`;
}

export function shareText(s: { mode: ToolMode; score?: number; archetype?: ArchetypeKey; agree?: number; total?: number }): string {
  switch (s.mode) {
    case "us":
      return `We are ${s.score}% aligned on Ahavah. How well do you fit with someone? ahavah.app/together`;
    case "me":
      return `I am ${ARCHETYPES[s.archetype ?? "sabbath"].name}. Which kind are you? ahavah.app/together`;
    case "knows_me":
      return "How well do you know me? Play at ahavah.app/together";
    case "couple":
      // Not in the export: the spec's progress line with the address.
      return `We completed the Ahavah marriage checklist: ${s.agree} of ${s.total} in agreement. ahavah.app/marriage-checklist`;
    case "single":
      // Not in the export: the share image's line with the address.
      return "I wrote my non-negotiables. ahavah.app/marriage-checklist";
  }
}

export function inviteShareText(kind: ToolKind, link: string): string {
  return kind === "game"
    ? `I played Ahavah’s compatibility game. Want to see how we fit? ${link}`
    // Not in the export: the checklist invite's share text.
    : `Will you take the Ahavah marriage checklist with me? ${link}`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-scoring-parity.test.ts tests/lib/together-questions.test.ts tests/lib/scoring`
Expected: PASS (6 parity tests with the fixture present, 8 question tests; the scoring suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/together/questions.ts src/lib/together/profile.ts src/lib/together/sentence.ts src/lib/together/share.ts tests/lib/together-scoring-parity.test.ts tests/lib/together-questions.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the game's questions, answers to profile and share text, scored as the API scores them" -m "Refs: TEC-1845"
```

---

### Task 17: The share images: fonts and the 5 templates

**Files:**
- Add: `src/lib/share-image/fonts/Ultra-Regular.ttf` (from `Claude Design/Ultra.zip`), `src/lib/share-image/fonts/PlusJakartaSans-800.woff`, `PlusJakartaSans-600.woff` (from `node_modules/@fontsource/plus-jakarta-sans/files/plus-jakarta-sans-latin-800-normal.woff` and `-600-`), `src/lib/share-image/fonts/OFL-Ultra.txt`, `OFL-PlusJakartaSans.txt` (their licences)
- Create: `src/lib/share-image/fonts.ts`, `src/lib/share-image/together-templates.tsx`
- Modify: `src/lib/share-image/render.tsx` (`fonts`), `src/lib/share-image/templates.tsx` (register)
- Test: `tests/lib/together-share-images.test.ts` (create)

**Interfaces:**
- Consumes: `renderShareImage`, `SHARE_SIZES`, `SHARE_TEMPLATES`, `AhavahMark` (growth foundations Task 13); `ARCHETYPES` (Task 16).
- Produces: `loadShareFonts(): Promise<ShareFont[]>`; `renderShareImage({ template, size, data, fonts? })`; templates `together-me` (`data.archetype`), `together-us` (`data.names: [a, b]`, `data.score`), `together-knows` (`data.name`), `together-couple` (`data.agree`, `data.total`), `together-single` (no data), each drawn for `link` (1200 by 630) and `story` (1080 by 1920) from the width and height they are given.

Transcribed from `pages/p07b-share-images.js` and `kit/ahv-arch.js`: navy `#1A1340` with the violet glow for the 4 single-colourway templates; Me in its archetype's colourway with its motif; the foot is the Ahavah mark and "ahavah.app/together"; story content sits between 250 px from the top and 340 px from the bottom (the export's safe area, whose red guides are not part of the image). Only "Who knows me best, invitation" is built (owner decision 7); the "names the top friend" template is not.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/together-share-images.test.ts`:

```ts
// @vitest-environment node
//
// Together's share images (TEC-1845): 5 templates, each at the link
// preview and the story size, with the brand's fonts. None reads an
// answer: each takes only the summary's names and headline number.
import { describe, expect, it } from "vitest";

import { loadShareFonts } from "@/lib/share-image/fonts";
import { renderShareImage } from "@/lib/share-image/render";
import { SHARE_SIZES } from "@/lib/share-image/sizes";
import { SHARE_TEMPLATES, templateFor } from "@/lib/share-image/templates";
import { ARCHETYPE_STYLE } from "@/lib/share-image/together-templates";

const CASES: [string, Record<string, unknown>][] = [
  ["together-me", { archetype: "bridge" }],
  ["together-us", { names: ["Anastasia-Marie", "Bartholomew"], score: 0 }],
  ["together-us", { names: ["R.", "D."], score: 100 }],
  ["together-knows", { name: "Eli" }],
  ["together-couple", { agree: 18, total: 22 }],
  ["together-single", {}],
];

describe("Together share images", () => {
  it("are registered by the names the routes ask for", () => {
    for (const name of ["together-me", "together-us", "together-knows", "together-couple", "together-single"]) {
      expect(SHARE_TEMPLATES[name]).toBeDefined();
      expect(templateFor(name)).toBe(SHARE_TEMPLATES[name]);
    }
  });

  it.each(CASES)("%s renders at both sizes with the brand fonts", async (template, data) => {
    const fonts = await loadShareFonts();
    expect(fonts.map((f) => `${f.name} ${f.weight}`)).toEqual(["Ultra 400", "Plus Jakarta Sans 800", "Plus Jakarta Sans 600"]);
    for (const size of ["link", "story"] as const) {
      const res = renderShareImage({ template, size, data, fonts });
      const bytes = Buffer.from(await res.arrayBuffer());
      expect(bytes.readUInt32BE(16)).toBe(SHARE_SIZES[size].width);
      expect(bytes.readUInt32BE(20)).toBe(SHARE_SIZES[size].height);
    }
  });

  it("draws Me in its archetype's colourway, as the 8 archetype cards are", () => {
    const element = templateFor("together-me")({ size: SHARE_SIZES.link, data: { archetype: "explorer" } });
    expect((element.props as { style: { background: string } }).style.background).toBe(ARCHETYPE_STYLE.explorer.bg);
    expect(ARCHETYPE_STYLE.explorer.bg).toBe("#FF4566");
  });

  it("never names a friend on the knows-me image", () => {
    const element = templateFor("together-knows")({ size: SHARE_SIZES.story, data: { name: "Rivka", top: "Hannah" } });
    expect(JSON.stringify(element)).not.toContain("Hannah");
    expect(JSON.stringify(element)).toContain("How well do you know ");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-share-images.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/share-image/fonts"`.

- [ ] **Step 3: Add the font files**

Run:
```bash
cd /d/Antigravity/ahavah-web
mkdir -p src/lib/share-image/fonts
unzip -o -j "Claude Design/Ultra.zip" Ultra-Regular.ttf LICENSE.txt -d src/lib/share-image/fonts
mv src/lib/share-image/fonts/LICENSE.txt src/lib/share-image/fonts/OFL-Ultra.txt
cp node_modules/@fontsource/plus-jakarta-sans/files/plus-jakarta-sans-latin-800-normal.woff src/lib/share-image/fonts/PlusJakartaSans-800.woff
cp node_modules/@fontsource/plus-jakarta-sans/files/plus-jakarta-sans-latin-600-normal.woff src/lib/share-image/fonts/PlusJakartaSans-600.woff
cp node_modules/@fontsource/plus-jakarta-sans/LICENSE src/lib/share-image/fonts/OFL-PlusJakartaSans.txt
ls -l src/lib/share-image/fonts
```
Expected: the 5 files listed; the 3 font files together under 200 KB, well inside the 500 KB image bundle cap. If `@fontsource/plus-jakarta-sans/LICENSE` has another name, copy the licence file that package ships.

- [ ] **Step 4: Write the implementation**

Create `src/lib/share-image/fonts.ts`:

```ts
/**
 * The brand's fonts for share images (TEC-1845): Ultra for display, Plus
 * Jakarta Sans for text (SIL Open Font Licence, files beside this one).
 * ImageResponse takes ttf, otf or woff, read from disk at request time as
 * the Next docs show (process.cwd() is the project root). Read once per
 * server instance.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";

export type ShareFont = { name: string; data: ArrayBuffer; weight: 400 | 600 | 800; style: "normal" };

const toArrayBuffer = (b: Buffer): ArrayBuffer =>
  b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;

let cached: Promise<ShareFont[]> | null = null;

export function loadShareFonts(): Promise<ShareFont[]> {
  cached ??= (async () => {
    const dir = join(process.cwd(), "src/lib/share-image/fonts");
    const [ultra, bold, semi] = await Promise.all([
      readFile(join(dir, "Ultra-Regular.ttf")),
      readFile(join(dir, "PlusJakartaSans-800.woff")),
      readFile(join(dir, "PlusJakartaSans-600.woff")),
    ]);
    return [
      { name: "Ultra", data: toArrayBuffer(ultra), weight: 400, style: "normal" },
      { name: "Plus Jakarta Sans", data: toArrayBuffer(bold), weight: 800, style: "normal" },
      { name: "Plus Jakarta Sans", data: toArrayBuffer(semi), weight: 600, style: "normal" },
    ];
  })();
  return cached;
}
```

In `src/lib/share-image/render.tsx`, add `import type { ShareFont } from "@/lib/share-image/fonts";` and replace `renderShareImage` with:

```tsx
export function renderShareImage({
  template,
  size,
  data = {},
  fonts,
}: {
  template: string;
  size: ShareSizeName;
  data?: Record<string, unknown>;
  fonts?: ShareFont[];
}): ImageResponse {
  const dims = SHARE_SIZES[size];
  // Called as a function so the renderer is handed plain elements.
  const element = templateFor(template)({ size: dims, data });
  return new ImageResponse(element, {
    ...dims,
    ...(fonts ? { fonts } : {}),
    headers: { "Cache-Control": SHARE_IMAGE_CACHE },
  });
}
```

Create `src/lib/share-image/together-templates.tsx`:

```tsx
// Satori reads JSX as a layout description; inline style is its API.
/* eslint-disable no-restricted-syntax */
/**
 * Together's share images (TEC-1845), transcribed from the Claude Design
 * export: pages/p07b-share-images.js (layout, sizes, words) and
 * kit/ahv-arch.js (the 8 archetype colourways and motifs). Every value is
 * a slot. None shows an answer: each template reads only the public
 * summary's names and headline number, and the knows-me template never
 * names a friend (owner decision 7). The images are not themed.
 */
import type { ReactElement } from "react";

import { AhavahMark } from "@/lib/share-image/mark";
import type { ShareTemplate } from "@/lib/share-image/templates";
import { ARCHETYPES, type ArchetypeKey } from "@/lib/together/questions";

const BG = "#1A1340";
const LIME = "#D7FF81";
const DISPLAY = "Ultra";
const TEXT = "Plus Jakarta Sans";

type Style = { key: ArchetypeKey; bg: string; ink: string; acc: string };

export const ARCHETYPE_STYLE: Record<ArchetypeKey, Style> = {
  sabbath: { key: "sabbath", bg: "#1A1340", ink: "#FFFFFF", acc: "#D7FF81" },
  feast: { key: "feast", bg: "#5524F5", ink: "#FFFFFF", acc: "#D7FF81" },
  family: { key: "family", bg: "#D7FF81", ink: "#0F0B1F", acc: "#5524F5" },
  builder: { key: "builder", bg: "#FBF9F4", ink: "#0F0B1F", acc: "#5524F5" },
  student: { key: "student", bg: "#EFE5FF", ink: "#0F0B1F", acc: "#5524F5" },
  peace: { key: "peace", bg: "#0F0B1F", ink: "#FFFFFF", acc: "#BC96FF" },
  explorer: { key: "explorer", bg: "#FF4566", ink: "#0F0B1F", acc: "#FFFFFF" },
  bridge: { key: "bridge", bg: "#2B1B6B", ink: "#FFFFFF", acc: "#FF8AA0" },
};

function motif(a: Style, size: number): ReactElement {
  const s = a.ink;
  const c = a.acc;
  const op = 0.32;
  const w = 10;
  const els: ReactElement[] = [];
  if (a.key === "sabbath") {
    for (let i = 0; i < 7; i++) {
      const x = 46 + i * 51;
      const last = i === 6;
      els.push(<line key={i} x1={x} y1={last ? 60 : 110} x2={x} y2={last ? 340 : 290} stroke={last ? c : s} strokeOpacity={last ? 1 : op} strokeWidth={last ? 16 : w} strokeLinecap="round" />);
    }
  } else if (a.key === "feast") {
    [90, 150, 210].forEach((r, i) => els.push(<path key={r} d={`M${200 - r} 330 A${r} ${r} 0 0 1 ${200 + r} 330`} fill="none" stroke={i === 2 ? c : s} strokeOpacity={i === 2 ? 1 : op} strokeWidth={w} strokeLinecap="round" />));
    els.push(<line key="base" x1={-10} y1={330} x2={410} y2={330} stroke={s} strokeOpacity={op} strokeWidth={w} />);
  } else if (a.key === "family") {
    [190, 140, 90].forEach((r) => els.push(<circle key={r} cx={200} cy={200} r={r} fill="none" stroke={s} strokeOpacity={op} strokeWidth={w} />));
    els.push(<circle key="core" cx={200} cy={200} r={40} fill={c} />);
  } else if (a.key === "builder") {
    [[0, 3], [1, 3], [0, 3], [1, 3]].forEach(([off, n], r) => {
      for (let i = 0; i < n; i++) {
        const hi = r === 3 && i === 1;
        els.push(<rect key={`${r}-${i}`} x={20 + off * 55 + i * 120} y={300 - r * 70} width={104} height={54} rx={8} fill={hi ? c : "none"} stroke={hi ? c : s} strokeOpacity={hi ? 1 : op} strokeWidth={w} />);
      }
    });
  } else if (a.key === "student") {
    for (let i = 0; i < 8; i++) {
      const y = 60 + i * 40;
      els.push(<line key={i} x1={40} y1={y} x2={i === 7 ? 230 : 360} y2={y} stroke={i === 4 ? c : s} strokeOpacity={i === 4 ? 1 : op} strokeWidth={w} strokeLinecap="round" />);
    }
  } else if (a.key === "peace") {
    els.push(<circle key="a" cx={148} cy={200} r={120} fill="none" stroke={s} strokeOpacity={op} strokeWidth={w} />);
    els.push(<circle key="b" cx={252} cy={200} r={120} fill="none" stroke={c} strokeWidth={w} />);
  } else if (a.key === "explorer") {
    els.push(<circle key="globe" cx={200} cy={200} r={160} fill="none" stroke={s} strokeOpacity={op} strokeWidth={w} />);
    els.push(<path key="route" d="M70 270 C150 120 260 110 330 140" fill="none" stroke={c} strokeWidth={w} strokeLinecap="round" strokeDasharray="2 26" />);
    els.push(<circle key="to" cx={330} cy={140} r={20} fill={c} />);
    els.push(<circle key="from" cx={70} cy={270} r={14} fill={s} fillOpacity={0.5} />);
  } else {
    els.push(<path key="arch" d="M20 300 Q200 40 380 300" fill="none" stroke={c} strokeWidth={w} strokeLinecap="round" />);
    els.push(<line key="deck" x1={0} y1={300} x2={400} y2={300} stroke={s} strokeOpacity={op} strokeWidth={w} />);
    [80, 140, 200, 260, 320].forEach((x) => {
      const t = (x - 20) / 360;
      const y = (1 - t) * (1 - t) * 300 + 2 * (1 - t) * t * 40 + t * t * 300;
      els.push(<line key={x} x1={x} y1={y + 8} x2={x} y2={292} stroke={s} strokeOpacity={op} strokeWidth={w} />);
    });
  }
  return <svg width={size} height={size} viewBox="0 0 400 400">{els}</svg>;
}

function ring(value: number, size: number, stroke: number): ReactElement {
  const r = size / 2 - stroke;
  const circ = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <div style={{ position: "relative", width: size, height: size, display: "flex" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={LIME} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(circ * v) / 100} ${circ}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <div style={{ position: "absolute", top: 0, left: 0, width: size, height: size, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "#FFFFFF" }}>
        <span style={{ fontFamily: DISPLAY, fontSize: size * 0.3, lineHeight: 1 }}>{String(v)}</span>
        <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: size * 0.075, marginTop: size * 0.03, opacity: 0.85 }}>aligned</span>
      </div>
    </div>
  );
}

function foot(fs: number, ink = "#FFFFFF"): ReactElement {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: fs * 0.6 }}>
      {AhavahMark({ size: Math.round(fs * 2.2) })}
      <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: fs, letterSpacing: "0.04em", color: ink }}>ahavah.app/together</span>
    </div>
  );
}

const isStory = (size: { width: number; height: number }) => size.height > size.width;

function frame(story: boolean, kick: string | null, main: ReactElement): ReactElement {
  const fs = story ? 36 : 22;
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", position: "relative", background: BG, color: "#FFFFFF", overflow: "hidden" }}>
      <div style={{ position: "absolute", right: story ? -260 : -160, top: story ? -200 : -220, width: story ? 900 : 620, height: story ? 900 : 620, borderRadius: 9999, background: "radial-gradient(circle, rgba(85,36,245,0.75), rgba(85,36,245,0) 70%)" }} />
      <div style={story
        ? { position: "absolute", left: 80, right: 80, top: 250, bottom: 340, display: "flex", flexDirection: "column", justifyContent: "center", gap: 56 }
        : { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, padding: "64px 90px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 28 }}>
        {kick ? <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: story ? 36 : 22, letterSpacing: "0.12em", textTransform: "uppercase", color: LIME }}>{kick}</span> : null}
        {main}
        {foot(fs)}
      </div>
    </div>
  );
}

const display = (fontSize: number, children: string): ReactElement => (
  <span style={{ fontFamily: DISPLAY, fontSize, lineHeight: 1.05, color: "#FFFFFF" }}>{children}</span>
);

const meTemplate: ShareTemplate = ({ size, data }) => {
  const key = (typeof data.archetype === "string" && data.archetype in ARCHETYPE_STYLE ? data.archetype : "sabbath") as ArchetypeKey;
  const a = ARCHETYPE_STYLE[key];
  const { name, line } = ARCHETYPES[key];
  const story = isStory(size);
  const long = name.length > 18;
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", position: "relative", background: a.bg, color: a.ink, overflow: "hidden" }}>
      <div style={{ position: "absolute", right: 70, top: story ? 330 : 135, display: "flex" }}>{motif(a, story ? 520 : 360)}</div>
      <div style={story
        ? { position: "absolute", left: 80, right: 80, bottom: 380, display: "flex", flexDirection: "column", gap: 44 }
        : { position: "absolute", left: 90, top: 0, bottom: 0, width: 680, display: "flex", flexDirection: "column", justifyContent: "center", gap: 24 }}>
        <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: story ? 36 : 22, letterSpacing: "0.12em", textTransform: "uppercase", opacity: 0.75 }}>I am</span>
        <span style={{ fontFamily: DISPLAY, fontSize: story ? (long ? 120 : 140) : (long ? 70 : 84), lineHeight: 1 }}>{name}</span>
        <span style={{ fontFamily: TEXT, fontWeight: 600, fontSize: story ? 46 : 26, lineHeight: 1.4, opacity: 0.88 }}>{line}</span>
        <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: story ? 40 : 24, opacity: 0.8 }}>Which kind are you?</span>
        {foot(story ? 36 : 22, a.ink)}
      </div>
    </div>
  );
};

const usTemplate: ShareTemplate = ({ size, data }) => {
  const names = Array.isArray(data.names) ? data.names.map(String) : [];
  const [a = "", b = ""] = names;
  const score = typeof data.score === "number" ? data.score : 0;
  const story = isStory(size);
  const long = a.length > 8 || b.length > 8;
  const heading = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: story ? "center" : "flex-start" }}>
      {display(story ? (long ? 84 : 120) : (long ? 56 : 76), a)}
      {display(story ? (long ? 84 : 120) : (long ? 56 : 76), `and ${b}`)}
    </div>
  );
  const kicker = <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: story ? 40 : 26, color: LIME }}>How well do we fit?</span>;
  return frame(story, null, story
    ? <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 56 }}>{ring(score, 560, 44)}{kicker}{heading}</div>
    : <div style={{ display: "flex", alignItems: "center", gap: 56 }}>{ring(score, 300, 26)}<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{kicker}{heading}</div></div>);
};

const knowsTemplate: ShareTemplate = ({ size, data }) => {
  const name = typeof data.name === "string" ? data.name : "";
  const story = isStory(size);
  const long = name.length > 8;
  return frame(story, "Who knows me best", (
    <div style={{ display: "flex", flexDirection: "column", gap: story ? 56 : 28 }}>
      {display(story ? (long ? 112 : 150) : (long ? 72 : 96), `How well do you know ${name}?`)}
      <span style={{ fontFamily: TEXT, fontWeight: 600, fontSize: story ? 46 : 28, lineHeight: 1.4, color: "rgba(255,255,255,0.85)" }}>Guess their answers. See who knows them best.</span>
    </div>
  ));
};

const coupleTemplate: ShareTemplate = ({ size, data }) => {
  const story = isStory(size);
  return frame(story, null, (
    <div style={{ display: "flex", flexDirection: "column", gap: story ? 56 : 28 }}>
      {display(story ? 104 : 68, "We completed the Ahavah marriage checklist")}
      <span style={{ fontFamily: TEXT, fontWeight: 800, fontSize: story ? 64 : 40, color: LIME }}>{`${Number(data.agree ?? 0)} of ${Number(data.total ?? 0)} in agreement`}</span>
    </div>
  ));
};

const singleTemplate: ShareTemplate = ({ size }) => {
  const story = isStory(size);
  return frame(story, null, (
    <div style={{ display: "flex", flexDirection: "column", gap: story ? 56 : 28 }}>
      {display(story ? 150 : 96, "I wrote my non-negotiables")}
      <span style={{ fontFamily: TEXT, fontWeight: 600, fontSize: story ? 46 : 30, lineHeight: 1.4, color: "rgba(255,255,255,0.85)" }}>The Ahavah marriage checklist. Scripture, your own hopes and the hard questions.</span>
    </div>
  ));
};

export const TOGETHER_TEMPLATES: Record<string, ShareTemplate> = {
  "together-me": meTemplate,
  "together-us": usTemplate,
  "together-knows": knowsTemplate,
  "together-couple": coupleTemplate,
  "together-single": singleTemplate,
};
```

In `src/lib/share-image/templates.tsx`, add at the end of the file:

```tsx
// Together (TEC-1845). Imported last: together-templates imports the
// ShareTemplate type from here.
import { TOGETHER_TEMPLATES } from "@/lib/share-image/together-templates";

Object.assign(SHARE_TEMPLATES, TOGETHER_TEMPLATES);
```

`SHARE_TEMPLATES` is declared `const` with a mutable record, so `Object.assign` adds the entries; `templateFor`'s own-property check finds them.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-share-images.test.ts tests/lib/share-image.test.ts`
Expected: PASS (1 + 6 + 2 new; the foundations suite unchanged). If a render throws on an SVG attribute Satori does not support, keep the attribute out and note which in the commit message; the 5 export frames are the check in Step 6.

- [ ] **Step 6: Match the export**

Render each template at both sizes to PNG (a small script calling `renderShareImage` and writing the bytes, run with `npx tsx`) and compare them by eye with `Claude Design/Ahavah Together Share Images.html` opened in a browser at the same sizes, filled at the export's extremes: Me with The Faithful Student, The Explorer and The Bridge Builder; Us with long names at 0, short at 50 and initials at 100; knows-me with a long name, a short one and initials; the checklist at 0, 11 and 22 of 22; single. Fix spacing and sizes to match. Re-run Step 5.

- [ ] **Step 7: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/share-image/fonts src/lib/share-image/fonts.ts src/lib/share-image/together-templates.tsx src/lib/share-image/render.tsx src/lib/share-image/templates.tsx tests/lib/together-share-images.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the 5 share image templates with the brand's fonts, link preview and story" -m "Refs: TEC-1845"
```

---

### Task 18: The `/together` hub

**Files:**
- Create: `src/app/together/page.tsx`, `src/components/together/together-hub.tsx`
- Modify: `src/app/sitemap.ts` (async; `/together` only while live)
- Add (when it exists): `public/assets/og-together.png` from `Claude Design/export/og/og-together-1200x630.png`
- Test: `tests/components/together-hub.test.tsx`, `tests/app/together-sitemap.test.ts` (create)

**Interfaces:**
- Consumes: `togetherStatus` (Task 15), `unfinished` (Task 15), `getSessionToken` and `readOnboarded`.
- Produces: `/together` (404 while dark), `TogetherHub` (export section 1: 1.1 default, 1.2 a game in progress, 1.3 a checklist in progress, 1.4 a member); `/together` in the sitemap while live.

Strings (export 1.1, 1.2): "Together", "For couples and the single season", "Two free tools for anyone preparing for marriage. Play without an account.", "How well do we fit?", "About 15 questions, about 2 minutes. Play alone, with one person or with friends.", "Play", "The marriage checklist", "Scripture, your own hopes and the hard questions. On your own or as a couple.", "Start the checklist", "Saving a result needs only your email. A shared image never shows your answers.", "Sign in", "Continue where you left off", "Continue".

The export's file `export/og/og-together-1200x630.png` was not in the project on 17 Oct. Retrieve the export again with `/handoff` before this task; if the file is still missing, leave `openGraph.images` out (the root layout's image is used) and record it in the task's commit message.

- [ ] **Step 1: Write the failing tests**

Create `tests/components/together-hub.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { TogetherHub } from "@/components/together/together-hub";
import { rememberSession } from "@/lib/together/storage";

const T = "t".repeat(32);

describe("the Together hub", () => {
  beforeEach(() => window.localStorage.clear());

  it("shows both tools, the privacy line and sign in", () => {
    render(<TogetherHub />);
    expect(screen.getByText("For couples and the single season")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Play" }).getAttribute("href")).toBe("/together/game");
    expect(screen.getByRole("link", { name: "Start the checklist" }).getAttribute("href")).toBe("/marriage-checklist");
    expect(screen.getByText("Saving a result needs only your email. A shared image never shows your answers.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeTruthy();
  });

  it("offers to continue a game left unfinished on this device", () => {
    rememberSession({ sessionId: "s1", token: T, kind: "game", mode: "us", seat: "owner" });
    render(<TogetherHub />);
    expect(screen.getByText("Continue where you left off")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Continue" }).getAttribute("href")).toBe("/together/game?session=s1");
    expect(screen.getByRole("link", { name: "Start the checklist" })).toBeTruthy();
  });
});
```

Create `tests/app/together-sitemap.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

const status = vi.hoisted(() => ({ live: false }));
vi.mock("@/lib/together/status", () => ({ togetherStatus: async () => ({ live: status.live, inviteEmail: false }) }));

import sitemap from "@/app/sitemap";

describe("the sitemap", () => {
  it("lists /together only while Together is live", async () => {
    status.live = false;
    expect((await sitemap()).map((e) => e.url)).not.toContain("https://ahavah.app/together");
    status.live = true;
    expect((await sitemap()).map((e) => e.url)).toContain("https://ahavah.app/together");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-hub.test.tsx tests/app/together-sitemap.test.ts`
Expected: FAIL, `Failed to resolve import "@/components/together/together-hub"`; the sitemap test fails because `sitemap()` returns an array, not a promise of one with `/together`.

- [ ] **Step 3: Write the implementation**

Create `src/components/together/together-hub.tsx`:

```tsx
"use client";

/**
 * /together, the hub (TEC-1845; export section 1). Needs no API call:
 * unfinished answers are read from this device. A member sees their
 * avatar where a visitor sees "Sign in"; their save step skips the code.
 * Markup transcribed from the export with /sot-sync.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { getSessionToken } from "@/lib/api-client";
import { readOnboarded } from "@/lib/onboarded-storage";
import { type StoredSession, unfinished } from "@/lib/together/storage";

export function TogetherHub() {
  const [game, setGame] = useState<StoredSession | null>(null);
  const [checklist, setChecklist] = useState<StoredSession | null>(null);
  const [member, setMember] = useState(false);

  useEffect(() => {
    // Read after mount so the server markup and the first client render agree.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGame(unfinished("game"));
    setChecklist(unfinished("checklist"));
    setMember(Boolean(getSessionToken()) && readOnboarded());
  }, []);

  return (
    <main className="together-hub">
      <header className="together-nav">
        <Link href="/" aria-label="Ahavah home">Ahavah</Link>
        {member ? null : <Link href="/auth/sign-in?next=%2Ftogether">Sign in</Link>}
      </header>
      <div className="together-head">
        <span className="ov">Together</span>
        <h1>For couples and the single season</h1>
        <p>Two free tools for anyone preparing for marriage. Play without an account.</p>
      </div>
      <section className="together-card">
        <h2>How well do we fit?</h2>
        <p>About 15 questions, about 2 minutes. Play alone, with one person or with friends.</p>
        {game ? <span className="chip">Continue where you left off</span> : null}
        <Link href={game ? `/together/game?session=${game.sessionId}` : "/together/game"}>
          {game ? "Continue" : "Play"}
        </Link>
      </section>
      <section className="together-card">
        <h2>The marriage checklist</h2>
        <p>Scripture, your own hopes and the hard questions. On your own or as a couple.</p>
        {checklist ? <span className="chip">Continue where you left off</span> : null}
        <Link href={checklist ? `/marriage-checklist?session=${checklist.sessionId}` : "/marriage-checklist"}>
          {checklist ? "Continue" : "Start the checklist"}
        </Link>
      </section>
      <p className="together-privacy">Saving a result needs only your email. A shared image never shows your answers.</p>
    </main>
  );
}
```

In the second test, with a game in progress the game card reads "Continue" and the checklist card still reads "Start the checklist".

Create `src/app/together/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TogetherHub } from "@/components/together/together-hub";
import { togetherStatus } from "@/lib/together/status";

// The page exists only once Together is live (the API's together_live).
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "For couples and the single season",
  description: "Two free tools for anyone preparing for marriage. Play without an account.",
  alternates: { canonical: "/together" },
  openGraph: {
    title: "For couples and the single season",
    description: "Two free tools for anyone preparing for marriage. Play without an account.",
    url: "https://ahavah.app/together",
    type: "website",
    images: [{ url: "/assets/og-together.png", width: 1200, height: 630, alt: "Together on Ahavah" }],
  },
};

export default async function TogetherPage() {
  const status = await togetherStatus();
  if (!status.live) notFound();
  return <TogetherHub />;
}
```

In `src/app/sitemap.ts`, add `import { togetherStatus } from "@/lib/together/status";`, change the signature to `export default async function sitemap(): Promise<MetadataRoute.Sitemap> {`, and before `const staticEntries = ...` add:

```ts
  // Together (TEC-1845): listed only once it is live, so search engines
  // never meet a page that answers 404.
  if ((await togetherStatus()).live) {
    routes.push({ path: "/together", priority: 0.7, changeFrequency: "monthly" });
  }
```

Copy the export's link preview: `cp "Claude Design/export/og/og-together-1200x630.png" public/assets/og-together.png` (see the note above if it is missing).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-hub.test.tsx tests/app/together-sitemap.test.ts`
Expected: PASS (2 and 1 new). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "Section 1"` and transcribe frames 1.1 to 1.4 (390, 768 and 1440; dark and light) onto `TogetherHub`, porting the kit classes it uses (`ov`, `card`, `chip`, `ico`, `btn-p`, `cap`) through the app's tokens. On the first phone screen: the title and the game's "Play" button. The member state shows the member's avatar and first name (`useProfile`). Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/app/together/page.tsx src/components/together/together-hub.tsx src/app/sitemap.ts public/assets/og-together.png tests/components/together-hub.test.tsx tests/app/together-sitemap.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the /together hub, dark until live, with continue where you left off" -m "Refs: TEC-1845"
```

Leave `public/assets/og-together.png` out of `git add` if Step 3 could not copy it.

---

### Task 19: The game: choosing a mode and the questions

**Files:**
- Create: `src/app/together/game/page.tsx`, `src/components/together/game-flow.tsx`, `src/components/together/mode-choice.tsx`, `src/components/together/question-screen.tsx`, `src/components/together/long-list.tsx`
- Test: `tests/components/together-game.test.tsx` (create)

**Interfaces:**
- Consumes: `startSession`, `saveAnswers`, `finishSession`, `getSession`, `SessionView` (Task 15); `rememberSession`, `sessionById`, `markFinished` (Task 15); `GAME_QUESTIONS`, `ROUNDS`, `COPY` (Task 16); `ALL_COUNTRIES` (`src/lib/countries.ts`), `LANGUAGES` (`src/lib/languages.ts`); `togetherStatus`.
- Produces: `/together/game` with search params `mode?`, `session?`, `chat?`; `GameFlow({ initialSession?: string; initialMode?: ToolMode; chat?: string })`, whose `onResult(view)` hands the finished view to the result components of Task 21 (wired there); `ModeChoice({ onStart(mode) , state: 'idle' | 'busy' | 'failed' })`; `QuestionScreen` props `{ question, roundIndex, position, total, value, saving, failed, guessingName?, isLast, onPick, onNext, onBack, onSkip, onRetry }`; `LongList({ kind: 'country' | 'language', multi, value, onChange })`.

Behaviour (export sections 2 and 3): one progress bar across the whole game ("Round 2 of 6, The feasts"); a round card between rounds 2 to 6 with its name, intro and "Begin" (3.1), static with reduced motion; a single-choice answer saves and moves on when tapped; a multiple choice has "Next", disabled with "Pick at least one, or skip" until something is picked; "Back" and "Skip this one" on every question ("Skip" saves `null`); "Just for fun" on light questions; "What would {name} say?" above the question for a knows-me friend; the last question's button reads "See my result"; a failed save keeps the pick and shows "Not saved. Check your connection." with "Retry"; long lists are a search field over a list, never a sideways strip.

- [ ] **Step 1: Write the failing test**

Create `tests/components/together-game.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  startSession: vi.fn(), saveAnswers: vi.fn(), finishSession: vi.fn(), getSession: vi.fn(),
}));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

import { GameFlow } from "@/components/together/game-flow";
import { sessionById } from "@/lib/together/storage";

const T = "t".repeat(32);

describe("the game", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.values(api).forEach((f) => f.mockReset());
    api.saveAnswers.mockResolvedValue({ saved: 1 });
  });

  it("asks who you are playing with and starts", async () => {
    api.startSession.mockResolvedValue({ session_id: "s1", player_token: T });
    render(<GameFlow />);
    expect(screen.getByText("Who are you playing with?")).toBeTruthy();
    expect(screen.getAllByText("You answer first. Then you send a link.")).toHaveLength(2);
    fireEvent.click(screen.getByRole("radio", { name: /Us/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText("Which calendar sets your Sabbaths and feasts?")).toBeTruthy();
    expect(screen.getByText("Round 1 of 6, Sabbath and calendar")).toBeTruthy();
    expect(api.startSession).toHaveBeenCalledWith("game", "us");
    expect(sessionById("s1")?.mode).toBe("us");
  });

  it("says when the game could not start", async () => {
    api.startSession.mockRejectedValue(new Error("down"));
    render(<GameFlow />);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByText("We could not start the game. Try again.")).toBeTruthy();
  });

  it("saves a single choice and moves on, and skips with null", async () => {
    api.startSession.mockResolvedValue({ session_id: "s1", player_token: T });
    render(<GameFlow initialMode="me" />);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    fireEvent.click(await screen.findByRole("button", { name: "Aviv barley" }));
    await waitFor(() => expect(api.saveAnswers).toHaveBeenCalledWith("s1", T, [{ question_key: "calendar", answer: "aviv-barley" }]));
    expect(await screen.findByText("Where are you in your Torah walk?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip this one" }));
    await waitFor(() => expect(api.saveAnswers).toHaveBeenLastCalledWith("s1", T, [{ question_key: "torah-walk", answer: null }]));
    expect(await screen.findByText("Just for fun")).toBeTruthy();
  });

  it("keeps a pick that failed to save and offers to retry", async () => {
    api.startSession.mockResolvedValue({ session_id: "s1", player_token: T });
    api.saveAnswers.mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ saved: 1 });
    render(<GameFlow initialMode="me" />);
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    fireEvent.click(await screen.findByRole("button", { name: "Enoch" }));
    expect(await screen.findByText("Not saved. Check your connection.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Enoch" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Where are you in your Torah walk?")).toBeTruthy();
  });

  it("needs a pick before Next on a multiple choice, and shows a round card", async () => {
    api.getSession.mockResolvedValue({ session_id: "s1", kind: "game", mode: "me", seat: "owner", state: "playing",
      my_answers: { calendar: "enoch", "torah-walk": "beginner", "sabbath-afternoon": "walk" } });
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "s1", token: T, kind: "game", mode: "me", seat: "owner", savedAt: 1 }]));
    render(<GameFlow initialSession="s1" />);
    expect(await screen.findByText("Which appointed times you keep, and the one you wait for all year.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Begin" }));
    expect(await screen.findByText("Pick every one that fits.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Pick at least one, or skip")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Passover" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.saveAnswers).toHaveBeenCalledWith("s1", T, [{ question_key: "spring-feasts", answer: ["passover"] }]));
  });

  it("asks a friend what the player would say", async () => {
    api.getSession.mockResolvedValue({ session_id: "s2", kind: "game", mode: "knows_me", seat: "guest", state: "playing",
      owner_display: "Rivka", my_answers: {} });
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "s2", token: T, kind: "game", mode: "knows_me", seat: "guest", savedAt: 1 }]));
    render(<GameFlow initialSession="s2" />);
    expect(await screen.findByText("What would Rivka say?")).toBeTruthy();
  });

  it("finishes on the last question with See my result", async () => {
    const all = { calendar: "enoch", "torah-walk": "beginner", "sabbath-afternoon": "walk", "spring-feasts": ["passover"],
      "autumn-feasts": ["sukkot"], "favourite-feast": "sukkot", "has-children": "no", "children-hope": "yes",
      "city-or-country": "city", homestead: "neither", community: "no", "sabbath-host": "me", country: "BB",
      move: "local-only", languages: ["en"], pace: "frequent" };
    api.getSession.mockResolvedValue({ session_id: "s3", kind: "game", mode: "me", seat: "owner", state: "playing", my_answers: all });
    api.finishSession.mockResolvedValue({ session_id: "s3", kind: "game", mode: "me", seat: "owner", state: "ready", my_answers: all,
      result: { archetype: "feast", why: ["feast"] } });
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "s3", token: T, kind: "game", mode: "me", seat: "owner", savedAt: 1 }]));
    const onResult = vi.fn();
    render(<GameFlow initialSession="s3" onResult={onResult} />);
    expect(await screen.findByText("How do you like to talk?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Video calls" }));
    fireEvent.click(screen.getByRole("button", { name: "See my result" }));
    await waitFor(() => expect(onResult).toHaveBeenCalled());
    expect(sessionById("s3")?.finished).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-game.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/together/game-flow"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/together/mode-choice.tsx`:

```tsx
"use client";

/** Choosing a mode (TEC-1845; export section 2). */
import { useState } from "react";

import type { ToolMode } from "@/lib/together/api";
import { COPY } from "@/lib/together/questions";

const MODES: { mode: ToolMode; title: string; line: string }[] = [
  { mode: "me", title: "Me", line: "See what you are looking for, in one word." },
  { mode: "us", title: "Us", line: "Play with one person, then compare. Neither of you sees the other’s answers." },
  { mode: "knows_me", title: "Who knows me best", line: "Answer about yourself, post the link in a group chat and see who knows you best." },
];

export function ModeChoice({ initial = "us", state, onStart }: {
  initial?: ToolMode;
  state: "idle" | "busy" | "failed";
  onStart: (mode: ToolMode) => void;
}) {
  const [mode, setMode] = useState<ToolMode>(initial);
  return (
    <div className="together-modes">
      <span className="ov">How well do we fit?</span>
      <h1>Who are you playing with?</h1>
      <div role="radiogroup" aria-label="Who are you playing with?">
        {MODES.map((m) => (
          <button key={m.mode} type="button" role="radio" aria-checked={mode === m.mode} onClick={() => setMode(m.mode)}>
            <b>{m.title}</b>
            <span>{m.line}</span>
            {m.mode !== "me" ? <span className="cap">You answer first. Then you send a link.</span> : null}
          </button>
        ))}
      </div>
      {state === "failed" ? <p role="alert">{COPY.startFailed}</p> : null}
      <button type="button" disabled={state === "busy"} aria-busy={state === "busy"} onClick={() => onStart(mode)}>Start</button>
    </div>
  );
}
```

Create `src/components/together/long-list.tsx`:

```tsx
"use client";

/** A long list as a search field over a list (export 3.7): never a sideways strip. */
import { useMemo, useState } from "react";

import { ALL_COUNTRIES } from "@/lib/countries";
import { LANGUAGES } from "@/lib/languages";

export function LongList({ kind, multi, value, onChange }: {
  kind: "country" | "language";
  multi: boolean;
  value: string | string[] | undefined;
  onChange: (next: string | string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const items = useMemo(
    () => (kind === "country"
      ? ALL_COUNTRIES.map((c) => ({ key: c.cc, label: c.name }))
      : LANGUAGES.map((l) => ({ key: l.code, label: l.label }))),
    [kind],
  );
  const q = query.trim().toLowerCase();
  const shown = q ? items.filter((i) => i.label.toLowerCase().startsWith(q) || i.label.toLowerCase().includes(` ${q}`)) : items;
  const picked = new Set(Array.isArray(value) ? value : value ? [value] : []);
  const toggle = (key: string) => {
    if (!multi) return onChange(key);
    const next = new Set(picked);
    if (next.has(key)) next.delete(key); else next.add(key);
    onChange([...next]);
  };
  return (
    <div className="together-longlist">
      <input type="search" aria-label="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
      <ul>
        {shown.map((i) => (
          <li key={i.key}>
            <button type="button" aria-pressed={picked.has(i.key)} onClick={() => toggle(i.key)}>{i.label}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

`ALL_COUNTRIES` is exported by `src/lib/countries.ts` (it feeds `POPULAR_COUNTRIES`); if it is not exported, export it there.

Create `src/components/together/question-screen.tsx`:

```tsx
"use client";

/** One question per screen (TEC-1845; export section 3). */
import { LongList } from "@/components/together/long-list";
import type { AnswerValue } from "@/lib/together/api";
import { COPY, ROUNDS, type GameQuestion } from "@/lib/together/questions";

export function QuestionScreen(p: {
  question: GameQuestion;
  position: number;
  total: number;
  value: AnswerValue | undefined;
  saving: boolean;
  failed: boolean;
  guessingName?: string | null;
  isFirst: boolean;
  isLast: boolean;
  onPick: (value: AnswerValue) => void;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
  onRetry: () => void;
  onLeave: () => void;
}) {
  const q = p.question;
  const roundIndex = ROUNDS.findIndex((r) => r.key === q.round);
  const picked = Array.isArray(p.value) ? p.value : p.value ? [String(p.value)] : [];
  const nothingPicked = q.multi && picked.length === 0;
  const toggle = (key: string) => {
    if (!q.multi) return p.onPick(key);
    p.onPick(picked.includes(key) ? picked.filter((k) => k !== key) : [...picked, key]);
  };
  return (
    <div className="together-question">
      <div className="together-progress">
        <button type="button" aria-label={COPY.leave} onClick={p.onLeave}>×</button>
        <span>{COPY.roundLabel(roundIndex + 1, ROUNDS[roundIndex].name)}</span>
        {q.light ? <span className="chip">{COPY.justForFun}</span> : null}
        <div className="bar" aria-hidden><div style={{ width: `${Math.round((p.position / p.total) * 100)}%` }} /></div>
      </div>
      {p.guessingName ? <span className="ov">{COPY.guessing(p.guessingName)}</span> : null}
      <h1>{q.text}</h1>
      {q.multi ? <span className="cap">{COPY.pickEvery}</span> : null}
      {q.longList ? (
        <LongList kind={q.longList} multi={Boolean(q.multi)} value={p.value as string | string[] | undefined} onChange={(v) => p.onPick(v)} />
      ) : (
        <div className="together-options">
          {q.options.map((o) => (
            <button key={o.key} type="button" aria-pressed={picked.includes(o.key)} onClick={() => toggle(o.key)}>{o.label}</button>
          ))}
        </div>
      )}
      {p.failed ? (
        <div role="alert">
          <span>{COPY.notSaved}</span>
          <button type="button" onClick={p.onRetry}>{COPY.retry}</button>
        </div>
      ) : null}
      {nothingPicked && q.multi ? <span className="cap">{COPY.pickAtLeastOne}</span> : null}
      <nav className="together-qnav">
        {p.isFirst ? <span /> : <button type="button" onClick={p.onBack}>{COPY.back}</button>}
        <button type="button" onClick={p.onSkip}>{COPY.skip}</button>
        {q.multi || q.longList || p.isLast ? (
          <button type="button" disabled={p.saving || (Boolean(q.multi) && nothingPicked)} onClick={p.onNext}>
            {p.isLast ? COPY.seeResult : COPY.next}
          </button>
        ) : null}
      </nav>
    </div>
  );
}
```

The `style` on the bar's fill is the one dynamic width; port it to the kit's progress class with a CSS variable during `/sot-sync`, as the checklist does (`--mc-fill`).

Create `src/components/together/game-flow.tsx`:

```tsx
"use client";

/**
 * The compatibility game (TEC-1845): choose a mode, answer one question per
 * screen, finish. Answers are saved one at a time with the device's token;
 * a pick that fails to save stays picked with a retry. On finish the view
 * goes to `onResult`, which shows the result for the mode (Task 21).
 */
import { useCallback, useEffect, useState } from "react";

import { ModeChoice } from "@/components/together/mode-choice";
import { QuestionScreen } from "@/components/together/question-screen";
import {
  type AnswerValue, type SessionView, type ToolMode, finishSession, getSession, saveAnswers, startSession,
} from "@/lib/together/api";
import { COPY, GAME_QUESTIONS, ROUNDS } from "@/lib/together/questions";
import { markFinished, rememberSession, sessionById } from "@/lib/together/storage";

type Phase =
  | { kind: "mode"; state: "idle" | "busy" | "failed" }
  | { kind: "loading" }
  | { kind: "round"; index: number }
  | { kind: "question"; index: number }
  | { kind: "done"; view: SessionView }
  | { kind: "failed" };

export function GameFlow({ initialSession, initialMode, onResult }: {
  initialSession?: string;
  initialMode?: ToolMode;
  onResult?: (view: SessionView, token: string | null) => void;
}) {
  const [phase, setPhase] = useState<Phase>(initialSession ? { kind: "loading" } : { kind: "mode", state: "idle" });
  const [sessionId, setSessionId] = useState<string | null>(initialSession ?? null);
  const [token, setToken] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [guessing, setGuessing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const finish = useCallback((view: SessionView, t: string | null) => {
    markFinished(view.session_id);
    setPhase({ kind: "done", view });
    onResult?.(view, t);
  }, [onResult]);

  useEffect(() => {
    if (!initialSession) return;
    const stored = sessionById(initialSession);
    const t = stored?.token || null;
    setToken(t);
    getSession(initialSession, t)
      .then((view) => {
        setAnswers(view.my_answers ?? {});
        if (view.mode === "knows_me" && view.seat === "guest") setGuessing(view.owner_display);
        if (view.state !== "playing") return finish(view, t);
        const next = GAME_QUESTIONS.findIndex((q) => !(q.key in (view.my_answers ?? {})));
        const index = next === -1 ? GAME_QUESTIONS.length - 1 : next;
        setPhase(startsRound(index) ? { kind: "round", index } : { kind: "question", index });
      })
      .catch(() => setPhase({ kind: "failed" }));
  }, [initialSession, finish]);

  const start = async (mode: ToolMode) => {
    setPhase({ kind: "mode", state: "busy" });
    try {
      const s = await startSession("game", mode);
      rememberSession({ sessionId: s.session_id, token: s.player_token, kind: "game", mode, seat: "owner" });
      setSessionId(s.session_id);
      setToken(s.player_token);
      setPhase({ kind: "question", index: 0 });
    } catch {
      setPhase({ kind: "mode", state: "failed" });
    }
  };

  const go = (index: number) => setPhase(startsRound(index) ? { kind: "round", index } : { kind: "question", index });

  const save = async (index: number, value: AnswerValue | null, advance: boolean) => {
    if (!sessionId) return;
    const q = GAME_QUESTIONS[index];
    setSaving(true);
    setFailed(false);
    try {
      await saveAnswers(sessionId, token, [{ question_key: q.key, answer: value }]);
      if (advance) {
        if (index === GAME_QUESTIONS.length - 1) {
          finish(await finishSession(sessionId, token), token);
        } else {
          go(index + 1);
        }
      }
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  if (phase.kind === "mode") return <ModeChoice initial={initialMode} state={phase.state} onStart={start} />;
  if (phase.kind === "loading" || phase.kind === "done") return null;
  if (phase.kind === "failed") return <p role="alert">{COPY.startFailed}</p>;
  if (phase.kind === "round") {
    const round = ROUNDS.find((r) => r.key === GAME_QUESTIONS[phase.index].round)!;
    const n = ROUNDS.indexOf(round) + 1;
    return (
      <div className="together-round">
        <span className="ov">{COPY.roundOf(n)}</span>
        <h1>{round.name}</h1>
        <p>{round.intro}</p>
        <button type="button" onClick={() => setPhase({ kind: "question", index: phase.index })}>{COPY.begin}</button>
      </div>
    );
  }
  const index = phase.index;
  const q = GAME_QUESTIONS[index];
  const isLast = index === GAME_QUESTIONS.length - 1;
  return (
    <QuestionScreen
      question={q}
      position={index}
      total={GAME_QUESTIONS.length}
      value={answers[q.key]}
      saving={saving}
      failed={failed}
      guessingName={guessing}
      isFirst={index === 0}
      isLast={isLast}
      onPick={(value) => {
        setAnswers((a) => ({ ...a, [q.key]: value }));
        if (!q.multi && !q.longList && !isLast) void save(index, value, true);
      }}
      onNext={() => void save(index, answers[q.key] ?? null, true)}
      onBack={() => index > 0 && setPhase({ kind: "question", index: index - 1 })}
      onSkip={() => {
        setAnswers((a) => {
          const next = { ...a };
          delete next[q.key];
          return next;
        });
        void save(index, null, true);
      }}
      onRetry={() => void save(index, answers[q.key] ?? null, true)}
      onLeave={() => window.location.assign("/together")}
    />
  );
}

/** A round card opens rounds 2 to 6 (export 3.1); round 1 starts on its first question (3.2). */
function startsRound(index: number): boolean {
  if (index === 0) return false;
  return GAME_QUESTIONS[index].round !== GAME_QUESTIONS[index - 1].round;
}
```

On the last question a single choice is picked and then confirmed with "See my result" (export 3.10 draws it), so `onPick` does not advance there.

Create `src/app/together/game/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GameResult } from "@/components/together/game-result";
import { togetherStatus } from "@/lib/together/status";
import type { ToolMode } from "@/lib/together/api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "How well do we fit?",
  description: "About 15 questions, about 2 minutes. Play alone, with one person or with friends.",
  alternates: { canonical: "/together/game" },
};

type Props = { searchParams: Promise<{ mode?: string; session?: string; chat?: string }> };
const MODES: ToolMode[] = ["me", "us", "knows_me"];

export default async function GamePage({ searchParams }: Props) {
  const status = await togetherStatus();
  if (!status.live) notFound();
  const { mode, session, chat } = await searchParams;
  return (
    <GameResult
      initialSession={session}
      initialMode={MODES.includes(mode as ToolMode) ? (mode as ToolMode) : undefined}
      chat={chat}
      inviteEmail={status.inviteEmail}
    />
  );
}
```

`GameResult` is Task 21's component, which wraps `GameFlow` and shows the result. Until Task 21 lands, export a temporary `GameResult` from `src/components/together/game-result.tsx` that renders `<GameFlow initialSession={...} initialMode={...} />`; Task 21 replaces the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-game.test.tsx`
Expected: PASS (7 new). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "Section 2"` and `"Section 3"` and transcribe frames 2.1 to 2.3 and 3.1 to 3.10 (390, 768 and 1440; dark and light): full-width answer pills within thumb reach, 44 px targets, the round card's motion off with `prefers-reduced-motion`, nothing sideways at 390 (the long list stacks under its search field). On the first phone screen: the round, the question and every answer. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/app/together/game/page.tsx src/components/together/game-flow.tsx src/components/together/game-result.tsx src/components/together/mode-choice.tsx src/components/together/question-screen.tsx src/components/together/long-list.tsx tests/components/together-game.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): choosing a mode and one question per screen, saved as you go" -m "Refs: TEC-1845"
```

---

### Task 20: Saving with email, code and name, and the share panel

**Files:**
- Create: `src/components/together/save-step.tsx`, `src/components/together/share-panel.tsx`
- Test: `tests/components/together-save.test.tsx` (create)

**Interfaces:**
- Consumes: `requestEmailOtp`, `checkOtp` (`src/lib/auth-otp.ts`, with the tool's source, Task 15); `claimSession`, `SOURCE_OF`, `SessionView` (Task 15); `AntibotFields` (`src/components/app/antibot-fields.tsx`); `useProfile`; `getSessionToken`, `readOnboarded`; `shareUrl`, `shareText` (Task 16).
- Produces: `SaveStep({ sessionId, token, mode, onSaved(view), heading? })` (export 5.1 to 5.8 and 5.12) and `SharePanel({ shareToken, mode, summary })` (5.9 to 5.11). A member skips the email and code: the step calls `claimSession` with their first name and shows "Saved to your account". `SharePanel` previews `/tools/r/{share}/story` and `/tools/r/{share}/link`; "Save image" shares the story PNG as a file where the phone can, else downloads it; "Share link" opens the share sheet with the text and the tagged link, else copies it.

Strings (5.1 to 5.12): "Save your result", "Email", "Show my name as", the privacy line "We keep your answers behind a private link so you can come back to them. Delete them any time. We delete them 12 months after your last visit.", "Send my code", "This creates a free Ahavah account, no matchmaking profile required.", "Enter a full email address, like name@example.com.", "We could not send your code. Please try again in a moment.", "Check your email", "We sent a 6-digit code to {email}.", "Didn’t get it? Resend code", "That code did not match. Try again.", "Too many attempts. Try again in a few minutes.", "Share your result", "Neither image shows an answer.", "Save image", "Share link", "The image could not be made. You can still share the link.", "Saved to your account". No marketing consent box (owner decision 11).

The export draws "Show my name as" with two chips, the full name and the initial. A visitor has given no name yet, so the step adds one text field under that label; once something is typed, the two chips offer it whole or as an initial (Spec conflicts, item 2).

- [ ] **Step 1: Write the failing test**

Create `tests/components/together-save.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const otp = vi.hoisted(() => ({ requestEmailOtp: vi.fn(), checkOtp: vi.fn() }));
vi.mock("@/lib/auth-otp", () => otp);
const api = vi.hoisted(() => ({ claimSession: vi.fn() }));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
const who = vi.hoisted(() => ({ member: false }));
vi.mock("@/lib/onboarded-storage", () => ({ readOnboarded: () => who.member }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  getSessionToken: () => (who.member ? "session" : null),
}));
vi.mock("@/lib/use-profile", () => ({ useProfile: () => ({ profile: { firstName: "Samuel" } }) }));

import { ApiError } from "@/lib/api-client";
import { SaveStep } from "@/components/together/save-step";

const T = "t".repeat(32);
const VIEW = { session_id: "s1", mode: "us", claimed: true, share_token: "share", invite_token: "inv" };

describe("saving a result", () => {
  beforeEach(() => {
    who.member = false;
    otp.requestEmailOtp.mockReset().mockResolvedValue(undefined);
    otp.checkOtp.mockReset().mockResolvedValue({ onboarded: false });
    api.claimSession.mockReset().mockResolvedValue(VIEW);
  });

  it("checks the address, sends the code, confirms it with the tool's source and saves with the chosen name", async () => {
    const onSaved = vi.fn();
    render(<SaveStep sessionId="s1" token={T} mode="us" onSaved={onSaved} />);
    expect(screen.getByText("This creates a free Ahavah account, no matchmaking profile required.")).toBeTruthy();
    expect(screen.queryByText(/news from Ahavah/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "daniel@example" } });
    fireEvent.click(screen.getByRole("button", { name: "Send my code" }));
    expect(await screen.findByText("Enter a full email address, like name@example.com.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "daniel@example.com" } });
    fireEvent.change(screen.getByLabelText("Show my name as"), { target: { value: "Daniel" } });
    fireEvent.click(screen.getByRole("radio", { name: "D." }));
    fireEvent.click(screen.getByRole("button", { name: "Send my code" }));
    expect(await screen.findByText("We sent a 6-digit code to daniel@example.com.")).toBeTruthy();
    screen.getAllByRole("textbox", { name: /Digit/ }).forEach((cell, i) => fireEvent.change(cell, { target: { value: String(i + 1) } }));
    await waitFor(() => expect(otp.checkOtp).toHaveBeenCalledWith("daniel@example.com", "123456", { source: "tool:game-us" }));
    await waitFor(() => expect(api.claimSession).toHaveBeenCalledWith("s1", T, "D."));
    expect(onSaved).toHaveBeenCalledWith(VIEW);
  });

  it("says when the code did not match or was tried too often", async () => {
    otp.checkOtp.mockRejectedValueOnce(new ApiError(401, "Invalid OTP")).mockRejectedValueOnce(new ApiError(401, "Too many attempts. Request a new code."));
    render(<SaveStep sessionId="s1" token={T} mode="me" onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "d@example.com" } });
    fireEvent.change(screen.getByLabelText("Show my name as"), { target: { value: "Daniel" } });
    fireEvent.click(screen.getByRole("button", { name: "Send my code" }));
    const fill = () => screen.getAllByRole("textbox", { name: /Digit/ }).forEach((c, i) => fireEvent.change(c, { target: { value: String(i) } }));
    await screen.findByText("Check your email");
    fill();
    expect(await screen.findByText("That code did not match. Try again.")).toBeTruthy();
    fill();
    expect(await screen.findByText("Too many attempts. Try again in a few minutes.")).toBeTruthy();
  });

  it("says when the code could not be sent", async () => {
    otp.requestEmailOtp.mockRejectedValue(new Error("down"));
    render(<SaveStep sessionId="s1" token={T} mode="me" onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "d@example.com" } });
    fireEvent.change(screen.getByLabelText("Show my name as"), { target: { value: "Daniel" } });
    fireEvent.click(screen.getByRole("button", { name: "Send my code" }));
    expect(await screen.findByText("We could not send your code. Please try again in a moment.")).toBeTruthy();
  });

  it("saves a member to their account with no code", async () => {
    who.member = true;
    const onSaved = vi.fn();
    render(<SaveStep sessionId="s1" token={T} mode="us" onSaved={onSaved} />);
    await waitFor(() => expect(api.claimSession).toHaveBeenCalledWith("s1", T, "Samuel"));
    expect(otp.requestEmailOtp).not.toHaveBeenCalled();
    expect(await screen.findByText("Saved to your account")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-save.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/together/save-step"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/together/save-step.tsx`:

```tsx
"use client";

/**
 * Saving a result (TEC-1845; export section 5): email, the 6-digit code
 * the checklist already uses, and the name to show. The code is confirmed
 * with the tool's source, so a new address is counted as a lead while the
 * API's switch is on; the save itself reads the address from the session,
 * never from this form. A member skips both and is saved to their account.
 * No marketing consent box (owner decision 11).
 */
import { useEffect, useRef, useState } from "react";

import { AntibotFields, type AntibotHandle } from "@/components/app/antibot-fields";
import { ApiError, getSessionToken } from "@/lib/api-client";
import { checkOtp, requestEmailOtp } from "@/lib/auth-otp";
import { readOnboarded } from "@/lib/onboarded-storage";
import { SOURCE_OF, type SessionView, type ToolMode, claimSession } from "@/lib/together/api";
import { useProfile } from "@/lib/use-profile";

export const SAVE_PRIVACY =
  "We keep your answers behind a private link so you can come back to them. Delete them any time. We delete them 12 months after your last visit.";

const validEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
const initial = (name: string) => `${name.trim().charAt(0).toUpperCase()}.`;

export function SaveStep({ sessionId, token, mode, onSaved, heading = "Save your result" }: {
  sessionId: string;
  token: string | null;
  mode: ToolMode;
  onSaved: (view: SessionView) => void;
  heading?: string;
}) {
  const { profile } = useProfile();
  const member = Boolean(getSessionToken()) && readOnboarded();
  const [phase, setPhase] = useState<"email" | "code" | "member">(member ? "member" : "email");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [useInitial, setUseInitial] = useState(false);
  const [code, setCode] = useState(["", "", "", "", "", ""]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const antibot = useRef<AntibotHandle>(null);
  const display = useInitial ? initial(name) : name.trim();

  useEffect(() => {
    if (!member) return;
    const first = profile.firstName?.trim();
    if (!first) return;
    claimSession(sessionId, token, first).then(onSaved).catch(() => setErr("We could not open this result"));
    // Once: a member is saved as soon as the step opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [member, profile.firstName]);

  async function send() {
    setErr("");
    if (!validEmail(email)) return setErr("Enter a full email address, like name@example.com.");
    if (!name.trim()) return;
    setBusy(true);
    try {
      await requestEmailOtp(email.trim(), antibot.current?.payload() ?? {});
      antibot.current?.reset();
      setPhase("code");
    } catch {
      setErr("We could not send your code. Please try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  async function verify(cells: string[]) {
    const otp = cells.join("");
    if (otp.length < 6) return;
    setErr("");
    setBusy(true);
    try {
      await checkOtp(email.trim(), otp, { source: SOURCE_OF[mode] });
      onSaved(await claimSession(sessionId, token, display));
    } catch (e) {
      const text = e instanceof ApiError && typeof e.body === "string" ? e.body : "";
      if (e instanceof ApiError && (e.status === 429 || text.startsWith("Too many"))) setErr("Too many attempts. Try again in a few minutes.");
      else if (e instanceof ApiError && e.status === 401) setErr("That code did not match. Try again.");
      else setErr("We could not send your code. Please try again in a moment.");
      setCode(["", "", "", "", "", ""]);
    } finally {
      setBusy(false);
    }
  }

  if (phase === "member") {
    return <div className="together-save"><span className="chip ok">Saved to your account</span>{err ? <p role="alert">{err}</p> : null}</div>;
  }
  if (phase === "code") {
    return (
      <div className="together-save">
        <h1>Check your email</h1>
        <p>We sent a 6-digit code to <b>{email.trim()}</b>.</p>
        <div className="together-code">
          {code.map((c, i) => (
            <input key={i} aria-label={`Digit ${i + 1}`} inputMode="numeric" maxLength={1} value={c}
              onChange={(e) => {
                const next = [...code];
                next[i] = e.target.value.replace(/\D/g, "").slice(-1);
                setCode(next);
                if (next.every(Boolean)) void verify(next);
              }} />
          ))}
        </div>
        {err ? <p role="alert">{err}</p> : null}
        <p className="ps">Didn&rsquo;t get it? <button type="button" disabled={busy} onClick={() => void send()}>Resend code</button></p>
      </div>
    );
  }
  return (
    <div className="together-save">
      <AntibotFields ref={antibot} />
      <h1>{heading}</h1>
      <label>Email<input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Show my name as<input autoComplete="given-name" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} /></label>
      {name.trim() ? (
        <div role="radiogroup" aria-label="Show my name as">
          <button type="button" role="radio" aria-checked={!useInitial} onClick={() => setUseInitial(false)}>{name.trim()}</button>
          <button type="button" role="radio" aria-checked={useInitial} onClick={() => setUseInitial(true)}>{initial(name)}</button>
        </div>
      ) : null}
      <p className="ps">{SAVE_PRIVACY}</p>
      {err ? <p role="alert">{err}</p> : null}
      <button type="button" disabled={busy} aria-busy={busy} onClick={() => void send()}>Send my code</button>
      <p className="cap">This creates a free Ahavah account, no matchmaking profile required.</p>
    </div>
  );
}
```

Create `src/components/together/share-panel.tsx`:

```tsx
"use client";

/**
 * The share panel (TEC-1845; export 5.9 to 5.11): both images previewed,
 * "Save image" (the story card, for Instagram or WhatsApp status) and
 * "Share link" (the link preview), with the share text. Neither image
 * shows an answer: both are drawn from the public summary.
 */
import { useState } from "react";

import { SOURCE_OF, type ToolMode } from "@/lib/together/api";
import type { ArchetypeKey } from "@/lib/together/questions";
import { shareText, shareUrl } from "@/lib/together/share";

export function SharePanel({ shareToken, mode, summary }: {
  shareToken: string;
  mode: ToolMode;
  summary: { score?: number; archetype?: ArchetypeKey; agree?: number; total?: number };
}) {
  const [image, setImage] = useState<"drawing" | "ready" | "failed">("drawing");
  const link = shareUrl(shareToken, SOURCE_OF[mode]);
  const text = shareText({ mode, ...summary });

  async function saveImage() {
    const res = await fetch(`/tools/r/${shareToken}/story`);
    const blob = await res.blob();
    const file = new File([blob], "ahavah-together.png", { type: "image/png" });
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], text });
      return;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ahavah-together.png";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function shareLink() {
    if (navigator.share) {
      await navigator.share({ text, url: link }).catch(() => undefined);
    } else {
      await navigator.clipboard?.writeText(`${text} ${link}`);
    }
  }

  return (
    <div className="together-share">
      <h1>Share your result</h1>
      <p className="ps">Neither image shows an answer.</p>
      {image === "failed" ? (
        <p className="cap">The image could not be made. You can still share the link.</p>
      ) : (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/tools/r/${shareToken}/story`} alt="" onLoad={() => setImage("ready")} onError={() => setImage("failed")} />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/tools/r/${shareToken}/link`} alt="" />
        </>
      )}
      <p className="together-sharetext">{text}</p>
      {image === "failed" ? null : <button type="button" onClick={() => void saveImage()}>Save image</button>}
      <button type="button" onClick={() => void shareLink()}>Share link</button>
    </div>
  );
}
```

While an image is still being drawn, the preview keeps its place with the kit's skeleton (5.10), which `/sot-sync` ports from the export.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-save.test.tsx`
Expected: PASS (4 new). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "Section 5"` and transcribe frames 5.1 and 5.3 to 5.12 (5.2, the consent box, is not used); 390, 768 and 1440; dark and light. On the first phone screen: the email field and "Send my code". The name chips are the export's; the text field above them is the one addition. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/together/save-step.tsx src/components/together/share-panel.tsx tests/components/together-save.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): save with email, code and name, or straight to a member's account, and the share panel" -m "Refs: TEC-1845"
```

---

### Task 21: The results: Me, Us and Who knows me best, deleting, and reopening from an email

**Files:**
- Replace: `src/components/together/game-result.tsx`
- Create: `src/components/together/me-result.tsx`, `us-result.tsx`, `knows-result.tsx`, `result-states.tsx`
- Test: `tests/components/together-results.test.tsx` (create)

**Interfaces:**
- Consumes: `GameFlow` (Task 19); `SaveStep`, `SharePanel` (Task 20); `getSession`, `deleteSession`, `removeFromBoard`, `restoreToBoard`, `sendInviteEmail`, `SessionView`, `MeResult`, `UsResult`, `FriendResult` (Task 15); `rememberSession`, `forgetSession`, `sessionById` (Task 15); `ARCHETYPES`, `AREA_LABELS`, `BAR_LABELS` (Task 16); `youInASentence`, `inviteUrl`, `inviteShareText`, `shareText` (Task 16); `requestEmailOtp`, `checkOtp`; `getSessionToken`.
- Produces: `GameResult({ initialSession?, initialMode?, chat?, inviteEmail })`; `MeResultView`, `UsSendLink`, `UsWaiting`, `UsReveal`, `KnowsPostLink`, `KnowsBoard`, `FriendResultView`; from `result-states.tsx`: `Invitations`, `ResultLoading`, `ResultFailed`, `ResultDeleted`, `DeleteDialog`, `ReopenStep`.

Strings: Me (4.1, 4.2): "You are", "You in a sentence", "Why this fits you", "The 2 rounds where your answers were strongest.", "Save and get your image", "Find people who answered like you", "Play with someone else". Us (4.3, 4.4, 4.7): "Your answers are saved", "Copy link", "Send it by email", "Send", "Share", "Nothing shows until you have both answered.", "Send the link again", "aligned", "Where you align most", "Worth talking about", "Save the image", "Delete this result". Who knows me best (4.11, 4.13, 4.15, 4.16, 4.18): "Post your link", "In a group chat, or anywhere your friends are. Each friend gives a name for the board.", "How well do you know me? Play at ahavah.app/together", "Who knows me best", "You got {right} of {total}", "You are first on {name}’s board.", "Your board", "You can remove a name.", "Post your link again", "{name} was removed from the board.", "Undo", "No guesses yet. Post your link in a group chat." States (4.19 to 4.22, 4.6): "Opening your result", "We could not open this result", "Check your connection and try again.", "Delete this result? The link will stop working for everyone.", "Delete", "Cancel", "This result was deleted.", "Confirm your email to see the score", "We send a 6-digit code before the reveal."

Lines the export names a person in before the app can know one (Spec conflicts, item 2), used until the guest has given a name: "Send your link" for 4.3's heading, "Waiting for the other player" for 4.4's, "Their email" for 4.3's field label; 4.3's reassurance line is 2.1's "Neither of you sees the other’s answers. You both see the score." (item 4). A friend placed after first reads "You are number {place} on {name}’s board." (item 3).

- [ ] **Step 1: Write the failing test**

Create `tests/components/together-results.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getSession: vi.fn(), deleteSession: vi.fn(), removeFromBoard: vi.fn(), restoreToBoard: vi.fn(),
  sendInviteEmail: vi.fn(), startSession: vi.fn(), saveAnswers: vi.fn(), finishSession: vi.fn(),
}));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
vi.mock("@/components/together/save-step", () => ({
  SaveStep: ({ onSaved }: { onSaved: (v: unknown) => void }) => (
    <button type="button" onClick={() => onSaved({ ...BASE, mode: "us", state: "waiting", my_answers: {}, claimed: true, share_token: "share", invite_token: "inv" })}>stub save</button>
  ),
  SAVE_PRIVACY: "",
}));
vi.mock("@/components/together/share-panel", () => ({ SharePanel: () => <p>share panel</p> }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

import { GameResult } from "@/components/together/game-result";

const T = "t".repeat(32);
const BASE = {
  session_id: "s1", kind: "game", seat: "owner", role: null, claimed: false, member: false, share_token: null,
  invite_token: null, owner_display: "Daniel", guest_display: null, my_display: "Daniel", board: null,
};

function stored(mode: string, seat = "owner") {
  window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "s1", token: T, kind: "game", mode, seat, savedAt: 1 }]));
}

describe("the results", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("shows the Me archetype, the sentence and why", async () => {
    stored("me");
    api.getSession.mockResolvedValue({ ...BASE, mode: "me", state: "ready",
      my_answers: { "spring-feasts": ["passover"], "autumn-feasts": ["sukkot"], "children-hope": "large-family", move: "international-open" },
      result: { archetype: "feast", why: ["feast", "family"] } });
    render(<GameResult initialSession="s1" inviteEmail={false} />);
    expect(await screen.findByText("The Feast Host")).toBeTruthy();
    expect(screen.getByText("You keep the spring and autumn feasts, hope for a large family and would move countries for the right marriage.")).toBeTruthy();
    expect(screen.getByText("Family and children")).toBeTruthy();
    expect(screen.getByText("The 2 rounds where your answers were strongest.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save and get your image" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Find people who answered like you" }).getAttribute("href")).toBe("/auth/sign-up?from=together");
  });

  it("leaves out why when nothing was answered", async () => {
    stored("me");
    api.getSession.mockResolvedValue({ ...BASE, mode: "me", state: "ready", my_answers: {}, result: { archetype: "sabbath", why: [] } });
    render(<GameResult initialSession="s1" inviteEmail={false} />);
    expect(await screen.findByText("The Sabbath Keeper")).toBeTruthy();
    expect(screen.queryByText("Why this fits you")).toBeNull();
    expect(screen.queryByText("You in a sentence")).toBeNull();
  });

  it("saves an Us game first, then offers the link", async () => {
    stored("us");
    api.getSession.mockResolvedValue({ ...BASE, mode: "us", state: "waiting", my_answers: {}, result: null });
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    render(<GameResult initialSession="s1" inviteEmail={true} />);
    fireEvent.click(await screen.findByRole("button", { name: "stub save" }));
    expect(await screen.findByText("Your answers are saved")).toBeTruthy();
    expect(screen.getByText("Send your link")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://ahavah.app/tools/i/inv"));
    expect(screen.getByLabelText("Their email")).toBeTruthy();
  });

  it("reveals Us to both, and deletes it for everyone", async () => {
    stored("us", "guest");
    api.getSession.mockResolvedValue({ ...BASE, seat: "guest", mode: "us", state: "ready", guest_display: "Rivka", my_answers: {},
      result: { score: 82, areas: {}, align: ["feast", "calendar", "family"], talk: ["relocation", "lifestyle"],
        bars: [{ round: "sabbath", pct: 90 }, { round: "feasts", pct: 95 }, { round: "family", pct: 85 },
          { round: "home", pct: 60 }, { round: "moving", pct: 40 }, { round: "talk", pct: 70 }] } });
    api.deleteSession.mockResolvedValue(undefined);
    render(<GameResult initialSession="s1" inviteEmail={false} />);
    expect(await screen.findByText("82")).toBeTruthy();
    expect(screen.getByText("Daniel and Rivka")).toBeTruthy();
    expect(screen.getByText("Where you align most")).toBeTruthy();
    expect(screen.getByText("Worth talking about")).toBeTruthy();
    expect(screen.getAllByText("Moving").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Delete this result" }));
    expect(screen.getByText("Delete this result? The link will stop working for everyone.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("This result was deleted.")).toBeTruthy();
    expect(api.deleteSession).toHaveBeenCalledWith("s1", T);
  });

  it("lets the player take a name off the board and put it back", async () => {
    stored("knows_me");
    const board = [{ player_id: 7, display: "Josiah", right: 10, total: 14, removed: false }];
    api.getSession.mockResolvedValue({ ...BASE, mode: "knows_me", state: "ready", claimed: true, share_token: "share",
      invite_token: "inv", my_answers: {}, result: null, board });
    api.removeFromBoard.mockResolvedValue({ ...BASE, mode: "knows_me", state: "ready", claimed: true, invite_token: "inv",
      board: [{ ...board[0], removed: true }] });
    api.restoreToBoard.mockResolvedValue({ ...BASE, mode: "knows_me", state: "ready", claimed: true, invite_token: "inv", board });
    render(<GameResult initialSession="s1" inviteEmail={false} />);
    expect(await screen.findByText("Your board")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove Josiah from the board" }));
    expect(await screen.findByText("Josiah was removed from the board.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(api.restoreToBoard).toHaveBeenCalledWith("s1", T, 7));
  });

  it("tells a friend their score and place, never the answers", async () => {
    stored("knows_me", "guest");
    api.getSession.mockResolvedValue({ ...BASE, seat: "guest", mode: "knows_me", state: "ready", my_display: "Hannah",
      owner_display: "Rivka", my_answers: {}, result: { right: 12, total: 14, place: 1 },
      board: [{ display: "Hannah", right: 12, total: 14, me: true }] });
    render(<GameResult initialSession="s1" inviteEmail={false} />);
    expect(await screen.findByText("You got 12 of 14")).toBeTruthy();
    expect(screen.getByText("You are first on Rivka’s board.")).toBeTruthy();
    expect(screen.queryByText("Rivka’s answers")).toBeNull();
  });

  it("asks for the email before reopening a result on another device", async () => {
    render(<GameResult initialSession="s9" inviteEmail={false} />);
    expect(await screen.findByText("Confirm your email to see the score")).toBeTruthy();
    expect(screen.getByText("We send a 6-digit code before the reveal.")).toBeTruthy();
    expect(api.getSession).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-results.test.tsx`
Expected: FAIL. `GameResult` is still Task 19's stand-in, so no result screen renders.

- [ ] **Step 3: Write the implementation**

Create `src/components/together/result-states.tsx`:

```tsx
"use client";

/** The states every result shares (TEC-1845; export 4.19 to 4.22, 4.6). */
import Link from "next/link";
import { useState } from "react";

import { ApiError } from "@/lib/api-client";
import { checkOtp, requestEmailOtp } from "@/lib/auth-otp";

export function Invitations() {
  return (
    <div className="together-invitations">
      <Link href="/auth/sign-up?from=together">Find people who answered like you</Link>
      <Link href="/together/game?mode=us">Play with someone else</Link>
    </div>
  );
}

export const ResultLoading = () => <div className="together-msg" aria-busy="true"><h1>Opening your result</h1></div>;

export const ResultFailed = () => (
  <div className="together-msg"><h1>We could not open this result</h1><p>Check your connection and try again.</p></div>
);

export const ResultDeleted = ({ line = "This result was deleted." }: { line?: string }) => (
  <div className="together-msg"><h1>{line}</h1></div>
);

export function DeleteDialog({ question, onDelete, onCancel }: { question: string; onDelete: () => void; onCancel: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-label={question} className="together-sheet">
      <h2>{question}</h2>
      <button type="button" onClick={onCancel}>Cancel</button>
      <button type="button" onClick={onDelete}>Delete</button>
    </div>
  );
}

/** A saved result opened on another device: the email and code first
 *  (the strict frame's two lines, 4.6), then the session reads it. */
export function ReopenStep({ onOpened }: { onOpened: () => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  return (
    <div className="together-save">
      <h1>Confirm your email to see the score</h1>
      <p className="cap">We send a 6-digit code before the reveal.</p>
      {sent ? (
        <label>Code<input inputMode="numeric" maxLength={6} value={code} onChange={async (e) => {
          const v = e.target.value.replace(/\D/g, "");
          setCode(v);
          if (v.length === 6) {
            try { await checkOtp(email.trim(), v); onOpened(); }
            catch (x) { setErr(x instanceof ApiError && x.status === 401 ? "That code did not match. Try again." : "We could not open this result"); }
          }
        }} /></label>
      ) : (
        <>
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <button type="button" onClick={async () => {
            try { await requestEmailOtp(email.trim()); setSent(true); }
            catch { setErr("We could not send your code. Please try again in a moment."); }
          }}>Send my code</button>
        </>
      )}
      {err ? <p role="alert">{err}</p> : null}
    </div>
  );
}
```

Create `src/components/together/me-result.tsx`:

```tsx
"use client";

/** The Me result (TEC-1845; export 4.1, 4.2). The sentence shows only here, never on an image. */
import { useState } from "react";

import { Invitations } from "@/components/together/result-states";
import { SaveStep } from "@/components/together/save-step";
import { SharePanel } from "@/components/together/share-panel";
import type { MeResult, SessionView } from "@/lib/together/api";
import { ARCHETYPES } from "@/lib/together/questions";
import { youInASentence } from "@/lib/together/sentence";

export function MeResultView({ view, token, onView }: { view: SessionView; token: string | null; onView: (v: SessionView) => void }) {
  const [saving, setSaving] = useState(false);
  const r = view.result as MeResult;
  const a = ARCHETYPES[r.archetype];
  const sentence = youInASentence(view.my_answers);
  if (view.share_token) return <SharePanel shareToken={view.share_token} mode="me" summary={{ archetype: r.archetype }} />;
  if (saving) return <SaveStep sessionId={view.session_id} token={token} mode="me" onSaved={onView} />;
  return (
    <div className="together-me">
      <div className="together-archetype">
        <span className="ov">You are</span>
        <h1>{a.name}</h1>
        <p>{a.line}</p>
      </div>
      <button type="button" onClick={() => setSaving(true)}>Save and get your image</button>
      {sentence ? <div><span className="ov">You in a sentence</span><p>{sentence}</p></div> : null}
      {r.why.length ? (
        <div>
          <span className="ov">Why this fits you</span>
          <div>{r.why.map((k) => <span key={k} className="chip">{ARCHETYPES[k].why}</span>)}</div>
          {r.why.length === 2 ? <span className="cap">The 2 rounds where your answers were strongest.</span> : null}
        </div>
      ) : null}
      <Invitations />
    </div>
  );
}
```

Create `src/components/together/us-result.tsx`:

```tsx
"use client";

/** Us: send the link, wait, the reveal (TEC-1845; export 4.3, 4.4, 4.7). */
import { useEffect, useRef, useState } from "react";

import { AntibotFields, type AntibotHandle } from "@/components/app/antibot-fields";
import { DeleteDialog, Invitations, ResultDeleted } from "@/components/together/result-states";
import { SaveStep } from "@/components/together/save-step";
import { SharePanel } from "@/components/together/share-panel";
import { type SessionView, type UsResult, deleteSession, getSession, sendInviteEmail } from "@/lib/together/api";
import { AREA_LABELS, BAR_LABELS } from "@/lib/together/questions";
import { inviteShareText, inviteUrl } from "@/lib/together/share";
import { forgetSession } from "@/lib/together/storage";

// Not in the export: 4.3 and 4.4 name the guest before anyone has joined
// (plan, Spec conflicts 2 and 4).
const SEND_HEADING = (name: string | null) => (name ? `Send ${name} your link` : "Send your link");
const WAIT_HEADING = (name: string | null) => (name ? `Waiting for ${name}` : "Waiting for the other player");
const NEITHER = "Neither of you sees the other’s answers. You both see the score.";

export function UsSendLink({ view, token, inviteEmail, onSent }: {
  view: SessionView; token: string | null; inviteEmail: boolean; onSent: () => void;
}) {
  const link = inviteUrl(view.invite_token ?? "");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sent" | "failed">("idle");
  const antibot = useRef<AntibotHandle>(null);
  return (
    <div className="together-send">
      <AntibotFields ref={antibot} />
      <span className="chip ok">Your answers are saved</span>
      <h1>{SEND_HEADING(view.guest_display)}</h1>
      <p>{NEITHER}</p>
      <button type="button" onClick={async () => {
        if (navigator.share) await navigator.share({ text: inviteShareText("game", link) }).catch(() => undefined);
        onSent();
      }}>Share</button>
      <div className="together-link"><span>{link.replace("https://", "")}</span>
        <button type="button" onClick={async () => { await navigator.clipboard?.writeText(link); }}>Copy link</button>
      </div>
      {inviteEmail ? (
        <div>
          <b>Send it by email</b>
          <label>Their email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <button type="button" onClick={async () => {
            try { await sendInviteEmail(view.session_id, token, email.trim(), antibot.current?.payload() ?? {}); setState("sent"); onSent(); }
            catch { setState("failed"); }
          }}>Send</button>
          {state === "sent" ? <span className="cap">Sent</span> : null}
          {state === "failed" ? <p role="alert">We could not send the invite. Try again, or share the link instead.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function UsWaiting({ view, token, onView, onSendAgain }: {
  view: SessionView; token: string | null; onView: (v: SessionView) => void; onSendAgain?: () => void;
}) {
  const other = view.seat === "owner" ? view.guest_display : view.owner_display;
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      getSession(view.session_id, token).then((v) => { if (v.state === "ready") onView(v); }).catch(() => undefined);
    }, 20_000);
    return () => window.clearInterval(id);
  }, [view.session_id, token, onView]);
  return (
    <div className="together-msg">
      <div className="together-ring" aria-hidden><span>0</span><span>waiting</span></div>
      <h1>{WAIT_HEADING(other)}</h1>
      <p>Nothing shows until you have both answered.</p>
      {onSendAgain ? <button type="button" onClick={onSendAgain}>Send the link again</button> : null}
    </div>
  );
}

export function UsReveal({ view, token, onView }: { view: SessionView; token: string | null; onView: (v: SessionView) => void }) {
  const r = view.result as UsResult;
  const [panel, setPanel] = useState<"none" | "save" | "share" | "delete" | "deleted">("none");
  if (panel === "deleted") return <ResultDeleted />;
  if (panel === "save") return <SaveStep sessionId={view.session_id} token={token} mode="us" onSaved={(v) => { onView(v); setPanel("share"); }} />;
  if (panel === "share" && view.share_token) return <SharePanel shareToken={view.share_token} mode="us" summary={{ score: r.score }} />;
  const toShare = () => setPanel(view.claimed && view.share_token ? "share" : "save");
  return (
    <div className="together-reveal">
      <div className="together-ring"><span>{r.score}</span><span>aligned</span></div>
      <b>{`${view.owner_display ?? ""} and ${view.guest_display ?? ""}`}</b>
      <div><span className="ov">Where you align most</span>{r.align.map((k) => <b key={k}>{AREA_LABELS[k]}</b>)}</div>
      <div><span className="ov">Worth talking about</span>{r.talk.map((k) => <b key={k}>{AREA_LABELS[k]}</b>)}</div>
      <div className="together-bars">
        {r.bars.map((b) => <div key={b.round}><span>{BAR_LABELS[b.round]}</span><meter min={0} max={100} value={b.pct} aria-label={BAR_LABELS[b.round]} /></div>)}
      </div>
      <button type="button" onClick={toShare}>Save the image</button>
      <button type="button" onClick={toShare}>Share</button>
      <Invitations />
      <button type="button" onClick={() => setPanel("delete")}>Delete this result</button>
      {panel === "delete" ? (
        <DeleteDialog question="Delete this result? The link will stop working for everyone."
          onCancel={() => setPanel("none")}
          onDelete={async () => { await deleteSession(view.session_id, token); forgetSession(view.session_id); setPanel("deleted"); }} />
      ) : null}
    </div>
  );
}
```

Create `src/components/together/knows-result.tsx`:

```tsx
"use client";

/** Who knows me best: post the link, the board, a friend's result (TEC-1845; export 4.11 to 4.18). */
import { useState } from "react";

import { Invitations } from "@/components/together/result-states";
import { type BoardRow, type FriendResult, type SessionView, removeFromBoard, restoreToBoard } from "@/lib/together/api";
import { inviteUrl } from "@/lib/together/share";

const POST_TEXT = "How well do you know me? Play at ahavah.app/together";

function Board({ rows, owner, onRemove }: { rows: BoardRow[]; owner: boolean; onRemove?: (r: BoardRow) => void }) {
  const shown = rows.filter((r) => !r.removed);
  if (!shown.length) return <p className="ps">No guesses yet. Post your link in a group chat.</p>;
  return (
    <ol className="together-board">
      {shown.map((r, i) => (
        <li key={`${r.display}-${i}`} aria-current={r.me ? "true" : undefined}>
          <b>{i + 1}</b><b>{r.display}</b><b>{`${r.right} of ${r.total}`}</b>
          {owner && onRemove ? <button type="button" aria-label={`Remove ${r.display} from the board`} onClick={() => onRemove(r)}>×</button> : null}
        </li>
      ))}
    </ol>
  );
}

export function KnowsBoard({ view, token, onView }: { view: SessionView; token: string | null; onView: (v: SessionView) => void }) {
  const [removed, setRemoved] = useState<BoardRow | null>(null);
  const link = inviteUrl(view.invite_token ?? "");
  const post = async () => {
    if (navigator.share) await navigator.share({ text: POST_TEXT, url: link }).catch(() => undefined);
    else await navigator.clipboard?.writeText(`${POST_TEXT} ${link}`);
  };
  const rows = view.board ?? [];
  if (!rows.length) {
    return (
      <div className="together-post">
        <span className="chip ok">Your answers are saved</span>
        <h1>Post your link</h1>
        <p>In a group chat, or anywhere your friends are. Each friend gives a name for the board.</p>
        <p className="together-sharetext">{POST_TEXT}</p>
        <button type="button" onClick={() => void post()}>Share</button>
        <button type="button" onClick={async () => { await navigator.clipboard?.writeText(link); }}>Copy link</button>
        <Board rows={[]} owner />
      </div>
    );
  }
  const count = rows.filter((r) => !r.removed).length;
  return (
    <div className="together-board-page">
      <span className="ov">Who knows me best</span>
      <h1>Your board</h1>
      <p className="ps">{`${count} ${count === 1 ? "friend has" : "friends have"} guessed. You can remove a name.`}</p>
      <Board rows={rows} owner onRemove={async (r) => {
        if (r.player_id === undefined) return;
        onView(await removeFromBoard(view.session_id, token, r.player_id));
        setRemoved(r);
      }} />
      {removed ? (
        <div role="status">{`${removed.display} was removed from the board.`}
          <button type="button" onClick={async () => {
            if (removed.player_id === undefined) return;
            onView(await restoreToBoard(view.session_id, token, removed.player_id));
            setRemoved(null);
          }}>Undo</button>
        </div>
      ) : null}
      <button type="button" onClick={() => void post()}>Post your link again</button>
    </div>
  );
}

export function FriendResultView({ view }: { view: SessionView }) {
  const r = view.result as FriendResult;
  const name = view.owner_display ?? "";
  // Not in the export: a place after first (plan, Spec conflicts 3).
  const place = r.place === 1 ? `You are first on ${name}’s board.` : `You are number ${r.place} on ${name}’s board.`;
  return (
    <div className="together-friend">
      <span className="ov">Who knows me best</span>
      <h1>{`You got ${r.right} of ${r.total}`}</h1>
      <p>{place}</p>
      <Board rows={view.board ?? []} owner={false} />
      <Invitations />
    </div>
  );
}
```

Replace `src/components/together/game-result.tsx` with:

```tsx
"use client";

/**
 * The game page's body (TEC-1845): plays, then shows the result for the
 * mode and seat. Us and Who knows me best save before the link is sent
 * (export 4.3, 4.11); the second player sees the reveal through the link
 * and is asked for an email only to save it or get the image (owner
 * decision 4, the lighter version). A link that names a session this
 * device cannot open asks for the email first (4.6's lines).
 */
import { useCallback, useEffect, useState } from "react";

import { GameFlow } from "@/components/together/game-flow";
import { FriendResultView, KnowsBoard } from "@/components/together/knows-result";
import { MeResultView } from "@/components/together/me-result";
import { ReopenStep, ResultFailed, ResultLoading } from "@/components/together/result-states";
import { SaveStep } from "@/components/together/save-step";
import { UsReveal, UsSendLink, UsWaiting } from "@/components/together/us-result";
import { getSessionToken } from "@/lib/api-client";
import { type SessionView, type ToolMode, getSession } from "@/lib/together/api";
import { rememberSession, sessionById } from "@/lib/together/storage";

export function GameResult({ initialSession, initialMode, chat, inviteEmail }: {
  initialSession?: string; initialMode?: ToolMode; chat?: string; inviteEmail: boolean;
}) {
  const [view, setView] = useState<SessionView | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [gate, setGate] = useState<"check" | "play" | "reopen" | "loading" | "failed">(initialSession ? "check" : "play");
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (gate !== "check" || !initialSession) return;
    const stored = sessionById(initialSession);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (stored) { setToken(stored.token || null); setGate("play"); }
    else if (getSessionToken()) setGate("loading");
    else setGate("reopen");
  }, [gate, initialSession]);

  useEffect(() => {
    if (gate !== "loading" || !initialSession) return;
    getSession(initialSession, null)
      .then((v) => {
        rememberSession({ sessionId: v.session_id, token: "", kind: v.kind, mode: v.mode, seat: v.seat });
        if (v.state === "playing") setGate("play"); else setView(v);
      })
      .catch(() => setGate("failed"));
  }, [gate, initialSession]);

  const onView = useCallback((v: SessionView) => {
    setView(v);
    if (v.invite_token) rememberSession({ sessionId: v.session_id, token: token ?? "", kind: v.kind, mode: v.mode, seat: v.seat, invite: v.invite_token, finished: v.state !== "playing" });
  }, [token]);

  if (gate === "check") return null;
  if (gate === "reopen") return <ReopenStep onOpened={() => setGate("loading")} />;
  if (gate === "failed") return <ResultFailed />;
  if (!view) {
    if (gate === "loading") return <ResultLoading />;
    return <GameFlow initialSession={initialSession} initialMode={initialMode} onResult={(v, t) => { setToken(t); setView(v); }} />;
  }

  const owner = view.seat === "owner";
  if (view.mode === "me") return <MeResultView view={view} token={token} onView={onView} />;
  if (view.mode === "knows_me") {
    if (!owner) return <FriendResultView view={view} />;
    if (!view.claimed) return <SaveStep sessionId={view.session_id} token={token} mode="knows_me" onSaved={onView} />;
    return <KnowsBoard view={view} token={token} onView={onView} />;
  }
  if (view.state === "ready") return <UsReveal view={view} token={token} onView={onView} />;
  if (owner && !view.claimed) return <SaveStep sessionId={view.session_id} token={token} mode="us" onSaved={onView} />;
  if (owner && !sent && !view.guest_display) {
    return <UsSendLink view={view} token={token} inviteEmail={inviteEmail} onSent={() => setSent(true)} />;
  }
  return <UsWaiting view={view} token={token} onView={onView} onSendAgain={owner ? () => setSent(false) : undefined} />;
}
```

`chat` is used from Task 25. In the Us send-link test, "Copy link" leaves the send-link screen in place (only Share and a sent email move on to waiting), so the email field is still there.

`GameResult` decides whether to reopen before `GameFlow` mounts, so `game-flow.tsx` does not change.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-results.test.tsx tests/components/together-game.test.tsx`
Expected: PASS (7 new; the game suite unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "Section 4a"`, `"Section 4b"`, `"Section 4c"` and `"Section 4"` and transcribe frames 4.1 to 4.4, 4.7, 4.11 to 4.13, 4.15 to 4.22 (390, 768 and 1440; dark and light): the ring as the export's SVG, the bars as its rounded tracks (the `meter` keeps the value for screen readers), the delete confirmation as the kit's sheet, the board as a list at every width. On the first phone screen: Me, the archetype and "Save and get your image"; the reveal, the ring, both names and the first area. 4.6 is used only for reopening. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/together/game-result.tsx src/components/together/me-result.tsx src/components/together/us-result.tsx src/components/together/knows-result.tsx src/components/together/result-states.tsx tests/components/together-results.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the Me, Us and Who knows me best results, deleting, and reopening with the email" -m "Refs: TEC-1845"
```

---

### Task 22: The second player's start at `/tools/i/{token}`

**Files:**
- Create: `src/app/tools/i/[token]/page.tsx`, `src/components/together/second-start.tsx`
- Test: `tests/components/together-second-start.test.tsx` (create)

**Interfaces:**
- Consumes: `getInvite`, `joinSession`, `InviteInfo` (Task 15); `sessionByInvite`, `rememberSession` (Task 15); `useProfile`, `getSessionToken`, `readOnboarded`; `togetherStatus`.
- Produces: `/tools/i/{token}` (404 while dark, never indexed); `SecondStart({ invite })`: the game's start (4.5, the lighter version), the friend's start (4.12), the checklist partner's start (6.4); deleted (4.8, 6.5), not found (4.9, 6.5), already played on this device (straight to the result), full; joining sends the guest to `/together/game?session={id}` or `/marriage-checklist?session={id}`.

A signed-in member (from a match's chat) sees "Signed in as {name}. No email step." (9.5) and joins with their profile's first name. Every other guest gives a name: knows-me with 4.12's field; Us and the checklist with a field labelled "Show my name as" (5.1's label; Spec conflicts, item 2). The API answers a deleted or unknown link without saying which tool it was, so those two states use the game's lines unless this device knows the link (Spec conflicts, item 12).

- [ ] **Step 1: Write the failing test**

Create `tests/components/together-second-start.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const api = vi.hoisted(() => ({ getInvite: vi.fn(), joinSession: vi.fn() }));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
const who = vi.hoisted(() => ({ member: false }));
vi.mock("@/lib/onboarded-storage", () => ({ readOnboarded: () => who.member }));
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  getSessionToken: () => (who.member ? "session" : null),
}));
vi.mock("@/lib/use-profile", () => ({ useProfile: () => ({ profile: { firstName: "Samuel" } }) }));

import { ApiError } from "@/lib/api-client";
import { SecondStart } from "@/components/together/second-start";
import { sessionById } from "@/lib/together/storage";

const T = "t".repeat(32);

describe("the second player's start", () => {
  beforeEach(() => {
    window.localStorage.clear();
    who.member = false;
    router.push.mockReset();
    router.replace.mockReset();
    api.getInvite.mockReset();
    api.joinSession.mockReset().mockResolvedValue({ session_id: "g1", player_token: T });
  });

  it("starts an Us game with a name, and nobody sees the other's answers", async () => {
    api.getInvite.mockResolvedValue({ kind: "game", mode: "us", owner_display: "Rivka", state: "open" });
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("Rivka wants to see how well you fit")).toBeTruthy();
    expect(screen.getByText("About 2 minutes. No account needed. Neither of you sees the other’s answers. You both see the score.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Show my name as"), { target: { value: "Daniel" } });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(api.joinSession).toHaveBeenCalledWith("inv", "Daniel"));
    expect(router.push).toHaveBeenCalledWith("/together/game?session=g1");
    expect(sessionById("g1")).toMatchObject({ seat: "guest", invite: "inv", mode: "us" });
  });

  it("asks a friend for the name the board will show", async () => {
    api.getInvite.mockResolvedValue({ kind: "game", mode: "knows_me", owner_display: "Rivka", state: "open" });
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("How well do you know Rivka?")).toBeTruthy();
    expect(screen.getByLabelText("Your name, as it will show on the board")).toBeTruthy();
  });

  it("invites a partner to the checklist", async () => {
    api.getInvite.mockResolvedValue({ kind: "checklist", mode: "couple", owner_display: "Rivka", state: "open" });
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("Rivka invited you to the Ahavah marriage checklist")).toBeTruthy();
    expect(screen.getByText("Your answers stay private until you have both finished. Then you each see where you agree and what to talk about.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Show my name as"), { target: { value: "Daniel" } });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/marriage-checklist?session=g1"));
  });

  it("says a deleted game was deleted", async () => {
    api.getInvite.mockRejectedValue(new ApiError(410, { error: "deleted" }));
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("This game was deleted")).toBeTruthy();
    expect(screen.getByText("You can still play on your own.")).toBeTruthy();
  });

  it("says when a game cannot be found", async () => {
    api.getInvite.mockRejectedValue(new ApiError(404, { error: "not_found" }));
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("We could not find this game")).toBeTruthy();
  });

  it("says the game is full and offers to play alone", async () => {
    api.getInvite.mockResolvedValue({ kind: "game", mode: "us", owner_display: "Rivka", state: "full" });
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("This link has already been used.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Play" }).getAttribute("href")).toBe("/together/game");
  });

  it("goes straight to the result when this device already played", async () => {
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "g0", token: T, kind: "game", mode: "us", seat: "guest", invite: "inv", savedAt: 1 }]));
    render(<SecondStart invite="inv" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/together/game?session=g0"));
    expect(api.getInvite).not.toHaveBeenCalled();
  });

  it("lets a signed-in member start with no email step", async () => {
    who.member = true;
    api.getInvite.mockResolvedValue({ kind: "game", mode: "us", owner_display: "Daniel", state: "open" });
    render(<SecondStart invite="inv" />);
    expect(await screen.findByText("Signed in as Samuel. No email step.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(api.joinSession).toHaveBeenCalledWith("inv", "Samuel"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-second-start.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/together/second-start"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/together/second-start.tsx`:

```tsx
"use client";

/**
 * The second player's start (TEC-1845; export 4.5, 4.8, 4.9, 4.12, 6.4,
 * 6.5, 9.5). The lighter version of owner decision 4: no email before
 * playing. A device that already played goes straight to its result.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getSessionToken } from "@/lib/api-client";
import { readOnboarded } from "@/lib/onboarded-storage";
import { type InviteInfo, getInvite, joinSession } from "@/lib/together/api";
import { rememberSession, sessionByInvite } from "@/lib/together/storage";
import { useProfile } from "@/lib/use-profile";

const pathFor = (kind: "game" | "checklist", id: string) =>
  kind === "game" ? `/together/game?session=${id}` : `/marriage-checklist?session=${id}`;

type Phase = { kind: "loading" } | { kind: "open"; info: InviteInfo } | { kind: "gone" | "missing" | "full" };

export function SecondStart({ invite }: { invite: string }) {
  const router = useRouter();
  const { profile } = useProfile();
  const member = Boolean(getSessionToken()) && readOnboarded();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const here = sessionByInvite(invite);
    if (here) { router.replace(pathFor(here.kind, here.sessionId)); return; }
    getInvite(invite)
      .then((info) => setPhase(info.state === "open" ? { kind: "open", info } : { kind: info.state === "full" ? "full" : "missing" }))
      .catch((e) => setPhase({ kind: e instanceof ApiError && e.status === 410 ? "gone" : "missing" }));
  }, [invite, router]);

  if (phase.kind === "loading") return null;
  if (phase.kind !== "open") {
    const heading = phase.kind === "gone" ? "This game was deleted"
      : phase.kind === "full" ? "This link has already been used." // Not in the export (Spec conflicts 3).
      : "We could not find this game";
    return (
      <div className="together-msg">
        <h1>{heading}</h1>
        <p>You can still play on your own.</p>
        <Link href="/together/game">Play</Link>
      </div>
    );
  }

  const { info } = phase;
  const owner = info.owner_display ?? "";
  const display = member ? (profile.firstName ?? "").trim() : name.trim();
  const start = async () => {
    if (!display) return;
    setBusy(true);
    try {
      const s = await joinSession(invite, display);
      rememberSession({ sessionId: s.session_id, token: s.player_token, kind: info.kind, mode: info.mode, seat: "guest", invite });
      router.push(pathFor(info.kind, s.session_id));
    } catch (e) {
      setPhase({ kind: e instanceof ApiError && e.status === 410 ? "gone" : e instanceof ApiError && e.status === 409 ? "full" : "missing" });
    } finally {
      setBusy(false);
    }
  };
  const nameField = member ? (
    <span className="cap">{`Signed in as ${display}. No email step.`}</span>
  ) : (
    <label>
      {info.mode === "knows_me" ? "Your name, as it will show on the board" : "Show my name as"}
      <input autoComplete="given-name" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
    </label>
  );

  return (
    <div className="together-second">
      {info.mode === "knows_me" ? (
        <>
          <span className="chip">Who knows me best</span>
          <h1>{`How well do you know ${owner}?`}</h1>
        </>
      ) : info.kind === "checklist" ? (
        <>
          <span className="chip">The marriage checklist</span>
          <h1>{`${owner} invited you to the Ahavah marriage checklist`}</h1>
          <p>Your answers stay private until you have both finished. Then you each see where you agree and what to talk about.</p>
        </>
      ) : (
        <>
          <span className="chip">How well do we fit?</span>
          <h1>{`${owner} wants to see how well you fit`}</h1>
          {/* 4.5's "will not see hers" names a pronoun the app does not know (Spec conflicts 4). */}
          <p>About 2 minutes. No account needed. Neither of you sees the other&rsquo;s answers. You both see the score.</p>
        </>
      )}
      {nameField}
      <button type="button" disabled={busy || !display} onClick={() => void start()}>Start</button>
    </div>
  );
}
```

Create `src/app/tools/i/[token]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SecondStart } from "@/components/together/second-start";
import { togetherStatus } from "@/lib/together/status";

export const dynamic = "force-dynamic";
// A private invitation: never in search results.
export const metadata: Metadata = { title: "How well do we fit?", robots: { index: false, follow: false } };

type Props = { params: Promise<{ token: string }> };

export default async function InvitePage({ params }: Props) {
  if (!(await togetherStatus()).live) notFound();
  const { token } = await params;
  return <SecondStart invite={token} />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/together-second-start.test.tsx`
Expected: PASS (8 new). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "4.5"`, `"4.8"`, `"4.9"`, `"4.12"`, `"6.4"`, `"6.5"`, `"9.5"` and transcribe them (390, 768 and 1440; dark and light): the inviter's initial avatar and the chip, the name field in 4.12's style for every guest. On the first phone screen: who invited them and "Start". Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add "src/app/tools/i/[token]/page.tsx" src/components/together/second-start.tsx tests/components/together-second-start.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the second player's start, with no email before playing" -m "Refs: TEC-1845"
```

---

### Task 23: The public result page and its images at `/tools/r/{token}`

**Files:**
- Create: `src/lib/together/summary.ts`, `src/app/tools/r/[token]/page.tsx`, `src/app/tools/r/[token]/opengraph-image.tsx`, `src/app/tools/r/[token]/story/route.ts`, `src/app/tools/r/[token]/link/route.ts`, `src/components/together/public-result.tsx`
- Test: `tests/lib/together-summary.test.ts`, `tests/components/together-public-result.test.tsx` (create)

**Interfaces:**
- Consumes: `fetchPublicSummary`, `renderShareImage`, `loadShareFonts` (Task 17); `apiOrigin`; `countShareOpen`, `PublicSummary` (Task 15); `shareText` (Task 16); `togetherStatus`.
- Produces: `parsePublicSummary(raw) -> PublicSummary | null`; `imageFor(summary) -> { template, data } | null`; `renderSummaryImage(token, size: 'link' | 'story')`; the page (never indexed), its 1200 by 630 link preview, `GET /tools/r/{token}/story` (1080 by 1920, for "Save image") and `GET /tools/r/{token}/link`; `PublicResult({ token, summary })`, which counts the opening once per tab.

The export has no frame for the page a shared link opens (the brief's scope names it). The plan composes it from drawn parts: the link preview image, the page title as the image's heading (the export's chip lines: "How well do we fit?", "Who knows me best", "The marriage checklist") and the hub's buttons ("Play", "Start the checklist"). A deleted result shows 4.22's "This result was deleted."; an unknown one is not found.

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/together-summary.test.ts`:

```ts
// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { imageFor, parsePublicSummary, renderSummaryImage } from "@/lib/together/summary";

describe("the public summary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("accepts only the shape the API sends", () => {
    expect(parsePublicSummary(null)).toBeNull();
    expect(parsePublicSummary({ kind: "game", mode: "us" })).toBeNull();
    expect(parsePublicSummary({ kind: "game", mode: "us", names: ["D.", "R."], state: "ready", score: 82 }))
      .toEqual({ kind: "game", mode: "us", names: ["D.", "R."], state: "ready", score: 82 });
  });

  it("draws an image only from names and the headline number", () => {
    expect(imageFor({ kind: "game", mode: "us", names: ["D.", "R."], state: "waiting" })).toBeNull();
    expect(imageFor({ kind: "game", mode: "us", names: ["D.", "R."], state: "ready", score: 82 }))
      .toEqual({ template: "together-us", data: { names: ["D.", "R."], score: 82 } });
    expect(imageFor({ kind: "game", mode: "knows_me", names: ["Rivka"], state: "ready" }))
      .toEqual({ template: "together-knows", data: { name: "Rivka" } });
    expect(imageFor({ kind: "game", mode: "me", names: ["D."], state: "ready", archetype: "feast" }))
      .toEqual({ template: "together-me", data: { archetype: "feast" } });
    expect(imageFor({ kind: "checklist", mode: "couple", names: ["D.", "R."], state: "ready", agree: 18, total: 22 }))
      .toEqual({ template: "together-couple", data: { agree: 18, total: 22 } });
  });

  it("renders the story card, and the plain mark when the summary cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(
      { kind: "game", mode: "us", names: ["D.", "R."], state: "ready", score: 82 }), { status: 200 })));
    const story = Buffer.from(await (await renderSummaryImage("abcdefghijklmnopqrstuv", "story")).arrayBuffer());
    expect([story.readUInt32BE(16), story.readUInt32BE(20)]).toEqual([1080, 1920]);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("gone", { status: 410 })));
    const link = Buffer.from(await (await renderSummaryImage("abcdefghijklmnopqrstuv", "link")).arrayBuffer());
    expect([link.readUInt32BE(16), link.readUInt32BE(20)]).toEqual([1200, 630]);
  });
});
```

Create `tests/components/together-public-result.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ countShareOpen: vi.fn() }));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));

import { PublicResult } from "@/components/together/public-result";

describe("the page a shared link opens", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    api.countShareOpen.mockReset().mockResolvedValue(undefined);
  });

  it("shows the image and invites the visitor to play, counting the opening once per tab", () => {
    const summary = { kind: "game", mode: "us", names: ["D.", "R."], state: "ready", score: 82 } as const;
    const { unmount } = render(<PublicResult token="tok" summary={summary} />);
    expect(screen.getByText("How well do we fit?")).toBeTruthy();
    expect(screen.getByRole("img").getAttribute("src")).toBe("/tools/r/tok/link");
    expect(screen.getByRole("link", { name: "Play" }).getAttribute("href")).toBe("/together");
    unmount();
    render(<PublicResult token="tok" summary={summary} />);
    expect(api.countShareOpen).toHaveBeenCalledTimes(1);
  });

  it("sends a checklist share to the checklist", () => {
    render(<PublicResult token="tok" summary={{ kind: "checklist", mode: "single", names: ["R."], state: "ready" }} />);
    expect(screen.getByText("The marriage checklist")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Start the checklist" }).getAttribute("href")).toBe("/marriage-checklist");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-summary.test.ts tests/components/together-public-result.test.tsx`
Expected: FAIL, `Failed to resolve import "@/lib/together/summary"` and `"@/components/together/public-result"`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/together/summary.ts`:

```ts
/**
 * A shared result's public summary and its images (TEC-1845). The API's
 * GET /tools/r/{token} carries names and the headline number, never an
 * answer; the images draw only that. When the summary cannot be read (or
 * the result is not ready) the image is the plain mark.
 */
import type { ImageResponse } from "next/og";

import { loadShareFonts } from "@/lib/share-image/fonts";
import { renderShareImage } from "@/lib/share-image/render";
import { fetchPublicSummary } from "@/lib/share-image/summary";
import type { PublicSummary, ToolKind, ToolMode } from "@/lib/together/api";
import type { ArchetypeKey } from "@/lib/together/questions";

const KINDS: ToolKind[] = ["game", "checklist"];
const MODES: ToolMode[] = ["me", "us", "knows_me", "couple", "single"];
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

export function parsePublicSummary(raw: unknown): PublicSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!KINDS.includes(r.kind as ToolKind) || !MODES.includes(r.mode as ToolMode)) return null;
  if (!Array.isArray(r.names) || !r.names.every((n) => typeof n === "string")) return null;
  if (r.state !== "ready" && r.state !== "waiting") return null;
  const out: PublicSummary = { kind: r.kind as ToolKind, mode: r.mode as ToolMode, names: r.names as string[], state: r.state };
  if (num(r.score) !== undefined) out.score = num(r.score);
  if (typeof r.archetype === "string") out.archetype = r.archetype as ArchetypeKey;
  if (num(r.agree) !== undefined) out.agree = num(r.agree);
  if (num(r.total) !== undefined) out.total = num(r.total);
  return out;
}

export function imageFor(s: PublicSummary): { template: string; data: Record<string, unknown> } | null {
  switch (s.mode) {
    case "me": return s.state === "ready" && s.archetype ? { template: "together-me", data: { archetype: s.archetype } } : null;
    case "us": return s.state === "ready" && s.score !== undefined ? { template: "together-us", data: { names: s.names.slice(0, 2), score: s.score } } : null;
    case "knows_me": return s.names[0] ? { template: "together-knows", data: { name: s.names[0] } } : null;
    case "couple": return s.state === "ready" && s.total !== undefined ? { template: "together-couple", data: { agree: s.agree ?? 0, total: s.total } } : null;
    case "single": return { template: "together-single", data: {} };
  }
}

export async function renderSummaryImage(token: string, size: "link" | "story"): Promise<ImageResponse> {
  const summary = await fetchPublicSummary(`/tools/r/${token}`, parsePublicSummary);
  const pick = summary ? imageFor(summary) : null;
  const fonts = await loadShareFonts();
  return renderShareImage({ template: pick?.template ?? "fallback", size, data: pick?.data ?? {}, fonts });
}

export function pageTitle(s: PublicSummary | null): string {
  if (!s) return "Together";
  if (s.kind === "checklist") return "The marriage checklist";
  return s.mode === "knows_me" ? "Who knows me best" : "How well do we fit?";
}
```

Create `src/components/together/public-result.tsx`:

```tsx
"use client";

/** The page a shared result link opens (TEC-1845): the image, and the way in. */
import Link from "next/link";
import { useEffect } from "react";

import { type PublicSummary, countShareOpen } from "@/lib/together/api";
import { pageTitle } from "@/lib/together/summary";
import { shareText } from "@/lib/together/share";

export function PublicResult({ token, summary }: { token: string; summary: PublicSummary }) {
  useEffect(() => {
    const key = `ahavah.together.opened.${token}`;
    try {
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, "1");
    } catch { /* storage blocked: count anyway */ }
    void countShareOpen(token);
  }, [token]);
  const game = summary.kind === "game";
  return (
    <main className="together-public">
      <h1>{pageTitle(summary)}</h1>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/tools/r/${token}/link`} alt={summary.state === "ready" ? shareText(summary) : pageTitle(summary)} width={1200} height={630} />
      <Link href={game ? "/together" : "/marriage-checklist"}>{game ? "Play" : "Start the checklist"}</Link>
    </main>
  );
}
```

Create `src/app/tools/r/[token]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublicResult } from "@/components/together/public-result";
import { ResultDeleted } from "@/components/together/result-states";
import { apiOrigin } from "@/lib/api-origin";
import { fetchPublicSummary } from "@/lib/share-image/summary";
import { togetherStatus } from "@/lib/together/status";
import { pageTitle, parsePublicSummary } from "@/lib/together/summary";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ token: string }> };
const TOKEN = /^[A-Za-z0-9_-]{16,64}$/;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { token } = await params;
  const s = TOKEN.test(token) ? await fetchPublicSummary(`/tools/r/${token}`, parsePublicSummary) : null;
  return { title: pageTitle(s), robots: { index: false, follow: false } };
}

export default async function SharedResultPage({ params }: Props) {
  if (!(await togetherStatus()).live) notFound();
  const { token } = await params;
  if (!TOKEN.test(token)) notFound();
  const res = await fetch(`${apiOrigin()}/tools/r/${token}`, { cache: "no-store", headers: { accept: "application/json" } });
  if (res.status === 410) return <ResultDeleted />;
  if (!res.ok) notFound();
  const summary = parsePublicSummary(await res.json());
  if (!summary) notFound();
  return <PublicResult token={token} summary={summary} />;
}
```

Create `src/app/tools/r/[token]/opengraph-image.tsx`:

```tsx
import { renderSummaryImage } from "@/lib/together/summary";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "A Together result on Ahavah";

export default async function Image({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return renderSummaryImage(token, "link");
}
```

Create `src/app/tools/r/[token]/story/route.ts`:

```ts
import { renderSummaryImage } from "@/lib/together/summary";

export async function GET(_request: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return renderSummaryImage(token, "story");
}
```

Create `src/app/tools/r/[token]/link/route.ts` the same way with `"link"`.

`renderShareImage` already sets `Cache-Control` (an hour in the browser, a day at the edge); a deleted result's image becomes the plain mark within a day, as the foundations decided.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-summary.test.ts tests/components/together-public-result.test.tsx`
Expected: PASS (3 and 2 new). Then `npx tsc --noEmit` reports no errors, and `npx next build` lists `/tools/r/[token]`, its `opengraph-image`, `story` and `link`; check in the build trace (`.next/server/app/tools/r/[token]/opengraph-image.js.nft.json` or the route's own trace) that `src/lib/share-image/fonts/*` is included. If it is not, add the folder to `outputFileTracingIncludes` for `/tools/r/[token]/**` in `next.config.ts`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/together/summary.ts "src/app/tools/r/[token]" src/components/together/public-result.tsx tests/lib/together-summary.test.ts tests/components/together-public-result.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): the page a shared result opens, its link preview and the story card" -m "Refs: TEC-1845"
```

Add `next.config.ts` to `git add` if Step 4 changed it.

---

### Task 24: The marriage checklist, version 2

**Files:**
- Modify: `src/components/app/marriage-checklist/checklist-client.tsx` (export the shared screens; two optional props)
- Create: `src/components/app/marriage-checklist/checklist-v2.tsx`, `src/components/app/marriage-checklist/comparison.tsx`, `src/app/marriage-checklist/v2-copy.ts`
- Modify: `src/app/marriage-checklist/page.tsx` (v1 or v2 by the switch; v2 metadata and FAQ), `src/app/marriage-checklist/content.ts` (module docstring), `src/app/marriage-checklist/marriage-checklist.css` (v2 dark first)
- Test: `tests/components/checklist-v2.test.tsx` (create)

**Interfaces:**
- Consumes: `startSession`, `saveAnswers`, `finishSession`, `getSession`, `deleteSession`, `sendInviteEmail`, `Comparison`, `SingleResult`, `SessionView` (Task 15); `rememberSession`, `sessionById`, `forgetSession` (Task 15); `SaveStep`, `SharePanel` (Task 20); `ReopenStep`, `Invitations`, `DeleteDialog` (Task 21); `inviteUrl`, `inviteShareText` (Task 16); `PASSAGES`, `SECTIONS` (`content.ts`); `togetherStatus`.
- Produces: `ChecklistV2({ initialSession?, inviteEmail })`; `ChecklistComparison({ view, onDelete })`; `CHECKLIST_V2_COPY`, `FAQ_V2`, `METADATA_V2` (`v2-copy.ts`); from `checklist-client.tsx`, exported: `GrowArea`, `ImportancePicker`, `StancePicker`, `FrequencyPicker`, `SectionScreen`, `ObligationScreen`, `OpenSectionScreen`, `computeRated`, `type RatedItem`; `ObligationScreen` and `OpenSectionScreen` gain `privateChip?: string` and `commentPlaceholder?: string`.

Flow: intro, then "How are you answering?" (6.1). Couple: the email-and-code step first, because an invite needs a saved session (brief 6.2), then the invite (6.2, 6.3), then today's screens with "Private until you both finish" on each (6.6), then finish: waiting (6.7) or the comparison (6.8, 6.9). Single: today's screens, then "What matters most to you" (6.10) with "Save and get your image" and "Do it with someone". The partner arrives from `/tools/i/{token}` with `?session=`, picks a role and answers. Deleting a comparison (6.11). Answers stay on the device while answering (key `ahavah.marriage-checklist.v6`) and go to the API in one call when the player finishes. Exodus 21:10-11 stays, the husband's passage, as today (owner decision 9).

Strings (6.1 to 6.11) are in `v2-copy.ts`, from the export. "If you join Ahavah, these can become your profile prompts." (6.10) is held behind `PROMPT_DRAFTS_LIVE = false`: prompt drafts belong to the profile prompts release 2, which is not built, so the line would not be true (Spec conflicts, item 6). The comment placeholder names the other person when known ("{name} will see this when you compare", 6.6) and otherwise reads "The other person will see this when you compare" (item 2).

The intro keeps today's screen with two lines changed: the notice becomes 6.1's stored-answers line, and step 3 ("Share your summary") becomes "Compare: answer on your own, or invite your intended or spouse and see where you agree." (item 3). The v1 summary and gate screens are not used in v2.

- [ ] **Step 1: Write the failing test**

Create `tests/components/checklist-v2.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  startSession: vi.fn(), saveAnswers: vi.fn(), finishSession: vi.fn(), getSession: vi.fn(),
  deleteSession: vi.fn(), sendInviteEmail: vi.fn(),
}));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
vi.mock("@/components/together/save-step", () => ({
  SaveStep: ({ onSaved }: { onSaved: (v: unknown) => void }) => (
    <button type="button" onClick={() => onSaved({ session_id: "c1", kind: "checklist", mode: "couple", seat: "owner",
      claimed: true, share_token: "share", invite_token: "inv", state: "playing", my_answers: {} })}>stub save</button>
  ),
  SAVE_PRIVACY: "",
}));

import { ChecklistComparison } from "@/components/app/marriage-checklist/comparison";
import { ChecklistV2 } from "@/components/app/marriage-checklist/checklist-v2";
import { FAQ_V2 } from "@/app/marriage-checklist/v2-copy";

const T = "t".repeat(32);
const STORE = "We keep your answers behind a private link so you can come back to them. Only you and the person you invite can see them. Either of you can delete them at any time.";

describe("the marriage checklist, version 2", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.values(api).forEach((f) => f.mockReset());
    api.startSession.mockResolvedValue({ session_id: "c1", player_token: T });
    api.saveAnswers.mockResolvedValue({ saved: 1 });
  });

  it("asks how you are answering, with the stored-answers line", () => {
    render(<ChecklistV2 inviteEmail={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Begin the checklist/ }));
    expect(screen.getByText("How are you answering?")).toBeTruthy();
    expect(screen.getByText("My non-negotiables")).toBeTruthy();
    expect(screen.getByText("You each answer privately, then compare.")).toBeTruthy();
    expect(screen.getByText(STORE)).toBeTruthy();
    expect(screen.queryByText(/never store/)).toBeNull();
  });

  it("saves first in couple mode, then offers the invite", async () => {
    render(<ChecklistV2 inviteEmail={true} />);
    fireEvent.click(screen.getByRole("button", { name: /Begin the checklist/ }));
    fireEvent.click(screen.getByRole("radio", { name: /With my intended or spouse/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(api.startSession).toHaveBeenCalledWith("checklist", "couple"));
    fireEvent.click(await screen.findByRole("button", { name: "stub save" }));
    expect(await screen.findByText("Email confirmed")).toBeTruthy();
    expect(screen.getByText("Invite your intended or spouse")).toBeTruthy();
    api.sendInviteEmail.mockRejectedValue(new Error("down"));
    fireEvent.change(screen.getByLabelText("Your spouse’s email"), { target: { value: "rivka@example.org" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByText("We could not send the invite. Try again, or share the link instead.")).toBeTruthy();
  });

  it("shows the private chip while a couple answers", async () => {
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "c1", token: T, kind: "checklist", mode: "couple", seat: "guest", savedAt: 1 }]));
    api.getSession.mockResolvedValue({ session_id: "c1", kind: "checklist", mode: "couple", seat: "guest", state: "playing",
      owner_display: "Rivka", claimed: false, my_answers: {}, role: null });
    render(<ChecklistV2 initialSession="c1" inviteEmail={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "I am the husband" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByText("Private until you both finish")).toBeTruthy();
    expect(await screen.findByPlaceholderText("Rivka will see this when you compare")).toBeTruthy();
  });

  it("finishes on your own with what matters most, and holds the prompts line", async () => {
    api.finishSession.mockResolvedValue({ session_id: "c1", kind: "checklist", mode: "single", seat: "owner", state: "ready",
      claimed: false, my_answers: {}, result: { top: [{ key: "p3", ref: "Proverbs 5:15-19", importance: 5 }] } });
    render(<ChecklistV2 inviteEmail={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Begin the checklist/ }));
    fireEvent.click(screen.getByRole("radio", { name: /On my own/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(api.startSession).toHaveBeenCalledWith("checklist", "single"));
    fireEvent.click(await screen.findByRole("button", { name: "I am the wife" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
    for (let i = 0; i < 8; i++) {
      fireEvent.click(await screen.findByRole("radio", { name: "4" }));
      fireEvent.click(screen.getByRole("radio", { name: "Agree" }));
      fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    }
    fireEvent.click(await screen.findByRole("button", { name: /Continue/ }));
    fireEvent.click(await screen.findByRole("button", { name: /See your summary/ }));
    expect(await screen.findByText("What matters most to you")).toBeTruthy();
    expect(screen.queryByText("If you join Ahavah, these can become your profile prompts.")).toBeNull();
    expect(screen.getByRole("button", { name: "Do it with someone" })).toBeTruthy();
    const [, , answers, role] = api.saveAnswers.mock.calls[0];
    expect(role).toBe("wife");
    expect(answers.map((a: { question_key: string }) => a.question_key)).not.toContain("p2");
    expect(answers).toHaveLength(8);
  });

  it("compares two people item by item, with what to talk about", () => {
    const view = {
      session_id: "c1", owner_display: "Daniel", guest_display: "Rivka", seat: "owner",
      result: {
        agree: 1, total: 2,
        agree_items: [{ key: "p1", ref: "Genesis 2:18-24", owner: { importance: 4, stance: "agree" }, guest: { importance: 5, stance: "agree" } }],
        talk_items: [{ key: "p3", ref: "Proverbs 5:15-19", tag: "stance", owner: { importance: 3, stance: "agree" },
          guest: { importance: 5, stance: "other", other_note: "Near my parents" } }],
        own: { owner: [{ key: "own-garden1", section: "nice-to-have", title: "A garden we grow together", importance: 4 }], guest: [] },
      },
    };
    render(<ChecklistComparison view={view as never} onDelete={vi.fn()} />);
    expect(screen.getByText("1 of 2 in agreement")).toBeTruthy();
    expect(screen.getByText("Each person’s comments show here to the other.")).toBeTruthy();
    expect(screen.getByText("Different stance")).toBeTruthy();
    expect(screen.getByText("A garden we grow together")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete this comparison" })).toBeTruthy();
  });

  it("says when there is nothing to talk about and no own items", () => {
    const view = { session_id: "c1", owner_display: "D.", guest_display: "R.", seat: "guest",
      result: { agree: 1, total: 1, agree_items: [], talk_items: [], own: { owner: [], guest: [] } } };
    render(<ChecklistComparison view={view as never} onDelete={vi.fn()} />);
    expect(screen.getByText("You agree on everything you both rated.")).toBeTruthy();
    expect(screen.getByText("Neither of you added your own items.")).toBeTruthy();
  });

  it("answers the FAQ truthfully for version 2", () => {
    const stored = FAQ_V2.find((f) => f.q === "Do you store my answers?")!;
    expect(stored.a).toMatch(/^Yes/);
    expect(stored.a).toContain("12 months after your last visit");
    expect(JSON.stringify(FAQ_V2)).not.toMatch(/never stored|discard|dating|\u2014/i);
  });
});
```

The single-mode test walks the 8 passages a wife answers (Exodus 21:10-11 is the husband's), then the two open sections. It assumes `ImportancePicker` buttons are `role="radio"` named by their number and `StancePicker` buttons named "Agree", as today.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/checklist-v2.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/marriage-checklist/comparison"`.

- [ ] **Step 3: Write the copy**

Create `src/app/marriage-checklist/v2-copy.ts`:

```ts
/**
 * The marriage checklist v2's words (TEC-1845): the export's (handoff/copy/
 * 07-together.md, section 6) and the page's FAQ and description, which the
 * owner delegated and this plan wrote to say what v2 does with answers.
 */
export const CHECKLIST_V2_COPY = {
  store: "We keep your answers behind a private link so you can come back to them. Only you and the person you invite can see them. Either of you can delete them at any time.",
  howAnswering: "How are you answering?",
  onMyOwn: "On my own",
  nonNegotiables: "My non-negotiables",
  withSpouse: "With my intended or spouse",
  eachPrivately: "You each answer privately, then compare.",
  emailConfirmed: "Email confirmed",
  inviteHeading: "Invite your intended or spouse",
  spouseEmail: "Your spouse’s email",
  sendInvite: "Send invite",
  inviteFailed: "We could not send the invite. Try again, or share the link instead.",
  privateChip: "Private until you both finish",
  commentPlaceholder: (name: string | null) =>
    name ? `${name} will see this when you compare` : "The other person will see this when you compare", // the fallback is not in the export
  waiting: (name: string | null) => (name ? `Waiting for ${name}` : "Waiting for the other player"), // the fallback is not in the export
  waitingLine: "Your answers stay private until you have both finished.",
  inAgreement: (agree: number, total: number) => `${agree} of ${total} in agreement`,
  commentsShow: "Each person’s comments show here to the other.",
  whereAgree: "Where you agree",
  talkAbout: "Talk about these",
  differentStance: "Different stance",
  importanceApart: "Importance 2 apart",
  ownItems: "Your own items",
  niceToHaves: "Nice to haves",
  challenges: "Challenges and obstacles",
  deleteComparison: "Delete this comparison",
  deleteQuestion: "Delete this comparison for both of you? This cannot be undone.",
  deleted: "This comparison was deleted",
  nothingToTalk: "You agree on everything you both rated.",
  noOwnItems: "Neither of you added your own items.",
  whatMatters: "What matters most to you",
  promptsLine: "If you join Ahavah, these can become your profile prompts.",
  doWithSomeone: "Do it with someone",
  saveImage: "Save and get your image",
  // Not in the export: step 3 of today's intro, which promised a summary
  // sent to you both.
  introCompareTitle: "Compare",
  introCompareBody: "Answer on your own, or invite your intended or spouse and see where you agree.",
};

/** Prompt drafts are the profile prompts release 2, not built yet; until
 *  then 6.10's promise would not be true (plan, Spec conflicts 6). */
export const PROMPT_DRAFTS_LIVE = false;

export const METADATA_V2 = {
  description:
    "A free, guided marriage checklist for Torah-observant couples. Work through biblical obligations, rate what matters most to you, and compare answers with your intended or spouse. Your answers stay private and you can delete them at any time.",
};

export const FAQ_V2: Array<{ q: string; a: string }> = [
  {
    q: "Is the marriage checklist free?",
    a: "Yes. The checklist is a free activity from Ahavah. You confirm your email with a one-time code to save your answers or to compare them with someone, and no matchmaking profile is required.",
  },
  {
    q: "Do you store my answers?",
    a: "Yes, once you save them. We keep them behind a private link so you can come back to them. Only you and the person you invite can see them, and either of you can delete them at any time. We delete them 12 months after your last visit.",
  },
  {
    q: "Which Bible passages are included?",
    a: "Section one covers Genesis 2:18-24, Exodus 21:10-11, Proverbs 5:15-19, 1 Corinthians 7:2-5, Ephesians 5:22-33, Colossians 3:18-19, 1 Peter 3:1-7, Malachi 2:14-16 and Hebrews 13:4, quoted verbatim from the KJV and linked to the full passage on YouVersion.",
  },
  {
    q: "Can I use it if I am single?",
    a: "Yes. Answer on your own to write down your non-negotiables, or invite someone you are courting to answer too and compare.",
  },
  {
    q: "How does my spouse get the results?",
    a: "Invite your intended or spouse by link or email. Each of you answers privately, and once you have both finished you each see where you agree and what to talk about. We also email each of you your own summary.",
  },
  {
    q: "Who made the marriage checklist?",
    a: "Ahavah, the matchmaking platform for Messianic and Torah-observant believers seeking a spouse across borders.",
  },
];
```

The passages answer drops today's serial comma before "and Hebrews 13:4"; the v1 FAQ keeps it until v1 is removed.

- [ ] **Step 4: Export the shared screens**

In `src/components/app/marriage-checklist/checklist-client.tsx`:

- Add `export` before `function GrowArea`, `function ImportancePicker`, `function StancePicker`, `function FrequencyPicker`, `function SectionScreen`, `function ObligationScreen`, `function OpenSectionScreen`, `function computeRated` and `type RatedItem`.
- In `ObligationScreen`'s props add `privateChip?: string; commentPlaceholder?: string;`, render `{privateChip ? <span className="mc-pill mc-pill--private">{privateChip}</span> : null}` inside `mc-chip-row` after the role tag, and use `placeholder={commentPlaceholder ?? "In your own words."}` on the "What does this mean to you?" field.
- In `OpenSectionScreen`'s props add the same two, render the chip in each item's `mc-item-head`, and use `commentPlaceholder ?? "In your own words."` on "Your notes".

v1 passes neither, so it renders exactly as before.

- [ ] **Step 5: Write the comparison and the v2 client**

Create `src/components/app/marriage-checklist/comparison.tsx`:

```tsx
"use client";

/** The comparison (TEC-1845; export 6.8, 6.9). At 390 each item stacks one person above the other, labelled with initials. */
import { CHECKLIST_V2_COPY as C } from "@/app/marriage-checklist/v2-copy";
import type { Comparison, ComparisonSide, OwnItem, SessionView } from "@/lib/together/api";

const STANCE = { agree: "Agree", disagree: "Disagree", other: "Other" } as const;
const initials = (name: string | null) => (name ? `${name.trim().charAt(0).toUpperCase()}.` : "");

function side(s: ComparisonSide): string {
  const parts = [s.stance ? STANCE[s.stance] : null, `importance ${s.importance}`].filter(Boolean).join(" · ");
  const said = s.other_note ?? s.comment;
  return said ? `${parts}. “${said}”` : parts;
}

function Row({ who, text }: { who: string; text: string }) {
  return <div className="mc2-row"><span className="av">{who}</span><span>{text}</span></div>;
}

export function ChecklistComparison({ view, onDelete }: { view: SessionView; onDelete: () => void }) {
  const r = view.result as Comparison;
  const o = initials(view.owner_display);
  const g = initials(view.guest_display);
  const own = (items: OwnItem[], section: OwnItem["section"]) => items.filter((i) => i.section === section).map((i) => i.title).join("; ");
  return (
    <div className="mc2-compare">
      <span className="ov">{`${view.owner_display ?? ""} and ${view.guest_display ?? ""}`}</span>
      <h1>{C.inAgreement(r.agree, r.total)}</h1>
      <p className="ps">{C.commentsShow}</p>
      <section>
        <h2>{C.whereAgree}</h2>
        {r.agree_items.map((i) => (
          <div key={i.key} className="card"><b>{i.ref}</b><Row who={o} text={side(i.owner)} /><Row who={g} text={side(i.guest)} /></div>
        ))}
      </section>
      <section>
        <h2>{C.talkAbout}</h2>
        {r.talk_items.length === 0 ? <p className="ps">{C.nothingToTalk}</p> : r.talk_items.map((i) => (
          <div key={i.key} className="card">
            <b>{i.ref}</b><span className="chip">{i.tag === "stance" ? C.differentStance : C.importanceApart}</span>
            <Row who={o} text={side(i.owner)} /><Row who={g} text={side(i.guest)} />
          </div>
        ))}
      </section>
      <section>
        <h2>{C.ownItems}</h2>
        {r.own.owner.length + r.own.guest.length === 0 ? <p className="ps">{C.noOwnItems}</p> : (
          <>
            <div className="card"><b>{C.niceToHaves}</b><Row who={o} text={own(r.own.owner, "nice-to-have")} /><Row who={g} text={own(r.own.guest, "nice-to-have")} /></div>
            <div className="card"><b>{C.challenges}</b><Row who={o} text={own(r.own.owner, "challenge")} /><Row who={g} text={own(r.own.guest, "challenge")} /></div>
          </>
        )}
      </section>
      <button type="button" onClick={onDelete}>{C.deleteComparison}</button>
    </div>
  );
}
```

Create `src/components/app/marriage-checklist/checklist-v2.tsx`:

```tsx
"use client";

/**
 * The marriage checklist, version 2 (TEC-1845; export section 6): on your
 * own ("My non-negotiables") or with your intended or spouse, answering
 * privately and comparing once both have finished. Today's answering
 * screens are reused unchanged, with the private chip in couple mode.
 * Answers stay on this device while answering and go to the API in one
 * call when the player finishes.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { AntibotFields, type AntibotHandle } from "@/components/app/antibot-fields";
import {
  ObligationScreen, OpenSectionScreen, SectionScreen, computeRated,
} from "@/components/app/marriage-checklist/checklist-client";
import { ChecklistComparison } from "@/components/app/marriage-checklist/comparison";
import { DeleteDialog, Invitations, ReopenStep, ResultDeleted } from "@/components/together/result-states";
import { SaveStep } from "@/components/together/save-step";
import { SharePanel } from "@/components/together/share-panel";
import { PASSAGES, type CustomItem, type PassageAnswer, type Role } from "@/app/marriage-checklist/content";
import { CHECKLIST_V2_COPY as C, PROMPT_DRAFTS_LIVE } from "@/app/marriage-checklist/v2-copy";
import { getSessionToken } from "@/lib/api-client";
import {
  type SessionView, type SingleResult, deleteSession, finishSession, getSession, saveAnswers, sendInviteEmail, startSession,
} from "@/lib/together/api";
import { inviteShareText, inviteUrl } from "@/lib/together/share";
import { forgetSession, rememberSession, sessionById } from "@/lib/together/storage";

type Step =
  | { kind: "intro" } | { kind: "mode" } | { kind: "save" } | { kind: "invite" } | { kind: "role" }
  | { kind: "passage"; i: number } | { kind: "open"; section: "nice-to-have" | "challenge" }
  | { kind: "result" } | { kind: "reopen" } | { kind: "deleted" };

export function ChecklistV2({ initialSession, inviteEmail }: { initialSession?: string; inviteEmail: boolean }) {
  const [step, setStep] = useState<Step>({ kind: initialSession ? "role" : "intro" });
  const [mode, setMode] = useState<"single" | "couple">("couple");
  const [sid, setSid] = useState<string | null>(initialSession ?? null);
  const [token, setToken] = useState<string | null>(null);
  const [seat, setSeat] = useState<"owner" | "guest">("owner");
  const [other, setOther] = useState<string | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [answers, setAnswers] = useState<Record<string, PassageAnswer>>({});
  const [custom, setCustom] = useState<CustomItem[]>([]);
  const [view, setView] = useState<SessionView | null>(null);
  const [inviteState, setInviteState] = useState<"idle" | "failed" | "sent">("idle");
  const [spouse, setSpouse] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const antibot = useRef<AntibotHandle>(null);
  const passages = useMemo(() => PASSAGES.filter((p) => role && p.roles.includes(role)), [role]);

  useEffect(() => {
    if (!initialSession) return;
    const stored = sessionById(initialSession);
    if (!stored && !getSessionToken()) { setStep({ kind: "reopen" }); return; }
    const t = stored?.token || null;
    setToken(t);
    getSession(initialSession, t).then((v) => {
      setMode(v.mode === "single" ? "single" : "couple");
      setSeat(v.seat);
      setOther(v.seat === "owner" ? v.guest_display : v.owner_display);
      if (v.state !== "playing") { setView(v); setStep({ kind: "result" }); }
    }).catch(() => setStep({ kind: "deleted" }));
  }, [initialSession]);

  const begin = async (m: "single" | "couple") => {
    setMode(m);
    const s = await startSession("checklist", m);
    rememberSession({ sessionId: s.session_id, token: s.player_token, kind: "checklist", mode: m, seat: "owner" });
    setSid(s.session_id);
    setToken(s.player_token);
    setStep({ kind: m === "couple" ? "save" : "role" });
  };

  const finish = async () => {
    if (!sid) return;
    const rated = computeRated(answers, custom);
    const items = rated.map((r) => ({
      question_key: r.section === "biblical" ? (r as { id: string }).id : `own-${(r as { id: string }).id.toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 40)}`,
      answer: {
        section: r.section, importance: r.importance,
        ...("title" in r && r.title ? { title: r.title } : {}),
        ...(r.stance ? { stance: r.stance } : {}), ...(r.frequency ? { frequency: r.frequency } : {}),
        ...(r.comment ? { comment: r.comment } : {}), ...(r.examples ? { examples: r.examples } : {}),
        ...(r.otherNote ? { other_note: r.otherNote } : {}),
      },
    }));
    await saveAnswers(sid, token, items, role);
    const v = await finishSession(sid, token);
    setView(v);
    setStep({ kind: "result" });
  };

  const placeholder = mode === "couple" ? C.commentPlaceholder(other) : undefined;
  const chip = mode === "couple" ? C.privateChip : undefined;

  switch (step.kind) {
    case "reopen": return <ReopenStep onOpened={() => window.location.reload()} />;
    case "deleted": return <ResultDeleted line={C.deleted} />;
    case "intro":
      return (
        <div className="mc2-intro">
          <p>{C.store}</p>
          <p><b>{C.introCompareTitle}</b> {C.introCompareBody}</p>
          <button type="button" onClick={() => setStep({ kind: "mode" })}>Begin the checklist</button>
        </div>
      );
    case "mode":
      return (
        <div className="mc2-mode">
          <span className="ov">The marriage checklist</span>
          <h1>{C.howAnswering}</h1>
          <div role="radiogroup" aria-label={C.howAnswering}>
            <button type="button" role="radio" aria-checked={mode === "single"} onClick={() => setMode("single")}><b>{C.onMyOwn}</b><span>{C.nonNegotiables}</span></button>
            <button type="button" role="radio" aria-checked={mode === "couple"} onClick={() => setMode("couple")}><b>{C.withSpouse}</b><span>{C.eachPrivately}</span></button>
          </div>
          <p className="cap">{C.store}</p>
          <button type="button" onClick={() => void begin(mode)}>Continue</button>
        </div>
      );
    case "save":
      return sid ? (
        <SaveStep sessionId={sid} token={token} mode={mode}
          onSaved={(v) => { setView(v); setStep({ kind: v.mode === "single" ? "result" : "invite" }); }} />
      ) : null;
    case "invite": {
      const link = inviteUrl(view?.invite_token ?? "");
      return (
        <div className="mc2-invite">
          <AntibotFields ref={antibot} />
          <span className="chip ok">{C.emailConfirmed}</span>
          <h1>{C.inviteHeading}</h1>
          <button type="button" onClick={() => void (navigator.share?.({ text: inviteShareText("checklist", link) }).catch(() => undefined))}>Share</button>
          <button type="button" onClick={() => void navigator.clipboard?.writeText(link)}>Copy link</button>
          {inviteEmail ? (
            <>
              <label>{C.spouseEmail}<input type="email" value={spouse} onChange={(e) => setSpouse(e.target.value)} /></label>
              <button type="button" onClick={async () => {
                try { await sendInviteEmail(sid ?? "", token, spouse.trim(), antibot.current?.payload() ?? {}); setInviteState("sent"); }
                catch { setInviteState("failed"); }
              }}>{inviteState === "failed" ? "Try again" : C.sendInvite}</button>
              {inviteState === "failed" ? <p role="alert">{C.inviteFailed}</p> : null}
            </>
          ) : null}
          <button type="button" onClick={() => setStep({ kind: "role" })}>Continue</button>
        </div>
      );
    }
    case "role":
      return <SectionScreen role={role} setRole={setRole} onNext={() => setStep({ kind: "passage", i: 0 })} onBack={() => setStep({ kind: seat === "guest" ? "role" : "mode" })} />;
    case "passage": {
      const p = passages[step.i];
      if (!p) return null;
      return (
        <ObligationScreen passage={p} role={role} answer={answers[p.id]} privateChip={chip} commentPlaceholder={placeholder}
          setAnswer={(a) => setAnswers((prev) => ({ ...prev, [p.id]: a }))}
          onNext={() => setStep(step.i + 1 < passages.length ? { kind: "passage", i: step.i + 1 } : { kind: "open", section: "nice-to-have" })}
          onBack={() => setStep(step.i > 0 ? { kind: "passage", i: step.i - 1 } : { kind: "role" })} />
      );
    }
    case "open":
      return (
        <OpenSectionScreen section={step.section} items={custom} setItems={setCustom} privateChip={chip} commentPlaceholder={placeholder}
          onNext={() => (step.section === "nice-to-have" ? setStep({ kind: "open", section: "challenge" }) : void finish())}
          onBack={() => setStep(step.section === "challenge" ? { kind: "open", section: "nice-to-have" } : { kind: "passage", i: passages.length - 1 })} />
      );
    case "result": {
      if (!view) return null;
      if (view.mode === "single") {
        if (view.share_token) return <SharePanel shareToken={view.share_token} mode="single" summary={{}} />;
        const top = (view.result as SingleResult).top;
        return (
          <div className="mc2-single">
            <span className="ov">{C.nonNegotiables}</span>
            <h1>{C.whatMatters}</h1>
            <ol>{top.map((t) => <li key={t.key}><b>{t.ref ?? t.title}</b><span>{`Importance ${t.importance}`}</span></li>)}</ol>
            {PROMPT_DRAFTS_LIVE ? <p>{C.promptsLine}</p> : null}
            <button type="button" onClick={() => setStep({ kind: "save" })}>{C.saveImage}</button>
            <button type="button" onClick={() => void begin("couple")}>{C.doWithSomeone}</button>
            <Invitations />
          </div>
        );
      }
      if (view.state === "waiting") {
        return <div className="mc2-wait"><h1>{C.waiting(other)}</h1><p>{C.waitingLine}</p></div>;
      }
      return (
        <>
          <ChecklistComparison view={view} onDelete={() => setConfirmDelete(true)} />
          {confirmDelete ? (
            <DeleteDialog question={C.deleteQuestion} onCancel={() => setConfirmDelete(false)} onDelete={async () => {
              await deleteSession(view.session_id, token);
              forgetSession(view.session_id);
              setStep({ kind: "deleted" });
            }} />
          ) : null}
        </>
      );
    }
  }
}
```

Single mode's "Save and get your image" opens the same save step; once saved, the result step shows the share panel.

The own-item keys are made from today's item ids (`nice-to-have-<timestamp>-<random>`), lower-cased and cut to 40 characters after `own-`, which the API's `own-[a-z0-9-]{6,40}` accepts.

- [ ] **Step 6: Choose v1 or v2 on the page, dark first**

In `src/app/marriage-checklist/page.tsx`:

- Replace `export const metadata: Metadata = {...}` with `export async function generateMetadata(): Promise<Metadata>` returning today's object, with `description` set to `METADATA_V2.description` when `(await togetherStatus()).live`.
- Make the page `async`; read `const live = (await togetherStatus()).live;` render `{live ? <ChecklistV2 inviteEmail={status.inviteEmail} initialSession={session} /> : <ChecklistClient />}` (with `searchParams: Promise<{ session?: string }>` read for `session`), and use `const faq = live ? FAQ_V2 : FAQ;` for both the visible FAQ and the JSON-LD. In the JSON-LD `HowTo`, when live, step 4 reads `{ name: "Compare your answers", text: "Invite your intended or spouse, then see where you agree and what to talk about." }` (Spec conflicts 3).
- Add `export const dynamic = "force-dynamic";`.

In `src/app/marriage-checklist/content.ts`, replace the docstring lines:

```ts
 * Copy rule: NO em dashes in any string (customer-facing hard rule).
 * Answers live in client state (mirrored to localStorage mid-session),
 * are emailed via POST /marriage-checklist/send, and never persisted.
```

with:

```ts
 * Copy rule: NO em dashes in any string (customer-facing hard rule).
 * The first checklist (checklist-client.tsx) keeps answers in client
 * state and emails them via POST /marriage-checklist/send, which stores
 * nothing. Version 2 (checklist-v2.tsx, TEC-1845) saves them behind a
 * private link through the API's /tools routes, readable only by the
 * players, deleted 12 months after the last visit or on request.
```

In `src/app/marriage-checklist/marriage-checklist.css`, add a v2 block: `.mc2` takes the app's dark tokens (the export's `ahv-kit.css` dark values, ported by `/sot-sync`) and, under the light theme (`[data-theme="light"] .mc2`, as the app's theme switch sets it), today's paper canvas values (`--mc-paper` and the rest of `.mc`'s light palette, lines 13 to 15). Owner decision 13: dark first, paper as the light variant.

- [ ] **Step 7: Run tests and match the export**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/checklist-v2.test.tsx`
Expected: PASS (7 new). Then `npx tsc --noEmit` reports no errors.

Run `/sot-sync "Claude Design/Ahavah Together.html" "Section 6"` and transcribe frames 6.1 to 6.11 (390, 768 and 1440; dark and light, the paper canvas for light): the comparison stacks at 390, one person above the other with initials, never 2 columns that push the page sideways. 6.12 is the email (Task 10). On the first phone screen: the comparison's head and the first item of "Where you agree". Re-run the tests.

- [ ] **Step 8: After launch, remove v1**

Not before Task 29 Step 7. One week after launch, with no errors from v2 in that week: delete `ChecklistClient`'s own screens that v2 does not use (`IntroScreen` stays if v2 now renders it, `SummaryScreen`, `GateScreen`, `DoneScreen`), `src/lib/marriage-checklist.ts`, the v1 `FAQ` and the `live` branch in `page.tsx`; keep the API's `/marriage-checklist/send` (it stores nothing and costs nothing) and record in its docstring that no client calls it. The v1 code step's "We do not add you to any dating emails." goes with it (Spec conflicts 14). Run the checklist tests and commit separately (`refactor(checklist): remove the first checklist after v2's launch`).

- [ ] **Step 9: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/marriage-checklist/checklist-client.tsx src/components/app/marriage-checklist/checklist-v2.tsx src/components/app/marriage-checklist/comparison.tsx src/app/marriage-checklist/v2-copy.ts src/app/marriage-checklist/page.tsx src/app/marriage-checklist/content.ts src/app/marriage-checklist/marriage-checklist.css tests/components/checklist-v2.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(checklist): version 2, on your own or as a couple, private until you both finish, then compared" -m "Refs: TEC-1845"
```

---

### Task 25: "Play Us together" from a match's chat

**Files:**
- Create: `src/components/app/chat-more-menu.tsx`
- Modify: `src/components/app/chat-thread-view.tsx` (the More button opens the menu)
- Modify: `src/components/together/game-result.tsx` (back to the chat with the invite in the message box)
- Test: `tests/components/chat-play-us.test.tsx` (create)

**Interfaces:**
- Consumes: `startSession`, `claimSession` (Task 15); `rememberSession` (Task 15); `useProfile`; `inviteUrl`, `inviteShareText` (Task 16); the chat's existing `?prefill=` (`chat-thread-view.tsx`, read once and removed from the URL).
- Produces: `ChatMoreMenu({ prospectUuid, onReport, onClose })` with "Play Us together" (only while Together is live, from `GET /tools/status`), "View profile" and "Report" (export 9.1); starting shows "Starting the game" and a failure "We could not start the game. Try again." (9.2, 9.3); `GameResult` with `chat` set sends a member who has finished and saved to `/chat/{uuid}?prefill=` with "I played Ahavah’s compatibility game. Want to see how we fit? {link}" (9.2).

The member plays first, then returns to the chat with the invite ready to send: the prefilled line says "I played", so it is offered only once they have (Spec conflicts, item 9). The match opens the link signed in and starts with no email step (Task 22). The export's menu also has "Unmatch", which the chat has no action for today; it is not built here (Spec conflicts, item 9).

- [ ] **Step 1: Write the failing test**

Create `tests/components/chat-play-us.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const api = vi.hoisted(() => ({ startSession: vi.fn(), claimSession: vi.fn(), getSession: vi.fn(), getStatus: vi.fn() }));
vi.mock("@/lib/together/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/together/api")>()), ...api,
}));
vi.mock("@/lib/use-profile", () => ({ useProfile: () => ({ profile: { firstName: "Samuel" } }) }));

import { ChatMoreMenu } from "@/components/app/chat-more-menu";
import { GameResult } from "@/components/together/game-result";

const T = "t".repeat(32);
const UUID = "0f8fad5b-d9cb-469f-a165-70867728950e";

describe("Play Us together", () => {
  beforeEach(() => {
    window.localStorage.clear();
    router.push.mockReset();
    router.replace.mockReset();
    Object.values(api).forEach((f) => f.mockReset());
    api.getStatus.mockResolvedValue({ live: true, invite_email: false });
  });

  it("is first in the chat's More menu", async () => {
    render(<ChatMoreMenu prospectUuid={UUID} onReport={vi.fn()} onClose={vi.fn()} />);
    await screen.findByRole("menuitem", { name: "Play Us together" });
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Play Us together", "View profile", "Report"]);
  });

  it("is left out while Together is dark", async () => {
    api.getStatus.mockResolvedValue({ live: false, invite_email: false });
    render(<ChatMoreMenu prospectUuid={UUID} onReport={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(api.getStatus).toHaveBeenCalled());
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["View profile", "Report"]);
  });

  it("starts an Us game saved to the member's account and opens it", async () => {
    api.startSession.mockResolvedValue({ session_id: "s1", player_token: T });
    api.claimSession.mockResolvedValue({ session_id: "s1", invite_token: "inv" });
    render(<ChatMoreMenu prospectUuid={UUID} onReport={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Play Us together" }));
    expect(screen.getByText("Starting the game")).toBeTruthy();
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/together/game?session=s1&chat=${UUID}`));
    expect(api.startSession).toHaveBeenCalledWith("game", "us");
    expect(api.claimSession).toHaveBeenCalledWith("s1", T, "Samuel");
  });

  it("says when the game could not start", async () => {
    api.startSession.mockRejectedValue(new Error("down"));
    render(<ChatMoreMenu prospectUuid={UUID} onReport={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Play Us together" }));
    expect(await screen.findByText("We could not start the game. Try again.")).toBeTruthy();
  });

  it("returns to the chat with the invite in the message box once the member has played", async () => {
    window.localStorage.setItem("ahavah.together.v1", JSON.stringify([{ sessionId: "s1", token: T, kind: "game", mode: "us", seat: "owner", savedAt: 1 }]));
    api.getSession.mockResolvedValue({ session_id: "s1", kind: "game", mode: "us", seat: "owner", state: "waiting", claimed: true,
      member: true, invite_token: "inv", my_answers: {}, result: null, owner_display: "Samuel", guest_display: null });
    render(<GameResult initialSession="s1" chat={UUID} inviteEmail={false} />);
    const text = "I played Ahavah’s compatibility game. Want to see how we fit? https://ahavah.app/tools/i/inv";
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith(`/chat/${UUID}?prefill=${encodeURIComponent(text)}`));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/chat-play-us.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/chat-more-menu"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/app/chat-more-menu.tsx`:

```tsx
"use client";

/**
 * The chat's More menu (TEC-1845; export 9.1 to 9.3): "Play Us together"
 * starts an Us game already saved to the member's account and opens it;
 * once they have played, the game returns them here with the invite in the
 * message box (src/components/together/game-result.tsx).
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { claimSession, getStatus, startSession } from "@/lib/together/api";
import { rememberSession } from "@/lib/together/storage";
import { useProfile } from "@/lib/use-profile";

export function ChatMoreMenu({ prospectUuid, onReport, onClose }: {
  prospectUuid: string; onReport: () => void; onClose: () => void;
}) {
  const router = useRouter();
  const { profile } = useProfile();
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  // Offered only once Together is live (the API's together_live).
  const [live, setLive] = useState(false);
  useEffect(() => {
    getStatus().then((s) => setLive(s.live)).catch(() => setLive(false));
  }, []);
  const play = async () => {
    setState("busy");
    try {
      const s = await startSession("game", "us");
      rememberSession({ sessionId: s.session_id, token: s.player_token, kind: "game", mode: "us", seat: "owner" });
      const v = await claimSession(s.session_id, s.player_token, (profile.firstName ?? "").trim() || "Me");
      router.push(`/together/game?session=${v.session_id}&chat=${prospectUuid}`);
    } catch {
      setState("failed");
    }
  };
  return (
    <div className="chat-more-menu" role="menu" aria-label="More">
      {live ? <button type="button" role="menuitem" disabled={state === "busy"} onClick={() => void play()}>Play Us together</button> : null}
      <Link role="menuitem" href={`/profile/${prospectUuid}`} prefetch={false} onClick={onClose}>View profile</Link>
      <button type="button" role="menuitem" onClick={() => { onClose(); onReport(); }}>Report</button>
      {state === "busy" ? <p className="cap" aria-live="polite">Starting the game</p> : null}
      {state === "failed" ? <p role="alert">We could not start the game. Try again.</p> : null}
    </div>
  );
}
```

`claimSession` needs a display name; a member with no first name on file is saved as "Me", which no screen reaches in practice (a member always has a first name after onboarding).

In `src/components/app/chat-thread-view.tsx`, add `import { ChatMoreMenu } from "@/components/app/chat-more-menu";` and `const [menuOpen, setMenuOpen] = useState(false);`, change `onMoreClick={() => setReportOpen(true)}` to `onMoreClick={() => setMenuOpen((o) => !o)}`, and after `<ChatHeader ... />` add:

```tsx
      {menuOpen && isUuidLike(id) ? (
        <ChatMoreMenu prospectUuid={id} onReport={() => setReportOpen(true)} onClose={() => setMenuOpen(false)} />
      ) : null}
```

In `src/components/together/game-result.tsx`, add `import { useRouter } from "next/navigation";`, `import { inviteShareText, inviteUrl } from "@/lib/together/share";`, `const router = useRouter();` at the top of `GameResult`, and this effect after the others:

```tsx
  // From a match's chat (9.2): once the member has played and the game is
  // saved, back to the chat with the invite in the message box.
  useEffect(() => {
    if (!chat || !view || view.mode !== "us" || view.seat !== "owner" || !view.invite_token) return;
    if (view.state === "playing") return;
    const text = inviteShareText("game", inviteUrl(view.invite_token));
    router.replace(`/chat/${chat}?prefill=${encodeURIComponent(text)}`);
  }, [chat, view, router]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/chat-play-us.test.tsx tests/components/together-results.test.tsx`
Expected: PASS (5 new; the results suite unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "Sections 8 and 9"` and transcribe 9.1 to 9.5 (390, 768 and 1440; dark and light): the menu as the export's card under the More button with 44 px rows, the busy line and the error above the message box. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/chat-more-menu.tsx src/components/app/chat-thread-view.tsx src/components/together/game-result.tsx tests/components/chat-play-us.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): Play Us together from a match's chat, back with the invite ready to send" -m "Refs: TEC-1845"
```

---

### Task 26: Answers carried into sign-up and onboarding

**Files:**
- Create: `src/lib/together/carry.ts`, `src/components/together/from-your-game.tsx`
- Modify: `src/components/together/game-result.tsx` (write the carry when a game finishes), `src/components/app/marriage-checklist/checklist-v2.tsx` (write the checklist's source)
- Modify: `src/app/auth/sign-up/page.tsx` (the line), `src/app/onboarding/verify-email/page.tsx` (the source), `src/app/onboarding/relocation/page.tsx`, `src/app/onboarding/languages/page.tsx` (filled from the game), `src/app/onboarding/complete/page.tsx` (the rest of the fields, then clear)
- Test: `tests/lib/together-carry.test.ts`, `tests/app/together-carry-onboarding.test.tsx` (create)

**Interfaces:**
- Consumes: `answersToProfile` (Task 16); `SOURCE_OF`, `ToolSource` (Task 15); `useProfile().update`; `checkOtp` with `source` (Task 15).
- Produces: `writeCarry({ source, profile, checklistTop? })`, `readCarry(now?) -> Carry | null` (30 day life), `clearCarry()`, `carriedSource() -> ToolSource | null`, `CARRY_LATER_FIELDS`; `FromYourGame` (export 8.2: "From your game", "We filled this from your game. Change it if you like."); the sign-up line (8.1): "Your answers will fill part of your profile. You can change them."

What carries: the player's own game answers as profile fields (never a friend's guesses, which are about someone else). Onboarding asks relocation and languages itself, so those two are filled on their screens with the tag; country is left for the player to pick on its own screen; the other six (calendar, Torah walk, feasts, family, home, how you talk) have no onboarding screen and are written once onboarding completes, only where the profile is still empty. The checklist carries its source, and the single's top items for the profile prompts release (Spec conflicts, item 6). The sign-up's source is the tool's (`tool:game-me`, `tool:game-us`, `tool:knows-me`, `tool:checklist`).

- [ ] **Step 1: Write the failing tests**

Create `tests/lib/together-carry.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";

import { CARRY_LATER_FIELDS, carriedSource, clearCarry, readCarry, writeCarry } from "@/lib/together/carry";

describe("the sign-up carry", () => {
  beforeEach(() => window.localStorage.clear());

  it("keeps a player's game answers and source for 30 days", () => {
    writeCarry({ source: "tool:game-us", profile: { relocation: "will-relocate", calendar: "enoch" } }, 1_000);
    expect(readCarry(1_000 + 29 * 86_400_000)?.profile.relocation).toBe("will-relocate");
    expect(readCarry(1_000 + 31 * 86_400_000)).toBeNull();
    writeCarry({ source: "tool:game-us", profile: {} });
    expect(carriedSource()).toBe("tool:game-us");
  });

  it("is cleared after use and survives broken storage", () => {
    writeCarry({ source: "tool:checklist", profile: {} });
    clearCarry();
    expect(readCarry()).toBeNull();
    window.localStorage.setItem("ahavah.together.carry.v1", "{oops");
    expect(readCarry()).toBeNull();
  });

  it("writes later only the fields onboarding does not ask", () => {
    expect(CARRY_LATER_FIELDS).toEqual(["calendar", "torahLevel", "feastDays", "familyViews", "livingPreferences", "communicationPrefs"]);
  });
});
```

Create `tests/app/together-carry-onboarding.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const prof = vi.hoisted(() => ({ profile: {} as Record<string, unknown>, update: vi.fn() }));
vi.mock("@/lib/use-profile", () => ({ useProfile: () => prof }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/onboarding/relocation" }));

import RelocationStep from "@/app/onboarding/relocation/page";
import { writeCarry } from "@/lib/together/carry";

describe("onboarding filled from the game", () => {
  beforeEach(() => {
    window.localStorage.clear();
    prof.profile = {};
    prof.update.mockReset().mockResolvedValue(undefined);
  });

  it("fills relocation from the game and says so", async () => {
    writeCarry({ source: "tool:game-me", profile: { relocation: "international-open" } });
    render(<RelocationStep />);
    await waitFor(() => expect(prof.update).toHaveBeenCalledWith({ relocation: "international-open" }));
    expect(screen.getByText("From your game")).toBeTruthy();
    expect(screen.getByText("We filled this from your game. Change it if you like.")).toBeTruthy();
  });

  it("never overwrites what the member already chose", async () => {
    writeCarry({ source: "tool:game-me", profile: { relocation: "international-open" } });
    prof.profile = { relocation: "local-only" };
    render(<RelocationStep />);
    await new Promise((r) => setTimeout(r, 20));
    expect(prof.update).not.toHaveBeenCalled();
    expect(screen.queryByText("From your game")).toBeNull();
  });
});
```

`OnboardingShell` may need more of the router or the profile hook in this test; mock what it reads (as `tests/app/onboarding-complete.test.tsx` does) if the render throws.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-carry.test.ts tests/app/together-carry-onboarding.test.tsx`
Expected: FAIL, `Failed to resolve import "@/lib/together/carry"`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/together/carry.ts`:

```ts
/**
 * What a Together result carries into sign-up (TEC-1845; spec "Joining
 * Ahavah from a result carries the answers into onboarding"): the tool's
 * source for /check-otp and the player's own game answers as profile
 * fields. Kept on this device for 30 days, never sent anywhere until the
 * player signs up, and cleared once onboarding has used it.
 */
import type { Profile } from "@/lib/profile-schema";
import type { ToolSource } from "@/lib/together/api";

const KEY = "ahavah.together.carry.v1";
const LIFE_MS = 30 * 86_400_000;

export type Carry = {
  source: ToolSource;
  profile: Partial<Profile>;
  /** The single checklist's top items, for the profile prompts release. */
  checklistTop?: { key: string; ref?: string; title?: string; importance: number }[];
  at: number;
};

/** Fields onboarding never asks, written once it completes, only where empty. */
export const CARRY_LATER_FIELDS = [
  "calendar", "torahLevel", "feastDays", "familyViews", "livingPreferences", "communicationPrefs",
] as const;

export function writeCarry(c: Omit<Carry, "at">, now: number = Date.now()): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...c, at: now }));
  } catch { /* private mode: nothing carries */ }
}

export function readCarry(now: number = Date.now()): Carry | null {
  try {
    const c = JSON.parse(window.localStorage.getItem(KEY) ?? "null") as Carry | null;
    if (!c || typeof c.source !== "string" || typeof c.at !== "number" || now - c.at > LIFE_MS) return null;
    return { ...c, profile: c.profile ?? {} };
  } catch {
    return null;
  }
}

export function clearCarry(): void {
  try { window.localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}

export function carriedSource(): ToolSource | null {
  return readCarry()?.source ?? null;
}
```

Create `src/components/together/from-your-game.tsx`:

```tsx
"use client";

/**
 * Fills one onboarding field from the game when the profile is still empty
 * and says so (TEC-1845; export 8.2). Never overwrites a choice.
 */
import { useEffect, useState } from "react";

import type { Profile } from "@/lib/profile-schema";
import { readCarry } from "@/lib/together/carry";
import { useProfile } from "@/lib/use-profile";

export function FromYourGame({ field }: { field: "relocation" | "languages" }) {
  const { profile, update } = useProfile();
  const [filled, setFilled] = useState(false);
  useEffect(() => {
    const value = readCarry()?.profile[field];
    const empty = profile[field] === undefined || (Array.isArray(profile[field]) && (profile[field] as unknown[]).length === 0);
    if (value === undefined || !empty || filled) return;
    void update({ [field]: value } as Partial<Profile>);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilled(true);
  }, [field, profile, update, filled]);
  if (!filled) return null;
  return (
    <div className="from-your-game">
      <span className="chip lime">From your game</span>
      <p className="text-body text-(--ink-2)">We filled this from your game. Change it if you like.</p>
    </div>
  );
}
```

In `src/app/onboarding/relocation/page.tsx`, import `FromYourGame` and render `<FromYourGame field="relocation" />` as the first child inside the heading's `motion.div`, above the `h1`. In `src/app/onboarding/languages/page.tsx`, render `<FromYourGame field="languages" />` in the same place; its `selected` state is initialised from `profile.languages` before the carry is applied, so also make that state follow `profile.languages` when it changes from empty (an effect that calls `setSelected(profile.languages)` once, when `selected` is still the default `["en"]` and the carry had languages).

In `src/components/together/game-result.tsx`, import `writeCarry`, `answersToProfile` and `SOURCE_OF`, and add after the other effects:

```tsx
  // "Find people who answered like you" carries the player's own answers
  // into sign-up. A friend's guesses are about someone else and carry
  // only the source.
  useEffect(() => {
    if (!view || view.state === "playing") return;
    const friend = view.mode === "knows_me" && view.seat === "guest";
    writeCarry({ source: SOURCE_OF[view.mode], profile: friend ? {} : answersToProfile(view.my_answers) });
  }, [view]);
```

In `checklist-v2.tsx`, after `setView(v)` in `finish`, add `writeCarry({ source: "tool:checklist", profile: {}, ...(v.mode === "single" ? { checklistTop: (v.result as SingleResult).top } : {}) });`.

In `src/app/auth/sign-up/page.tsx`, import `readCarry` and `useSearchParams`; under the `<p>` that reads "We'll email you a 6-digit code to sign in.", add:

```tsx
          {fromTogether ? (
            <p className="text-body text-(--ink-2)">Your answers will fill part of your profile. You can change them.</p>
          ) : null}
```

with `const fromTogether = useSearchParams()?.get("from") === "together" && readCarry() !== null;` computed in the component (in an effect if the page renders on the server, so the markup matches).

In `src/app/onboarding/verify-email/page.tsx`, import `carriedSource` and replace `const result = await checkOtp(email, code);` with:

```tsx
      // A Together player signing up is counted under the tool (TEC-1845).
      const source = carriedSource();
      const result = await checkOtp(email, code, source ? { source } : undefined);
```

In `src/app/onboarding/complete/page.tsx`, import `readCarry`, `clearCarry` and `CARRY_LATER_FIELDS`, take `update` and `profile` from `useProfile()` beside `finishOnboarding`, and in `finish`'s `.then((personUuid) => { ... })` add before `return true;`:

```tsx
          // Answers carried from a Together game fill what onboarding
          // never asked, only where the profile is still empty.
          const carry = readCarry();
          if (carry) {
            const patch: Record<string, unknown> = {};
            for (const f of CARRY_LATER_FIELDS) {
              const empty = profile[f] === undefined || (Array.isArray(profile[f]) && (profile[f] as unknown[]).length === 0);
              if (empty && carry.profile[f] !== undefined) patch[f] = carry.profile[f];
            }
            if (Object.keys(patch).length) void update(patch);
            clearCarry();
          }
```

and add `profile` and `update` to the `useCallback` dependency list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/together-carry.test.ts tests/app/together-carry-onboarding.test.tsx tests/app/onboarding-complete.test.tsx tests/lib/finish-onboarding.test.tsx`
Expected: PASS (3 and 2 new; the onboarding suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Together.html" "8.1"` and `"8.2"` and transcribe the sign-up line and the tag (390, 768 and 1440; dark and light). 8.2 draws the onboarding screen with the game's answer labels; the onboarding page keeps its own labels and gains only the tag and the line (Spec conflicts, item 10). Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/together/carry.ts src/components/together/from-your-game.tsx src/components/together/game-result.tsx src/components/app/marriage-checklist/checklist-v2.tsx src/app/auth/sign-up/page.tsx src/app/onboarding/verify-email/page.tsx src/app/onboarding/relocation/page.tsx src/app/onboarding/languages/page.tsx src/app/onboarding/complete/page.tsx tests/lib/together-carry.test.ts tests/app/together-carry-onboarding.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(together): game answers fill part of the profile at sign-up, and the sign-up counts the tool" -m "Refs: TEC-1845"
```

---

### Task 27: The privacy paragraphs: before you join, and Together

**Files:**
- Create: `src/lib/legal-leads-copy.ts`, `src/lib/legal-together-copy.ts`
- Modify: `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` (two sections after `quick-answers`)
- Test: `tests/app/legal-together.test.tsx` (create)

**Interfaces:**
- Consumes: `type LegalCopy` (`src/lib/legal-spotlight-copy.ts`).
- Produces: `LEADS_PRIVACY` ("Before you join") and `TOGETHER_PRIVACY` ("The game and the marriage checklist") on both privacy pages, slugs `before-you-join` and `together`.

The owner delegated this wording (17 Oct). Growth foundations Task 14 drafted "Before you join" and held it; it never shipped (no `legal-leads-copy.ts` on `master` on 17 Oct). It ships here, rewritten to say only what is true at this launch: visitor alerts are not built, so they are not named, and the mail a lead gets is named. Both paragraphs ship before `AHAVAH_TOOL_LEADS_ENABLED` and `AHAVAH_TOGETHER_LIVE_ENABLED` go on (Task 29). Every sentence below is checked against the code of Tasks 1 to 13:

- Kept: answers, the chosen name and the email of a player who saved (Tasks 6, 8); a game nobody saved, for 30 days, tied to the device (Task 13).
- Who sees them: the players through their link or email (Task 6); in the checklist each person's comments show to the other (Task 5); a friend sees their own score and the board (Task 7); staff see counts only (Task 14); a shared link or image shows names and a score, a type or the agreement count (Task 9).
- Mail: the code, the summary, a note when the other person has finished (Tasks 10, 11).
- Deleting: either player of a shared result, at once (Task 9); 12 months after the last visit (Task 13); with the account (Task 13); on request at support@ahavah.app.

- [ ] **Step 1: Write the failing test**

Create `tests/app/legal-together.test.tsx`:

```tsx
import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
}));

import PrivacyPage from "@/app/legal/privacy/page";
import { LEADS_PRIVACY } from "@/lib/legal-leads-copy";
import { TOGETHER_PRIVACY } from "@/lib/legal-together-copy";

it("says what Together keeps, who sees it, for how long and how to delete it", () => {
  expect(TOGETHER_PRIVACY.title).toBe("The game and the marriage checklist");
  for (const words of ["your answers, the name you chose to show and your email", "Only you, and the person you invited",
    "comments show to the other", "never see your answers", "never an answer", "Staff see only counts",
    "12 months after your last visit", "30 days", "with your account", "support@ahavah.app"]) {
    expect(TOGETHER_PRIVACY.body).toContain(words);
  }
});

it("says what a visitor's email is used for, and nothing more", () => {
  expect(LEADS_PRIVACY.title).toBe("Before you join");
  for (const words of ["12 months after your last visit", "Other members never see it", "support@ahavah.app",
    "a note when the other person has finished"]) {
    expect(LEADS_PRIVACY.body).toContain(words);
  }
  expect(LEADS_PRIVACY.body).not.toMatch(/gathering|someone who fits joins/i);
});

it("uses no em dash and never says dating", () => {
  for (const c of [LEADS_PRIVACY, TOGETHER_PRIVACY]) {
    expect(c.body).not.toMatch(/\u2014|dating/i);
  }
});

it("shows both on the signed-in privacy page and is on the public one", () => {
  render(<PrivacyPage />);
  expect(screen.getAllByText("Before you join").length).toBeGreaterThan(0);
  expect(screen.getAllByText("The game and the marriage checklist").length).toBeGreaterThan(0);
  const pub = readFileSync("src/app/privacy/page.tsx", "utf8");
  expect(pub).toContain("LEADS_PRIVACY");
  expect(pub).toContain("TOGETHER_PRIVACY");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-together.test.tsx`
Expected: FAIL, `Failed to resolve import "@/lib/legal-leads-copy"`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/legal-leads-copy.ts`:

```ts
/**
 * What Ahavah keeps about someone who gives an email before joining
 * (TEC-1845; the API's lead table). Today that is a Together player who
 * saves a result. Gatherings and visitor alerts add their own words when
 * they ship. The same paragraph is on /privacy and /legal/privacy; edit it
 * here, never in a page. Wording delegated by the owner, 17 Oct 2026.
 */
import type { LegalCopy } from "@/lib/legal-spotlight-copy";

export const LEADS_PRIVACY: LegalCopy = {
  title: "Before you join",
  body: "If you give us your email before you join, to save a game or marriage checklist result, we keep it with a note of which of these you used and when. We use it only for what you asked for: your sign-in code, your checklist summary and a note when the other person has finished. Other members never see it. We delete it 12 months after your last visit, or sooner if you ask at support@ahavah.app. If you later join, we note which of these brought you, to see which outreach works.",
};
```

Create `src/lib/legal-together-copy.ts`:

```ts
/**
 * Together on the privacy pages (TEC-1845; spec "Data (API)" and the
 * growth spec's Privacy). Every sentence matches the API: ahavah-api
 * service/tools (sessions, retention, admin). Wording delegated by the
 * owner, 17 Oct 2026. Edit it here, never in a page.
 */
import type { LegalCopy } from "@/lib/legal-spotlight-copy";

export const TOGETHER_PRIVACY: LegalCopy = {
  title: "The game and the marriage checklist",
  body: "You can play the compatibility game and answer the marriage checklist without an account. When you save a result, we keep your answers, the name you chose to show and your email behind a private link. Only you, and the person you invited to an Us game or the checklist, can open it, through that link or by confirming your email. In the checklist, each person's comments show to the other when you compare. A friend who plays Who knows me best gives only a name. They see their own score and the board and never see your answers. A shared link or image shows names and a score, a type or how many items you agree on, never an answer. Staff see only counts. Either of you can delete a shared result at any time, and it is gone for both. We delete a result 12 months after your last visit and a game nobody saved after 30 days. Everything is deleted with your account, or sooner if you ask at support@ahavah.app.",
};
```

In `src/app/legal/privacy/page.tsx`, add both imports and, after the `quick-answers` section object:

```tsx
        {
          slug: "before-you-join",
          heading: LEADS_PRIVACY.title,
          body: LEADS_PRIVACY.body,
        },
        {
          slug: "together",
          heading: TOGETHER_PRIVACY.title,
          body: TOGETHER_PRIVACY.body,
        },
```

In `src/app/privacy/page.tsx`, add both imports and the same two entries after `quick-answers` in `SECTIONS`.

- [ ] **Step 4: Check the wording**

Run `/copy-pass` on the two bodies (humanizer, as the owner preferred on 13 Oct) and then:
`node ~/.claude/skills/avoid-ai-writing/bin/avoid-ai-writing-gate.js --threshold 6 src/lib/legal-leads-copy.ts src/lib/legal-together-copy.ts` and `node ~/.claude/skills/avoid-ai-writing/scripts/check-style.js src/lib/legal-together-copy.ts --config techbase`.
Expected: both pass. Keep every fact above; if the pass changes a phrase the test matches, change the test to the new phrase.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-together.test.tsx tests/app/legal-questions.test.tsx tests/app/legal-spotlight.test.tsx`
Expected: PASS (4 new; the two legal suites unchanged).

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/legal-leads-copy.ts src/lib/legal-together-copy.ts src/app/privacy/page.tsx src/app/legal/privacy/page.tsx tests/app/legal-together.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "docs(privacy): what Together keeps, who sees it and when it is deleted, and a visitor's email" -m "Refs: TEC-1845"
```

---

## The launch

### Task 28: The launch posts for the Growth calendar (ahavah-admin)

**Files:**
- Create: `src/lib/together-launch.ts`, `scripts/together-launch-entries.mjs`
- Test: `tests/together-launch.test.mjs` (create)

**Interfaces:**
- Consumes: `isRestPeriod`, `isUnknown`, `highDayAt` (`src/lib/rest-days.ts`); `CalendarEntry`, `calendarProblems` (`src/lib/social-calendar.ts`, which takes `kind` and `targetPath` since 4de56a8).
- Produces: `togetherLaunchEntries(launchDay: string) -> CalendarEntry[]`; `node scripts/together-launch-entries.mjs YYYY-MM-DD` prints them.

4 posts on days 0, 3, 7 and 10 from the launch day, each a Facebook entry and an Instagram entry with that channel's artwork from the Growth social set (the export draws an Instagram variant without the address and a Facebook one with it, 1.1 and 1.2), each moved to the next day the rest-day rules allow and never onto a high day. Kind `tool` (its own `utm_campaign`), target `/together` (the checklist post: `/marriage-checklist`). Captions carry no link; the API adds the tracking link on Facebook only.

| Id | Day | Artwork (Growth social set) | Caption |
|---|---|---|---|
| `together-launch-announce` | 0 | 1.5, the Us card with the empty ring | "New on Ahavah: Together. Two free tools for anyone preparing for marriage. Play a 2 minute game alone, with one person or with friends, and see how well you fit. No account needed." |
| `together-launch-kinds` | 3 | 1.1 (Instagram) and 1.2 (Facebook), The Feast Host | "Which kind of builder are you? 8 kinds, one game. Find yours on Ahavah." |
| `together-launch-checklist` | 7 | 2.2, the C1 cover "Ten questions to ask early" | "Ten questions to ask early. Then answer them together, with the free Ahavah marriage checklist." |
| `together-launch-friends` | 10 | 1.1 and 1.2, The Explorer | "How well do your friends know you? Play Who knows me best on Ahavah and post your link in a group chat." |

Captions 2 and 3 are the export's own lines (1.7, 2.2); 1 and 4 are this plan's and wait for the owner (Spec conflicts, item 3).

- [ ] **Step 1: Write the failing test**

Create `tests/together-launch.test.mjs`:

```js
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import ts from 'typescript';

const transpile = (path) => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function load(path, requireMap = {}) {
  const module = { exports: {} };
  vm.runInNewContext(transpile(path), {
    module, exports: module.exports, Date, console,
    require: (id) => {
      if (id in requireMap) return requireMap[id];
      throw new Error(`Unexpected require: ${id}`);
    },
  });
  return module.exports;
}

const plain = (v) => JSON.parse(JSON.stringify(v));
const restDays = load('../src/lib/rest-days.ts');
const calendar = load('../src/lib/social-calendar.ts', { './rest-days': restDays });
const launch = load('../src/lib/together-launch.ts', { './rest-days': restDays });

test('4 posts, each on Facebook and on Instagram, in order and never on a rest day', () => {
  const entries = plain(launch.togetherLaunchEntries('2026-10-20'));
  assert.equal(entries.length, 8);
  assert.deepEqual([...new Set(entries.map((e) => e.id.replace(/-(fb|ig)$/, '')))], [
    'together-launch-announce', 'together-launch-kinds', 'together-launch-checklist', 'together-launch-friends']);
  for (const e of entries) {
    assert.equal(e.kind, 'tool');
    assert.equal(e.promotional, true);
    assert.deepEqual(e.channels, [e.id.endsWith('-fb') ? 'facebook' : 'instagram']);
    assert.equal(e.image, `${e.id}.jpg`);
    assert.equal(restDays.isRestPeriod(new Date(e.publishAt)), false);
  }
  const days = entries.filter((e) => e.id.endsWith('-fb')).map((e) => e.publishAt.slice(0, 10));
  assert.deepEqual([...days].sort(), days);
  assert.equal(entries.find((e) => e.id === 'together-launch-checklist-fb').targetPath, '/marriage-checklist');
  assert.equal(entries.find((e) => e.id === 'together-launch-announce-ig').targetPath, '/together');
});

test("every post passes the calendar's own checks", () => {
  assert.deepEqual(plain(calendar.calendarProblems(launch.togetherLaunchEntries('2026-10-20'), () => true)), []);
});

test('captions carry no link, no link below, nothing about dating and no em dash', () => {
  for (const e of plain(launch.togetherLaunchEntries('2026-10-20'))) {
    assert.doesNotMatch(e.caption, /https?:\/\/|ahavah\.app|link below|dating|\u2014/i);
  }
});

test('a series that runs past the read calendar is refused', () => {
  assert.throws(() => launch.togetherLaunchEntries('2026-11-05'), /read the next month first/);
});
```

The last test assumes the owner's calendar is read only to 9 Nov 2026, as on 17 Oct (quick questions plan, conflict 1); move its date past `KNOWN_THROUGH` in `src/lib/rest-days.ts` if that has been extended.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/together-launch.test.mjs`
Expected: FAIL, `ENOENT` reading `src/lib/together-launch.ts`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/together-launch.ts`:

```ts
/**
 * The launch posts for Together (TEC-1845; ahavah-api plan
 * docs/superpowers/plans/2026-10-17-together-release-1.md, Task 28).
 * Days 0, 3, 7 and 10 from the launch day, each moved to the next day the
 * rest-day rules allow and never onto a high day (they are promotional);
 * a series that runs past the calendar's last read date is refused. Each
 * post is a Facebook entry and an Instagram entry with that channel's
 * artwork from the Growth social set. Captions carry no link: the API adds
 * the tracking link on Facebook, and Instagram carries none. The entries go
 * into content/social-calendar.json only after the owner confirms them.
 */
import type { CalendarEntry, Pillar } from './social-calendar';
import { highDayAt, isRestPeriod, isUnknown } from './rest-days';

const SLOT = 'T08:30:00-04:00';

const POSTS: readonly { id: string; day: number; pillar: Pillar; target: string; caption: string; art: string }[] = [
  { id: 'together-launch-announce', day: 0, pillar: 'C', target: '/together', art: 'Growth Social Set 1.5, the Us card with the empty ring',
    caption: 'New on Ahavah: Together. Two free tools for anyone preparing for marriage. Play a 2 minute game alone, with one person or with friends, and see how well you fit. No account needed.' },
  { id: 'together-launch-kinds', day: 3, pillar: 'C', target: '/together', art: 'Growth Social Set 1.1 and 1.2, The Feast Host',
    caption: 'Which kind of builder are you? 8 kinds, one game. Find yours on Ahavah.' },
  { id: 'together-launch-checklist', day: 7, pillar: 'C', target: '/marriage-checklist', art: 'Growth Social Set 2.2, C1 cover',
    caption: 'Ten questions to ask early. Then answer them together, with the free Ahavah marriage checklist.' },
  { id: 'together-launch-friends', day: 10, pillar: 'F', target: '/together', art: 'Growth Social Set 1.1 and 1.2, The Explorer',
    caption: 'How well do your friends know you? Play Who knows me best on Ahavah and post your link in a group chat.' },
];

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function togetherLaunchEntries(launchDay: string): CalendarEntry[] {
  const out: CalendarEntry[] = [];
  let earliest = launchDay;
  POSTS.forEach((post, i) => {
    let day = addDays(launchDay, post.day);
    if (day < earliest) day = earliest;
    for (;;) {
      const at = new Date(`${day}${SLOT}`);
      if (isUnknown(at)) {
        throw new Error(`${post.id}: ${day} is past the last date the owner's calendar has been read for; read the next month first`);
      }
      if (!isRestPeriod(at) && !highDayAt(at)) break;
      day = addDays(day, 1);
    }
    for (const [suffix, channel] of [['fb', 'facebook'], ['ig', 'instagram']] as const) {
      out.push({
        id: `${post.id}-${suffix}`,
        publishAt: `${day}${SLOT}`,
        channels: [channel],
        image: `${post.id}-${suffix}.jpg`,
        caption: post.caption,
        pillar: post.pillar,
        promotional: true,
        source: `${post.art} (${channel === 'facebook' ? 'the Facebook variant' : 'the Instagram variant'}).`,
        kind: 'tool',
        targetPath: post.target,
        notes: `Together launch, post ${i + 1} of 4, day ${post.day} from the launch day ${launchDay}. TEC-1845.`,
      });
    }
    earliest = addDays(day, 1);
  });
  return out;
}
```

Create `scripts/together-launch-entries.mjs`:

```js
// Prints the Together launch posts for a launch day, as entries for
// content/social-calendar.json (TEC-1845). Nothing is written.
//   node scripts/together-launch-entries.mjs 2026-11-17
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const transpile = (path) => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function load(path, requireMap = {}) {
  const module = { exports: {} };
  vm.runInNewContext(transpile(path), {
    module, exports: module.exports, Date,
    require: (id) => {
      if (id in requireMap) return requireMap[id];
      throw new Error(`Unexpected require: ${id}`);
    },
  });
  return module.exports;
}

const [launchDay] = process.argv.slice(2);
if (!/^\d{4}-\d{2}-\d{2}$/.test(launchDay ?? '')) {
  console.error('usage: node scripts/together-launch-entries.mjs YYYY-MM-DD');
  process.exit(1);
}
const restDays = load('../src/lib/rest-days.ts');
const launch = load('../src/lib/together-launch.ts', { './rest-days': restDays });
console.log(JSON.stringify(launch.togetherLaunchEntries(launchDay), null, 2));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/together-launch.test.mjs tests/social-calendar.test.mjs tests/rest-days.test.mjs`
Expected: all pass (4 new, the calendar and rest-day suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-admin
git add src/lib/together-launch.ts scripts/together-launch-entries.mjs tests/together-launch.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): the Together launch posts, Facebook and Instagram, held to the calendar's rest days" -m "Refs: TEC-1845"
```

---

### Task 29: The launch, in order, with every send proofed first

An operational task: no code. Each step names who acts. Nothing reaches players or social before the owner confirms its proof.

**Files:**
- Modify (ahavah-admin, Step 9 only): `content/social-calendar.json`; Add: `assets/social/together-launch-*-fb.jpg`, `together-launch-*-ig.jpg` (8 files)

- [ ] **Step 1: Ship the API, dark**

Merge Tasks 1 to 14 to `ahavah/main`; the push deploys through GitHub Actions and applies 0068. With every Together switch at its default `0`: `curl -s https://api.ahavah.app/tools/status` answers `{"invite_email":false,"live":false}`, and `curl -s -o /dev/null -w '%{http_code}' -X POST https://api.ahavah.app/tools/sessions -H 'content-type: application/json' -d '{"kind":"game","mode":"me"}'` answers `404`.

- [ ] **Step 2: Ship the web, dark**

Merge Tasks 15 to 26 to `master` (Vercel deploys it). Check: `https://ahavah.app/together` answers 404; `https://ahavah.app/marriage-checklist` is today's checklist, word for word; the sitemap has no `/together`; a match's chat menu shows "View profile" and "Report" only ("Play Us together" appears once Together is live).

- [ ] **Step 3: The owner reads what the export did not have**

In the session, hand the owner the list under "Spec conflicts and decisions needing the owner", items 2 to 6, 9 and 18 (the new lines, the guest names, the archetype points rule), run through `/copy-pass` first. His changes go into the code (Tasks 16, 21, 22, 24, 28) and the commits ship before Step 6. Nothing launches on lines he has not read.

- [ ] **Step 4: Proofs to the owner**

Inside the api container, as `scripts/send_proofs.py` is run: `python -m scripts.send_together_proofs` (dry run), then `python -m scripts.send_together_proofs --send`. The owner receives the 5 emails at `harrigan.tennyson@gmail.com` and checks each at 390 and 600, light and dark, including Gmail's forced dark mode, and every line.

- [ ] **Step 5: The privacy paragraphs go live**

Merge Task 27 to `master`. Check both privacy pages show "Before you join" and "The game and the marriage checklist".

- [ ] **Step 6: Switch on, in this order, after he confirms**

In the production environment that `docker-compose.production.yml` reads, for both api and cron, then restart both:

1. `AHAVAH_TOOL_LEADS_ENABLED=1` (the privacy paragraph is live; the checklist's new wording ships with v2 in the same step).
2. `AHAVAH_TOGETHER_LIVE_ENABLED=1`.
3. Each email switch whose proof he confirmed: `AHAVAH_TOGETHER_ANSWERED_EMAIL_ENABLED`, `AHAVAH_TOGETHER_READY_EMAIL_ENABLED`, `AHAVAH_TOGETHER_SUMMARY_EMAIL_ENABLED`, `AHAVAH_TOGETHER_INVITE_EMAIL_ENABLED`.

Check `curl -s https://api.ahavah.app/tools/status` answers `{"invite_email":true,"live":true}` (or `false` for the invite if that proof is still open), `/together` loads, `/marriage-checklist` shows "How are you answering?" after "Begin the checklist", and the sitemap lists `/together`.

- [ ] **Step 7: A real round on production, by the operator and the owner**

On two phones: Me to the end and save (a code arrives; the share panel shows both images; "Save image" saves the story card); Us, the owner saving and sending the link, the other phone opening it, playing and seeing the reveal with no email, the owner receiving "has answered" and seeing the same score; Who knows me best with two friends and the board, removing and restoring a name; the checklist as a couple, the comparison, and one person deleting it (the link then says it was deleted). Paste each share link into WhatsApp and check the preview. On a phone at 390, nothing scrolls sideways. Then delete every test result with "Delete this result" or "Delete this comparison".

- [ ] **Step 8: Linear**

Move TEC-1845's Together work to Done once Step 7 passes; the follow-ups are their own issues: the Couple tools row (Task 14), prompt drafts from the checklist (item 6, with the profile prompts release 2), the leader pack (spec phase 2), the design follow-up for guest names (item 2) and Unmatch in the chat (item 9). Run `/linear-sync` before the session's final commit.

- [ ] **Step 9: The social posts, after the owner approves them**

In ahavah-admin: `node scripts/together-launch-entries.mjs <launch day>`. The owner approves the 4 captions. Export the 8 artworks (1080 by 1350 JPEG) from `Ahavah Growth Social Set.html` with `/handoff` into `assets/social/`, named as the entries' `image`, append the printed entries to `content/social-calendar.json` and run `node --test tests/social-calendar.test.mjs`. Then:

```bash
cd /d/Antigravity/ahavah-admin
git add content/social-calendar.json assets/social/together-launch-announce-fb.jpg assets/social/together-launch-announce-ig.jpg assets/social/together-launch-kinds-fb.jpg assets/social/together-launch-kinds-ig.jpg assets/social/together-launch-checklist-fb.jpg assets/social/together-launch-checklist-ig.jpg assets/social/together-launch-friends-fb.jpg assets/social/together-launch-friends-ig.jpg
git -c user.email=admin@techbaseltd.com commit -m "content(social): the Together launch posts" -m "Refs: TEC-1845"
```

Each post still waits in the Growth queue for his approval. Instagram captions carry no link.

- [ ] **Step 10: A week after launch**

If v2 ran a week without errors (Vercel and API logs, `email_outbox` rows for `together_%` in `failed` or `acceptance_unknown`), do Task 24 Step 8. Read `GET /admin/growth/tools` with an admin session each week: completion per mode (`completed` / `started`), invite acceptance (`joined` / `links` for `us`), share openings and sign-ups per tool source. The spec's 60 day target, an assumption to test: 1 in 5 completed Us games brings a new person who also completes. The nearest reading here is `joined` among completed `us` sessions; sign-ups under `tool:game-us` and `utm:share/game-us` show who then joined.

---

## Spec conflicts and decisions needing the owner

1. **The hub's link preview is missing.** `Claude Design/export/og/og-together-1200x630.png` was not in the design project on 17 Oct (`export/` holds `social` and `src-social` only). Task 18 retrieves it with `/handoff`; if it is still missing, `/together` ships with the site's default preview.
2. **Guest names.** The export names the guest on screens the app reaches before any guest exists ("Send Rivka your link", "Waiting for Rivka", "Rivka’s email", 6.6's "Rivka will see this when you compare", 6.7), and its save step (5.1) offers the name as two chips with no field, though a visitor has given no name. This plan: guests give a name when they start (4.12's field for friends; "Show my name as" for Us and the checklist), visitors type a name on the save step, and before a guest has joined the owner sees "Send your link", "Waiting for the other player", "Their email" and "The other person will see this when you compare". These need a design follow-up (a short `/brief`) and the owner's words.
3. **Lines the export does not have**, each marked in the code, for `/copy-pass` and the owner: the intros of rounds 1, 3, 4, 5 and 6 (Task 16); the parts of "You in a sentence" beyond the export's example (Task 16); the checklist's two share texts and its invite share text (Task 16); "You are number {place} on {name}’s board." (Task 21); "This link has already been used." (Task 22); v2's intro step 3, FAQ answers, description and HowTo step (Task 24); the invite email's footer "We have not added you to any list." (Task 10); launch captions 1 and 4 (Task 28).
4. **"Hers".** 4.3 and 4.5 say "Rivka will not see your answers and you will not see hers": the app does not know the sender's pronoun. The plan uses 2.1's "Neither of you sees the other’s answers. You both see the score." on the second player's start, the send-link screen and the invite email.
5. **The invite email is not drawn.** The export draws "Send it by email" (4.3, 6.2) but no invite email. Task 10 builds it on the brand shell from the start screens' lines; it is proofed with the others and is behind `together_invite_email`.
6. **"If you join Ahavah, these can become your profile prompts." (6.10) is not true yet.** Prompt drafts are the profile prompts release 2 (written answers), not built. The line is held (`PROMPT_DRAFTS_LIVE = false`) and the single's top items are kept in the sign-up carry for that release.
7. **Hanukkah and Purim.** The export draws the spring feasts without them (3.3) and with them (3.5); the plan uses 3.3. A game never asks them, so a profile that lists them scores slightly differently against game answers; game against game is unaffected. (Decision 3.)
8. **Two numbers for the same people.** The app's pill keeps plural marriage at weight 1 (decision 8) while the game gives it 0, so two members may see one number in the game and another in the app. Recorded as decided.
9. **The chat menu.** "Play Us together" sends the member to play first and back with the invite, since the prefilled line says "I played" (9.2 draws the invite appearing at once). The export's menu also has "Unmatch", which the chat has no action for; it is not built here and needs a confirmation frame.
10. **Onboarding labels.** 8.2 draws the relocation screen with the game's answer labels; the onboarding page keeps the profile's labels and gains only the tag and the line.
11. **Admin > Growth, Couple tools row:** Linear issue the id Task 14 returns (Ahavah Admin, Backlog). The API's counts are in place.
12. **A deleted or unknown invite link cannot say which tool it was.** The API answers both without the kind, so `/tools/i` shows the game's lines (4.8, 4.9) for a checklist link too; 6.5's checklist lines show where the device knows the link.
13. **The checklist summary email.** Decision 12 keeps it "as today", decision 10 changes the stored-answers wording everywhere. In v2 its lede drops "sent to you both" (each person answers and gets their own) and its footer carries 6.1's stored line; the first checklist's email is unchanged until v1 is removed. Proofed in Task 12.
14. **"Dating" on the live checklist.** Today's code step says "We do not add you to any dating emails." The plan does not touch the live v1 before launch (no change to a live page without a proof); the line goes with v1 in Task 24 Step 8. The owner may want it fixed sooner.
15. **The spec's "Turnstile once keys exist"** is not used: bot protection is free only (owner, 13 Oct), through `signupguard`.
16. **Not in this release by the spec or the decisions:** the leader pack (phase 2), the knows-me image naming the top friend (decision 7), "Rivka’s answers" for friends (decision 6), the strict email-first second player (decision 4), the consent box (decision 11), Hanukkah and Purim (decision 3), the "without Exodus 21" variants (decision 9).
17. **Retention choices the spec does not make:** a session nobody saved goes after 30 days, and a deleted session's tombstone after 30 days. Both are stated on the privacy page (Task 27).
18. **The Me archetype rule** (Task 4's points table) is engineering's; the brief asks the owner to approve it.
19. **Unverified while writing this plan:** that Satori draws every SVG attribute the motifs use (Task 17 Step 5 renders them); that Vercel's trace includes the font files (Task 23 Step 4 checks the build); that the browser's preflight for `X-Tool-Token` passes (flask-cors allows all headers by default; Task 29 Step 7 exercises it); that `AntibotPayload` carries `website` and the stamp under the invite route's names (Task 15 Step 3).

## Self-review

**Spec coverage.**

| Requirement (spec, brief, the task's scope) | Task |
|---|---|
| Tables `tool_session`, `tool_answer`, `tool_result` in one migration (0068), plus `tool_player` | 1 |
| A dark-launch switch like `questions_live`; every switch off, passed to api and cron | 2 |
| Scoring reuses the 9 axes, plural marriage weight 0 and no question, ported to Python, cross-repo parity test | 3, 16 |
| About 15 questions in 6 rounds plus 3 light; one per screen; Back, Skip, multi Next, failures, long lists | 3, 16, 19 |
| Me: archetype, line, "You in a sentence", "Why this fits you" | 4, 16, 21 |
| Us: link to one person, simultaneous reveal, ring, 3 align, 2 to talk about, 6 bars | 6, 7, 21 |
| Who knows me best: friends give only a name, guess, leaderboard; owner removes a name; friends never see answers | 4, 7, 21 |
| Playing needs nothing; saving needs the existing code and onboardee session; a member skips it | 6, 8, 20 |
| The second player sees the result through the link, email only to save or for the image (decision 4) | 7, 8, 22 |
| Tokens: unguessable share and invite tokens; answers readable only by the players | 6, 8, 9 |
| `POST /tools/sessions`, answers, claim, `GET /tools/r`, `GET /tools/i`, `DELETE` | 6 to 9 |
| Public summary and share images never show answers; knows-me image never names a friend | 9, 17, 23 |
| Share images at 1200 by 630 and 1080 by 1920 through `src/lib/share-image/`; share text; UTM tags | 16, 17, 20, 23 |
| Two invitations on every result | 21, 23, 24 |
| Leads only while `AHAVAH_TOOL_LEADS_ENABLED` is on; sources `tool:*`; a member is never a lead | 8, 10, 26 |
| Notify email to the first player through the outbox, proofed, switch default off (decision 5) | 10, 12 |
| Checklist couple mode: invite, private answering, comparison with agree, talk about, own items | 5, 6, 24 |
| Checklist single mode "My non-negotiables" | 5, 24 |
| Either person deletes a shared comparison | 9, 24 |
| Checklist results email stays, plus "your comparison is ready" (decision 12) | 10, 12 |
| Checklist share image, progress only | 17, 24 |
| Stored-answers wording changes on the checklist, the FAQ, the description and the API docstrings (decision 10) | 10, 24 |
| Exodus 21:10-11 stays (decision 9) | 5, 24 |
| Checklist dark first, paper canvas as light (decision 13) | 24 |
| Rate limits: per recipient 5 an hour, signupguard on the mail-sending endpoint | 11 |
| Deleted 12 months after the last visit, or on request, and with the account | 9, 13 |
| Admin: counts only, never answers | 14 |
| "Play Us together" from a match's chat | 25 |
| Joining from a result carries the answers into onboarding; sign-up source `tool:*` | 26 |
| Privacy page names stored tool results, why, how long, who sees them and how to delete | 27 |
| `/together` hub, page title, sitemap, dark until live | 18 |
| Proofs to the owner only | 12, 29 |
| Launch runbook; social posts through the Growth calendar, no Instagram links | 28, 29 |
| Measurement: completion per mode, invite acceptance, share opens, sign-ups by `tool:*` | 14, 29 |
| No marketing consent box (decision 11) | 20 |
| The app's pill unchanged (decision 8) | 16 (test), 29 |

Not in this release: the leader pack (spec phase 2), prompt drafts from the checklist (profile prompts release 2), Turnstile (owner: free only), Unmatch in the chat (conflict 9).

**Placeholder scan.** Searched for "TBD", "TODO", "implement later", "fill in", "similar to Task", "add appropriate" and code steps without code: none. Set by the export by design and named as such: the markup of each web task (`/sot-sync` against the frames listed), the hub's link preview file (conflict 1) and the 8 social artworks (Task 29 Step 9). The Linear id in conflict 11 is filled by Task 14. Task 19's temporary `GameResult` is replaced in Task 21, named as such.

**Type consistency.** Checked across tasks: question keys and option keys identical in `service/tools/questions.py` (Task 3) and `src/lib/together/questions.ts` (Task 16), in the same order; `answers_to_profile` and `answersToProfile` map the same fields (the fixture pins both); `GAME_WEIGHTS` the same in both; the view shape (`session_id`, `kind`, `mode`, `seat`, `role`, `state`, `claimed`, `member`, `share_token`, `invite_token`, `owner_display`, `guest_display`, `my_display`, `my_answers`, `result`, `board`) from `sessions.view` (Task 6) matches `SessionView` (Task 15); results `{archetype, why}`, `{score, areas, align, talk, bars}`, `{right, total, place}`, `compare()`'s `{agree, total, agree_items, talk_items, own}` and `{top}` match `MeResult`, `UsResult`, `FriendResult`, `Comparison`, `SingleResult`; board rows `{player_id, display, right, total, removed}` for the owner and `{display, right, total, me}` for a friend match `BoardRow`; the public summary `{kind, mode, names, state, score?, archetype?, agree?, total?}` (Task 9) matches `PublicSummary` and `parsePublicSummary` (Task 23); archetype keys and area keys are the same 8 everywhere; sources `tool:game-me`, `tool:game-us`, `tool:knows-me`, `tool:checklist` in `SOURCE` (Task 6), `SOURCE_OF` (Task 15), the migration's check (Task 1) and `service.leads.sources`; switch names identical in Tasks 2, 10, 11 and the runbook; `ToolError` reasons the web reads (`deleted` 410, `full` 409, `not_found` 404) match Tasks 7, 9 and 22; the header `X-Tool-Token` in Task 6 and Task 15; template names `together-me`, `together-us`, `together-knows`, `together-couple`, `together-single` in Tasks 17 and 23; `invite_emails` in the migration, `prepare_invite` and the counts. The test counts in each run step match the tests written: API 9, 8, 16, 14, 14, 12, 9, 9, 9, 10, 6, 4, 4, 3; web 2 plus 4 plus 4, 6 plus 8, 9, 2 plus 1, 7, 4, 7, 8, 3 plus 2, 7, 5, 3 plus 2, 4; admin 4.

**Review Focus.** Each line names a test written out in its task: Task 3 `test_the_port_scores_each_shared_case_as_the_web_engine_does[partial]`, Task 4 `test_no_answers_gives_the_sabbath_keeper_with_no_why`, Task 16 `scores a player who skipped almost everything`; Task 7 `test_a_second_guest_is_refused_in_a_two_player_mode`, Task 22 `says the game is full and offers to play alone`; Task 7 `test_the_owner_cannot_join_their_own_game`; Task 6 `test_us_reveals_nothing_until_both_have_finished`, Task 10 `test_the_answered_email_goes_to_whoever_finished_first`; Task 6 `test_a_display_name_is_cleaned_or_refused`, Task 10 `test_names_are_escaped_in_every_email`.
