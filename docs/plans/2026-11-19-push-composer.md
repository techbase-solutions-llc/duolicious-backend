Linear: TEC-2182

# Push composer for the Ahavah admin: implementation plan

Status: approved by the owner, 19 Nov 2026 ("yes approved"), with the 3 automatic pushes in "Automatic pushes" below. Written 19 Nov 2026 from API origin/ahavah/main b298d82d, admin origin/master 8929525 and web origin/master f943aac, plus counts read from production.

## Goal

An admin writes one push, picks an audience from data the API already holds, sees how many members it will reach and what the notification looks like, sends it to their own device, and then sends it now or at a set time. Every send is capped, logged once per member, held in quiet hours and on rest days, and can be cancelled before it goes.

## What exists today

- `service/notifications/__init__.py`: `_send_to_user_blocking(person_id, payload, kind)` sends to every device a member has, prunes dead subscriptions, and passes every push through the send guard. Payload shape is `{title, body, url, tag}`. VAPID keys are set in production.
- `smtp/guard.py:117-120`: per member, 6 pushes of one kind and 20 pushes in total (chat apart) in 24 hours; 1,000 pushes an hour across the service. `guard.no_send()` makes a dry run raise rather than send.
- `push_send_log` (migration 0064): primary key `(person_id, campaign, campaign_id)`, so a row written before the send makes a second run skip that member.
- `service/spotlight/prompts.py`: the only admin-triggered push today. It claims `<campaign>:pending` rows, sends on a thread after commit, moves the row to `<campaign>` when a device took it, gives the claim back when none did, caps a run at `PUSH_CAP = 500`, and holds members in quiet hours. The Growth routes give it Preview, Dry run, Send, status and run history (`service/api/admin/growth_routes.py`). This is the pattern to copy.
- `scripts/push_reactivation.py` and the 2 Nov check-in (a scratchpad script, not in a repo) were one-off sends over the same sender. Its docstring says there is no broadcast in the product.
- Quiet hours: `service/questions/pushes.py` `quiet()` is 21:00 to 08:00 in the member's zone from `push_subscription.tz`, US Eastern when missing. 19 of the 24 people with a subscription have a zone stored.
- Rest days: `service/questions/schedule.resting(now)` is true inside a rest period (17:00 Barbados the evening before to midnight at its end) or after `KNOWN_THROUGH`, which is 8 Dec 2026 in `service/spotlight/restdays.py`. Rest days still to come: Tuesdays 24 Nov, 1 Dec and 8 Dec.
- Toggles: `notification_preference` has one column per push kind; `_EVENT_COLUMN` and `_EVENT_DEFAULTS` map them.
- Taps: `push_tap (person_id, src, tapped_at)` with a check on `src`. The values allowed today are qpush, mpush, lpush, mmalert, mmintro and mmtold. The web records a tap from `?src=` (`src/lib/push-tap.ts`).
- Audit: `admin_audit_log` (migration 0026), written through `service/admin.record_audit`, and `service/campaigns/runner.audit_send`.
- Admin Growth tab (`src/components/admin/tab-growth.tsx`): stats, Matchmaker, the push and tiers card (counts only), the publishing queue, removals, member of the week, emails and controls.
- Production on 19 Nov: 20 of 91 activated members (staff and testers left out) have push on.

## Server

### Switch

`AHAVAH_PUSH_COMPOSER_ENABLED`, default off, added to `service/campaigns/switches.py`. While it is off, every composer route answers 404 and the worker sends nothing, but the dry run and the test send still work so the owner can try it out.

### New push kind and member toggle

The new kind is `announcement` and the new column is `notification_preference.push_announcements`, **default on**.

We suggest on because only 20 members have push at all, and every one of them chose to turn it on. Starting it off would mean nobody receives a composer push until they find the toggle. It has to be easy to turn off, so:
- Settings > Notifications gets an "Ahavah news and suggestions" toggle;
- tapping the notification opens the app with a one-line footer on the landing page: "Turned off news pushes? You can in Settings";
- every composer audience leaves out members who left campaign email (`campaigns_unsubscribed_at`). This follows the Spotlight push rule, so a member who said no to campaigns is never pushed one.

Add `announcement` to `_EVENT_COLUMN` and `_EVENT_DEFAULTS` (True). Sends go through `send_to_user_counted(event_kind='announcement', kind='composer:<send id>')`, never `notify()`, which would fall back to email.

### Audience filters (data already held)

All filters work on `person` and `push_subscription`. They combine with AND.

