# Games, gatherings and the Matchmaker inside the app: entry points, sign-up and sharing

Date: 22 Oct 2026 (revised the same day after review)
Status: approved by the owner on 22 Oct 2026 (all suggested defaults). Release 1 in progress.
Refs: TEC-1845

This plan answers the owner’s request of 22 Oct (paraphrased): launch the games, gatherings and the matchmaking service from inside the app without disturbing it and make hosting from the app a different experience from the website. It also decides when someone must sign in, when sign-up is only encouraged and what a lighter sign-up looks like for people who are not looking to marry themselves.

It builds on the read-only audit `docs/plans/2026-10-22-feature-entry-audit.md`. Every code claim used here was rechecked in the code. Line references are in the tables, in section 8, in the brief (section 11) and in the evidence appendix.

## 1. The answer

We suggest keeping the 5 tabs exactly as they are and giving Together, gatherings and matchmaking help one quiet home: a short group of 3 rows on Profile, each shown only while its feature is switched on. Elsewhere they appear only where the member has nothing else to do (the empty deck, an empty Matches or Inbox, a chat with no messages yet) or where they belong to a conversation the member is already having (a chat, another member’s profile), so Discover stays photo first.

Identity follows a ladder: anyone can look, play and read; an email link or code proves an address for one task; a member never sees a code for their own address and never sees a sign-up prompt; and organisers, mentors and families keep their own sign-in, which can later grow into a full profile if they choose to start one with the same address.

Sharing works the same way at every step: a shared link opens without signing in and offers the smallest useful next step (play, RSVP, look). Joining is suggested once, after the person has had something. The biggest gap is the organiser, who today has no way to share a gathering from Ahavah at all, so we suggest an organiser share kit that promotes their gathering and never Ahavah.

Every new entry in the app ships dark behind one new switch with an owner-only list, so the owner sees it working on his own account before any member does. Today’s feature switches are all on in production, so without this the entries would reach every member the moment they deploy.

One bug comes first. When a signed-in member asks to host or signs in as a mentor on the same device, the app throws away their session and they are signed out. That fix needs no new design and ships before anything else.

## 2. What we need from you

8 decisions. Each has our suggestion first and the alternative second.

1. Where the features live. We suggest no sixth tab and one group of 3 rows on Profile. The alternative is a sixth tab on all three surfaces, or a second short list under the tabs on desktop only.
2. The Invite card. We suggest keeping “Share Ahavah” as its own card, since it is an approved design. The alternative is folding it into the new group to shorten Profile on a phone.
3. Approval for members who host. We suggest members go through the same approval as everyone else. The alternative is that verified members publish without waiting.
4. Guests sharing a gathering. We suggest “Bring someone with you” on the confirmed page for every guest and “Send to a match” for members, sharing only the gathering link, never who else is going. The brief for the confirmed page’s join block has already gone to Claude Design and does not mention it, so we suggest drawing “Bring someone with you” in a follow-up brief once that design is back. The alternatives are to send a one-line addendum to the brief already sent (with your approval) or to leave guest sharing out and rely on the organiser kit.
5. Results of a game started from a chat. We suggest these stay private between the two, with no public “how aligned we are” share, since it would show a courtship in progress. The alternative is to offer the same share as any other result.
6. Credit for members’ game shares. We suggest a member’s shared result carries their referral code, so they are credited if a friend joins. Each friend who joins earns the member 5 tokens and 30 days of Premium, the same as any referral. It needs web work: the public result page must keep the code from the link, which today is kept only from invite links. For reporting, we suggest the sign-up stays counted as a game share, as it is today, and the code is used only for the credit. The alternative is to keep the share’s own credit only.
7. The light sign-in. We suggest one page, “Your Ahavah”, for organisers, mentors, recommenders and gathering guests, with a name that avoids the word “account” so nobody thinks they have joined. It needs a new short-lived sign-in for people who hold no role (section 5). We suggest no matchmaker role that can browse, because nothing below a member ever sees a member. The alternatives are a matchmaker role limited to the singles they recommended (they see whether those singles joined and can suggest introductions between them only), or no page at all, with each role signing in on its own as today.
8. Trust guards. We suggest that a mentor who later joins and the singles who invited them never see each other in Discover, and that a person who recommends a single is never told whether that single joined (unless you choose the limited matchmaker role in decision 7). The alternative is to treat them like any other members and senders.

## 3. Where each feature lives in the app

### The new entry switch

The feature switches were read from the public status routes on ahavah.app on 22 Oct 2026:

| Route | Answer |
|---|---|
| `/tools/status` | live on, invite_email on |
| `/events/status` | live on, list on, hosting on, invite off |
| `/matchmaker/status` | live, alerts, introductions, mentors and visitor_alerts all on |

So a new entry tied only to its feature switch would show to every member the moment it deploys. We suggest one new switch, `app_entries`, with 3 settings: off, owner only (an allow list of member accounts) and on. It is set the way the other switches are, in the server’s settings, with a restart. The public status routes cannot tell who is asking, so the app reads it through a member-only request that answers yes when the switch is on, or when it is set to owner only and the member is on the list. This is an API change with no database change. Every new entry below follows its feature switch and `app_entries`; the existing entries keep their own switch alone.

### No tab is added

We suggest no sixth tab. The phone tab bar, the tablet rail and the desktop sidebar all draw from one list, so a sixth tab changes all three at once. On a phone the bar is a floating pill about 380 px wide, and a sixth target makes every tab narrower, including Discover, Matches and Inbox, which members use every day. We also expect gatherings, the game and introductions to be occasional for any one member, though we have not measured it. The rail on the owner’s 800 px tablet stays as approved.

