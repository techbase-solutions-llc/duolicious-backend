# Ahavah audit, 13 October 2026

Evidence is from code and read-only SQL. Counts exclude admin accounts 18, 23 and 126.

## 1. How Ahavah is doing

Sign-ups are small but steady, and conversation has stalled. 2 to 4 people join a week and likes reached 18 a week, but no message has been sent since 2 Oct and 21 of 58 members have been away over 30 days.

Ever: 7 matches and 3 two-sided conversations. Matches get messages (6 of 7); the stall is before them. Women passed 284 men and liked 30; 58 likes sit unanswered on 20 members. The median man has 2 women in a sensible age band who were online in 30 days. Discover serves 10 cards, then says "You're all caught up" although 14 of 25 members with a deck had more queued (use-discover-deck.ts:216-219). Tapping past a member's last photo records a pass (discover/page.tsx:418-424).

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Page the deck past 10 cards | 14 members cut off | hours | none |
| Tap past the last photo loops back | accidental passes | hours | none |
| Saved age range as the default filter | women like 18% of in-band men, 5% outside | days | design brief, owner |
| Extend Premium or take Stripe live (now test mode) | 14 lapse from 16 Dec | hours | owner |

## 2. The dashboard

Engagement figures are right, but one screen is broken, staff accounts inflate most counts and it shows totals without names to act on. Do not approve the W41 roundup: its caption says "4 joined" when 3 did, because roundup.py:65 counts admin 126.

Economy > Entitlement holders returns 500 on every load (economy.py:44: Flask cannot serialise the interval; API log 2 Oct). Admin accounts make Overview read 61 persons and Growth 2 Spotlight opt-ins (true: 58 and 1). The email "Recipients" column shows the cohort before the frequency cap: E2 reads 59 while the last run reached 50 and a send today would reach 0 (growth_routes.py:76). Overview uses Barbados days, other tabs UTC (1 against 3 sign-ups today). The click logger reads only beta codes (referral_click_route.py:45-47), so 87 of 128 clicks have no inviter.

You cannot see who has likes waiting, what an email achieved (E2: 0 clicks from 53 sends since 1 Oct), post ages (one due 8 Oct goes out 5 days late) or push subscribers (11 of 58).

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Return time_left as seconds; test every admin response | broken tab | hours | none |
| One member rule excluding admins, one Barbados-day helper, label fixes | 61 to 58; tabs agree | days | owner: cancel or correct W41 |
| Click logger reads member codes; backfill 87 rows | 68% of clicks attributed | hours | owner: approve the write |
| Email table: would reach now, last run, clicks, returns | E2's 0 clicks visible | days | design brief, owner |
| "Waiting on a reply" list; age and alert on the review queue | 20 members to nudge; missed slots | days | design brief, owner |

## 3. More sign-ups and traction

Sign-up is open and onboarding loses almost nobody, so the limit is traffic, from sources nobody can see. Measure and plug leaks first, then aim at US women.

26 of 27 members since August have no source: ahavah-web never reads UTM tags or referrers (grep, 0 matches). Meta spent $0 in 30 days and the Pixel has been off since 9 Sep (F07). 151 sign-up codes requested in 30 days were never entered, 61 from 3 IP addresses, with Turnstile off (person/__init__.py:376-380); whether they are bots is not verified. Every invite and almost every page share og.png, which reads "The dating app for people who actually want a partner". The landing page invents "2,840 nearby" (page.tsx:798).

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Store first touch (UTM, referrer, codes); optional "How did you hear about Ahavah?" | 54 of 58 sources unknown | days | design brief, owner |
| New share image saying marriage; true figures in place of invented ones | every shared link | days | design brief, owner |
| Turnstile on with the CSP change; inbox delivery test | 151 unentered codes | hours | owner: keys |
| Your own note to the ~50 waitlist and beta contacts who never joined | assumption: 2 to 5 members | hours | owner writes |
| Referral asks and assembly outreach aimed at US women; ads wait for source capture | 19 of 27 joiners since August are men | week+ | owner time, F07 |

## 4. Getting dormant members back

Nothing tells away members someone is waiting, and an email click lands them signed out on a broken screen. Fix the landing, then send the likes.