| Filter | Source |
| --- | --- |
| Push on (always) | a `push_subscription` row exists |
| Gender | `person.gender_id` |
| Country, region | `person.country`, `person.region` |
| Last online | `person.last_online_time` (within 7, 14 or 30 days, or not since) |
| Joined | `person.sign_up_time` (within N days) |
| Photo | `person.has_profile_picture_id` null or not |
| Onboarded | `person.activated` (always true for members; the onboardee table holds the unfinished) |
| Verification tier | `person.ahavah_verification_tier` |
| Premium | `person.has_gold`, `subscription_expires_at > now()` (confirm the field Premium uses in `service/cron/entitlements` before building) |
| Spotlight | `person.spotlight_opt_in` |

These are always left out, using the same SQL as the other campaigns: staff (`staff_sql`), testers (`tester_sql`), members with deletion requested or deactivated by an admin, suppressed and excluded addresses (`_excluded()`, `suppressed_sql_pattern`), campaign unsubscribes, and members with `push_announcements` off.

**Tester test send:** a send marked `testers_only` inverts the tester rule. Its audience is testers only and can never include a member. The route refuses `testers_only` with any filter that could reach a member.

**Opposite gender:** the opposite-gender rule ([[feedback_ahavah_opposite_gender_only]]) governs who members see. It does not apply to a broadcast, because a broadcast shows nobody to anybody. If a push's text or landing page shows people (for example "new members near you"), the landing page applies the rule as it always does. The composer itself never names or shows a member.

### Tap target

`url` must be one of an allow list held in the API: `/discover`, `/matches`, `/chat`, `/likes`, `/events`, `/host`, `/together`, `/profile`, `/settings/notifications`, `/settings/privacy` and `/your-ahavah`. Each must be checked against the web routes before the list is fixed. The API adds `?src=apush&send=<id>`. No free text and no outside links.

### Text limits

The service worker (`public/sw.js`) shows the payload's title and body as given, with no limit. The web push payload itself must stay under 4 KB. Phones cut long text, so we propose title at most 50 characters and body at most 120, counted as whole characters. Both are required, and line breaks are refused. The API checks them and the admin counts them as the admin types. Copy rules are checked in the API with the existing copy linter if there is one, or else a simple check for em dashes and for "!" at the end of a title.

### Routes (admin only, `require_admin`)

- `POST /admin/growth/push/audience` takes filters and returns `{count, held_now: {quiet, resting}, by_country: [...]}`. Counts only, never names.
- `POST /admin/growth/push/test` sends to the signed-in admin's own devices with kind `composer_test`. It returns `delivered: true/false` and records `test_delivered_at` against the draft. The test is **required**: a real send is refused unless the draft's current text, url and filters were test-delivered in the last 24 hours. Any change to the draft clears the test.
- `POST /admin/growth/push/dry-run` runs the whole audience and hold logic inside `guard.no_send()`. It writes nothing and returns what would be sent now, what would be held and why, and what is over a cap.
- `POST /admin/growth/push/send` takes `{draft_id, when: 'now' | ISO time, mode: 'barbados' | 'member_local'}`. It freezes the draft into a send row and audits it. `member_local` means "at this clock time in each member's own zone".
- `POST /admin/growth/push/<id>/cancel` cancels a scheduled or held send. Members already sent to stay sent, the rest are released, and the cancel is audited.
- `GET /admin/growth/push/sends` and `GET /admin/growth/push/<id>` list the sends and give one send's state and results.

### Scheduling and holding

A cron tick runs every 10 minutes, next to the returnmail cron. For each send that is due, it takes each member and:
- if it is quiet hours where they are, or `resting(now)`, holds them and tries again next tick;
- claims `push_send_log (person_id, 'composer', '<send id>:pending')`, sends after commit, moves the row to `'<send id>'` when a device took it, and gives the claim back when none did, as `prompts.py` does.

A send has a hold window, 48 hours by default. A member still held at the end of it is marked `expired` and counted in the results, never dropped silently.

At schedule time the route refuses a slot that `restdays.slot_problem` calls a rest day or unknown. A slot after 8 Dec is unknown, so nothing can be scheduled past `KNOWN_THROUGH` until the calendar is extended. The admin says so in words.

### Caps and idempotency

