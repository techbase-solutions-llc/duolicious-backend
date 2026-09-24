Linear: TEC-1192

# The dashboard counts what actually happened Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every number on the admin dashboard counts the thing its label names, and the activity members actually generate (likes, matches, conversations, feedback) stops being invisible.

**Architecture:** Almost all of this is in one file, `service/admin/queries/overview.py`, plus one new query module for engagement. No new tables, no new cron, no new tab. The engagement figures come from `liked` and from `mam_message`, both already in this database. The admin surface gains one section on the Overview tab built from primitives already in `design-primitives.tsx`.

**Tech Stack:** Python 3.11, psycopg 3, Flask (`ahavah-api`); Next.js 16, React 19, Tailwind v4, TanStack Query, Recharts (`ahavah-admin`).

**Spec:** none. This is an audit against live production data on 2026-09-24, following the same audit that produced `2026-09-24-email-runs-itself-and-reports-itself.md`.

## What we found, measured against production

Every figure below was read from the live database, not inferred from the code.

| What the dashboard says | What is true | Why they differ |
|---|---|---|
| Signups today: **0** | 5 people signed up in the last 7 days | The KPI counts `waitlist_signup` + `beta_signup`. Real members create `person` rows. |
| "vs 0 yesterday" | unknown | The string is a literal in the JSX. The route returns no yesterday figure. |
| Premium adds (30d): **flat zero** | 15 checkout completions, 8 subscriptions created | It counts `admin_audit_log WHERE action = 'grant_entitlement'`. That action has never been written once. |
| Premium holders: **51** | 51, and total persons is also 51 | Everyone in the database holds premium. The KPI restates "Total persons", which sits beside it. |
| Likes / matches / chats | 98 likes, 5 mutual matches, 29 messages across 9 conversations | Nothing anywhere shows them. The word "matches" appears in the admin once, in a comment. |
| Member feedback | 1 row in `feedback` | No admin route queries that table. |
| Recent activity | four kinds, two of them the dead signup sources | A real member joining produces no line in the feed. |

**The day boundary.** Every KPI and every chart uses `CURRENT_DATE`, which is UTC. Barbados is UTC-4, so anyone signing up after 20:00 local lands on the next day's bar. The dashboard is read in Barbados.

**Why this is one plan and not seven.** Six of the seven rows are the same defect: a label that no longer describes its query, usually because the thing it measured was the pre-launch funnel. They live in one file and share one test surface. Engagement is genuinely new work and is the last task for that reason.

## What this plan does not do

- **It does not lift the reports queue out of the legacy route.** `tab-moderation.tsx` says "Pre-Stage-B placeholder" and names where reports still live. That is honest, and `pending_reports` on the Overview is genuinely wired (currently 0). Honest empty states are not this plan's target.
- **It does not wire Sentry.** The API errors card says Sentry is not wired. Also honest.
- **It never reads message content.** The owner's words: "not the content of the chat just chats initiated and chats responded to". No query added by this plan may select `mam_message.message`, `search_body` or `translations`. This is enforced by a test, not by care.
- **It does not change how premium is granted**, only how it is reported.

## Global Constraints

- Pushing `ahavah/main` deploys production. Work on `dashboard-counts-what-happened`; deploy only after review and on the owner's go.
- **A number on this dashboard must count the thing its label names.** Where the honest answer is "we do not measure that", the panel says so rather than showing a figure that looks like an answer. That is the standard the last plan set and this one inherits.
- Barbados (`America/Barbados`) is the day boundary for every date bucket. UTC is the storage timezone and stays so.
- No em dashes on added lines. Sentence case in UI copy.
- No attribution trailers in any commit. Git email `admin@techbaseltd.com`.
- Never nest `api_tx`. No literal `%` in psycopg SQL.
- Add files to git by explicit path. Never `git add -A`. Never `git stash`.
- API tests: `MSYS_NO_PATHCONV=1 docker compose -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests -q` (baseline 941).
- Admin tests: `node --test "tests/*.test.mjs"` (baseline 180). `npx tsc --noEmit` must pass. There is no `npm test` script.

---

### Task 1: Signups count people, in Barbados, against a real yesterday

**Files:** Modify `service/admin/queries/overview.py`, modify `service/api/admin/overview_routes.py` if the payload shape changes, create `tests/test_admin_overview_counts.py`, modify `ahavah-admin/src/components/admin/tab-overview.tsx`, modify `ahavah-admin/src/lib/types.ts`.

**Interfaces:**
- Produces: `kpis.signups_today` and a new `kpis.signups_yesterday`, both counting `person` rows by `sign_up_time` in Barbados.