| Surface | Change | Switch |
|---|---|---|
| Phone tab bar (below 600 px) | None. No new tab, no badge for these features | none |
| Tablet rail (600 to 1279 px) | None. The member photo at the foot of the rail could open Profile, as a small tidy-up | none |
| Desktop sidebar (1280 px and up) | None. The “You” block could open Profile, as on the rail | none |

### Profile: the home for all three

A group of 3 rows, working name “More from Ahavah”. On a phone it sits after the Boost and Invite cards and before the Edit profile row. From 600 px up it sits in the left column straight after the Invite card. On the owner’s tablet held upright (706 px) Profile is a single column, so this keeps the group near the top; from 1024 px (the tablet on its side and desktop) Profile has 2 columns and the group stays under the Invite card on the left. When every switch below is off, the group is hidden and Profile looks as it does today.

| Row (intent, copy to come from the design round) | Opens | Shown while |
|---|---|---|
| Together: the game and the marriage checklist | The Together page inside the app’s frame | `/tools/status` live and `app_entries` |
| Gatherings: find one, your places, host one | A new “Your gatherings” screen inside the app (Going, Hosting, Find a gathering) | `/events/status` live and list, plus `app_entries`. The Hosting part also follows hosting |
| Matchmaking help: your alert, introductions, recommend a single, your mentor, share the families page | A new short page that gathers what already exists | `/matchmaker/status` live and at least one of alerts, introductions or mentors, plus `app_entries` |

Each row may carry one small status line, for example “1 upcoming” or “Your alert is on”, so the member sees where things stand without opening it. No count or dot appears on the Profile tab.

The Invite card (“Share Ahavah”) stays where it is (decision 2).

### Settings

| Row | Change | Switch |
|---|---|---|
| Your mentor | None. Already there while mentors are on | `/matchmaker/status` mentors (exists) |
| Notifications | In release 4 only, one toggle per new push | each toggle follows its push’s switch (section 9, release 4) |

No feature rows are added to Settings. Settings is for how the account behaves, and these are things to do.

### Matches

| Entry | Change | Switch |
|---|---|---|
| Introduction cards at the top | None | `/matchmaker/status` introductions (exists) |
| Empty Matches (no matches yet) | New, release 2. One row under the empty state: the gathering row when one is near, otherwise the game row. The same component as the empty deck’s rows | gathering row: `/events/status` live and list, plus `app_entries`; game row: `/tools/status` live and `app_entries` |

Nothing is added to Matches while the member has matches.

### Inbox and chat

| Where | Entry | Status | Switch |
|---|---|---|---|
| Inbox list with conversations | Nothing | | |
| Empty Inbox (no conversations) | One row under the empty state, chosen as on empty Matches | New, release 2 | as on empty Matches |
| A chat with no messages yet | “Play Us together”, one quiet line below the hello line or the shared question, gone once a message is sent | New, release 2 | `/tools/status` live and `app_entries` |
| Chat > More | Play Us together | Exists | `/tools/status` live |
| Chat > More | Share with your mentor | Exists | `/matchmaker/status` mentors |
| Chat > More | Go through the marriage checklist together | New, release 4. Same flow as the Us game: start, save, open with the chat attached | `/tools/status` live and `app_entries` |
| Chat message box | A gathering link put into the box from the gathering’s page (“Send to a match”) | New, release 3, decision 4 | `/events/status` live and `app_entries` |

### Discover, empty deck only

While there are people to see, Discover shows the photo card and its action row and nothing else, on every size (approved 22 Oct). These entries appear only once the deck is empty.

| Entry | Change | Switch |
|---|---|---|
| “See how well you and a friend fit” (the game) | Exists, but today it shows only when member alerts are also on. We suggest it follows Together’s switch alone (fix 7) | `/tools/status` live |
| One gathering row: the next gathering in the member’s region, or “See gatherings” | New, release 2. One row at most | `/events/status` live and list, plus `app_entries` |
| People waiting, alert, map, Share Ahavah, Adjust filters, See passes again | Unchanged | as today |

Today the empty deck’s card holds up to 5 rows (people waiting, alert, map, Share Ahavah, the game). We suggest the gathering row does not make it longer: at most 5 rows, in this order of priority: people waiting, alert, gathering, game, Share Ahavah, map. When all 6 would show, the map row gives way, since Map is already a tab.

### Another member’s profile

| Entry | Change | Switch |
|---|---|---|
| More > Suggest an introduction | None | `/matchmaker/status` introductions (exists) |

### Public feature pages, when a member opens them

Today the Together pages, the gatherings list, a gathering page, the RSVP pages, the host pages, the families page and the alert pages all show the website’s header with “Sign up”, and a member has no way back into the app except the logo. We suggest that the pages a member reaches from the app open inside the app’s frame: the tab bar on a phone, the rail on a tablet and the sidebar on desktop, with a back action to where they came from (falling back to Profile). The weekly question’s answer page already works this way.

The difficulty is that the session lives in the browser, so the server does not know a member is there when it draws the page. A neutral first frame with no “Sign up”, swapped after the page loads, would cost too much: every visitor and every search engine would lose “Sign up” until the scripts run, and a member would see the whole page jump from the website’s frame to the app’s on every visit.

We suggest the cheaper route. Every in-app entry links to the same public page with a marker the server can read (working form `?in=app`). With the marker, the server draws the app’s frame from the first byte. Without it, visitors and search engines get the website’s frame with “Sign up”, as today. Only a member who arrives from outside the app (an email, a shared link) sees the header change after the page loads, and then only the header changes: their avatar replaces “Sign up”. The marker only appears on entries the member is allowed to see, so it follows `app_entries` without the server needing to know who is asking.

