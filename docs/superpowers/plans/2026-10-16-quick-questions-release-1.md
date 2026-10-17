Linear: TEC-1845

# Quick questions, release 1, and its launch: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Members answer a light question each week with one tap, unlock each other's answers by answering, get a shared question in the empty chat of a new match and hear about it through capped, held pushes, one E2 line and a launch, with every send behind a switch that stays off until the owner has seen a proof.

**Architecture:** The API keeps one answer bank per member (`prompt_answer`) beside the existing `prompt_bank`, an approved weekly schedule (`question_drop`) whose drop day is the first free day of each week under the lunar rest-day rule and one shared question per match (`match_question`). A small `service/questions` package answers every read and enforces "answer to see theirs" on the server. The pushes, the launch email and the launch push are jobs in the existing hourly `returnmail` cron, each behind its own switch in `service/campaigns/switches.py`, logged in `push_send_log` and the outbox like the held reminders. The web adds a quick-question kind to the next-action card, the catch-up run, Quick answers on profiles, the meter, the chat block, a settings row and the email answer page, all transcribed from the revised Claude Design export. The admin gets its calendar target path now and its Questions tab as a Linear issue.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pytest in the `docker-compose.test.yml` api container (ahavah-api); Next.js 16.2, React 19, vitest and Testing Library (ahavah-web); Next.js 16.2, `node --test` (ahavah-admin).

**Spec:** `docs/superpowers/specs/2026-10-13-profile-prompts-design.md`, its "Revision, 16 Oct 2026: fun questions in the app" and the release 1 sections it points to, which supersede the older sections. Read with `docs/superpowers/plans/2026-10-16-growth-foundations.md` (migration 0066 created `prompt_bank` empty; Task 11 there shipped the question of the week) and the design brief `ahavah-web/docs/design-briefs/2026-10-13-profile-prompts.md` (revised 16 Oct).

## Before you start

- Production's last migration is 0066. This plan adds 0067 only.
- ahavah-api: branch `quick-questions` from the branch that holds this plan and the 16 Oct spec (`growth-foundations` when this was written; `ahavah/main` once it has merged). ahavah-web: branch `quick-questions` from `master`. ahavah-admin: branch `quick-questions` from `master`. Use superpowers:using-git-worktrees.
- Backend tasks (1 to 14) do not wait for design, except Task 14's two title images. Web tasks (15 to 23) wait for the revised design export: the brief was revised on 16 Oct and is being designed now. The design at `ahavah-web/Claude Design/Ahavah Profile Prompts.html`, `pages/p08-prompts.js` and `handoff/copy/08-profile-prompts.md` is for the previous brief (written prompts, replies, the opening question) and is not built here. The revised export is `Ahavah Quick Questions.html` at the design project root (the brief's definition of done), retrieved with `/handoff`.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. Every test command uses the shared `ahavah-api-postgres-1` database, which other sessions also use. Never remove, reset or recreate that container or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Web tests run with `cd /d/Antigravity/ahavah-web && npx vitest run <file>`. Admin tests run with `cd /d/Antigravity/ahavah-admin && node --test tests/<file>.test.mjs`.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845`, no attribution trailers.
- Line numbers are hints measured on 16 Oct (ahavah-api `growth-foundations` at 4e8e442, ahavah-web `design-wave-1` at 72ca8dc, ahavah-admin 42a3fea). Every edit is anchored on the code it quotes; trust the quote over the number.

## Global Constraints

Every task's requirements include these. Quoted lines are verbatim from the spec or the brief.

- Copy: sentence case, British spelling, no em dashes, digits for numbers, no serial comma, never "dating". This covers UI strings, push text, email text, captions, code comments and commit messages. "Wording goes through the ux-writing skill and the owner." Copy in this plan is the spec's and the brief's draft; the export may change a line, and the export wins.
- Release 1 carries no free text: "Answers are either-or or pick-one choices from fixed options, so nothing a member writes reaches another member before a person can review it."
- "No question or prompt about plural marriage."
- Privacy: answers show "Never to signed-out viewers, on `limited` (hidden) profiles, in push text or in `ahavah_extra`." "A split shows only from 5 answers." Splits are "counts, never percentages". "Lock screens show no names and no answers."
- Switches: every new send is behind a switch in `SWITCHES`, "each off by default", and each variable has its pass-through "in the form `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}`, in both environment blocks of `docker-compose.production.yml`" (api and cron). "Nothing reaches members or social until he confirms."
- Proofs: emails to `harrigan.tennyson@gmail.com` only and pushes to person 18 only, never through the outbox, recording nothing.
- Pushes: "Sends use `send_to_user_safe`, never `notify()`, which falls back to email." Each follows "the `_already`, `_log_push`, `held.after_commit` pattern in `emails/reminders.py`".
- Rest days: the lunar rule in `service/spotlight/restdays.py` (owner decision 1), evening before included, nothing past `KNOWN_THROUGH`.
- Social: "captions carry no link and never say 'link below'". No stock or staged faces, nothing that says dating.
- Screens: every visual comes from Claude Design; mobile first at 390; nothing scrolls sideways; option buttons stack at 390 and are the one place a label may wrap.
- Rollout: "Nothing is written into the chat server."

## Review Focus

The five inputs the spec implies but does not test, most likely to bite a member first. Each has a test in the task named.

1. A member with no time zone, a time zone the server does not know or a garbled value from an old browser: stored as none, pushed at 18:00 US Eastern, never an error at subscribe. Task 6, `test_a_bad_or_missing_time_zone_is_stored_as_none`; Task 9, `test_a_member_with_no_time_zone_is_pushed_at_18_eastern`.
2. A question the owner switches off or rewords after members answered it: answers stay stored and the question leaves profiles, splits and the card; an email link to it says it has closed. Task 2, `test_a_closed_or_unknown_question_is_refused`; Task 4, `test_an_answer_to_a_question_switched_off_is_not_shown`; Task 13, `test_a_label_edit_keeps_every_answer`.
3. A double tap, a second email click on the other option or a reload of a `?src=` link: one answer, never overwritten by an email click, one tap counted. Task 2, `test_keep_existing_never_overwrites`; Task 6, `test_a_push_tap_is_recorded_once_per_10_minutes`.
4. A match where the other member has been deactivated: no chat question and no silent-match push. Task 5, `test_a_match_with_a_deactivated_member_has_no_context`; Task 9, `test_no_silent_match_push_when_the_other_member_is_deactivated`.
5. A day that is free but sits on the eve of a rest day and a tick that lands inside a rest period: the eve is never a drop day and nothing is pushed or emailed in a rest period. Task 3, `test_the_eve_of_a_rest_day_is_not_a_drop_day`; Task 9, `test_nothing_goes_in_a_rest_period`.

## Decisions taken

The owner may still change any of these.

Owner defaults, 16 Oct (spec decision numbers in brackets where they differ from the owner's list):

1. **Rest days (spec 1).** The weekly question drops on the first free day of each Sunday-to-Saturday week by the lunar rule in `service/spotlight/restdays.py`, never a fixed Sunday. The weekly push goes at 18:00 the member's local time on that day. The Friday and Saturday rule is not applied to these pushes. Copy uses the "each week" versions the brief gives beside every line that names Sunday.
2. **The question set (spec 2).** The 14 choice questions, their option wording and the first 6-week order as the spec lists them, approved through the design proofs. Order: mountains or the sea, window seat or aisle, the best Sabbath afternoon, early or on time or late, host the feast meal or bring dessert, people or quiet.
3. **Silent match (spec 3).** The silent-match push goes to both members.
4. **Written answers (spec 5).** Written answers wait for human review. That is release 2 and not in this plan.
5. **Push default (spec 11).** `push_questions` defaults on.
6. **Launch day (spec 8).** Launch on the first free day after the screens ship: the first approved drop.
7. **Catch-up (spec 10).** The catch-up run offers every active question from launch, leaving out this week's.
8. **The gap (spec 12).** Question pushes count towards the 3-day gap: `question` and `match_question` join `_GAP_CAMPAIGNS`, and `nudged_recently_sql` reads `push_send_log` for them.

Choices this plan makes where the spec leaves one:

- **A drop day** is a day that is not a rest day and whose next day is not one either (a rest period starts 17:00 Barbados the evening before, and 18:00 local in the US falls after that), on or before the day before `KNOWN_THROUGH`. A week with no such day has no question.
- **The current question** is the latest approved drop on or before today (Barbados date), for at most 14 days. It stays current until the next drop.
- **`question_drop.approved_at`** is added (the spec lists 2 columns). Only approved drops go live; changing a week's question takes its approval away.
- **Rank 4.5** for the quick-question card, between verification-pending (4) and profile-finish (5), so no other rank moves.
- **The question week** for the push budget starts at 00:00 Barbados on the current drop's `live_on`.
- **The silent-match window** is from 24 hours to 7 days after the match, while neither member has written.
- **"Stop after 2"** counts `question` and `match_question` pushes sent after the member's `last_online_time`.
- **Push bodies** use a short form built from the options ("Mountains or the sea?"), so the longest body is 102 characters, inside the 110 a lock screen shows.
- **The launch email and the launch push** go on any approved drop day while their switch is on, once per member ever. The runbook (Task 26) turns both off after launch week. The launch push writes two `push_send_log` rows: `questions_launch`/`launch` (once ever) and `question`/`{live_on}` (the week's budget).
- **Question pushes and the launch email skip** test and suppressed addresses (`_excluded()`, `suppressed_predicate_sql`), as the reminders do.
- **The email answer page** saves with `PUT /answers/{key}` and `keep_existing: true`, so an email click never overwrites an earlier answer; "Change to {option}" then saves without it.
- **The chat block** reads a new `GET /conversation-context/{uuid}` rather than extending `/conversation-prospect`.
- **Proofs** for this feature come from a separate script, `scripts/send_question_proofs.py`, reusing `scripts/send_proofs.py`'s address, account and helpers, so the owner is not re-sent the 10 Wave 3 proofs.

## File structure

ahavah-api:

| Path | Action | Responsibility |
|---|---|---|
| `migrations/0067_quick_questions.sql` | Create | Bank columns and seed, answers, drops, match questions, time zone, push taps, the new preference and person columns |
| `service/questions/__init__.py` | Create | Package docstring |
| `service/questions/bank.py` | Create | Live questions, saving an answer, the split |
| `service/questions/schedule.py` | Create | Drop days, the current drop, rest periods |
| `service/questions/member.py` | Create | The card, catch-up, Quick answers, the match question, the E2 line |
| `service/questions/copy.py` | Create | Push and E2 wording, the sample question for proofs |
| `service/questions/pushes.py` | Create | Silent-match, weekly and launch pushes |
| `service/questions/admin.py` | Create | Admin > Questions reads and edits |
| `service/api/questions_routes.py` | Create | Member routes |
| `service/api/admin/questions_routes.py` | Create | Admin routes |
| `service/api/__init__.py` | Modify | Registers both route modules |
| `duotypes/__init__.py` | Modify | Request models; `push_questions`; subscribe `tz` |
| `service/person/__init__.py` | Modify | `quick_answers` on `/prospect-profile` |
| `service/notifications/__init__.py` | Modify | The `questions` kind, the off stamp, the time zone |
| `service/campaigns/switches.py` | Modify | 5 switches |
| `service/campaigns/held.py` | Modify | The gap reads question pushes |
| `service/campaigns/__init__.py` | Modify | `questions_launch` in `SELF_CAPPED_CAMPAIGNS` |
| `service/cron/returnmail/__init__.py` | Modify | The 4 new jobs |
| `emails/community_weekly.py`, `emails/send_community_weekly.py` | Modify | The E2 question line |
| `emails/questions_launch.py` | Create | The launch email and its job |
| `emails/assets/title-quick-questions.png`, `-wht.png`, `tests/email_assets_manifest.txt` | Add | The title images from the export |
| `scripts/send_question_proofs.py` | Create | Proofs to the owner only |
| `docker-compose.production.yml` | Modify | 5 pass-throughs in api and cron |
| `tests/conftest.py` | Modify | `questions_schema`, `make_question`, `drops`, `push_member`, `pushed_questions` |
| `tests/test_migration_0067.py`, `test_question_answers.py`, `test_question_schedule.py`, `test_quick_answers_profile.py`, `test_conversation_context.py`, `test_question_notification_prefs.py`, `test_question_switches.py`, `test_question_gap.py`, `test_question_pushes.py`, `test_questions_launch_push.py`, `test_e2_question_line.py`, `test_send_question_proofs.py`, `test_admin_questions.py`, `test_questions_launch_email.py` | Create | One file per task |

ahavah-web (every row waits for the revised export):

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/api-client.ts` | Modify | `put` |
| `src/lib/questions.ts` | Create | Types, copy, pure helpers, `saveAnswer` |
| `src/lib/next-action.ts`, `src/lib/use-next-action.ts` | Modify | The quick-question kind, promotion, the meter |
| `src/components/app/question-card.tsx` | Create | The card and the catch-up offer |
| `src/components/app/next-action.tsx` | Modify | Custom body, selectable rows, the meter line |
| `src/components/app/catch-up-run.tsx` | Create | The run |
| `src/app/discover/page.tsx` | Modify | Wires the card and the run |
| `src/components/app/quick-answers.tsx` | Create | Quick answers, others' and own |
| `src/app/profile/[uuid]/page.tsx`, `src/app/profile/page.tsx` | Modify | Show them |
| `src/components/app/chat-question-block.tsx`, `src/components/app/chat-thread-view.tsx` | Create, modify | The chat block |
| `src/app/settings/notifications/page.tsx`, `src/lib/use-notification-preferences.ts`, `src/lib/use-push-subscription.ts` | Modify | The settings row, the time zone |
| `src/lib/push-tap.ts`, `src/components/push-tap-capture.tsx`, `src/app/layout.tsx` | Create, modify | `POST /push-taps` |
| `src/components/app/q-answer-view.tsx`, `src/app/q/[key]/[choice]/page.tsx` | Create | The email answer page |
| `src/lib/legal-questions-copy.ts`, `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` | Create, modify | The privacy paragraph |
| `public/email/title-quick-questions.png`, `-wht.png` | Add | The title images (Task 14) |

ahavah-admin:

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/social-calendar.ts`, `src/lib/social-queue.ts`, `src/lib/growth-server.ts` | Modify | `targetPath` on an entry, sent as `target_path` |
| `src/lib/questions-launch.ts`, `scripts/questions-launch-entries.mjs` | Create | The 4 launch posts for a launch day |
| `tests/questions-launch.test.mjs`, `tests/social-queue.test.mjs` | Create, modify | Their tests |
| `content/social-calendar.json`, `assets/social/questions-launch-*.jpg` | Modify, add | Only at launch, after the owner confirms (Task 26) |

---

### Task 1: Migration 0067, the quick questions schema and the seeded bank

**Files:**
- Create: `migrations/0067_quick_questions.sql`
- Create: `tests/test_migration_0067.py`
- Modify: `tests/conftest.py` (append fixtures at the end)

**Interfaces:**
- Consumes: `prompt_bank` (0066), `person`, `ahavah_match` (0006), `push_subscription` (0010), `notification_preference` (0013, 0029, 0057), the `growth_schema` fixture.
- Produces: `prompt_bank.format` (`either_or` | `pick_one` | `text`) and `prompt_bank.options` (jsonb array of `{key, label}`), 14 active and 20 inactive seeded rows; `prompt_answer(person_id, prompt_key, choice_key, text, text_status, created_at, updated_at)`, primary key `(person_id, prompt_key)`; `question_drop(live_on date primary key, prompt_key, approved_at, created_at)`; `match_question(match_id uuid primary key, prompt_key, offered_at)`; `push_subscription.tz`; `notification_preference.push_questions` (default TRUE) and `push_questions_off_at`; `push_tap(id, person_id, src in qpush|mpush|lpush, tapped_at)`; `person.question_catchup_declined_at`. Fixtures: `questions_schema` (session), `make_question(labels=('Yes', 'No'), *, active=True, sort=0, text=None) -> dict(key, text, format, options)`, `drops` (factory `add(live_on: date, key: str, approved=True)`, restoring any row it replaced).

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_0067.py`:

```python
"""Migration 0067: quick questions, release 1 (TEC-1845).

Pins the bank as the owner approved it (14 choice questions active, the
guide's 20 open questions waiting inactive for release 2), the shape rules
the database itself enforces, and that a second run of the file never
overwrites an edit the owner made in Admin > Questions. The deploy may run
the file more than once, so every test runs it twice first.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from database import api_tx

_DIR = Path(__file__).resolve().parent.parent / 'migrations'


def _apply(name: str) -> None:
    with api_tx() as tx:
        tx.execute((_DIR / name).read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def _applied_twice():
    _apply('0066_growth_foundations.sql')
    _apply('0067_quick_questions.sql')
    _apply('0067_quick_questions.sql')


WYR = 'Would you rather'
MER = 'Mornings, evenings and how you rest'
FAM = 'Family life and traditions'
LIT = 'Little preferences that reveal a lot'

ACTIVE = {
    'host-or-dessert': (WYR, 'either_or', ['Hosting the feast meal', 'Bringing dessert']),
    'mountains-or-sea': (WYR, 'either_or', ['Mountains', 'The sea']),
    'cabin-or-city': (WYR, 'either_or', ['A cabin with no signal', 'A new city to explore']),
    'grow-or-market': (WYR, 'either_or', ['Growing vegetables', 'Knowing every good market stall']),
    'language-or-instrument': (WYR, 'either_or', ['A new language', 'A new instrument']),
    'coffee-or-tea': (MER, 'pick_one', ['Coffee', 'Tea', 'Something else']),
    'morning-or-night': (MER, 'either_or', ['Early mornings', 'Late evenings']),
    'sabbath-afternoon': (MER, 'pick_one', ['A long walk', 'A nap', 'A table full of friends']),
    'people-or-quiet': (MER, 'either_or', ['People', 'Quiet']),
    'family-table': (FAM, 'either_or', ['A big family table', 'Small and cosy']),
    'window-or-aisle': (LIT, 'either_or', ['The window seat', 'The aisle seat']),
    'early-or-late': (LIT, 'pick_one', ['Early', 'On time', 'A little late']),
    'plan-or-decide': (LIT, 'either_or', ['Planning to the hour', 'Deciding on the day']),
    'city-town-or-country': (LIT, 'pick_one', ['The city', 'A small town',
                                               'A long drive to the nearest neighbour']),
}

OPEN = {
    'cook-for-guests', 'feast-food', 'song-every-word', 'book-or-album', 'hobby-to-start',
    'surprisingly-good-at', 'place-to-return', 'first-hour', 'ideal-free-day',
    'ideal-kitchen-table', 'ideal-trip', 'ideal-picnic', 'tradition-to-carry-on', 'best-cook',
    'favourite-feast-gathering', 'family-game', 'pet', 'secret-chore', 'thing-with-a-story',
    'small-good-thing',
}


def _bank() -> dict:
    with api_tx('read committed') as tx:
        rows = tx.execute(
            """SELECT key, text, category, format, options, active FROM prompt_bank
                WHERE key = ANY(%(k)s)""",
            dict(k=[*ACTIVE, *OPEN])).fetchall()
    return {r['key']: dict(r) for r in rows}


def test_the_14_choice_questions_are_seeded_active_with_their_options():
    bank = _bank()
    for key, (category, fmt, labels) in ACTIVE.items():
        row = bank[key]
        assert row['active'] is True, key
        assert (row['category'], row['format']) == (category, fmt), key
        assert [o['label'] for o in row['options']] == labels, key
        assert len({o['key'] for o in row['options']}) == len(labels), key


def test_the_20_open_questions_wait_inactive_for_release_2():
    bank = _bank()
    assert set(OPEN) <= set(bank)
    for key in OPEN:
        assert (bank[key]['format'], bank[key]['active'], bank[key]['options']) == ('text', False, []), key


def test_every_option_reads_inside_a_sentence():
    for key, (_, _, labels) in ACTIVE.items():
        for label in labels:
            words = label.lower().split()
            assert 1 <= len(label) <= 40, label
            assert 'i' not in words and 'my' not in words, label
            assert '\u2014' not in label, label
    assert max(len(r['text']) for r in _bank().values()) <= 120


def test_a_second_run_keeps_the_owners_edits():
    with api_tx() as tx:
        before = tx.execute("SELECT options, active FROM prompt_bank WHERE key = 'mountains-or-sea'").fetchone()
        tx.execute("""UPDATE prompt_bank
                         SET options = jsonb_set(options, '{0,label}', '"Hills"'), active = FALSE
                       WHERE key = 'mountains-or-sea'""")
    try:
        _apply('0067_quick_questions.sql')
        row = _bank()['mountains-or-sea']
        assert row['options'][0]['label'] == 'Hills' and row['active'] is False
    finally:
        with api_tx() as tx:
            tx.execute("UPDATE prompt_bank SET options = %(o)s::jsonb, active = %(a)s WHERE key = 'mountains-or-sea'",
                       dict(o=json.dumps(before['options']), a=before['active']))


@pytest.mark.parametrize('fmt,options', [
    ('either_or', [{'key': 'a', 'label': 'A'}]),
    ('pick_one', [{'key': 'a', 'label': 'A'}, {'key': 'b', 'label': 'B'}]),
    ('pick_one', [{'key': k, 'label': k} for k in 'abcde']),
    ('text', [{'key': 'a', 'label': 'A'}]),
    ('poll', []),
])
def test_the_format_and_its_options_must_agree(fmt, options):
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO prompt_bank (key, text, category, format, options)
                   VALUES (%(k)s, 'x', 'test', %(f)s, %(o)s::jsonb)""",
                dict(k=f'm0067-{uuid4().hex[:8]}', f=fmt, o=json.dumps(options)))


def test_an_answer_names_a_choice_or_a_text(make_person):
    person = make_person(name='M0067')
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO prompt_answer (person_id, prompt_key) VALUES (%(p)s, 'mountains-or-sea')",
                       dict(p=person['id']))
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, 'mountains-or-sea', 'sea')""", dict(p=person['id']))


def test_one_question_per_drop_day():
    day = date(2031, 3, 2)
    try:
        with api_tx() as tx:
            tx.execute("INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, 'mountains-or-sea')", dict(d=day))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with api_tx() as tx:
                tx.execute("INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, 'window-or-aisle')", dict(d=day))
    finally:
        with api_tx() as tx:
            tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=day))


def test_a_push_tap_names_a_known_source(make_person):
    person = make_person(name='M0067Tap')
    with pytest.raises(psycopg.errors.CheckViolation):
        with api_tx() as tx:
            tx.execute("INSERT INTO push_tap (person_id, src) VALUES (%(p)s, 'email')", dict(p=person['id']))


def test_the_new_columns_and_their_defaults(make_person):
    person = make_person(name='M0067Cols')
    with api_tx() as tx:
        tx.execute('INSERT INTO notification_preference (person_id) VALUES (%(p)s)', dict(p=person['id']))
        pref = tx.execute('SELECT push_questions, push_questions_off_at FROM notification_preference '
                          'WHERE person_id = %(p)s', dict(p=person['id'])).fetchone()
        cols = {(r['table_name'], r['column_name']) for r in tx.execute(
            """SELECT table_name, column_name FROM information_schema.columns
                WHERE (table_name, column_name) IN (('push_subscription', 'tz'),
                      ('person', 'question_catchup_declined_at'), ('match_question', 'prompt_key'))""").fetchall()}
    assert pref['push_questions'] is True and pref['push_questions_off_at'] is None
    assert cols == {('push_subscription', 'tz'), ('person', 'question_catchup_declined_at'),
                    ('match_question', 'prompt_key')}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0067.py -q -p no:warnings`
Expected: every test errors in `_applied_twice` with `FileNotFoundError` for `0067_quick_questions.sql`.

- [ ] **Step 3: Write the migration**

Create `migrations/0067_quick_questions.sql`:

```sql
-- 0067_quick_questions.sql
-- Quick questions, release 1 (TEC-1845,
-- docs/superpowers/specs/2026-10-13-profile-prompts-design.md, revision of
-- 16 Oct; plan docs/superpowers/plans/2026-10-16-quick-questions-release-1.md).
--
--   prompt_bank        gains format and options. The 14 choice questions from
--                      the guide are seeded active; its 20 open questions are
--                      seeded inactive and wait for written answers in
--                      release 2. Seeded with ON CONFLICT DO NOTHING, so a
--                      second run never undoes the owner's edits.
--   prompt_answer      one answer per member per question. Release 1 fills
--                      choice_key only; text and text_status are release 2's.
--   question_drop      the approved weekly schedule: which question goes live
--                      on which drop day (service/questions/schedule.py).
--   match_question     the one question both members of a match answer.
--   push_subscription.tz             the device's IANA time zone, for 18:00
--                                    local pushes and quiet hours.
--   notification_preference.push_questions (default on, owner decision of
--                      16 Oct) and push_questions_off_at, stamped when a
--                      member turns it off, so switch-offs can be counted.
--   push_tap           a landing from a question push (?src=).
--   person.question_catchup_declined_at  "Not now" on the catch-up offer,
--                      held on every device.
--
-- No question about plural marriage. Idempotent: the deploy may run this
-- file more than once.

ALTER TABLE prompt_bank ADD COLUMN IF NOT EXISTS format TEXT NOT NULL DEFAULT 'text';
ALTER TABLE prompt_bank ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE prompt_bank DROP CONSTRAINT IF EXISTS prompt_bank_format_check;
-- CASE, not OR: jsonb_array_length raises on a non-array, and only CASE
-- fixes the order of evaluation.
ALTER TABLE prompt_bank ADD CONSTRAINT prompt_bank_format_check CHECK (
  CASE format
    WHEN 'text' THEN options = '[]'::jsonb
    WHEN 'either_or' THEN CASE WHEN jsonb_typeof(options) = 'array'
                               THEN jsonb_array_length(options) = 2 ELSE FALSE END
    WHEN 'pick_one' THEN CASE WHEN jsonb_typeof(options) = 'array'
                              THEN jsonb_array_length(options) BETWEEN 3 AND 4 ELSE FALSE END
    ELSE FALSE
  END);

INSERT INTO prompt_bank (key, text, category, format, options, active, sort) VALUES
  ('host-or-dessert', 'Would you rather host the feast meal or be the guest who brings dessert?',
   'Would you rather', 'either_or',
   '[{"key":"host","label":"Hosting the feast meal"},{"key":"dessert","label":"Bringing dessert"}]', TRUE, 10),
  ('mountains-or-sea', 'Would you rather wake up to mountains or the sea?',
   'Would you rather', 'either_or',
   '[{"key":"mountains","label":"Mountains"},{"key":"sea","label":"The sea"}]', TRUE, 20),
  ('cabin-or-city', 'Would you rather spend a week in a cabin with no signal or a week exploring a city you have never seen?',
   'Would you rather', 'either_or',
   '[{"key":"cabin","label":"A cabin with no signal"},{"key":"city","label":"A new city to explore"}]', TRUE, 30),
  ('grow-or-market', 'Would you rather grow your own vegetables or know every good market stall for miles around?',
   'Would you rather', 'either_or',
   '[{"key":"grow","label":"Growing vegetables"},{"key":"market","label":"Knowing every good market stall"}]', TRUE, 40),
  ('language-or-instrument', 'Would you rather learn a new language or a new instrument?',
   'Would you rather', 'either_or',
   '[{"key":"language","label":"A new language"},{"key":"instrument","label":"A new instrument"}]', TRUE, 50),
  ('coffee-or-tea', 'Coffee, tea or something else?',
   'Mornings, evenings and how you rest', 'pick_one',
   '[{"key":"coffee","label":"Coffee"},{"key":"tea","label":"Tea"},{"key":"other","label":"Something else"}]', TRUE, 60),
  ('morning-or-night', 'Are you up with the sun, or do you do your best thinking after dark?',
   'Mornings, evenings and how you rest', 'either_or',
   '[{"key":"early","label":"Early mornings"},{"key":"late","label":"Late evenings"}]', TRUE, 70),
  ('sabbath-afternoon', 'What does the best Sabbath afternoon look like to you?',
   'Mornings, evenings and how you rest', 'pick_one',
   '[{"key":"walk","label":"A long walk"},{"key":"nap","label":"A nap"},{"key":"table","label":"A table full of friends"}]', TRUE, 80),
  ('people-or-quiet', 'When you need to recharge, do you look for people or for quiet?',
   'Mornings, evenings and how you rest', 'either_or',
   '[{"key":"people","label":"People"},{"key":"quiet","label":"Quiet"}]', TRUE, 90),
  ('family-table', 'Big family table or small and cosy?',
   'Family life and traditions', 'either_or',
   '[{"key":"big","label":"A big family table"},{"key":"cosy","label":"Small and cosy"}]', TRUE, 100),
  ('window-or-aisle', 'Window seat or aisle?',
   'Little preferences that reveal a lot', 'either_or',
   '[{"key":"window","label":"The window seat"},{"key":"aisle","label":"The aisle seat"}]', TRUE, 110),
  ('early-or-late', 'Are you early, on time or a little late?',
   'Little preferences that reveal a lot', 'pick_one',
   '[{"key":"early","label":"Early"},{"key":"on-time","label":"On time"},{"key":"late","label":"A little late"}]', TRUE, 120),
  ('plan-or-decide', 'Do you plan a trip down to the hour or decide when you get there?',
   'Little preferences that reveal a lot', 'either_or',
   '[{"key":"plan","label":"Planning to the hour"},{"key":"decide","label":"Deciding on the day"}]', TRUE, 130),
  ('city-town-or-country', 'City, small town or a long drive to the nearest neighbour?',
   'Little preferences that reveal a lot', 'pick_one',
   '[{"key":"city","label":"The city"},{"key":"town","label":"A small town"},{"key":"drive","label":"A long drive to the nearest neighbour"}]', TRUE, 140),
  ('cook-for-guests', 'What dish could you cook for guests without looking at a recipe?', 'Favourites', 'text', '[]', FALSE, 200),
  ('feast-food', 'Which feast food do you look forward to all year?', 'Favourites', 'text', '[]', FALSE, 210),
  ('song-every-word', 'What song have you played so many times you know every word?', 'Favourites', 'text', '[]', FALSE, 220),
  ('book-or-album', 'Which book or album would you hand to a friend who wanted to understand you?', 'Favourites', 'text', '[]', FALSE, 230),
  ('hobby-to-start', 'What hobby have you always meant to start?', 'Favourites', 'text', '[]', FALSE, 240),
  ('surprisingly-good-at', 'What are you surprisingly good at?', 'Favourites', 'text', '[]', FALSE, 250),
  ('place-to-return', 'Which place have you visited that you would happily go back to tomorrow?', 'Favourites', 'text', '[]', FALSE, 260),
  ('first-hour', 'What does the first hour of your day look like?', 'Mornings, evenings and how you rest', 'text', '[]', FALSE, 270),
  ('ideal-free-day', 'Describe your ideal free day from the moment you wake up.', 'Describe your ideal', 'text', '[]', FALSE, 280),
  ('ideal-kitchen-table', 'Describe your ideal kitchen table: how big, how many chairs and what usually ends up on it.', 'Describe your ideal', 'text', '[]', FALSE, 290),
  ('ideal-trip', 'Describe your ideal trip, including how you would get there.', 'Describe your ideal', 'text', '[]', FALSE, 300),
  ('ideal-picnic', 'Describe your ideal picnic, right down to what is in the basket.', 'Describe your ideal', 'text', '[]', FALSE, 310),
  ('tradition-to-carry-on', 'What family tradition would you love to carry on?', 'Family life and traditions', 'text', '[]', FALSE, 320),
  ('best-cook', 'Who is the best cook in your family, and what do they make?', 'Family life and traditions', 'text', '[]', FALSE, 330),
  ('favourite-feast-gathering', 'What feast gathering has been your favourite so far, and what made it so good?', 'Family life and traditions', 'text', '[]', FALSE, 340),
  ('family-game', 'Which game always comes out when your family gets together?', 'Family life and traditions', 'text', '[]', FALSE, 350),
  ('pet', 'Do you have a pet, or one you dream of having?', 'Family life and traditions', 'text', '[]', FALSE, 360),
  ('secret-chore', 'Which chore do you secretly enjoy?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 370),
  ('thing-with-a-story', 'What is one thing in your home with a story behind it?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 380),
  ('small-good-thing', 'What small thing always makes your day better?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 390)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS prompt_answer (
  person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  prompt_key   TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE ON DELETE CASCADE,
  choice_key   TEXT,
  text         TEXT,
  text_status  TEXT         CHECK (text_status IN ('pending', 'approved', 'rejected')),
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (person_id, prompt_key),
  CHECK (choice_key IS NOT NULL OR text IS NOT NULL),
  CHECK ((text IS NULL) = (text_status IS NULL))
);
CREATE INDEX IF NOT EXISTS idx__prompt_answer__prompt_choice ON prompt_answer (prompt_key, choice_key);

CREATE TABLE IF NOT EXISTS question_drop (
  live_on      DATE         PRIMARY KEY,
  prompt_key   TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE,
  approved_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS match_question (
  match_id    UUID         PRIMARY KEY REFERENCES ahavah_match(match_id) ON DELETE CASCADE,
  prompt_key  TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE ON DELETE CASCADE,
  offered_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE push_subscription ADD COLUMN IF NOT EXISTS tz TEXT;

ALTER TABLE notification_preference
  ADD COLUMN IF NOT EXISTS push_questions BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS push_questions_off_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS push_tap (
  id         BIGSERIAL    PRIMARY KEY,
  person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  src        TEXT         NOT NULL CHECK (src IN ('qpush', 'mpush', 'lpush')),
  tapped_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__push_tap__tapped_at ON push_tap (tapped_at);
CREATE INDEX IF NOT EXISTS idx__push_tap__person_src ON push_tap (person_id, src, tapped_at);

ALTER TABLE person ADD COLUMN IF NOT EXISTS question_catchup_declined_at TIMESTAMPTZ;
```

Append to `tests/conftest.py`:

```python
# ---------------------------------------------------------------------------
# Quick questions (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0067 is idempotent, so applying it here is what the deploy does.
# A module that reads the quick-question tables asks for it with
#     pytestmark = pytest.mark.usefixtures('questions_schema')
# make_question() adds an active choice question with unique keys, so a
# test's answers and splits never meet another test's. drops.add() sets a
# question_drop row and puts back any row it replaced.

@pytest.fixture(scope='session')
def questions_schema(growth_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0067_quick_questions.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


@pytest.fixture
def make_question(questions_schema):
    import json
    from uuid import uuid4

    from database import api_tx

    made: list[str] = []

    def _make(labels=('Yes', 'No'), *, active: bool = True, sort: int = 0,
              text: str | None = None) -> dict:
        key = f'tq-{uuid4().hex[:10]}'
        fmt = 'either_or' if len(labels) == 2 else 'pick_one'
        options = [dict(key=f'c{i}-{uuid4().hex[:6]}', label=label) for i, label in enumerate(labels)]
        text = text or f'Test question {key}?'
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO prompt_bank (key, text, category, format, options, active, sort)
                   VALUES (%(k)s, %(t)s, 'test', %(f)s, %(o)s::jsonb, %(a)s, %(s)s)""",
                dict(k=key, t=text, f=fmt, o=json.dumps(options), a=active, s=sort))
        made.append(key)
        return dict(key=key, text=text, format=fmt, options=options)

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE prompt_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM prompt_bank WHERE key = ANY(%(k)s)', dict(k=made))


@pytest.fixture
def drops(questions_schema):
    from database import api_tx

    made: list = []
    saved: list[dict] = []

    def _add(live_on, key: str, approved: bool = True) -> None:
        with api_tx() as tx:
            old = tx.execute(
                'SELECT live_on, prompt_key, approved_at, created_at FROM question_drop WHERE live_on = %(d)s',
                dict(d=live_on)).fetchone()
            if old is not None and live_on not in made:
                saved.append(dict(old))
            tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=live_on))
            tx.execute(
                """INSERT INTO question_drop (live_on, prompt_key, approved_at)
                   VALUES (%(d)s, %(k)s, CASE WHEN %(a)s::boolean THEN NOW() END)""",
                dict(d=live_on, k=key, a=approved))
        made.append(live_on)

    yield _add
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on = ANY(%(d)s)', dict(d=made))
        for row in saved:
            tx.execute(
                """INSERT INTO question_drop (live_on, prompt_key, approved_at, created_at)
                   VALUES (%(live_on)s, %(prompt_key)s, %(approved_at)s, %(created_at)s)
                   ON CONFLICT (live_on) DO NOTHING""", row)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_migration_0067.py -q -p no:warnings`
Expected: `13 passed`.

- [ ] **Step 5: Apply 0067 to the shared test database**

Later tasks change code that existing suites run (`/prospect-profile`, the preferences routes, the gap). The file is idempotent, so apply it alone; never reset the container:
Run: `cd /d/Antigravity/ahavah-api && docker exec -i ahavah-api-postgres-1 psql -X -v ON_ERROR_STOP=1 -U postgres -d duo_api < migrations/0067_quick_questions.sql`
Expected: a list of `ALTER TABLE`, `INSERT 0 n`, `CREATE TABLE` and `CREATE INDEX` lines, exit code 0.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add migrations/0067_quick_questions.sql tests/test_migration_0067.py tests/conftest.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the quick questions schema and the bank of 34" -m "Refs: TEC-1845"
```

---

### Task 2: Answering a question, and the split

**Files:**
- Create: `service/questions/__init__.py`, `service/questions/bank.py`
- Create: `service/api/questions_routes.py`
- Modify: `service/api/__init__.py` (bottom, after `import service.api.admin.spotlight_routes`)
- Modify: `duotypes/__init__.py` (after `class PatchNotificationPreferences`)
- Test: `tests/test_question_answers.py` (create)

**Interfaces:**
- Consumes: Task 1's tables and `make_question`; `member_sql` from `service.admin.queries.members`.
- Produces, in `service.questions.bank`: `SPLIT_MIN = 5`, `CHOICE_FORMATS`, `LIVE` (SQL: the `prompt_bank` row aliased `b` is a live quick question), `AnswerRefused(ValueError)` with `'closed'` or `'bad_choice'`, `question_json(row) -> dict(key, text, format, options=[{key, label}])`, `live_question(tx, key) -> Optional[dict]`, `choice_of(tx, person_id, key) -> Optional[str]`, `split(tx, question) -> Optional[list[dict(key, n)]]`, `question_state(tx, person_id, question) -> dict(question, my_choice, counts)`, `save_answer(tx, person_id, key, choice_key, *, keep_existing=False) -> dict` (a question state), `my_answers(tx, person_id) -> list[dict(question, choice_key)]`. Routes: `PUT /answers/<key>` body `{choice_key, keep_existing?}` (200 state; 404 `{"error": "closed"}`; 400 `{"error": "bad_choice"}`), `GET /answers` (`{"answers": [...]}`). `duotypes.PutAnswer`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_answers.py`:

```python
"""Answering a quick question (TEC-1845).

One answer per member per question, changed by answering again. An email
click saves only when nothing is saved yet (keep_existing). A question that
is switched off, unknown or open (release 2) is closed. The split is counts,
shown only from 5 member answers and only to a member who has answered;
staff answers are not counted.
"""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')


def _member(make_person, sign_in, name: str) -> dict:
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def _answer(person_id: int, key: str, choice: str) -> None:
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)""", dict(p=person_id, k=key, c=choice))


def test_an_answer_is_saved_and_can_be_changed(client, make_person, sign_in, make_question):
    q = make_question()
    a, b = (o['key'] for o in q['options'])
    me = _member(make_person, sign_in, 'AnswerMe')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['my_choice'] == a and r.get_json()['counts'] is None
    assert r.get_json()['question'] == q
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=b))
    assert r.get_json()['my_choice'] == b
    mine = client.get('/answers', headers=me['headers']).get_json()['answers']
    assert [x['choice_key'] for x in mine if x['question']['key'] == q['key']] == [b]


def test_keep_existing_never_overwrites(client, make_person, sign_in, make_question):
    q = make_question()
    a, b = (o['key'] for o in q['options'])
    me = _member(make_person, sign_in, 'KeepMe')
    client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=b, keep_existing=True))
    assert r.status_code == 200 and r.get_json()['my_choice'] == a
    other = _member(make_person, sign_in, 'KeepFirst')
    r = client.put(f"/answers/{q['key']}", headers=other['headers'], json=dict(choice_key=b, keep_existing=True))
    assert r.get_json()['my_choice'] == b


def test_a_closed_or_unknown_question_is_refused(client, make_person, sign_in, make_question):
    off = make_question(active=False)
    me = _member(make_person, sign_in, 'ClosedMe')
    for key in (off['key'], 'no-such-question', 'pet'):
        r = client.put(f'/answers/{key}', headers=me['headers'],
                       json=dict(choice_key=off['options'][0]['key']))
        assert r.status_code == 404, key
        assert r.get_json() == dict(error='closed')


def test_a_choice_the_question_does_not_offer_is_refused(client, make_person, sign_in, make_question):
    q = make_question()
    me = _member(make_person, sign_in, 'BadChoice')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key='not-an-option'))
    assert r.status_code == 400 and r.get_json() == dict(error='bad_choice')


def test_the_split_shows_from_5_answers_to_a_member_who_answered(client, make_person, sign_in, make_question):
    q = make_question(labels=('Mountains', 'The sea'))
    a, b = (o['key'] for o in q['options'])
    for i, choice in enumerate((a, a, a)):
        _answer(make_person(name=f'Split{i}')['id'], q['key'], choice)
    fourth = _member(make_person, sign_in, 'SplitFourth')
    r = client.put(f"/answers/{q['key']}", headers=fourth['headers'], json=dict(choice_key=b))
    assert r.get_json()['counts'] is None, '4 answers must not show a split'
    fifth = _member(make_person, sign_in, 'SplitFifth')
    r = client.put(f"/answers/{q['key']}", headers=fifth['headers'], json=dict(choice_key=b))
    assert r.get_json()['counts'] == [dict(key=a, n=3), dict(key=b, n=2)]


def test_staff_answers_are_not_counted(client, make_person, sign_in, make_question):
    q = make_question()
    a, _ = (o['key'] for o in q['options'])
    for i in range(3):
        _answer(make_person(name=f'Counted{i}')['id'], q['key'], a)
    staff = make_person(name='StaffAnswer')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=staff['id']))
    _answer(staff['id'], q['key'], a)
    me = _member(make_person, sign_in, 'CountedMe')
    r = client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=a))
    assert r.get_json()['counts'] is None, 'the staff answer made it look like 5'


def test_signed_out_is_turned_away(client):
    r = client.put('/answers/mountains-or-sea', json=dict(choice_key='sea'))
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_answers.py -q -p no:warnings`
Expected: the route tests fail with 404 or 405 for `/answers` (no route), and `test_signed_out_is_turned_away` fails on the status code.

- [ ] **Step 3: Write the implementation**

Create `service/questions/__init__.py`:

```python
"""Quick questions, release 1 (TEC-1845).

docs/superpowers/specs/2026-10-13-profile-prompts-design.md (revision of
16 Oct) and docs/superpowers/plans/2026-10-16-quick-questions-release-1.md.

  bank      live questions, one member's answer, the split
  schedule  the weekly drop day and the current question
  member    what one member sees: the card, catch-up, Quick answers on a
            profile, the match question, the E2 line
  copy      push and E2 wording
  pushes    the silent-match, weekly and launch pushes
  admin     Admin > Questions
"""
```

Create `service/questions/bank.py`:

```python
"""Live questions, one member's answers and the split (TEC-1845).

Release 1 answers are taps on fixed options, never free text, so nothing a
member writes reaches another member. A question is live when it is active
and has a choice format; the open questions wait for release 2.

The split is counts, never percentages, and shows only from SPLIT_MIN
member answers, so a small count cannot point to a person. Staff answers
are not counted. A member sees a split only once they have answered.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from typing import Optional

from service.admin.queries.members import member_sql

SPLIT_MIN = 5
CHOICE_FORMATS = ('either_or', 'pick_one')
# SQL: the prompt_bank row aliased b is a live quick question.
LIVE = "b.active AND b.format IN ('either_or', 'pick_one')"


class AnswerRefused(ValueError):
    """'closed': no live question has that key. 'bad_choice': the question
    does not offer that option."""


_COLS = 'b.key, b.text, b.format, b.options'

_Q_QUESTION = f"SELECT {_COLS} FROM prompt_bank b WHERE b.key = %(k)s AND {LIVE}"

_Q_CHOICE = """
    SELECT choice_key FROM prompt_answer
     WHERE person_id = %(p)s AND prompt_key = %(k)s AND choice_key IS NOT NULL
"""

_Q_COUNTS = f"""
    SELECT a.choice_key, count(*) AS n
      FROM prompt_answer a
      JOIN person p ON p.id = a.person_id
     WHERE a.prompt_key = %(k)s AND a.choice_key IS NOT NULL
       AND p.activated AND {member_sql('p')}
     GROUP BY a.choice_key
"""

_Q_SAVE = """
    INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
    VALUES (%(p)s, %(k)s, %(c)s)
    ON CONFLICT (person_id, prompt_key) DO UPDATE
       SET choice_key = EXCLUDED.choice_key, updated_at = NOW()
"""

# An email click: saves only when nothing is saved yet (spec, Launch).
_Q_SAVE_IF_NEW = """
    INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
    VALUES (%(p)s, %(k)s, %(c)s)
    ON CONFLICT (person_id, prompt_key) DO NOTHING
"""

_Q_MY_ANSWERS = f"""
    SELECT {_COLS}, a.choice_key
      FROM prompt_answer a
      JOIN prompt_bank b ON b.key = a.prompt_key
     WHERE a.person_id = %(p)s AND a.choice_key IS NOT NULL AND {LIVE}
     ORDER BY b.sort, b.key
"""


def question_json(row) -> dict:
    return dict(key=row['key'], text=row['text'], format=row['format'],
                options=[dict(key=o['key'], label=o['label']) for o in row['options']])


def live_question(tx, key: str) -> Optional[dict]:
    row = tx.execute(_Q_QUESTION, dict(k=key)).fetchone()
    return question_json(row) if row else None


def choice_of(tx, person_id: int, key: str) -> Optional[str]:
    row = tx.execute(_Q_CHOICE, dict(p=person_id, k=key)).fetchone()
    return row['choice_key'] if row else None


def split(tx, question: dict) -> Optional[list[dict]]:
    """Counts per option, in the question's order, or None under SPLIT_MIN."""
    got = {r['choice_key']: int(r['n'])
           for r in tx.execute(_Q_COUNTS, dict(k=question['key'])).fetchall()}
    counts = [dict(key=o['key'], n=got.get(o['key'], 0)) for o in question['options']]
    return counts if sum(c['n'] for c in counts) >= SPLIT_MIN else None


def question_state(tx, person_id: int, question: dict) -> dict:
    mine = choice_of(tx, person_id, question['key'])
    return dict(question=question, my_choice=mine,
                counts=split(tx, question) if mine is not None else None)


def save_answer(tx, person_id: int, key: str, choice_key: str, *,
                keep_existing: bool = False) -> dict:
    question = live_question(tx, key)
    if question is None:
        raise AnswerRefused('closed')
    if choice_key not in {o['key'] for o in question['options']}:
        raise AnswerRefused('bad_choice')
    tx.execute(_Q_SAVE_IF_NEW if keep_existing else _Q_SAVE,
               dict(p=person_id, k=key, c=choice_key))
    return question_state(tx, person_id, question)


def my_answers(tx, person_id: int) -> list[dict]:
    return [dict(question=question_json(r), choice_key=r['choice_key'])
            for r in tx.execute(_Q_MY_ANSWERS, dict(p=person_id)).fetchall()]
```

In `duotypes/__init__.py`, after `class PatchNotificationPreferences` and its fields, add:

```python
class PutAnswer(BaseModel):
    """PUT /answers/<key> (TEC-1845). `keep_existing` is the email answer
    page's: it saves only when the member has no answer yet."""
    choice_key: str = Field(min_length=1, max_length=40)
    keep_existing: bool = False
```

Create `service/api/questions_routes.py`:

```python
"""Quick questions, the member routes (TEC-1845).

Imported at the bottom of service/api/__init__.py, as notifications_routes
is. Every route needs a signed-in member.
"""
import duotypes as t

from database import api_tx
from service.api.decorators import aget, aput, validate


@aput('/answers/<key>')
@validate(t.PutAnswer)
def put_answer(req: t.PutAnswer, s: t.SessionInfo, key: str):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.bank import AnswerRefused, save_answer
    try:
        with api_tx() as tx:
            return save_answer(tx, s.person_id, key, req.choice_key,
                               keep_existing=req.keep_existing)
    except AnswerRefused as e:
        reason = str(e)
        return dict(error=reason), (404 if reason == 'closed' else 400)


@aget('/answers')
def get_answers(s: t.SessionInfo):
    """The member's own answers, for their own profile."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.bank import my_answers
    with api_tx('read committed') as tx:
        return dict(answers=my_answers(tx, s.person_id))
```

In `service/api/__init__.py`, after the line `import service.api.admin.spotlight_routes  # noqa: E402,F401`, add:

```python
# Quick questions (TEC-1845).
import service.api.questions_routes  # noqa: E402,F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_answers.py -q -p no:warnings`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/__init__.py service/questions/bank.py service/api/questions_routes.py service/api/__init__.py duotypes/__init__.py tests/test_question_answers.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): answer a quick question with one tap, split shown from 5" -m "Refs: TEC-1845"
```

---

### Task 3: The weekly drop day, the card's question and the catch-up run

**Files:**
- Create: `service/questions/schedule.py`, `service/questions/member.py`
- Modify: `service/api/questions_routes.py` (append)
- Test: `tests/test_question_schedule.py` (create)

**Interfaces:**
- Consumes: `LIVE`, `question_json`, `question_state` (Task 2); `drops`, `make_question` (Task 1); `service.spotlight.restdays` read as a module (`rd.REST_DAYS`, `rd.KNOWN_THROUGH`, `rd.BARBADOS`, `rd.is_rest_period`, `rd.is_beyond_known`), so a test's monkeypatch reaches it.
- Produces, in `service.questions.schedule`: `CURRENT_FOR_DAYS = 14`, `FIRST_WEEKS: tuple[str, ...]`, `barbados_today(now: Optional[datetime] = None) -> date`, `week_start(day: date) -> date` (the Sunday), `drop_day(week_of: date) -> Optional[date]`, `week_starts_at(live_on: date) -> datetime`, `current_drop(tx, now=None) -> Optional[dict(live_on: date, question: dict)]`, `resting(now: datetime) -> bool`. In `service.questions.member`: `current_for(tx, person_id, now=None) -> dict(current)`, `catch_up_for(tx, person_id, now=None) -> dict(declined, questions)`, `decline_catch_up(tx, person_id) -> None`. Routes: `GET /questions/current`, `GET /questions/catch-up`, `POST /questions/catch-up/decline` (204).

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_schedule.py`:

```python
"""The weekly drop day, the card's question and the catch-up run (TEC-1845).

Owner decision 1 (16 Oct): the question drops on the first free day of each
Sunday-to-Saturday week by the lunar rule, never a fixed Sunday. A free day
is not a rest day and not the eve of one (a rest period starts 17:00
Barbados the evening before). Nothing is decided past KNOWN_THROUGH. The
card shows the latest approved drop for up to 14 days. The catch-up run
offers every active question the member has not answered, leaving out this
week's (decision 10), and "Not now" holds on every device.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.questions.schedule import barbados_today, current_drop, drop_day, week_start

pytestmark = pytest.mark.usefixtures('questions_schema')

SUN = date(2027, 1, 3)  # a Sunday


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2027, 12, 31))

    def rest(*days):
        monkeypatch.setattr(rd, 'REST_DAYS', tuple(days))
    rest()
    return rest


def test_a_week_runs_sunday_to_saturday():
    assert [week_start(SUN + timedelta(days=i)) for i in range(7)] == [SUN] * 7
    assert week_start(SUN + timedelta(days=7)) == SUN + timedelta(days=7)


def test_with_no_rest_day_the_drop_is_the_sunday(calendar):
    assert drop_day(SUN + timedelta(days=4)) == SUN


def test_a_rest_sunday_and_monday_move_the_drop_to_tuesday(calendar):
    calendar(SUN, SUN + timedelta(days=1))
    assert drop_day(SUN) == SUN + timedelta(days=2)


def test_the_eve_of_a_rest_day_is_not_a_drop_day(calendar):
    calendar(SUN + timedelta(days=1))
    assert drop_day(SUN) == SUN + timedelta(days=2)


def test_a_week_past_the_known_calendar_has_no_drop(calendar, monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', SUN - timedelta(days=1))
    assert drop_day(SUN) is None
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', SUN + timedelta(days=2))
    calendar(SUN, SUN + timedelta(days=1))
    assert drop_day(SUN) is None, 'Tuesday needs Wednesday to be known'


@pytest.mark.real_calendar
def test_the_owners_october_calendar():
    # restdays.py as entered on 1 Oct: both candidate dates of each eighth
    # month Sabbath, every Sunday and Monday to 9 Nov. Update this test when
    # the owner confirms the month or reads the ninth.
    assert drop_day(date(2026, 10, 18)) == date(2026, 10, 20)
    assert drop_day(date(2026, 10, 25)) == date(2026, 10, 27)
    assert drop_day(date(2026, 11, 1)) == date(2026, 11, 3)
    assert drop_day(date(2026, 11, 8)) is None


def _at(day: date) -> datetime:
    return datetime.combine(day, time(15, 0), timezone.utc)


def test_the_current_question_is_the_latest_approved_drop(make_question, drops):
    q1, q2, q3 = make_question(), make_question(), make_question()
    drops(SUN, q1['key'])
    drops(SUN + timedelta(days=7), q2['key'])
    drops(SUN + timedelta(days=14), q3['key'], approved=False)
    with api_tx('read committed') as tx:
        got = current_drop(tx, _at(SUN + timedelta(days=16)))
    assert got == dict(live_on=SUN + timedelta(days=7), question=q2)


def test_a_drop_stays_current_for_14_days_and_not_before_it_goes_live(make_question, drops):
    q = make_question()
    drops(SUN, q['key'])
    with api_tx('read committed') as tx:
        assert current_drop(tx, _at(SUN - timedelta(days=1))) is None
        assert current_drop(tx, _at(SUN + timedelta(days=13)))['question'] == q
        assert current_drop(tx, _at(SUN + timedelta(days=14))) is None


def test_a_switched_off_question_is_not_current(make_question, drops):
    q = make_question()
    drops(SUN, q['key'])
    with api_tx() as tx:
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE key = %(k)s', dict(k=q['key']))
        assert current_drop(tx, _at(SUN)) is None


def _member(make_person, sign_in, name):
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def test_the_card_question_comes_with_the_members_answer(client, make_person, sign_in, make_question, drops):
    q = make_question()
    today = barbados_today()
    drops(today, q['key'])
    me = _member(make_person, sign_in, 'CardMe')
    cur = client.get('/questions/current', headers=me['headers']).get_json()['current']
    assert (cur['live_on'], cur['question'], cur['my_choice'], cur['counts']) == (today.isoformat(), q, None, None)
    client.put(f"/answers/{q['key']}", headers=me['headers'], json=dict(choice_key=q['options'][1]['key']))
    cur = client.get('/questions/current', headers=me['headers']).get_json()['current']
    assert cur['my_choice'] == q['options'][1]['key']


def test_catch_up_offers_every_active_question_except_this_weeks(client, make_person, sign_in, make_question, drops):
    week, other = make_question(), make_question()
    drops(barbados_today(), week['key'])
    me = _member(make_person, sign_in, 'CatchUpMe')
    keys = [x['key'] for x in client.get('/questions/catch-up', headers=me['headers']).get_json()['questions']]
    assert other['key'] in keys and 'mountains-or-sea' in keys
    assert week['key'] not in keys and 'pet' not in keys
    client.put(f"/answers/{other['key']}", headers=me['headers'], json=dict(choice_key=other['options'][0]['key']))
    keys = [x['key'] for x in client.get('/questions/catch-up', headers=me['headers']).get_json()['questions']]
    assert other['key'] not in keys


def test_not_now_holds_on_every_device(client, make_person, sign_in):
    p = make_person(name='DeclineMe')
    phone, laptop = sign_in(p), sign_in(p)
    assert client.get('/questions/catch-up', headers=laptop).get_json()['declined'] is False
    assert client.post('/questions/catch-up/decline', headers=phone).status_code == 204
    with api_tx('read committed') as tx:
        first = tx.execute('SELECT question_catchup_declined_at AS d FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['d']
    assert client.get('/questions/catch-up', headers=laptop).get_json()['declined'] is True
    client.post('/questions/catch-up/decline', headers=laptop)
    with api_tx('read committed') as tx:
        again = tx.execute('SELECT question_catchup_declined_at AS d FROM person WHERE id = %(i)s',
                           dict(i=p['id'])).fetchone()['d']
    assert again == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_schedule.py -q -p no:warnings`
Expected: collection error, `ModuleNotFoundError: No module named 'service.questions.schedule'`.

- [ ] **Step 3: Write the implementation**

Create `service/questions/schedule.py`:

```python
"""When each week's quick question goes live (TEC-1845).

Owner decision 1 (16 Oct 2026): the question drops on the first free day of
each Sunday-to-Saturday week by the lunar rule in
service/spotlight/restdays.py, never a fixed Sunday, and the weekly push
goes at 18:00 the member's local time on that day.

A free day is not a rest day and not the eve of one: a rest period starts at
17:00 Barbados the evening before, and 18:00 anywhere in the Americas falls
after that. The day after a drop day must be known too, so the last
possible drop day is the day before KNOWN_THROUGH. A week with no free day
has no question.

The current question is the latest approved drop on or before today's
Barbados date, for at most CURRENT_FOR_DAYS: it stays on the card until the
next one goes live.

restdays is read as a module on every call, so a test can move its dates.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import service.spotlight.restdays as rd
from service.questions.bank import LIVE, question_json

CURRENT_FOR_DAYS = 14

# Owner decision 2 (16 Oct): the first 6 weeks, in order. Admin > Questions
# proposes them for empty weeks; the owner approves or reorders.
FIRST_WEEKS = ('mountains-or-sea', 'window-or-aisle', 'sabbath-afternoon',
               'early-or-late', 'host-or-dessert', 'people-or-quiet')


def barbados_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(rd.BARBADOS).date()


def week_start(day: date) -> date:
    """The Sunday that starts `day`'s week."""
    return day - timedelta(days=day.isoweekday() % 7)


def _free(day: date) -> bool:
    return day not in rd.REST_DAYS and (day + timedelta(days=1)) not in rd.REST_DAYS


def drop_day(week_of: date) -> Optional[date]:
    start = week_start(week_of)
    for i in range(7):
        day = start + timedelta(days=i)
        if day + timedelta(days=1) > rd.KNOWN_THROUGH:
            return None
        if _free(day):
            return day
    return None


def week_starts_at(live_on: date) -> datetime:
    """The start of a question week, for the 1-push-a-week budget."""
    return datetime.combine(live_on, time(0, 0), rd.BARBADOS)


def resting(now: datetime) -> bool:
    """Inside a rest period, or past the last date the calendar is read for:
    no question push and no launch email goes."""
    return rd.is_rest_period(now) or rd.is_beyond_known(now)


# The latest approved drop first, then whether its question is still live:
# switching this week's question off empties the card, it never brings back
# an older week's.
_Q_CURRENT = f"""
    SELECT d.live_on, b.key, b.text, b.format, b.options
      FROM (SELECT live_on, prompt_key FROM question_drop
             WHERE approved_at IS NOT NULL
               AND live_on <= %(today)s
               AND live_on > %(today)s::date - {CURRENT_FOR_DAYS}
             ORDER BY live_on DESC LIMIT 1) d
      JOIN prompt_bank b ON b.key = d.prompt_key AND {LIVE}
"""


def current_drop(tx, now: Optional[datetime] = None) -> Optional[dict]:
    row = tx.execute(_Q_CURRENT, dict(today=barbados_today(now))).fetchone()
    return dict(live_on=row['live_on'], question=question_json(row)) if row else None
```

Create `service/questions/member.py`:

```python
"""What one member sees of the quick questions (TEC-1845).

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from service.questions.bank import LIVE, question_json, question_state
from service.questions.schedule import current_drop

_Q_CATCH_UP = f"""
    SELECT b.key, b.text, b.format, b.options
      FROM prompt_bank b
     WHERE {LIVE}
       AND b.key <> ALL(%(skip)s)
       AND NOT EXISTS (SELECT 1 FROM prompt_answer a
                        WHERE a.person_id = %(p)s AND a.prompt_key = b.key)
     ORDER BY b.sort, b.key
"""

_Q_DECLINED = """
    SELECT question_catchup_declined_at IS NOT NULL AS declined FROM person WHERE id = %(p)s
"""

# The first "Not now" is the one kept.
_Q_DECLINE = """
    UPDATE person SET question_catchup_declined_at = COALESCE(question_catchup_declined_at, NOW())
     WHERE id = %(p)s
"""


def current_for(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    drop = current_drop(tx, now)
    if drop is None:
        return dict(current=None)
    return dict(current=dict(live_on=drop['live_on'].isoformat(),
                             **question_state(tx, person_id, drop['question'])))


def catch_up_for(tx, person_id: int, now: Optional[datetime] = None) -> dict:
    """Every live question the member has not answered, leaving out this
    week's, which has the card to itself (owner decision 10)."""
    drop = current_drop(tx, now)
    skip = [drop['question']['key']] if drop else []
    row = tx.execute(_Q_DECLINED, dict(p=person_id)).fetchone()
    return dict(declined=bool(row and row['declined']),
                questions=[question_json(r) for r in
                           tx.execute(_Q_CATCH_UP, dict(p=person_id, skip=skip)).fetchall()])


def decline_catch_up(tx, person_id: int) -> None:
    tx.execute(_Q_DECLINE, dict(p=person_id))
```

Append to `service/api/questions_routes.py` (and add `apost` to its decorator import):

```python
@aget('/questions/current')
def get_current_question(s: t.SessionInfo):
    """This week's question, the member's answer and the split once there
    are 5 answers and the member has given one."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import current_for
    with api_tx('read committed') as tx:
        return current_for(tx, s.person_id)


@aget('/questions/catch-up')
def get_catch_up(s: t.SessionInfo):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import catch_up_for
    with api_tx('read committed') as tx:
        return catch_up_for(tx, s.person_id)


@apost('/questions/catch-up/decline')
def post_catch_up_decline(s: t.SessionInfo):
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import decline_catch_up
    with api_tx() as tx:
        decline_catch_up(tx, s.person_id)
    return '', 204
```

The decorator import line at the top of `service/api/questions_routes.py` becomes:

```python
from service.api.decorators import aget, apost, aput, validate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_schedule.py -q -p no:warnings`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/schedule.py service/questions/member.py service/api/questions_routes.py tests/test_question_schedule.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the weekly drop day by the lunar rule, the card and catch-up" -m "Refs: TEC-1845"
```

---

### Task 4: Quick answers on a profile, locked until the viewer answers

**Files:**
- Modify: `service/questions/member.py` (append)
- Modify: `service/person/__init__.py` (`get_prospect_profile`, the signed-in full-profile path, before `return profile` at the end of the function)
- Test: `tests/test_quick_answers_profile.py` (create)

**Interfaces:**
- Consumes: `LIVE`, `question_json` (Task 2); the `person_id` key of the `/prospect-profile` JSON (`Q_SELECT_PROSPECT_PROFILE`).
- Produces: `service.questions.member.quick_answers_for(tx, viewer_id: int, prospect_id: int) -> list[dict(question, locked: bool, choice_key: Optional[str], shared: bool)]`; `/prospect-profile/<uuid>` for a signed-in viewer of a full profile carries `quick_answers` (never on the anonymous or `limited` responses).

- [ ] **Step 1: Write the failing test**

Create `tests/test_quick_answers_profile.py`:

```python
"""Quick answers on a profile (TEC-1845, spec "Where answers show").

The server enforces "answer to see theirs": a question the viewer has not
answered comes back locked, with no choice anywhere in the response. Shared
answers are marked. Never to signed-out viewers and never on a limited
(hidden) profile. A question switched off leaves every profile.
"""
from __future__ import annotations

import json

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')

_COUNTRY = 'XQ'


@pytest.fixture
def world(make_person, add_photo, sign_in):
    """As tests/test_photo_gate.py builds it: a viewer and a woman with an
    approved face photo, in each other's search country."""
    viewer = make_person(name='QaViewer', gender='Man')
    other = make_person(name='QaOther', gender='Woman')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET activated = TRUE, country = %(c)s,
                      show_my_location = TRUE, last_online_time = NOW(),
                      ahavah_extra = COALESCE(ahavah_extra, '{}'::jsonb)
                                     || '{"citySet": true}'::jsonb
                WHERE id = ANY(%(i)s)""",
            dict(c=_COUNTRY, i=[viewer['id'], other['id']]))
        tx.execute("INSERT INTO search_preference_gender (person_id, gender_id) "
                   "SELECT %(i)s, id FROM gender WHERE name = 'Woman'", dict(i=viewer['id']))
        tx.execute("INSERT INTO search_preference_country (person_id, country) "
                   "VALUES (%(i)s, %(c)s)", dict(i=viewer['id'], c=_COUNTRY))
    add_photo(other['id'], position=1, face_count=1)
    return dict(viewer=viewer, other=other, headers=sign_in(viewer))


def _answer(person_id, question, index):
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)
                      ON CONFLICT (person_id, prompt_key) DO UPDATE SET choice_key = EXCLUDED.choice_key""",
                   dict(p=person_id, k=question['key'], c=question['options'][index]['key']))


def _profile(client, world, headers=True):
    r = client.get(f"/prospect-profile/{world['other']['uuid']}",
                   headers=world['headers'] if headers else None)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def _by_key(r) -> dict:
    return {x['question']['key']: x for x in r.get_json()['quick_answers']}


def test_a_question_the_viewer_has_not_answered_comes_back_locked(client, world, make_question):
    shared, locked = make_question(), make_question()
    _answer(world['other']['id'], shared, 0)
    _answer(world['other']['id'], locked, 1)
    _answer(world['viewer']['id'], shared, 0)
    r = _profile(client, world)
    got = _by_key(r)
    assert got[shared['key']] == dict(question=shared, locked=False,
                                      choice_key=shared['options'][0]['key'], shared=True)
    assert got[locked['key']] == dict(question=locked, locked=True, choice_key=None, shared=False)
    # The question lists every option key, as it should. Anywhere else in
    # the response, their locked choice is a leak.
    j = r.get_json()
    elsewhere = dict(j, quick_answers=[dict(x, question=None) for x in j['quick_answers']])
    assert locked['options'][1]['key'] not in json.dumps(elsewhere), 'their locked answer leaked'


def test_a_different_answer_is_shown_but_not_shared(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    _answer(world['viewer']['id'], q, 1)
    got = _by_key(_profile(client, world))[q['key']]
    assert (got['locked'], got['choice_key'], got['shared']) == (False, q['options'][0]['key'], False)


def test_signed_out_viewers_get_no_quick_answers(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    assert 'quick_answers' not in _profile(client, world, headers=False).get_json()


def test_a_hidden_members_short_profile_carries_none(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    with api_tx() as tx:
        tx.execute('UPDATE person SET hide_me_from_strangers = TRUE WHERE id = %(i)s', dict(i=world['other']['id']))
    j = _profile(client, world).get_json()
    assert j['limited'] is True and 'quick_answers' not in j


def test_an_answer_to_a_question_switched_off_is_not_shown(client, world, make_question):
    q = make_question()
    _answer(world['other']['id'], q, 0)
    with api_tx() as tx:
        tx.execute('UPDATE prompt_bank SET active = FALSE WHERE key = %(k)s', dict(k=q['key']))
    assert q['key'] not in _by_key(_profile(client, world))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_quick_answers_profile.py -q -p no:warnings`
Expected: the three tests that read `quick_answers` fail with `KeyError: 'quick_answers'`; the signed-out and hidden tests pass already.

- [ ] **Step 3: Write the implementation**

Append to `service/questions/member.py`:

```python
# Only the prospect's answers to live questions. The viewer's own answer
# decides the lock: no answer from the viewer, no choice in the response.
_Q_QUICK_ANSWERS = f"""
    SELECT b.key, b.text, b.format, b.options,
           theirs.choice_key AS theirs, mine.choice_key AS mine
      FROM prompt_answer theirs
      JOIN prompt_bank b ON b.key = theirs.prompt_key AND {LIVE}
      LEFT JOIN prompt_answer mine
             ON mine.person_id = %(viewer)s AND mine.prompt_key = theirs.prompt_key
            AND mine.choice_key IS NOT NULL
     WHERE theirs.person_id = %(prospect)s AND theirs.choice_key IS NOT NULL
     ORDER BY b.sort, b.key
"""


def quick_answers_for(tx, viewer_id: int, prospect_id: int) -> list[dict]:
    out = []
    for r in tx.execute(_Q_QUICK_ANSWERS, dict(viewer=viewer_id, prospect=prospect_id)).fetchall():
        locked = r['mine'] is None
        out.append(dict(question=question_json(r), locked=locked,
                        choice_key=None if locked else r['theirs'],
                        shared=not locked and r['mine'] == r['theirs']))
    return out
```

In `service/person/__init__.py`, in `get_prospect_profile`, replace the end of the function:

```python
    try:
        from service.notifications import record_profile_view
        record_profile_view(viewer_id=s.person_id, viewed_uuid=prospect_uuid)
    except Exception:
        pass

    return profile
```

with:

```python
    try:
        from service.notifications import record_profile_view
        record_profile_view(viewer_id=s.person_id, viewed_uuid=prospect_uuid)
    except Exception:
        pass

    # Quick answers (TEC-1845): signed-in viewers of a full profile only.
    # The anonymous and limited paths returned above, so neither carries
    # them. Locked for the viewer until they answer the same question.
    from service.questions.member import quick_answers_for
    with api_tx('READ COMMITTED') as tx:
        profile['quick_answers'] = quick_answers_for(tx, s.person_id, profile['person_id'])

    return profile
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_quick_answers_profile.py tests/test_photo_gate.py -q -p no:warnings`
Expected: all pass (5 new, the photo gate suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/member.py service/person/__init__.py tests/test_quick_answers_profile.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): Quick answers on a profile, locked until the viewer answers" -m "Refs: TEC-1845"
```

---

### Task 5: The shared question in a new match

**Files:**
- Modify: `service/questions/member.py` (append)
- Modify: `service/api/questions_routes.py` (append)
- Test: `tests/test_conversation_context.py` (create)

**Interfaces:**
- Consumes: `choice_of`, `LIVE`, `question_json` (Task 2); `ahavah_match` (`user_a_id` is always the lower id); `is_blocked_pair`.
- Produces: `service.questions.member.ensure_match_question(tx, match_id: str, a_id: int, b_id: int) -> Optional[dict]` (the question; assigns once, preferring one neither member has answered), `conversation_context(tx, person_id: int, other_uuid: str) -> Optional[dict(match_question)]` (None when not matched); route `GET /conversation-context/<prospect_uuid>` returning `{"match_question": null | {question, mine, they_answered, theirs}}`, 404 when not matched. `theirs` is null until `mine` is set.

- [ ] **Step 1: Write the failing test**

Create `tests/test_conversation_context.py`:

```python
"""The shared question in a new match (TEC-1845, spec "What members get" 5).

Both members get the same question, chosen once: one neither has answered
if there is one. Each answers first, then sees the other's. No context
without a match, or once the other member is deactivated. Nothing is
written into the chat server.
"""
from __future__ import annotations

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')


@pytest.fixture
def pair(make_person, sign_in):
    a, b = make_person(name='CtxA', gender='Man'), make_person(name='CtxB', gender='Woman')
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        match_id = str(tx.execute("""INSERT INTO ahavah_match (user_a_id, user_b_id)
                                     VALUES (%(a)s, %(b)s) RETURNING match_id""",
                                  dict(a=lo, b=hi)).fetchone()['match_id'])
    return dict(a=dict(a, headers=sign_in(a)), b=dict(b, headers=sign_in(b)), match_id=match_id)


def _ctx(client, me, other):
    return client.get(f"/conversation-context/{other['uuid']}", headers=me['headers'])


def test_both_members_get_the_same_question(client, pair):
    ra, rb = _ctx(client, pair['a'], pair['b']), _ctx(client, pair['b'], pair['a'])
    assert ra.status_code == rb.status_code == 200, ra.get_data(as_text=True)
    assert ra.get_json()['match_question']['question'] == rb.get_json()['match_question']['question']
    with api_tx('read committed') as tx:
        n = tx.execute('SELECT count(*) AS n FROM match_question WHERE match_id = %(m)s::uuid',
                       dict(m=pair['match_id'])).fetchone()['n']
    assert n == 1


def test_the_question_is_one_neither_member_has_answered(client, pair, make_question):
    answered = make_question(sort=-100)
    fresh = make_question(sort=-99)
    with api_tx() as tx:
        tx.execute("""INSERT INTO prompt_answer (person_id, prompt_key, choice_key)
                      VALUES (%(p)s, %(k)s, %(c)s)""",
                   dict(p=pair['a']['id'], k=answered['key'], c=answered['options'][0]['key']))
    assert _ctx(client, pair['a'], pair['b']).get_json()['match_question']['question']['key'] == fresh['key']


def test_theirs_stays_hidden_until_you_answer(client, pair):
    q = _ctx(client, pair['a'], pair['b']).get_json()['match_question']['question']
    first, second = (o['key'] for o in q['options'][:2])
    client.put(f"/answers/{q['key']}", headers=pair['b']['headers'], json=dict(choice_key=first))
    mq = _ctx(client, pair['a'], pair['b']).get_json()['match_question']
    assert (mq['mine'], mq['they_answered'], mq['theirs']) == (None, True, None)
    client.put(f"/answers/{q['key']}", headers=pair['a']['headers'], json=dict(choice_key=second))
    mq = _ctx(client, pair['a'], pair['b']).get_json()['match_question']
    assert (mq['mine'], mq['they_answered'], mq['theirs']) == (second, True, first)
    mq = _ctx(client, pair['b'], pair['a']).get_json()['match_question']
    assert (mq['mine'], mq['theirs']) == (first, second)


def test_no_context_without_a_match(client, pair, make_person):
    stranger = make_person(name='CtxStranger')
    assert _ctx(client, pair['a'], stranger).status_code == 404
    assert client.get('/conversation-context/not-a-uuid', headers=pair['a']['headers']).status_code == 404


def test_a_match_with_a_deactivated_member_has_no_context(client, pair):
    with api_tx() as tx:
        tx.execute('UPDATE person SET activated = FALSE WHERE id = %(i)s', dict(i=pair['b']['id']))
    assert _ctx(client, pair['a'], pair['b']).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_conversation_context.py -q -p no:warnings`
Expected: every test fails on a 404 or 405 from the missing route, except `test_no_context_without_a_match` and the deactivated test, which pass by accident.

- [ ] **Step 3: Write the implementation**

Append to `service/questions/member.py` (and add `choice_of` to its `service.questions.bank` import):

```python
_Q_MATCH = """
    SELECT m.match_id::text AS match_id, m.user_a_id, m.user_b_id, o.id AS other_id
      FROM person o
      JOIN ahavah_match m ON m.user_a_id = LEAST(%(me)s, o.id)
                         AND m.user_b_id = GREATEST(%(me)s, o.id)
     WHERE o.uuid = uuid_or_null(%(uuid)s::text)
       AND o.activated
       AND NOT is_blocked_pair(%(me)s, o.id)
"""

# One question per match, chosen once: a live question neither member has
# answered, otherwise any live one (spec, Data).
_Q_ASSIGN = f"""
    INSERT INTO match_question (match_id, prompt_key)
    SELECT %(m)s::uuid, b.key
      FROM prompt_bank b
     WHERE {LIVE}
     ORDER BY EXISTS (SELECT 1 FROM prompt_answer a
                       WHERE a.prompt_key = b.key AND a.person_id IN (%(a)s, %(b)s)),
              b.sort, b.key
     LIMIT 1
    ON CONFLICT (match_id) DO NOTHING
"""

_Q_MATCH_QUESTION = f"""
    SELECT b.key, b.text, b.format, b.options
      FROM match_question mq
      JOIN prompt_bank b ON b.key = mq.prompt_key AND {LIVE}
     WHERE mq.match_id = %(m)s::uuid
"""


def ensure_match_question(tx, match_id: str, a_id: int, b_id: int) -> Optional[dict]:
    tx.execute(_Q_ASSIGN, dict(m=match_id, a=a_id, b=b_id))
    row = tx.execute(_Q_MATCH_QUESTION, dict(m=match_id)).fetchone()
    return question_json(row) if row else None


def conversation_context(tx, person_id: int, other_uuid: str) -> Optional[dict]:
    """None when the two are not matched (or the other member is
    deactivated or blocked). Their answer stays hidden until the member has
    answered."""
    m = tx.execute(_Q_MATCH, dict(me=person_id, uuid=other_uuid)).fetchone()
    if m is None:
        return None
    question = ensure_match_question(tx, m['match_id'], m['user_a_id'], m['user_b_id'])
    if question is None:
        return dict(match_question=None)
    mine = choice_of(tx, person_id, question['key'])
    theirs = choice_of(tx, m['other_id'], question['key'])
    return dict(match_question=dict(
        question=question, mine=mine, they_answered=theirs is not None,
        theirs=theirs if mine is not None else None))
```

Append to `service/api/questions_routes.py`:

```python
@aget('/conversation-context/<prospect_uuid>')
def get_conversation_context(s: t.SessionInfo, prospect_uuid: str):
    """The chat block of a match (spec, API): the match question, whether
    the other member has answered and both answers once both have."""
    if s.person_id is None:
        return 'Not signed in', 401
    from service.questions.member import conversation_context
    with api_tx() as tx:
        ctx = conversation_context(tx, s.person_id, prospect_uuid)
    return ctx if ctx is not None else ('', 404)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_conversation_context.py -q -p no:warnings`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/member.py service/api/questions_routes.py tests/test_conversation_context.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): one shared question for a new match, answer first to see theirs" -m "Refs: TEC-1845"
```

---

### Task 6: The push setting, the device's time zone and push taps

**Files:**
- Modify: `service/notifications/__init__.py` (`EventKind`, `_EVENT_COLUMN`, `_EVENT_DEFAULTS`, `_EMAIL_COLUMN`, `_EMAIL_DEFAULTS`, `post_subscribe`, `get_notification_preferences`, `patch_notification_preferences`)
- Modify: `duotypes/__init__.py` (`PostNotificationsSubscribe`, `PatchNotificationPreferences`, a new `PostPushTap`)
- Modify: `service/api/questions_routes.py` (append)
- Test: `tests/test_question_notification_prefs.py` (create)

**Interfaces:**
- Consumes: Task 1's columns and `push_tap`.
- Produces: event kind `'questions'` gated by `push_questions` (default TRUE, never emailed); `service.notifications.clean_tz(value) -> Optional[str]`; `POST /notifications/subscribe` accepts optional `tz`; `GET /notifications/preferences` returns `push_questions`; a PATCH carrying `push_questions: false` stamps `push_questions_off_at` (first stamp kept), `true` clears it; `POST /push-taps` body `{src: 'qpush' | 'mpush' | 'lpush'}` (204, one row per member and source per 10 minutes).

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_notification_prefs.py`:

```python
"""The quick questions push setting, the time zone and push taps (TEC-1845).

`questions` is a push-only event kind, on by default (owner decision of
16 Oct). Turning it off is stamped so switch-offs can be counted by week
(the guard rail). A subscription keeps its device's time zone for 18:00
local pushes; anything the server cannot read is stored as none. A landing
from a question push writes one push_tap, however often the page reloads.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from database import api_tx

pytestmark = pytest.mark.usefixtures('questions_schema')


def _member(make_person, sign_in, name):
    p = make_person(name=name)
    return dict(p, headers=sign_in(p))


def _pref(pid):
    with api_tx('read committed') as tx:
        return tx.execute('SELECT push_questions, push_questions_off_at FROM notification_preference '
                          'WHERE person_id = %(p)s', dict(p=pid)).fetchone()


def _subscribe(client, headers, endpoint, **extra):
    return client.post('/notifications/subscribe', headers=headers, json=dict(
        endpoint=endpoint, keys=dict(p256dh='k', auth='a'), **extra))


def _tz(pid):
    with api_tx('read committed') as tx:
        return [r['tz'] for r in tx.execute('SELECT tz FROM push_subscription WHERE person_id = %(p)s',
                                            dict(p=pid)).fetchall()]


def test_quick_question_pushes_are_on_by_default(client, make_person, sign_in):
    from service.notifications import _allowed_for_event
    me = _member(make_person, sign_in, 'PrefDefault')
    assert client.get('/notifications/preferences', headers=me['headers']).get_json()['push_questions'] is True
    assert _allowed_for_event(me['id'], 'questions') is True


def test_turning_it_off_is_stamped_and_turning_it_on_clears_it(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'PrefOff')
    assert client.patch('/notifications/preferences', headers=me['headers'],
                        json=dict(push_questions=False)).status_code == 204
    first = _pref(me['id'])
    assert first['push_questions'] is False and first['push_questions_off_at'] is not None
    client.patch('/notifications/preferences', headers=me['headers'], json=dict(push_questions=False))
    assert _pref(me['id'])['push_questions_off_at'] == first['push_questions_off_at']
    client.patch('/notifications/preferences', headers=me['headers'], json=dict(push_questions=True))
    assert _pref(me['id']) == dict(push_questions=True, push_questions_off_at=None)


def test_quick_questions_are_never_emailed():
    from service.campaigns import _Q_UNSUBSCRIBED
    from service.notifications import _EMAIL_COLUMN, _EMAIL_DEFAULTS
    assert _EMAIL_COLUMN['questions'] == 'push_questions'
    assert _EMAIL_DEFAULTS['questions'] is False
    assert 'push_questions' not in _Q_UNSUBSCRIBED['notifications']


def test_a_subscription_keeps_its_devices_time_zone(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TzKeep')
    endpoint = f'https://push.example.com/{uuid4()}'
    assert _subscribe(client, me['headers'], endpoint, tz='America/Chicago').status_code == 200
    _subscribe(client, me['headers'], endpoint)
    assert _tz(me['id']) == ['America/Chicago']


def test_a_bad_or_missing_time_zone_is_stored_as_none(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TzBad')
    for tz in ('Mars/Olympus_Mons', 'x' * 200, '', None):
        r = _subscribe(client, me['headers'], f'https://push.example.com/{uuid4()}', tz=tz)
        assert r.status_code == 200, tz
    assert _tz(me['id']) == [None, None, None, None]


def test_a_push_tap_is_recorded_once_per_10_minutes(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'Tapper')
    for src in ('qpush', 'qpush', 'lpush'):
        assert client.post('/push-taps', headers=me['headers'], json=dict(src=src)).status_code == 204
    with api_tx('read committed') as tx:
        rows = tx.execute('SELECT src FROM push_tap WHERE person_id = %(p)s ORDER BY id',
                          dict(p=me['id'])).fetchall()
    assert [r['src'] for r in rows] == ['qpush', 'lpush']


def test_an_unknown_source_is_refused(client, make_person, sign_in):
    me = _member(make_person, sign_in, 'TapBad')
    assert client.post('/push-taps', headers=me['headers'], json=dict(src='email')).status_code == 400


def test_a_signed_out_tap_is_refused(client):
    assert client.post('/push-taps', json=dict(src='qpush')).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_notification_prefs.py -q -p no:warnings`
Expected: failures with `KeyError: 'push_questions'` and `KeyError: 'questions'`; the time zone tests fail on `[None]` versus `['America/Chicago']`; the tap tests fail with 404 or 405.

- [ ] **Step 3: Write the implementation**

In `service/notifications/__init__.py`:

Replace the `EventKind` definition with:

```python
EventKind = Literal[
    "match", "message", "like", "weekly", "verification", "profile_view", "questions"
]
```

Add `"questions": "push_questions",` as the last entry of `_EVENT_COLUMN` and `"questions": True,` as the last entry of `_EVENT_DEFAULTS` (owner decision of 16 Oct: on by default).

In `_EMAIL_COLUMN` add, after the `"weekly"` line:

```python
    # Quick questions (TEC-1845) are push only. Like weekly, the entry
    # points at the push column and the kind is never emailed: the question
    # line in E2 belongs to that campaign and its own unsubscribe.
    "questions":    "push_questions",
```

and in `_EMAIL_DEFAULTS` add `"questions":    False,` (fails towards not emailing).

Add, after `PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)` and its `if not PUSH_ENABLED` block:

```python
def clean_tz(value) -> Optional[str]:
    """A device's IANA time zone as stored on push_subscription.tz (TEC-1845),
    or None for anything the server cannot read. Never raises: a browser
    that sends something odd still subscribes, and its pushes use the
    default zone (service/questions/pushes.py)."""
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(value)
    except Exception:
        return None
    return value
```

In `post_subscribe`, replace the INSERT statement and its parameters with:

```python
        tx.execute(
            """
            INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
            VALUES (%(person_id)s, %(endpoint)s, %(p256dh)s, %(auth)s, %(tz)s)
            ON CONFLICT (person_id, endpoint) DO UPDATE
              SET p256dh    = EXCLUDED.p256dh,
                  auth      = EXCLUDED.auth,
                  tz        = COALESCE(EXCLUDED.tz, push_subscription.tz),
                  updated_at = NOW()
            """,
            dict(
                person_id=s.person_id,
                endpoint=req.endpoint,
                p256dh=req.keys.p256dh,
                auth=req.keys.auth,
                tz=clean_tz(getattr(req, 'tz', None)),
            ),
        )
```

In `get_notification_preferences`, add `push_questions=True,` as the last entry of `_MATRIX_DEFAULTS`.

In `patch_notification_preferences`, after the `if 'push_likes' in updates:` block, add:

```python
    # Turning quick-question pushes off is stamped, so switch-offs can be
    # counted by week (TEC-1845, the guard rail); turning them on clears it.
    # A second "off" keeps the first stamp.
    if 'push_questions' in updates:
        set_clause += (', push_questions_off_at = CASE WHEN %(push_questions)s::boolean THEN NULL '
                       'ELSE COALESCE(notification_preference.push_questions_off_at, NOW()) END')
        insert_cols += ', push_questions_off_at'
        insert_vals += ', CASE WHEN %(push_questions)s::boolean THEN NULL ELSE NOW() END'
```

In `duotypes/__init__.py`:

Add to `PostNotificationsSubscribe`, after `keys: PushSubscriptionKeys`:

```python
    # The device's IANA time zone (TEC-1845), from the web's
    # Intl.DateTimeFormat. Unbounded here on purpose: anything the server
    # cannot read is stored as None by service.notifications.clean_tz, so
    # an odd value never stops a device from subscribing.
    tz: Optional[str] = None
```

Add to `PatchNotificationPreferences`, after `email_profile_views`:

```python
    # Quick questions (TEC-1845): push only, no email column.
    push_questions: Optional[bool] = None
```

Add after `class PutAnswer`:

```python
class PostPushTap(BaseModel):
    """POST /push-taps (TEC-1845): the web app landed on a ?src= URL."""
    src: Literal['qpush', 'mpush', 'lpush']
```

`Literal`, `Dict` and `List` are already imported at the top of `duotypes/__init__.py`.

Append to `service/api/questions_routes.py`:

```python
# One row per member and source per 10 minutes, so a reload or a second
# tab does not count twice.
_Q_TAP = """
    INSERT INTO push_tap (person_id, src)
    SELECT %(p)s, %(s)s
     WHERE NOT EXISTS (SELECT 1 FROM push_tap
                        WHERE person_id = %(p)s AND src = %(s)s
                          AND tapped_at > NOW() - interval '10 minutes')
"""


@apost('/push-taps')
@validate(t.PostPushTap)
def post_push_tap(req: t.PostPushTap, s: t.SessionInfo):
    """Nothing recorded a push tap before this (spec, Notifications): the
    web reads only utm keys and sw.js only opens the URL."""
    if s.person_id is None:
        return 'Not signed in', 401
    with api_tx() as tx:
        tx.execute(_Q_TAP, dict(p=s.person_id, s=req.src))
    return '', 204
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_notification_prefs.py tests/test_like_alerts.py tests/test_notification_fallback.py tests/test_verification_pref.py -q -p no:warnings`
Expected: all pass (8 new, the three existing suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/notifications/__init__.py duotypes/__init__.py service/api/questions_routes.py tests/test_question_notification_prefs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): a push-only setting, the device time zone and push taps" -m "Refs: TEC-1845"
```

---

### Task 7: The 5 switches, passed through to the api and the cron

**Files:**
- Modify: `service/campaigns/switches.py` (`SWITCHES`)
- Modify: `docker-compose.production.yml` (the `api` and `cron` environment blocks, after `AHAVAH_SPOTLIGHT_COPY_ENABLED` in each)
- Test: `tests/test_question_switches.py` (create)

**Interfaces:**
- Consumes: `service.campaigns.switches.enabled`.
- Produces: switch names `question_push`, `match_question_push`, `e2_question_line`, `questions_launch_email`, `questions_launch_push`, each off unless its variable is `1`, `true`, `yes` or `on`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_switches.py`:

```python
"""The quick-question switches (TEC-1845, spec "Notifications" and "Launch").

Each is off unless its variable is set, and each variable is passed through
to both the api and the cron containers, defaulting to 0: without the
pass-through a switch can never be turned on. tests/test_return_mail_cron.py
already checks that every switch reads as off unless set.
"""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'question_push': 'AHAVAH_QUESTION_PUSH_ENABLED',
    'match_question_push': 'AHAVAH_MATCH_QUESTION_PUSH_ENABLED',
    'e2_question_line': 'AHAVAH_E2_QUESTION_LINE_ENABLED',
    'questions_launch_email': 'AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED',
    'questions_launch_push': 'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2, (
        f'{env} must be passed through in both the api and the cron blocks, defaulting to 0')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_switches.py -q -p no:warnings`
Expected: `6 failed`.

- [ ] **Step 3: Write the implementation**

In `service/campaigns/switches.py`, add at the end of `SWITCHES`, after the `'spotlight_copy'` entry:

```python
    # Quick questions (TEC-1845): the weekly question push and the
    # silent-match push, the question line in E2, and the launch email and
    # push. Off until the owner has seen each proof on his own device.
    'question_push': 'AHAVAH_QUESTION_PUSH_ENABLED',
    'match_question_push': 'AHAVAH_MATCH_QUESTION_PUSH_ENABLED',
    'e2_question_line': 'AHAVAH_E2_QUESTION_LINE_ENABLED',
    'questions_launch_email': 'AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED',
    'questions_launch_push': 'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED',
```

In `docker-compose.production.yml`, in the `api` service's environment, replace:

```yaml
      AHAVAH_SPOTLIGHT_COPY_ENABLED: ${AHAVAH_SPOTLIGHT_COPY_ENABLED:-0}
      # Meta Conversions API (service/metapixel.py) — no-op when blank.
```

with:

```yaml
      AHAVAH_SPOTLIGHT_COPY_ENABLED: ${AHAVAH_SPOTLIGHT_COPY_ENABLED:-0}
      # Quick questions (TEC-1845). Off until the owner confirms each proof.
      # The api needs them too: Admin > Questions shows their state and E2
      # is built here for the Send button.
      AHAVAH_QUESTION_PUSH_ENABLED: ${AHAVAH_QUESTION_PUSH_ENABLED:-0}
      AHAVAH_MATCH_QUESTION_PUSH_ENABLED: ${AHAVAH_MATCH_QUESTION_PUSH_ENABLED:-0}
      AHAVAH_E2_QUESTION_LINE_ENABLED: ${AHAVAH_E2_QUESTION_LINE_ENABLED:-0}
      AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED:-0}
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      # Meta Conversions API (service/metapixel.py) — no-op when blank.
```

The `# Meta Conversions API` comment line is existing text and keeps its punctuation. In the `cron` service's environment, replace:

```yaml
      AHAVAH_SPOTLIGHT_COPY_ENABLED: ${AHAVAH_SPOTLIGHT_COPY_ENABLED:-0}
      DUO_CRON_MAX_RANDOM_START_DELAY: ${DUO_CRON_MAX_RANDOM_START_DELAY:-15}
```

with:

```yaml
      AHAVAH_SPOTLIGHT_COPY_ENABLED: ${AHAVAH_SPOTLIGHT_COPY_ENABLED:-0}
      # Quick questions (TEC-1845): the cron sends the pushes and the launch
      # email. Off until the owner confirms each proof.
      AHAVAH_QUESTION_PUSH_ENABLED: ${AHAVAH_QUESTION_PUSH_ENABLED:-0}
      AHAVAH_MATCH_QUESTION_PUSH_ENABLED: ${AHAVAH_MATCH_QUESTION_PUSH_ENABLED:-0}
      AHAVAH_E2_QUESTION_LINE_ENABLED: ${AHAVAH_E2_QUESTION_LINE_ENABLED:-0}
      AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED:-0}
      AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED: ${AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED:-0}
      DUO_CRON_MAX_RANDOM_START_DELAY: ${DUO_CRON_MAX_RANDOM_START_DELAY:-15}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_switches.py tests/test_return_mail_cron.py -q -p no:warnings`
Expected: all pass (6 new, the return mail suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/campaigns/switches.py docker-compose.production.yml tests/test_question_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): 5 switches, off by default, passed to the api and the cron" -m "Refs: TEC-1845"
```

---

### Task 8: Question pushes count towards the 3-day gap

**Files:**
- Modify: `service/campaigns/held.py` (`_GAP_CAMPAIGNS`, `nudged_recently_sql`, the module docstring's caps list)
- Test: `tests/test_question_gap.py` (create)

**Interfaces:**
- Consumes: `push_send_log` (0064); `emails.one_photo_nudge.queue_due`.
- Produces: `held._GAP_CAMPAIGNS` gains `'question'` and `'match_question'`; `held._GAP_PUSH_CAMPAIGNS = ('question', 'match_question')`; `nudged_recently_sql(person_ref)` returns a parenthesised SQL boolean that is true for a gap campaign in the outbox or a question push in `push_send_log` within `NUDGE_GAP_DAYS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_gap.py`:

```python
"""The 3-day gap counts question pushes (TEC-1845, owner decision 12).

`question` and `match_question` join the gap campaigns, and the gap reads
push_send_log for them, since a push has no outbox row. The cost the spec
names: the weekly emails that respect the gap (one_photo, profile_views,
likes_waiting) are skipped for a member who had a question push in the last
3 days. Other pushes still do not count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import one_photo_nudge
from service.campaigns import held

pytestmark = pytest.mark.usefixtures('questions_schema')

TUESDAY = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)


def _push(pid, campaign, days_ago):
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, %(c)s, %(cid)s, NOW() - make_interval(days => %(d)s))""",
                   dict(p=pid, c=campaign, cid=f'gap-{uuid4().hex[:8]}', d=days_ago))


def _gap(pid) -> bool:
    with api_tx('read committed') as tx:
        return tx.execute(f"SELECT {held.nudged_recently_sql('%(p)s')} AS g", dict(p=pid)).fetchone()['g']


def test_a_question_push_in_the_last_3_days_counts(make_person):
    p = make_person(name='GapQuestion')
    _push(p['id'], 'question', 2)
    assert _gap(p['id']) is True


def test_a_silent_match_push_counts_too(make_person):
    p = make_person(name='GapMatch')
    _push(p['id'], 'match_question', 1)
    assert _gap(p['id']) is True


def test_an_older_question_push_does_not_count(make_person):
    p = make_person(name='GapOld')
    _push(p['id'], 'question', 4)
    assert _gap(p['id']) is False


def test_other_pushes_still_do_not_count(make_person):
    p = make_person(name='GapOther')
    _push(p['id'], 'match_reminder', 1)
    assert _gap(p['id']) is False


def test_the_tuesday_photo_email_waits_after_a_question_push(make_person, add_photo, monkeypatch):
    monkeypatch.setenv('AHAVAH_ONE_PHOTO_NUDGE_ENABLED', '1')
    pushed = make_person(name='GapPhotoA', email=f'gap-a-{uuid4().hex[:8]}@ahavah-test.invalid')
    quiet = make_person(name='GapPhotoB', email=f'gap-b-{uuid4().hex[:8]}@ahavah-test.invalid')
    for p in (pushed, quiet):
        add_photo(p['id'], position=1)
    _push(pushed['id'], 'question', 2)
    with api_tx() as tx:
        one_photo_nudge.queue_due(tx, TUESDAY)
    with api_tx('read committed') as tx:
        queued = {r['person_id'] for r in tx.execute(
            "SELECT person_id FROM email_outbox WHERE campaign = 'one_photo' AND person_id = ANY(%(i)s)",
            dict(i=[pushed['id'], quiet['id']])).fetchall()}
    assert queued == {quiet['id']}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_gap.py -q -p no:warnings`
Expected: `test_a_question_push_in_the_last_3_days_counts`, `test_a_silent_match_push_counts_too` and `test_the_tuesday_photo_email_waits_after_a_question_push` fail; the other 2 pass.

- [ ] **Step 3: Write the implementation**

In `service/campaigns/held.py`, in the module docstring, replace:

```python
  likes_waiting, one_photo, profile_views   once per ISO week at most (the
      weekly id), plus their own longer rule where one is stated, and never
      within NUDGE_GAP_DAYS of another of these three or a reminder
```

with:

```python
  likes_waiting, one_photo, profile_views   once per ISO week at most (the
      weekly id), plus their own longer rule where one is stated, and never
      within NUDGE_GAP_DAYS of another of these three, a reminder or a
      quick-question push (TEC-1845, owner decision 12 of 16 Oct 2026)
```

Replace:

```python
# The campaigns that count for the gap.
_GAP_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                  'match_reminder', 'message_reminder')
```

with:

```python
# The campaigns that count for the gap. The quick-question pushes count
# too (TEC-1845): they have no outbox row, so the gap reads their send log.
# The cost, accepted by the owner: one_photo (Tuesday) and profile_views
# (Wednesday) are skipped in a week the member had a question push.
_GAP_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                  'match_reminder', 'message_reminder', 'question', 'match_question')
_GAP_PUSH_CAMPAIGNS = ('question', 'match_question')
```

Replace the body of `nudged_recently_sql`:

```python
    names = ', '.join(f"'{c}'" for c in _GAP_CAMPAIGNS)
    return f"""EXISTS (SELECT 1 FROM email_outbox o
                WHERE o.person_id = {person_ref} AND o.campaign IN ({names})
                  AND o.state IN ('queued', 'reserved', 'accepted', 'acceptance_unknown')
                  AND o.created_at > NOW() - make_interval(days => {NUDGE_GAP_DAYS}))"""
```

with:

```python
    names = ', '.join(f"'{c}'" for c in _GAP_CAMPAIGNS)
    pushes = ', '.join(f"'{c}'" for c in _GAP_PUSH_CAMPAIGNS)
    return f"""(EXISTS (SELECT 1 FROM email_outbox o
                 WHERE o.person_id = {person_ref} AND o.campaign IN ({names})
                   AND o.state IN ('queued', 'reserved', 'accepted', 'acceptance_unknown')
                   AND o.created_at > NOW() - make_interval(days => {NUDGE_GAP_DAYS}))
             OR EXISTS (SELECT 1 FROM push_send_log l
                 WHERE l.person_id = {person_ref} AND l.campaign IN ({pushes})
                   AND l.sent_at > NOW() - make_interval(days => {NUDGE_GAP_DAYS})))"""
```

Add to the docstring of `nudged_recently_sql`, after its last sentence: `A quick-question push counts from its push_send_log row.`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_gap.py tests/test_one_photo_nudge.py tests/test_likes_waiting_weekly.py tests/test_profile_views_weekly.py tests/test_reminders.py -q -p no:warnings`
Expected: all pass (5 new, the four existing suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/campaigns/held.py tests/test_question_gap.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): question pushes count towards the 3-day gap" -m "Refs: TEC-1845"
```

---

### Task 9: The silent-match push and the weekly question push

**Files:**
- Create: `service/questions/copy.py`, `service/questions/pushes.py`
- Modify: `service/cron/returnmail/__init__.py` (import and `JOBS`)
- Modify: `tests/conftest.py` (append `push_member` and `pushed_questions`)
- Test: `tests/test_question_pushes.py` (create)

**Interfaces:**
- Consumes: `current_drop`, `week_starts_at`, `resting` (Task 3); `ensure_match_question` (Task 5); the `questions` event kind (Task 6); the switches (Task 7); the gap (Task 8); `held.after_commit`; `send_to_user_safe(person_id, title, body, url, tag, *, event_kind)`.
- Produces, in `service.questions.copy`: `LOCK_SCREEN_CHARS = 110`, `SAMPLE_QUESTION`, `in_sentence(label) -> str`, `short_question(question) -> str`, `weekly_push(live_on: str, question) -> dict(title, body, url, tag)`, `launch_push(live_on: str, question) -> dict`, `match_question_push(other_uuid, match_id) -> dict`, `e2_line(question) -> str`, `PUSH_PROOFS: list[dict]` (each with `kind`). In `service.questions.pushes`: `QUESTION = 'question'`, `MATCH_QUESTION = 'match_question'`, `LAUNCH = 'questions_launch'`, `LAUNCH_ID = 'launch'`, `PUSH_READY() -> bool`, `_push(person_id, title, body, url, tag)`, `zone(tz) -> ZoneInfo`, `quiet(local) -> bool`, `queue_match_question_pushes(tx, now) -> int`, `queue_weekly_question_pushes(tx, now) -> int` and the shared helpers `_audience`, `_member_cols`, `_week`, `_pushed_this_week`, `_deliver`, `_evening` that Task 10 uses. `returnmail.JOBS` gains `('match_question_push', ...)` before `('question_push', ...)`. Fixtures: `push_member(name, *, tz='UTC', gender='Woman', online_days_ago=1, push=True) -> person row`, `pushed_questions -> list[dict(person_id, title, body, url, tag)]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def push_member(make_person):
    """A mailable member with one push subscription in time zone `tz`,
    last online `online_days_ago` days ago."""
    from uuid import uuid4

    from database import api_tx

    def _make(name: str, *, tz: str | None = 'UTC', gender: str = 'Woman',
              online_days_ago: int = 1, push: bool = True) -> dict:
        p = make_person(name=name, gender=gender,
                        email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
        with api_tx() as tx:
            tx.execute("UPDATE person SET last_online_time = NOW() - make_interval(days => %(d)s) "
                       "WHERE id = %(i)s", dict(d=online_days_ago, i=p['id']))
            if push:
                tx.execute(
                    """INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                       VALUES (%(i)s, %(e)s, 'k', 'a', %(tz)s)""",
                    dict(i=p['id'], e=f'https://push.test/{uuid4()}', tz=tz))
        return p

    return _make


@pytest.fixture
def pushed_questions(monkeypatch):
    """Every quick-question push, captured instead of sent."""
    from service.questions import pushes as qp

    sent: list[dict] = []
    monkeypatch.setattr(qp, '_push', lambda person_id, title, body, url, tag: sent.append(
        dict(person_id=person_id, title=title, body=body, url=url, tag=tag)))
    monkeypatch.setattr(qp, 'PUSH_READY', lambda: True)
    return sent
```

Create `tests/test_question_pushes.py`:

```python
"""The silent-match push and the weekly question push (TEC-1845, spec
"Notifications").

Both share 1 push per member per question week; the silent-match push runs
first and wins. Weekly: 18:00 to 21:00 the member's local time on the drop
day, to members active in 60 days who have not answered, held by the gap.
Silent match: from 24 hours after a match with no message, once per match,
to both members, outside quiet hours, not held by the gap. Neither goes in
a rest period, to anyone who left campaign emails, to staff or after 2
pushes with no visit.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from emails import reminders as rm
from service.campaigns import held
from service.questions import copy
from service.questions import pushes as qp
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_QUESTION_PUSH_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_MATCH_QUESTION_PUSH_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    """This week's question goes live today (Barbados date)."""
    q = make_question(labels=('Mountains', 'The sea'))
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _at(day, hour, minute=30, tz='UTC') -> datetime:
    return datetime.combine(day, time(hour, minute), ZoneInfo(tz)).astimezone(UTC)


def _run(job, now) -> None:
    with api_tx() as tx:
        job(tx, now)
    held.run_after_commit()


def _to(sent, person) -> list[dict]:
    return [p for p in sent if p['person_id'] == person['id']]


def _match(a, b, hours_ago) -> str:
    lo, hi = sorted((a['id'], b['id']))
    with api_tx() as tx:
        return str(tx.execute(
            """INSERT INTO ahavah_match (user_a_id, user_b_id, created_at)
               VALUES (%(a)s, %(b)s, NOW() - make_interval(hours => %(h)s)) RETURNING match_id""",
            dict(a=lo, b=hi, h=hours_ago)).fetchone()['match_id'])


def _sql(query, **params) -> None:
    with api_tx() as tx:
        tx.execute(query, params)


def _likes_waiting_queued_now(person) -> None:
    _sql("""INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload, unsub_scope)
            SELECT 'likes_waiting', 'gap-test', id, email, '{}'::jsonb, 'campaigns'
              FROM person WHERE id = %(p)s""", p=person['id'])


def test_nothing_goes_while_the_switches_are_off(push_member, pushed_questions, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTION_PUSH_ENABLED', raising=False)
    monkeypatch.delenv('AHAVAH_MATCH_QUESTION_PUSH_ENABLED', raising=False)
    a, b = push_member('OffA'), push_member('OffB')
    _match(a, b, 25)
    _run(qp.queue_match_question_pushes, _at(week['today'], 18))
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, a) == _to(pushed_questions, b) == []


def test_the_weekly_question_goes_at_18_local_on_the_drop_day(push_member, pushed_questions, week, on):
    m = push_member('Weekly')
    live_on = week['today'].isoformat()
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == [dict(
        person_id=m['id'], title="This week's question",
        body='Mountains or the sea? One tap, then see who picked the same.',
        url='/discover?src=qpush', tag=f'question:{live_on}')]
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = 'question' "
                          "AND campaign_id = %(w)s", dict(p=m['id'], w=live_on)).fetchone()
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 19))
    assert len(_to(pushed_questions, m)) == 1


def test_not_before_18_or_from_21_or_on_another_day(push_member, pushed_questions, week, on):
    m = push_member('Window')
    for now in (_at(week['today'], 17), _at(week['today'], 21),
                _at(week['today'] + timedelta(days=1), 18)):
        _run(qp.queue_weekly_question_pushes, now)
    assert _to(pushed_questions, m) == []


def test_the_members_own_time_zone_sets_the_hour(push_member, pushed_questions, week, on):
    m = push_member('Chicago', tz='America/Chicago')
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == [], '18:30 UTC is the early afternoon in Chicago'
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18, tz='America/Chicago'))
    assert len(_to(pushed_questions, m)) == 1


def test_a_member_with_no_time_zone_is_pushed_at_18_eastern(push_member, pushed_questions, week, on):
    m = push_member('NoZone', tz=None)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18, tz='America/New_York'))
    assert len(_to(pushed_questions, m)) == 1


def test_who_is_left_out(push_member, pushed_questions, week, on):
    control = push_member('Control')
    answered, away, off = push_member('Answered'), push_member('Away', online_days_ago=61), push_member('Off')
    left, nosub, staff = push_member('Left'), push_member('NoSub', push=False), push_member('Staff')
    q = week['question']
    _sql("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
         p=answered['id'], k=q['key'], c=q['options'][0]['key'])
    _sql('INSERT INTO notification_preference (person_id, push_questions) VALUES (%(p)s, FALSE)', p=off['id'])
    _sql('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', p=left['id'])
    _sql("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(p)s", p=staff['id'])
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    got = {p['person_id'] for p in pushed_questions}
    assert control['id'] in got
    assert not got & {answered['id'], away['id'], off['id'], left['id'], nosub['id'], staff['id']}


def test_nothing_goes_in_a_rest_period(push_member, pushed_questions, week, on, monkeypatch):
    a, b = push_member('RestA'), push_member('RestB')
    _match(a, b, 25)
    monkeypatch.setattr(rd, 'REST_DAYS', (week['today'],))
    _run(qp.queue_match_question_pushes, _at(week['today'], 18))
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, a) == _to(pushed_questions, b) == []


def test_the_gap_holds_the_weekly_push(push_member, pushed_questions, week, on):
    m = push_member('Gap')
    _likes_waiting_queued_now(m)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []


def test_pushes_stop_after_2_with_no_visit(push_member, pushed_questions, week, on):
    m = push_member('Unvisited', online_days_ago=10)
    for days, cid in ((8, '2000-01-02'), (6, '2000-01-09')):
        _sql("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                VALUES (%(p)s, 'question', %(c)s, NOW() - make_interval(days => %(d)s))""",
             p=m['id'], c=cid, d=days)
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 18))
    assert _to(pushed_questions, m) == []
    _sql('UPDATE person SET last_online_time = NOW() WHERE id = %(p)s', p=m['id'])
    _run(qp.queue_weekly_question_pushes, _at(week['today'], 19))
    assert len(_to(pushed_questions, m)) == 1


def test_a_silent_match_gets_one_push_each_after_24_hours(push_member, pushed_questions, on):
    a, b = push_member('SilentA', gender='Man'), push_member('SilentB')
    mid = _match(a, b, 25)
    now = _at(barbados_today(), 12)
    _run(qp.queue_match_question_pushes, now)
    assert _to(pushed_questions, a) == [dict(
        person_id=a['id'], title='An easy first line',
        body='Your new match has a question waiting. Answer first, then see theirs.',
        url=f"/chat/{b['uuid']}?src=mpush", tag=f'match:{mid}')]
    assert [p['url'] for p in _to(pushed_questions, b)] == [f"/chat/{a['uuid']}?src=mpush"]
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT 1 FROM match_question WHERE match_id = %(m)s::uuid', dict(m=mid)).fetchone()
    _run(qp.queue_match_question_pushes, now + timedelta(hours=1))
    assert len(_to(pushed_questions, a)) == 1


def test_not_before_24_hours_or_once_anyone_has_written(push_member, pushed_questions, on):
    a, b = push_member('EarlyA'), push_member('EarlyB')
    _match(a, b, 23)
    c, d = push_member('WroteC'), push_member('WroteD')
    _match(c, d, 25)
    _sql('INSERT INTO messaged (subject_person_id, object_person_id) VALUES (%(s)s, %(o)s)', s=d['id'], o=c['id'])
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert not [p for p in pushed_questions if p['person_id'] in {a['id'], b['id'], c['id'], d['id']}]


def test_a_silent_match_push_waits_out_quiet_hours(push_member, pushed_questions, on):
    a, b = push_member('QuietA'), push_member('QuietB')
    _match(a, b, 30)
    day = barbados_today()
    _run(qp.queue_match_question_pushes, _at(day, 22))
    _run(qp.queue_match_question_pushes, _at(day + timedelta(days=1), 7))
    assert _to(pushed_questions, a) == []
    _run(qp.queue_match_question_pushes, _at(day + timedelta(days=1), 8))
    assert len(_to(pushed_questions, a)) == 1


def test_the_silent_match_push_comes_first_and_spends_the_week(push_member, pushed_questions, week, on):
    from service.cron import returnmail
    a, b = push_member('FirstA'), push_member('FirstB')
    _match(a, b, 25)
    now = _at(week['today'], 18)
    _run(qp.queue_match_question_pushes, now)
    _run(qp.queue_weekly_question_pushes, now)
    assert [p['title'] for p in _to(pushed_questions, a)] == ['An easy first line']
    names = [name for name, _ in returnmail.JOBS]
    assert names.index('match_question_push') < names.index('question_push')


def test_the_silent_match_push_is_not_held_by_the_gap(push_member, pushed_questions, on):
    a, b = push_member('UnheldA'), push_member('UnheldB')
    _match(a, b, 25)
    _likes_waiting_queued_now(a)
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert len(_to(pushed_questions, a)) == 1


def test_no_silent_match_push_when_the_other_member_is_deactivated(push_member, pushed_questions, on):
    a, b = push_member('GoneA'), push_member('GoneB')
    _match(a, b, 25)
    _sql('UPDATE person SET activated = FALSE WHERE id = %(p)s', p=b['id'])
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    assert _to(pushed_questions, a) == []


def test_a_match_gets_the_question_push_and_the_3_day_reminder(push_member, pushed_questions, on, monkeypatch):
    # The spec lets both go: they say different things.
    monkeypatch.setenv('AHAVAH_MATCH_REMINDER_ENABLED', '1')
    reminded: list[int] = []
    monkeypatch.setattr(rm, '_push', lambda person_id, title, body, url, kind: reminded.append(person_id))
    monkeypatch.setattr(rm, 'PUSH_READY', lambda: True)
    a, b = push_member('BothA', online_days_ago=2), push_member('BothB', online_days_ago=2)
    _match(a, b, 73)
    tuesday = datetime(2026, 10, 13, 13, tzinfo=UTC)
    _run(qp.queue_match_question_pushes, tuesday)
    _run(rm.queue_match_reminders, tuesday)
    assert len(_to(pushed_questions, a)) == 1 and a['id'] in reminded


def test_a_push_that_fails_is_tried_again(push_member, on, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('push service down')
    monkeypatch.setattr(qp, '_push', boom)
    monkeypatch.setattr(qp, 'PUSH_READY', lambda: True)
    a, b = push_member('FlakyA'), push_member('FlakyB')
    _match(a, b, 25)
    _run(qp.queue_match_question_pushes, _at(barbados_today(), 12))
    with api_tx('read committed') as tx:
        assert tx.execute("SELECT 1 FROM push_send_log WHERE person_id = %(p)s AND campaign = 'match_question'",
                          dict(p=a['id'])).fetchone() is None


def test_every_push_fits_a_lock_screen():
    with api_tx('read committed') as tx:
        rows = tx.execute("""SELECT key, text, format, options FROM prompt_bank
                              WHERE active AND format IN ('either_or', 'pick_one')""").fetchall()
    assert rows
    for r in rows:
        for push in (copy.weekly_push('2026-11-15', dict(r)), copy.launch_push('2026-11-15', dict(r))):
            assert len(push['body']) <= copy.LOCK_SCREEN_CHARS, push['body']
    assert len(copy.MATCH_BODY) <= copy.LOCK_SCREEN_CHARS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_pushes.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'copy' from 'service.questions'`.

- [ ] **Step 3: Write the implementation**

Create `service/questions/copy.py`:

```python
"""What the quick-question pushes and the E2 line say (TEC-1845).

Draft copy from the spec. It goes through the ux-writing pass and the
owner's proofs (scripts/send_question_proofs.py) before any switch goes on.
Nothing here names a person or carries an answer: a lock screen shows it.
Each body stays within LOCK_SCREEN_CHARS. Owner decision 1 drops the
question on the first free day of the week, so no line names Sunday.
"""
from __future__ import annotations

LOCK_SCREEN_CHARS = 110

WEEKLY_TITLE = "This week's question"
# The spec asks the ux-writing pass to check "see who picked the same": the
# card shows counts, not people.
WEEKLY_TAIL = 'One tap, then see who picked the same.'
MATCH_TITLE = 'An easy first line'
MATCH_BODY = 'Your new match has a question waiting. Answer first, then see theirs.'
LAUNCH_TITLE = 'New on Ahavah: quick questions'
LAUNCH_TAIL = 'Answer with one tap.'

# Week 1 of the approved order, for proofs and previews: nothing per member.
SAMPLE_QUESTION = dict(
    key='mountains-or-sea', text='Would you rather wake up to mountains or the sea?',
    format='either_or',
    options=[dict(key='mountains', label='Mountains'), dict(key='sea', label='The sea')])


def in_sentence(label: str) -> str:
    """Options are written to read inside a sentence once their first
    letter is lower-cased (spec, The launch question set)."""
    return label[:1].lower() + label[1:]


def short_question(question: dict) -> str:
    """'Mountains or the sea?' or 'Coffee, tea or something else?'."""
    labels = [o['label'] for o in question['options']]
    parts = [labels[0], *(in_sentence(label) for label in labels[1:])]
    return f"{', '.join(parts[:-1])} or {parts[-1]}?"


def weekly_push(live_on: str, question: dict) -> dict:
    return dict(title=WEEKLY_TITLE, body=f'{short_question(question)} {WEEKLY_TAIL}',
                url='/discover?src=qpush', tag=f'question:{live_on}')


def launch_push(live_on: str, question: dict) -> dict:
    return dict(title=LAUNCH_TITLE, body=f'{short_question(question)} {LAUNCH_TAIL}',
                url='/discover?src=lpush', tag=f'question:{live_on}')


def match_question_push(other_uuid: str, match_id: str) -> dict:
    """Reuses the match's own tag, so it replaces the match notification."""
    return dict(title=MATCH_TITLE, body=MATCH_BODY,
                url=f'/chat/{other_uuid}?src=mpush', tag=f'match:{match_id}')


def e2_line(question: dict) -> str:
    return f"This week's question: {in_sentence(short_question(question))} Answer in the app."


# What scripts/send_question_proofs.py pushes to the owner's account: the
# real wording, with links that record no tap and open nobody's chat. The
# weekly and launch proofs share one tag, so a device that replaces by tag
# shows only the launch proof once both arrive.
PUSH_PROOFS = [
    dict(weekly_push('proof', SAMPLE_QUESTION), url='/discover', kind='question'),
    dict(match_question_push('proof', 'proof'), url='/inbox', kind='match_question'),
    dict(launch_push('proof', SAMPLE_QUESTION), url='/discover', kind='questions_launch'),
]
```

Create `service/questions/pushes.py`:

```python
"""The quick-question pushes (TEC-1845, spec "Notifications").

  match_question  from 24 hours after a match in which nobody has written,
                  once per match, to both members (owner decision 3). Not
                  held by the gap: it goes once and a hold would lose it.
  question        this week's question, 18:00 to 21:00 the member's local
                  time on the drop day, to members active in the last 60
                  days who have not answered it. Held by the gap.
  launch          the launch week's question push (queue_launch_pushes).

They share 1 push per member per question week (from 00:00 Barbados on the
current drop's live_on). The cron runs match_question first, so when both
are due the silent match wins and no weekly push follows that week.

Every push: only to a member with push_questions on (default on) and a
subscription; never to one who left campaign emails, to staff, to a test or
suppressed address; never in quiet hours (21:00 to 08:00 local, from
push_subscription.tz, US Eastern when missing); never in a rest period or
past the known calendar (schedule.resting); never after 2 question pushes
with no visit since. send_to_user_safe only, never notify(), which would
fall back to email. Each is logged in push_send_log in the job's
transaction and sent after it commits (held.after_commit); one that fails
gives its log rows back, to be tried next tick.

Held: nothing goes unless its switch is on (service/campaigns/switches.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from emails.base import suppressed_sql_pattern
from service.admin.queries.members import member_sql
from service.campaigns import held, suppressed_predicate_sql, unsubscribed_predicate_sql
from service.campaigns.switches import enabled
from service.growth.queries import _excluded
from service.questions import copy
from service.questions.member import ensure_match_question
from service.questions.schedule import current_drop, resting, week_starts_at

QUESTION = 'question'
MATCH_QUESTION = 'match_question'
LAUNCH = 'questions_launch'
LAUNCH_ID = 'launch'

DEFAULT_TZ = ZoneInfo('America/New_York')
QUIET_FROM, QUIET_UNTIL = 21, 8
EVENING = 18
ACTIVE_DAYS = 60
MAX_UNVISITED = 2


def PUSH_READY() -> bool:
    from service.notifications import PUSH_ENABLED
    return PUSH_ENABLED


def _push(person_id: int, title: str, body: str, url: str, tag: str) -> None:
    from service.notifications import send_to_user_safe
    send_to_user_safe(person_id, title, body, url, tag, event_kind='questions')


def zone(tz: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz) if tz else DEFAULT_TZ
    except Exception:
        return DEFAULT_TZ


def quiet(local: datetime) -> bool:
    return local.hour >= QUIET_FROM or local.hour < QUIET_UNTIL


def _evening(drop: dict, local: datetime) -> bool:
    return local.date() == drop['live_on'] and EVENING <= local.hour < QUIET_FROM


def _audience(alias: str = 'p') -> str:
    return f"""{alias}.activated AND {alias}.deletion_requested_at IS NULL
       AND {member_sql(alias)}
       AND lower({alias}.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql('campaigns', f'{alias}.id')})
       AND NOT ({suppressed_predicate_sql(f'{alias}.email')})
       AND COALESCE((SELECT np.push_questions FROM notification_preference np
                      WHERE np.person_id = {alias}.id), TRUE)
       AND EXISTS (SELECT 1 FROM push_subscription ps WHERE ps.person_id = {alias}.id)"""


def _member_cols(alias: str = 'p') -> str:
    """The member's id, newest known time zone and how many question
    pushes have gone since their last visit."""
    return f"""{alias}.id AS person_id,
       (SELECT ps.tz FROM push_subscription ps
         WHERE ps.person_id = {alias}.id AND ps.tz IS NOT NULL
         ORDER BY ps.updated_at DESC LIMIT 1) AS tz,
       (SELECT count(*) FROM push_send_log l
         WHERE l.person_id = {alias}.id
           AND l.campaign IN ('{QUESTION}', '{MATCH_QUESTION}')
           AND l.sent_at > COALESCE({alias}.last_online_time, '-infinity'::timestamptz)) AS unvisited"""


_Q_PUSHED_THIS_WEEK = f"""
    SELECT 1 FROM push_send_log l
     WHERE l.person_id = %(p)s
       AND ((l.campaign = '{QUESTION}' AND l.campaign_id = %(week)s)
            OR (l.campaign = '{MATCH_QUESTION}' AND l.sent_at >= %(since)s))
     LIMIT 1
"""


def _week(drop: Optional[dict], now: datetime) -> tuple[str, datetime]:
    """(the week's key, when the week began). Before the first drop there is
    no week key, and the last 7 days stand in for the week."""
    if drop is None:
        return '', now - timedelta(days=7)
    return drop['live_on'].isoformat(), week_starts_at(drop['live_on'])


def _pushed_this_week(tx, person_id: int, week: str, since: datetime) -> bool:
    return tx.execute(_Q_PUSHED_THIS_WEEK, dict(p=person_id, week=week, since=since)).fetchone() is not None


def _log(tx, campaign: str, cid: str, person_id: int) -> bool:
    return tx.execute(
        """INSERT INTO push_send_log (person_id, campaign, campaign_id)
           VALUES (%(p)s, %(c)s, %(cid)s) ON CONFLICT DO NOTHING RETURNING person_id""",
        dict(p=person_id, c=campaign, cid=cid)).fetchone() is not None


def _unlog(logs: list[tuple[str, str]], person_id: int) -> None:
    """Runs in its own transaction, from held.run_after_commit."""
    from database import api_tx
    with api_tx() as tx:
        for campaign, cid in logs:
            tx.execute("""DELETE FROM push_send_log
                           WHERE person_id = %(p)s AND campaign = %(c)s AND campaign_id = %(cid)s""",
                       dict(p=person_id, c=campaign, cid=cid))


def _deliver(tx, person_id: int, logs: list[tuple[str, str]], push: dict) -> bool:
    """Log every key, then push after the commit. Callers check every key
    first, so a key already taken here means another tick got there; that
    member is skipped."""
    for campaign, cid in logs:
        if not _log(tx, campaign, cid, person_id):
            return False
    held.after_commit(lambda: _push(person_id, push['title'], push['body'], push['url'], push['tag']),
                      on_failure=lambda: _unlog(logs, person_id))
    return True


def _params(**extra) -> dict:
    return dict(ex=_excluded(), sup=suppressed_sql_pattern(), **extra)


_Q_SILENT = f"""
    WITH m AS (
        SELECT match_id, user_a_id, user_b_id
          FROM ahavah_match
         WHERE created_at <= NOW() - make_interval(hours => 24)
           AND created_at > NOW() - make_interval(days => 7)
           AND NOT EXISTS (SELECT 1 FROM messaged x
                            WHERE (x.subject_person_id = user_a_id AND x.object_person_id = user_b_id)
                               OR (x.subject_person_id = user_b_id AND x.object_person_id = user_a_id))
           AND NOT is_blocked_pair(user_a_id, user_b_id)
    ), sides AS (
        SELECT match_id, user_a_id, user_b_id, user_a_id AS pid, user_b_id AS other FROM m
        UNION ALL
        SELECT match_id, user_a_id, user_b_id, user_b_id, user_a_id FROM m
    )
    SELECT s.match_id::text AS match_id, s.user_a_id, s.user_b_id,
           o.uuid::text AS other_uuid, {_member_cols()}
      FROM sides s
      JOIN person p ON p.id = s.pid
      JOIN person o ON o.id = s.other AND o.activated AND o.deletion_requested_at IS NULL
     WHERE {_audience()}
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{MATCH_QUESTION}'
                          AND l.campaign_id = s.match_id::text)
     ORDER BY s.match_id, p.id
"""


def queue_match_question_pushes(tx, now: datetime) -> int:
    if not enabled('match_question_push') or not PUSH_READY() or resting(now):
        return 0
    week, since = _week(current_drop(tx, now), now)
    n = 0
    for r in tx.execute(_Q_SILENT, _params()).fetchall():
        if int(r['unvisited']) >= MAX_UNVISITED or quiet(now.astimezone(zone(r['tz']))):
            continue
        if _pushed_this_week(tx, r['person_id'], week, since):
            continue
        if ensure_match_question(tx, r['match_id'], r['user_a_id'], r['user_b_id']) is None:
            continue
        if _deliver(tx, r['person_id'], [(MATCH_QUESTION, r['match_id'])],
                    copy.match_question_push(r['other_uuid'], r['match_id'])):
            n += 1
    return n


_Q_WEEKLY = f"""
    SELECT {_member_cols()}
      FROM person p
     WHERE {_audience()}
       AND p.last_online_time > NOW() - make_interval(days => {ACTIVE_DAYS})
       AND NOT EXISTS (SELECT 1 FROM prompt_answer a
                        WHERE a.person_id = p.id AND a.prompt_key = %(key)s)
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{QUESTION}'
                          AND l.campaign_id = %(week)s)
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def queue_weekly_question_pushes(tx, now: datetime) -> int:
    if not enabled('question_push') or not PUSH_READY() or resting(now):
        return 0
    drop = current_drop(tx, now)
    if drop is None:
        return 0
    week, since = _week(drop, now)
    push = copy.weekly_push(week, drop['question'])
    n = 0
    for r in tx.execute(_Q_WEEKLY, _params(key=drop['question']['key'], week=week)).fetchall():
        if int(r['unvisited']) >= MAX_UNVISITED or not _evening(drop, now.astimezone(zone(r['tz']))):
            continue
        if _pushed_this_week(tx, r['person_id'], week, since):
            continue
        if _deliver(tx, r['person_id'], [(QUESTION, week)], push):
            n += 1
    return n
```

In `service/cron/returnmail/__init__.py`, add after `from emails import likes_waiting_weekly, one_photo_nudge, profile_views_weekly, reminders`:

```python
from service.questions import pushes as question_pushes
```

and replace `JOBS`:

```python
JOBS = [
    ('likes_waiting', likes_waiting_weekly.queue_due),
    ('match_reminder', reminders.queue_match_reminders),
    ('message_reminder', reminders.queue_message_reminders),
    ('profile_views', profile_views_weekly.queue_due),
    ('one_photo', one_photo_nudge.queue_due),
]
```

with:

```python
JOBS = [
    ('likes_waiting', likes_waiting_weekly.queue_due),
    ('match_reminder', reminders.queue_match_reminders),
    ('message_reminder', reminders.queue_message_reminders),
    ('profile_views', profile_views_weekly.queue_due),
    ('one_photo', one_photo_nudge.queue_due),
    # Quick questions (TEC-1845). The silent-match push runs before the
    # weekly one: when both are due it wins and spends the week's push.
    ('match_question_push', question_pushes.queue_match_question_pushes),
    ('question_push', question_pushes.queue_weekly_question_pushes),
]
```

Add to the module docstring of `service/cron/returnmail/__init__.py`, after its first paragraph: `It also runs the quick-question pushes (service/questions/pushes.py), each behind its own switch.`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_question_pushes.py tests/test_return_mail_cron.py tests/test_reminders.py -q -p no:warnings`
Expected: all pass (18 new, the two existing suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/copy.py service/questions/pushes.py service/cron/returnmail/__init__.py tests/conftest.py tests/test_question_pushes.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the silent-match and weekly question pushes, capped and held" -m "Refs: TEC-1845"
```

---

### Task 10: The launch push

**Files:**
- Modify: `service/questions/pushes.py` (append)
- Modify: `service/cron/returnmail/__init__.py` (`JOBS`)
- Test: `tests/test_questions_launch_push.py` (create)

**Interfaces:**
- Consumes: everything Task 9 produced in `pushes`; `copy.launch_push`; the `questions_launch_push` switch.
- Produces: `service.questions.pushes.queue_launch_pushes(tx, now) -> int`; `returnmail.JOBS` gains `('questions_launch_push', ...)` between `match_question_push` and `question_push`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_questions_launch_push.py`:

```python
"""The launch push (TEC-1845, spec "Launch").

One line, once per member ever, on a drop day evening while its switch is
on: to members with a subscription and the setting on, whether or not they
have answered or been away, never to one who left campaign emails. It is
that week's question push: it spends the week's budget, so no weekly push
follows. Quiet hours, rest days, the gap and the stop after 2 all apply.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from database import api_tx
from service.campaigns import held
from service.questions import pushes as qp
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc


@pytest.fixture
def launch_on(monkeypatch):
    monkeypatch.setenv('AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED', '1')
    monkeypatch.setenv('AHAVAH_QUESTION_PUSH_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    q = make_question(labels=('Mountains', 'The sea'))
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _evening(day) -> datetime:
    return datetime.combine(day, time(18, 30), ZoneInfo('UTC')).astimezone(UTC)


def _run(job, now) -> None:
    with api_tx() as tx:
        job(tx, now)
    held.run_after_commit()


def _to(sent, person) -> list[dict]:
    return [p for p in sent if p['person_id'] == person['id']]


def _logs(person) -> set:
    with api_tx('read committed') as tx:
        return {(r['campaign'], r['campaign_id']) for r in tx.execute(
            'SELECT campaign, campaign_id FROM push_send_log WHERE person_id = %(p)s',
            dict(p=person['id'])).fetchall()}


def test_off_by_default(push_member, pushed_questions, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED', raising=False)
    m = push_member('LaunchOff')
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []


def test_the_launch_push_goes_once_on_a_drop_day_evening(push_member, pushed_questions, week, launch_on):
    m = push_member('Launch')
    live_on = week['today'].isoformat()
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == [dict(
        person_id=m['id'], title='New on Ahavah: quick questions',
        body='Mountains or the sea? Answer with one tap.',
        url='/discover?src=lpush', tag=f'question:{live_on}')]
    assert _logs(m) == {('questions_launch', 'launch'), ('question', live_on)}
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert len(_to(pushed_questions, m)) == 1


def test_the_launch_push_spends_the_weeks_budget(push_member, pushed_questions, week, launch_on):
    from service.cron import returnmail
    m = push_member('LaunchBudget')
    _run(qp.queue_launch_pushes, _evening(week['today']))
    _run(qp.queue_weekly_question_pushes, _evening(week['today']))
    assert [p['title'] for p in _to(pushed_questions, m)] == ['New on Ahavah: quick questions']
    names = [name for name, _ in returnmail.JOBS]
    assert names.index('questions_launch_push') < names.index('question_push')


def test_it_reaches_members_who_answered_or_have_been_away(push_member, pushed_questions, week, launch_on):
    answered = push_member('LaunchAnswered')
    away = push_member('LaunchAway', online_days_ago=90)
    q = week['question']
    with api_tx() as tx:
        tx.execute("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
                   dict(p=answered['id'], k=q['key'], c=q['options'][0]['key']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert len(_to(pushed_questions, answered)) == len(_to(pushed_questions, away)) == 1


def test_never_to_a_member_who_left_campaign_emails(push_member, pushed_questions, week, launch_on):
    m = push_member('LaunchLeft')
    with api_tx() as tx:
        tx.execute('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', dict(p=m['id']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []


def test_once_ever(push_member, pushed_questions, week, launch_on):
    m = push_member('LaunchTwice')
    with api_tx() as tx:
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'launch', NOW() - interval '30 days')""",
                   dict(p=m['id']))
    _run(qp.queue_launch_pushes, _evening(week['today']))
    assert _to(pushed_questions, m) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_questions_launch_push.py -q -p no:warnings`
Expected: every test fails with `AttributeError: module 'service.questions.pushes' has no attribute 'queue_launch_pushes'`.

- [ ] **Step 3: Write the implementation**

Append to `service/questions/pushes.py`:

```python
# The launch push (spec, Launch): once per member ever, on a drop day
# evening while its switch is on. Not limited to members active in 60 days
# or to those who have not answered: for a member who has been away it is a
# reason to come back. It is that week's question push, so it is logged
# under both keys: questions_launch/launch (once ever) and question/{week}
# (the week's budget, so no weekly push follows).
_Q_LAUNCH = f"""
    SELECT {_member_cols()}
      FROM person p
     WHERE {_audience()}
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{LAUNCH}'
                          AND l.campaign_id = '{LAUNCH_ID}')
       AND NOT EXISTS (SELECT 1 FROM push_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{QUESTION}'
                          AND l.campaign_id = %(week)s)
       AND NOT {held.nudged_recently_sql('p.id')}
     ORDER BY p.id
"""


def queue_launch_pushes(tx, now: datetime) -> int:
    if not enabled('questions_launch_push') or not PUSH_READY() or resting(now):
        return 0
    drop = current_drop(tx, now)
    if drop is None:
        return 0
    week, since = _week(drop, now)
    push = copy.launch_push(week, drop['question'])
    n = 0
    for r in tx.execute(_Q_LAUNCH, _params(week=week)).fetchall():
        if int(r['unvisited']) >= MAX_UNVISITED or not _evening(drop, now.astimezone(zone(r['tz']))):
            continue
        if _pushed_this_week(tx, r['person_id'], week, since):
            continue
        if _deliver(tx, r['person_id'], [(LAUNCH, LAUNCH_ID), (QUESTION, week)], push):
            n += 1
    return n
```

In `service/cron/returnmail/__init__.py`, replace:

```python
    ('match_question_push', question_pushes.queue_match_question_pushes),
    ('question_push', question_pushes.queue_weekly_question_pushes),
```

with:

```python
    ('match_question_push', question_pushes.queue_match_question_pushes),
    # The launch push before the weekly one: in launch week it is the
    # week's question push.
    ('questions_launch_push', question_pushes.queue_launch_pushes),
    ('question_push', question_pushes.queue_weekly_question_pushes),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_questions_launch_push.py tests/test_question_pushes.py -q -p no:warnings`
Expected: all pass (6 new, 18 from Task 9).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/pushes.py service/cron/returnmail/__init__.py tests/test_questions_launch_push.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the launch push, once per member, as launch week's question push" -m "Refs: TEC-1845"
```

---

### Task 11: The question line in Monday's E2

**Files:**
- Modify: `service/questions/member.py` (imports and append)
- Modify: `emails/community_weekly.py` (`community_weekly_html` and a new `_question_block`)
- Modify: `emails/send_community_weekly.py` (`_build_personal`, `build_for`, a new `preview_question_line`)
- Test: `tests/test_e2_question_line.py` (create)

**Interfaces:**
- Consumes: `current_drop`, `barbados_today` (Task 3); `copy.e2_line`, `copy.SAMPLE_QUESTION` (Task 9); the `e2_question_line` switch (Task 7).
- Produces: `service.questions.member.e2_question_line(tx, person_id: int, now: datetime) -> Optional[str]`; `community_weekly_html(..., question_line: Optional[str] = None)`; `send_community_weekly.preview_question_line(to: str) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_e2_question_line.py`:

```python
"""The question line in Monday's E2 (TEC-1845, spec "Notifications", Email).

One line naming the question that went live in the last 7 days, behind
AHAVAH_E2_QUESTION_LINE_ENABLED. Left out for a member who had the launch
email in the last 7 days, which already carried the question. With the
switch off, E2 is exactly what it was.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from database import api_tx
from emails import send_community_weekly as e2
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

LINE = "This week's question: the window seat or the aisle seat? Answer in the app."


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_QUESTION_LINE_ENABLED', '1')


@pytest.fixture
def aisle(make_question):
    return make_question(labels=('The window seat', 'The aisle seat'), text='Window seat or aisle?')


def _row(make_person, name):
    p = make_person(name=name, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
    with api_tx('read committed') as tx:
        email = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=p['id'])).fetchone()['email']
    return dict(person_id=p['id'], email=email, name='x', week=dict(new_members=[], total=40, spotlight=None))


def test_off_by_default_e2_has_no_question_line(make_person, aisle, drops, monkeypatch):
    monkeypatch.delenv('AHAVAH_E2_QUESTION_LINE_ENABLED', raising=False)
    drops(barbados_today(), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Off'))
    assert "This week's question" not in html


def test_on_it_names_the_question_that_went_live_this_week(make_person, aisle, drops, on):
    drops(barbados_today() - timedelta(days=1), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2On'))
    assert LINE in html


def test_a_drop_older_than_7_days_gives_no_line(make_person, aisle, drops, on):
    drops(barbados_today() - timedelta(days=8), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Old'))
    assert "This week's question" not in html


def test_no_line_for_a_member_who_had_the_launch_email_this_week(make_person, aisle, drops, on):
    drops(barbados_today(), aisle['key'])
    row = _row(make_person, 'E2Launch')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id)
                      VALUES (%(p)s, 'questions_launch', 'questions_launch')""", dict(p=row['person_id']))
    _, html = e2.build_for(row)
    assert "This week's question" not in html


def test_the_personal_e2_carries_it_too(make_person, aisle, drops, on, monkeypatch):
    monkeypatch.setenv('AHAVAH_E2_PERSONAL_ENABLED', '1')
    drops(barbados_today(), aisle['key'])
    _, html = e2.build_for(_row(make_person, 'E2Personal'))
    assert LINE in html


def test_the_proof_shows_the_line_and_writes_nothing():
    with api_tx('read committed') as tx:
        before = tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n']
    subject, html = e2.preview_question_line('owner@example.org')
    with api_tx('read committed') as tx:
        after = tx.execute('SELECT count(*) AS n FROM campaign_link').fetchone()['n']
    assert "This week's question: mountains or the sea? Answer in the app." in html
    assert subject == 'This week on Ahavah' and after == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_e2_question_line.py -q -p no:warnings`
Expected: the 2 tests that look for the line and the proof test fail; the 3 tests that expect no line pass.

- [ ] **Step 3: Write the implementation**

In `service/questions/member.py`, replace the import block at the top with:

```python
from datetime import datetime, timedelta
from typing import Optional

from service.campaigns.switches import enabled
from service.questions import copy
from service.questions.bank import LIVE, choice_of, question_json, question_state
from service.questions.schedule import barbados_today, current_drop
```

and append:

```python
# A member who had the launch email in the last 7 days already has the
# question in front of them (spec, Launch: the next E2 leaves the line out).
_Q_HAD_LAUNCH_EMAIL = """
    SELECT 1 FROM email_send_log
     WHERE person_id = %(p)s AND campaign = 'questions_launch'
       AND sent_at > %(now)s::timestamptz - interval '7 days'
    UNION ALL
    SELECT 1 FROM email_outbox
     WHERE person_id = %(p)s AND campaign = 'questions_launch'
       AND created_at > %(now)s::timestamptz - interval '7 days'
    LIMIT 1
"""


def e2_question_line(tx, person_id: int, now: datetime) -> Optional[str]:
    """The line in Monday's E2: the question that went live in the last 7
    days. None while the switch is off, when no question went live this
    week or when the member had the launch email this week."""
    if not enabled('e2_question_line'):
        return None
    drop = current_drop(tx, now)
    if drop is None or drop['live_on'] <= barbados_today(now) - timedelta(days=7):
        return None
    if tx.execute(_Q_HAD_LAUNCH_EMAIL, dict(p=person_id, now=now)).fetchone():
        return None
    return copy.e2_line(drop['question'])
```

In `emails/community_weekly.py`, add after `_personal_block`:

```python
def _question_block(line: Optional[str]) -> str:
    """This week's quick question (TEC-1845), held behind
    AHAVAH_E2_QUESTION_LINE_ENABLED. Built from the question bank, never
    member text; escaped all the same."""
    if not line:
        return ''
    return (f'<p class="e-text" style="margin:0 0 20px;font-family:{SANS};font-size:17px;'
            f'line-height:1.55;color:{INK_SOFT};">{_esc(line)}</p>')
```

Change the signature of `community_weekly_html` to:

```python
def community_weekly_html(new_members: list[dict], total_members: int, spotlight: Optional[dict], cta_url: str, unsubscribe_url: str,
                          *, personal_line: Optional[str] = None, invite_url: Optional[str] = None,
                          cta_label: str = "Open Discover", question_line: Optional[str] = None) -> str:
```

and in its body replace:

```python
{_personal_block(personal_line)}

{_safe_spotlight_block(spotlight)}
```

with:

```python
{_personal_block(personal_line)}

{_question_block(question_line)}

{_safe_spotlight_block(spotlight)}
```

Add `question_line` to the docstring's list: `` `personal_line`, `invite_url` and `cta_label` are the held personal parts (AHAVAH_E2_PERSONAL_ENABLED); `question_line` is this week's quick question (AHAVAH_E2_QUESTION_LINE_ENABLED); left out, the email is as it was. ``

In `emails/send_community_weekly.py`, add to the imports:

```python
from service.questions.member import e2_question_line
```

In `_build_personal`, replace:

```python
        new_members = newcomers_for(tx, pid, week)
    return parts['subject'], community_weekly_html(
        new_members, week['total'], week['spotlight'], cta,
        _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
        personal_line=parts['line'], invite_url=invite, cta_label=parts['cta_label'])
```

with:

```python
        new_members = newcomers_for(tx, pid, week)
        question_line = e2_question_line(tx, pid, datetime.now(timezone.utc))
    return parts['subject'], community_weekly_html(
        new_members, week['total'], week['spotlight'], cta,
        _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
        personal_line=parts['line'], invite_url=invite, cta_label=parts['cta_label'],
        question_line=question_line)
```

In `build_for`, replace:

```python
        new_members = newcomers_for(tx, row['person_id'], week)
    return SUBJECT, community_weekly_html(new_members, week['total'], week['spotlight'], cta,
                                          _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL))
```

with:

```python
        new_members = newcomers_for(tx, row['person_id'], week)
        question_line = (e2_question_line(tx, row['person_id'], datetime.now(timezone.utc))
                         if row.get('person_id') else None)
    return SUBJECT, community_weekly_html(new_members, week['total'], week['spotlight'], cta,
                                          _unsub_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL),
                                          question_line=question_line)
```

Add after `preview_personal`:

```python
def preview_question_line(to: str) -> tuple[str, str]:
    """The proof of the question line (TEC-1845): E2 as every member gets
    it, with the line for the sample question. Reads nothing per member and
    stores nothing; the button goes straight to Discover."""
    from service.questions.copy import SAMPLE_QUESTION, e2_line
    return SUBJECT, community_weekly_html(
        [dict(first_name='Rivka', country='US'), dict(first_name='Daniel', country='GB')], 58, None,
        f"{WEB_BASE_URL}/discover", _unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        question_line=e2_line(SAMPLE_QUESTION))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_e2_question_line.py tests/test_e2_personal.py tests/test_community_weekly.py tests/test_e2_newcomers_fit.py -q -p no:warnings`
Expected: all pass (6 new, the three E2 suites unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/member.py emails/community_weekly.py emails/send_community_weekly.py tests/test_e2_question_line.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): this week's question as one line in E2, held behind its switch" -m "Refs: TEC-1845"
```

---

### Task 12: Proofs of the pushes and the E2 line, to the owner only

**Files:**
- Create: `scripts/send_question_proofs.py`
- Test: `tests/test_send_question_proofs.py` (create)

**Interfaces:**
- Consumes: `scripts.send_proofs.PROOF_TO`, `PUSH_PERSON_ID`, `_inert`, `_smtp`, `_subscriptions`, `_push_one`; `copy.PUSH_PROOFS` (Task 9); `send_community_weekly.preview_question_line` (Task 11).
- Produces: `scripts.send_question_proofs.plan() -> tuple[list[dict], list[dict]]`, `main(argv)`; email proofs named `e2_question_line` (Task 14 adds `questions_launch`); 3 push proofs, each with its tag.

- [ ] **Step 1: Write the failing test**

Create `tests/test_send_question_proofs.py`:

```python
"""scripts/send_question_proofs.py (TEC-1845): one proof of each quick
question email and push, to the owner's address and his account (18) only.
A dry run by default; nothing recorded against any member, not even a push
tap; no switch read or changed."""
import os

import pytest

from database import api_tx
from scripts import send_question_proofs as sq

EXPECTED_EMAILS = {'e2_question_line'}
_TABLES = ('campaign_link', 'email_outbox', 'email_send_log', 'push_send_log', 'push_tap')


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f"SELECT count(*) AS n FROM {t}").fetchone()['n'] for t in _TABLES}


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def capture(monkeypatch, questions_schema):
    smtp, pushes, asked = _Smtp(), [], []
    monkeypatch.setattr(sq, '_smtp', lambda: smtp)
    monkeypatch.setattr(sq, '_subscriptions', lambda pid: asked.append(pid) or [
        dict(endpoint='https://push.test/a', p256dh='k', auth='a')])
    monkeypatch.setattr(sq, '_push_one', lambda sub, payload: pushes.append(payload))
    return smtp, pushes, asked


def test_the_plan_covers_every_question_proof():
    emails, pushes = sq.plan()
    assert {e['name'] for e in emails} == EXPECTED_EMAILS
    assert [p['title'] for p in pushes] == ["This week's question", 'An easy first line',
                                           'New on Ahavah: quick questions']
    assert not [p for p in pushes if 'src=' in p['url']], 'a proof tap would count as a member tap'
    assert sq.PROOF_TO == 'harrigan.tennyson@gmail.com' and sq.PUSH_PERSON_ID == 18


def test_a_dry_run_sends_nothing(capture, capsys):
    smtp, pushes, asked = capture
    before = _counts()
    sq.main([])
    assert smtp.sent == [] and pushes == [] and asked == []
    assert _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_send_goes_to_the_owner_only_and_records_nothing(capture, monkeypatch):
    smtp, pushes, asked = capture
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    sq.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'}
    assert len(smtp.sent) == len(EXPECTED_EMAILS)
    assert all(s['subject'].startswith('[PROOF] ') for s in smtp.sent)
    assert asked == [18] and len(pushes) == 3
    assert all(p['title'].startswith('[Proof] ') for p in pushes)
    assert [p['tag'] for p in pushes] == ['question:proof', 'match:proof', 'question:proof']
    assert _counts() == before and dict(os.environ) == env_before


def test_no_proof_carries_a_live_unsubscribe_link():
    from service.config import WEB_BASE_URL
    for e in sq.plan()[0]:
        assert f'{WEB_BASE_URL.rstrip("/")}/u/' not in e['html'], e['name']
        assert f'href="{sq.PROOF_LINK_DISABLED}"' in e['html'], e['name']
    by_name = {e['name']: e['html'] for e in sq.plan()[0]}
    assert "This week's question: mountains or the sea? Answer in the app." in by_name['e2_question_line']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_send_question_proofs.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'send_question_proofs' from 'scripts'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/send_question_proofs.py`:

```python
"""Send the owner one proof of each quick-question email and push
(TEC-1845), before any of their switches is turned on.

    python -m scripts.send_question_proofs            # DRY RUN: lists what it would send
    python -m scripts.send_question_proofs --send     # send the proofs

Run inside the api container (mailer settings and VAPID keys). The same
rules as scripts/send_proofs.py, whose address, account and helpers this
reuses: emails to PROOF_TO only, straight through the mailer, never the
outbox; pushes to account PUSH_PERSON_ID's subscriptions only, sent
directly; sample data only; no switch read or changed; every unsubscribe
link inert. Push links carry no ?src=, so a proof tap counts as nothing.

The tag check the spec asks for ("Whether iOS replaces by tag is
unverified; the owner's proof should test it"): the weekly and launch
proofs share the tag question:proof. On a device that replaces by tag,
only the launch proof is left once both have arrived.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from scripts.send_proofs import (PROOF_LINK_DISABLED, PROOF_TO, PUSH_PERSON_ID, _inert,
                                 _push_one, _smtp, _subscriptions)

__all__ = ['PROOF_LINK_DISABLED', 'PROOF_TO', 'PUSH_PERSON_ID', 'plan', 'main']


def _emails() -> list[dict]:
    from emails import send_community_weekly
    builders = [
        ('e2_question_line', 'Weekly email with the question line',
         send_community_weekly.preview_question_line, send_community_weekly.FROM_ADDR),
    ]
    out = []
    for name, label, build, from_addr in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f"[PROOF] {subject}",
                        html=_inert(name, html), from_addr=from_addr))
    return out


def _pushes() -> list[dict]:
    from service.questions.copy import PUSH_PROOFS
    return [dict(p) for p in PUSH_PROOFS]


def plan() -> tuple[list[dict], list[dict]]:
    """Every proof email (built) and every proof push. Writes nothing."""
    return _emails(), _pushes()


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--send', action='store_true', help='send the proofs (default: dry run)')
    a = ap.parse_args(argv)
    emails, pushes = plan()
    print(f"{'SEND' if a.send else 'DRY RUN'}: {len(emails)} proof emails to {PROOF_TO}, "
          f"{len(pushes)} proof pushes to account {PUSH_PERSON_ID}")
    for e in emails:
        print(f"  email  {e['name']:17s} {e['subject']}  ({e['label']})")
    for p in pushes:
        print(f"  push   {p['kind']:17s} {p['title']}: {p['body']} -> {p['url']} [{p['tag']}]")
    if not a.send:
        print('Nothing sent. Run with --send to send these proofs.')
        return
    smtp = _smtp()
    for e in emails:
        mid = smtp.send(subject=e['subject'], body=e['html'], to_addr=PROOF_TO, from_addr=e['from_addr'])
        print(f"sent {e['name']} ({mid or 'no id'})")
    subs = _subscriptions(PUSH_PERSON_ID)
    if not subs:
        print(f"account {PUSH_PERSON_ID} has no push subscription; no push sent")
    for p in pushes:
        payload = dict(title=f"[Proof] {p['title']}", body=p['body'], url=p['url'], tag=p['tag'])
        for sub in subs:
            status = _push_one(sub, payload)
            print(f"pushed {p['kind']} ({'ok' if status is None else status})")


if __name__ == '__main__':
    main(sys.argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_send_question_proofs.py tests/test_send_proofs.py -q -p no:warnings`
Expected: all pass (4 new, the Wave 3 proof suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add scripts/send_question_proofs.py tests/test_send_question_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): proofs of the question pushes and the E2 line, to the owner only" -m "Refs: TEC-1845"
```

---

### Task 13: Admin > Questions, the API

**Files:**
- Create: `service/questions/admin.py`
- Create: `service/api/admin/questions_routes.py`
- Modify: `service/api/__init__.py` (bottom, after `import service.api.questions_routes`)
- Modify: `duotypes/__init__.py` (after `class PostPushTap`)
- Test: `tests/test_admin_questions.py` (create)

**Interfaces:**
- Consumes: `CHOICE_FORMATS`, `LIVE`, `live_question` (Task 2); `FIRST_WEEKS`, `barbados_today`, `drop_day`, `week_start` (Task 3); `enabled`; `require_admin`, `record_audit`.
- Produces, in `service.questions.admin`: `SWITCH_NAMES`, `LABEL_MAX = 40`, `GUARD_RAIL_SWITCH_OFFS = 2`, `QuestionEditRefused`, `ScheduleRefused`, `switch_states() -> dict[str, bool]`, `bank_rows(tx) -> list[dict]`, `update_question(tx, key, *, active=None, labels=None) -> dict`, `schedule_rows(tx, now=None, weeks=6) -> list[dict]`, `set_drop(tx, day, key, now=None)`, `clear_drop(tx, day, now=None)`, `approve(tx, days, now=None) -> list[str]`, `push_rows(tx, weeks=8) -> list[dict]`. Routes (admin only): `GET /admin/questions`, `PATCH /admin/questions/<key>`, `GET /admin/questions/schedule`, `PUT /admin/questions/schedule/<live_on>`, `DELETE /admin/questions/schedule/<live_on>`, `POST /admin/questions/schedule/approve`, `GET /admin/questions/pushes`. `duotypes.PatchAdminQuestion`, `PutQuestionDrop`, `PostApproveDrops`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_questions.py`:

```python
"""Admin > Questions, the API (TEC-1845, spec "Screens" 7).

The bank with its options and counts split by sex (counts only); switching
a question on or off and editing option wording, never its keys; the next
6 weeks with the approved order proposed for empty weeks, which the owner
fills, reorders and approves; pushes sent, tapped and switched off by week,
with the guard rail at 2 switch-offs; and the state of each switch.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone

import pytest

import service.spotlight.restdays as rd
from database import api_tx
from service.questions import admin as qa
from service.questions.schedule import FIRST_WEEKS

pytestmark = pytest.mark.usefixtures('questions_schema')

SUN = date(2027, 1, 3)
NOW = datetime.combine(SUN - timedelta(days=2), time(15), timezone.utc)  # Friday 1 Jan 2027


def _headers(person, admin: bool) -> dict:
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        if admin:
            tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=person['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=person['id']))
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date(2027, 12, 31))
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    window = dict(a=SUN - timedelta(days=7), b=SUN + timedelta(days=70))
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)
    yield
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on >= %(a)s AND live_on < %(b)s', window)


def _answer(person_id, question, index):
    with api_tx() as tx:
        tx.execute("INSERT INTO prompt_answer (person_id, prompt_key, choice_key) VALUES (%(p)s, %(k)s, %(c)s)",
                   dict(p=person_id, k=question['key'], c=question['options'][index]['key']))


def test_only_an_admin_may_read_or_change(client, make_person, make_question):
    member = _headers(make_person(name='QaMember'), admin=False)
    q = make_question()
    assert client.get('/admin/questions', headers=member).status_code == 403
    assert client.get('/admin/questions/schedule', headers=member).status_code == 403
    assert client.patch(f"/admin/questions/{q['key']}", headers=member, json=dict(active=False)).status_code == 403


def test_the_bank_lists_every_question_with_its_split_by_sex(client, make_person, make_question):
    admin = _headers(make_person(name='QaAdmin'), admin=True)
    q = make_question()
    for name, gender, index in (('QaW1', 'Woman', 0), ('QaW2', 'Woman', 0), ('QaM1', 'Man', 1)):
        _answer(make_person(name=name, gender=gender)['id'], q, index)
    body = client.get('/admin/questions', headers=admin).get_json()
    rows = {r['key']: r for r in body['bank']}
    assert {'mountains-or-sea', 'pet'} <= set(rows)
    row = rows[q['key']]
    assert row['answers'] == 3
    assert [(o['n'], o['by_sex']) for o in row['options']] == [(2, {'woman': 2}), (1, {'man': 1})]
    assert set(body['switches']) == set(qa.SWITCH_NAMES)


def test_a_label_edit_keeps_every_answer(client, make_person, make_question):
    admin = _headers(make_person(name='QaLabel'), admin=True)
    q = make_question(labels=('Mountains', 'The sea'))
    member = make_person(name='QaLabelMember')
    _answer(member['id'], q, 0)
    first = q['options'][0]['key']
    r = client.patch(f"/admin/questions/{q['key']}", headers=admin, json=dict(labels={first: 'The hills'}))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [o['label'] for o in r.get_json()['options']] == ['The hills', 'The sea']
    with api_tx('read committed') as tx:
        assert tx.execute('SELECT choice_key FROM prompt_answer WHERE person_id = %(p)s AND prompt_key = %(k)s',
                          dict(p=member['id'], k=q['key'])).fetchone()['choice_key'] == first


def test_a_bad_label_or_switching_on_an_open_question_is_refused(client, make_person, make_question):
    admin = _headers(make_person(name='QaBad'), admin=True)
    q = make_question()
    first = q['options'][0]['key']
    for labels in ({first: 'x' * 41}, {'not-an-option': 'X'}, {first: 'A \u2014 B'}, {first: '  '}, {}):
        r = client.patch(f"/admin/questions/{q['key']}", headers=admin, json=dict(labels=labels))
        assert (r.status_code, r.get_json()) == (400, dict(error='bad_labels')), labels
    r = client.patch('/admin/questions/pet', headers=admin, json=dict(active=True))
    assert (r.status_code, r.get_json()) == (400, dict(error='not_a_choice_question'))
    assert client.patch('/admin/questions/no-such-question', headers=admin,
                        json=dict(active=False)).status_code == 404


def test_the_schedule_shows_6_weeks_with_the_approved_order_proposed(calendar):
    with api_tx('read committed') as tx:
        rows = qa.schedule_rows(tx, NOW)
        used = {r['prompt_key'] for r in tx.execute('SELECT DISTINCT prompt_key FROM question_drop').fetchall()}
    assert [r['week_of'] for r in rows] == [(SUN - timedelta(days=7) + timedelta(weeks=i)).isoformat() for i in range(6)]
    assert [r['live_on'] for r in rows] == [r['week_of'] for r in rows], 'with no rest day, each drop is the Sunday'
    assert rows[0]['proposed_key'] is None, 'a week already under way is not proposed'
    fresh = [k for k in FIRST_WEEKS if k not in used]
    k = min(5, len(fresh))
    assert [r['proposed_key'] for r in rows[1:1 + k]] == fresh[:k]


def test_a_week_can_be_filled_reordered_and_approved(calendar, make_question):
    q1, q2 = make_question(), make_question()
    week2 = SUN + timedelta(days=7)
    with api_tx() as tx:
        qa.set_drop(tx, SUN, q1['key'], now=NOW)
        assert qa.approve(tx, [SUN, week2], now=NOW) == [SUN.isoformat(), week2.isoformat()]
        rows = {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}
        assert (rows[SUN.isoformat()]['prompt_key'], rows[SUN.isoformat()]['approved']) == (q1['key'], True)
        assert rows[week2.isoformat()]['approved'] is True and rows[week2.isoformat()]['prompt_key']
        qa.set_drop(tx, SUN, q2['key'], now=NOW)
        rows = {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}
        assert (rows[SUN.isoformat()]['prompt_key'], rows[SUN.isoformat()]['approved']) == (q2['key'], False)
        qa.clear_drop(tx, SUN, now=NOW)
        assert {r['live_on']: r for r in qa.schedule_rows(tx, NOW)}[SUN.isoformat()]['prompt_key'] is None


def test_a_question_goes_only_on_its_weeks_drop_day(calendar, client, make_person, make_question):
    q, off = make_question(), make_question(active=False)
    cases = ((SUN + timedelta(days=1), q['key'], 'not_a_drop_day'),
             (SUN - timedelta(days=7), q['key'], 'already_live'),
             (SUN, off['key'], 'not_a_live_question'))
    for day, key, reason in cases:
        with pytest.raises(qa.ScheduleRefused, match=reason):
            with api_tx() as tx:
                qa.set_drop(tx, day, key, now=NOW)
    admin = _headers(make_person(name='QaDay'), admin=True)
    r = client.put('/admin/questions/schedule/not-a-date', headers=admin, json=dict(prompt_key=q['key']))
    assert (r.status_code, r.get_json()) == (400, dict(error='bad_day'))


def test_pushes_taps_and_switch_offs_by_week(calendar, make_person, make_question):
    q = make_question()
    a, b = make_person(name='QaPushA'), make_person(name='QaPushB')
    in_week = '2027-01-04 12:00:00+00'
    with api_tx() as tx:
        tx.execute("INSERT INTO question_drop (live_on, prompt_key, approved_at) VALUES (%(d)s, %(k)s, NOW())",
                   dict(d=SUN, k=q['key']))
        for p in (a, b):
            tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                          VALUES (%(p)s, 'question', '2027-01-03', %(t)s)""", dict(p=p['id'], t=in_week))
            tx.execute("""INSERT INTO notification_preference (person_id, push_questions, push_questions_off_at)
                          VALUES (%(p)s, FALSE, %(t)s)""", dict(p=p['id'], t=in_week))
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'launch', %(t)s)""", dict(p=a['id'], t=in_week))
        tx.execute("""INSERT INTO push_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'match_question', 'm-qa', %(t)s)""", dict(p=b['id'], t=in_week))
        tx.execute("INSERT INTO push_tap (person_id, src, tapped_at) VALUES (%(p)s, 'qpush', %(t)s)",
                   dict(p=a['id'], t=in_week))
        rows = {r['live_on']: r for r in qa.push_rows(tx, weeks=52)}
    row = rows[SUN.isoformat()]
    assert (row['weekly_sent'], row['launch_sent'], row['match_question_sent']) == (1, 1, 1)
    assert row['taps'] == dict(qpush=1, mpush=0, lpush=0)
    assert (row['switched_off'], row['guard_rail']) == (2, True)


def test_the_routes_answer_an_admin(client, make_person, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTION_PUSH_ENABLED', raising=False)
    monkeypatch.setenv('AHAVAH_E2_QUESTION_LINE_ENABLED', '1')
    admin = _headers(make_person(name='QaRoutes'), admin=True)
    body = client.get('/admin/questions', headers=admin).get_json()
    assert body['switches']['e2_question_line'] is True and body['switches']['question_push'] is False
    assert len(client.get('/admin/questions/schedule', headers=admin).get_json()['weeks']) == 6
    assert isinstance(client.get('/admin/questions/pushes', headers=admin).get_json()['weeks'], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_admin_questions.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'admin' from 'service.questions'`.

- [ ] **Step 3: Write the implementation**

Create `service/questions/admin.py`:

```python
"""Admin > Questions (TEC-1845, spec "Screens" 7).

What the owner reads and changes:

  the bank      every question with its options and its counts split by sex
                (counts only, never who). He switches a question on or off
                and edits option wording; keys never change, because answers
                and the launch email's links are keyed on them. An open
                (text) question cannot be switched on in release 1.
  the schedule  the next SCHEDULE_WEEKS weeks, each with its drop day
                (service/questions/schedule.py) and question. An empty week
                ahead is offered the approved order (FIRST_WEEKS), then the
                rest of the bank. He fills, reorders and approves; changing
                an approved week's question takes its approval away. A week
                already under way is not changed here.
  pushes        sent, tapped and switched off, by question week. 2 or more
                switch-offs in a week is the guard rail: move to a
                fortnightly push.
  switches      their state; this tab never flips them.

Every function takes the caller's transaction and never opens one.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

import service.spotlight.restdays as rd
from service.admin.queries.members import member_sql
from service.campaigns.switches import enabled
from service.questions.bank import CHOICE_FORMATS, LIVE, live_question
from service.questions.schedule import FIRST_WEEKS, barbados_today, drop_day, week_start

SWITCH_NAMES = ('question_push', 'match_question_push', 'e2_question_line',
                'questions_launch_email', 'questions_launch_push')
LABEL_MAX = 40
GUARD_RAIL_SWITCH_OFFS = 2
SCHEDULE_WEEKS = 6


class QuestionEditRefused(ValueError):
    """'unknown_question', 'not_a_choice_question' or 'bad_labels'."""


class ScheduleRefused(ValueError):
    """'not_a_drop_day', 'already_live', 'not_a_live_question' or
    'nothing_to_propose'."""


def switch_states() -> dict:
    return {name: enabled(name) for name in SWITCH_NAMES}


_Q_BANK = """
    SELECT key, text, category, format, options, active, sort
      FROM prompt_bank ORDER BY sort, key
"""

_Q_SPLIT = f"""
    SELECT a.prompt_key, a.choice_key, COALESCE(lower(g.name), 'unknown') AS sex, count(*) AS n
      FROM prompt_answer a
      JOIN person p ON p.id = a.person_id AND p.activated AND {member_sql('p')}
      LEFT JOIN gender g ON g.id = p.gender_id
     WHERE a.choice_key IS NOT NULL
     GROUP BY 1, 2, 3
"""


def bank_rows(tx) -> list[dict]:
    split: dict = {}
    for r in tx.execute(_Q_SPLIT).fetchall():
        split.setdefault((r['prompt_key'], r['choice_key']), {})[r['sex']] = int(r['n'])
    rows = []
    for b in tx.execute(_Q_BANK).fetchall():
        options = []
        for o in b['options']:
            by_sex = split.get((b['key'], o['key']), {})
            options.append(dict(key=o['key'], label=o['label'], n=sum(by_sex.values()), by_sex=by_sex))
        rows.append(dict(key=b['key'], text=b['text'], category=b['category'], format=b['format'],
                         active=b['active'], sort=b['sort'],
                         answers=sum(o['n'] for o in options), options=options))
    return rows


def update_question(tx, key: str, *, active: Optional[bool] = None,
                    labels: Optional[dict] = None) -> dict:
    row = tx.execute('SELECT key, format, options, active FROM prompt_bank WHERE key = %(k)s FOR UPDATE',
                     dict(k=key)).fetchone()
    if row is None:
        raise QuestionEditRefused('unknown_question')
    if active is True and row['format'] not in CHOICE_FORMATS:
        raise QuestionEditRefused('not_a_choice_question')
    options = [dict(key=o['key'], label=o['label']) for o in row['options']]
    if labels is not None:
        keys = {o['key'] for o in options}
        if not labels or set(labels) - keys:
            raise QuestionEditRefused('bad_labels')
        edited = []
        for o in options:
            label = labels.get(o['key'], o['label'])
            label = label.strip() if isinstance(label, str) else ''
            if not label or len(label) > LABEL_MAX or '\u2014' in label:
                raise QuestionEditRefused('bad_labels')
            edited.append(dict(key=o['key'], label=label))
        options = edited
    tx.execute("""UPDATE prompt_bank SET options = %(o)s::jsonb, active = COALESCE(%(a)s, active)
                   WHERE key = %(k)s""", dict(o=json.dumps(options), a=active, k=key))
    return dict(key=key, active=row['active'] if active is None else active, options=options)


_Q_LIVE_KEYS = f"SELECT b.key FROM prompt_bank b WHERE {LIVE} ORDER BY b.sort, b.key"
_Q_USED_KEYS = "SELECT DISTINCT prompt_key FROM question_drop"


def _proposal_queue(tx) -> list[str]:
    """The approved order first, then the rest of the bank, leaving out any
    question that has had a week."""
    live = [r['key'] for r in tx.execute(_Q_LIVE_KEYS).fetchall()]
    used = {r['prompt_key'] for r in tx.execute(_Q_USED_KEYS).fetchall()}
    first = [k for k in FIRST_WEEKS if k in live and k not in used]
    return first + [k for k in live if k not in used and k not in FIRST_WEEKS]


_Q_DROPS = """
    SELECT d.live_on, d.prompt_key, d.approved_at, b.text
      FROM question_drop d JOIN prompt_bank b ON b.key = d.prompt_key
     WHERE d.live_on >= %(a)s AND d.live_on < %(b)s
"""


def schedule_rows(tx, now: Optional[datetime] = None, weeks: int = SCHEDULE_WEEKS) -> list[dict]:
    today = barbados_today(now)
    first = week_start(today)
    drops = {r['live_on']: r for r in tx.execute(
        _Q_DROPS, dict(a=first, b=first + timedelta(weeks=weeks))).fetchall()}
    queue = _proposal_queue(tx)
    out = []
    for i in range(weeks):
        week_of = first + timedelta(weeks=i)
        day = drop_day(week_of)
        d = drops.get(day) if day else None
        proposed = queue.pop(0) if (day and d is None and day > today and queue) else None
        problem = None
        if day is None:
            problem = 'unknown' if week_of + timedelta(days=7) > rd.KNOWN_THROUGH else 'no_free_day'
        out.append(dict(week_of=week_of.isoformat(), live_on=day.isoformat() if day else None,
                        problem=problem, prompt_key=d['prompt_key'] if d else None,
                        text=d['text'] if d else None, approved=bool(d and d['approved_at']),
                        proposed_key=proposed))
    return out


def _check_day(day: date, now: Optional[datetime]) -> None:
    if drop_day(day) != day:
        raise ScheduleRefused('not_a_drop_day')
    if day <= barbados_today(now):
        raise ScheduleRefused('already_live')


_Q_SET_DROP = """
    INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, %(k)s)
    ON CONFLICT (live_on) DO UPDATE
       SET prompt_key = EXCLUDED.prompt_key,
           approved_at = CASE WHEN question_drop.prompt_key = EXCLUDED.prompt_key
                              THEN question_drop.approved_at END
"""


def set_drop(tx, day: date, key: str, now: Optional[datetime] = None) -> None:
    _check_day(day, now)
    if live_question(tx, key) is None:
        raise ScheduleRefused('not_a_live_question')
    tx.execute(_Q_SET_DROP, dict(d=day, k=key))


def clear_drop(tx, day: date, now: Optional[datetime] = None) -> None:
    _check_day(day, now)
    tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=day))


def approve(tx, days: list[date], now: Optional[datetime] = None) -> list[str]:
    """Approve each week, filling an empty one with the next proposal."""
    queue = _proposal_queue(tx)
    done = []
    for day in sorted(days):
        _check_day(day, now)
        if tx.execute('SELECT 1 FROM question_drop WHERE live_on = %(d)s', dict(d=day)).fetchone() is None:
            if not queue:
                raise ScheduleRefused('nothing_to_propose')
            tx.execute('INSERT INTO question_drop (live_on, prompt_key) VALUES (%(d)s, %(k)s)',
                       dict(d=day, k=queue.pop(0)))
        tx.execute('UPDATE question_drop SET approved_at = COALESCE(approved_at, NOW()) WHERE live_on = %(d)s',
                   dict(d=day))
        done.append(day.isoformat())
    return done


# A question week runs from 00:00 Barbados on its drop day to the next
# drop's, or 7 days when there is none yet. The launch push is also logged
# as that week's question push, so weekly_sent takes it back out.
_Q_PUSHES = """
    WITH w AS (
        SELECT live_on,
               live_on::timestamp AT TIME ZONE 'America/Barbados' AS starts,
               COALESCE(LEAD(live_on) OVER (ORDER BY live_on), live_on + 7)::timestamp
                   AT TIME ZONE 'America/Barbados' AS ends
          FROM question_drop WHERE approved_at IS NOT NULL
    )
    SELECT w.live_on,
           (SELECT count(*) FROM push_send_log l
             WHERE l.campaign = 'question' AND l.campaign_id = w.live_on::text) AS question_sent,
           (SELECT count(*) FROM push_send_log l WHERE l.campaign = 'questions_launch'
               AND l.sent_at >= w.starts AND l.sent_at < w.ends) AS launch_sent,
           (SELECT count(*) FROM push_send_log l WHERE l.campaign = 'match_question'
               AND l.sent_at >= w.starts AND l.sent_at < w.ends) AS match_question_sent,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'qpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS qpush,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'mpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS mpush,
           (SELECT count(*) FROM push_tap t WHERE t.src = 'lpush'
               AND t.tapped_at >= w.starts AND t.tapped_at < w.ends) AS lpush,
           (SELECT count(*) FROM notification_preference np
             WHERE np.push_questions_off_at >= w.starts AND np.push_questions_off_at < w.ends) AS switched_off
      FROM w
     ORDER BY w.live_on DESC
     LIMIT %(n)s
"""


def push_rows(tx, weeks: int = 8) -> list[dict]:
    out = []
    for r in tx.execute(_Q_PUSHES, dict(n=weeks)).fetchall():
        launch = int(r['launch_sent'])
        off = int(r['switched_off'])
        out.append(dict(live_on=r['live_on'].isoformat(),
                        weekly_sent=int(r['question_sent']) - launch, launch_sent=launch,
                        match_question_sent=int(r['match_question_sent']),
                        taps=dict(qpush=int(r['qpush']), mpush=int(r['mpush']), lpush=int(r['lpush'])),
                        switched_off=off, guard_rail=off >= GUARD_RAIL_SWITCH_OFFS))
    return out
```

In `duotypes/__init__.py`, after `class PostPushTap`, add:

```python
class PatchAdminQuestion(BaseModel):
    """PATCH /admin/questions/<key> (TEC-1845): switch on or off, and/or
    new wording for some options, keyed by option key."""
    active: Optional[bool] = None
    labels: Optional[Dict[str, str]] = None


class PutQuestionDrop(BaseModel):
    prompt_key: str = Field(min_length=1, max_length=64)


class PostApproveDrops(BaseModel):
    live_on: List[str] = Field(min_length=1, max_length=12)
```

Create `service/api/admin/questions_routes.py`:

```python
"""Admin > Questions (TEC-1845). Admin sessions only; every change is
audited in the transaction that makes it."""
from __future__ import annotations

from datetime import date
from typing import Optional

import duotypes as t
from database import api_tx
from service.admin import record_audit, require_admin
from service.api.decorators import adelete, aget, apatch, apost, aput, validate
from service.questions import admin as qa


def _day(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@aget('/admin/questions')
def get_admin_questions(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(bank=qa.bank_rows(tx), switches=qa.switch_states())


@apatch('/admin/questions/<key>')
@validate(t.PatchAdminQuestion)
def patch_admin_question(req: t.PatchAdminQuestion, s: t.SessionInfo, key: str):
    require_admin(s)
    try:
        with api_tx() as tx:
            row = qa.update_question(tx, key, active=req.active, labels=req.labels)
            record_audit(tx, s, 'questions.update', metadata=dict(key=key, active=req.active, labels=req.labels))
            return row
    except qa.QuestionEditRefused as e:
        return dict(error=str(e)), (404 if str(e) == 'unknown_question' else 400)


@aget('/admin/questions/schedule')
def get_admin_question_schedule(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(weeks=qa.schedule_rows(tx))


@aput('/admin/questions/schedule/<live_on>')
@validate(t.PutQuestionDrop)
def put_admin_question_drop(req: t.PutQuestionDrop, s: t.SessionInfo, live_on: str):
    require_admin(s)
    day = _day(live_on)
    if day is None:
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            qa.set_drop(tx, day, req.prompt_key)
            record_audit(tx, s, 'questions.schedule', metadata=dict(live_on=live_on, prompt_key=req.prompt_key))
            return dict(weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@adelete('/admin/questions/schedule/<live_on>')
def delete_admin_question_drop(s: t.SessionInfo, live_on: str):
    require_admin(s)
    day = _day(live_on)
    if day is None:
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            qa.clear_drop(tx, day)
            record_audit(tx, s, 'questions.unschedule', metadata=dict(live_on=live_on))
            return dict(weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@apost('/admin/questions/schedule/approve')
@validate(t.PostApproveDrops)
def post_admin_question_approve(req: t.PostApproveDrops, s: t.SessionInfo):
    require_admin(s)
    days = [_day(v) for v in req.live_on]
    if any(d is None for d in days):
        return dict(error='bad_day'), 400
    try:
        with api_tx() as tx:
            approved = qa.approve(tx, days)
            record_audit(tx, s, 'questions.approve', metadata=dict(live_on=approved))
            return dict(approved=approved, weeks=qa.schedule_rows(tx))
    except qa.ScheduleRefused as e:
        return dict(error=str(e)), 400


@aget('/admin/questions/pushes')
def get_admin_question_pushes(s: t.SessionInfo):
    require_admin(s)
    with api_tx('read committed') as tx:
        return dict(weeks=qa.push_rows(tx))
```

In `service/api/__init__.py`, after `import service.api.questions_routes  # noqa: E402,F401`, add:

```python
import service.api.admin.questions_routes  # noqa: E402,F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_admin_questions.py -q -p no:warnings`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add service/questions/admin.py service/api/admin/questions_routes.py service/api/__init__.py duotypes/__init__.py tests/test_admin_questions.py
git -c user.email=admin@techbaseltd.com commit -m "feat(admin): Questions: the bank, the 6-week schedule, pushes by week, switches" -m "Refs: TEC-1845"
```

---

### Task 14: The launch email

This task waits for the 2 title images from the revised design export (brief section 8). Every other backend task is independent of design.

**Files:**
- Add: `ahavah-web/public/email/title-quick-questions.png`, `ahavah-web/public/email/title-quick-questions-wht.png` (from the export)
- Add (by the sync script): `emails/assets/title-quick-questions.png`, `emails/assets/title-quick-questions-wht.png`; Modify: `tests/email_assets_manifest.txt`
- Create: `emails/questions_launch.py`
- Modify: `service/campaigns/__init__.py` (`SELF_CAPPED_CAMPAIGNS`)
- Modify: `service/cron/returnmail/__init__.py` (import and `JOBS`)
- Modify: `scripts/send_question_proofs.py` (`_emails`), `tests/test_send_question_proofs.py` (`EXPECTED_EMAILS`)
- Test: `tests/test_questions_launch_email.py` (create)

**Interfaces:**
- Consumes: `current_drop`, `barbados_today`, `resting` (Task 3); `copy.in_sentence`, `copy.short_question`, `copy.SAMPLE_QUESTION` (Task 9); the `questions_launch_email` switch (Task 7); `make_campaign_link`, `held.queue`, `held.already_queued`, `held.para`, `held.footer`, `held.SEND_HOUR_UTC`; `emails.base.render`, `chip`, `title_image`, `LIME`, `INK`, `SANS`.
- Produces: `emails.questions_launch.CAMPAIGN = 'questions_launch'`, `CAMPAIGN_ID = 'questions_launch'`, `SUBJECT`, `FROM_ADDR`, `TITLE_WIDTH`, `launch_html(question, links, unsubscribe_url) -> str`, `queue_due(tx, now) -> int`, `preview(to) -> tuple[str, str]`; `returnmail.JOBS` gains `('questions_launch_email', ...)`.

- [ ] **Step 1: Bring in the title images**

From the revised export, take `title-quick-questions.png` (dark ink) and `title-quick-questions-wht.png` (white ink), exported at 2x, and copy both into `/d/Antigravity/ahavah-web/public/email/`. Note the width the design sets (between 360 and 528 px); Step 4 uses it.

Run: `cd /d/Antigravity/ahavah-api && ./scripts/sync_email_assets.sh`
Expected: both files are copied into `emails/assets/` and `tests/email_assets_manifest.txt` lists them.

- [ ] **Step 2: Write the failing test**

Create `tests/test_questions_launch_email.py`:

```python
"""The launch email (TEC-1845, spec "Launch").

To every member who has not left campaign emails, once per member ever, on
a drop day from 12:00 UTC while its switch is on. One button per option,
each its own campaign link to /q/{key}/{choice}; the click alone saves
nothing (the web page saves once the member is signed in). Exempt from the
7-day campaign cap, which E2 would otherwise trip for nearly everyone.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

from database import api_tx
from emails import questions_launch as ql
from service.campaigns import SELF_CAPPED_CAMPAIGNS
from service.config import WEB_BASE_URL
from service.questions.schedule import barbados_today

pytestmark = pytest.mark.usefixtures('questions_schema')

UTC = timezone.utc


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED', '1')


@pytest.fixture
def week(make_question, drops):
    q = make_question(labels=('Mountains', 'The sea'),
                      text='Would you rather wake up to mountains or the sea?')
    today = barbados_today()
    drops(today, q['key'])
    return dict(question=q, today=today)


def _at(day, hour, minute=30) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def _member(make_person, name):
    return make_person(name=name, email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')


def _run(now) -> None:
    with api_tx() as tx:
        ql.queue_due(tx, now)


def _queued(person) -> list[dict]:
    with api_tx('read committed') as tx:
        return [dict(r) for r in tx.execute(
            """SELECT campaign_id, exempt, unsub_scope, payload->>'subject' AS subject,
                      payload->>'html' AS html
                 FROM email_outbox WHERE person_id = %(p)s AND campaign = 'questions_launch'""",
            dict(p=person['id'])).fetchall()]


def test_off_by_default(make_person, week, monkeypatch):
    monkeypatch.delenv('AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED', raising=False)
    m = _member(make_person, 'LaunchMailOff')
    _run(_at(week['today'], 12))
    assert _queued(m) == []


def test_on_a_drop_day_from_12_utc_each_member_gets_it_once(make_person, week, on):
    m = _member(make_person, 'LaunchMail')
    _run(_at(week['today'], 12))
    [row] = _queued(m)
    assert (row['campaign_id'], row['exempt'], row['unsub_scope'], row['subject']) == (
        'questions_launch', True, 'campaigns', 'New on Ahavah: quick questions')
    with api_tx('read committed') as tx:
        targets = {r['target_url'] for r in tx.execute(
            "SELECT target_url FROM campaign_link WHERE kind = 'questions_launch' AND subject_person_id = %(p)s",
            dict(p=m['id'])).fetchall()}
    q = week['question']
    assert targets == {f"{WEB_BASE_URL.rstrip('/')}/q/{q['key']}/{o['key']}" for o in q['options']}
    _run(_at(week['today'], 15))
    assert len(_queued(m)) == 1


def test_not_before_12_or_on_a_day_without_a_drop(make_person, week, on):
    m = _member(make_person, 'LaunchMailEarly')
    _run(_at(week['today'], 11))
    _run(_at(week['today'] + timedelta(days=1), 12))
    assert _queued(m) == []


def test_never_twice(make_person, week, on):
    m = _member(make_person, 'LaunchMailTwice')
    with api_tx() as tx:
        tx.execute("""INSERT INTO email_send_log (person_id, campaign, campaign_id, sent_at)
                      VALUES (%(p)s, 'questions_launch', 'questions_launch', NOW() - interval '20 days')""",
                   dict(p=m['id']))
    _run(_at(week['today'], 12))
    assert _queued(m) == []


def test_not_to_a_member_who_left_campaign_emails_or_to_staff(make_person, week, on):
    left, staff = _member(make_person, 'LaunchMailLeft'), _member(make_person, 'LaunchMailStaff')
    with api_tx() as tx:
        tx.execute('UPDATE person SET campaigns_unsubscribed_at = NOW() WHERE id = %(p)s', dict(p=left['id']))
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(p)s", dict(p=staff['id']))
    _run(_at(week['today'], 12))
    assert _queued(left) == _queued(staff) == []


def test_the_email_reads_as_drafted():
    subject, html = ql.preview('owner@example.org')
    assert subject == 'New on Ahavah: quick questions'
    for text in ('New in the app', 'alt="Quick questions."',
                 'Each week a light question now waits for you in the app.',
                 'This week: would you rather wake up to mountains or the sea?',
                 '>Mountains<', '>The sea<',
                 "Tap your answer. We'll save it once you're signed in.",
                 'Also new on Ahavah',
                 'See who liked you in Liked you, and like them back from their profile.',
                 'Discover now keeps going past the first 10 profiles.',
                 'A reminder when a match or a message is waiting for you.',
                 "This week's is mountains or the sea. Tap your answer."):
        assert text in html, text
    assert '\u2014' not in html and 'Sunday' not in html


def test_it_is_exempt_from_the_7_day_cap():
    assert 'questions_launch' in SELF_CAPPED_CAMPAIGNS


def test_the_preview_writes_nothing():
    with api_tx('read committed') as tx:
        before = [tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                  for t in ('campaign_link', 'email_outbox')]
    ql.preview('owner@example.org')
    with api_tx('read committed') as tx:
        after = [tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                 for t in ('campaign_link', 'email_outbox')]
    assert after == before
```

In `tests/test_send_question_proofs.py`, change:

```python
EXPECTED_EMAILS = {'e2_question_line'}
```

to:

```python
EXPECTED_EMAILS = {'e2_question_line', 'questions_launch'}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_questions_launch_email.py tests/test_send_question_proofs.py -q -p no:warnings`
Expected: collection error, `ImportError: cannot import name 'questions_launch' from 'emails'`.

- [ ] **Step 4: Write the implementation**

Create `emails/questions_launch.py` (set `TITLE_WIDTH` to the width the export gives in Step 1):

```python
"""The quick questions launch email (TEC-1845, spec "Launch").

To every member who has not left campaign emails, once per member ever
(email_send_log campaign questions_launch), on a drop day from 12:00 UTC,
held behind AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED. Members away for more
than 30 days are included: for them it is a reason to come back.

Each option is its own campaign link to /q/{key}/{choice} on the web app,
so clicks count per option. The click alone records nothing (mail scanners
open links); the page saves the answer once the member is signed in, and
never over an earlier one.

Brand shell, title image from Claude Design (never hand-rolled type), the
campaigns footer and unsubscribe. In SELF_CAPPED_CAMPAIGNS and queued
exempt: E2 goes to every member every Monday, so a 7-day cap would skip
nearly everyone. Owner decision 1: no line names Sunday.

Copy rules: no em dashes, sentence case, digits.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from emails.base import INK, LIME, SANS, chip, render, suppressed_sql_pattern, title_image
from service.admin.queries.members import member_sql
from service.campaigns import (held, make_campaign_link, suppressed_predicate_sql,
                               unsubscribed_predicate_sql)
from service.campaigns.switches import enabled
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.growth.queries import _excluded
from service.questions.copy import SAMPLE_QUESTION, in_sentence, short_question
from service.questions.schedule import barbados_today, current_drop, resting
from service.unsubscribe import make_url as unsub_url

CAMPAIGN = 'questions_launch'
CAMPAIGN_ID = 'questions_launch'
SWITCH = 'questions_launch_email'
UNSUB_SCOPE = 'campaigns'
FROM_ADDR = f"support@{EMAIL_DOMAIN}"
# The width the Claude Design export sets for the title (360 to 528 px).
TITLE_WIDTH = 460

SUBJECT = "New on Ahavah: quick questions"
CHIP = "New in the app"
BODY = ("Each week a light question now waits for you in the app. Answer it with one tap, "
        "and once 5 members have answered you can see how the answers split. On someone's "
        "profile, answer the same questions to see what they picked. When you match, you both "
        "get one question to answer, so your first message has somewhere to start.")
TAP_LINE = "Tap your answer. We'll save it once you're signed in."
ALSO_TITLE = "Also new on Ahavah"
# True while every member holds Premium; 14 lapse from 16 Dec (spec,
# decision 9), so the first line changes if the email goes later.
ALSO_NEW = ("See who liked you in Liked you, and like them back from their profile.",
            "Discover now keeps going past the first 10 profiles.",
            "A reminder when a match or a message is waiting for you.")


def preheader_for(question: dict) -> str:
    return f"This week's is {in_sentence(short_question(question).rstrip('?'))}. Tap your answer."


def _option_button(label: str, href: str) -> str:
    """The one place a label may wrap (brief, section 1): a long option
    grows the button taller rather than running off a phone screen."""
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 12px;">
      <tr><td align="center" bgcolor="{LIME}" style="border-radius:999px;">
        <a href="{href}" target="_blank" style="display:block;padding:16px 24px;font-family:{SANS};font-size:17px;font-weight:800;line-height:1.3;color:{INK};text-decoration:none;border-radius:999px;white-space:normal;">{escape(label)}</a>
      </td></tr>
    </table>"""


def launch_html(question: dict, links: list[tuple[str, str]], unsubscribe_url: str) -> str:
    buttons = ''.join(_option_button(label, href) for label, href in links)
    also = ''.join(held.para(f"&#8226;&nbsp; {line}", size=16, bottom=8) for line in ALSO_NEW)
    body = f"""
{chip(CHIP)}

{title_image("title-quick-questions.png", "title-quick-questions-wht.png", "Quick questions.", TITLE_WIDTH)}

{held.para(BODY)}

{held.para(f"This week: {escape(in_sentence(question['text']))}", bottom=16)}

{buttons}

{held.para(TAP_LINE, size=15, muted=True, bottom=28)}

<h2 class="e-h2" style="margin:0 0 10px;font-family:{SANS};font-size:19px;font-weight:800;color:{INK};">{ALSO_TITLE}</h2>
{also}
"""
    return render(title=SUBJECT, preheader=preheader_for(question), body_html=body,
                  footer_html=held.footer("You're receiving this because you're a member of Ahavah.",
                                          unsubscribe_url))


def _target(question: dict, choice_key: str) -> str:
    return f"{WEB_BASE_URL.rstrip('/')}/q/{question['key']}/{choice_key}"


_Q_DUE = f"""
    SELECT p.id AS person_id, p.email
      FROM person p
     WHERE p.activated AND p.deletion_requested_at IS NULL
       AND {member_sql('p')}
       AND lower(p.email) <> ALL(%(ex)s)
       AND NOT ({unsubscribed_predicate_sql(UNSUB_SCOPE, 'p.id')})
       AND NOT ({suppressed_predicate_sql('p.email')})
       AND NOT EXISTS (SELECT 1 FROM email_send_log l
                        WHERE l.person_id = p.id AND l.campaign = '{CAMPAIGN}')
     ORDER BY p.id
"""


def queue_due(tx, now: datetime) -> int:
    if not enabled(SWITCH) or now.hour < held.SEND_HOUR_UTC or resting(now):
        return 0
    drop = current_drop(tx, now)
    if drop is None or drop['live_on'] != barbados_today(now):
        return 0
    question = drop['question']
    n = 0
    for r in tx.execute(_Q_DUE, dict(ex=_excluded(), sup=suppressed_sql_pattern())).fetchall():
        pid = r['person_id']
        if held.already_queued(tx, CAMPAIGN, CAMPAIGN_ID, pid):
            continue
        links = [(o['label'], make_campaign_link(tx, CAMPAIGN, _target(question, o['key']), pid))
                 for o in question['options']]
        unsub = unsub_url(UNSUB_SCOPE, r['email'], WEB_BASE_URL)
        if held.queue(tx, campaign=CAMPAIGN, campaign_id=CAMPAIGN_ID, person_id=pid, email=r['email'],
                      subject=SUBJECT, html=launch_html(question, links, unsub), from_addr=FROM_ADDR,
                      unsub_scope=UNSUB_SCOPE, unsub_url=unsub) is not None:
            n += 1
    return n


def preview(to: str) -> tuple[str, str]:
    """The proof: week 1's question, buttons straight to the answer page,
    nothing stored."""
    q = SAMPLE_QUESTION
    return SUBJECT, launch_html(q, [(o['label'], _target(q, o['key'])) for o in q['options']],
                                unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))
```

In `service/campaigns/__init__.py`, replace:

```python
SELF_CAPPED_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                         'match_reminder', 'message_reminder', 'friend_joined',
                         'referral', 'spotlight_note')
```

with:

```python
SELF_CAPPED_CAMPAIGNS = ('likes_waiting', 'one_photo', 'profile_views',
                         'match_reminder', 'message_reminder', 'friend_joined',
                         'referral', 'spotlight_note', 'questions_launch')
```

and add to the comment above it: `The quick questions launch email (TEC-1845) goes to each member once ever, in the same way.`

In `service/cron/returnmail/__init__.py`, change the emails import to:

```python
from emails import likes_waiting_weekly, one_photo_nudge, profile_views_weekly, questions_launch, reminders
```

and add as the last entry of `JOBS`:

```python
    # The launch email (TEC-1845): once per member, on a drop day while its
    # switch is on.
    ('questions_launch_email', questions_launch.queue_due),
```

In `scripts/send_question_proofs.py`, replace `_emails`:

```python
def _emails() -> list[dict]:
    from emails import questions_launch, send_community_weekly
    builders = [
        ('e2_question_line', 'Weekly email with the question line',
         send_community_weekly.preview_question_line, send_community_weekly.FROM_ADDR),
        ('questions_launch', 'The launch email',
         questions_launch.preview, questions_launch.FROM_ADDR),
    ]
    out = []
    for name, label, build, from_addr in builders:
        subject, html = build(PROOF_TO)
        out.append(dict(name=name, label=label, subject=f"[PROOF] {subject}",
                        html=_inert(name, html), from_addr=from_addr))
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/test_questions_launch_email.py tests/test_send_question_proofs.py tests/test_email_templates_use_the_brand_shell.py tests/test_return_mail_cron.py tests/test_campaigns.py -q -p no:warnings`
Expected: all pass (8 new, 4 proof tests, the brand shell, return mail and campaign suites unchanged).

- [ ] **Step 6: Commit (both repos)**

```bash
cd /d/Antigravity/ahavah-web
git add public/email/title-quick-questions.png public/email/title-quick-questions-wht.png
git -c user.email=admin@techbaseltd.com commit -m "feat(email): the quick questions title image, from Claude Design" -m "Refs: TEC-1845"
cd /d/Antigravity/ahavah-api
git add emails/assets/title-quick-questions.png emails/assets/title-quick-questions-wht.png tests/email_assets_manifest.txt emails/questions_launch.py service/campaigns/__init__.py service/cron/returnmail/__init__.py scripts/send_question_proofs.py tests/test_send_question_proofs.py tests/test_questions_launch_email.py
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the launch email, one tap per option, once per member" -m "Refs: TEC-1845"
```

---

## Release 1 web (ahavah-web)

Tasks 15 to 22 wait for the revised Claude Design export of the brief `docs/design-briefs/2026-10-13-profile-prompts.md` (16 Oct): `Ahavah Quick Questions.html` with its copy file, retrieved with `/handoff`. Do not build from `Ahavah Profile Prompts.html` or `pages/p08-prompts.js`; they draw the previous brief. Each task's behaviour, data and tests are fixed here; its markup is written with the kit primitives below and then matched to the export's frames, screen by screen, with `/sot-sync "Claude Design/Ahavah Quick Questions.html" <screen>`, keeping every test green. Where the export changes a string, the export wins: change the constant in `src/lib/questions.ts` and its test together. Copy rules: brief, "Copy rules". Layout rules: brief, "Layout, for every frame in this brief" (390 first, 768, 1440; nothing scrolls sideways; option buttons stack and may wrap; 44 px targets).

### Task 15: The API client's PUT and the quick-questions library

Waits for: the revised export (for its strings).

**Files:**
- Modify: `src/lib/api-client.ts` (`request` method union, `apiClient`)
- Create: `src/lib/questions.ts`
- Test: `tests/lib/questions.test.ts` (create)

**Interfaces:**
- Consumes: the API shapes from Tasks 2 to 6.
- Produces, in `@/lib/questions`: types `QuestionFormat`, `QuestionOption`, `Question`, `SplitCount`, `QuestionState`, `CurrentQuestion`, `CurrentResponse`, `CatchUpResponse`, `MyAnswer`, `MyAnswersResponse`, `QuickAnswer`, `MatchQuestion`, `ConversationContext`, `PushSource`, `QuestionCardPick`; constants `QUICK_ANSWER_GOAL = 5`, `CARD_LABEL`, `CARD_FOOTER`, `UNDER_SPLIT_LINE`, `SAVE_FAILED`, `CATCH_UP_TITLE`, `CATCH_UP_DONE`, `CLOSED_LINE`; functions `inSentence`, `labelOf`, `splitLine`, `catchUpOfferLine`, `meterLabel`, `meterOnlyBody`, `chatLine`, `askWhyPrefill`, `pickQuestionCard`, `pushSourceOf`, `earlierAnswerLine`, `changeToLabel`, `keepLabel`, `parseQuickAnswers`, `saveAnswer(key, choiceKey, { keepExisting? }) -> Promise<QuestionState>`. `apiClient.put<T>(path, body?)`.

- [ ] **Step 1: Write the failing test**

Create `tests/lib/questions.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ put: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { put: api.put } };
});

import {
  askWhyPrefill,
  catchUpOfferLine,
  changeToLabel,
  chatLine,
  earlierAnswerLine,
  inSentence,
  keepLabel,
  meterLabel,
  meterOnlyBody,
  pickQuestionCard,
  pushSourceOf,
  saveAnswer,
  splitLine,
  type CurrentQuestion,
  type MatchQuestion,
  type Question,
} from "@/lib/questions";

const Q: Question = {
  key: "mountains-or-sea",
  text: "Would you rather wake up to mountains or the sea?",
  format: "either_or",
  options: [
    { key: "mountains", label: "Mountains" },
    { key: "sea", label: "The sea" },
  ],
};
const current = (my_choice: string | null): CurrentQuestion => ({
  live_on: "2026-11-15", question: Q, my_choice, counts: null,
});
const mq = (mine: string | null, theirs: string | null, they_answered = theirs !== null): MatchQuestion => ({
  question: Q, mine, theirs, they_answered,
});

describe("questions: copy", () => {
  it("sets an option inside a sentence", () => {
    expect(inSentence("The sea")).toBe("the sea");
    expect(inSentence("Mountains")).toBe("mountains");
  });

  it("shows the split as counts, never percentages", () => {
    expect(splitLine({ question: Q, my_choice: "sea", counts: [{ key: "mountains", n: 14 }, { key: "sea", n: 9 }] }))
      .toBe("14 picked Mountains, 9 picked The sea");
    expect(splitLine({ question: Q, my_choice: "sea", counts: null })).toBeNull();
  });

  it("offers the catch-up run in the singular for one question", () => {
    expect(catchUpOfferLine(14)).toBe("14 questions, one tap each.");
    expect(catchUpOfferLine(1)).toBe("1 question, one tap.");
  });

  it("caps the meter at 5", () => {
    expect(meterLabel(3)).toBe("3 of 5 quick answers");
    expect(meterLabel(9)).toBe("5 of 5 quick answers");
    expect(meterOnlyBody(1)).toBe("1 of 5 so far. They give a match something to ask you about.");
  });

  it("words the email answer page's choice", () => {
    expect(earlierAnswerLine("Mountains")).toBe("You answered mountains before.");
    expect(changeToLabel("The sea")).toBe("Change to the sea");
    expect(keepLabel("Mountains")).toBe("Keep mountains");
  });
});

describe("questions: the chat block", () => {
  it("says what each side is waiting for", () => {
    expect(chatLine(mq(null, null))).toBeNull();
    expect(chatLine(mq(null, null, true))).toBe("They've answered. Answer to see theirs.");
    expect(chatLine(mq("sea", null))).toBe("Your answer is in. You'll see theirs when they answer.");
    expect(chatLine(mq("sea", "mountains"))).toBe("You both answered. Ask why?");
    expect(chatLine(mq("sea", "sea"))).toBe("You both picked the sea.");
  });

  it("fills Ask why with both answers set inside the sentence", () => {
    expect(askWhyPrefill(mq("sea", "mountains"))).toBe("I picked the sea. What made you pick mountains?");
    expect(askWhyPrefill(mq("sea", "sea"))).toBe("We both picked the sea. What made you pick it?");
    expect(askWhyPrefill(mq("sea", null))).toBeNull();
  });
});

describe("questions: which card the slot shows", () => {
  const catchUp = { declined: false, questions: [Q, Q] };

  it("puts this week's unanswered question first", () => {
    expect(pickQuestionCard(current(null), catchUp)?.kind).toBe("weekly");
  });

  it("offers the catch-up run once this week's is answered", () => {
    expect(pickQuestionCard(current("sea"), catchUp)).toEqual({ kind: "catch-up", count: 2 });
  });

  it("keeps the answered card when the run was declined or is empty", () => {
    expect(pickQuestionCard(current("sea"), { declined: true, questions: [Q] })?.kind).toBe("weekly");
    expect(pickQuestionCard(null, { declined: false, questions: [] })).toBeNull();
  });
});

describe("questions: push sources and saving", () => {
  beforeEach(() => api.put.mockReset());

  it("reads only the 3 push sources", () => {
    expect(pushSourceOf("?src=qpush")).toBe("qpush");
    expect(pushSourceOf("?utm_source=x&src=lpush")).toBe("lpush");
    expect(pushSourceOf("?src=email")).toBeNull();
    expect(pushSourceOf("")).toBeNull();
  });

  it("saves through PUT /answers/{key}", async () => {
    api.put.mockResolvedValue({ question: Q, my_choice: "sea", counts: null });
    await saveAnswer("mountains-or-sea", "sea");
    expect(api.put).toHaveBeenCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: false });
    await saveAnswer("mountains-or-sea", "sea", { keepExisting: true });
    expect(api.put).toHaveBeenLastCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: true });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/questions.test.ts`
Expected: FAIL, `Failed to resolve import "@/lib/questions"`.

- [ ] **Step 3: Write the implementation**

In `src/lib/api-client.ts`, change the method union of `request` from `"GET" | "POST" | "PATCH" | "DELETE"` to `"GET" | "POST" | "PUT" | "PATCH" | "DELETE"`, and add to `apiClient`, after `post`:

```ts
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
```

Create `src/lib/questions.ts`:

```ts
/**
 * Quick questions, release 1 (TEC-1845): the API shapes, the copy and the
 * small pure rules every surface shares. Spec:
 * ahavah-api/docs/superpowers/specs/2026-10-13-profile-prompts-design.md
 * (revision of 16 Oct); screens: the revised Claude Design export of
 * docs/design-briefs/2026-10-13-profile-prompts.md.
 *
 * Copy is the brief's draft. Where the export changes a line, change it
 * here and in tests/lib/questions.test.ts together. Owner decision 1: the
 * question arrives on the first free day of each week, so no line names
 * Sunday.
 */
import { apiClient } from "@/lib/api-client";

export const QUICK_ANSWER_GOAL = 5;

export type QuestionFormat = "either_or" | "pick_one";
export type QuestionOption = { key: string; label: string };
export type Question = { key: string; text: string; format: QuestionFormat; options: QuestionOption[] };
export type SplitCount = { key: string; n: number };
/** `counts` is null under 5 answers and until the member has answered. */
export type QuestionState = { question: Question; my_choice: string | null; counts: SplitCount[] | null };
export type CurrentQuestion = QuestionState & { live_on: string };
export type CurrentResponse = { current: CurrentQuestion | null };
export type CatchUpResponse = { declined: boolean; questions: Question[] };
export type MyAnswer = { question: Question; choice_key: string };
export type MyAnswersResponse = { answers: MyAnswer[] };
/** A locked answer carries no choice: the server withholds it. */
export type QuickAnswer = { question: Question; locked: boolean; choice_key: string | null; shared: boolean };
/** `theirs` stays null until `mine` is set. */
export type MatchQuestion = { question: Question; mine: string | null; they_answered: boolean; theirs: string | null };
export type ConversationContext = { match_question: MatchQuestion | null };
export type PushSource = "qpush" | "mpush" | "lpush";
export type QuestionCardPick =
  | { kind: "weekly"; state: CurrentQuestion }
  | { kind: "catch-up"; count: number }
  | null;

export const CARD_LABEL = "Quick question";
export const CARD_FOOTER = "A new question each week";
export const UNDER_SPLIT_LINE = "Thanks. You'll see how members answered once 5 have.";
export const SAVE_FAILED = "We could not save that. Try again.";
export const CATCH_UP_TITLE = "Catch up on quick questions";
export const CATCH_UP_DONE = "All caught up. A new question arrives each week.";
export const CLOSED_LINE = "That question has closed. This week's is waiting on Discover.";

const PUSH_SOURCES: ReadonlyArray<PushSource> = ["qpush", "mpush", "lpush"];

/** Options read inside a sentence once the first letter is lower-cased. */
export function inSentence(label: string): string {
  return label.charAt(0).toLowerCase() + label.slice(1);
}

export function labelOf(question: Question, key: string | null): string | null {
  return question.options.find((o) => o.key === key)?.label ?? null;
}

export function splitLine(state: QuestionState): string | null {
  if (!state.counts) return null;
  return state.counts.map((c) => `${c.n} picked ${labelOf(state.question, c.key) ?? c.key}`).join(", ");
}

export function catchUpOfferLine(n: number): string {
  return n === 1 ? "1 question, one tap." : `${n} questions, one tap each.`;
}

export function meterLabel(n: number): string {
  return `${Math.min(n, QUICK_ANSWER_GOAL)} of ${QUICK_ANSWER_GOAL} quick answers`;
}

export function meterOnlyBody(n: number): string {
  return `${Math.min(n, QUICK_ANSWER_GOAL)} of ${QUICK_ANSWER_GOAL} so far. They give a match something to ask you about.`;
}

export function chatLine(q: MatchQuestion): string | null {
  if (q.mine === null) return q.they_answered ? "They've answered. Answer to see theirs." : null;
  if (q.theirs === null) return "Your answer is in. You'll see theirs when they answer.";
  if (q.mine === q.theirs) return `You both picked ${inSentence(labelOf(q.question, q.mine) ?? "")}.`;
  return "You both answered. Ask why?";
}

export function askWhyPrefill(q: MatchQuestion): string | null {
  const mine = labelOf(q.question, q.mine);
  const theirs = labelOf(q.question, q.theirs);
  if (!mine || !theirs) return null;
  if (q.mine === q.theirs) return `We both picked ${inSentence(mine)}. What made you pick it?`;
  return `I picked ${inSentence(mine)}. What made you pick ${inSentence(theirs)}?`;
}

/**
 * This week's unanswered question first; then the catch-up offer, unless
 * declined or empty; then this week's answered card, with its split.
 */
export function pickQuestionCard(current: CurrentQuestion | null, catchUp: CatchUpResponse | null): QuestionCardPick {
  if (current && current.my_choice === null) return { kind: "weekly", state: current };
  if (catchUp && !catchUp.declined && catchUp.questions.length > 0) {
    return { kind: "catch-up", count: catchUp.questions.length };
  }
  if (current) return { kind: "weekly", state: current };
  return null;
}

export function pushSourceOf(search: string): PushSource | null {
  const src = new URLSearchParams(search).get("src");
  return PUSH_SOURCES.includes(src as PushSource) ? (src as PushSource) : null;
}

export function earlierAnswerLine(label: string): string {
  return `You answered ${inSentence(label)} before.`;
}

export function changeToLabel(label: string): string {
  return `Change to ${inSentence(label)}`;
}

export function keepLabel(label: string): string {
  return `Keep ${inSentence(label)}`;
}

export function parseQuickAnswers(raw: unknown): QuickAnswer[] {
  return Array.isArray(raw) ? (raw as QuickAnswer[]) : [];
}

export function saveAnswer(
  key: string,
  choiceKey: string,
  opts: { keepExisting?: boolean } = {},
): Promise<QuestionState> {
  return apiClient.put<QuestionState>(`/answers/${encodeURIComponent(key)}`, {
    choice_key: choiceKey,
    keep_existing: opts.keepExisting ?? false,
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/questions.test.ts tests/lib/api-client-expired.test.ts`
Expected: PASS (12 new tests, the API client suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/api-client.ts src/lib/questions.ts tests/lib/questions.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the quick questions library and the API client's PUT" -m "Refs: TEC-1845"
```

---

### Task 16: The catch-up run

Waits for: the revised export, section 2 (the catch-up run; full screen below 768, a centred dialog at 768 and on desktop).

**Files:**
- Create: `src/components/app/catch-up-run.tsx`
- Test: `tests/components/catch-up-run.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /questions/catch-up`, `saveAnswer`, `CATCH_UP_DONE`, `SAVE_FAILED` (Task 15); the kit `Dialog`, `DialogContent`, `DialogTitle`, `Progress`, `Button`.
- Produces: `CatchUpRun({ open, onClose }: { open: boolean; onClose: () => void })`. Each tap saves on its own, so closing partway keeps what was answered.

- [ ] **Step 1: Write the failing test**

Create `tests/components/catch-up-run.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { get: api.get, put: api.put } };
});
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}));

import { CatchUpRun } from "@/components/app/catch-up-run";

const q = (key: string, text: string) => ({
  key, text, format: "either_or" as const,
  options: [{ key: "a", label: "Option A" }, { key: "b", label: "Option B" }],
});

describe("CatchUpRun", () => {
  beforeEach(() => {
    api.get.mockReset().mockResolvedValue({ declined: false, questions: [q("one", "First question?"), q("two", "Second question?")] });
    api.put.mockReset().mockResolvedValue({});
  });

  it("shows the progress and the first question, and a tap saves and moves on", async () => {
    render(<CatchUpRun open onClose={() => {}} />);
    expect(await screen.findByText("First question?")).toBeTruthy();
    expect(screen.getByText("1 of 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Option B" }));
    expect(await screen.findByText("Second question?")).toBeTruthy();
    expect(api.put).toHaveBeenCalledWith("/answers/one", { choice_key: "b", keep_existing: false });
    expect(screen.getByText("2 of 2")).toBeTruthy();
  });

  it("skips without saving", async () => {
    render(<CatchUpRun open onClose={() => {}} />);
    await screen.findByText("First question?");
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByText("Second question?")).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("keeps the card and says so when a save fails", async () => {
    api.put.mockRejectedValueOnce(new Error("offline"));
    render(<CatchUpRun open onClose={() => {}} />);
    await screen.findByText("First question?");
    fireEvent.click(screen.getByRole("button", { name: "Option A" }));
    expect((await screen.findByRole("alert")).textContent).toBe("We could not save that. Try again.");
    expect(screen.getByText("First question?")).toBeTruthy();
  });

  it("ends all caught up, and Back to Discover closes", async () => {
    const onClose = vi.fn();
    api.get.mockResolvedValue({ declined: false, questions: [q("one", "Only question?")] });
    render(<CatchUpRun open onClose={onClose} />);
    await screen.findByText("Only question?");
    fireEvent.click(screen.getByRole("button", { name: "Option A" }));
    expect(await screen.findByText("All caught up. A new question arrives each week.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back to Discover" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes partway, keeping what was answered", async () => {
    const onClose = vi.fn();
    render(<CatchUpRun open onClose={onClose} />);
    await screen.findByText("First question?");
    fireEvent.click(screen.getByRole("button", { name: "Option A" }));
    await screen.findByText("Second question?");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/catch-up-run.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/catch-up-run"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/app/catch-up-run.tsx`:

```tsx
"use client";

/**
 * The catch-up run (TEC-1845; brief section 2): every live question the
 * member has not answered, this week's left out, one tap card at a time.
 * Each tap saves on its own, so closing partway keeps what was answered.
 * A full screen below 768, a centred dialog at 768 and on desktop. Markup
 * matched to the revised Claude Design export.
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { apiClient } from "@/lib/api-client";
import {
  CARD_LABEL,
  CATCH_UP_DONE,
  SAVE_FAILED,
  saveAnswer,
  type CatchUpResponse,
  type Question,
} from "@/lib/questions";

export function CatchUpRun({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [index, setIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuestions(null);
    setIndex(0);
    setFailed(false);
    apiClient
      .get<CatchUpResponse>("/questions/catch-up")
      .then((r) => {
        if (alive) setQuestions(r?.questions ?? []);
      })
      .catch(() => {
        if (alive) setQuestions([]);
      });
    return () => {
      alive = false;
    };
  }, [open]);

  const total = questions?.length ?? 0;
  const done = questions !== null && index >= total;
  const current = questions && !done ? questions[index] : null;

  async function answer(choice: string) {
    if (!current || saving) return;
    setSaving(true);
    setFailed(false);
    try {
      await saveAnswer(current.key, choice);
      setIndex((i) => i + 1);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent className="flex h-dvh w-full max-w-none flex-col gap-5 rounded-none p-5 md:h-auto md:max-w-md md:rounded-[22px]">
        <div className="flex items-center justify-between gap-3">
          <DialogTitle className="text-overline text-(--ink-3)">{CARD_LABEL}</DialogTitle>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex size-11 items-center justify-center rounded-full text-(--ink-2)"
          >
            <X className="size-5" />
          </button>
        </div>

        {questions === null ? null : done ? (
          <div className="flex flex-col items-start gap-4">
            <p className="text-h2 text-(--ink)">{CATCH_UP_DONE}</p>
            <Button size="tap" className="rounded-full" onClick={onClose}>
              Back to Discover
            </Button>
          </div>
        ) : current ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Progress value={Math.round((index / total) * 100)} aria-label="Catch-up progress" />
              <p className="text-caption font-semibold text-(--ink-3)">
                {index + 1} of {total}
              </p>
            </div>
            <h2 className="text-h2 text-(--ink)">{current.text}</h2>
            <div className="flex flex-col gap-2">
              {current.options.map((o) => (
                <Button
                  key={o.key}
                  size="tap"
                  variant="outlineSubtle"
                  className="h-auto min-h-11 w-full whitespace-normal rounded-full py-2.5"
                  disabled={saving}
                  onClick={() => void answer(o.key)}
                >
                  {o.label}
                </Button>
              ))}
            </div>
            {failed ? (
              <p role="alert" className="text-caption text-red-500">
                {SAVE_FAILED}
              </p>
            ) : null}
            <button
              type="button"
              className="self-start text-meta font-bold text-(--link)"
              onClick={() => {
                setFailed(false);
                setIndex((i) => i + 1);
              }}
            >
              Skip
            </button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/catch-up-run.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" catch-up` and transcribe section 2's frames (offered, first card, mid run, skipped, last card, done, closed partway, save failed, 14 and 1 questions, dark and light, 390, 768, 1440 and the longest option at 320) onto this markup. Re-run Step 4; it must still pass.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/catch-up-run.tsx tests/components/catch-up-run.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the catch-up run, one tap card at a time" -m "Refs: TEC-1845"
```

---

### Task 17: The question card in the next-action slot

Waits for: the revised export, section 1 (the card in 3 states, as a row in "And {n} more", brought to the top).

**Files:**
- Modify: `src/lib/next-action.ts` (`NextActionKind`, `NEXT_ACTION_RANK`, `selectNextAction`)
- Modify: `src/lib/use-next-action.ts` (types, state, fetches, the quick-question entry, the result)
- Create: `src/components/app/question-card.tsx`
- Modify: `src/components/app/next-action.tsx` (`ROW_ICON`, `NextAction` props and body, selectable rows, an empty secondary action)
- Modify: `src/app/discover/page.tsx` (the card, the run)
- Test: `tests/lib/next-action.test.ts` (modify), `tests/components/question-card.test.tsx` (create), `tests/lib/use-next-action-questions.test.tsx` (create)

**Interfaces:**
- Consumes: Task 15's library; `CatchUpRun` (Task 16); `GET /questions/current`, `GET /questions/catch-up`, `POST /questions/catch-up/decline`.
- Produces: kind `"quick-question"` at rank 4.5; `selectNextAction(live, promote?: NextActionKind | null)`; `NextActionRowData.onSelect?: () => void`; `UseNextActionResult` gains `question: QuestionCardPick`, `declineCatchUp: () => Promise<void>`, `reload: () => void`; `NextAction` takes `custom?: ReactNode`; `QuestionCard({ pick, onStartCatchUp, onDeclineCatchUp })` and `WeeklyQuestion({ initial })` from `@/components/app/question-card`.

- [ ] **Step 1: Write the failing tests**

In `tests/lib/next-action.test.ts`, replace the expectation in `it("matches the SOT's 'Next-action priority order' board, plus profile-finish", ...)` with:

```ts
    expect(NEXT_ACTION_RANK).toEqual({
      "message-failed": 1,
      "new-match": 2,
      "profile-incomplete": 3,
      "verification-pending": 4,
      "quick-question": 4.5,
      "profile-finish": 5,
      "add-city": 6,
      "premium-upsell": 8,
    });
```

and append:

```ts
describe("next-action: the quick question (TEC-1845)", () => {
  it("ranks below verification-pending and above profile-finish", () => {
    const { primary, more } = selectNextAction([
      item("profile-finish"), item("quick-question"), item("verification-pending"),
    ]);
    expect(primary?.kind).toBe("verification-pending");
    expect(more.map((m) => m.kind)).toEqual(["quick-question", "profile-finish"]);
  });

  it("comes to the top for a visit when promoted, the rest in rank order", () => {
    const { primary, more } = selectNextAction(
      [item("new-match"), item("quick-question"), item("premium-upsell")],
      "quick-question",
    );
    expect(primary?.kind).toBe("quick-question");
    expect(more.map((m) => m.kind)).toEqual(["new-match", "premium-upsell"]);
  });

  it("changes nothing when the promoted kind is not live", () => {
    const { primary } = selectNextAction([item("new-match")], "quick-question");
    expect(primary?.kind).toBe("new-match");
  });
});
```

Create `tests/components/question-card.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ put: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { put: api.put } };
});

import { QuestionCard } from "@/components/app/question-card";

const Q = {
  key: "mountains-or-sea",
  text: "Would you rather wake up to mountains or the sea?",
  format: "either_or" as const,
  options: [{ key: "mountains", label: "Mountains" }, { key: "sea", label: "The sea" }],
};
const weekly = (my_choice: string | null, counts: { key: string; n: number }[] | null = null) => ({
  kind: "weekly" as const,
  state: { live_on: "2026-11-15", question: Q, my_choice, counts },
});

describe("QuestionCard", () => {
  beforeEach(() => api.put.mockReset());

  it("answers with one tap and thanks the member until 5 have answered", async () => {
    api.put.mockResolvedValue({ question: Q, my_choice: "sea", counts: null });
    render(<QuestionCard pick={weekly(null)} onStartCatchUp={() => {}} onDeclineCatchUp={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "The sea" }));
    expect(await screen.findByText("Thanks. You'll see how members answered once 5 have.")).toBeTruthy();
    expect(api.put).toHaveBeenCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: false });
    expect(screen.getByText("A new question each week")).toBeTruthy();
  });

  it("shows the split as counts once there are 5", () => {
    render(
      <QuestionCard
        pick={weekly("sea", [{ key: "mountains", n: 14 }, { key: "sea", n: 9 }])}
        onStartCatchUp={() => {}}
        onDeclineCatchUp={() => {}}
      />,
    );
    expect(screen.getByText("14 picked Mountains, 9 picked The sea")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("keeps the options and says so when a save fails", async () => {
    api.put.mockRejectedValue(new Error("offline"));
    render(<QuestionCard pick={weekly(null)} onStartCatchUp={() => {}} onDeclineCatchUp={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Mountains" }));
    expect((await screen.findByRole("alert")).textContent).toBe("We could not save that. Try again.");
    expect(screen.getByRole("button", { name: "The sea" })).toBeTruthy();
  });

  it("lets the member change an answer", () => {
    render(<QuestionCard pick={weekly("sea")} onStartCatchUp={() => {}} onDeclineCatchUp={() => {}} />);
    expect(screen.queryByRole("button", { name: "Mountains" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByRole("button", { name: "Mountains" })).toBeTruthy();
  });

  it("offers the catch-up run with Start and Not now", () => {
    const start = vi.fn();
    const decline = vi.fn();
    render(<QuestionCard pick={{ kind: "catch-up", count: 1 }} onStartCatchUp={start} onDeclineCatchUp={decline} />);
    expect(screen.getByText("Catch up on quick questions")).toBeTruthy();
    expect(screen.getByText("1 question, one tap.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(start).toHaveBeenCalled();
    expect(decline).toHaveBeenCalled();
  });
});
```

Create `tests/lib/use-next-action-questions.test.tsx`:

```tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { get: api.get, post: api.post } };
});
vi.mock("@/lib/chat-session", () => ({ readChatSession: () => null }));
vi.mock("@/lib/chat-cache", () => ({ getMostRecentFailedOutgoing: async () => null }));

import { useNextAction } from "@/lib/use-next-action";

const Q = {
  key: "mountains-or-sea", text: "Would you rather wake up to mountains or the sea?", format: "either_or",
  options: [{ key: "mountains", label: "Mountains" }, { key: "sea", label: "The sea" }],
};

function serve(current: unknown, catchUp: unknown = { declined: false, questions: [] }) {
  api.get.mockImplementation(async (path: string) => {
    if (path === "/matches") return { matches: [] };
    if (path === "/check-verification") return { status: "queued" };
    if (path === "/questions/current") return { current };
    if (path === "/questions/catch-up") return catchUp;
    if (path === "/answers") return { answers: [] };
    throw new Error(`unexpected ${path}`);
  });
}

const hook = () =>
  renderHook(() => useNextAction({ profile: {}, profileLoaded: true, onOpenDeck: () => {}, onStartCatchUp: () => {} }));

describe("useNextAction: the quick question", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset().mockResolvedValue({});
    window.history.replaceState({}, "", "/discover");
  });
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("shows below a higher card as a row that names the question", async () => {
    serve({ live_on: "2026-11-15", question: Q, my_choice: null, counts: null });
    const { result } = hook();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.primary?.kind).not.toBe("quick-question");
    const row = result.current.more.find((r) => r.kind === "quick-question");
    expect(row?.title).toBe("Quick question");
    expect(row?.subtitle).toBe(Q.text);
  });

  it("comes to the top when the visit came from a question push", async () => {
    window.history.replaceState({}, "", "/discover?src=qpush");
    serve({ live_on: "2026-11-15", question: Q, my_choice: null, counts: null });
    const { result } = hook();
    await waitFor(() => expect(result.current.primary?.kind).toBe("quick-question"));
    expect(result.current.question?.kind).toBe("weekly");
  });

  it("comes to the top when its row is tapped", async () => {
    serve({ live_on: "2026-11-15", question: Q, my_choice: null, counts: null });
    const { result } = hook();
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.more.find((r) => r.kind === "quick-question")?.onSelect?.());
    expect(result.current.primary?.kind).toBe("quick-question");
  });

  it("gives way to the catch-up offer once this week's is answered, and Not now holds", async () => {
    serve({ live_on: "2026-11-15", question: Q, my_choice: "sea", counts: null }, { declined: false, questions: [Q] });
    const { result } = hook();
    await waitFor(() => expect(result.current.question).toEqual({ kind: "catch-up", count: 1 }));
    await act(() => result.current.declineCatchUp());
    expect(api.post).toHaveBeenCalledWith("/questions/catch-up/decline");
    expect(result.current.question?.kind).toBe("weekly");
  });
});
```

Step 3 adds `onStartCatchUp` to the hook's input now, so this file passes it from the start; Task 18 is the first to use it (the meter).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/next-action.test.ts tests/components/question-card.test.tsx tests/lib/use-next-action-questions.test.tsx`
Expected: FAIL: the rank map lacks `quick-question`; `question-card` does not resolve; the hook returns no quick-question row.

- [ ] **Step 3: Write the implementation**

In `src/lib/next-action.ts`:

Add `| "quick-question"` to `NextActionKind`, after `| "verification-pending"`. In `NEXT_ACTION_RANK`, add after `"verification-pending": 4,`:

```ts
  // Quick questions (TEC-1845): below every real event and the blocking
  // profile card, above the soft profile-finish nudge. 4.5 so no other rank
  // moves and the SOT board still reads across.
  "quick-question": 4.5,
```

Replace `selectNextAction` with:

```ts
export function selectNextAction<T extends RankedItem>(
  live: ReadonlyArray<T>,
  promote: NextActionKind | null = null,
): { primary: T | null; more: T[] } {
  // `promote` brings one live kind to the top for this visit (a tapped row,
  // or a landing from a question push); the rest keep their rank order.
  const rank = (item: T) => (item.kind === promote ? 0 : NEXT_ACTION_RANK[item.kind]);
  const sorted = [...live].sort((a, b) => rank(a) - rank(b));
  const primary = sorted[0] ?? null;
  const more = sorted.slice(1);
  return { primary, more };
}
```

In `src/lib/use-next-action.ts`:

Change the React import to `import { useCallback, useEffect, useMemo, useState } from "react";` and add:

```ts
import {
  CARD_LABEL,
  CATCH_UP_TITLE,
  catchUpOfferLine,
  pickQuestionCard,
  pushSourceOf,
  type CatchUpResponse,
  type CurrentResponse,
  type QuestionCardPick,
} from "@/lib/questions";
```

Replace `NextActionRowData` with:

```ts
export type NextActionRowData = {
  kind: NextActionKind;
  title: string;
  subtitle: string;
  href: string;
  /** When set, the row is a button that acts in place instead of a link. */
  onSelect?: () => void;
};
```

Replace `UseNextActionResult` with:

```ts
export type UseNextActionResult = {
  primary: NextActionPrimaryData | null;
  more: NextActionRowData[];
  loading: boolean;
  /** The quick-question card's content when that kind is live. */
  question: QuestionCardPick;
  declineCatchUp: () => Promise<void>;
  /** Read every signal again (after the catch-up run closes). */
  reload: () => void;
};
```

Change the hook's input type to:

```ts
export function useNextAction(input: {
  profile: Partial<Profile>;
  profileLoaded: boolean;
  onOpenDeck: () => void;
  /** Opens the catch-up run; the meter on the profile-finish card uses it. */
  onStartCatchUp: () => void;
}): UseNextActionResult {
```

After `const [now, setNow] = useState<number | null>(null);`, add:

```ts
  // Quick questions (TEC-1845).
  const [current, setCurrent] = useState<CurrentResponse["current"]>(null);
  const [catchUp, setCatchUp] = useState<CatchUpResponse | null>(null);
  const [promoted, setPromoted] = useState<NextActionKind | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // A landing from the weekly or launch push shows the question first for
  // this visit (spec: /discover?src=qpush or ?src=lpush).
  useEffect(() => {
    const src = pushSourceOf(window.location.search);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (src === "qpush" || src === "lpush") setPromoted("quick-question");
  }, []);

  const declineCatchUp = useCallback(async () => {
    setCatchUp((c) => (c ? { ...c, declined: true } : c));
    try {
      await apiClient.post("/questions/catch-up/decline");
    } catch {
      // Offered again on the next visit; nothing else is lost.
    }
  }, []);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
```

In `run()`, replace the `Promise.allSettled` call and its first assignment with:

```ts
      const [matchesRes, verifyRes, failedRes, currentRes, catchUpRes] = await Promise.allSettled([
        apiClient.get<MatchesResponse>("/matches"),
        apiClient.get<{ status?: string | null }>("/check-verification"),
        session ? getMostRecentFailedOutgoing(session.myUuid) : Promise.resolve(null),
        apiClient.get<CurrentResponse>("/questions/current"),
        apiClient.get<CatchUpResponse>("/questions/catch-up"),
      ]);
      if (!alive) return;
      setCurrent(currentRes.status === "fulfilled" ? (currentRes.value?.current ?? null) : null);
      setCatchUp(catchUpRes.status === "fulfilled" ? (catchUpRes.value ?? null) : null);
```

keeping the existing `if (matchesRes.status === "fulfilled") { ... }` and the lines after it. Change that effect's dependency array from `[]` to `[reloadKey]`.

In the `useMemo`, change the loading return to:

```ts
      return { primary: null, more: [], loading: true, question: null, declineCatchUp, reload };
```

After the `// 4. verification-pending` block, add:

```ts
    // 4.5 quick-question (TEC-1845) ----------------------------------------
    // This week's unanswered question, else the catch-up offer, else this
    // week's answered card with its split (pickQuestionCard). The card's
    // body is QuestionCard, passed to NextAction as `custom`; the row brings
    // it to the top for this visit.
    const question = pickQuestionCard(current, catchUp);
    if (question) {
      const title = question.kind === "weekly" ? question.state.question.text : CATCH_UP_TITLE;
      live.push({
        kind: "quick-question",
        primary: {
          kind: "quick-question",
          tone: "calm",
          kicker: CARD_LABEL,
          title,
          primaryLabel: "",
          secondaryLabel: "",
        },
        row: {
          kind: "quick-question",
          title: CARD_LABEL,
          subtitle: question.kind === "weekly" ? question.state.question.text : catchUpOfferLine(question.count),
          href: "/discover",
          onSelect: () => setPromoted("quick-question"),
        },
      });
    }
```

Replace the end of the memo:

```ts
    const { primary, more } = selectNextAction(live);
    return {
      primary: primary?.primary ?? null,
      more: more.map((m) => m.row),
      loading: false,
    };
```

with:

```ts
    const { primary, more } = selectNextAction(live, promoted);
    return {
      primary: primary?.primary ?? null,
      more: more.map((m) => m.row),
      loading: false,
      question,
      declineCatchUp,
      reload,
    };
```

and add `current, catchUp, promoted, declineCatchUp, reload` to the memo's dependency array.

Create `src/components/app/question-card.tsx`:

```tsx
"use client";

/**
 * The quick-question card (TEC-1845; brief section 1) and the catch-up
 * offer that shares its slot (section 2). One tap answers; there is no
 * Save. The split shows as counts once 5 have answered. Options stack at
 * 390 and are the one place a label may wrap. Markup matched to the
 * revised Claude Design export.
 */
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  CARD_FOOTER,
  CATCH_UP_TITLE,
  SAVE_FAILED,
  UNDER_SPLIT_LINE,
  catchUpOfferLine,
  saveAnswer,
  splitLine,
  type QuestionCardPick,
  type QuestionState,
} from "@/lib/questions";
import { cn } from "@/lib/utils";

export function QuestionCard({
  pick,
  onStartCatchUp,
  onDeclineCatchUp,
}: {
  pick: NonNullable<QuestionCardPick>;
  onStartCatchUp: () => void;
  onDeclineCatchUp: () => void;
}) {
  if (pick.kind === "catch-up") {
    return <CatchUpOffer count={pick.count} onStart={onStartCatchUp} onDecline={onDeclineCatchUp} />;
  }
  return <WeeklyQuestion initial={pick.state} />;
}

export function WeeklyQuestion({ initial }: { initial: QuestionState }) {
  const [state, setState] = useState(initial);
  const [changing, setChanging] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const answered = state.my_choice !== null && !changing;

  async function pick(choice: string) {
    if (saving) return;
    setSaving(choice);
    setFailed(false);
    try {
      setState(await saveAnswer(state.question.key, choice));
      setChanging(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-h2 text-(--ink)">{state.question.text}</h2>
      {answered ? (
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-2">
            {state.question.options.map((o) => (
              <li
                key={o.key}
                aria-current={o.key === state.my_choice ? "true" : undefined}
                className={cn(
                  "rounded-full border border-(--hairline) px-4 py-2.5 text-meta font-semibold text-(--ink-2)",
                  o.key === state.my_choice && "border-lime text-(--ink)",
                )}
              >
                {o.label}
              </li>
            ))}
          </ul>
          <p className="text-caption text-(--ink-3)">{splitLine(state) ?? UNDER_SPLIT_LINE}</p>
          <button
            type="button"
            className="self-start text-meta font-bold text-(--link)"
            onClick={() => setChanging(true)}
          >
            Change
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2 md:flex-row md:flex-wrap">
          {state.question.options.map((o) => (
            <Button
              key={o.key}
              size="tap"
              variant="outlineSubtle"
              className="h-auto min-h-11 w-full whitespace-normal rounded-full py-2.5 md:w-auto"
              disabled={saving !== null}
              aria-busy={saving === o.key}
              onClick={() => void pick(o.key)}
            >
              {o.label}
            </Button>
          ))}
        </div>
      )}
      {failed ? (
        <p role="alert" className="text-caption text-red-500">
          {SAVE_FAILED}
        </p>
      ) : null}
      <p className="text-caption text-(--ink-3)">{CARD_FOOTER}</p>
    </div>
  );
}

function CatchUpOffer({ count, onStart, onDecline }: { count: number; onStart: () => void; onDecline: () => void }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-h2 text-(--ink)">{CATCH_UP_TITLE}</h2>
      <p className="text-meta leading-relaxed text-(--ink-2)">{catchUpOfferLine(count)}</p>
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2">
        <Button size="tap" className="rounded-full" onClick={onStart}>
          Start
        </Button>
        <button type="button" className="text-meta font-bold text-(--link) whitespace-nowrap" onClick={onDecline}>
          Not now
        </button>
      </div>
    </div>
  );
}
```

In `src/components/app/next-action.tsx`:

- Change `import type { CSSProperties } from "react";` to `import type { CSSProperties, ReactNode } from "react";`.
- Add `"quick-question": MessageCircle,` to `ROW_ICON`, after `"verification-pending": Clock,` (the export may name another icon; change it then).
- Change the `NextAction` props to take `custom`:

```tsx
export function NextAction({
  firstName,
  primary,
  more,
  custom,
}: {
  firstName?: string;
  primary: NextActionPrimaryData | null;
  more: ReadonlyArray<NextActionRowData>;
  /** Replaces the title, body and actions (the quick-question card). */
  custom?: ReactNode;
}) {
```

- Immediately before `{primary.avatars || primary.useIconTile ? (`, add `{custom ? custom : (<>`; immediately after the closing `</div>` of the actions row (the `<div className="mt-0.5 flex flex-wrap items-center gap-x-3.5 gap-y-2">` block), add `</>)}`.
- Replace the `<SecondaryAction ... />` element with:

```tsx
          {primary.secondaryLabel ? (
            <SecondaryAction
              label={primary.secondaryLabel}
              href={primary.secondaryHref}
              onClick={primary.onSecondary}
            />
          ) : null}
```

- In the "And {n} more" rows, replace the `<Link key={row.kind} href={row.href} prefetch={false} className="flex items-center gap-3 border-t border-(--hairline) py-2.5 first:border-t-0">` element and its matching `</Link>` with a row that is a button when `row.onSelect` is set:

```tsx
                  {more.map((row) => {
                    const RowIcon = ROW_ICON[row.kind];
                    const rowClass =
                      "flex w-full items-center gap-3 border-t border-(--hairline) py-2.5 text-left first:border-t-0";
                    const body = (
                      <>
                        <IconBadge tone="brand" shape="square" size="sm" className="shrink-0">
                          <RowIcon className="size-4" />
                        </IconBadge>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-meta font-semibold text-(--ink)">{row.title}</p>
                          <p className="truncate text-caption text-(--ink-3)">{row.subtitle}</p>
                        </div>
                        <ChevronRight className="size-4 shrink-0 text-(--ink-3)" />
                      </>
                    );
                    return row.onSelect ? (
                      <button key={row.kind} type="button" onClick={row.onSelect} className={rowClass}>
                        {body}
                      </button>
                    ) : (
                      <Link key={row.kind} href={row.href} prefetch={false} className={rowClass}>
                        {body}
                      </Link>
                    );
                  })}
```

In `src/app/discover/page.tsx`:

- Add imports:

```tsx
import { CatchUpRun } from "@/components/app/catch-up-run";
import { QuestionCard } from "@/components/app/question-card";
```

- Before the `useNextAction` call, add:

```tsx
  // Quick questions (TEC-1845): the catch-up run opens from the card's
  // Start, the meter and /discover?catchup=1 (the own profile's link).
  const [catchUpOpen, setCatchUpOpen] = useState(false);
  const openCatchUp = useCallback(() => setCatchUpOpen(true), []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (new URLSearchParams(window.location.search).get("catchup") === "1") setCatchUpOpen(true);
  }, []);
```

- Pass `onStartCatchUp: openCatchUp,` to `useNextAction({ ... })`.
- Replace the `<NextAction firstName={userProfile.firstName} primary={nextAction.primary} more={nextAction.more} />` element with:

```tsx
            <NextAction
              firstName={userProfile.firstName}
              primary={nextAction.primary}
              more={nextAction.more}
              custom={
                nextAction.primary.kind === "quick-question" && nextAction.question ? (
                  <QuestionCard
                    pick={nextAction.question}
                    onStartCatchUp={openCatchUp}
                    onDeclineCatchUp={() => void nextAction.declineCatchUp()}
                  />
                ) : undefined
              }
            />
```

- Immediately after the `{nextAction.primary ? ( ... ) : null}` block, add:

```tsx
        <CatchUpRun
          open={catchUpOpen}
          onClose={() => {
            setCatchUpOpen(false);
            nextAction.reload();
          }}
        />
```

`useState`, `useCallback` and `useEffect` are already imported in the page.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/next-action.test.ts tests/components/question-card.test.tsx tests/lib/use-next-action-questions.test.tsx tests/app/discover-page.test.tsx`
Expected: PASS (3 new and 1 changed in `next-action.test.ts`, 5 card tests, 4 hook tests, the Discover page suite unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" question-card` and transcribe section 1's frames (unanswered, saving, saved under 5, saved with the split, changing, save failed, either-or and pick-one, the longest question and option at 390 and 320, as a row, brought to the top, dark and light) onto `question-card.tsx` and the row. Check at 390 in the browser that nothing scrolls sideways. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/next-action.ts src/lib/use-next-action.ts src/components/app/question-card.tsx src/components/app/next-action.tsx src/app/discover/page.tsx tests/lib/next-action.test.ts tests/components/question-card.test.tsx tests/lib/use-next-action-questions.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the weekly question card in the next-action slot, and the catch-up offer" -m "Refs: TEC-1845"
```

---

### Task 18: The meter on the profile-finish card

Waits for: the revised export, section 4.

**Files:**
- Modify: `src/lib/next-action.ts` (`pickProfileCompletionCard`, a new `profileFinishCopy`)
- Modify: `src/lib/use-next-action.ts` (fetch `/answers`, the profile-finish entry)
- Modify: `src/components/app/next-action.tsx` (the meter line)
- Test: `tests/lib/next-action.test.ts` (append), `tests/components/next-action-meter.test.tsx` (create)

**Interfaces:**
- Consumes: `QUICK_ANSWER_GOAL`, `meterLabel`, `meterOnlyBody` (Task 15); `onStartCatchUp` (Task 17's hook input).
- Produces: `pickProfileCompletionCard({ eligible, stepsLeft, quickAnswers? })` (a member with no steps left but fewer than 5 answers keeps the soft card); `profileFinishCopy({ stepsLeft, quickAnswers }) -> { meterOnly, title, body, meter }`; `NextActionPrimaryData.meter?: { label: string; onClick: () => void }`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/next-action.test.ts` (and add `profileFinishCopy` to its import list):

```ts
describe("next-action: the quick answers meter (TEC-1845)", () => {
  it("keeps the soft card for a member with no steps left and fewer than 5 answers", () => {
    expect(pickProfileCompletionCard({ eligible: true, stepsLeft: 0, quickAnswers: 3 })).toBe("profile-finish");
    expect(pickProfileCompletionCard({ eligible: true, stepsLeft: 0, quickAnswers: 5 })).toBeNull();
  });

  it("never lets the answers make the blocking card", () => {
    expect(pickProfileCompletionCard({ eligible: false, stepsLeft: 0, quickAnswers: 0 })).toBe("profile-finish");
    expect(pickProfileCompletionCard({ eligible: false, stepsLeft: 2, quickAnswers: 0 })).toBe("profile-incomplete");
  });

  it("words the card with the meter alone", () => {
    expect(profileFinishCopy({ stepsLeft: 0, quickAnswers: 1 })).toEqual({
      meterOnly: true,
      title: "Add a few quick answers",
      body: "1 of 5 so far. They give a match something to ask you about.",
      meter: "1 of 5 quick answers",
    });
  });

  it("keeps the steps copy and adds the meter beside it, apart from the step count", () => {
    expect(profileFinishCopy({ stepsLeft: 2, quickAnswers: 3 })).toEqual({
      meterOnly: false,
      title: "2 steps left to finish your profile",
      body: "A more complete profile gets seen by more people.",
      meter: "3 of 5 quick answers",
    });
    expect(profileFinishCopy({ stepsLeft: 1, quickAnswers: 5 }).meter).toBeNull();
  });
});
```

Create `tests/components/next-action-meter.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { NextAction } from "@/components/app/next-action";

it("shows the meter on the profile-finish card and opens the catch-up run from it", () => {
  const onClick = vi.fn();
  render(
    <NextAction
      firstName="Ann"
      primary={{
        kind: "profile-finish", tone: "calm", kicker: "Finish your profile",
        title: "Add a few quick answers", body: "1 of 5 so far. They give a match something to ask you about.",
        primaryLabel: "Answer now", onPrimary: onClick, secondaryLabel: "",
        meter: { label: "1 of 5 quick answers", onClick },
      }}
      more={[]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "1 of 5 quick answers" }));
  expect(onClick).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("See all steps")).toBeNull();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/next-action.test.ts tests/components/next-action-meter.test.tsx`
Expected: FAIL: `profileFinishCopy` is not exported; `pickProfileCompletionCard` ignores `quickAnswers`; the meter button does not render.

- [ ] **Step 3: Write the implementation**

In `src/lib/next-action.ts`, add `import { QUICK_ANSWER_GOAL, meterLabel, meterOnlyBody } from "@/lib/questions";` and replace `pickProfileCompletionCard` with:

```ts
export function pickProfileCompletionCard(input: {
  eligible: boolean;
  stepsLeft: number;
  /** Quick answers given (TEC-1845). Left out, the card ignores them. */
  quickAnswers?: number;
}): Extract<NextActionKind, "profile-incomplete" | "profile-finish"> | null {
  const answersShort = (input.quickAnswers ?? QUICK_ANSWER_GOAL) < QUICK_ANSWER_GOAL;
  if (input.stepsLeft <= 0) return answersShort ? "profile-finish" : null;
  return input.eligible ? "profile-finish" : "profile-incomplete";
}

/**
 * The profile-finish card's words (TEC-1845, brief section 4). Quick
 * answers sit apart from the steps: they never count in "{n} steps left",
 * and the meter is its own line. With no step left the card stays for the
 * answers alone, with its own title, since "0 steps left" would be false.
 */
export function profileFinishCopy(input: { stepsLeft: number; quickAnswers: number }): {
  meterOnly: boolean;
  title: string;
  body: string;
  meter: string | null;
} {
  const meter = input.quickAnswers < QUICK_ANSWER_GOAL ? meterLabel(input.quickAnswers) : null;
  if (input.stepsLeft <= 0) {
    return { meterOnly: true, title: "Add a few quick answers", body: meterOnlyBody(input.quickAnswers), meter };
  }
  return {
    meterOnly: false,
    title:
      input.stepsLeft === 1
        ? "One more step to finish your profile"
        : `${input.stepsLeft} steps left to finish your profile`,
    body: "A more complete profile gets seen by more people.",
    meter,
  };
}
```

In `src/lib/use-next-action.ts`:

- Add `type MyAnswersResponse` and `QUICK_ANSWER_GOAL` to the `@/lib/questions` import, and `profileFinishCopy` to the `@/lib/next-action` import.
- Add to `NextActionPrimaryData`:

```ts
  /** The quick answers meter (TEC-1845), a line that opens the catch-up run. */
  meter?: { label: string; onClick: () => void };
```

- Destructure `onStartCatchUp` from `input` beside `onOpenDeck`.
- Add state `const [answersCount, setAnswersCount] = useState<number>(QUICK_ANSWER_GOAL);` beside the quick-question state.
- Add `apiClient.get<MyAnswersResponse>("/answers"),` as the last entry of the `Promise.allSettled` list, `answersRes` as the last name in its destructuring, and after `setCatchUp(...)`:

```ts
      // A failed read shows no meter rather than a wrong one.
      setAnswersCount(
        answersRes.status === "fulfilled" ? (answersRes.value?.answers?.length ?? QUICK_ANSWER_GOAL) : QUICK_ANSWER_GOAL,
      );
```

- Pass the answers to the card decision:

```ts
    const completionCard = pickProfileCompletionCard({
      eligible,
      stepsLeft: visibility.stepsLeft,
      quickAnswers: answersCount,
    });
```

- Replace the `else` branch that pushes the `profile-finish` entry with:

```ts
      } else {
        // Eligible, or every step done with fewer than 5 quick answers.
        const finish = profileFinishCopy({ stepsLeft: visibility.stepsLeft, quickAnswers: answersCount });
        live.push({
          kind: "profile-finish",
          primary: {
            kind: "profile-finish",
            tone: "calm",
            kicker: "Finish your profile",
            title: finish.title,
            body: finish.body,
            primaryLabel: finish.meterOnly ? "Answer now" : primaryLabel,
            primaryHref: finish.meterOnly ? undefined : editHref,
            onPrimary: finish.meterOnly ? onStartCatchUp : undefined,
            secondaryLabel: finish.meterOnly ? "" : "See all steps",
            secondaryHref: finish.meterOnly ? undefined : editHref,
            progress: finish.meterOnly ? undefined : progress,
            meter: finish.meter ? { label: finish.meter, onClick: onStartCatchUp } : undefined,
          },
          row: {
            kind: "profile-finish",
            title: "Finish your profile",
            subtitle: finish.meterOnly ? (finish.meter ?? progress.doneLabel) : progress.doneLabel,
            href: editHref,
          },
        });
      }
```

- Add `answersCount` and `onStartCatchUp` to the memo's dependency array.

In `src/components/app/next-action.tsx`, immediately after the `{primary.progress ? ( ... ) : null}` block, add:

```tsx
        {primary.meter ? (
          <button
            type="button"
            onClick={primary.meter.onClick}
            className="self-start text-caption font-semibold text-(--link)"
          >
            {primary.meter.label}
          </button>
        ) : null}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/lib/next-action.test.ts tests/components/next-action-meter.test.tsx tests/lib/use-next-action-questions.test.tsx`
Expected: PASS (4 new pure tests and every earlier one, the meter test, the hook tests). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" meter` and transcribe section 4's frames (0, 1, 3 and 5 of 5; with steps left and with none; dark and light). Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/next-action.ts src/lib/use-next-action.ts src/components/app/next-action.tsx tests/lib/next-action.test.ts tests/components/next-action-meter.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the quick answers meter on the profile-finish card" -m "Refs: TEC-1845"
```

---

### Task 19: Quick answers on profiles

Waits for: the revised export, section 3 (others' profiles with the locked state; the member's own view with Change).

**Files:**
- Create: `src/components/app/quick-answers.tsx`
- Modify: `src/app/profile/[uuid]/page.tsx` (`adaptProspect`, the fetched state's type, a refresh, the section after the bio in both layouts)
- Modify: `src/app/profile/page.tsx` (the own view)
- Test: `tests/components/quick-answers.test.tsx` (create)

**Interfaces:**
- Consumes: `quick_answers` on `/prospect-profile` (Task 4), `GET /answers` (Task 2), `saveAnswer`, `labelOf`, `parseQuickAnswers` (Task 15); `useIsDesktop`; kit `Sheet`, `SheetContent`, `SheetTitle`, `Popover`, `PopoverTrigger`, `PopoverContent`, `Button`.
- Produces: `QuickAnswers({ answers, onAnswered })`, `OwnQuickAnswers()`, constants `QUICK_ANSWERS_TITLE`, `LOCKED_LINE`, `SHARED_LINE`.

- [ ] **Step 1: Write the failing test**

Create `tests/components/quick-answers.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { get: api.get, put: api.put } };
});
vi.mock("@/lib/use-is-desktop", () => ({ useIsDesktop: () => false }));
vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ open, children }: { open: boolean; children: ReactNode }) => (open ? <div role="dialog">{children}</div> : null),
  SheetContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}));

import { OwnQuickAnswers, QuickAnswers } from "@/components/app/quick-answers";

const Q = (key: string, text: string) => ({
  key, text, format: "either_or" as const,
  options: [{ key: "a", label: "Mountains" }, { key: "b", label: "The sea" }],
});

describe("QuickAnswers on another member's profile", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
  });

  it("locks a question the viewer has not answered", () => {
    render(<QuickAnswers answers={[{ question: Q("one", "Mountains or the sea?"), locked: true, choice_key: null, shared: false }]} onAnswered={async () => {}} />);
    expect(screen.getByText("Quick answers")).toBeTruthy();
    expect(screen.getByText("Answer to see theirs")).toBeTruthy();
    expect(screen.queryByText("Mountains")).toBeNull();
  });

  it("marks an answer both members gave", () => {
    render(<QuickAnswers answers={[{ question: Q("one", "Mountains or the sea?"), locked: false, choice_key: "b", shared: true }]} onAnswered={async () => {}} />);
    expect(screen.getByText("The sea")).toBeTruthy();
    expect(screen.getByText("You both picked this")).toBeTruthy();
  });

  it("answering a locked chip saves and reveals theirs", async () => {
    api.put.mockResolvedValue({});
    const onAnswered = vi.fn(async () => {});
    render(<QuickAnswers answers={[{ question: Q("one", "Mountains or the sea?"), locked: true, choice_key: null, shared: false }]} onAnswered={onAnswered} />);
    fireEvent.click(screen.getByRole("button", { name: /Answer to see theirs/ }));
    fireEvent.click(await screen.findByRole("button", { name: "The sea" }));
    await waitFor(() => expect(onAnswered).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith("/answers/one", { choice_key: "b", keep_existing: false });
  });

  it("keeps the sheet open and says so when a save fails", async () => {
    api.put.mockRejectedValue(new Error("offline"));
    render(<QuickAnswers answers={[{ question: Q("one", "Mountains or the sea?"), locked: true, choice_key: null, shared: false }]} onAnswered={async () => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Answer to see theirs/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Mountains" }));
    expect((await screen.findByRole("alert")).textContent).toBe("We could not save that. Try again.");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("is absent when the member has no answers", () => {
    const { container } = render(<QuickAnswers answers={[]} onAnswered={async () => {}} />);
    expect(container.textContent).toBe("");
  });
});

describe("OwnQuickAnswers", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset();
  });

  it("offers the catch-up run when there are none yet", async () => {
    api.get.mockResolvedValue({ answers: [] });
    render(<OwnQuickAnswers />);
    expect(await screen.findByText("No quick answers yet")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Answer a few" }).getAttribute("href")).toBe("/discover?catchup=1");
  });

  it("changes an answer from the member's own profile", async () => {
    api.get.mockResolvedValue({ answers: [{ question: Q("one", "Mountains or the sea?"), choice_key: "a" }] });
    api.put.mockResolvedValue({ question: Q("one", "Mountains or the sea?"), my_choice: "b", counts: null });
    render(<OwnQuickAnswers />);
    expect(await screen.findByText("Mountains")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    fireEvent.click(await screen.findByRole("button", { name: "The sea" }));
    expect(await screen.findByText("The sea")).toBeTruthy();
    expect(api.put).toHaveBeenCalledWith("/answers/one", { choice_key: "b", keep_existing: false });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/quick-answers.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/quick-answers"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/app/quick-answers.tsx`:

```tsx
"use client";

/**
 * Quick answers on a profile (TEC-1845; brief section 3). Chips wrap and
 * never scroll sideways: the question small, the answer large. A question
 * the viewer has not answered is locked ("Answer to see theirs"); the
 * server withholds the choice, so answering reveals it on the next read.
 * A sheet below 768, a popover anchored to the chip at 768 and on desktop.
 * The member's own view changes an answer the same way. Markup matched to
 * the revised Claude Design export.
 */
import Link from "next/link";
import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { apiClient } from "@/lib/api-client";
import {
  SAVE_FAILED,
  labelOf,
  saveAnswer,
  type MyAnswer,
  type MyAnswersResponse,
  type Question,
  type QuickAnswer,
} from "@/lib/questions";
import { useIsDesktop } from "@/lib/use-is-desktop";

export const QUICK_ANSWERS_TITLE = "Quick answers";
export const LOCKED_LINE = "Answer to see theirs";
export const SHARED_LINE = "You both picked this";

const CHIP = "flex flex-col items-start gap-0.5 rounded-2xl border border-(--hairline) bg-(--card) px-3.5 py-2.5 text-left";

function Chooser({
  open,
  onOpenChange,
  trigger,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  title: string;
  children: ReactNode;
}) {
  const desktop = useIsDesktop();
  if (desktop) {
    return (
      <Popover open={open} onOpenChange={onOpenChange}>
        <PopoverTrigger render={trigger} />
        <PopoverContent className="w-72">{children}</PopoverContent>
      </Popover>
    );
  }
  return (
    <>
      {trigger}
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="bottom" className="gap-3 p-5">
          <SheetTitle>{title}</SheetTitle>
          {children}
        </SheetContent>
      </Sheet>
    </>
  );
}

function Options({ question, onPick }: { question: Question; onPick: (choice: string) => Promise<void> }) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  async function pick(choice: string) {
    setSaving(true);
    setFailed(false);
    try {
      await onPick(choice);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="flex flex-col gap-2">
      {question.options.map((o) => (
        <Button
          key={o.key}
          size="tap"
          variant="outlineSubtle"
          className="h-auto min-h-11 w-full whitespace-normal rounded-full py-2.5"
          disabled={saving}
          onClick={() => void pick(o.key)}
        >
          {o.label}
        </Button>
      ))}
      {failed ? (
        <p role="alert" className="text-caption text-red-500">
          {SAVE_FAILED}
        </p>
      ) : null}
    </div>
  );
}

function TheirChip({ item, onAnswered }: { item: QuickAnswer; onAnswered: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  if (!item.locked) {
    return (
      <div className={CHIP}>
        <span className="text-caption text-(--ink-3)">{item.question.text}</span>
        <span className="text-meta font-bold text-(--ink)">{labelOf(item.question, item.choice_key)}</span>
        {item.shared ? <span className="text-caption font-semibold text-lime">{SHARED_LINE}</span> : null}
      </div>
    );
  }
  const trigger = (
    <button type="button" className={CHIP} onClick={() => setOpen(true)}>
      <span className="text-caption text-(--ink-3)">{item.question.text}</span>
      <span className="text-meta font-bold text-(--ink)">{LOCKED_LINE}</span>
    </button>
  );
  return (
    <Chooser open={open} onOpenChange={setOpen} trigger={trigger} title={item.question.text}>
      <Options
        question={item.question}
        onPick={async (choice) => {
          await saveAnswer(item.question.key, choice);
          setOpen(false);
          await onAnswered();
        }}
      />
    </Chooser>
  );
}

export function QuickAnswers({ answers, onAnswered }: { answers: QuickAnswer[]; onAnswered: () => Promise<void> }) {
  if (answers.length === 0) return null;
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <h2 className="text-meta font-semibold uppercase text-(--ink-2)">{QUICK_ANSWERS_TITLE}</h2>
      <div className="flex flex-wrap gap-2">
        {answers.map((a) => (
          <TheirChip key={a.question.key} item={a} onAnswered={onAnswered} />
        ))}
      </div>
    </section>
  );
}

function OwnChip({ answer, onChanged }: { answer: MyAnswer; onChanged: (next: MyAnswer) => void }) {
  const [open, setOpen] = useState(false);
  const trigger = (
    <button type="button" className="self-start text-caption font-bold text-(--link)" onClick={() => setOpen(true)}>
      Change
    </button>
  );
  return (
    <div className={CHIP}>
      <span className="text-caption text-(--ink-3)">{answer.question.text}</span>
      <span className="text-meta font-bold text-(--ink)">{labelOf(answer.question, answer.choice_key)}</span>
      <Chooser open={open} onOpenChange={setOpen} trigger={trigger} title={answer.question.text}>
        <Options
          question={answer.question}
          onPick={async (choice) => {
            const state = await saveAnswer(answer.question.key, choice);
            setOpen(false);
            onChanged({ question: answer.question, choice_key: state.my_choice ?? choice });
          }}
        />
      </Chooser>
    </div>
  );
}

export function OwnQuickAnswers() {
  const [answers, setAnswers] = useState<MyAnswer[] | null>(null);
  useEffect(() => {
    let alive = true;
    apiClient
      .get<MyAnswersResponse>("/answers")
      .then((r) => {
        if (alive) setAnswers(r?.answers ?? []);
      })
      .catch(() => {
        if (alive) setAnswers(null);
      });
    return () => {
      alive = false;
    };
  }, []);
  if (answers === null) return null;
  return (
    <section className="flex flex-col gap-2 rounded-[18px] border border-(--hairline) bg-(--card) p-5">
      <h2 className="text-meta font-semibold text-(--ink)">{QUICK_ANSWERS_TITLE}</h2>
      {answers.length === 0 ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-caption text-(--ink-3)">No quick answers yet</p>
          <Link href="/discover?catchup=1" prefetch={false} className="text-meta font-bold text-(--link)">
            Answer a few
          </Link>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {answers.map((a) => (
            <OwnChip
              key={a.question.key}
              answer={a}
              onChanged={(next) =>
                setAnswers((list) => (list ?? []).map((x) => (x.question.key === next.question.key ? next : x)))
              }
            />
          ))}
        </div>
      )}
    </section>
  );
}
```

In `src/app/profile/[uuid]/page.tsx`:

- Add imports:

```tsx
import { QuickAnswers } from "@/components/app/quick-answers";
import { parseQuickAnswers, type QuickAnswer } from "@/lib/questions";
```

- Change the return type of `adaptProspect` from `Profile & { country?: string }` to `Profile & { country?: string; quickAnswers?: QuickAnswer[] }` and the cast at its end to the same type, then add inside its returned object, after `limited: raw.limited === true,`:

```tsx
    // Quick answers (TEC-1845): locked by the server until the viewer
    // answers; absent for signed-out viewers and hidden members.
    quickAnswers: parseQuickAnswers(raw.quick_answers),
```

- Change the fetched state to `useState<(Profile & { quickAnswers?: QuickAnswer[] }) | null>(null)`.
- After the `useEffect` that fetches the profile, add:

```tsx
  // After the viewer answers a locked question, read the answers again: the
  // server reveals theirs only now.
  const refreshQuickAnswers = useCallback(async () => {
    try {
      const raw = await apiClient.get<Record<string, unknown>>(`/prospect-profile/${uuid}`);
      setFetched((p) => (p ? { ...p, quickAnswers: parseQuickAnswers(raw.quick_answers) } : p));
    } catch {
      // The chip stays locked; the member can open the profile again.
    }
  }, [uuid]);
```

  and add `useCallback` to the page's React import if it is not there.
- In `bioContent`, immediately after the `{profile.bio && ( <p className="text-body leading-relaxed text-(--ink)/85">{profile.bio}</p> )}` block, and in the desktop column immediately after the `{profile.bio && ( <p className="m-0 text-base leading-relaxed ...">{profile.bio}</p> )}` block, add:

```tsx
      <QuickAnswers answers={profile.quickAnswers ?? []} onAnswered={refreshQuickAnswers} />
```

In `src/app/profile/page.tsx`, add `import { OwnQuickAnswers } from "@/components/app/quick-answers";` and replace:

```tsx
          ) : null}
        </div>

        {/* Right column: action rows + sign out */}
```

with:

```tsx
          ) : null}

          {/* Quick answers (TEC-1845): the only place a past week's answer
              can be read and changed. */}
          <OwnQuickAnswers />
        </div>

        {/* Right column: action rows + sign out */}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/quick-answers.test.tsx`
Expected: PASS (7 tests). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" quick-answers` and transcribe section 3's frames (1, 5 and 14 answers; all locked; mixed; several shared; a locked chip being answered; a matched profile; the own view with none, some and all; dark and light; the sheet at 390 and the popover at 768 and 1440). Check at 390 in the browser that the chips wrap and nothing scrolls sideways. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/quick-answers.tsx "src/app/profile/[uuid]/page.tsx" src/app/profile/page.tsx tests/components/quick-answers.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): Quick answers on profiles, answer to see theirs" -m "Refs: TEC-1845"
```

---

### Task 20: The shared question in the chat

Waits for: the revised export, section 5.

**Files:**
- Create: `src/components/app/chat-question-block.tsx`
- Modify: `src/components/app/chat-thread-view.tsx` (the message list)
- Test: `tests/components/chat-question-block.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /conversation-context/{uuid}` (Task 5); `chatLine`, `askWhyPrefill`, `labelOf`, `saveAnswer`, `SAVE_FAILED`, `CARD_LABEL` (Task 15); the thread's `handleDraftChange`.
- Produces: `ChatQuestionBlock({ prospectUuid, theirName, onAskWhy, fallback })`. While loading it renders nothing; with no question or a failed read it renders `fallback`.

- [ ] **Step 1: Write the failing test**

Create `tests/components/chat-question-block.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { get: api.get, put: api.put } };
});

import { ChatQuestionBlock } from "@/components/app/chat-question-block";

const UUID = "0b8a5c1e-1111-4222-8333-944455556666";
const Q = {
  key: "mountains-or-sea", text: "Would you rather wake up to mountains or the sea?", format: "either_or",
  options: [{ key: "mountains", label: "Mountains" }, { key: "sea", label: "The sea" }],
};
const ctx = (mine: string | null, theirs: string | null, they_answered = theirs !== null) => ({
  match_question: { question: Q, mine, theirs, they_answered },
});
const block = (onAskWhy = vi.fn()) =>
  render(<ChatQuestionBlock prospectUuid={UUID} theirName="Esther" onAskWhy={onAskWhy} fallback={<p>Say hello to start the conversation.</p>} />);

describe("ChatQuestionBlock", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.put.mockReset().mockResolvedValue({});
  });

  it("shows nothing while it loads", () => {
    api.get.mockReturnValue(new Promise(() => {}));
    const { container } = block();
    expect(container.textContent).toBe("");
  });

  it("asks the question when neither has answered, and answering reads it again", async () => {
    api.get.mockResolvedValueOnce(ctx(null, null)).mockResolvedValueOnce(ctx("sea", null));
    block();
    fireEvent.click(await screen.findByRole("button", { name: "The sea" }));
    expect(await screen.findByText("Your answer is in. You'll see theirs when they answer.")).toBeTruthy();
    expect(api.put).toHaveBeenCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: false });
    expect(api.get).toHaveBeenCalledWith(`/conversation-context/${UUID}`);
  });

  it("tells the member the other has answered", async () => {
    api.get.mockResolvedValue(ctx(null, null, true));
    block();
    expect(await screen.findByText("They've answered. Answer to see theirs.")).toBeTruthy();
  });

  it("shows both answers and fills the reply box from Ask why", async () => {
    api.get.mockResolvedValue(ctx("sea", "mountains"));
    const onAskWhy = vi.fn();
    block(onAskWhy);
    expect(await screen.findByText("You both answered. Ask why?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ask why?" }));
    expect(onAskWhy).toHaveBeenCalledWith("I picked the sea. What made you pick mountains?");
  });

  it("names a shared answer", async () => {
    api.get.mockResolvedValue(ctx("sea", "sea"));
    const onAskWhy = vi.fn();
    block(onAskWhy);
    expect(await screen.findByText("You both picked the sea.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ask why?" }));
    expect(onAskWhy).toHaveBeenCalledWith("We both picked the sea. What made you pick it?");
  });

  it("falls back to the existing line when there is no question", async () => {
    api.get.mockResolvedValue({ match_question: null });
    block();
    expect(await screen.findByText("Say hello to start the conversation.")).toBeTruthy();
  });

  it("hides and falls back when the read fails", async () => {
    api.get.mockRejectedValue(new Error("offline"));
    block();
    expect(await screen.findByText("Say hello to start the conversation.")).toBeTruthy();
  });

  it("says so and keeps the options when an answer fails to save", async () => {
    api.get.mockResolvedValue(ctx(null, null));
    api.put.mockRejectedValue(new Error("offline"));
    block();
    fireEvent.click(await screen.findByRole("button", { name: "Mountains" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("We could not save that. Try again."));
    expect(screen.getByRole("button", { name: "The sea" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/chat-question-block.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/chat-question-block"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/app/chat-question-block.tsx`:

```tsx
"use client";

/**
 * The shared question in a match's chat (TEC-1845; brief section 5). Both
 * members get the same question; each answers first, then sees the
 * other's. It sits as the first item in the history, above the messages,
 * and scrolls with them, so a member whose match wrote first still sees
 * it. "Ask why?" fills the reply box directly (the ?prefill= effect runs
 * only for links from outside the thread). Room is left above for the
 * introducer's note and beside it for the opening question (release 2).
 * Markup matched to the revised Claude Design export.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import {
  CARD_LABEL,
  SAVE_FAILED,
  askWhyPrefill,
  chatLine,
  labelOf,
  saveAnswer,
  type ConversationContext,
  type MatchQuestion,
} from "@/lib/questions";

export function ChatQuestionBlock({
  prospectUuid,
  theirName,
  onAskWhy,
  fallback,
}: {
  prospectUuid: string | null;
  theirName: string;
  onAskWhy: (text: string) => void;
  fallback: ReactNode;
}) {
  // undefined while loading; null when there is no question or the read failed.
  const [ctx, setCtx] = useState<MatchQuestion | null | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    if (!prospectUuid) {
      setCtx(null);
      return;
    }
    try {
      const r = await apiClient.get<ConversationContext>(`/conversation-context/${encodeURIComponent(prospectUuid)}`);
      setCtx(r?.match_question ?? null);
    } catch {
      setCtx(null);
    }
  }, [prospectUuid]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (ctx === undefined) return null;
  if (ctx === null) return <>{fallback}</>;

  const question = ctx.question;
  const line = chatLine(ctx);
  const prefill = askWhyPrefill(ctx);

  async function answer(choice: string) {
    if (saving) return;
    setSaving(true);
    setFailed(false);
    try {
      await saveAnswer(question.key, choice);
      await load();
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-label="Your shared question"
      className="flex flex-col gap-3 self-stretch rounded-[22px] border border-(--hairline) bg-(--card) p-4"
    >
      <p className="text-overline text-(--ink-3)">{CARD_LABEL}</p>
      <p className="text-h3 text-(--ink)">{question.text}</p>
      {ctx.mine === null ? (
        <div className="flex flex-col gap-2">
          {question.options.map((o) => (
            <Button
              key={o.key}
              size="tap"
              variant="outlineSubtle"
              className="h-auto min-h-11 w-full whitespace-normal rounded-full py-2.5"
              disabled={saving}
              onClick={() => void answer(o.key)}
            >
              {o.label}
            </Button>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-2xl bg-(--app) px-3 py-2">
            <p className="text-caption text-(--ink-3)">You</p>
            <p className="text-meta font-bold text-(--ink)">{labelOf(question, ctx.mine)}</p>
          </div>
          {ctx.theirs !== null ? (
            <div className="rounded-2xl bg-(--app) px-3 py-2">
              <p className="text-caption text-(--ink-3)">{theirName}</p>
              <p className="text-meta font-bold text-(--ink)">{labelOf(question, ctx.theirs)}</p>
            </div>
          ) : null}
        </div>
      )}
      {line ? <p className="text-meta text-(--ink-2)">{line}</p> : null}
      {prefill ? (
        <Button size="tap" variant="outlineSubtle" className="self-start rounded-full" onClick={() => onAskWhy(prefill)}>
          Ask why?
        </Button>
      ) : null}
      {failed ? (
        <p role="alert" className="text-caption text-red-500">
          {SAVE_FAILED}
        </p>
      ) : null}
    </section>
  );
}
```

In `src/components/app/chat-thread-view.tsx`, add `import { ChatQuestionBlock } from "@/components/app/chat-question-block";` and replace:

```tsx
        ) : !isHydrated ? null : messages.length === 0 ? (
          <p className="self-center text-meta text-(--ink-3)">
            Say hello to start the conversation.
          </p>
        ) : (
          messages.map((m) => (
```

with:

```tsx
        ) : !isHydrated ? null : (
          <>
          {/* The shared question (TEC-1845): first in the history, above
              the messages, scrolling with them. It takes the place of the
              hello line while the chat is empty, and gives it back when
              there is no question or it cannot be read. */}
          <ChatQuestionBlock
            prospectUuid={isUuidLike(id) ? id : null}
            theirName={subject.name}
            onAskWhy={(text) => handleDraftChange(text)}
            fallback={
              messages.length === 0 ? (
                <p className="self-center text-meta text-(--ink-3)">
                  Say hello to start the conversation.
                </p>
              ) : null
            }
          />
          {messages.map((m) => (
```

and replace:

```tsx
            </TextBubble>
          ))
        )}
        {theyAreTyping && <TypingIndicator avatar={subject.name[0]} />}
```

with:

```tsx
            </TextBubble>
          ))}
          </>
        )}
        {theyAreTyping && <TypingIndicator avatar={subject.name[0]} />}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/chat-question-block.test.tsx tests/lib/chat-recovery.test.ts`
Expected: PASS (8 new, the chat recovery suite unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" chat-block` and transcribe section 5's frames (the 4 states, matching answers, saving, failed, no question, loading, the other member wrote first, after messages from both, the reply box filled by Ask why, desktop split view, dark and light). At 390, check in the browser that the reply box stays above the keyboard and the block and the reply box both show without a scroll in an empty chat. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/chat-question-block.tsx src/components/app/chat-thread-view.tsx tests/components/chat-question-block.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the shared question at the top of a match's chat, with Ask why" -m "Refs: TEC-1845"
```

---

### Task 21: The settings row, the device's time zone and push taps

Waits for: the revised export, section 6.

**Files:**
- Modify: `src/lib/use-notification-preferences.ts` (`NotificationPreferences`, `DEFAULTS`)
- Modify: `src/app/settings/notifications/page.tsx` (`EVENTS`, `EMAIL_KEYS`, the email cell)
- Modify: `src/lib/use-push-subscription.ts` (`subscribeBody`, exported)
- Create: `src/lib/push-tap.ts`, `src/components/push-tap-capture.tsx`
- Modify: `src/app/layout.tsx` (mount the capture after `<FirstTouchCapture />`)
- Test: `tests/app/notifications-questions-row.test.tsx`, `tests/lib/push-tap.test.ts` (create)

**Interfaces:**
- Consumes: `push_questions` (Task 6), `POST /push-taps`, subscribe `tz` (Task 6); `pushSourceOf` (Task 15).
- Produces: a "Quick questions" row with a push switch and no email switch, left out of "Turn off all notification emails"; `subscribeBody(sub)` sends `tz`; `recordPushTap(search: string) -> Promise<boolean>`; `PushTapCapture`.

- [ ] **Step 1: Write the failing tests**

Create `tests/app/notifications-questions-row.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const prefs = vi.hoisted(() => ({ setOne: vi.fn(), refresh: vi.fn() }));
vi.mock("@/lib/use-require-session", () => ({ useRequireSession: () => {} }));
vi.mock("@/components/app/settings-shell", () => ({
  SettingsShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/lib/use-push-subscription", () => ({
  usePushSubscription: () => ({ state: "subscribed", syncCount: 0, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}));
vi.mock("@/lib/use-notification-preferences", () => ({
  useNotificationPreferences: () => ({
    state: {
      kind: "happy",
      savingKey: null,
      prefs: {
        push_matches: true, email_matches: true, push_messages: true, email_messages: true,
        push_likes: false, email_likes: false, push_verification: true, email_verification: true,
        push_profile_views: false, email_profile_views: false, push_weekly_digest: false, push_questions: true,
      },
    },
    setOne: prefs.setOne,
    refresh: prefs.refresh,
  }),
}));
vi.mock("@/components/ui/switch", () => ({
  Switch: ({ checked, onCheckedChange, "aria-label": label }: { checked: boolean; onCheckedChange?: (v: boolean) => void; "aria-label"?: string }) => (
    <button role="switch" aria-label={label} aria-checked={checked} onClick={() => onCheckedChange?.(!checked)} />
  ),
}));

import NotificationsSettingsPage from "@/app/settings/notifications/page";

beforeEach(() => prefs.setOne.mockReset().mockResolvedValue(undefined));

it("shows Quick questions with a push switch and no email switch", () => {
  render(<NotificationsSettingsPage />);
  expect(screen.getByText("Quick questions")).toBeTruthy();
  expect(screen.getByText("This week's question, and an easy first line for a quiet new match")).toBeTruthy();
  expect(screen.getByRole("switch", { name: "Push: Quick questions" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.queryByRole("switch", { name: "Email: Quick questions" })).toBeNull();
  expect(screen.getByText("Push only")).toBeTruthy();
  fireEvent.click(screen.getByRole("switch", { name: "Push: Quick questions" }));
  expect(prefs.setOne).toHaveBeenCalledWith("push_questions", false);
});

it("leaves quick questions out of turning off all notification emails", async () => {
  render(<NotificationsSettingsPage />);
  fireEvent.click(screen.getByRole("button", { name: /Turn off all notification emails/ }));
  await vi.waitFor(() => expect(prefs.setOne).toHaveBeenCalledTimes(5));
  expect(prefs.setOne.mock.calls.map((c) => c[0])).not.toContain("push_questions");
});
```

Create `tests/lib/push-tap.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ post: vi.fn(), token: "session-token" as string | null }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { post: api.post }, getSessionToken: () => api.token };
});

import { recordPushTap } from "@/lib/push-tap";
import { subscribeBody } from "@/lib/use-push-subscription";

describe("push taps", () => {
  beforeEach(() => {
    api.post.mockReset().mockResolvedValue(undefined);
    api.token = "session-token";
  });

  it("records a landing from a question push once", async () => {
    expect(await recordPushTap("?src=qpush")).toBe(true);
    expect(api.post).toHaveBeenCalledWith("/push-taps", { src: "qpush" });
  });

  it("records nothing for other links or a signed-out visitor", async () => {
    expect(await recordPushTap("?utm_source=facebook")).toBe(false);
    api.token = null;
    expect(await recordPushTap("?src=lpush")).toBe(false);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("never throws when the API is down", async () => {
    api.post.mockRejectedValue(new Error("offline"));
    expect(await recordPushTap("?src=mpush")).toBe(false);
  });
});

describe("the subscription carries the device's time zone", () => {
  it("adds tz to the subscribe body", () => {
    const sub = { toJSON: () => ({ endpoint: "https://push.example/1", keys: { p256dh: "k", auth: "a" } }) } as unknown as PushSubscription;
    expect(subscribeBody(sub)).toEqual({
      endpoint: "https://push.example/1",
      keys: { p256dh: "k", auth: "a" },
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/notifications-questions-row.test.tsx tests/lib/push-tap.test.ts`
Expected: FAIL: no "Quick questions" row, `@/lib/push-tap` does not resolve, and `subscribeBody` is not exported.

- [ ] **Step 3: Write the implementation**

In `src/lib/use-notification-preferences.ts`, add `push_questions: boolean;` to `NotificationPreferences` (after `email_profile_views`) and `push_questions: true,` to `DEFAULTS` (owner decision of 16 Oct: on by default).

In `src/app/settings/notifications/page.tsx`:

- Change the `EVENTS` element type to make `emailKey` optional:

```ts
const EVENTS: ReadonlyArray<{
  label: string;
  pushKey: PrefKey;
  /** Absent for a push-only row (Quick questions). */
  emailKey?: PrefKey;
  description: string;
}> = [
```

- Add as the last entry of `EVENTS`:

```ts
  {
    // TEC-1845: push only. The question line in Monday's email belongs to
    // that email, and its own unsubscribe governs it.
    label: "Quick questions",
    pushKey: "push_questions",
    description: "This week's question, and an easy first line for a quiet new match",
  },
```

- Replace `const EMAIL_KEYS: ReadonlyArray<PrefKey> = EVENTS.map((e) => e.emailKey);` and its comment with:

```ts
// The five email_* keys the bulk "turn off all" affordance clears. A
// push-only row has none, so it is left alone.
const EMAIL_KEYS: ReadonlyArray<PrefKey> = EVENTS.flatMap((e) => (e.emailKey ? [e.emailKey] : []));
```

- In the matrix, replace the two lines that compute `emailValue` and `savingEmail` with:

```tsx
              const emailKey = ev.emailKey;
              const emailValue = happy && emailKey ? happy.prefs[emailKey] : false;
              const savingEmail = emailKey ? happy?.savingKey === emailKey : false;
```

- Replace the email column's contents (the `{loading ? ( <Skeleton ... /> ) : ( <Switch ... aria-label={`Email: ${ev.label}`} /> )}` expression) with:

```tsx
                    {!emailKey ? (
                      <span className="text-center text-caption text-(--ink-3)">Push only</span>
                    ) : loading ? (
                      <Skeleton className="h-5 w-8 rounded-full" />
                    ) : (
                      <Switch
                        checked={emailValue}
                        disabled={!happy || savingEmail}
                        onCheckedChange={(next) => void prefs.setOne(emailKey, next)}
                        aria-label={`Email: ${ev.label}`}
                      />
                    )}
```

In `src/lib/use-push-subscription.ts`, replace `function subscribeBody(sub: PushSubscription) {` and its body with:

```ts
/** The device's IANA time zone, for 18:00 local question pushes and quiet
 *  hours (TEC-1845). Undefined where the browser cannot say; the API then
 *  uses US Eastern. */
function deviceTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** The body POST /notifications/subscribe takes, from a browser subscription. */
export function subscribeBody(sub: PushSubscription) {
  const json = sub.toJSON();
  // PushSubscription.toJSON() always populates endpoint + keys when
  // `userVisibleOnly: true`; the optional chains keep TS happy.
  return {
    endpoint: json.endpoint,
    keys: {
      p256dh: json.keys?.p256dh ?? "",
      auth: json.keys?.auth ?? "",
    },
    tz: deviceTimeZone(),
  };
}
```

Create `src/lib/push-tap.ts`:

```ts
/**
 * Push taps (TEC-1845). Nothing recorded a tap on a push before: sw.js
 * only opens the URL and first-touch reads only utm keys. The question
 * pushes land on ?src=qpush, mpush or lpush; a signed-in landing posts one
 * tap, which the API counts once per 10 minutes. Never throws.
 */
import { apiClient, getSessionToken } from "@/lib/api-client";
import { pushSourceOf } from "@/lib/questions";

export async function recordPushTap(search: string): Promise<boolean> {
  const src = pushSourceOf(search);
  if (!src || !getSessionToken()) return false;
  try {
    await apiClient.post("/push-taps", { src });
    return true;
  } catch {
    return false;
  }
}
```

Create `src/components/push-tap-capture.tsx`:

```tsx
"use client";

import { useEffect } from "react";

import { recordPushTap } from "@/lib/push-tap";

/** Posts a push tap for a landing from a question push. Renders nothing.
 *  Mounted once from RootLayout, beside FirstTouchCapture. */
export function PushTapCapture() {
  useEffect(() => {
    void recordPushTap(window.location.search);
  }, []);
  return null;
}
```

In `src/app/layout.tsx`, add `import { PushTapCapture } from "@/components/push-tap-capture";` and, immediately after `<FirstTouchCapture />`, add `<PushTapCapture />`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/notifications-questions-row.test.tsx tests/lib/push-tap.test.ts tests/app/notifications-settings.test.tsx tests/lib/use-notification-preferences.test.tsx tests/lib/use-push-subscription.test.tsx`
Expected: PASS (2 row tests, 4 tap and time zone tests, the three existing suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" settings-row` and transcribe section 6's frames (on, off, push not set up on this device, dark and light), with the empty email cell lined up with the other 5 rows. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/use-notification-preferences.ts src/app/settings/notifications/page.tsx src/lib/use-push-subscription.ts src/lib/push-tap.ts src/components/push-tap-capture.tsx src/app/layout.tsx tests/app/notifications-questions-row.test.tsx tests/lib/push-tap.test.ts
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the Quick questions push row, the device time zone and push taps" -m "Refs: TEC-1845"
```

---

### Task 22: The page an email answer lands on

Waits for: the revised export, section 9.

**Files:**
- Create: `src/components/app/q-answer-view.tsx`, `src/app/q/[key]/[choice]/page.tsx`
- Test: `tests/components/q-answer-view.test.tsx` (create)

**Interfaces:**
- Consumes: `PUT /answers/{key}` with `keep_existing` (Task 2); `saveAnswer`, `labelOf`, `earlierAnswerLine`, `changeToLabel`, `keepLabel`, `CLOSED_LINE`, `SAVE_FAILED` (Task 15); `WeeklyQuestion` (Task 17); `useRequireSession`, `getSessionToken`, `ApiError`.
- Produces: `/q/{key}/{choice}`. Signed out, it sends the member to sign-in and back here (`useRequireSession`); signed in, it saves without overwriting an earlier answer, then shows the card.

- [ ] **Step 1: Write the failing test**

Create `tests/components/q-answer-view.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const api = vi.hoisted(() => ({ put: vi.fn(), token: "session-token" as string | null }));
vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, apiClient: { put: api.put }, getSessionToken: () => api.token };
});

import { ApiError } from "@/lib/api-client";
import { QAnswerView } from "@/components/app/q-answer-view";

const Q = {
  key: "mountains-or-sea", text: "Would you rather wake up to mountains or the sea?", format: "either_or",
  options: [{ key: "mountains", label: "Mountains" }, { key: "sea", label: "The sea" }],
};

describe("the email answer page", () => {
  beforeEach(() => {
    api.put.mockReset();
    api.token = "session-token";
    router.replace.mockReset();
    window.history.replaceState({}, "", "/q/mountains-or-sea/sea");
  });

  it("saves the pick without overwriting and shows the saved card", async () => {
    api.put.mockResolvedValue({ question: Q, my_choice: "sea", counts: null });
    render(<QAnswerView questionKey="mountains-or-sea" choiceKey="sea" />);
    expect(await screen.findByText("Thanks. You'll see how members answered once 5 have.")).toBeTruthy();
    expect(api.put).toHaveBeenCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: true });
    expect(screen.getByRole("link", { name: "Go to Discover" }).getAttribute("href")).toBe("/discover");
  });

  it("offers to change or keep an earlier, different answer", async () => {
    api.put
      .mockResolvedValueOnce({ question: Q, my_choice: "mountains", counts: null })
      .mockResolvedValueOnce({ question: Q, my_choice: "sea", counts: null });
    render(<QAnswerView questionKey="mountains-or-sea" choiceKey="sea" />);
    expect(await screen.findByText("You answered mountains before.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Change to the sea" }));
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith("/answers/mountains-or-sea", { choice_key: "sea", keep_existing: false }));
  });

  it("keeps the earlier answer when asked", async () => {
    api.put.mockResolvedValue({ question: Q, my_choice: "mountains", counts: null });
    render(<QAnswerView questionKey="mountains-or-sea" choiceKey="sea" />);
    fireEvent.click(await screen.findByRole("button", { name: "Keep mountains" }));
    expect(await screen.findByRole("link", { name: "Go to Discover" })).toBeTruthy();
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it("says a closed question has closed and points to Discover", async () => {
    api.put.mockRejectedValue(new ApiError(404, { error: "closed" }));
    render(<QAnswerView questionKey="old-question" choiceKey="a" />);
    expect(await screen.findByText("That question has closed. This week's is waiting on Discover.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to Discover" })).toBeTruthy();
  });

  it("sends a signed-out member to sign in and back, saving nothing", async () => {
    api.token = null;
    render(<QAnswerView questionKey="mountains-or-sea" choiceKey="sea" />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/auth/sign-in?next=%2Fq%2Fmountains-or-sea%2Fsea"));
    expect(api.put).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/q-answer-view.test.tsx`
Expected: FAIL, `Failed to resolve import "@/components/app/q-answer-view"`.

- [ ] **Step 3: Write the implementation**

Create `src/components/app/q-answer-view.tsx`:

```tsx
"use client";

/**
 * Where an option button in the launch email lands (TEC-1845; brief
 * section 9): /q/{key}/{choice}. The click alone saves nothing (mail
 * scanners open links). A signed-out member signs in first and comes back
 * here; on an iPhone this is the main path, since a link in Mail opens in
 * Safari, apart from the installed app's sign-in. Signed in, the pick is
 * saved only if nothing is saved yet; an earlier, different answer is
 * offered "Change to {option}" or "Keep {earlier}". Markup matched to the
 * revised Claude Design export.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WeeklyQuestion } from "@/components/app/question-card";
import { ApiError, getSessionToken } from "@/lib/api-client";
import {
  CLOSED_LINE,
  SAVE_FAILED,
  changeToLabel,
  earlierAnswerLine,
  keepLabel,
  labelOf,
  saveAnswer,
  type QuestionState,
} from "@/lib/questions";
import { useRequireSession } from "@/lib/use-require-session";

type Phase = "saving" | "saved" | "closed" | "failed";

function ToDiscover() {
  return (
    <Button size="tap" className="self-start rounded-full" render={<Link href="/discover" prefetch={false} />}>
      Go to Discover
    </Button>
  );
}

export function QAnswerView({ questionKey, choiceKey }: { questionKey: string; choiceKey: string }) {
  useRequireSession();
  const signedIn = Boolean(getSessionToken());
  const [phase, setPhase] = useState<Phase>("saving");
  const [answer, setAnswer] = useState<QuestionState | null>(null);
  const [kept, setKept] = useState(false);

  const save = useCallback(
    async (keepExisting: boolean) => {
      setPhase("saving");
      try {
        setAnswer(await saveAnswer(questionKey, choiceKey, { keepExisting }));
        setPhase("saved");
      } catch (err) {
        setPhase(err instanceof ApiError && (err.status === 404 || err.status === 400) ? "closed" : "failed");
      }
    },
    [questionKey, choiceKey],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (signedIn) void save(true);
  }, [signedIn, save]);

  if (!signedIn) return null;
  if (phase === "closed") {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-h3 text-(--ink)">{CLOSED_LINE}</p>
        <ToDiscover />
      </div>
    );
  }
  if (phase === "failed") {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-meta text-red-500">
          {SAVE_FAILED}
        </p>
        <Button size="tap" className="self-start rounded-full" onClick={() => void save(true)}>
          Try again
        </Button>
      </div>
    );
  }
  if (phase === "saving" || !answer) return null;

  const earlier = labelOf(answer.question, answer.my_choice);
  const picked = labelOf(answer.question, choiceKey);
  if (!kept && answer.my_choice !== choiceKey && earlier && picked) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-h2 text-(--ink)">{answer.question.text}</h1>
        <p className="text-body text-(--ink-2)">{earlierAnswerLine(earlier)}</p>
        <div className="flex flex-col gap-2 md:flex-row">
          <Button size="tap" className="rounded-full" onClick={() => void save(false)}>
            {changeToLabel(picked)}
          </Button>
          <Button size="tap" variant="outlineSubtle" className="rounded-full" onClick={() => setKept(true)}>
            {keepLabel(earlier)}
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <WeeklyQuestion initial={answer} />
      <ToDiscover />
    </div>
  );
}
```

Create `src/app/q/[key]/[choice]/page.tsx`:

```tsx
"use client";

import { use } from "react";

import { QAnswerView } from "@/components/app/q-answer-view";

type Props = { params: Promise<{ key: string; choice: string }> };

/** /q/{key}/{choice}: the launch email's answer page (TEC-1845). */
export default function QuestionAnswerPage({ params }: Props) {
  const { key, choice } = use(params);
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-6 px-4 py-8">
      <QAnswerView questionKey={decodeURIComponent(key)} choiceKey={decodeURIComponent(choice)} />
    </main>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/components/q-answer-view.test.tsx tests/app/sign-in-next.test.tsx`
Expected: PASS (5 new, the sign-in return suite unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Match the export**

Run `/sot-sync "Claude Design/Ahavah Quick Questions.html" answer-page` and transcribe section 9's frames (signed out in Safari on an iPhone through sign-in to the saved card, signed out elsewhere, saving, saved under 5 and with the split, answered the same, answered differently, closed, failed; 390, 768 and 1440; dark and light). If the export draws a "pick held" screen before sign-in, see item 4 of "Spec conflicts and decisions needing the owner": it needs a public read of the question, which the spec does not list. Re-run Step 4.

- [ ] **Step 6: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/components/app/q-answer-view.tsx "src/app/q/[key]/[choice]/page.tsx" tests/components/q-answer-view.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "feat(questions): the page an email answer lands on, saved once signed in" -m "Refs: TEC-1845"
```

---

### Task 23: The privacy paragraph (held for the owner's wording)

Waits for: the owner's approval of the wording after the ux-writing pass. Ships before any quick-question switch goes on (spec, Privacy: "Before launch, the privacy page names quick answers and the stored time zone").

**Files:**
- Create: `src/lib/legal-questions-copy.ts`
- Modify: `src/app/privacy/page.tsx`, `src/app/legal/privacy/page.tsx` (a section after Spotlight)
- Test: `tests/app/legal-questions.test.tsx` (create)

**Interfaces:**
- Consumes: the `LegalCopy` shape from `src/lib/legal-spotlight-copy.ts`.
- Produces: `QUICK_ANSWERS_PRIVACY: LegalCopy` on both privacy pages.

- [ ] **Step 1: Write the failing test**

Create `tests/app/legal-questions.test.tsx`:

```tsx
import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn() }),
}));

import PrivacyPage from "@/app/legal/privacy/page";
import { QUICK_ANSWERS_PRIVACY } from "@/lib/legal-questions-copy";

it("names quick answers, who sees them and the stored time zone", () => {
  expect(QUICK_ANSWERS_PRIVACY.title).toBe("Quick answers");
  for (const words of ["Only signed-in members", "only after giving their own", "once 5 have answered",
    "time zone", "deleted with your account"]) {
    expect(QUICK_ANSWERS_PRIVACY.body).toContain(words);
  }
  expect(QUICK_ANSWERS_PRIVACY.body).not.toMatch(/\u2014/);
});

it("shows on the signed-in privacy page", () => {
  render(<PrivacyPage />);
  expect(screen.getAllByText(/time zone/).length).toBeGreaterThan(0);
});

it("is on the public privacy page too", () => {
  expect(readFileSync("src/app/privacy/page.tsx", "utf8")).toContain("QUICK_ANSWERS_PRIVACY");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-questions.test.tsx`
Expected: FAIL, `Failed to resolve import "@/lib/legal-questions-copy"`.

- [ ] **Step 3: Write the implementation**

Create `src/lib/legal-questions-copy.ts`:

```ts
/**
 * Quick answers on the privacy pages (TEC-1845; spec, Privacy). The public
 * /privacy and the signed-in /legal/privacy show the same paragraph; edit
 * it here, never in a page. Wording goes through the ux-writing pass and
 * the owner before it ships, and it ships before any quick-question switch
 * goes on.
 */
import type { LegalCopy } from "@/lib/legal-spotlight-copy";

export const QUICK_ANSWERS_PRIVACY: LegalCopy = {
  title: "Quick answers",
  body: "Quick answers are the options you tap on Ahavah's weekly questions. Only signed-in members see them, and a member sees your answer to a question only after giving their own. How members answered shows as counts, never names, and only once 5 have answered. When you turn on push, we also keep the time zone of that device, so a question arrives in your evening and never at night. Both are deleted with your account, and you can change an answer at any time on your profile.",
};
```

In `src/app/legal/privacy/page.tsx`, add `import { QUICK_ANSWERS_PRIVACY } from "@/lib/legal-questions-copy";` and, after the section:

```tsx
        {
          slug: "spotlight",
          heading: SPOTLIGHT_PRIVACY.title,
          body: SPOTLIGHT_PRIVACY.body,
        },
```

add:

```tsx
        {
          slug: "quick-answers",
          heading: QUICK_ANSWERS_PRIVACY.title,
          body: QUICK_ANSWERS_PRIVACY.body,
        },
```

In `src/app/privacy/page.tsx`, add the same import and, after:

```tsx
  {
    slug: "spotlight",
    heading: SPOTLIGHT_PRIVACY.title,
    body: SPOTLIGHT_PRIVACY.body,
  },
```

add:

```tsx
  {
    slug: "quick-answers",
    heading: QUICK_ANSWERS_PRIVACY.title,
    body: QUICK_ANSWERS_PRIVACY.body,
  },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /d/Antigravity/ahavah-web && npx vitest run tests/app/legal-questions.test.tsx tests/app/legal-spotlight.test.tsx`
Expected: PASS (3 new, the Spotlight legal suite unchanged).

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-web
git add src/lib/legal-questions-copy.ts src/app/privacy/page.tsx src/app/legal/privacy/page.tsx tests/app/legal-questions.test.tsx
git -c user.email=admin@techbaseltd.com commit -m "docs(privacy): name quick answers and the stored time zone" -m "Refs: TEC-1845"
```

---

## The launch, admin and follow-ups

### Task 24: Calendar entries with a target path, and the 4 launch posts (ahavah-admin)

The spec proposes that calendar entries gain a target path so the Facebook links land on `/discover` instead of the home page. The API already takes `target_path` on `/admin/growth/brand` (growth foundations, Task 9); this is the admin half, recorded as TEC-1895 (Backlog, Ahavah Admin). This task does the `target_path` part of that issue only.

**Files:**
- Modify: `src/lib/social-calendar.ts` (`CalendarEntry`, `calendarProblems`)
- Modify: `src/lib/social-queue.ts` (`queueDueBrandPosts`)
- Modify: `src/lib/growth-server.ts` (the `brand` entry type)
- Create: `src/lib/questions-launch.ts`, `scripts/questions-launch-entries.mjs`
- Test: `tests/questions-launch.test.mjs` (create), `tests/social-queue.test.mjs` (append)

**Interfaces:**
- Consumes: `isRestPeriod`, `isUnknown`, `highDayAt` from `src/lib/rest-days.ts`; `POST /admin/growth/brand` with `target_path`.
- Produces: `CalendarEntry.targetPath?: string`; `questionsLaunchEntries(launchDay: string, opts?: { thisWeek?: string; source?: string }) -> CalendarEntry[]`; `node scripts/questions-launch-entries.mjs YYYY-MM-DD ["window seat or aisle"]` prints them as JSON.

- [ ] **Step 1: Write the failing tests**

Create `tests/questions-launch.test.mjs`:

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
const launch = load('../src/lib/questions-launch.ts', { './rest-days': restDays });

const IDS = ['questions-launch-announce', 'questions-launch-how', 'questions-launch-would-you-rather',
  'questions-launch-this-week'];

test('four posts on days 0, 3, 9 and 11 from a free launch day', () => {
  const entries = plain(launch.questionsLaunchEntries('2026-10-20'));
  assert.deepEqual(entries.map((e) => e.id), IDS);
  assert.deepEqual(entries.map((e) => e.publishAt), ['2026-10-20T08:30:00-04:00', '2026-10-23T08:30:00-04:00',
    '2026-10-29T08:30:00-04:00', '2026-10-31T08:30:00-04:00']);
  for (const e of entries) {
    assert.equal(e.targetPath, '/discover');
    assert.equal(e.promotional, true);
    assert.deepEqual(e.channels, ['facebook', 'instagram']);
    assert.equal(e.image, `${e.id}.jpg`);
  }
});

test('a rest day moves a post to the next free day, as the spec counts it', () => {
  const entries = plain(launch.questionsLaunchEntries('2026-10-25'));
  assert.deepEqual(entries.map((e) => e.publishAt.slice(0, 10)),
    ['2026-10-27', '2026-10-28', '2026-11-03', '2026-11-05']);
});

test('a series that runs past the read calendar is refused', () => {
  assert.throws(() => launch.questionsLaunchEntries('2026-11-03'), /read the next month first/);
});

test("every post passes the calendar's own checks", () => {
  const entries = launch.questionsLaunchEntries('2026-10-20');
  assert.deepEqual(plain(calendar.calendarProblems(entries, () => true)), []);
});

test('captions name the app and carry no link, no link below and no Sunday', () => {
  for (const e of plain(launch.questionsLaunchEntries('2026-10-20', { thisWeek: 'window seat or aisle' }))) {
    assert.doesNotMatch(e.caption, /https?:\/\/|link below|Sunday|\u2014/i);
    assert.match(e.caption, /Ahavah app/);
  }
});

test('a target path must be a path on the web app', () => {
  const base = plain(launch.questionsLaunchEntries('2026-10-20'))[0];
  for (const bad of ['//evil.example', 'https://evil.example/', 'discover']) {
    const problems = plain(calendar.calendarProblems([{ ...base, targetPath: bad }], () => true));
    assert.ok(problems.some((p) => p.includes('targetPath')), bad);
  }
});
```

Append to `tests/social-queue.test.mjs`:

```js
test('an entry with a target path sends it to the brand route', async (t) => {
  const api = fakeApi();
  const queue = harness(t, api);
  await queue.queueDueBrandPosts({ calendar: [{ ...entry('with-path'), targetPath: '/discover' }], readImage, now: NOW });
  const brand = api.calls.find((c) => c.path === '/admin/growth/brand');
  assert.equal(brand.body.target_path, '/discover');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/questions-launch.test.mjs tests/social-queue.test.mjs`
Expected: FAIL: `questions-launch.ts` cannot be read (ENOENT); the new social-queue test fails on `undefined !== '/discover'`.

- [ ] **Step 3: Write the implementation**

In `src/lib/social-calendar.ts`, add to `CalendarEntry`, after `source: string;`:

```ts
  /** Where the post's Facebook link lands, a path on the web app such as
   *  /discover. Left out, the API sends it to the home page. Instagram
   *  carries no link either way. */
  targetPath?: string;
```

add after `const IMAGE_RE = ...`:

```ts
// The API's own rule for a post's target (valid_target_path).
const TARGET_PATH_RE = /^\/[A-Za-z0-9/_-]*$/;
```

and in `calendarProblems`, after the `pillar` check:

```ts
    if (e.targetPath !== undefined
        && (typeof e.targetPath !== 'string' || !TARGET_PATH_RE.test(e.targetPath) || e.targetPath.startsWith('//'))) {
      problems.push(`${name}: targetPath must be a path on the web app, such as /discover`);
    }
```

In `src/lib/growth-server.ts`, change the `brand` entry type to:

```ts
  brand: (entry: { slug: string; caption: string; scheduled_for: string; platforms: ('facebook' | 'instagram')[]; target_path?: string }) =>
```

In `src/lib/social-queue.ts`, replace the `growthApi.brand({ ... })` call with:

```ts
      const created = await growthApi.brand({
        slug: entry.id,
        caption: entry.caption,
        scheduled_for: entry.publishAt,
        platforms: entry.channels,
        // TEC-1895, the target path half: the post's Facebook link lands
        // where the entry says, not on the home page.
        ...(entry.targetPath ? { target_path: entry.targetPath } : {}),
      });
```

Create `src/lib/questions-launch.ts`:

```ts
/**
 * The 4 social posts that launch quick questions (TEC-1845; ahavah-api
 * spec docs/superpowers/specs/2026-10-13-profile-prompts-design.md,
 * "Launch", the social series). Days 0, 3, 9 and 11 from the launch day,
 * each moved to the next day the rest-day rules allow and never onto a
 * high day (they are promotional). A series that runs past the calendar's
 * last read date is refused: read the next month first.
 *
 * Captions are the spec's drafts in their "each week" versions (owner
 * decision 1), with no link: the API adds the tracking link on Facebook
 * and Instagram carries none. The entries go into
 * content/social-calendar.json only after the owner confirms them.
 */
import type { CalendarEntry, Pillar } from './social-calendar';
import { highDayAt, isRestPeriod, isUnknown } from './rest-days';

const SLOT = 'T08:30:00-04:00';

const POSTS: readonly { id: string; day: number; pillar: Pillar; caption: (thisWeek: string) => string }[] = [
  {
    id: 'questions-launch-announce', day: 0, pillar: 'C',
    caption: () => "Something new on Ahavah: quick questions. Each week a light question waits for you in the app, and you answer it with one tap. Answer the same questions as someone to see what they picked. When you match, you both get one question, so your first message has somewhere to start. Open the Ahavah app to answer this week's.",
  },
  {
    id: 'questions-launch-how', day: 3, pillar: 'C',
    caption: () => "How quick questions work.\n1. A new question arrives in the Ahavah app each week.\n2. Tap your answer. Once 5 members have answered, you can see how the answers split.\n3. On a profile, answer a question to see their answer. When you match, you both answer the same question, then see each other's.",
  },
  {
    id: 'questions-launch-would-you-rather', day: 9, pillar: 'F',
    caption: () => 'Would you rather spend a week in a cabin with no signal or a week exploring a city you have never seen? Tell us in the comments. There is a new question like this in the Ahavah app every week.',
  },
  {
    id: 'questions-launch-this-week', day: 11, pillar: 'C',
    caption: (thisWeek) => `This week's quick question is waiting in the Ahavah app: ${thisWeek}? One tap to answer, then see how members answered.`,
  },
];

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function questionsLaunchEntries(
  launchDay: string,
  opts: { thisWeek?: string; source?: string } = {},
): CalendarEntry[] {
  const thisWeek = opts.thisWeek ?? 'window seat or aisle';
  const source = opts.source ?? 'Ahavah Quick Questions.html, section 10, the 4 launch artworks.';
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
    out.push({
      id: post.id,
      publishAt: `${day}${SLOT}`,
      channels: ['facebook', 'instagram'],
      image: `${post.id}.jpg`,
      caption: post.caption(thisWeek),
      pillar: post.pillar,
      promotional: true,
      source,
      targetPath: '/discover',
      notes: `Quick questions launch, post ${i + 1} of 4, day ${post.day} from the launch day ${launchDay}. TEC-1845.`,
    });
    earliest = addDays(day, 1);
  });
  return out;
}
```

Create `scripts/questions-launch-entries.mjs`:

```js
// Prints the 4 quick questions launch posts for a launch day, as entries
// for content/social-calendar.json (TEC-1845). Nothing is written.
//   node scripts/questions-launch-entries.mjs 2026-11-17 "window seat or aisle"
// The second argument is week 2's question as caption 4 names it.
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

const [launchDay, thisWeek] = process.argv.slice(2);
if (!/^\d{4}-\d{2}-\d{2}$/.test(launchDay ?? '')) {
  console.error('usage: node scripts/questions-launch-entries.mjs YYYY-MM-DD ["window seat or aisle"]');
  process.exit(1);
}
const restDays = load('../src/lib/rest-days.ts');
const launch = load('../src/lib/questions-launch.ts', { './rest-days': restDays });
console.log(JSON.stringify(launch.questionsLaunchEntries(launchDay, thisWeek ? { thisWeek } : {}), null, 2));
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /d/Antigravity/ahavah-admin && node --test tests/questions-launch.test.mjs tests/social-queue.test.mjs tests/social-calendar.test.mjs tests/rest-days.test.mjs`
Expected: all pass (6 new, 1 new in the queue suite, the calendar and rest-day suites unchanged). Then `npx tsc --noEmit` reports no errors.

- [ ] **Step 5: Commit**

```bash
cd /d/Antigravity/ahavah-admin
git add src/lib/social-calendar.ts src/lib/social-queue.ts src/lib/growth-server.ts src/lib/questions-launch.ts scripts/questions-launch-entries.mjs tests/questions-launch.test.mjs tests/social-queue.test.mjs
git -c user.email=admin@techbaseltd.com commit -m "feat(growth): calendar entries carry a target path; the 4 quick questions launch posts" -m "The target path half of TEC-1895." -m "Refs: TEC-1845"
```

---

### Task 25: Admin > Questions screens become a Linear issue

The API for Admin > Questions is Task 13; the screens live in ahavah-admin and wait for the revised export's section 7. The repo's rule is that what remains becomes an issue.

**Files:**
- Modify: `docs/superpowers/plans/2026-10-16-quick-questions-release-1.md` (item 12 of "Spec conflicts and decisions needing the owner")

**Interfaces:**
- Consumes: Task 13's routes.
- Produces: one Linear issue in the Ahavah Admin project, its id recorded in item 12.

- [ ] **Step 1: Create the issue**

With the Linear tools (`mcp__linear-server__save_issue`): team `Techbase Solutions LLC`, project `Ahavah Admin`, label `Client: Ahavah`, state Backlog.

Title: `Questions tab: the bank, the 6-week schedule, answers, pushes and switches`

Description: `Follow-up to TEC-1845 (ahavah-api docs/superpowers/plans/2026-10-16-quick-questions-release-1.md, Task 13). Build Admin > Questions from section 7 of the revised Claude Design export of ahavah-web docs/design-briefs/2026-10-13-profile-prompts.md. The API is in place, admin session only: GET /admin/questions (bank with options, answers and counts split by sex; switch states); PATCH /admin/questions/<key> {active?, labels?: {option key: label}} (labels 1 to 40 characters; option keys never change; an open question cannot be switched on); GET /admin/questions/schedule (6 weeks: week_of, live_on, problem, prompt_key, text, approved, proposed_key); PUT and DELETE /admin/questions/schedule/<live_on> {prompt_key}; POST /admin/questions/schedule/approve {live_on: [...]}; GET /admin/questions/pushes (by question week: weekly_sent, launch_sent, match_question_sent, taps by source, switched_off, guard_rail at 2 or more switch-offs). The tab shows the switches and never flips them. Counts only, never who. Admin tables fold into cards at 390. Until this ships, the owner's schedule approval goes through the API with an admin session.`

Expected: one issue id in the Ahavah Admin project.

- [ ] **Step 2: Record the id**

In item 12 of "Spec conflicts and decisions needing the owner" at the end of this plan, replace the words `the id Task 25 returns` with the id from Step 1.

- [ ] **Step 3: Commit**

```bash
cd /d/Antigravity/ahavah-api
git add docs/superpowers/plans/2026-10-16-quick-questions-release-1.md
git -c user.email=admin@techbaseltd.com commit -m "docs(questions): the Admin > Questions screens are an issue" -m "Refs: TEC-1845"
```

---

### Task 26: The launch, in order, with every send proofed first

An operational task: no code. Each step names who acts. Nothing reaches members or social before the owner confirms the proof of it.

**Files:**
- Modify (ahavah-admin, Step 7 only): `content/social-calendar.json`; Add: `assets/social/questions-launch-announce.jpg`, `questions-launch-how.jpg`, `questions-launch-would-you-rather.jpg`, `questions-launch-this-week.jpg`

- [ ] **Step 1: Ship the backend with every switch off**

Merge Tasks 1 to 14 to `ahavah/main`; the push deploys through GitHub Actions and applies 0067. On the production database (reached however the operator normally reaches it; this plan did not read the droplet), check:

```sql
SELECT count(*) FILTER (WHERE active AND format <> 'text') AS live,
       count(*) FILTER (WHERE NOT active AND format = 'text') AS waiting
  FROM prompt_bank;
```

Expected: `live = 14`, `waiting = 20`. With an admin session, `GET /admin/questions` shows all 5 switches `false`.

- [ ] **Step 2: Ship the web**

Merge Tasks 15 to 22 to `master` (Vercel deploys it). Task 23 (privacy) merges once the owner has approved its wording, and before Step 5.

- [ ] **Step 3: The owner approves the schedule**

The launch day is the first free day after the screens ship (owner decision 6), and it is the first approved drop. Under the calendar as read on 16 Oct the drop days are 20 Oct, 27 Oct and 3 Nov; nothing after 9 Nov can be scheduled until the ninth month is read and both `service/spotlight/restdays.py` and `ahavah-admin/src/lib/rest-days.ts` are extended. Approve through Admin > Questions once it exists (Task 25), or with an admin session: `GET /admin/questions/schedule`, then `POST /admin/questions/schedule/approve` with the weeks' `live_on` dates.

- [ ] **Step 4: Proofs to the owner**

Inside the api container, as `scripts/send_proofs.py` is run: `python -m scripts.send_question_proofs` (dry run), then `python -m scripts.send_question_proofs --send`. The owner receives the launch email and the E2 with the question line at `harrigan.tennyson@gmail.com`, and the weekly, silent-match and launch pushes on account 18's devices. He checks: every line after the ux-writing pass; the launch email at 390 and 600, light and dark, including Gmail's forced dark mode; and the tag test (on iOS, the launch proof should replace the weekly one; if both stay, iOS does not replace by tag, and the silent-match push will not replace the match notification either).

- [ ] **Step 5: Switch on, after he confirms**

Set to `1`, in the production environment that `docker-compose.production.yml` reads, for both api and cron, then restart both: `AHAVAH_MATCH_QUESTION_PUSH_ENABLED`, `AHAVAH_QUESTION_PUSH_ENABLED`, `AHAVAH_E2_QUESTION_LINE_ENABLED` and, for launch week, `AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED` and `AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED`. Check `GET /admin/questions` shows each `true`. Do this before the launch day's 12:00 UTC.

- [ ] **Step 6: Launch day**

Nothing to run: the hourly return-mail cron queues the launch email from 12:00 UTC and the launch push from 18:00 each member's local time, then the weekly push in later weeks. Watch the cron log for `return_mail: {...}` lines naming `questions_launch_email` and `questions_launch_push`.

- [ ] **Step 7: The social series, after the owner approves it**

In ahavah-admin: `node scripts/questions-launch-entries.mjs <launch day> "<week 2's question, as caption 4 names it>"`. The owner approves the 4 captions. Put the 4 artworks from the export into `assets/social/`, append the printed entries to `content/social-calendar.json` and run `node --test tests/social-calendar.test.mjs`. Then commit:

```bash
cd /d/Antigravity/ahavah-admin
git add content/social-calendar.json assets/social/questions-launch-announce.jpg assets/social/questions-launch-how.jpg assets/social/questions-launch-would-you-rather.jpg assets/social/questions-launch-this-week.jpg
git -c user.email=admin@techbaseltd.com commit -m "content(social): the 4 quick questions launch posts" -m "Refs: TEC-1845"
```

Each post still waits in the Growth queue for his approval. Keep `DUO_CRON_QUESTION_OF_WEEK_ENABLED` at `0` for the 2 weeks of the series, so the feeds never carry 2 question posts in one week.

- [ ] **Step 8: After launch week**

Set `AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED` and `AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED` back to `0` and restart api and cron, once every time zone is past 21:00 on the launch day. Left on, each would reach later members on a later drop day.

- [ ] **Step 9: Each week**

Read `GET /admin/questions/pushes`. If `guard_rail` is true for a week (2 or more switch-offs), tell the owner: the spec's rule is to move to a fortnightly push. Read the answer counts in `GET /admin/questions` against the targets under the spec's Measurement (decision 7, not yet agreed). The launch email's clicks per option are not on Admin > Questions; read them on the production database:

```sql
SELECT l.target_url, count(c.*) FILTER (WHERE c.ua_class <> 'bot') AS clicks
  FROM campaign_link l
  LEFT JOIN campaign_click c ON c.link_key = l.key
 WHERE l.kind = 'questions_launch'
 GROUP BY l.target_url
 ORDER BY l.target_url;
```

Each `target_url` ends `/q/{question}/{option}`. Answers saved from those clicks cannot be told apart from answers given in the app; the week's answer counts are the nearest measure.

---

## Spec conflicts and decisions needing the owner

1. **No drop day past 9 Nov until the ninth month is read.** `restdays.py` holds every Sunday and Monday to 9 Nov as rest days and nothing after `KNOWN_THROUGH`. Drop days exist on 20 Oct, 27 Oct and 3 Nov only. Weekly drops after that and any launch series that runs past 9 Nov (the series spans 11 days or more) wait for the owner's ninth month in both rest-day files. This blocks scheduling, not building.
2. **Drop days on a Tuesday meet the Tuesday photo email.** Under the lunar rule the drop often falls on a Tuesday. `one_photo` is queued Tuesdays at 12:00 UTC, so with decision 12 the weekly push that evening is held by the gap for every member queued that email, and a weekly push held one week leaves that member none (the budget is 1 a week). The spec costed decision 12 for a Sunday push. The owner may prefer to move `one_photo` to another weekday.
3. **E2 is a `community` scope email in code**, not campaigns as the spec says (`UNSUB_SCOPE = 'community'` in `emails/send_community_weekly.py`). The question line therefore follows "Stop the weekly email". No change made.
4. **The "pick held" screen before sign-in.** The brief draws a signed-out member seeing their pick held, then signing in. Showing the question signed out needs a public read of a question, which the spec's API does not list. Task 22 sends the member straight to sign-in with the way back, as every email link does. If the export draws the held screen, a public `GET /questions/{key}` (question text and options only) is a small addition for the owner to approve.
5. **`question_drop.approved_at`** is added (the spec lists `prompt_key` and `live_on` only), so a proposed week is not live until he approves it.
6. **The launch email and push go on any approved drop day while their switches are on**, once per member ever. The spec ties them to the launch day; this way a late confirmation still launches on the next drop day. The runbook turns both off after launch week.
7. **Push copy.** "One tap, then see who picked the same" is kept verbatim; the spec itself asks the ux-writing pass to check it, since the card shows counts, not people. Push bodies use a short form built from the options ("Mountains or the sea?") rather than the full question, to fit a lock screen.
8. **The silent-match push window** is 24 hours to 7 days. A match whose first 24 hours ran into a rest period or a week whose push was spent gets its push later that window, or none.
9. **Release 2 remains blocked** by the Moderation > Text queue, as the spec says; nothing here starts it.
10. **Decision 7 (targets)** is still open. Admin > Questions shows the counts it would be read from.
11. **Decision 9 (launch copy)** is settled only through the proofs in Task 26. If the launch email goes after 16 Dec, the Liked you line changes (14 members' Premium lapses).
12. **Admin > Questions screens:** Linear issue the id Task 25 returns (Ahavah Admin, Backlog). Task 24 does the target path half of TEC-1895; the `kind` half of that issue stays open.
13. **Launch measurement.** Email clicks per option are counted by the existing `campaign_click` rows (query in Task 26 Step 9); an answer saved from a click cannot be told apart from one given in the app, so "the answers saved from them" (spec, Measurement) is read only as the week's answer counts. Facebook clicks per post come from the publishing queue's own tracking links, as for every post.
14. **Unverified:** that iOS replaces a notification by tag (the proof tests it); and the exact title image width and every string, which the export sets.

## Self-review

**Spec coverage.**

| Spec requirement (release 1 and launch) | Task |
|---|---|
| `prompt_bank.format`, `options`; 14 active, 20 inactive | 1 |
| `prompt_answer`, `question_drop`, `match_question`, `push_subscription.tz`, `push_questions` and `_off_at`, `push_tap`, `person.question_catchup_declined_at` | 1 |
| `PUT /answers/{key}`, `GET /answers`; split from 5, counts | 2 |
| Weekly drop by the lunar rule (decision 1); `GET /questions/current`, `GET /questions/catch-up`, `POST .../decline`; catch-up offers every active question (decision 10) | 3 |
| `/prospect-profile` `quick_answers`, answer to see theirs enforced on the server; never signed out or limited | 4 |
| `GET /conversation-context/{uuid}`; one question per match, neither answered first | 5 |
| Push kind `questions`, never emailed, default on (decision 11); off stamp for the guard rail; time zone; `POST /push-taps` | 6 |
| 5 switches off by default, pass-throughs in api and cron | 7 |
| Question pushes in `_GAP_CAMPAIGNS`, gap reads `push_send_log` (decision 12), cost tested | 8 |
| Silent-match push to both (decision 3), weekly push at 18:00 local, 1 a week, silent match first, quiet hours, rest days, stop after 2, no campaign leavers, `send_to_user_safe`, the `_log_push` and `after_commit` pattern, tags, `?src=`; a match that gets both the question push and the 3-day reminder | 9 |
| Launch push as launch week's question push, `?src=lpush` | 10 |
| E2 line behind `e2_question_line`, left out after the launch email | 11 |
| Proofs to the owner only | 12, 14 |
| Admin endpoints for Admin > Questions (bank, options, schedule, counts by sex, pushes, taps, switch-offs, switches) | 13 |
| Launch email: audience, once ever, `SELF_CAPPED_CAMPAIGNS`, exempt, brand shell, title image, per-option campaign links to `/q/{key}/{choice}` | 14 |
| The card in 3 states, as a row, rank between 4 and 5, promoted by a row tap or `?src=` | 17 |
| The catch-up run, declined server side | 16, 17 |
| Quick answers, locked, shared, own view with Change | 19 |
| The meter, apart from steps, the card with the meter alone | 18 |
| The chat block above messages, Ask why filling the box directly | 20 |
| Settings row push only, out of "turn off all emails"; time zone saved at subscribe; push taps | 21 |
| `/q/{key}/{choice}`: saved only signed in, never overwriting, change or keep, closed | 22 |
| Privacy page names quick answers and the time zone | 23 |
| 4 social posts through the calendar, no Instagram links, target path `/discover`, rest days | 24, 26 |
| Admin > Questions screens | 25 (issue) |
| Proofs before switches, launch order, question of the week off for 2 weeks | 26 |

Not in release 1 by the spec: written answers, likes with a comment, the opening question, the same-answer chip on Discover (release 2).

**Placeholder scan.** Searched for "TBD", "TODO", "implement later", "fill in", "similar to Task", "add appropriate" and steps without code: none. Two values are set by the export by design and named as such: the title image width (`TITLE_WIDTH`, Task 14 Step 1) and the web markup, matched with `/sot-sync` in each web task after its tests are green. The Linear id in item 12 is filled by Task 25.

**Type consistency.** Checked across tasks: `question_json` shape `{key, text, format, options: [{key, label}]}` (Tasks 2 to 5, 9, 13, web `Question`); `question_state` `{question, my_choice, counts}` (Tasks 2, 3, web `QuestionState`); `current_for` returns `current` with `live_on` (Task 3, web `CurrentResponse`); `catch_up_for` `{declined, questions}` (Task 3, web `CatchUpResponse`); `quick_answers_for` items `{question, locked, choice_key, shared}` (Task 4, web `QuickAnswer`); `conversation_context` `{match_question: {question, mine, they_answered, theirs}}` (Task 5, web `MatchQuestion`); `current_drop` `{live_on: date, question}` used by Tasks 9 to 11 and 14; `week_starts_at`, `resting`, `barbados_today` defined in Task 3 and used in 9 to 14; `ensure_match_question(tx, match_id: str, a_id, b_id)` (Tasks 5, 9); `_push(person_id, title, body, url, tag)` and `PUSH_READY` patched by the `pushed_questions` fixture (Tasks 9, 10); `copy.weekly_push(live_on: str, question)` and `launch_push` (Tasks 9, 10, 12); `push_send_log` keys `question/{live_on}`, `match_question/{match_id}`, `questions_launch/launch` (Tasks 9, 10, 13); switch names identical in Tasks 7, 9 to 14 and the `SWITCH_NAMES` of Task 13; `PUT /answers` body `{choice_key, keep_existing}` (Task 2, web `saveAnswer`); `selectNextAction(live, promote)` and rank `4.5` (Task 17); `onStartCatchUp` on the hook input (added in Task 17, used in Task 18); `pickProfileCompletionCard` with optional `quickAnswers` (Task 18); `WeeklyQuestion` exported in Task 17 and used in Task 22; `subscribeBody` exported in Task 21. The test counts in each run step match the tests written in that task: 13, 7, 12, 5, 5, 8, 6, 5, 18, 6, 6, 4, 9, 8 (API); 12, 5, 3 plus 5 plus 4, 4 plus 1, 7, 8, 2 plus 4, 5, 3 (web); 6 plus 1 (admin).

**Review Focus.** Each of the five lines names a test that is written out in its task: Task 6 `test_a_bad_or_missing_time_zone_is_stored_as_none`, Task 9 `test_a_member_with_no_time_zone_is_pushed_at_18_eastern`, Task 2 `test_a_closed_or_unknown_question_is_refused` and `test_keep_existing_never_overwrites`, Task 4 `test_an_answer_to_a_question_switched_off_is_not_shown`, Task 13 `test_a_label_edit_keeps_every_answer`, Task 6 `test_a_push_tap_is_recorded_once_per_10_minutes`, Task 5 `test_a_match_with_a_deactivated_member_has_no_context`, Task 9 `test_no_silent_match_push_when_the_other_member_is_deactivated`, Task 3 `test_the_eve_of_a_rest_day_is_not_a_drop_day`, Task 9 `test_nothing_goes_in_a_rest_period`.
