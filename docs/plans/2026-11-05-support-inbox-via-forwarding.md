Linear: TEC-2115

# Support inbox: copy support mail by forwarding, with no Google key

Date: 5 Nov 2026. Status: approved by the owner on 5 Nov 2026 (chose "Forwarding, no Google key" and asked for the support inbox to be done autonomously). Replaces the Gmail API reader in `2026-11-05-support-messages-in-admin.md`; everything else in that plan (the table, the admin routes, the 14-day import rule, retention, privacy rules) stands.

## Why the change

Mail to support@ahavah.app is delivered to the owner's main mailbox, admin@techbaseltd.com. There is no separate support mailbox. A Google service account with domain-wide delegation for that mailbox could read the whole Techbase inbox, client mail included. The owner chose forwarding instead, so the server never holds a Google key.

## How it works

1. A Gmail filter on admin@techbaseltd.com forwards mail addressed to support@ahavah.app to a receiving address on the Techbase Resend account (`AHAVAH_SUPPORT_INBOUND_ADDRESS`). Gmail keeps the original From, To, Subject and Message-ID.
2. The supportinbox cron (every 5 minutes, unchanged) lists received emails with `GET https://api.resend.com/emails/receiving` (newest pages first, `limit` up to 100, `after`/`before` cursors) and, for each one it has not stored, whose `to` or `cc` includes support@ahavah.app or the inbound address, fetches it with `GET /emails/receiving/{id}` and stores it in `support_message`.
3. Idempotency is on the Resend email id (new unique column). The list is read until it reaches an id already stored, or the end. Resend keeps received mail 30 days, so a pass that has been down less than 30 days loses nothing.
4. The Resend key is `AHAVAH_SUPPORT_RESEND_KEY`, falling back to the key the API already uses to send through Resend. Listing and reading received mail needs a full-access key; a sending-only key answers 401/403, which is recorded in the inbox status (`last_error`, the error class and status code only) and shown in the admin's warning banner.
5. "Reply in Gmail" opens the original in the owner's mailbox: `https://mail.google.com/mail/?authuser={AHAVAH_SUPPORT_GMAIL_USER}#search/rfc822msgid%3A{message-id}`, `AHAVAH_SUPPORT_GMAIL_USER` defaulting to admin@techbaseltd.com.
6. Skipped, as before: automatic replies and mailer-daemon mail, and mail sent by support@ahavah.app itself. Gmail's forwarding confirmation email is stored like any other message (it is addressed to the inbound address); staff mark it Not for us.

## Rulings (where the brief is silent)

- Polling, not a Resend webhook: no signing secret to place on the server, and the "checked {time}" line in the admin stays true. Cost if wrong: up to 5 minutes' delay.
- The Gmail API reader and the google-auth dependency are removed, not left switched off, so nothing on the server can ask Google for a mailbox. Cost if wrong: rebuilding it, which the owner has ruled out.
- Mail where support@ahavah.app was only in Bcc is not matched by the list filter. Cost if wrong: such mail is missed; it is rare for a support address.

## Schema

Migration 0094 (idempotent): `support_message.resend_email_id TEXT UNIQUE`, `support_message.rfc_message_id TEXT`; `gmail_message_id` and `gmail_thread_id` become nullable. `support_inbox_state` keeps its row per mailbox; `history_id` and `backfill_token` are unused.

## Switching on

Owner-free, done by Claude on 5 Nov: set `AHAVAH_SUPPORT_INBOUND_ADDRESS` and `AHAVAH_SUPPORT_INBOX_ENABLED=1` on the server, add the forwarding address and filter in Gmail, confirm the forwarding code, then send a test to support@ahavah.app and see it in Admin > Support.
