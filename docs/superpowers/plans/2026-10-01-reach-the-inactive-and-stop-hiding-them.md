Linear: TEC-1607

# Reach the inactive members, and stop hiding them

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every member who drifted away hears that people are joining, by email and (where they allowed it) by push; every active member without push is asked to turn it on; and inactive profiles stop disappearing from the map and the feed.

**Architecture:** Four small pieces on top of what exists. The dormancy cron goes to dry run and the 24 members it deactivated are reactivated by a one-off script. E3 (the re-invite) gains a notifications prompt and two run flags. A one-off script sends the push over the existing per-member sender. A new campaign E6 on the brand shell asks active members to turn notifications on, and the admin lists it beside the others.

**Tech stack:** Flask API, psycopg, the `emails/base.py` shell, `service/campaigns/runner.py`, Next.js admin.

**Spec:** Owner decisions in the conversation of 1 Oct 2026, recorded on TEC-1607.

## Global constraints

- No em dashes. Sentence case. British spelling. Torah-observant believers, never Jewish framing.
- Every email renders through `emails/base.py render()` with a `title_image()` brand asset. No hand-rolled display type (CI guard `tests/test_email_templates_use_the_brand_shell.py`).
- Never nest `api_tx`. No literal `%` in psycopg SQL.
- Counts, never names, in anything sent to a member about other members.
- The owner reads the rendered E3 before the real send. Nothing in this plan sends to a member until the owner says go.
- Owner's accounts (`admin@ahavah.app`, the `admin` role) are never recipients.
- Commits by explicit path, `Refs: TEC-1607`, git email admin@techbaseltd.com, no attribution trailers.

## Facts read from production, 1 Oct 2026

| Group | Count | Rule |
|---|---|---|
| Inactive members (list 1) | 24 | `NOT activated`, none pending deletion, all offline 30+ days, none self-deactivated in the last 30 days, none in a club |
| Inactive with a push subscription (list 2) | 5 | list 1 with a `push_subscription` row |
| Active members with no push (list 3) | 23 | `activated`, online within 30 days, no subscription, not admin |
| E3 last sent | 20 Sep, 15 people | 13 of them are in list 1, inside the 30 day resend window |
| Weekly email last sent | 24 Sep, 17 of list 1 | the 7 day frequency cap clears on 1 Oct 12:00 UTC |

## Order of work, and why

Reactivation comes first. E3's `paused` wording tells a member their profile is hidden, which stops being true the moment they are reactivated. Once every list 1 member is `activated`, the run uses the `quiet` wording for all of them, which is what the owner asked for: a count of who joined, a prompt to visit, a prompt to turn on push.

Consequences the owner should know, stated once here:

- Reactivated members appear in the feed and on the map, and other members can like and message them. Some will never answer. Their profile shows when they were last online, so this is visible rather than hidden.
- Reactivated members are back in the weekly email cohort (`send_community_weekly` requires `activated`).
- A member who deactivated on purpose from Profile > Edit would be reactivated too. Production shows no such account (the `/deactivate` route has never been hit in the audit log and all 24 match the cron's rule), and a member can deactivate again in two taps.

---

### Task 1: Stop the dormancy cron and reactivate the 24

**Files:**
- Modify: `docker-compose.production.yml:236` (default `DUO_CRON_AUTODEACTIVATE2_DRY_RUN` to `true`)
- Modify: `service/cron/autodeactivate2/__init__.py` (docstring recording the decision)
- Create: `scripts/reactivate_dormant.py`
- Test: `tests/test_reactivate_dormant.py`

**Interfaces:**
- Produces: `scripts/reactivate_dormant.py` with `reactivate_dormant(tx) -> list[dict]` returning `{person_id, email}` rows it reactivated.

- [ ] **Step 1: Failing test**

```python
# tests/test_reactivate_dormant.py
from database import api_tx
from scripts.reactivate_dormant import reactivate_dormant


def _set(tx, pid, **cols):
    sets = ', '.join(f"{k} = %({k})s" for k in cols)
    tx.execute(f"UPDATE person SET {sets} WHERE id = %(id)s", dict(id=pid, **cols))


def test_the_dormant_come_back_and_the_deleting_do_not(make_person):
    dormant = make_person(name='Dormant')
    deleting = make_person(name='Deleting')
    with api_tx() as tx:
        _set(tx, dormant['id'], activated=False)
        tx.execute("UPDATE person SET activated = FALSE, deletion_requested_at = NOW() WHERE id = %(i)s",
                   dict(i=deleting['id']))
    with api_tx() as tx:
        rows = reactivate_dormant(tx)
    ids = {r['person_id'] for r in rows}
    assert dormant['id'] in ids and deleting['id'] not in ids
    with api_tx('read committed') as tx:
        a = tx.execute("SELECT activated FROM person WHERE id = %(i)s", dict(i=dormant['id'])).fetchone()
        d = tx.execute("SELECT activated FROM person WHERE id = %(i)s", dict(i=deleting['id'])).fetchone()
    assert a['activated'] is True and d['activated'] is False


def test_a_second_run_changes_nothing(make_person):
    p = make_person(name='Twice')
    with api_tx() as tx:
        _set(tx, p['id'], activated=False)
    with api_tx() as tx:
        first = {r['person_id'] for r in reactivate_dormant(tx)}
    with api_tx() as tx:
        second = {r['person_id'] for r in reactivate_dormant(tx)}
    assert p['id'] in first and p['id'] not in second
```

- [ ] **Step 2: Run, expect import failure**
- [ ] **Step 3: Implement**

```python
# scripts/reactivate_dormant.py
"""Bring back the members the dormancy cron hid (TEC-1607).

    PYTHONPATH=/app python3 scripts/reactivate_dormant.py [--dry-run]

Owner decision 1 Oct 2026: an inactive profile stays visible on the map and
in the feed. The cron that set `activated = FALSE` after 30 days offline is
now in dry run (docker-compose.production.yml), and this puts back the
members it already hid. It never touches an account that asked to be
deleted: that one is leaving, not resting.

Idempotent: a reactivated member no longer matches, so a second run is a
no-op. Club counts are not re-incremented because the cron's decrement only
ever ran for members in a club, and none of the 24 is in one (read from
production on 1 Oct 2026). If that changes, re-count before running.
"""
from __future__ import annotations

import argparse

from database import api_tx

_Q = """
    UPDATE person SET activated = TRUE
     WHERE NOT activated AND deletion_requested_at IS NULL
    RETURNING id AS person_id, email
"""
_Q_DRY = """
    SELECT id AS person_id, email FROM person
     WHERE NOT activated AND deletion_requested_at IS NULL
"""


def reactivate_dormant(tx, dry_run: bool = False) -> list[dict]:
    return [dict(r) for r in tx.execute(_Q_DRY if dry_run else _Q).fetchall()]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    with api_tx() as tx:
        rows = reactivate_dormant(tx, a.dry_run)
    print(f"{'would reactivate' if a.dry_run else 'reactivated'} {len(rows)}")
    for r in rows:
        print(' ', r['person_id'])
```

- [ ] **Step 4: Compose default and docstring.** In `docker-compose.production.yml` change `${DUO_CRON_AUTODEACTIVATE2_DRY_RUN:-false}` to `:-true`. In the cron docstring add: "Owner decision 1 Oct 2026 (TEC-1607): inactive profiles stay visible, so production runs this in dry run. The module stays so the decision can be reversed with one env var."
- [ ] **Step 5: Tests green, commit** `feat(members): inactive profiles stay visible; bring back the 24 the cron hid`.
- [ ] **Step 6 (production, after deploy):** set `DUO_CRON_AUTODEACTIVATE2_DRY_RUN=true` in `.env.production` (backup first), recreate the cron container, run the script, confirm `SELECT count(*) FROM person WHERE NOT activated` is 0 (or equals the pending-deletion count).

---

### Task 2: E3 asks for notifications too, and can be aimed at the offline

**Files:**
- Modify: `emails/reinvite.py` (`reinvite_html` takes `notifications_url`)
- Modify: `emails/send_reinvite.py` (`recipients(offline_days=None, ignore_resend=False)`, CLI flags, `build_for` mints the second link)
- Modify: `service/api/admin/growth_routes.py` only if the admin passes flags (it does not; the one-off run is from the CLI)
- Test: `tests/test_reinvite.py`

**Interfaces:**
- Produces: `reinvite_html(first_name, total_new, cta_url, unsubscribe_url, gender_label='new members', state='quiet', notifications_url=None)`. With `notifications_url` set, both states render a paragraph "Want to hear when someone likes you or writes to you? Turn on notifications and we will tell you straight away, even when the app is closed." followed by a text link "Turn on notifications".
- Produces: `recipients(offline_days: int | None = None, ignore_resend: bool = False)`. `offline_days` keeps only members with `last_online < NOW() - offline_days`; `ignore_resend` drops the `reinvite_sent_at` window. CLI: `--offline-days N`, `--ignore-resend`.

- [ ] **Step 1: Failing tests**

```python
def test_the_email_asks_for_notifications_when_given_the_link():
    html = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x',
                         gender_label='women', notifications_url='https://ahavah.app/s/n')
    assert 'Turn on notifications' in html and 'https://ahavah.app/s/n' in html
    assert 'even when the app is closed' in html
    paused = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x',
                           state='paused', notifications_url='https://ahavah.app/s/n')
    assert 'Turn on notifications' in paused


def test_without_the_link_nothing_about_notifications_is_said():
    html = reinvite_html('Ehud', 4, 'https://ahavah.app/s/k', 'https://ahavah.app/u/x')
    assert 'notifications' not in html.lower()


def test_offline_days_keeps_only_the_long_offline(make_person):
    # a quiet member online yesterday, and one offline for 40 days; both have a newcomer
    ...  # set last_online_time, assert membership in recipients(offline_days=30)


def test_ignore_resend_lets_a_recent_recipient_through(make_person):
    ...  # reinvite_sent_at = NOW(); not in recipients(); in recipients(ignore_resend=True)
```

- [ ] **Step 2: Run, expect failures on the new keyword and flags**
- [ ] **Step 3: Implement.** In `reinvite_html` build `notif = ''` or the paragraph plus `<p><a href="{notifications_url}" style="color:{INDIGO};font-weight:700;">Turn on notifications</a></p>` and place it after the button in both branches. In `send_reinvite.py` thread `offline_days` into `_Q_RECIPIENTS` as `AND (%(offline)s IS NULL OR last_online < NOW() - make_interval(days => %(offline)s))` and `ignore_resend` as `AND (%(ignore_resend)s OR reinvite_sent_at IS NULL OR ...)`. In `build_for`, mint `notifications_url = make_campaign_link(tx, 'e3', f"{WEB_BASE_URL}/settings/notifications", pid)` in the same transaction as the CTA link.
- [ ] **Step 4: Tests green, commit** `feat(reinvite): ask for notifications, and aim a run at the long offline`.
- [ ] **Step 5: Render the preview for the owner.** `python -m emails.send_reinvite` has no preview flag; render `build_for(preview_row(...))` inside the test container to `_preview_e3.html`, screenshot with headless Chrome (`--user-data-dir` isolated), send the image. **Wait for the owner's go before the real send.**
- [ ] **Step 6 (production, owner's go):** `python -m emails.send_reinvite --send --offline-days 30 --ignore-resend --campaign-id e3-20261001-inactive`. Expect 24 built (fewer if a member has no matching newcomer; report the number).

---

### Task 3: One push to the inactive who allowed it

**Files:**
- Create: `scripts/push_reactivation.py`
- Test: `tests/test_push_reactivation.py` (recipient selection only; the sender is stubbed)

**Interfaces:**
- Produces: `select_recipients(tx, offline_days=30) -> list[dict]` with `person_id, total_new`; `send_all(rows, send=_send_to_user_blocking)`.

- [ ] **Step 1: Failing test:** an offline member with a subscription is selected; an admin with a subscription is not; a member with no newcomers is not; an unsubscribed-from-notifications member is not.
- [ ] **Step 2: Implement.** Selection: `last_online_time < NOW() - offline_days`, `deletion_requested_at IS NULL`, has a `push_subscription`, `'admin' <> ALL(roles)`, email not in `_excluded()`, not `campaign_unsubscribed(..., 'notifications')`, `count_newcomers_since(tx, id, last_online_time) > 0`. Payload: title `"People are joining Ahavah"`, body `f"{n} new members since you were last here. Come and see who."`, url `/discover`, tag `reactivation-2026-10`. Call the blocking sender outside any transaction (it opens its own). `--dry-run` prints the rows.
- [ ] **Step 3: Tests green, commit** `feat(push): one note to the inactive who allowed push`.
- [ ] **Step 4 (production):** run with `--dry-run`, expect 5 (person 20, 30, 38, 91, 101 less any with zero newcomers), then run for real and report successes and pruned endpoints.

---

### Task 4: E6, turn on notifications

**Files:**
- Create: `emails/notifications_nudge.py`, `emails/send_notifications_nudge.py`
- Modify: `service/campaigns/weekid.py` (`'e6': 'notif'`), `service/api/admin/growth_routes.py` (`_CAMPAIGNS['e6']`)
- Modify (admin): `src/components/admin/growth-emails.tsx` (`NAMES.e6 = "Turn on notifications"`, `ORDER`), `src/lib/growth-api.ts` (`CAMPAIGN_SUFFIX.e6 = "notif"`, the `campaignId` union)
- Test: `tests/test_notifications_nudge.py`; the admin cross-repo test `tests/growth-api.test.mjs` already compares the two suffix tables

**Interfaces:**
- Produces: `notifications_nudge_html(first_name, settings_url, unsubscribe_url) -> str`, `SUBJECT = "Hear about it the moment it happens"`, `FROM_ADDR = support@`, `UNSUB_SCOPE = 'notifications'`, `recipients()`, `recipient_count()`, `build_for(row)`, `preview_row(to)`.

- [ ] **Step 1: Failing tests:** html contains the button label "Turn on notifications" and `settings_url`; contains no em dash; recipients exclude a member with a subscription, an admin, and a member offline 31 days; include an active member with none.
- [ ] **Step 2: Implement the template** on `render()` with `chip("Notifications")`, `title_image("title-note.png", "title-note-wht.png", "A note from Ahavah.", 460)`, paragraphs:
  - "{name}, when someone likes you or writes to you on Ahavah, we can tell you straight away, even when the app is closed."
  - "Notifications are off for your account at the moment. One tap turns them on, and you choose what you hear about: matches, messages, likes."
  - `button("Turn on notifications", settings_url)`
  - `callout("On an iPhone, add Ahavah to your home screen first. Notifications only work from there.")`
  - Standard footer with Unsubscribe and Help.
- [ ] **Step 3: Implement the sender** on the E1 pattern. `_Q_RECIPIENTS`: `activated`, `deletion_requested_at IS NULL`, `last_online_time >= NOW() - interval '30 days'`, `NOT EXISTS push_subscription`, `'admin' <> ALL(COALESCE(roles, '{}'))`, excluded emails, unsubscribe and suppression predicates. `build_for` mints `make_campaign_link(tx, 'e6', f"{WEB_BASE_URL}/settings/notifications", pid)`.
- [ ] **Step 4: Register** `e6` in `weekid.py`, `growth_routes._CAMPAIGNS`, and the three admin spots.
- [ ] **Step 5: Both suites green** (API: whole suite; admin: `node --test "tests/*.test.mjs"`), commit API `feat(emails): E6 asks active members to turn notifications on` and admin `feat(growth): list the notifications email`.
- [ ] **Step 6 (production, owner's go):** `python -m emails.send_notifications_nudge --send --campaign-id e6-20261001-first`. Expect 23 built.

---

### Task 5: Deploy, run, record

- [ ] Deploy API (`git push origin <branch>:ahavah/main`), watch the run, then admin (`master`).
- [ ] Production order: Task 1 step 6 (env + reactivate), Task 2 step 5 (preview to owner, wait), Task 2 step 6, Task 3 step 4, Task 4 step 6.
- [ ] Verify: `email_send_log` rows for `e3-20261001-inactive` and `e6-20261001-first`; outbox drained; cron log shows dry run.
- [ ] Linear: comment on TEC-1607 with the numbers; `/linear-sync`.

## Self-review

- Spec coverage: reactivation (Task 1), email 1 with visit and push prompts and owner preview (Task 2), push to the inactive excluding the owner (Task 3), email 2 with one button (Task 4), run order and records (Task 5). Threads: parked, not in scope.
- Type consistency: `reinvite_html(..., notifications_url=None)` is used the same way in Task 2 steps 1 and 3; `recipients(offline_days, ignore_resend)` matches the CLI flags; `'e6': 'notif'` is the same string on both sides.
- Placeholders: Task 2 and 3 tests are sketched with `...` where the pattern is the one already in `tests/test_reinvite.py` (`_sendable_email`, setting `last_online_time`); the implementer copies that pattern.
