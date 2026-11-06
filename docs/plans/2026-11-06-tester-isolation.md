Linear: TEC-2135

# Tester isolation

## Why

The owner, 6 Nov 2026: "i notice blaynes test user jess getting likes, confusing people, i thought we had catered for the fact that people would be testing by hiding those test accounts from the view of the actual app users and only allowing those test accounts to interact with each other for the purpose of testing".

It was never built. What exists is an email list (`AHAVAH_TEST_ACCOUNT_EMAILS`, read by `service/growth/queries.py` `_excluded()`, not set in production) that keeps addresses out of campaign email and counts, and the rule that staff views are not recorded (`service/man_woman.py`). Labs testers, Blayne among them, sign up on the live app with test accounts.

## The rule

A tester is a person whose `roles` holds `'tester'`. A tester and a non-tester never see or reach each other anywhere members see people. Testers see and reach only other testers, under the same opposite-gender rule as everyone else (`opposite_gender_sql`, no fail-open). Existing likes, matches, views and messages across the line are hidden by the same filters and never deleted, so revoking the role brings them back.

## The fragment

One SQL function, `is_tester_split_pair(a INT, b INT)` (migration 0095): true when exactly one of the two is a tester. Staff are no exception. Python twin: `service/testers.py` (`TESTER_ROLE`, `tester_sql(alias)`).

The project already has a named hard barrier, `is_blocked_pair(a, b)` (migrations 0035 and 0070: a report either way, or an unmatch), which every visibility query calls, and a deck barrier, `is_deck_suppressed(searcher, prospect)`. Migration 0095 adds `OR is_tester_split_pair(a, b)` to both, the way 0070 added the unmatch. That covers, with no change to their queries:

- Discover deck and map (`Q_UNCACHED_SEARCH_2` through `is_deck_suppressed`, `Q_MAP_MARKERS`, `deck_base_sql`)
- profile open by id or link, full and limited, and the conversation profile (404, as for a block)
- Views both ways (`Q_VISITORS`), and so no view is recorded or pushed
- Liked you, your likes, matches, one match (`service/decisions`)
- sending a chat message and presence (`chatutil.fetch_is_skipped`), reactions, rewind
- Together started from a chat, introductions and their cards, mentors, quick questions in a conversation, matchmaker alert counts (`fits_sql` uses `deck_base_sql`)
- member emails that name another member: likes waiting, profile views weekly, reminders, community weekly personal lines; the admin community counts of matches and conversations

Places that do not call the barrier get it directly:

| Surface | Change |
|---|---|
| Deck cache (`Q_CACHED_SEARCH`) | re-checks `is_tester_split_pair`, so a role granted after a card was cached still hides it. No cache purge. |
| Like and match (`Q_RECORD_LIKE`) | no like row, no match, no push across the line |
| Super like | answers 404 before any token is spent, as for an unmatch |
| Chat inbox (`Q_GET_INBOX`) | threads across the line are left out for both sides |
| Chat history (`Q_SELECT_MESSAGE`) | returns nothing across the line |
| Spotlight | a tester fails the `staff` rule, so never eligible, never a card, never member of the week |
| Gatherings organiser list (`rsvp_list`) | guests whose account is on the other side of the line from the organiser's member account are left out |
| Organiser's digest email (`queue_digest`) | the same guests are left out of the names and the total |
| Inbox details (`Q_INBOX_INFO`) | a peer across the line reads as a deleted account: no name or photo, thread archived |
| Unread message push and email (`Q_UNREAD_INBOX`) | no push about a thread across the line |
| Organiser's going total (`_Q_LIST`) and new-guests push (`_Q_NEW_GUESTS`) | guests across the line are not counted |
| Matchmaker alert counts for a visitor (`deck_base_sql` with no owner) | testers are not counted |
| Friend joined email | not sent when the inviter and the friend are on opposite sides; tester to tester still sent |
| Hand-run senders (digest, new features, first match, comeback, onboarding nudge, profile nudge, member welcome) | `person` recipients and the digest's names and count leave testers out |

