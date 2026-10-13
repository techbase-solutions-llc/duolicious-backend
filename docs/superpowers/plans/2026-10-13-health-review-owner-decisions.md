Linear: TEC-1838

# Owner decisions from the 13 Oct health review

Each item is something only you can decide or do. Each carries a recommendation, what it costs and what I need from you. Findings are numbered as in `docs/audits/2026-10-13-ahavah-health-review-findings.json`.

## Decide before 16 December

### Premium expiry and Stripe (67, 71)

Every member holds free Premium. 14 lose it on 16 December, 13 in January, 11 in February and 12 in March. Stripe is still in test mode, so after expiry nobody can pay to get it back. From then on, the likes-waiting email we are building would send members to a list they cannot open.

We suggest you choose one of these before the end of November:

- **Take Stripe live.** This needs live keys, live prices and a live webhook, plus a check of every entitlement. Allow a day of work after you create the live products. Once Premium can lapse and be bought, the referral reward (30 days per friend) starts to mean something.
- **Extend everyone's Premium to a single date,** for example 30 June 2027, and decide about live payments later. This takes about an hour. The referral reward then stays symbolic until that date.

I need: your choice, and if Stripe goes live, the live keys set on the droplet by you.

## Decide now - Consolidate everyone to a single date next year

### US women as this quarter's focus (47)

19 of the 27 people who joined since August are men, and the typical man has about 2 women in a sensible age band who were active this month. Every woman who joins adds possible matches for 37 men. We suggest aiming the referral asks, the assembly outreach, any ad set and the social copy at US women for the next 90 days. The message "across borders" stays.

I need: yes or no. Yes

### Meta Pixel (F07) and ads (46)

Ads have spent nothing in 30 days. The Pixel was removed on 9 September as a privacy decision (F07), so Meta cannot see sign-ups. We suggest no spend until source capture is live (Wave 2 of this plan). After that there are two options:

- Restore a single consented sign-up signal on public pages only.
- Run without the Pixel and judge ads by our own source counts.

Retry the Meta dating advertiser permission before any spend. If ads restart, we suggest $5 to $10 a day, US women 25 to 44, one ad set, with fresh artwork from Claude Design. As an estimate, not a measurement: 15 to 40 members a month for $150 to $300.

I need: the F07 decision, the permission retry (only you can submit it) and a monthly budget.  Im not making any more investments but you can try the pixel again, if not a workaround somehwow

### Bot protection at sign-up (43)

In the last 30 days, 151 sign-up codes were requested by addresses that never entered them. 61 of those came from 3 IP addresses, mostly between 15 September and 3 October. Codes sent to strangers bring spam complaints, and those hurt delivery of real codes. Turnstile is built into the code and switched off because no keys exist. Wave 1 prepares the page rules it needs.

I need: create a Turnstile widget in your Cloudflare account for ahavah.app (managed mode). Then send me the two keys through the droplet and Vercel environment settings, not in chat, or tell me where they are and I will set them.

### Flagged message text in Moderation (18) i dont think i have a cloudfare account, but if i do i wont want to pay anything more - fix it in a way thats free

Overview tells admins that message content is never read. Moderation > Messages would show the text of auto-flagged rude messages; there are 0 today, so nothing has ever been shown. We suggest showing flagged text to admins, because a moderator cannot judge a report blind, and changing the Overview line to say only flagged messages are visible to moderators.

I need: yes, or the opposite (hide flagged text and keep the promise as it is).

### Spotlight guardrails (87) You Decide

We recommend against all of these:

- Opting members in by default, or a pre-ticked box in onboarding.
- A reminder that keeps coming back, like the push banner.
- Tokens or Premium in return for opting in.
- Approving a card automatically when it lapses.
- Posting any photo without approval of that card.
- Stock or staged faces.
- Captions such as "available".
- Rating polls.

One honest invitation per channel is enough, plus a clear way out.

I need: agreement, so later growth work respects them. This i agree with

### Boost and Spotlight naming (89)