The defect the owner reported by hand: the card said 0 signups on a day they had received one. The chart directly beneath it counts `person` correctly and would have drawn that member. Two numbers from one route, disagreeing on the same screen.

- [ ] **Step 1: Write the failing test**

```python
"""Signups count PEOPLE. waitlist_signup and beta_signup were the
pre-launch funnel and nobody has used them since; on 2026-09-24 they held
0 rows for the last 7 days while 5 real members had joined."""
from database import api_tx
from service.admin.queries import Q_OVERVIEW_KPIS


def _kpis():
    with api_tx('read committed') as tx:
        return dict(tx.execute(Q_OVERVIEW_KPIS).fetchone())


def test_a_person_who_signed_up_today_is_counted_today(make_person):
    before = _kpis()['signups_today']
    p = make_person(name='SignupToday')
    with api_tx() as tx:
        tx.execute("UPDATE person SET sign_up_time = NOW() WHERE id = %(i)s",
                   dict(i=p['id']))
    assert _kpis()['signups_today'] == before + 1


def test_yesterday_is_a_real_count_not_a_constant(make_person):
    before = _kpis()['signups_yesterday']
    p = make_person(name='SignupYesterday')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET sign_up_time =
                 ((NOW() AT TIME ZONE 'America/Barbados')::date - 1
                  + TIME '12:00') AT TIME ZONE 'America/Barbados'
               WHERE id = %(i)s""",
            dict(i=p['id']))
    assert _kpis()['signups_yesterday'] == before + 1


def test_the_day_boundary_is_barbados_not_utc(make_person):
    """22:00 in Barbados is 02:00 the next day in UTC. Under CURRENT_DATE
    that member lands on tomorrow's count, on a dashboard read in Barbados."""
    today = _kpis()['signups_today']
    p = make_person(name='LateEvening')
    with api_tx() as tx:
        tx.execute(
            """UPDATE person SET sign_up_time =
                 ((NOW() AT TIME ZONE 'America/Barbados')::date + TIME '22:00')
                 AT TIME ZONE 'America/Barbados'
               WHERE id = %(i)s""",
            dict(i=p['id']))
    assert _kpis()['signups_today'] == today + 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `... /app/tests/run.sh tests/test_admin_overview_counts.py -q`
Expected: FAIL. `signups_yesterday` does not exist; `signups_today` does not move.

- [ ] **Step 3: Rewrite the two KPI columns**

In `Q_OVERVIEW_KPIS`, replace the `signups_today` expression with a count of `person` bucketed in Barbados, and add `signups_yesterday` beside it. Use this shape, and note the comment is part of the change:

```sql
        -- Signups are PEOPLE. This used to count waitlist_signup +
        -- beta_signup, which were the pre-launch funnel: on 2026-09-24 they
        -- held zero rows for the previous week while five real members had
        -- joined, and the owner caught the card saying 0 on a day they had
        -- personally received a signup. The chart below the card already
        -- counted person correctly, so the two disagreed on one screen.
        --
        -- Barbados, not UTC: the dashboard is read in Barbados, and under
        -- CURRENT_DATE a member who joins after 20:00 local lands on the
        -- next day's number.
        (SELECT COUNT(*) FROM person
          WHERE (sign_up_time AT TIME ZONE 'America/Barbados')::date
                = (NOW() AT TIME ZONE 'America/Barbados')::date) AS signups_today,
        (SELECT COUNT(*) FROM person
          WHERE (sign_up_time AT TIME ZONE 'America/Barbados')::date
                = (NOW() AT TIME ZONE 'America/Barbados')::date - 1) AS signups_yesterday,
