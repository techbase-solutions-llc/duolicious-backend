Linear: TEC-2115

# Support messages in the admin

Owner's request, 5 Nov 2026: keep a copy of every message to support@ahavah.app in the admin panel, so a request is seen even when the support inbox is not checked. Prompted by a member's "please unlock my account" email (30 Oct) that went unanswered for 6 days.

## What it does

- Every message sent to support@ahavah.app is copied into the API within about 5 minutes: sender, subject, body as plain text, time received, and the member it came from when the address matches an account.
- The admin gets a Support section listing them, newest first, each with Open, Handled, Not for us and a link to the member.
- Anything not marked handled within 24 hours goes into the owner's existing daily alert email, the same way unanswered member reports do now ("N support messages have had no answer for more than 24 hours").
- Replying stays in Gmail for now: each message carries a "Reply in Gmail" link to its thread. Sending from the admin is a later step if wanted.

## How mail gets in

ahavah.app mail is delivered by Google Workspace (MX smtp.google.com). We suggest the API reads the support mailbox through the Gmail API with a Google service account that has read-only, domain-wide access to that one mailbox, and checks for new messages every 5 minutes from the existing cron container. It needs no DNS change, it reads the whole history (so the 30 Oct message comes in too) and nothing is forwarded anywhere.

Owner steps (about 10 minutes, a Workspace admin is needed):
1. Google Cloud: create a service account in a project, enable the Gmail API, create a JSON key.
2. Workspace Admin, Security, API controls, Domain-wide delegation: add the service account's client id with the single scope `https://www.googleapis.com/auth/gmail.readonly`.
3. Put the key on the droplet as a file the API reads (path in `.env.production`), never in the repo or in chat.
Until then the feature is built and switched off by `AHAVAH_SUPPORT_INBOX_ENABLED`.

Alternatives considered: forwarding support@ to an inbound webhook (needs DNS and a verified forwarding address, loses history), and an Apps Script in the mailbox (code outside the repo).

## Build

API (`ahavah-api`)
1. Migration: `support_message` (gmail message id unique, thread id, from address, from name, subject, body text capped at 20,000 characters, received_at, person_id nullable, status `open` | `handled` | `not_for_us`, handled_by, handled_at).
2. `service/support_inbox/`: the poller (history id cursor, idempotent on message id, skips mail sent by support@ itself and auto-replies), plain text from HTML when there is no text part.
3. Admin routes: list (status filter, paging), mark handled, mark not for us; audit rows like the feedback routes.
4. The daily alert gains support messages open for more than 24 hours.
5. Cron entry with a blank-safe interval (the 14 Sep cron rule).

Admin (`ahavah-admin`)
6. Support section built from the Claude Design brief `briefs/2026-11-05-support-messages.md` in the Ahavah project, after the design comes back.

## The daily alert line (built 6 Nov 2026)

The owner's daily alert is the stale-post email (TEC-1897, `emails/admin_alerts.py`, sent by the adminalerts cron once per Barbados day at or after 07:00). There is no daily report line: a member report is emailed on its own as it arrives. The support line joins the stale-post email: "1 support message has had no answer for more than 24 hours", "N support messages have had no answer for more than 24 hours", with an Open support button to https://admin.ahavah.app/?tab=support, as the posts have Open the queue. It counts `support_message` rows with status `open` received more than 24 hours ago, and names no subject, body or address. Zero adds nothing.

Ruling: a lone support line is the whole daily alert when no post is waiting, behind its own switch `support_alert` (`AHAVAH_SUPPORT_ALERT_ENABLED`, off, proof in `scripts/send_admin_alert_proofs.py`). Why: a lone post line sends the alert by itself, and a lone report is emailed by itself, so an unanswered message riding only on days a post is stale could wait unseen for weeks, which is the 30 Oct failure this plan exists to stop. The switch ships off, so nothing new sends until the owner has seen the proof, whether or not the stale-post switch is on. Both parts share the day's one log row (still named `stale_posts`, so the deploy day cannot send twice): at most one alert email a day, and a message that passes 24 hours after that day's alert waits for the next one. Cost if wrong: the owner gets a daily email on days with no post waiting; turning `support_alert` off removes it.

## Privacy

Support messages are member content. They are read only in the admin by staff, never logged, never sent to analytics, and kept 1 year, then deleted by the existing retention cron.

## Tests

Poller: new message stored once, replays ignored, own mail skipped, member matched by email. Routes: staff only, status changes audited. Alert: an open message older than 24 hours is listed, a handled one is not.