| Piece | Switch |
|---|---|
| The app’s frame on a public page (with the marker) | the page’s own feature switch and `app_entries` |
| The member header after load (no marker) | the page’s own feature switch and `app_entries` |

“Sign up” is never shown to a member once the device knows them.

## 4. Hosting from the app versus the website

An organiser on the website is usually a fellowship leader who will never join. A member in the app is already known. The two flows should reflect that.

| Step | On the website (visitor or organiser) | In the app (member) |
|---|---|---|
| Way in | Landing “Host”, the gatherings list’s empty state | Profile > Gatherings > Host a gathering |
| Prove the address | 6-digit email code | None for the member’s own address. The API already accepts a signed-in member’s session for this request (`service/api/events_routes.py:84-108`) |
| Name and address | Typed in | Name filled from the profile and editable, since the host is often an assembly. The account’s address is used, with “Use a different email” for a church or ministry address. That address is proved with the usual code, which runs without touching the member’s session |
| Getting back in later | An emailed organiser link, kept on that one device, valid 7 days; “Send me a new link” | From the app on any device: the member’s session opens their organiser access when the addresses match. For a gathering hosted under a different address, see below |
| Approval | Waits for approval | The same queue by default (decision 3) |
| After publishing | Copy link | The share kit (section 7): the phone’s share sheet, story and feed images, a suggested group announcement and copy link |
| Guests | Guests page | The same page inside the app’s frame, from “Hosting” |
| Asked to join Ahavah | Never | Not applicable |

If an organiser joins later, their gatherings appear under “Hosting” when the address matches, with no extra step. Matching by address at the time it is needed keeps a private role separate from the member’s profile and needs no database change.

Matching by address does not cover a gathering a member hosts under a church address: nothing records that the member made it, so it would not appear under Hosting on another device. We suggest storing that one link when the member makes it in the app (one column on the organiser record naming the member), so the gathering follows the member to any device. It adds a migration to release 3. The cheaper alternative is to say plainly in the form that a gathering hosted under another address is managed only through that address’s organiser link. Either way, organisers never see which of their guests are members, as today.

## 5. The identity ladder

### The 5 steps

| Step | What proves it | Exists today as |
|---|---|---|
| 0 None | Nothing (a device token at most) | Browsing, playing Together |
| 1 Email link | A confirm link, no session | RSVP confirm, visitor alert confirm |
| 2 Email code | The 6-digit code | Saving a game result, the families form |
| 3 Role | An organiser or mentor sign-in, proved by a link or a code | Organiser link (7 days), mentor sign-in (30 days) |
| 4 Member | A full profile | Everything behind the 5 tabs |

### Every action and what it needs

“Needs” is the lowest step that keeps the action safe. “Sign-up” says where joining is suggested, and when.

| Action | Visitor needs | Member in the app | Sign-up | Switch |
|---|---|---|---|---|
| Browse gatherings, open a gathering page | None | Member, in the app’s frame | Never asked | `/events/status` live, list; the app’s frame also `app_entries` |
| RSVP | Email link | Confirmed at once | Encouraged after the place is confirmed, as the approved invite-to-join plan sets out | `/events/status` live |
| See my places | The links in my emails | New “Your gatherings” list | Never asked | `/events/status` live, list and `app_entries` |
| Ask to host, manage gatherings | Email code, then role | No code for the member’s own address | Never asked | `/events/status` hosting; the in-app form also `app_entries` |
| Play the game or the checklist | None | Member, saved to the account from the start | Encouraged on the visitor’s own result, once | `/tools/status` live |
| Save a result, invite by email | Email code | No code | Not again on the same screen | `/tools/status` live, invite_email |
| See my past results | The private link in my email | New list on the Together page | Never asked | `/tools/status` live and `app_entries` |
| Visitor alert (“tell me when someone who fits joins”) | Email link | Not applicable (members use their own alert) | Encouraged in the alert email, whose purpose is joining | `/matchmaker/status` visitor_alerts |
| Member alert, suggest an introduction, answer one | Not possible | Member only | Required | `/matchmaker/status` alerts, introductions |
| Recommend a single | Email code on the families page | Member, on the invite page | Never asked of the sender | `/matchmaker/status` introductions |
| Mentor’s view | Role (invite link or code) | No code; member’s session opens it | Never asked | `/matchmaker/status` mentors |
| Open “Your Ahavah” (release 4) | The new address sign-in (below) | Not applicable | Offered as an ordinary row | new `light_sign_in` on `/matchmaker/status` |
| Quick questions, referral, Discover, Map, Matches, Inbox | Not possible | Member only | Required | as today |

One line is firm: suggesting an introduction stays member-only, and nothing below the member step ever sees a member’s name, photo or profile. A matchmaker who is not a member would need to browse the people on Ahavah to suggest anyone, which breaks that line, so we suggest no browsing matchmaker role. The owner named the matchmaker as his example of a sign-up for a different use, so this is decision 7, with a limited role as the alternative.

### The light sign-in (for people who sign up without using the app as a member)

Who it is for: organisers and mentors; parents and friends who recommend a single; gathering guests who want their places in one spot. None of them came to marry.

What it is: one proved address that opens what is held under it. Organisers and mentors already have a sign-in. Recommenders and guests do not: a guest holds only confirm links, and the email code they may have used creates a half-finished sign-up record, which is deleted after an hour without activity and which the app reads as a sign-up in progress. That record cannot open this page.

