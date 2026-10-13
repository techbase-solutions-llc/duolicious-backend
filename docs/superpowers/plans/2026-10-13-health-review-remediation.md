Linear: TEC-1829 (W1 TEC-1830, W2 TEC-1831, W3 TEC-1832, W4 TEC-1833, W5 TEC-1834, W6 TEC-1835, W7 TEC-1836, W8 TEC-1837, W9 TEC-1838)

# Health review remediation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every finding in the 13 Oct 2026 health review is either fixed and deployed, built and held for the owner's proof, sent to Claude Design as a brief, or put to the owner as a decision with a recommendation.

**Source:** `docs/audits/2026-10-13-ahavah-health-review.md` (the answer) and `docs/audits/2026-10-13-ahavah-health-review-findings.json` (99 findings, each with evidence as file:line or SQL, the recommendation, effort and whether design or the owner is needed). Finding numbers below are their order in that file.

**Owner instruction, 13 Oct 2026:** "Develop the plans to remediate each of these findings and execute it."

## Global constraints

- Plan before code. This file is the plan; each wave below is executed only as written, and a change of approach is recorded here first.
- No hand-built screens. Any change to how a screen looks, or any new or moved control, goes to Claude Design as a brief (project `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`, folder `briefs/`), and is built only from the export. Logic, data, queries, routing, crons and email plumbing are built directly.
- Nothing new reaches members before a proof reaches the owner (`harrigan.tennyson@gmail.com`, his member account id 18 for push) and he confirms. New or changed member emails, pushes and in-app copy ship behind a switch that is off; the switch is turned on only after confirmation.
- Copy: no em dashes, sentence case, British spelling, Torah-observant believers (never Jewish framing), marriage not dating. Member copy goes through the `ux-writing` skill (in-app) or `humanizer` (emails) before the proof.
- Never nest `api_tx`. No literal `%` in psycopg SQL. Never read message bodies (`mam_message`); counts only.
- API tests: one run at a time against the shared test database (`MSYS_NO_PATHCONV=1 docker compose -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh <paths> -q`). Web: `npx vitest run`, `npx tsc --noEmit`. Admin: `node --test "tests/*.test.mjs"`, `npx tsc --noEmit`.
- Branches: `health-remediation` in each repo. Implementers commit (explicit paths, `Refs: TEC-NN`, git email admin@techbaseltd.com, no attribution trailers) and never push; the controller verifies and deploys.
- Production is read only for implementers. Data corrections (backfills) are scripts the controller runs after deploy.

## The member predicate

Many findings are the same mistake: staff accounts counted as members. One rule everywhere: a member is a `person` whose `roles` does not contain `admin` (`'admin' <> ALL(COALESCE(roles, ARRAY[]::text[]))`). It lives in one SQL fragment in `service/admin/queries/` and every admin, growth, roundup and Spotlight eligibility query uses it.

## Every finding and its disposition

Now: built and deployed in a wave below. Held: built, deployed switched off, proof to the owner, switched on after he confirms. Brief: goes to Claude Design (W8). Owner: a decision or an action only the owner can take (W9). Later wave: planned, not in this round.

