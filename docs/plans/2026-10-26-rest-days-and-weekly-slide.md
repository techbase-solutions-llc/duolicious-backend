# Rest days from the owner's calendar, and the weekly email on the next free day

Date: 2026-10-26. Refs: TEC-1933, TEC-1447, TEC-1845. Repos: `ahavah-api` and `ahavah-admin`.

## Why

The owner wants emails and posts to go out steadily while new people join. Two things stop that today.

1. The eighth month was entered with two candidate dates for every Sabbath, so every Sunday and every Monday from 18 October to 9 November is blocked. The weekly email (e2) goes on Mondays, so it has been skipped every week since 19 October. Nothing is known after 9 November, so from 10 November every post and campaign email is refused.
2. When the weekly email's day is a rest day, that week gets no email at all.

## The dates

Read from the owner's Biblical Calendar Engine account (biblecalendar.app, calendar view, anchored to America/Barbados) at 02:50 Barbados time on 26 October 2026. The owner confirmed them in chat the same morning. The app marks both months as projected.

| Month | Day 1 | Sabbaths (lunar days 8, 15, 22, 29) |
|---|---|---|
| Eighth | Sun 11 Oct 2026 (30 days, to 9 Nov) | 18 Oct, 25 Oct, 1 Nov, 8 Nov (Sundays) |
| Ninth | Tue 10 Nov 2026 (29 days, to 8 Dec) | 17 Nov, 24 Nov, 1 Dec, 8 Dec (Tuesdays) |

The app's home screen still read "Day 15, Sabbath (est.)" at 02:50 on Monday 26 October, while its month grid puts day 15 on Sunday 25 October. We follow the grid, which the owner confirmed.

## Changes

### 1. The rest-day calendar (both repos, kept identical)

- `ahavah-api/service/spotlight/restdays.py`: remove 19 Oct, 26 Oct, 2 Nov and 9 Nov. Keep 18 Oct, 25 Oct, 1 Nov and 8 Nov. Add 17 Nov, 24 Nov, 1 Dec and 8 Dec. Set `KNOWN_THROUGH` to 8 Dec 2026. Update the comment: the eighth month is no longer provisional.
- `ahavah-admin/src/lib/rest-days.ts`: the same dates and the same `KNOWN_THROUGH`. `tests/rest-days.test.mjs` already fails if the two disagree.
- `ahavah-api/docs/marketing/feast-dates-2026.md`: replace the provisional section with the table above and its source line.

### 2. The weekly email moves to the next free day

Today `is_send_window` is true only on the send weekday (Monday) from 12:00 UTC. Proposed:

- Work out this ISO week's nominal slot (Monday 12:00 UTC). If that slot is in a rest period or past `KNOWN_THROUGH`, move it forward one day at a time (12:00 UTC each day) until it is free, up to Sunday of the same ISO week. If no day is free, the week is skipped and the admin says so.
- The window runs from the slot to midnight UTC that day, as now. The existing rest check stays in `_send_once` as a second belt, because a rest period can begin in the evening of the slot's day (17:00 Barbados is 21:00 UTC).
- The campaign id stays `week_campaign_id(now, 'e2')`. A slide never leaves the ISO week, so the id, the dedupe and the admin's Send button all keep working.
- A slide happens only when the nominal day itself is a rest day. A Monday that is free but already past does not slide to Tuesday. This matters on deploy day: the change goes in after Monday 26 October's window has closed, and Tuesday 27 October must not send a weekly email (owner, 26 Oct: start on Monday 2 November).
- `next_send_at` returns the slid slot, so Growth > Emails shows the real next send.

### 3. Deploy timing

Deploy after 00:00 UTC on Tuesday 27 October (20:00 Barbados on Monday). Before then, the freed Monday would open today's window and the weekly email would go out today, which the owner declined.

## Tests

- API: the dates (each Sabbath blocked from 17:00 the evening before to midnight; each freed Monday open; 9 Dec unknown); the slide (Monday free gives Monday; Monday a rest day gives Tuesday; every day blocked gives none); no slide for a free Monday that has passed; `next_send_at` across a slide; the cron sends inside a slid window and not outside it.
- Admin: `rest-days.test.mjs` parity, and `social-calendar.test.mjs` still passes with the booked posts (28, 29, 31 Oct and 4 Nov; none falls on a new rest day).

## What this costs

The dates are the app's projections. If the owner later confirms a month differently, both files change again. The cap rule is unchanged: a member gets at most one campaign email in 7 days (6 for e2), so anyone who gets a hand-sent email between 27 and 30 October skips the 2 November weekly email.