Campaign email, digests, "new members" and the admin growth and overview counts all bind `%(ex)s` from `_excluded()` (35 sites). `_excluded()` now adds the email of every tester to the static list and the env list, so all of them leave testers out with no edit, and so will any new query written the same way.

## Rulings

Ruling (changed 6 Nov 2026 on review; it first exempted staff who are not testers): in the member app a tester and a non-tester never meet, staff included; staff still see everything in the admin panel. Cost: the owner's member account will not see testers in Discover; staff who need to test get the tester role too.

Ruling: a staff account that is also a tester is a tester on every member-facing surface. Why: a staff member testing the app needs to see what testers see. The admin panel is unchanged for them. Cost if wrong: a staff tester stops seeing real members in the app until the role is revoked.

Ruling: `_excluded()` reads tester emails on its own short-lived connection, cached for 60 seconds per process. It never fails its caller: on an error it returns the last list read (none before the first), logs the error class once, retries after 10 seconds, connects with a 3-second timeout and never holds its lock while connecting. Why: `api_tx` is one shared connection behind a lock that is not re-entrant, and every caller calls `_excluded()` inside its own transaction; this keeps 35 queries, some of them in files other work is changing, untouched. The roles route clears the cache in its own process. Cost if wrong: up to 60 seconds after a grant, another process (cron) can still count or email the new tester once.

Ruling: testers still get the reminders and pushes about one pair or one gathering (`emails/reminders.py`, `service/notifications/activity_pushes.py`, which call `_excluded(testers=False)`), because the tester line already gates the pair and testers need to test those flows. The weekly likes-waiting and profile-views emails still use the full list, so testers do not get them. Cost if wrong: a tester's phone gets reminder pushes from test activity.

Ruling: testers get no campaign email and are not counted as new members, even by other testers. Why: the brief puts campaign email, digests and counts outside testing. Cost if wrong: a tester cannot test a campaign email or the new-members line with tester data; transactional mail (sign-in codes) is unaffected.

Ruling: Spotlight folds testers into the existing `staff` reason rather than adding a reason code. Why: no new reason for the admin to read, no change to the admin UI. Cost if wrong: the admin sees "staff" as the reason a tester is not eligible.

Ruling: hidden, never deleted. Why: the brief. Revoking the role brings back every like, match, view and thread the person had across the line. Cost if wrong: a revoked tester's old test likes reappear to real members. If the owner wants them gone on revoke, that is a separate, explicit cleanup.

Ruling: Together invite links shared outside a chat are not gated. Why: the owner shares them on purpose, and they work for people who are not members. Cost if wrong: a tester could send a real member a link and play with them.

## Not covered

- The public going count still includes testers.
- A Together session already started from a chat between a tester and a non-tester stays in each side's own list of sessions (`tools.sessions.mine`).
- Hand-run senders whose recipients are not `person` rows (launch, reengagement, referral intro: waitlist and beta lists) are not changed; a tester only appears there if their address is on those lists.

## How the role is granted

Admins only, in the admin user drawer: Actions, Roles, "Grant tester" or "Revoke tester", next to Grant mod, with the same confirm dialog and a reason. `PATCH /admin/users/<uuid>/roles` accepts `'tester'` beside `'admin'` and `'mod'` and writes the same `patch_roles` audit row (before, after, reason). The users list gets a `role_tester` filter beside `role_admin` and `role_mod`.

## Tests

- `tests/test_tester_isolation.py`: a tester is invisible to a non-tester and the other way round on the deck, the map, profile by id, Views, likes, matches, inbox, chat history, chat send gate, super like and Spotlight eligibility; testers see testers (opposite gender only); staff who are not testers are members in the app; existing cross likes, matches, views and messages disappear from both sides and come back on revoke; `_excluded()` and the admin overview count leave testers out; the roles route grants and revokes `tester` with an audit row.
- A static test fails if a later migration redefines `is_blocked_pair` or `is_deck_suppressed` without `is_tester_split_pair`.

## Deploy

Migration 0095 (0094 is taken by the support inbox work). Idempotent: `CREATE OR REPLACE` only, no data change.