| # | Finding | Workstream | Disposition | Remedy |
|---|---|---|---|---|
| 1 | Economy > Entitlement holders returns 500 on every load (timedelta in time_left cannot be JSON-serialised) | W1 | Now | time_left returned as seconds; a test proves every admin response serialises |
| 2 | W41 roundup awaiting approval counts admin account 126 as a new member: stored caption says 4 joined, the t... | W1 | Now | roundup counts exclude admin roles; W41 caption regenerated; approval stays with the owner |
| 3 | Growth email table: 'Recipients' means three different things. For e1, e2, e3 and e6 it is today's cohort b... | W1+W8 | Now (API), Brief (UI) | API returns would-reach-now, last-run-reached and last-run-clicks per campaign |
| 4 | Admin-role accounts (ids 18, 23, 126) are counted as members on Overview, System, Economy, Growth and Moder... | W1 | Now | one member predicate (no admin role) used by every admin query |
| 5 | 'Acted 14 days' is labelled 'Liked or messaged' but also counts passes | W1 | Now | query matches its label: likes or messages, passes excluded |
| 6 | Day buckets differ by tab: Overview uses Barbados time, System, Cohorts and Economy use UTC | W1 | Now | one Barbados-day helper on every tab |
| 7 | Referral click logger resolves only beta_signup codes, so all 87 clicks on member links have no inviter and... | W1 | Now | click logger resolves member codes; backfill of the 87 rows |
| 8 | Growth 'With photo' counts members whose only photos were rejected (men tile shows 37 when only 34 in the s... | W1 | Now | With photo counts approved photos only |
| 9 | Approved photos with no detected face are invisible in Moderation | W1+W8 | Now (API), Brief (UI) | endpoint for approved photos with no face |
| 10 | Publishing queue gives no age or week for cards in review; the W41 roundup has waited 8 days | W1+W8 | Now (API), Brief (UI) | queue rows carry age and week; owner alert after 24h in review |
| 11 | Growth 'Messages 7/30 days' counts first contacts, not messages | W1 | Now | Messages counts messages, not first contacts |
| 12 | Economy ledger table is silently limited to the last 30 days while 3 of its 4 KPIs are all-time | W1 | Now | ledger window and KPIs share one period |
| 13 | Overview charts: empty state unreachable, Premium adds would count test-mode Stripe events, three KPI spark... | W1 | Now | reachable empty state, test-mode Stripe excluded, each sparkline plots its own series |
| 14 | Recent activity shows a time with no date | W8 | Brief | activity time shows a date |
| 15 | Growth tab Emails label 'Dry run sends to the admin address only' is untrue: a dry run sends nothing to any... | W1 | Now | dry run writes nothing; label says what Preview and Dry run do |
| 16 | Beta funnel 'Person' and 'Completed' steps are the same count by construction (both 22), so the funnel has ... | W1 | Now | funnel gets a real onboarding step |
| 17 | System 'API errors' card is a permanent placeholder although an admin route is failing | W8 | Brief | API errors card backed by a real counter |
| 18 | Overview says message content is never read; Moderation > Messages displays message text | W9 | Owner | Moderation shows flagged message text while Overview promises content is never read |
| 19 | 'Pending reports' has no resolved state | W8 | Brief | reports gain a resolved state |
| 20 | Email sends made outside the Send button leave no audit row; email clicks shown nowhere | W1+W8 | Now (API), Brief (UI) | every send writes an audit row; clicks exposed |
| 21 | No list of members someone is waiting on, so the owner cannot choose who to nudge | W1+W8 | Now (API), Brief (UI) | endpoint: members someone is waiting on |
| 22 | The Emails table shows recipients and last sent, never what a send achieved | W1+W8 | Now (API), Brief (UI) | endpoint: per-send results (reached, clicks, returned) |
| 23 | Posts waiting for approval go stale with no alert and no age shown; one missed its slot by 5 days | W1+W8 | Now (API), Brief (UI) | see 10 |
| 24 | No acquisition channel is recorded for 54 of 58 members | W7+W8 | Now (capture), Brief (UI) | first-touch capture; sources view |
| 25 | Clicks on members' own invite links record no inviter, so the per-inviter table misses 87 of 128 clicks (41... | W1 | Now | same fix as 7 |
| 26 | Push subscribers and opt-in rate are not shown anywhere | W1+W8 | Now (API), Brief (UI) | endpoint: push subscribers and opt-in rate |
| 27 | Reports have no working screen, and the Overview card can never clear | W8 | Brief | reports screen |
| 28 | People who start signing up and stop are invisible and cannot be helped | W1+W8 | Now (API), Brief (UI) | endpoint: stuck sign-ups |
| 29 | Engagement has totals but no weekly funnel, so rising likes hide silent conversations | W1+W8 | Now (API), Brief (UI) | endpoint: weekly funnel |
| 30 | No list of members missing a usable photo or verification | W1+W8 | Now (API), Brief (UI) | endpoint: members missing a usable photo or verification |
| 31 | Overview, Growth and the true member list disagree on how many members there are (61, 60, 58). Growth's "Me... | W1 | Now | same member rule as 4; messages counted as messages |
| 32 | A like is invisible to the person who receives it | W3 | Now (push), Held (email) | like push on with push (58); likes-waiting email held for proof (57) |
| 33 | Discover keeps showing members who have left, so new likes go to people who will not see them | W2+W8 | Now (order), Brief (label) | recently active first; away label designed |
| 34 | There is no saved age range, so most decisions are passes on people outside a sensible age band | W2+W8 | Now (server default), Brief (onboarding step) | computed age band is the default deck filter |
| 35 | A tap on the right half of a member's last or only photo records a pass with no warning. Paid single undos ... | W2 | Now | tap past the last photo loops, never passes |
| 36 | The Discover deck serves 10 cards per load, then says "You're all caught up" while more members are queued ... | W2 | Now | deck pages past 10 |
| 37 | The empty deck is a dead end | W8 | Brief | empty deck with a next step and the invite |
| 38 | Profiles with one photo or none are passed almost every time | W3 | Held | one-photo nudge email, proof first |
| 39 | Liked you has no like-back button, and on desktop it sends premium members to a paywall that cannot take pa... | W2+W8 | Now (routing), Brief (like-back) | premium members never routed to the paywall |
| 40 | Passes lapse after 7 days, so on a pool this small members re-pass the same people every week | W2 | Now | pass window 30 days while the pool is small |
| 41 | First-message filters inherited from Duolicious can block a matched member's hello and give the wrong reason | W2 | Now | a matched hello is never blocked by first-message filters |
| 42 | Plan step 1: no attribution is captured anywhere, so 26 of 27 members since August have no source | W7+W8 | Now (capture), Brief (question) | UTM, referrer and codes stored on first touch |
| 43 | Plan step 2: 151 sign-up codes requested in 30 days were never entered, and bot protection is off | W7+W9 | Now (wiring), Owner (keys) | Turnstile and CSP ready; switched on when keys exist |
| 44 | The share image on every page but /marriage-checklist, and on every invite link, calls Ahavah 'the dating app' | W7+W8 | Brief (export) | the existing Open Graph artboard exported at 1200x630 from Claude Design; its stock photo exists only there, so it is not rebuilt in code |
| 45 | Plan step 3: referral links land on a bare form, and the reward is Premium that every member already has | W4+W8+W9 | Brief, Owner | invite landing designed; reward decided by the owner |
| 46 | Meta: nothing has run for 30 days, and conversion tracking was deliberately switched off on 9 Sept | W9 | Owner | F07 Pixel policy; ads restart |
| 47 | Women are the constraint: 19 of 27 members who joined since August are men | W9 | Owner | women-first outreach |
| 48 | Plan step 4: about 50 warm leads from the waitlist and beta never joined | W9 | Owner | personal note to about 50 warm leads (draft supplied) |
| 49 | Plan step 5: assembly, teacher and feast-gathering channels are untouched | W9 | Owner | assembly and teacher channels |
| 50 | Plan step 6: social is 1 non-promotional post a week, held up by approvals, with 6 human clicks ever | W9 | Owner | social cadence; queue alerts from 10 help |
| 51 | The landing page and the /verify screen show made-up figures (2,840 nearby, 2.1x replies, 3.4x matches, 98%... | W7+W8 | Now (true figures), Brief (proof section) | invented figures replaced with live counts |
| 52 | Plan step 7: the sign-up path asks for the email twice, then 15 profile screens before the member sees anyone | W8+W9 | Brief, Owner | shorter sign-up path |
| 53 | The marriage checklist lead magnet has been sent once since July | W9 | Owner | checklist lead magnet schedule |
| 54 | Search content is thin: 3 guides and 1 out-of-date update in an 18-URL sitemap | W9 | Owner | search content plan |
| 55 | The sign-up gate is gone, but stale gate code and old promises are still shipping | W7 | Now | stale gate code and promises removed |
| 56 | All 21 members offline over 30 days have no session; in a browser with no stored token, email links land on... | W3 | Now | sign-in guard with return path |
| 57 | A member who receives a like is never told, and the likes-waiting email exists but is not scheduled | W3 | Held | likes-waiting cron built, off until the owner confirms the proof |
| 58 | The push banner on Discover, Matches and Inbox, and the E3 and E6 emails, promise like alerts, but turning ... | W3 | Now | enabling push turns like alerts on (and for current subscribers who never chose) |
| 59 | E6 could not turn push on for most phone readers: the link opens signed out, and iPhone Safari has no push | none | Refuted | independent verifier showed phone clickers were signed in |
| 60 | E2 weekly email has no personal reason to return: 0 clicks from 53 sends in October | W3 | Held | E2 gains a personal line, proof first |
| 61 | Matches stall with nobody reminded: no follow-up for an unanswered match or message | W3 | Held | match and message reminders, proof first |
| 62 | Unsubscribing from a marketing email silences match, message and like emails | W3 | Now | separate unsubscribe scope for campaigns |
| 63 | Like, match and message emails are not logged, so their return rate cannot be measured | W3 | Now | like, match and message emails logged |
| 64 | No trigger for new members who fit what someone is looking for; E3 is a manual send and ignored waiting likes | W3 | Held | new-fit reason folded into the likes-waiting email |
| 65 | The profile-view email switch does nothing | W3 | Held | profile-view email wired, off until the proof is confirmed |
| 66 | Push shows 'Active on this device' and hides every opt-in prompt whenever the browser holds a subscription,... | W3 | Now | browser subscription resynced to the server |
| 67 | After premium expires, a likes email will lead to a locked list nobody can pay to open | W9 | Owner | Premium expiry and Stripe live |
| 68 | The member referral-intro email, sent by the cron since 1 Oct, reuses the beta body. It tells post-beta mem... | W4 | Held | member body and share text rewritten; cron resumes on confirmation |
| 69 | Invites are offered only on Profile, never where members run out of people to see | W8 | Brief | invite on the empty deck |
| 70 | The share message and framing do not fit a marriage-minded, community-based audience | W8+W4 | Brief, Held (text) | share framing designed; share text in the proof pack |
| 71 | The reward has no felt value today, and the friend's '6 months Premium' is not an invite perk | W9 | Owner | referral reward |
| 72 | The invite landing is a bare sign-up form with no inviter, no explanation and no promised benefit | W8 | Brief | invite landing |
| 73 | Clicks on member invite links are logged with no inviter, so the admin per-inviter table never shows member... | W1 | Now | same fix as 7 |
| 74 | Nobody can tell whether the 32 referral emails were opened or acted on | W4 | Now | referral email links tracked |
| 75 | The inviter is never told when a friend joins or completes their profile | W4 | Held | friend-joined email, proof first |
| 76 | The weekly email mentions invites only in weeks with no new members, and never includes the link | W3 | Held | E2 carries the invite link every week, proof first |
| 77 | 4 members have no personal code; id 49 also has no beta code, so /invite shows 'ahavah.app/i/' with no code... | W2 | Now | missing codes minted; null never shown |
| 78 | Person 27, the only opted-in member who is not an admin, was sent 2 member-of-week cards 2 days apart. Both... | W5 | Now (fix), Held (offer) | why offers stopped is fixed; the next offer to person 27 waits for the owner |
| 79 | Spotlight copy promises "one photo you choose", but no member screen offers a choice: the card page shows o... | W5 | Held | copy says main profile photo until a picker exists |
| 80 | Most members have never been asked: E1 reached 24 people, and the in-app switch is 4 taps deep and appears ... | W5 | Held | E1 resend with fresh tokens to the 34, proof first |
| 81 | Consent is all or nothing: public Facebook and Instagram, with no members-only first step | W8 | Brief | members-only level |
| 82 | The copy raises the fear of being seen without answering it, and says nothing about what the member gains | W5 | Held | consent copy answers the fear, proof first |
| 83 | Opting in from Settings says nothing, and unverified members can opt in and are never featured | W8 | Brief | opt-in confirmation and eligibility message |
| 84 | No alternatives without a face are running: roundups sit unapproved and there is no way to collect quotable... | W8+W9 | Brief, Owner | testimonials collection; roundups approved by the owner |
| 85 | 27 members could be featured today, and nothing shows a personal founding-member ask has been made | W9 | Owner | personal asks (drafts supplied) |
| 86 | No member can see what a card looks like before saying yes | W8 | Brief | card preview before consent |
| 87 | Pushing harder would cost trust with this audience: guardrails on what not to do | W9 | Owner | guardrails recorded in the plan |
| 88 | The only member card ever published is a welcome post for an admin-role account | W5 | Now | admin roles out of Spotlight eligibility |
| 89 | 'Spotlight' also names the paid Boost, which may confuse members | W9 | Owner | Boost versus Spotlight naming |
| 90 | The E1 funnel cannot be measured between sending the email and confirming | W5 | Now | E1 links tracked |
| 91 | Enforce the gate in the API with one predicate, with matches, self-view and admins exempt | W6+W8 | Now (behind a switch, off), Brief (prompt) | one predicate; matches, self and admins exempt |
| 92 | Views list (GET /visitors) shows a member's lowest-position photo whatever its moderation state (rejected, ... | W6 | Now | Views list shows approved photos only |
| 93 | A member's own unapproved photo (pending, held or rejected) shows to them as a normal live photo. Right now... | W8 | Brief | own pending or rejected photo states |
| 94 | Only the browser enforces the photo requirement at sign-up | W6 | Now | server requires a photo to finish onboarding |
| 95 | Members without a photo still appear in other members' decks and on the map | W6 | Now | members with no approved photo leave decks and the map |
| 96 | Photo files are public-read and the image route has no sign-in check | W6 | Later wave | image access planned separately (signed URLs touch every surface and email) |
| 97 | A moderator's approval of a photo with no detected face is not recorded on the photo | W6 | Now | moderator face confirmation recorded on the photo |
| 98 | The face rule checks only position 1, and only when the photo is first scored | W6 | Now | face rule re-checked when the main photo changes |
| 99 | The gate's effect on the 4 members is not measured | W6 | Now | gate effect measured |

## Waves

Each wave is one workflow: one implementer per repo lane (API, web, admin), never two API lanes at once because they share the test database, then an independent reviewer per lane. The controller runs every suite, deploys, verifies in production and records the outcome on the Linear issue before the next wave.

### Wave 1: the numbers, the deck and the way back in

**API lane (W1, findings 1, 2, 4, 5, 6, 7, 8, 11, 12, 13, 15, 16, 20, 25, 31, 73):**
- [ ] Member predicate fragment; apply to every admin, growth and roundup query (`service/admin/queries/*`, `service/growth/queries.py`, `service/spotlight/roundup.py:65` and friends). Test: an admin-role person never changes any count.
- [ ] Economy `time_left` as integer seconds (`service/admin/queries/economy.py:44`); a test calls every `/admin/*` GET route and asserts a 200 with serialisable JSON.
- [ ] One Barbados-day helper (`_BARBADOS_TODAY` in overview.py) moved to a shared module and used by System, Cohorts and Economy.
- [ ] "Acted 14 days" counts likes or messages only; "With photo" counts approved photos only; Growth "Messages" counts messages (rows in `messaged`), not first contacts; ledger window and KPIs share one period; sparklines plot their own series; empty state reachable; Premium adds exclude test-mode Stripe (same livemode rule as paying members); beta funnel gains a real onboarding step.
- [ ] Dry run writes no `campaign_link` rows and no Spotlight nonces; every send path writes an audit row.
- [ ] Referral click logger resolves member codes (`person.referral_code`) as well as beta codes (`service/api/referral_click_route.py:45-47`); `scripts/backfill_referral_click_inviter.py` fills `inviter_email` for past rows (controller runs it after deploy).
- [ ] Roundup counts exclude admins; the W41 roundup row's caption is regenerated through the existing regenerate path (approval stays with the owner).

Added 13 Oct after the Wave 1 review, before the code. "Same fix as 7" under-scoped findings 25 and 73, and the member rule stopped short of the emails:
- [ ] Cohorts per-inviter table rebuilt on code holders (findings 7, 25, 73): `person.referral_code` and `beta_signup.referral_code`, grouped by the holder's address, listed when the intro was sent (`beta_signup` or `email_send_log` campaign `referral`) or the link has clicks or sign-ups. Clicks are counted on the code, well-formed and without bots; Total clicks and Distinct codes leave bots out too, as Overview does. Same output columns, so the admin table is unchanged. The Beta tab's "Intro emails sent" stays the beta cohort's figure, because it sits beside cohort size and never emailed.
- [ ] The member rule applies to every count members read (findings 2 and 4): E2's new members and member total, and the newcomer counts E3 and the push reactivation script share. These are corrections, not new copy. Whether staff accounts (the owner's account 18 among them) keep receiving E1, E2 and E3 is the recipient half and goes to the owner (W9); E6 and the referral intro already leave staff out.
- [ ] The admin hard delete removes the address from `referral_link_click` and `referral`, as the deletion cron does.

**Web lane (W2, W3, W7; findings 35, 36, 39, 55, 56, 66, 77; plus the capture half of 42):**
- [ ] Deck pages past 10 (`src/lib/use-discover-deck.ts:205-219`): follow `next_cursor` (or the API's `n`/`o` paging) before declaring the deck empty. Test with a fake API returning two pages.
- [ ] A tap past the last or only photo loops to the first photo and never records a decision (`src/app/discover/page.tsx:418-424`).
- [ ] Sign-in guard with return path on `/matches`, `/inbox`, `/chat/*`, `/settings/*` using the existing `useRequireSession(returnTo)`; the post-sign-in redirect honours `next`.
- [ ] Push resync: when the browser holds a subscription the server does not, post it to `/notifications/subscribe` instead of reporting "Active on this device".
- [ ] Premium members are never routed to the paywall from Liked you on desktop.
- [ ] `/invite` never shows `ahavah.app/i/` with no code or copies `null`.
- [ ] Stale sign-up gate code and promises removed where they are logic, not layout.
- [ ] First-touch capture: on first load store `utm_*`, `document.referrer` host, `/i/` and `/share/` codes in localStorage (30 day expiry) and send them with onboarding so the API can write `lead_source` (API half in Wave 2).

**Admin lane (W1 display half):**
- [ ] Labels that state what the numbers are (Dry run versus Preview; "Recipients" until the W8 design lands says "Eligible now"); consume the corrected API fields where an existing slot shows them. No new UI.

**Briefs lane (W8):** four briefs written to `ahavah-web/docs/design-briefs/2026-10-13-*.md` (member: Discover and matching; member: referral and Spotlight; member: photos, sign-up and landing; admin: acting on the community) covering findings 3, 9, 10, 14, 17, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30, 33, 34, 37, 39, 42, 44, 45, 51, 52, 69, 70, 72, 81, 83, 84, 86, 91, 93. Mobile first (390, then 768, then 1440), bento rule for dashboards, every state (happy, loading, empty, error). The controller pushes them with DesignSync and gives the owner the one-liners.

### Wave 2: who the deck shows, and the photo gate

**API lane (W2, W6, W7 API half; findings 33, 34, 36, 40, 41, 42, 77, 91, 92, 94, 95, 97, 98, 99):**
- [ ] Deck order: seen in the last 30 days first, then the rest (owner decided 1 Oct that away members stay visible).
- [ ] Default age band: when the client sends no age filter, search uses `search_preference_age` (fail open as the other filters do).
- [ ] Pass window 30 days (`is_deck_suppressed`, migration).
- [ ] First-message filters never block a hello inside a match.
- [ ] Missing referral codes minted for the 4 members; a person row is never left without one.
- [ ] `lead_source` written from the captured first touch at onboarding.
- [ ] Views list (`person/sql/__init__.py:3628-3643`) returns approved photos only.
- [ ] Server requires an approved-or-pending photo to finish onboarding.
- [ ] Members with no approved photo leave decks and the map.
- [ ] `photo.face_confirmed_at` (migration) set when a moderator approves a no-face photo; the face rule re-runs when the main photo changes.
- [ ] Photo gate: `can_view_photos(viewer)` SQL function; the queries that return other members' photos return none unless it is true, the profile is the viewer's own, or the pair has a match or a message. Behind `AHAVAH_PHOTO_GATE_ENABLED` (off) until the W8 prompt screen ships. Admin metric for gated members.

**Web lane:** the capture call wired to the API half; nothing visual.

### Wave 3: messages that bring people back (built, held for proof)

**API lane (W3, W4, W5; findings 32, 38, 57, 58, 60, 61, 62, 63, 64, 65, 68, 74, 75, 76, 78, 80, 88, 90):**
- [ ] Enabling push sets like alerts on unless the member chose otherwise; backfill for current subscribers with no preference row (Now).
- [ ] Campaign unsubscribe scope separate from transactional match, message and like emails (Now).
- [ ] Like, match and message emails go through the outbox and the send log (Now).
- [ ] Spotlight: admin roles out of eligibility; why offers stopped after 22 Sep found and fixed; E1 links tracked (Now).
- [ ] Referral email links tracked (Now).
- [ ] Held, each behind its own switch, off: likes-waiting weekly email (count only, with the new-fit line), match and message reminders, profile-view email, one-photo nudge, E2 personal line and weekly invite link, referral body and share text for members, friend-joined email, E1 resend with fresh tokens to the 34, the next card offer to person 27.
- [ ] `scripts/send_proofs.py` sends one proof of each held email to the owner and one push of each held push to account 18. Nothing else is sent.

**Web lane:** Spotlight strings ("your main profile photo", consent copy that answers the fear) and the share text, on the branch, held until confirmed.

## Owner decisions (W9)

Written to `docs/superpowers/plans/2026-10-13-health-review-owner-decisions.md` with a recommendation and a draft where one helps: Premium expiry and Stripe live (67); F07 Pixel policy and ads (46); Turnstile keys (43); women-first outreach and assemblies (47, 49); a note to the ~50 warm leads (48); social cadence and roundup approvals (50, 84); checklist lead magnet (53); search content (54); referral reward (71); Spotlight personal asks and guardrails (85, 87); Boost versus Spotlight naming (89); message text in Moderation versus the "never read" promise (18); whether staff accounts keep receiving E1, E2 and E3 (2, 4).

## Later wave

Finding 96: photo files are public-read and `/image` needs no sign-in. Signed or session-checked image URLs touch every surface that shows a photo, the emails that embed them and the Spotlight renderer; planned as its own issue after the photo gate is live.

## Verification per wave

- [ ] All three suites green (API full suite, web vitest + tsc, admin node tests + tsc + build).
- [ ] Deploy API (`git push origin health-remediation:ahavah/main`, watch the Actions run), then admin and web (`master`, Vercel READY).
- [ ] Production checks named per finding (for example: every `/admin/*` GET returns 200; Overview reads 58 members; a signed-out visit to `/matches?x` lands on sign-in with `next`).
- [ ] Outcome comment on each Linear sub-issue; state moved only for what is verified.