```

- [ ] **Step 4: Run them and watch them pass**

- [ ] **Step 5: Make the delta real in the UI**

In `tab-overview.tsx`, the Signups card currently reads:

```tsx
delta={k?.signups_today ? { value: k.signups_today, label: "vs 0 yesterday" } : null}
```

`"vs 0 yesterday"` is a literal. Replace with the real comparison, and show it whenever either number is non-zero so a drop to zero is visible too:

```tsx
delta={
  k && (k.signups_today || k.signups_yesterday)
    ? {
        value: k.signups_today - k.signups_yesterday,
        label: `vs ${k.signups_yesterday} yesterday`,
      }
    : null
}
```

Add `signups_yesterday: number` to `OverviewResponse["kpis"]` in `types.ts`. Check what `KpiCard`'s `delta.value` does with a negative number before shipping; if it renders a bare minus where an arrow is expected, fix it in `kpi-card.tsx`.

- [ ] **Step 6: Lock the literal out**

Add to `ahavah-admin/tests/` a case asserting `tab-overview.tsx` does not contain `vs 0 yesterday`, matching on collapsed whitespace as `tests/outbox.test.mjs` does. Same class of regression lock as the deleted `"100%"`.

- [ ] **Step 7: Commit**

```bash
git add service/admin/queries/overview.py tests/test_admin_overview_counts.py
git commit -m "fix(admin): count signups as people, in Barbados, against a real yesterday"
```

### Task 2: The premium panels say something true

**Files:** Modify `service/admin/queries/overview.py`, modify `ahavah-admin/src/components/admin/tab-overview.tsx`, modify `types.ts`, extend `tests/test_admin_overview_counts.py`.

Two separate defects, both about premium, so they move together.

**The chart is structurally dead.** `Q_OVERVIEW_PREMIUM_30D` counts `admin_audit_log WHERE action = 'grant_entitlement' AND metadata->>'name' = 'premium'`. Live, the only actions ever written to that table are `admin_map_view`, `growth.email.send`, `growth.queue.member_of_week` and `reject_photo`. The chart cannot ever show a non-zero bar.

**The KPI is a tautology.** "Premium holders: 51" sits two cards from "Total persons: 51". Every person in the database holds premium; all 51 have a `subscription_expires_at`. Only 3 of them have any row in `entitlement_event`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_premium_series_reads_the_entitlement_ledger():
    """entitlement_event is the append-only ledger migration 0005 created
    for exactly this. admin_audit_log never carried the action the old query
    filtered on, so the chart was structurally incapable of a non-zero bar."""
    from service.admin.queries import Q_OVERVIEW_PREMIUM_30D
    assert 'entitlement_event' in Q_OVERVIEW_PREMIUM_30D
    assert 'grant_entitlement' not in Q_OVERVIEW_PREMIUM_30D


def test_a_purchase_event_appears_on_its_own_day(db):
    """Insert one checkout completion dated today and assert the last
    bucket moves. A test that only greps the SQL would not catch a query
    that names the right table and still buckets wrongly."""
    # Insert into entitlement_event with received_at = NOW(), run
    # Q_OVERVIEW_PREMIUM_30D, assert the final row's count went up by one.
    # Use a unique event_id (it is the primary key).
```

Write that second test out in full when implementing; it is the one that carries the weight.

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Rewrite the series**

```sql
-- Subscription purchases, from the append-only ledger migration 0005
-- created for this (`entitlement_event`, fed by the Stripe webhook).
--
-- This used to count admin_audit_log WHERE action = 'grant_entitlement'.
-- That action has never been written: the only actions in that table are
-- admin_map_view, growth.email.send, growth.queue.member_of_week and
-- reject_photo. The chart was structurally incapable of a non-zero bar,
-- and drew a flat line at zero while 15 checkouts had completed.
--
-- Only the events that START a paid relationship are counted here.
-- Renewals, updates and cancellations are real but are not "new", and
-- folding them in would make a churn event look like a sale.
Q_OVERVIEW_PREMIUM_30D = """
    WITH days AS (
        SELECT generate_series(
            ((NOW() AT TIME ZONE 'America/Barbados')::date - INTERVAL '29 days')::date,
            (NOW() AT TIME ZONE 'America/Barbados')::date,
            INTERVAL '1 day'
        )::date AS d
    )
    SELECT
        days.d::text AS day,
        COALESCE((
            SELECT COUNT(*) FROM entitlement_event
             WHERE event_type IN ('checkout.session.completed',
                                  'customer.subscription.created')
               AND (received_at AT TIME ZONE 'America/Barbados')::date = days.d
        ), 0) AS adds
      FROM days
     ORDER BY days.d
"""
```

**Before writing this, query production for the distinct `event_type` values** and confirm the two names above are the ones that mean "a new paid relationship started". The list on 2026-09-24 was `checkout.session.completed` (15), `customer.subscription.created` (8), `customer.subscription.deleted` (8), `customer.subscription.updated` (5). If a third creation-shaped type appears, include it and say why in the comment.

- [ ] **Step 4: Replace the tautological KPI**

"Premium holders" next to "Total persons", both 51, tells the owner nothing. Replace that card with **"Paying members"**: people holding premium who have at least one `entitlement_event`. Live that is 3, against 51 holders, and the gap is the fact worth seeing.

Add to `Q_OVERVIEW_KPIS`:

```sql
        -- Premium holders was a tautology: every person in the database
        -- holds premium (51 of 51 on 2026-09-24, all with a
        -- subscription_expires_at), so the card restated "Total persons"
        -- from two cards away. What is worth knowing is how many of them
        -- ever transacted.
        (SELECT COUNT(*) FROM person p
          WHERE 'premium' = ANY(p.entitlements)
            AND EXISTS (SELECT 1 FROM entitlement_event e
                         WHERE e.app_user_id = p.id::text)) AS paying_members,
```