So the light sign-in needs a new kind of sign-in: a short-lived address session, issued by the email code step when the person asks for “Your Ahavah” and kept apart from the half-finished sign-up record. It is an API change and most likely a migration (a new table or a new token type). If that cost is too high for release 4, the cheaper start is organisers and mentors only, joined through the sign-ins they already have, with guests and recommenders added later.

In release 4 it gets one page (working name “Your Ahavah”, opened by the code or by a link in any role email) that lists what is held under the address: gatherings you host, your places, singles you mentor (first name only), saved Together results, a visitor alert and recommendations you sent (date and count only). It has 2 actions: delete everything under this email and start a matchmaking profile. The page keeps nothing of its own.

Its limits: it never appears in Discover, Map or any count. It never receives news, never sees a member and never fills a profile field. Assembly names and RSVP names may be a church or a family, so nothing from a role is copied into a profile.

Can it become a full profile? Yes, and only by the person’s own choice. “Start a matchmaking profile” opens sign-up with the address filled in and says why the same address matters. The steps that already run when sign-up finishes then bring across confirmed leads, saved Together results, RSVPs and a visitor alert. The roles keep working as before.

Before “delete everything” can be promised, the account erase code must also cover organiser rows and RSVPs by address; today it covers leads, Together sessions and matchmaker data.

## 6. When and how sign-up is encouraged

### The moments

Joining is suggested only at these points, each as one quiet line or button below the main action, never as a sheet or a pop-up:

1. A visitor’s own Together result (exists).
2. A public Together result, below “Play it yourself” (exists).
3. The RSVP confirmed page, the confirm and reminder emails and the single email the day after the gathering, exactly as the approved invite-to-join plan sets out (`ahavah-api/docs/superpowers/plans/2026-10-22-events-invite-to-join.md`). This plan does not change it.
4. The visitor alert email (“Join to see them”).
5. The page a recommended single lands on (release 3, section 7).
6. The light sign-in page’s “Start a matchmaking profile”, as an ordinary row (release 4).

### The frequency cap

- At most one join suggestion per screen.
- On a device, none on the screen that follows another suggestion in the same flow, and none within 24 hours of the last one shown. The note is kept in the browser and the page works normally if it cannot be read.
- The cap does not apply to the 3 surfaces of the approved invite-to-join plan (the confirmed page, the confirm and reminder emails, the email the day after). They keep that plan’s own rules, so its block still shows to every guest who is not a member.
- By email, no new join email is proposed here. For later features we propose a shared once-per-address record that every dedicated invitation to join checks before it sends. The approved plan’s own once-per-address table could be extended to do this, but that widens an approved scope, so it needs its own approval when a later feature asks for it.

### Where it is never shown

- To a member, anywhere. Today every Together result shows “Find people who answered like you” to members as well; that is fixed in release 1.
- Discover while there are people to see.
- Organiser screens and organiser emails. “For leaders” was removed because we do not recruit through organisers, and the share kit promotes their gathering only.
- Mentor screens and mentor emails.
- The families page after a recommendation is sent, and the recommended single beyond the one email that already exists.
- A gathering page before RSVP, and the RSVP form itself.
- Invite emails one player sends to another.
- Anyone who has unsubscribed.

## 7. Sharing

Every shared link opens without signing in. Nothing about another member, an answer or a venue appears in any share.

| Moment | What is shared | Preview | Where a non-member lands | Next step offered | Switch |
|---|---|---|---|---|---|
| A game result (exists) | Story image or link with the score or type | The result’s link image | The public result | Play it yourself; Join Ahavah below it | `/tools/status` live |
| A member’s game result | As above, plus the member’s referral code on the link (decision 6) | as above | as above | as above; the member is credited if the friend joins | `/tools/status` live and `app_entries` |
| A game started from a chat | The private result only, unless the owner chooses otherwise (decision 5) | | | | `/tools/status` live |
| A confirmed RSVP, guest: “Bring someone with you” (decision 4) | The gathering’s page, naming the gathering and day, never the venue | The gathering’s existing link image | The gathering page | RSVP; that guest then follows the approved invite-to-join plan | `/events/status` live and `app_entries` |
| A member’s gathering: “Send to a match” (decision 4) | The gathering link, put into a chat’s message box | as above | Not applicable (a member) | | `/events/status` live and `app_entries` |
| The organiser share kit | Copy link, the phone’s share sheet, a story image, a feed image and a suggested announcement for a WhatsApp or Telegram group | New story and feed images for gatherings (only the link image exists) | The gathering page | RSVP | the kit: `/events/status` hosting and `app_entries`; the images: `/events/status` live |
| A single is recommended | The existing email from the sender | | A new short landing in place of going straight to the sign-up form: who recommended them (first name), what Ahavah is, the game first and joining second | Play; join | `/matchmaker/status` introductions and `app_entries` |
| A parent has sent a recommendation | The families page, to other parents | The families page’s existing preview | The families page | Recommend a single | `/matchmaker/status` introductions |
| Share Ahavah (exists) | The member’s invite link | as today | Sign-up | Sign up | as today |
| An introduction both said yes to | Nothing public. The introducer sees in-app next steps only: suggest another, or recommend a single | | | | `/matchmaker/status` introductions |

The organiser kit goes in 3 places: the email that tells the organiser the gathering is live (today it is the manage email with a note and links only to the manage page), each published row in “Your gatherings” and the gathering’s own host page. The daily guests email gains a quiet “share it again” link. The kit is offered only while a gathering is published, never for a draft, a cancelled or an ended gathering.

“Bring someone with you” is drawn in a follow-up brief on top of the confirmed page’s join block, once that design is back (decision 4 and section 11).

