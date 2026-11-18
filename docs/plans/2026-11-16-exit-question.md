Linear: TEC-2158

# Exit question when a member deletes their account

Owner, 16 Nov 2026: plan, review, build and deploy an in-app exit questionnaire for members who delete.

## What the member sees

Settings > Account > Delete account opens the same box as today. Between the explanation and the buttons there is one optional question.

- Label: `Why are you leaving? (optional)`
- One-tap answers, pick one, tap again to clear:
  - `I met someone on Ahavah` (code `met_here`)
  - `I met someone elsewhere` (code `met_elsewhere`)
  - `Not enough people near me` (code `few_people`)
  - `Not what I expected` (code `not_expected`)
  - `Taking a break` (code `break`)
  - `Something else` (code `other`)
- A note field, shown for every answer once one is picked: placeholder `Anything you want us to know (optional)`, 300 characters at most, counter shown from 250.
- Helper line under the question: `Your answer is kept without your name or email.`
- Buttons unchanged: `Cancel` and `Delete forever`. Delete works with no answer.
- Layout: the answers are a wrapping row of pills at 390, 800 and 1440; no sideways scroll at 320. The box scrolls inside itself if the keyboard covers it.

The design goes on the existing canvas (artifact d3a03415, page "Ahavah Deletion and Organiser Emails") before the web build, and the build follows it.

## Server (ahavah-api)

Migration `0100_exit_answer.sql`:

```sql
CREATE TABLE IF NOT EXISTS exit_answer (
  id          BIGSERIAL PRIMARY KEY,
  person_id   INT REFERENCES person(id) ON DELETE SET NULL,
  reason      TEXT NOT NULL CHECK (reason IN
              ('met_here','met_elsewhere','few_people','not_expected','break','other')),
  note        TEXT CHECK (note IS NULL OR char_length(note) <= 300),
  gender      TEXT,
  member_days INT,
  had_premium BOOLEAN,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  kept_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS exit_answer_created_idx ON exit_answer (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS exit_answer_open_person_idx
  ON exit_answer (person_id) WHERE person_id IS NOT NULL AND kept_at IS NULL;
```

- `DELETE /account` accepts an optional JSON body `{reason, note}`. No body, an empty body or an unknown reason deletes exactly as today and stores nothing; a bad answer never blocks a deletion. The note is trimmed, cut to 300 characters, and dropped when empty.
- The row is written inside the same transaction as the soft delete, with gender (Man or Woman), whole days since sign-up and whether the member has Premium now. No name, email, city or uuid.
- Staff and testers: nothing is stored for a person with the admin, mod or tester role.
- When the 7 days pass and the cron hard-deletes the person, `person_id` becomes NULL and the answer stays. Nothing else links it to the person.
- When a member keeps their account (cancel deletion, or signing in again as it works today), set `kept_at = NOW()` on their open answer. A later deletion writes a new row.
- Admin: `GET /admin/exit-answers` (admin only) returns totals per reason for all time and the last 90 days, and the latest 50 answers: date, reason, note, gender, member_days, had_premium, state (`waiting`, `deleted`, `kept`). It never returns a person id, name or email.
- Tests: answer stored with the delete; no body still deletes; unknown reason deletes and stores nothing; note cut to 300; tester and staff store nothing; hard delete keeps the row with NULL person; keep sets kept_at; a second deletion makes a second row; the admin route refuses a non-admin and returns no identifying field.

## App (ahavah-web)

- `src/app/settings/account/page.tsx`: add the question to the delete box as designed; send `{reason, note}` with the delete only when a reason is picked; reset the choice when the box closes.
- Reason codes and labels live in one file, `src/lib/exit-reasons.ts`.
- If the server is still the old version it ignores the body, so the app can ship in either order. Check that `apiClient.delete` can carry a body; if it cannot, extend it.
- Tests: the options render; picking one sends it; none picked sends no body; the note is capped; delete still works when the request fails as today.

## Admin (ahavah-admin)

- A card `Why members left` on the System tab under the member feedback card (`tab-system.tsx`, `member-feedback.tsx` is the model): a count per reason (all time, last 90 days) and the latest answers with their notes. Uses existing card, table and pill components only; no new chart. Designed on the canvas first.
- Tests for the mapping from the API to rows, and the empty state `No answers yet.`

## Privacy

`/legal/privacy` gains one sentence in its deletion paragraph: `If you tell us why you are leaving, we keep that answer without your name or email.` The owner reads this line before it ships, as it is legal copy.

## Rulings

- One question, optional. A longer questionnaire would cut the number of answers. Cost if wrong: add a second question later.
- The note could hold personal details the member types. It is capped at 300 characters, shown only to admins, and the helper line says how it is kept.
- No email asks why afterwards. The deletion notice email is unchanged.
- The 3 accounts waiting now are not asked.

## Order and checks

1. Design on the canvas (app box at 390, 800, 1440; admin card).
2. Server, with tests. 3. App and admin, with tests, type check and build.
4. Fresh review of all 3 diffs. 5. Deploy server and admin, then app. Verify the migration, health, and that a delete with no answer still works on a test account (tester role, nothing stored) and that the admin card loads.

## Changes after review (16 Nov), these override the text above

1. `DELETE /account` reads the body with `request.get_json(silent=True)` in the handler and uses it only if it is a dict. No `@validate`. A missing or bad body deletes as today.
2. The insert runs in a SAVEPOINT inside the soft-delete transaction and every error is swallowed and logged (no member data in the log). Before inserting, close any open row for the person (`kept_at = NOW(), person_id = NULL`), so the unique index cannot collide.
3. `kept_at` is set where sign-in clears `deletion_requested_at` (service/person/sql/__init__.py ~388), since deletion wipes every session and a member must sign in to keep the account. Also set it in `cancel_account_deletion`. Both are best-effort: a failure never blocks sign-in. On keep, `person_id` is set to NULL too.
4. Privacy. `member_days` is replaced by `member_band TEXT` with a CHECK: `under_1_month`, `1_to_6_months`, `over_6_months`. The admin route returns the month of the answer (`2026-11`), never the day. Rows still waiting on the 7 days (person_id set, kept_at NULL) are left out of the counts and the list; the route returns only how many are waiting. States shown are `Deleted` and `Kept`.
5. The migration is applied before the new code starts (the deploy script already does this); the sign-in change must also tolerate the table being absent only if that is cheap. Premium is `person.has_gold`; gender comes from a join on `gender`; staff and testers are `COALESCE(roles, ARRAY[]::text[]) && ARRAY['admin','mod','tester']::text[]`.

## Changes after the code review (18 Nov)

6. Kept answers are counted only (`kept` in the admin response) and left out of the reason counts and the list. The member is still active, and the waiting count dropping as they cancel would tie the note to them. The counts and the list are answers from members who are gone; every listed state is `deleted`.
7. Migration 0100 sets `lock_timeout = '5s'` around its work and adds a full index on `person_id` for the key's `ON DELETE SET NULL`.