- **Per send:** an audience above 500 is refused (the Spotlight cap), and so is one above `AHAVAH_PUSH_COMPOSER_MAX_AUDIENCE` if it is set lower.
- **Per member:** at most 1 composer push in 72 hours and 2 in 7 days. A member over the cap is skipped and counted as `capped`.
- **Per day:** at most 2 composer sends a Barbados day, and at most 1,000 composer pushes in total.
- Pushing the Send button again, or a retried request, carries an idempotency key (the draft id plus a hash of its content). A second send with the same key returns the first.
- The send guard's own per-member and hourly limits still apply underneath.

### Logging

- `push_send_log`: one row per member per send, as described above.
- `admin_audit_log`, written through `record_audit`, gets these actions: `push_composer_test`, `push_composer_schedule`, `push_composer_send`, `push_composer_cancel`. The metadata holds the send id, a hash of the filters, the audience count, the title and the url. It never holds a member's address.
- The send row (see the migration below) keeps the results: `sent`, `held`, `capped`, `failed`, `expired`, `tapped`.

### Taps

Add `apush` to the check on `push_tap.src`, and add a `send_id` column (nullable) so taps can be counted per send. The web's `src/lib/push-tap.ts` accepts `apush` and passes `send` through. A tap counts once per member per send.

## Migration 0101_push_composer.sql

- `notification_preference.push_announcements BOOLEAN NOT NULL DEFAULT TRUE` and `push_announcements_off_at TIMESTAMPTZ`.
- Table `push_composer_send`: id uuid, title, body, url, filters jsonb, testers_only, idempotency_key unique, state (`draft`, `tested`, `scheduled`, `sending`, `sent`, `cancelled`, `failed`), scheduled_for, mode, hold_until, test_delivered_at, created_by, created_at, cancelled_at, and counts (`audience`, `sent`, `held`, `capped`, `failed`, `expired`).
- `push_tap`: the src check gains `apush`; add a nullable `send_id uuid`.
- Idempotent with `lock_timeout`, as 0100 is.

## Admin UI

It sits on the Growth tab as a "Pushes" card, after the push and tiers card. The card holds the composer and a list of past and scheduled sends. Every state below must be drawn on the Ahavah Claude Design canvas first, as page p35, through `/brief`. Nothing is built until the design is returned with `/handoff` and approved.

These are the states the card needs:
1. Compose: title and body with character counts, the tap target picked from the allow list, and the filters.
2. Preview: the audience count, how many are held now (quiet hours or rest), and a phone mock of the notification (Android and iOS lock screen, Ahavah icon, title and body cut as a phone would cut them).
3. Test sent: delivered or not delivered, with the reason. The Send controls stay locked until this shows delivered.
4. Schedule: send now, or a date and time, in Barbados time or each member's local time. Refused slots are shown in words.
5. Scheduled: when it goes, with a Cancel button.
6. Sending: the counts as they rise.
7. Sent: the results (sent, held, capped, failed, expired, tapped).
8. Failed or halted: the reason, for example the send guard halted it, the switch is off or VAPID is missing.
9. Empty and loading states, and an error for when the audience could not be counted.

## Tests

API (pytest):
- each filter gives the expected SQL result;
- staff, testers, suppressed addresses, campaign unsubscribes and members with the toggle off are always left out;
- `testers_only` reaches testers only and refuses member filters;
- the url allow list holds, and an outside or unknown path is refused;
- the title and body limits, and line breaks;
- no real send without a delivered test, and an edit clears the test;
- a dry run raises inside `no_send()` and writes nothing;
- quiet hours hold a member, and per member zones work, including a missing zone;
- `resting()` holds, a schedule after `KNOWN_THROUGH` is refused, and a rest window that starts mid-send holds the rest of the send;
- the hold window ends as `expired`, never as a silent drop;
- a second tick, a retried request and a double press send nothing twice (`push_send_log` key, idempotency key);
- the per send, per member and per day caps;
- a cancel releases held members and keeps those already sent;
- a claim with no device given back is retried once;
- audit rows are written for test, schedule, send and cancel, with no addresses in their metadata;
- a toggle off and a PATCH to it work, and the toggle shows in GET preferences;
- taps with `apush` are counted once per send;
- every route answers 404 while the switch is off, except test and dry run;
- the `Send rules` deploy job (`tests/test_send_rules_static.py`) knows the new sender.

Admin (vitest): each state renders; Send stays locked until a test is delivered; the counters; the cancel confirm; a 320 and 390 px width check of the card.

Web: the `apush` tap is recorded; the new Settings toggle saves; the landing footer line shows.

## Rollout