### Measurement

| Loop | Counted today | Missing, and what we suggest |
|---|---|---|
| Game | Admin > Growth: started, completed, saved, links, guests, share opens; sign-ups by tool source; the Sources table by share mode | Member referral credit (decision 6). Share taps are not counted, only opens |
| Gatherings | Admin > Events: views, RSVPs, confirmed and sign-ups per gathering | Which share brought a view or an RSVP. We suggest an optional share tag (host, guest, app, feed) on the page-view count and the RSVP |
| Organisers | Gatherings per organiser | Guests per organiser share, from the same share tag |
| Recommend a single | Recommendations sent, singles joined | A visitor sender on the families page has no source (fix 10) |
| Introductions | Suggested, accepted by both, conversations that followed | Push taps: the tap record accepts only the 3 question pushes, so the introduction and alert pushes cannot be counted (fix 11) |

Before spending on ads, the owner wants to see the game and the Matchmaker working. We suggest:

1. A walkthrough on his phone and the 800 px tablet with `app_entries` set to owner only: each loop from the sharer’s screen to a signed-out second device, ending on the Admin row that moved. Test addresses are already left out of the Growth counts.
2. A few weeks of organic use read as ratios (share opens per finished game, plays from public results, sign-ups per gathering, singles joined per recommendation). He sets the bar; we propose no target.
3. One thing to know before ads go out. An ad visitor who plays and saves a result is credited to the game, because the earliest confirmed lead wins; the ad’s own tag survives only in the record of the person’s first visit, and Meta receives only the completed sign-up. If ads will send people to the game, we suggest reading that first-visit record next to the lead source in Admin.

The switches were read on 22 Oct 2026 (section 3): Together, gatherings (list and hosting) and every Matchmaker part are on in production, and the “For leaders” invite switch is off. No switch today can be turned on for one account, which is why `app_entries` carries its own owner-only list.

## 8. Fixes found on the way

Severity: high means a member can lose their session or see something wrong today; medium means a wrong prompt or a dead end; low means a loose end or a missing count. “No new UI” means the fix uses screens and states that already exist and can ship before any design round.

| # | Finding | Severity | No new UI? | Evidence |
|---|---|---|---|---|
| 1 | Asking to host or signing in as a mentor signs a member out. Both call the shared email-code step, which stores a new session over the member’s and clears the account data on the device. If the member stops at the code or uses a church address, they are signed out; every other open Ahavah tab is sent to sign-in. If they use another member’s address, the device is signed in as that member. The web side was run in a throwaway test (2 of 2 passed); the API side is read from code | High | Yes | `components/events/host-request.tsx:53`, `:68`; `components/matchmaker/mentor-sign-in.tsx:78`, `:97`; `lib/auth-otp.ts:44`; `lib/api-client.ts:65-79` |
| 2 | A member who opens a saved checklist link that their account cannot read is shown the email-code step (same harm as fix 1). The game result already shows “not found” to members instead | Medium | Yes | `components/app/marriage-checklist/checklist-v2.tsx:246`, `:271-272`; `components/together/game-result.tsx:47`, `:93`; `components/together/result-states.tsx:151` |
| 3 | The old checklist’s email step (shown only while Together is off) has no member check | Low | Yes | `components/app/marriage-checklist/checklist-client.tsx:522` |
| 4 | The families page and the Together save step decide “member” from a local flag; if the flag is missing a member gets the code step | Low | Yes | `components/matchmaker/families-recommend.tsx:19`; `components/together/kit.tsx:62-69` |
| 5 | Every Together result asks members to sign up (“Find people who answered like you”); the public result shows “Join Ahavah” to members | Medium | Yes, by removing it for members. The member’s replacement actions come with the design round | `components/together/result-states.tsx:22-34`; `components/together/public-result.tsx:31` |
| 6 | The Together header shows a member’s avatar, but it does not open anything | Low | Yes | `components/together/kit.tsx:49-58` |
| 7 | The empty-deck game row shows only when member alerts are also on | Low | Yes | `app/discover/page.tsx:934`; `components/app/deck-end.tsx:207-213` |
| 8 | The alert email’s “Join to see them” link carries `from=alert`, which the sign-up page ignores. The alert still carries across if the same address is used | Low | Yes for the source; any new sign-up line waits for design | `ahavah-api/service/matchmaker/mail.py:94`; `app/auth/sign-up/page.tsx:166-168` |
| 9 | “For leaders” is already unreachable: the invite switch is off in production, so its page answers “not found” and the gatherings empty-state link and the sitemap entry are hidden. What remains is optional dead-code removal (the page, the empty-state link, the sitemap line and the page’s share template), with no switch change | Low | Yes | `app/invite-ahavah/page.tsx:34-35`; `components/events/events-list.tsx:93-94`; `app/sitemap.ts:37`; `/events/status` read 22 Oct 2026 |
| 10 | A host request and a families-page visitor sender record no source, and the `mentor` source is defined but never written. We suggest they stay out of the lead list (they did not come to marry) and are credited only if they later join: when sign-up finishes, set the source to `mentor`, `host` or `family` if it is still empty, as sources that can never receive news | Low | Yes | `components/events/host-request.tsx:68`; `components/matchmaker/recommend-form.tsx:132`; `ahavah-api/service/leads/sources.py:23` |
| 11 | Push taps can be recorded only for the 3 question pushes. The introduction, both-said-yes and alert pushes each carry a tag (`mm-alert`, `mm-intro-{id}`, `mm-told-{id}`) but no `?src=` value, and the tap record accepts only qpush, mpush and lpush | Low | Yes | `ahavah-api/service/matchmaker/mail.py:277`, `:283`, `:288`; `ahavah-api/duotypes/__init__.py:1065` |
| 12 | The gathering page-view count takes only the gathering, so shares cannot be told apart | Low | Yes | `ahavah-api/service/api/events_routes.py:288-299` |

