Linear: TEC-2113

# Format-only redraw of an approved Spotlight card

Owner, 6 Nov 2026: member cards move from 1080x1080 to 4:5 (1080x1350), "no square posts for IG feed". On Stewart's member-of-the-week card, already approved and scheduled for Mon 9 Nov 08:00 Barbados on both platforms: "redraw at 4:5, it's already approved, so no need to email him anything, it's just an aspect ratio fix."

## The problem

Consent is bound to a revision (`service/spotlight/revisions.py`). Any content change makes a new revision, consent does not carry over, and a new render queues the card-ready email (E4). A scheduled row also cannot take new artwork: `create_revision` refuses `in_flight` and the image route refuses `bad_status` and `already_rendered`. So today the only way to a 4:5 card is to cancel and start again, which emails the member and asks him to approve again.

## Rulings

Ruling: a format-only redraw keeps the same revision, caption, photo, participants and channels; only the artwork bytes change, and consent recorded for that revision stays valid. Why: the owner ruled it an aspect ratio fix to content the member already approved. Cost if wrong: a member's approval would cover artwork he did not see; contained by allowing it for member cards only, on an approved revision, admin only, with an audit row naming the old and new images.

Ruling: no member email and no push. The redraw path never calls `_enqueue_card_ready`, `_enqueue_card_ready_on_render` or `complete_render_if_ready`. Why: the owner said "no need to email him anything". Cost if wrong: Stewart gets a second "your card is ready" for a card he already approved; a test asserts nothing reaches the outbox.

Ruling: the hold is a column, `publishing_queue.format_redraw_requested_at`, not a new status. `claim_spotlight_posts` skips a row that carries it, and `dispatch_check` refuses one (`format_redraw_pending`) as a second guard. The rows stay `scheduled` and their `scheduled_for` is never touched; clearing the column is what returns them to the publish run. Why: a status change would touch the transition table, the Growth tab's state machine and every status filter, and returning a row to `scheduled` would need its slot carried somewhere. Cost if wrong: a row could be claimed with the old artwork; covered by the claim filter, the dispatch check and a test that claims a due held row.

Ruling: the old artwork stays on each row until that row's new artwork lands, and the swap is one UPDATE. Why: a held row must never publish with no image or with the square one; the swap never leaves a row without an image, and the hold covers the time the two platforms differ. Cost if wrong: nothing posts while held, so the worst case is a late post.

Ruling: if the new artwork has not landed by `scheduled_for`, the post waits. The slot is left as it was; once the redraw completes, the next publish run claims the row (it is already due), so it goes out late rather than square. The completion audit records `late: true` when that happens. The rest-day check in `dispatch_check` still applies, so a redraw finishing on a Sabbath sends the row to review rather than posting.

Ruling: the redraw finishes only when every held row carries the same bytes. Then the revision's `asset_hash`, `image_key` and `image_url` move to the new render, the new objects of any `scheduled` row are made public (approval already made the old ones public; a `review` row is made public by its own approval later), and only after that succeeds is the hold cleared. A failed public flip leaves the hold in place and the next tick tries again. Old objects go through `enqueue_asset_delete`, guarded by `is_referenced`, so a key a published row or a revision still names is never deleted.

Ruling: allowed only for `welcome` and `member_of_week`, only when every row of the request is `review` or `scheduled` with its delivery resolved, the member has not withdrawn, and the current revision is rendered with consent complete. Refused for roundups and brand posts, for any published, cancelled, processing, failed or awaiting row, and for a revision the member has not approved.

Ruling: a new revision (a caption edit, or a member picking another photo) clears the hold. Why: that path un-renders the rows and the tick draws the new revision with the current renderer anyway, through the normal consent flow. Cost if wrong: a stale hold would keep a row out of the publish run for good.

## What changes

API (`ahavah-api`):

1. Migration `0096_spotlight_format_redraw.sql`: the column, and `claim_spotlight_posts` re-created with `AND format_redraw_requested_at IS NULL`.
2. `service/spotlight/redraw.py`: request, attach (compare and set, same revision only) and finish.
3. `POST /admin/growth/queue/<qid>/format-redraw` (admin only): holds every row of the row's request. Audited `growth.queue.format_redraw` with the request key, revision and old image keys.
4. `POST /admin/growth/queue/<request_key>/format-redraw/image` (admin or cron): the replace path. Only for a held row on the same revision. Audited per upload and on completion (`growth.queue.format_redraw.done`, old and new keys, `late`).
5. `GET /admin/growth/queue?format_redraw=1`: the held rows for the tick. Every queue row now carries `format_redraw_pending`.
6. `dispatch_check` refuses a held row; `create_revision` clears the hold.

Admin (`ahavah-admin`):

1. The daily tick draws each held request with the current renderer (`renderCard`, unchanged) and uploads through the replace path. Failures are counted in the tick result, not reported as render failures.
2. The Growth row menu gets "Redraw at the current size" for an approved member card, following the existing action pattern. While a redraw is waiting it shows dimmed with "Waiting for the next tick".

The renderer's size is not changed here. Another change sets `cardSize` to 1080x1350 after the design lands; a redraw asked for before that deploys draws whatever the renderer draws at the time.

## Tests

- Consent recorded for the revision survives, and the revision id is unchanged.
- No E4 and no other outbox row is queued by asking for or completing a redraw.
- A due held row is never claimed: not with the old artwork, not with one platform redrawn and the other not.
- After completion the rows are `scheduled` with the same `scheduled_for`, carry the new image, and the old keys are queued for deletion.
- Refused for a roundup and a brand post, for a published or cancelled row, and for a revision without consent.
- Audited: who, request key, old and new keys.