Two referral emails and the boost card call a Boost "a 30-minute spotlight on Discover". We suggest "a 30-minute boost on Discover", so that Spotlight only ever means the opt-in feature.

I need: yes or no. The emails change as part of the referral rewrite you will proof; the card wording changes through Claude Design. Sure ok

## Your hands, with drafts

### A personal note to the warm leads (48)

About 50 people joined the waitlist or beta and never created an account. All are still subscribed, and they have had several scripted emails. We suggest one short plain note from you, asking what stopped them. As an assumption, 2 to 5 of them join, and the answers are useful in themselves.

Draft (yours to change; I send it through Resend only after you approve the final text):

> Subject: A quick question from Ehud
>
> Shalom {first name},
>
> You put your name down for Ahavah earlier this year. The app has been open for a few months now, and {N} believers have joined, most of them in the United States.
>
> I noticed you never made a profile, and I would like to know why. Was it the timing, something on the sign-up screens, or did Ahavah not look like what you were hoping for? A one-line reply is plenty, and I read every one.
>
> If you would like to look again, it is at ahavah.app.
>
> Ehud

### Notes to Spotlight candidates (85) ok

27 members could be featured today. 14 of them were online in the last 30 days, 4 of them women, and none of the women has opted in. Person 27 opted in, was sent 2 cards and both expired unanswered. We suggest a personal note from you to the 14, women included, with an easy no, and featuring each person no more than once a quarter. Send it after the copy fix that says "your main profile photo" is live.

Draft:

> Subject: Would you help us introduce Ahavah?
>
> Shalom {first name},
>
> We are starting to introduce a few members on Ahavah’s Facebook and Instagram, so believers who have not heard of us can see real people here. Each post is one photo of you, your first name, age and country, and nothing else.
>
> Nothing is posted unless you approve that exact card, and you can say no to any card or switch it off at any time. If you would rather not, that is completely fine and changes nothing for you.
>
> If you are willing, turn on Spotlight in Settings, under Privacy, and we will send you a card to look at first.
>
> Ehud

### Roundups waiting for approval (84, 50) ok

Four roundup posts have waited since 5 and 12 October. W41 overstates sign-ups by one; Wave 1 fixes the count and rebuilds that card. We suggest:

- Cancel W40: its slot has passed.
- Approve W41 once it is rebuilt.
- From then on, approve a month of posts in one sitting. The queue will email you when a post enters review.

I need: the approvals in Growth.

### Assembly and teacher outreach (49) ok

There is no system for this; it is founder work. We suggest 3 to 4 hours a week:

- Email 20 US congregations a week, starting in states where members already live. Use a one-page note for assembly leaders; I can draft it when you want it.
- Offer Torah-observant teachers and podcasters a conversation about preparing for marriage, with the marriage checklist as the reason to talk.
- Register for spring 2027 feast gatherings and Sukkot 2027 by March.

I need: a go, and which of the three to start with. i dont know about outreach. i think outrach regarding the events portions shuld be on social, with a nice events platrofmr they can tie into which can even be tied into a torah observant fellowship locator and databate.. this feature needs morethinking through. cold emailing is not a thing i want to do

### Marriage checklist and guides (53, 54)

The checklist has been emailed once since July, and the site has 3 guides. We suggest:

- Make the checklist the thing offered to leaders and teachers.
- Make it the call to action on one social post a month.
- Add one guide a month tied to the biblical calendar, for example preparing for Passover and Unleavened Bread as a single person.

I need: a go. Each guide comes to you for voice before it is published.

## Added after Wave 1 (13 Oct) ok

### Staff accounts and the campaign emails (2, 4)

Your 3 staff accounts (your member account, Admin and Techbase Admin) no longer count as members anywhere on the dashboard or in what members read. They still receive the Spotlight announcement, the weekly community email and the re-invite when those go out. The notifications email and the referral intro already leave staff out. We suggest keeping your member account on the weekly email, so you see exactly what members see, and leaving the other two off.

I need: yes, or a different split. you can scope the accounts but as of right nowits just me using th dashboard

### The retired sign-up host