Keep `premium_holders` in the payload (the Economy tab may use it) but stop rendering it as a KPI. Label the new card "Paying members" with the sub "of {premium_holders} with premium".

- [ ] **Step 5: Say that the money is not real yet**

Stripe is in test mode. A card reading "Paying members: 3" with nothing qualifying it invites the owner to read it as revenue. Add one line under the card: "Stripe is in test mode, so these are test transactions." Remove that line when Stripe goes live, and note the dependency in the card's comment.

- [ ] **Step 6: Run, verify, commit**

### Task 3: Every date bucket is a Barbados day

**Files:** Modify `service/admin/queries/overview.py`, extend `tests/test_admin_overview_counts.py`.

Task 1 fixed the two signup KPIs. This finishes the file.

- [ ] `Q_OVERVIEW_SIGNUPS_30D`, `Q_OVERVIEW_REFERRAL_CTR_7D` and `Q_OVERVIEW_PREMIUM_30D` all bucket on `CURRENT_DATE` and `created_at::date`. Convert each to `(… AT TIME ZONE 'America/Barbados')::date`, both in the `generate_series` bounds and in the per-day comparison. Missing one side gives an off-by-one that only shows near midnight.
- [ ] Check `service/admin/queries/cohorts.py` and `economy.py` for the same pattern and convert any date bucket a human reads. Leave retention and expiry arithmetic in UTC: those are durations, not calendar days, and a timezone would be wrong there.
- [ ] Test: one row timestamped 22:00 Barbados today lands in today's bucket, not tomorrow's, in each converted series.
- [ ] Commit.

### Task 4: A real member joining shows up in the activity feed

**Files:** Modify `service/admin/queries/overview.py`, modify `ahavah-admin/src/components/admin/tab-overview.tsx`, tests.

`Q_OVERVIEW_RECENT_ACTIVITY` unions four sources: `beta_signup`, `waitlist_signup`, `referral` and `admin_audit_log`. The first two are the dead funnel, so a real member joining produces no line.

- [ ] Add a `person` branch, keyed on `sign_up_time`, emitting kind `signup_member`.
- [ ] **Do not emit the member's email as `subject`.** The existing branches carry emails because waitlist and beta rows are pre-account records. A `person` row is an account, and the feed is a glanceable list, not a user record. Emit the person's name, and their uuid as `object` so the row can link into the user drawer. Confirm the drawer opens by uuid before relying on it.
- [ ] Give the new kind an icon and a sentence in whatever map `tab-overview.tsx` uses for the existing kinds. Read that map; do not invent a parallel one.
- [ ] Test: a person created now appears in the feed with kind `signup_member`, and the feed's SQL selects no email column from `person`.
- [ ] Commit.

### Task 5: Likes, matches and conversations stop being invisible

**Files:** Create `service/admin/queries/engagement.py`, create `service/api/admin/engagement_routes.py`, modify `service/admin/queries/__init__.py`, create `tests/test_admin_engagement.py`, modify `ahavah-admin/src/lib/queries.ts`, `types.ts`, `tab-overview.tsx`.

The owner asked for this directly: "does the dashboard show likes, matches and ongoing chats? (not the content of the chat just chats initiated and chats responded to)". Live there are 98 likes, 22 of them in the last week, 5 mutual matches, and 29 messages across 9 conversations. None of it is visible.

**The two tables, and their traps.**

`liked` has columns `liker_id, liked_id, created_at, is_super`. A match is a pair where both directions exist. Count each match once, with `liker_id < liked_id`, or every match counts twice.

`mam_message` is the XMPP archive: `id, direction, message, person_id, translations, search_body, from_jid, remote_bare_jid, detected_source_lang, audio_uuid`. Three things about it:

1. **It has no timestamp column.** The `id` is a MongooseIM MAM id: microseconds since epoch shifted left by 8. `to_timestamp(id / 1000000 / 256)` decodes it, verified against production (oldest 2026-07-09, newest 2026-09-21, both plausible). Put that expression behind a named SQL fragment with a comment, not inline in three places.
2. **Every message is stored twice**, once in each participant's archive, as `direction` `'I'` and `'O'`. Live: 58 rows, 29 actual messages. Count `direction = 'O'` only, or every figure doubles.
3. **It holds message content.** `message`, `search_body` and `translations` must never appear in a query this plan adds.

- [ ] **Step 1: Write the failing tests**