1. Run the migration, then deploy the API with the switch off. Try the dry run and a test send against the owner's device.
2. Brief p35, hand it off, and build the admin behind the same switch.
3. The owner approves the copy of the first push and its proof.
4. Switch on. The first real send goes to a small filter, for example one country, and we watch `send_tally` and the alerts.

The backup of `.env.production` is taken before the switch changes, as with every other switch.

## Risks and how each is prevented

| Risk | Prevention |
| --- | --- |
| Wrong audience | Fixed exclusions in SQL that the UI cannot turn off; a counted preview; a required test; `testers_only` cannot mix with members; a cap of 500 per send. |
| Double send | `push_send_log` primary key claimed before the send; an idempotency key per draft; the send state moves forward only; a claim with no device is retried once. |
| Sending on a rest day | `resting()` checked per member at send time; the schedule refused by `slot_problem`; nothing after `KNOWN_THROUGH` (8 Dec) until the calendar is read further. |
| Quiet hours | Checked per member in their own zone; held, then expired after 48 hours, and counted. |
| Spam fatigue | 1 composer push per member in 72 hours and 2 in 7 days; 2 sends a day; a member toggle; campaign unsubscribes respected; taps per send shown, so pushes nobody taps can be stopped. |
| Send loop (as on 2 Nov) | One send row is one pass over its audience; a tick sends only to unclaimed members; the send guard's hourly ceiling; `send_tally` and the watchdog see it. |
| Leaking member data | Counts only in routes and audit; the composer never names a member. |

## Pushes worth sending

Every count below was read from production on 19 Nov 2026. "Push members" means the 20 activated members with push on, leaving out staff and testers.

1. **Likes waiting.** Data: `liked` with no `liked` back and no `skipped` row. 4 push members have at least 1 like from an active member that they have not answered. This needs to be automatic, per member: the `AHAVAH_LIKES_WAITING_ENABLED` email exists, but there is no push. It could go on the composer only if a "has an unanswered like" filter is added.
   Title: Someone likes you
   Body: You have a like waiting. Open Ahavah to see it.
2. **New members near you this week.** Data: `person.sign_up_time`, `country`, `gender_id`. 9 members joined in the last 7 days, and 14 push members share a country with a newcomer of the other gender. This works best as an automatic weekly push with the count per country. Through the composer it can go by country filter, with no count in the text.
   Title: New on Ahavah near you
   Body: People in your country joined Ahavah this week. Take a look.
3. **Play the Us game with your match.** Data: `ahavah_match`, `unmatched_pair`, `tool_session` (owner_person_id, chat_person_id). There are 14 current matches between members, and none has a Together session between the pair. This needs to be automatic, per match. It names nobody, which follows the open decision on naming in reminders.
   Title: Try the Us game with your match
   Body: Answer the same questions and see where you agree.
4. **Get verified.** Data: `person.ahavah_verification_tier`. 7 of the 20 push members have no tier. It can go through the composer with the tier filter set to none. The tap target is to be confirmed against the web's verification route.
   Title: Show members your profile is real
   Body: Verify your profile to get a badge on your card.
5. **Be in Spotlight.** Data: `person.spotlight_opt_in`. None of the 20 push members has opted in. No composer is needed: the existing Growth row `spotlight_push` (`service/spotlight/prompts.py`) sends its approved copy today.
   Title: Be featured on Ahavah
   Body: Turn on Spotlight and you could be our member of the week.
6. **Before the Sabbath.** Data: `REST_DAYS` in `service/spotlight/restdays.py`. The Sabbaths still to come are Tuesdays 24 Nov, 1 Dec and 8 Dec, and each rest begins at 17:00 Barbados time the evening before. It goes through the composer, scheduled for the Monday morning, Barbados time, to push members, and it never touches the rest window. It works best paired with the "Last online" filter (8 push members were last online 14 or more days ago).
   Title: Before the Sabbath
   Body: Say hello to your matches today. Ahavah is quiet from this evening.
7. **Host a gathering.** Data: `event` and `organiser`. There are no upcoming member gatherings, and the only upcoming one, on 24 Nov, is cancelled. It goes through the composer to all push members, with the tap target `/host`. The copy follows the 5 Nov social post. We suggest not linking to `/events` while the list is empty.
   Title: Host a gathering
   Body: A Sabbath meal, a study evening or a feast day. List it and members near you can join.
8. **Come back to new faces.** Data: `person.last_online_time`, plus the newcomer count since that date (`count_newcomers_since` in `service/growth/queries.py`, as used by `scripts/push_reactivation.py`). 8 push members have not been online for 14 days or more. It can go through the composer with "Last online: not in 14 days". A count in the text would need the automatic version.
   Title: People are joining Ahavah
   Body: New members have joined since you last looked. See who is new.