The workflow that copied every release to the second Vercel project (signup.ahavah.app) was removed in Wave 1. That host sits behind Vercel's own sign-in wall, so no member could reach it, and each release was a build nobody used. The project and its domain still exist in Vercel.

I need: delete the `ahavah-signup` project in the Vercel dashboard when convenient, or tell me to leave it. yeah you can delete

## Added during Wave 2 (13 Oct)

### How a new member found Ahavah, and the privacy page (42)

From Wave 2, when someone finishes sign-up, the app sends the link that brought them (the campaign tags on it, the site that linked to them and any invite code), and later their answer to "How did you hear about Ahavah?". This is how the dashboard will stop showing 54 of 58 members as "unknown". Neither privacy page mentions it today. We suggest adding this line to both:

> When you join, we note how you found Ahavah: the website or campaign link that brought you, any invite code you used and your answer if you tell us how you heard about us. We use this only to see which outreach works. Other members never see it.

The web part is built and held. It goes live with the API part, in the same release, after you confirm the wording.

I need: yes to the line, or your changes. this is fine

### Three chat messages members can see (41)

When a message is not sent, the chat says why. Three of those reasons said the wrong thing, and Wave 2 corrects them. After Wave 2 a member inside a match can no longer meet the second and third; they remain for the cases where they still apply. Changed in-app words wait for your confirmation.

| When | Today | Proposed |
| --- | --- | --- |
| Not matched | You can message each other once you match | Not sent. You can only message people you are matched with |
| Daily limit | You are sending too quickly. Wait a moment and try again | Not sent. You have reached the 24-hour limit on starting new conversations. Try again later |
| Same opening words | You already sent this exact message | Not sent. These exact words were used to start a conversation in the past 7 days. Try your own words |

The short line under each message on a phone changes to match: "(not sent: you are not matched)", "(24-hour limit on new conversations reached)" and "(these exact words were used recently, try your own)". ok

I need: yes, or your changes. Until then these 3 changes stay out of the release.

## Decisions recorded (13 Oct, from the owner's notes above)

| Item | Decision | What happens |
|---|---|---|
| Premium expiry (67, 71) | Consolidate everyone to a single date next year | Every member's Premium moves to 30 June 2027 (the date proposed above). Stripe stays in test mode. |
| US women focus (47) | Yes | Referral asks, social copy and any ad set aim at US women for 90 days. |
| Pixel and ads (46) | No more spend. Try the Pixel again, or a free workaround | Plan a consented Pixel on public pages (or the server-side Conversions API on its own). No budget. |
| Bot protection (43) | Free only; no Cloudflare account | Plan free server-side defences (per-address and per-network code limits, a hidden form field, timing check) instead of Turnstile. |
| Spotlight guardrails (87) | Agreed | Every list item above is a rule for later growth work. |
| Boost naming (89) | Yes | "a 30-minute boost on Discover" in the referral rewrite (proofed) and the boost card (Claude Design). |
| Notes to Spotlight candidates (85) | Yes | Proof to the owner first, sent after the "main profile photo" copy is live. |
| Roundups (84, 50) | Yes | W40 cancelled; W41 (rebuilt, "3 joined from 2 countries") waits for the owner's approval in Growth. |
| Assembly and teacher outreach (49) | No cold email | Outreach goes through social and the events platform. A Torah-observant fellowship locator and directory, tied to events, needs its own thinking before any spec. |
| Staff accounts (2, 4) | Scope them; only the owner uses the dashboard | The owner's member account stays on the weekly email; Admin and Techbase Admin come off every campaign email. |
| Retired sign-up host | Delete | `ahavah-signup` project deleted in Vercel. |
| Privacy line (42) | Yes | On both privacy pages; the first-touch capture is live (web 01d57d7). |
| Chat messages (41) | Yes | Live (web 01d57d7). |
| Instagram links | New rule, 13 Oct | Instagram posts carry no link (API 38811fa); the 3 queued Instagram posts were cleaned. |

Still open: flagged message text in Moderation (18), the note to the warm leads (48) and the checklist and guides plan (53, 54).