How we suggest fixing 1 without any new screen: keep the code step exactly as it looks today, but hold the code’s temporary session in memory for that one task and send it only with the host request or the mentor sign-in, never storing it as the device’s session. The member’s session is never touched, and a visitor who hosts no longer has a 6-month half-finished sign-up left on their device. The shared request code deliberately refuses a caller’s own sign-in header, so this needs a small, separately reviewed option. Write the failing test first: a member’s session must survive both code steps, other tabs must not be redirected and the API must still return the member afterwards. Skipping the code for members altogether is part of in-app hosting (release 3), because it changes the form.

## 9. Phasing

### Release 1: fixes with no new UI

Fixes 1 to 8 and 10 to 12, with fix 8’s source handling once the invite-to-join plan’s source carry has landed, and fix 9’s dead-code removal if wanted. Each with tests, deployed with no switch change. The owner checks on his phone and tablet that hosting and the mentor sign-in no longer sign him out, and that his Together results no longer ask him to sign up.

### Release 2: the in-app home, so the owner can see it working

After the first design round. First the `app_entries` switch and its owner-only list in the API, deployed set to off. Then the Profile group, the app’s frame and the member header on the public feature pages, the member’s actions on Together results, the gathering row on the empty deck, the rows on empty Matches and empty Inbox, “Play Us together” in a chat with no messages and “Your gatherings” with the Going list (a new member-only list of the member’s places, which also picks up places booked before joining).

Release 2 deploys dark: `app_entries` is off, so no member sees any of it although the feature switches are on. It is then set to owner only, with his account on the list. The owner plays the game, RSVPs and sets an alert as a member on his phone and tablet, and runs the visitor walkthrough in section 7, before any ad spend. It goes on for everyone only on his word.

### Release 3: hosting and sharing

In-app hosting (no code for the member’s own address, organiser access from the member’s session, the share sheet at the end and the stored link for a gathering hosted under another address if chosen in section 4, which needs a migration), the organiser share kit with the new story and feed images, the “is live” email with the kit, “Bring someone with you” and “Send to a match” if approved, the recommended single’s landing page, the referral code on members’ game shares if approved (with the public result page keeping the code), the Matchmaking help page and the share tags on the counts. Each new entry follows its feature switch and `app_entries`.

### Release 4: the light sign-in and pushes

The “Your Ahavah” page with delete everything and start a matchmaking profile, after the erase code covers organiser rows and RSVPs and after the address session exists (an API change and most likely a migration). Also past Together results following the account, the couple checklist from a chat and 3 new pushes, each with its own toggle in Settings > Notifications and its own switch:

| Push | New switch | Also needs |
|---|---|---|
| A reminder of a gathering you are going to | `push_gathering_reminder` | `/events/status` live |
| New guests for your gathering, at most once a day | `push_new_guests` | `/events/status` hosting |
| Your match finished the game | `push_match_played` | `/tools/status` live |
| “Your Ahavah” page | `light_sign_in` on `/matchmaker/status` | the address session |

No push goes out in a rest period, and none after 9 Nov 2026 until the rest-day calendar is extended.

## 10. What this plan does not cover

- Inviting gathering guests to join: the approved plan `ahavah-api/docs/superpowers/plans/2026-10-22-events-invite-to-join.md`.
- Gatherings in member emails: `ahavah-api/docs/superpowers/plans/2026-10-22-gatherings-in-member-emails.md`.
- Discover’s layout while there are people to see: `docs/plans/2026-10-22-discover-photo-first.md`.
- Recruiting organisers or leaders, or bringing back “For leaders”.
- Matchmaker accounts that can browse members.
- The ads themselves, their audiences or budgets and any change to what Meta receives.
- Extending the rest-day calendar past 9 Nov 2026.
- Admin screens beyond the counts named in section 7.
- Prices, tokens and Premium.

## 11. What the Claude Design brief must cover

The brief goes into the existing Claude Design project (Ahavah, `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`), never a new one. Release 2’s screens go in the first round; release 3 and 4 screens can follow in a second round.

The brief for the confirmed page’s join block (frames 2.10 and 2.11) has already gone: it is saved at `docs/design-briefs/2026-10-22-events-invite-to-join.md` and is in the design bridge registry as `briefs/2026-10-22-events-invite-to-join.md`. It stays as it is. “Bring someone with you” is a follow-up brief, drawn on top of the returned 2.10 and 2.11 once that handoff is back (or a one-line addendum to the sent brief, only if the owner approves it under decision 4).

Out of scope: Discover while there are people to see. Draw nothing there, no row, badge or banner; see `docs/plans/2026-10-22-discover-photo-first.md`.

Screens and states:

