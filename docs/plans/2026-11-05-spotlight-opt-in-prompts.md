# Spotlight opt-in prompts (TEC-2113)

Date: 5 Nov 2026. Branch `spotlight-prompt` off `origin/ahavah/main`.

## The request

The owner, 5 Nov 2026: "make his card and send him a push so we can get his spotlight out now and push to other members and email the rest with push off so they can opt in at the earliest possible convenience".

## What gets built

Three new rows on the Growth tab's Emails table, each with the existing Preview, Dry run and Send flow. Nothing here sends by itself except the card-ready push in part 3.

1. `spotlight_push`, a push to every activated member who is not staff, has push on and has not opted in to Spotlight. Title "Be featured on Ahavah", body "Turn on Spotlight and you could be our member of the week." A tap opens `/settings/privacy`, where the Spotlight switch is.
2. `e1_push_off`, the existing Spotlight announcement email (E1, same builder, same single-use confirm link) to every activated member who is not staff, has no push subscription and has not opted in.
3. `card_push`, a push to each member whose drawn Spotlight card is waiting for their approval and whose card-ready email has gone. Title "Your Spotlight card is ready", body "Check the email we just sent and tap Approve to be featured." The same push now also goes on its own when a drawn card's card-ready email is queued (the `e4-drawn` path), so the owner presses Send only for cards drawn before this change, such as the 9 Nov member of the week.

## How it works

- `service/spotlight/prompts.py` holds the two push audiences, the push words, and one runner. A run reads the audience, skips members in quiet hours (21:00 to 08:00 their time), stops at 500 pushes, writes one `push_send_log` row per member before the push, and pushes after. A push no device took gives its row back, so the next Send tries that member again. A dry run builds and counts, writes nothing and runs inside the send guard's `no_send()`, so any push it attempted would raise.
- `emails/send_spotlight_announcement_push_off.py` is the E1 variant: E1's recipient filters plus the push and opt-in rules, built by E1's own `build` with its click links minted under `e1_push_off` so the row counts its own clicks.
- `service/api/admin/growth_routes.py` lists the new rows, each carrying `channel` (`email` or `push`), and sends the push rows through the runner instead of the email outbox. Preview of a push row pushes the sample to the admin's own devices.
- `service/api/admin/spotlight_routes.py`: `_enqueue_card_ready` asks for the card push whenever it queues a new card-ready email. The two routes that call it collect the push and send it once their transaction commits.
- Admin (`ahavah-admin`): names and order for the three rows, `channel` on the row type, and the dry run toast counts members held back by quiet hours. No new screen.

## Rulings where the request is silent

- Ruling: staff means the `admin` or `mod` role (`service.man_woman.staff_sql`), plus the excluded test addresses. Why: the brief names both roles; the older `member_sql` leaves out only `admin`. Cost if wrong: a moderator who is also a member gets no prompt.
- Ruling: members who left campaign emails (`campaigns` scope) get neither push. Why: the reactivation push set this rule for marketing pushes (TEC-1607). Cost if wrong: a few members who would have opted in are not asked.
- Ruling: the opt-in push goes once per member per run, and a run is the ISO week the admin's Send button keys it by. A second Send in the same week reaches only members it has not reached (late subscribers, those held by quiet hours or past the 500). Why: the brief asks for one per member per run, idempotent on rerun. Cost if wrong: pressing Send every week pushes the same members again.
- Ruling: the push-off email goes to each member once ever and is self-capped, like the Spotlight candidates note: it neither waits behind nor holds back the weekly E2. Why: the weekly E2 went on Monday 2 Nov, so E1's 7 day cap would hold nearly everyone until 9 Nov, against "at the earliest possible convenience". Cost if wrong: repeating it needs a code change.
- Ruling: the push-off email counts as E1 for the two scripts that ask whether a member was sent E1 (the held resend and the candidates note). Why: it is the same email. Cost if wrong: the candidates note reaches a few more people.
- Ruling: the card push is keyed per card revision (`<request_key>:<revision id>`), as asked, but the automatic one goes only when a new card-ready email is queued, since its words point at that email. A card redrawn after an edit gets no new email and so no automatic push; the Growth row can push its new revision. Cost if wrong: one push fewer after a redraw.
- Ruling: a tap on the card push opens the member's card review page with a fresh single-use card link minted for the push, not the app's home. Why: the member can approve in two taps; Web Push payloads are encrypted for the device, and the link is bound to the member's consent epoch like the email's. Cost if wrong: the push carries a live card link; the fallback is `/`.
- Ruling: every push here respects quiet hours, and the automatic card push also respects rest periods and the known calendar; one held back is not logged, so the Growth row sends it later. The Send route already refuses real sends in a rest period. Cost if wrong: a card push waits until the owner presses Send.
- Ruling: push sends run in a background thread after the rows are written, so a 500 member run does not hold the request open. Cost if wrong: a restart mid-run leaves some members logged but not pushed, which is how the reactivation push fails too.
- Ruling: the push rows report "reached" from `push_send_log` and no clicks. Push taps on these links are not counted: the web app records taps only for its known sources. Cost: no click figure for the pushes.

## Tests

`tests/test_spotlight_prompts.py`: audiences leave out staff (admin and mod), opted-in, deleted, deactivated, unsubscribed and suppressed members; push on goes to the push row and push off to the email row; a rerun with the same id pushes nobody twice; a dry run sends nothing and writes nothing; the cap; a push no device took gives its row back; the card push on a new card-ready email, once per revision, not outside a collecting request; the Growth index, send and preview for the new rows.

Refs: TEC-2113