```python
"""Engagement figures. The owner's constraint is explicit: chats initiated
and chats responded to, never content."""

def test_a_match_counts_once_not_twice(make_person):
    """Both directions of a mutual like are rows in `liked`. Without the
    liker_id < liked_id guard every match is counted twice."""


def test_a_one_way_like_is_not_a_match(make_person):
    """Negative control for the test above."""


def test_a_conversation_with_one_sender_is_initiated_but_not_answered():
    """The distinction the owner asked for: someone reached out and nobody
    replied. That is the number that says whether the product is working."""


def test_a_conversation_both_sides_have_written_in_counts_as_answered():


def test_messages_are_not_double_counted(make_person):
    """mam_message stores each message twice, once per participant. On
    2026-09-24 production held 58 rows for 29 messages."""


def test_no_engagement_query_touches_message_content():
    """A standing guard, not a matter of care. The owner asked for counts,
    not content, and a later edit must not quietly widen that."""
    import service.admin.queries.engagement as eng
    src = open(eng.__file__, encoding='utf-8').read()
    lowered = src.lower()
    for forbidden in ('search_body', 'translations', 'm.message', ' message '):
        assert forbidden not in lowered, f'engagement SQL references {forbidden}'
```

Write each body out in full when implementing.

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Write the queries**

`Q_ENGAGEMENT_KPIS` returns: `likes_7d`, `likes_total`, `matches_total`, `conversations_total`, `conversations_answered`, `messages_7d`. A conversation is a distinct `(person_id, remote_bare_jid)` pair over `direction = 'O'`; answered means both participants appear as a sender in the same pair.

- [ ] **Step 4: Route**

`GET /admin/engagement` behind `require_admin`, one `api_tx`, never nested. Follow `system_routes.py` for shape.

- [ ] **Step 5: Surface it**

A section on the Overview tab titled "Engagement", below Trends, built from `AdminCard` and the existing `TripleStat`-equivalent. Five figures: Likes 7d, Matches, Conversations, Answered, Messages 7d. Under them, one line: "A conversation is answered when both people have written in it. Message content is never read."

- [ ] **Step 6: Run the full suite, commit**

### Task 6: Member feedback is read by something

**Files:** Modify `service/admin/queries/system.py` or a new `feedback.py`, modify a route, modify `tab-system.tsx` or `tab-moderation.tsx`, tests.

There is 1 row in `feedback` and no admin route queries the table. Someone took the trouble to write to the product and nobody has seen it.

- [ ] **Read the table definition first.** Confirm its columns and whether it carries a person id, a timestamp and a resolved flag. The task below assumes text plus a timestamp; correct it against reality rather than the other way round.
- [ ] Newest 50, with whatever the table holds, on the System tab as an `AdminCard` with a `TableShell`.
- [ ] If the table has no read or resolved marker, do not invent one. Show the rows and say the list is everything ever submitted. A fake "unread" badge would be this plan's own defect.
- [ ] Test: a row written now appears in the payload; the route refuses a non-admin.
- [ ] Commit.

### Task 7: Review and deploy

- [ ] Whole branch review on the most capable model; one fix wave.
- [ ] **Before deploying, compare every changed figure against production by hand.** Run each new query on the droplet and check its answer against a direct count. The previous plan shipped two Critical defects that a review caught and a test did not, both because the implementation was verified against its own assumptions.
- [ ] Deploy API, then admin.
- [ ] Confirm on the live dashboard: Signups today matches a direct `person` count for the Barbados day; the premium chart has non-zero bars where `entitlement_event` has rows; the engagement figures match direct counts of 98 likes, 5 matches, 9 conversations.

## Self-review record

- **The failure mode this plan is most at risk of is its own defect**: replacing a wrong number with another wrong number. Hence Task 7's by-hand comparison, and hence every task asserting on behaviour against seeded rows rather than on the SQL's text. The one source assertion, the content guard in Task 5, is a standing prohibition rather than a substitute for a behavioural test.
- **The `mam_message` double-count is the single most likely thing to go wrong**, because 58 rows looks like 58 messages and the number is plausible either way. It has its own test with the production figures written into the docstring.
- **Task 2 changes what a card means, not just its number.** Swapping "Premium holders" for "Paying members" drops a figure the owner has been looking at. It is in the plan rather than done quietly because that is a product decision, and the justification is that the old card restated the card two along from it.
- Reuse over invention: one new query module, one new route, one new section. Everything else is edits to queries that already exist.
- **Deliberately left:** the reports queue and Sentry, because both currently say plainly that they are not wired, and `email_outbox` retention, which belongs with the previous plan's known-not-fixed list.