1. Profile group of 3 rows with status lines; each row with its switch off; all switches off (group hidden). Three layouts: phone below 600 px, after the Invite card (`app/profile/page.tsx:385-386`); one column from 600 to 1023 px (the owner’s tablet held upright), straight after the Invite card (`app/profile/page.tsx:445`, `:500-501`); and 2 columns from 1024 px up (the tablet on its side at 1186 px and desktop), in the left column after the Invite card, where the left column also holds this week’s question and the hero (`:449`, `:500-501`) and the right column opens with Quick answers and the rows (`:543-547`).
2. Empty deck with the decoupled game row and the one gathering row (`components/app/deck-end.tsx:114-234`). At most 5 rows, in this order: people waiting, alert, gathering, game, Share Ahavah, map; when all 6 would show, map gives way. Draw the full 5-row state and the state with only map and Share Ahavah.
3. The same row component on empty Matches (`app/matches/page.tsx:488-494`, `:1268`) and empty Inbox (`app/inbox/page.tsx:281-285`, `:580-589`): one row under the empty state. And “Play Us together” in a chat with no messages, as one quiet line below the hello line or the shared question (`components/app/chat-thread-view.tsx:360-375`).
4. The app’s frame around the Together pages, the gatherings list, a gathering page, the RSVP pages, the host pages and the families page when opened from the app: top bar and back action, drawn from the first byte. Reference pattern: `app/q/[key]/[choice]/page.tsx:17-24`.
5. The member header on public pages for a member who arrives from outside the app: avatar linking to Profile, a way into the app, no “Sign up”; only the header changes after load (`components/events/events-shell.tsx:36-40`, `components/together/kit.tsx:49-58`).
6. Together results, member version: no sign-up line; “Share” and a way back to Discover or to play with a match (`components/together/result-states.tsx:22-34`).
7. “Your gatherings”: Going, Hosting, Find a gathering; empty, upcoming and past states.
8. In-app hosting: filled form, “Use a different email”, waiting for approval, approved and the share kit as the last step.
9. Organiser share kit on “Your gatherings” rows (`components/events/my-gatherings.tsx:156-190`) and the host page, for published only; the story (1080x1920) and feed (1080x1350) images with a long title and an online version (`lib/share-image/sizes.ts`, `lib/share-image/events-templates.tsx:164-165`).
10. The “is live” email with the page link and the kit, and the guests email’s share link, with titles as pre-rendered images and no type of 20 px or more.
11. “Send to a match”: the match picker and the message box with the gathering link.
12. The recommended single’s landing page.
13. The Matchmaking help page with each block on and off.
14. The couple checklist row in Chat > More (`components/app/chat-more-menu.tsx:66-82`).
15. The “Your Ahavah” light sign-in page, delete everything (confirm and done) and start a matchmaking profile; the code step’s lines saying what we keep, for how long and that no matchmaking profile is created.
16. Push titles and bodies and the Settings > Notifications toggles, as intent only.

Follow-up brief, after the invite-to-join handoff is back: “Bring someone with you” on frames 2.10 and 2.11, ordered with the approved join block and “Add to calendar” (`components/events/rsvp-status.tsx:97-99`).

States for every screen: visitor, light sign-in holder (release 4), member, switch off.

Sizes: 390 first, then 320 checked for sideways scroll, then the tablet at 706x1186 and 800 px wide (the owner’s Android tablet) and turned on its side at 1186x706, then desktop at 1440. Light and dark for each. Every tap target at least 44 px.

Copy: intent only, to be written in the design round and passed through `/copy-pass` and the owner. Sentence case, British spelling, digits, no em dashes, no serial comma, no exclamation marks, no urgency. “Marriage” and “courtship” for the relationship, and none of the house’s banned words. Describe the service, never the reader. The old checklist’s line “This creates a free Ahavah account” (`components/app/marriage-checklist/checklist-client.tsx:581`) must match whatever name the light sign-in gets.

## Evidence

Read on 22 Oct 2026. Web paths are under `ahavah-web/src/`; API paths are under `ahavah-api/`.