Already automatic, so not on this list: match and message reminders, the weekly question (next drops 22 Nov, 29 Nov and 6 Dec, all approved), the match question, Matchmaker alerts, and the gathering reminder and new guests pushes.


## Owner's answers (19 Nov 2026)

- The composer is approved as planned, and the owner wants it built.
- The owner turned down the generic "Host a gathering" push. It is not the first push, and the composer never sends anything that was not written for the occasion.
- The 3 automatic pushes below are approved for building: likes waiting, new near you and the Us game. Each ships switched off. The owner sees each one on a test device and approves its wording before its switch goes on.
- Ruling (mine): the UI is drawn on canvas p35 by us, not briefed out. The canvas is the plan for the screens. The cost if this is wrong is a redesign round on the canvas.

## Automatic pushes

These rules apply to all 3:
- **Switches:** each has its own switch, default off: `AHAVAH_PUSH_LIKES_WAITING_ENABLED`, `AHAVAH_PUSH_NEWCOMERS_ENABLED` and `AHAVAH_PUSH_US_GAME_ENABLED`. A dry run works while a switch is off. So does a test send to a named admin's own devices, through an admin route.
- **Sending:** each sends through `send_to_user_counted` with its own `kind`, and never through `notify()`, which falls back to email.
- **Who is left out:** staff, members with deletion requested or deactivated by an admin, and suppressed addresses are always left out. Tester isolation holds: a tester is only ever told about testers, and a member never about a tester. The opposite-gender rule and the deck's visibility rules (blocks, skips, `is_deck_suppressed`, staff hidden) apply to every person counted or pointed to.
- **Holding:** these pushes are recurring, so in quiet hours or `resting(now)` the member is skipped this tick and tried on the next one, inside the same period.
- **Once per period:** `push_send_log` is keyed by period, so a period is sent at most once.
- **Caps:** the send guard applies underneath.
- **Taps:** each push gets its own tap source (`lwpush`, `nnpush` and `uspush`), added to the `push_tap.src` check in migration 0101.
- **Text:** no push names a member or carries their words.
- **Wording:** the titles and bodies below are drafts, and the owner approves the final words before each switch goes on.

1. **Likes waiting.** This is a reminder on top of the like push that already exists at the moment of the like.
   - **Who gets it:** a member who has had at least 1 like from a visible member for 3 days or more, has not answered it (no like back, skip, block or match), and has not been online since that like arrived.
   - **How often:** at most once in 7 days per member. The daily cron sends it between 10:00 and 20:00 in the member's own zone.
   - **Toggle:** the existing likes toggle.
   - **Tap:** wherever the existing like push opens. If seeing likes is a Premium feature, the tap opens what a free member already sees for a like, never a bare paywall.
   - **Draft words:** "Someone likes you" / "You have a like waiting. Open Ahavah to see it."
2. **New near you.**
   - **When:** weekly, Thursday from 10:00 in the member's zone.
   - **Who gets it:** a member, when at least 1 member they could be shown on the deck (opposite gender, activated, with a photo, visible to them) joined in their country in the last 7 days.
   - **What it says:** the count of those newcomers and the country. It is never sent when the count is 0.
   - **How often:** at most once a week.
   - **Toggle:** the new `push_announcements` toggle (news and suggestions).
   - **Tap:** `/discover`.
   - **Draft words:** "New on Ahavah near you" / "2 new members joined in Barbados this week." (1 member: "1 new member joined in Barbados this week.")
3. **The Us game with your match.**
   - **Who gets it:** each member of a current match (not unmatched, both active and visible to each other) made 2 days ago or more, with no Together session ever between the pair.
   - **How often:** at most once per match per member, and at most 1 Us game push per member in 7 days.
   - **Toggle:** the existing toggle closest to match activity; the builder names which and why.
   - **Tap:** the place where that member starts the Us game with that match. The name is never in the text.
   - **Draft words:** "Try the Us game with your match" / "Answer the same questions and see where you agree."

**Tests for each:** who gets it and who does not (each exclusion), the once-per-period key, the quiet hours and rest-day skips, the switch off, the dry run writing nothing, the counts and pluralisation, tester isolation, and no name in the payload.

**Growth tab:** the push and tiers card gains one row per automatic push, showing whether it is on or off, sent in the last 7 days and tapped. The rows are counts only.