All 21 members away over 30 days have no session; the dormancy cron deleted the sessions (autodeactivate2/sql/__init__.py:40-45). Without a token, /matches shows "We couldn't load your matches" (matches/page.tsx:1042) and /inbox shows empty. Like alerts default to off (notifications/__init__.py:53-60): 0 of 58 have like push on. 16 members hold 40 likes that arrived after their last visit. The push banner promises like alerts (push-opt-in-banner.tsx:60); enabling push leaves them off. Unsubscribing from E3, E6 or Spotlight also silences match and message emails (unsubscribe/__init__.py:100-111).

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Sign-in guard with ?next on /matches, /inbox, /chat, /settings | 21 members land where promised | hours | none |
| Weekly likes-waiting email, count only, through the outbox | 16 members, 40 likes | days | owner: approve |
| Enabling push turns like push on | 0 of 58 hear of likes | hours | owner: matrix change |
| Separate unsubscribe scope for campaigns | match emails kept | hours | owner |

## 5. Referral sharing

The link sits on Profile only, the message says just "Join me on Ahavah.", the reward means nothing while everyone holds Premium and the referral email tells members they joined a beta.

One Facebook post by member 32 produced 79 of 128 clicks and 2 of 4 referrals ever. The intro sent to 32 members since 1 Oct says "You were one of the first people to opt into the Ahavah beta" (referral_intro.py:39-41) and its button pre-writes "join the beta" (share/[code]/page.tsx:34-35). The invite lands on a bare sign-up form, and inviters are never told a friend joined (person/__init__.py:917-918).

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Members' own email and share text, no beta | 32 sent, 0 clicks | hours | owner: approve copy |
| Invite prompt on the "all caught up" screen | 3 taps to 1 | days | design brief |
| Share text saying what Ahavah is, for a friend or a fellowship | the one channel that worked | days | design brief |
| Invite landing that explains Ahavah; tell inviters when a friend joins | 35 human hits, 2 entries on 13 Sep | days | design brief, owner |

## 6. Spotlight opt-in

Opt-in is 1 because 34 of 58 members were never asked, the copy promises a photo choice that does not exist, consent is public or nothing and the one yes was never followed up.

E1 reached 24 members on 20 Sep. Person 27 opted in, was sent 2 cards and both expired unanswered; no card has been offered since 22 Sep. The copy says "one photo you choose" (spotlight-copy.ts:17) but the card page has no picker (card/[token]/page.tsx:271-327). 27 members are eligible today, 14 of them online in 30 days.

| Action | Moves | Effort | Needs |
|---|---|---|---|
| Your notes to person 27 and 14 eligible active members | 0 published | hours | owner writes |
| Interim copy "your main profile photo", then a picker | honest consent | days | design brief, owner |
| Plainer consent copy; resend E1 with fresh tokens to the 34 | old tokens expire 20 Oct | hours | owner approves |
| Members-only level before public social | likely the biggest lever (not measured) | week+ | design brief, owner, legal copy |

We advise against default-on, rewards for opting in or repeated prompts.

## 7. Your photo gate proposal

Do it, differently: enforce it in the API, count any approved photo with a face and exempt existing matches and chats. Fix 2 defects first. It affects 4 members, the same 4 under a photo or a face rule.

A browser blur would not work: photo files are public-read and /image needs no sign-in (api/__init__.py:463-491), so the queries must stop returning photos. Women gave profiles with 0 or 1 photo 5 likes and 116 passes. Not verified: the 4 members' activity; they may leave rather than upload.

The design: a SQL function can_view_photos(viewer), true for admins and for anyone with an approved photo whose face_count is above 0, unknown or confirmed by a moderator (new photo.face_confirmed_at). The 12 queries returning others' photos return none unless it is true, the profile is their own, or the pair has a match or message. Gated members keep names, bios, likes and chat, see the existing gradient and get one prompt on Discover, Map, Matches and Views ("being checked" when a photo is held). We suggest gated members also leave others' decks (your decision) and onboarding requires a photo server-side.

First fix the Views list, which shows photos whatever their moderation state (person/sql/__init__.py:3628-3643), and the profile that shows members 49, 113 and 117 their rejected photo as live. About 4 working days plus a design round.

## Recommended next 3 moves

1. Make waiting likes reach people: sign-in guard, weekly likes email, like push on with push. 16 members hold 40 likes nobody can tell them about.
2. Fix the Discover deck: paging past 10 and the tap that passes. Hours of work; every active member hits both.
3. Capture sign-up source, replace the "dating app" share image and turn on Turnstile. 54 of 58 sources are unknown.

## Checked and not a problem

- E6 "opens signed out on phones": refuted; 2 of 3 phone clickers were signed in and changed settings within 22 seconds.
- Overview engagement figures match independent counts.
- 0 referral clicks since 1 Oct is a true zero; the logger works (last click 23 Sep).
- Sign-up is open; 1 unfinished onboarding in 30 days.

One verifier ran a read-only command in the API container (Flask version), outside the SELECT-only rule; nothing changed.