- Feature switches in production: `GET https://ahavah.app/api/tools/status` returned `{"invite_email":true,"live":true}`; `/events/status` returned `{"hosting":true,"invite":false,"list":true,"live":true}`; `/matchmaker/status` returned `{"alerts":true,"introductions":true,"live":true,"mentors":true,"visitor_alerts":true}`. Read 22 Oct 2026, 22:24 UTC.
- Switches are environment settings read on every call, on or off for everyone, with no per-account option: `service/campaigns/switches.py:1-17`, `:139-143`; Together’s: `service/tools/__init__.py:33-40`, `service/api/tools_routes.py:31-37`.
- One nav list for all three surfaces: `components/app/nav-tabs.ts:5-11`. Phone bar width `max-w-95`: `components/app/bottom-nav.tsx:43`.
- Breakpoints: md 600 px, lg 1024 px, xl 1280 px: `app/globals.css:36-38`.
- Profile on a phone (Boost, Invite, then rows): `app/profile/page.tsx:385-386`. From 600 px: one column below 1024 px (`md:grid-cols-1`), 2 from 1024 px: `:445`. Left column: question (600 px and up), hero, Boost, Invite: `:449`, `:500-501`. Right column: Quick answers, then the rows: `:543-547`. “Not phone” means 600 px and up: `lib/use-is-desktop.ts:43-44`.
- Empty states: Matches `app/matches/page.tsx:488-494`, `:1268`; Inbox `app/inbox/page.tsx:281-285`, `:580-589`; an empty chat shows the shared question or the hello line: `components/app/chat-thread-view.tsx:360-375`. Empty deck rows: `components/app/deck-end.tsx:114-234`.
- Empty-deck game row tied to alerts: `app/discover/page.tsx:934`.
- Chat More menu (Play Us together, mentor row): `components/app/chat-more-menu.tsx:47-53`, `:66-71`.
- Public pages show “Sign up”: `components/events/events-shell.tsx:36-40`. Together’s member check after mount: `components/together/kit.tsx:62-69`. App-frame pattern: `app/q/[key]/[choice]/page.tsx:17-24`.
- Host request accepts a signed-in session and uses its address: `service/api/events_routes.py:84-108`. Mentor sign-in uses the session’s address when signed in: `service/api/mentor_routes.py:147-164`.
- Organiser link lasts 7 days: `service/events/organisers.py:20`. Mentor sign-in lasts 30 days: `service/matchmaker/mentor_view.py:25`. Nothing ties an organiser to a member: `service/events/organisers.py:63-91`.
- Half-finished sign-up sessions last 6 months: `init-api.sql:400`. The half-finished sign-up record is deleted after an hour without activity when a new code is asked for: `service/person/sql/__init__.py:350-353`.
- Member RSVPs indexed by member: `migrations/0071` line 112. The existing `GET /rsvp/me` returns only the member’s name and address: `service/api/events_routes.py:342-352`.
- “For leaders” answers “not found” while the invite switch is off: `app/invite-ahavah/page.tsx:34-35`; the empty-state link and the sitemap entry follow the same switch: `components/events/events-list.tsx:91-94`, `app/sitemap.ts:37`.
- No share or copy action anywhere in `components/events/` (searched for `navigator.share` and `clipboard`). Gatherings draw only the link image: `lib/share-image/events-templates.tsx:164-165`.
- Together share links carry `utm_source=share`: `lib/together/share.ts:12-15`. The share tag outranks a referral code for the lead source: `service/person/attribution.py:92-95`. The referral credit is a separate step that takes the inviter’s code from the sign-up request: `service/person/__init__.py:461`. A referral is worth 5 tokens and 30 Premium days: `service/referrals/__init__.py:287-288`. Codes are kept only from `/i/` and `/share/`: `lib/first-touch.ts:15-18`, `app/i/[code]/route.ts:36-44`.
- The recommended single’s link goes straight to sign-up: `app/i/[code]/route.ts:36-37`.
- Matchmaker push tags: `service/matchmaker/mail.py:277`, `:283`, `:288`. The tap record’s accepted values: `duotypes/__init__.py:1065`.
- The approved invite-to-join plan’s once-per-address table `lead_join_invite`: `ahavah-api/docs/superpowers/plans/2026-10-22-events-invite-to-join.md:13`, `:42`.
- The invite-to-join brief already sent: `docs/design-briefs/2026-10-22-events-invite-to-join.md`; registry entry `~/.claude/design-bridge/registry.json:168-170`. It does not mention “Bring someone with you” (searched).
- Account erase covers leads and Together sessions by address: `service/hard_delete.py:71`, `:87-93`.
- Finish-onboarding linking steps: `service/person/__init__.py:957-1001`.
- Session bug check: a throwaway test using the actual `lib/auth-otp.ts`, `lib/api-client.ts` and `lib/session-lifecycle.ts` with the network stubbed passed 2 of 2; not kept in the repo.

## Owner's answer (22 Oct 2026)

Asked directly: "Should I build to every suggested answer in all three plans: the 8 in-app decisions, the 11 for inviting gathering guests to join and the 13 for gatherings in the emails?" He chose "Yes, all suggestions". Build to every suggested default here; any he later changes is applied then. He also approved deploying the member sign-out fix once its tests and build pass.

## API build notes (23 Oct 2026, release 2 backend)

This is a copy of `ahavah-web/docs/plans/2026-10-22-in-app-entry-and-sign-up.md`, kept here for the API's build notes. Built on branch `app-entries` from `ahavah/main` 4762b16, dark (`AHAVAH_APP_ENTRIES` defaults to off). No migration.

What was built:

- `service/app_entries.py`: `AHAVAH_APP_ENTRIES` is off, owner or on, and `AHAVAH_APP_ENTRIES_ALLOW` is a comma-separated list of person ids and addresses. Both pass through to the api and the cron in `docker-compose.production.yml`, defaulting to off and empty.
- `GET /app-entries/status` (members only) answers `{enabled}`, with `Cache-Control: no-store`.
- `GET /rsvp/mine` (members only) lists the member's places for Your gatherings > Going: `{upcoming, past, more_upcoming, more_past}`. Each item is `{id, state, party_size, gathering: {slug, title, starts_at, ends_at, tz, tz_label, mode, city, country, cancelled}, place_path}`.
- `GET /rsvp/mine/<id>` (members only) shows one of the member's places exactly as their emailed link shows it.

Rulings made while building:

- `app_entries` is not in `service/campaigns/switches.py`. That registry holds on or off switches, and this one has 3 settings, so it has its own module. Anything other than off, owner or on reads as off. An allow-list entry of digits is a person id and one with an @ is an address, compared after the same normalising `person.normalized_email` uses. Anything else is ignored.
- The compose lines sit after `AHAVAH_SPOTLIGHT_COPY_ENABLED` in both blocks, away from the lines `events-invite-to-join` and `gatherings-in-emails` add, so the branches merge without a conflict.
- The brief asked for each place's token path. A token is stored only as its hash, and issuing a new one would retire the link in the member's email, so no token path can be given. The list gives `place_path` instead, `/rsvp/mine/<id>`, an API path the web can open with the member's session. It is null once the place's view closes (a day after the gathering ends, as the emailed link's does).
- Both routes are gated on `events_live` (they sit under `/rsvp`, so the dark check already answers 404) and on `app_entries`, not on `events_list`.
- Only confirmed places that are not erased show, on gatherings the public may find. A paused gathering, or one sent back for approval, leaves the list until it is back. A cancelled place and a cancelled gathering show with their state; the cancel note does not.
- Upcoming means not yet ended, soonest first. Past means ended, most recent first. Each list is capped (50 upcoming and 20 past) and says when there is more; there is no cursor.
- `tests/test_events_switches.py` now counts 25 gathering routes, the 23 before and the 2 new ones.
