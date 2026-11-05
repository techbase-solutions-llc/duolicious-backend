Linear: TEC-2113

# The "card is ready" email waits for the card

Owner's ruling, 5 Nov 2026: the email or alert must not go out to a member until their card is drawn.

## What happened

Creating a welcome or member-of-the-week card in the admin queues E4 ("Your Spotlight card is ready") in the same transaction (`service/api/admin/spotlight_routes.py`, the welcome route and the member-of-the-week route, both `_enqueue_card_ready`). The card is only drawn by the admin's daily tick at 06:00 UTC, which uploads the image to `/admin/growth/queue/<rk>/image`; the render completes there (`complete_render_if_ready`). Stewart got E4 on 5 Nov, opened the link and saw "Your card is still being prepared. We will email you again when it is ready." Nothing sent that second email.

## Change

1. The welcome and member-of-the-week creation routes no longer queue E4. Their audit rows keep `invite_sent` (now false at creation) and add `invite_on_render: true` when approvals are on.
2. When an image upload completes the render (`complete_render_if_ready` returns true) for a subject card still `awaiting_member`, and `approvals_enabled` is on, queue E4 in the same transaction with campaign id `e4-drawn-<request_key>`, so it sends once per card however many times the card is re-rendered, and a card already emailed before it was drawn (the old behaviour, Stewart's) still gets this one.
3. `invite-pending` (the drain run when approvals resume) only queues E4 for cards already drawn (current revision has an asset hash), using the same `e4-drawn-` key. Cards not yet drawn get it at render.
4. No copy change. The card page's "We will email you again when it is ready" is now true.

## Tests

- Creating a member-of-the-week or welcome card queues no E4.
- Completing the render of an awaiting_member card with approvals on queues exactly one E4; a second render of the same card queues none.
- With approvals off, the render queues none; `invite-pending` later queues it once for a drawn card and none for an undrawn one.
- A card that already has the old `e4-<rk>` row still gets `e4-drawn-<rk>` at render.
- A roundup or other subject-less card never queues E4.

## Deploy

Stacked on `busy-row` (TEC-2111 server half). Both go out in one API deploy on the owner's go.
