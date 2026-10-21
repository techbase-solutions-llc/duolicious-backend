# Better reports: plan

Date: 21 October 2026
Refs: TEC-1845
Repos: ahavah-api, ahavah-web, ahavah-admin

## Why

The first member report came in on 20 October and was no use to the owner, for three reasons.

1. Its email was never sent, because of the wrong sender. That is fixed in a6ee690.
2. Its reason was a bare "Other", with no words, so it said nothing about what happened.
3. The email is the old Duolicious template: a YAML dump, the photo links and two one-click ban links. The owner wants none of that.

The owner's words (21 Oct): "Other" is not a reason. The email should carry no delete links or other links, except perhaps one to the dashboard. Moderation is done from the dashboard.

## What changes

### 1. A report must say what happened (web and API)

- **Web** (`ahavah-web/src/components/app/block-report-sheet.tsx`): when "Other" is chosen, the details field becomes required.
  - Its label changes from "Additional details (optional)" to "What happened?"
  - Send stays disabled until at least 10 characters are written.
  - The other 5 categories keep details optional.
  - New lines, put through /copy-pass before the build:
    - "What happened?"
    - "Tell us in a few words. We read every report."
- **API** (`service/api` `post_skip_by_uuid`): it refuses a report of "other" with fewer than 10 characters of details, with a 400 and a message the app shows. The app's own check can be bypassed, and old installed versions do not have it.
- **Test:** an "other" report with no details is refused. An "other" report with details, and a "harassment" report with none, are both accepted.

### 2. The report email is an alert, not a moderation tool (API)

Replace `report_template` in `antiabuse/lodgereport/__init__.py`.

- **Subject:** `New report: {reason title}`, for example "New report: Harassment or abusive messages".
- **Body**, in the Ahavah shell, with phone sizes from `emails/base.render()`:
  - the reason title and the member's own words;
  - who reported whom, by first name and member number;
  - where it was reported from (a profile or a conversation);
  - how many messages the two have exchanged;
  - the time.
- **One button: "Open in the dashboard".** It links to the report in admin.ahavah.app's Moderation tab.
- **Removed:**
  - both ban links;
  - the photo-removal links;
  - the YAML dump;
  - the photo links;
  - the messages.
- `Q_MAKE_REPORT` stops creating `banned_person_admin_token` and `deleted_photo_admin_token` rows. The old `/admin/ban-link` and `/admin/delete-photo-link` routes keep working for any link already in an inbox.
- The email is added to `tests/email_samples.py`, so the phone check covers it.
- **Tests:**
  - no `ban-link` or `delete-photo-link` appears in the body;
  - the body contains the one dashboard link;
  - the reason title and details are escaped.

### 3. Moderation happens in the dashboard (admin and API)

- The Moderation tab opens a report directly from a link (`?tab=moderation&report=<id>`), so the email's button lands on it.
- "Show messages" (brief `briefs/2026-10-20-admin-report-messages.md`, sent 20 Oct):
  - a staff-only API route returns the last 25 messages between the two members, including messages after unmatching;
  - it writes one audit row each time messages are opened;
  - the admin UI is built when the design returns.
- Ban, deactivate and dismiss already exist in the dashboard and stay there.

## Order

1. API: refuse a bare "other", the new email, stop making tokens, the messages route. All in one branch, tested, then deployed.
2. Web: the required field, built as soon as the copy pass is done.
3. Admin: the deep link now, and the messages view when the design returns.

## Owner's answers (21 Oct 2026)

- Build the plan as written.
- The form change is built straight away, without a Claude Design round. This is an explicit waiver for this one change only: it reuses the existing details box and styles.

## Not changing

- The categories themselves.
- Bot detection on the reason text.
- Who receives report emails (DUO_REPORT_EMAIL).
