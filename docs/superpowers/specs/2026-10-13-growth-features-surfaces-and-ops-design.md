Linear: TEC-1845

# Growth features: marketing surfaces, social assets, the scheduler and the dashboard

The four feature specs (couple tools, profile prompts, events, matchmaker) each describe their own screens and data. This spec covers what they share and what they were missing when reviewed on 13 Oct 2026: where visitors meet them, the social artwork they need, how they feed the automated post scheduler, how they show on the admin dashboard, the privacy work, and the order to build them.

## Gaps found in the four specs

1. **Marketing surfaces.** None said where a visitor first meets the feature on the website, or what search engines see.
2. **Social assets.** Share images were specified; the posts that promote each feature were not.
3. **Scheduler.** The publishing queue knows five kinds (`welcome`, `roundup`, `member_of_week`, `highlight`, `brand`) and the brand calendar (`ahavah-admin/content/social-calendar.json`) has 7 posts, the last on 4 Nov. Nothing fed events, prompts or the tools into it.
4. **Dashboard.** Each spec named its own admin row, but there was no shared sources view and no text moderation queue for all the new free text.
5. **Privacy.** Stored tool results, RSVP data, mentor access and introductions all need the privacy page, the terms and the deletion path updated before launch.
6. **Measurement.** No shared lead-source names, so the dashboard could not compare a game player with an event guest.
7. **Order.** The specs assumed first-touch capture and dynamic share images existed; neither does yet.

## Marketing surfaces (website, all designed in Claude Design)

- **Landing page sections:**
  - "Try it before you join" (the game and the checklist).
  - "Gatherings near you" (next 3 events).
  - "Not ready? Tell me when someone who fits joins" (visitor alert).

  These replace the invented figures the health review found (finding 51) with things people can do.
- **Pages with their own titles, descriptions, share images and sitemap entries:**
  - `/together`, `/together/game`, `/marriage-checklist` (exists).
  - `/events` and `/e/{slug}`, with schema.org `Event` data so gatherings can appear in Google's event results.
  - `/invite-ahavah` for leaders.
  - `/families`, explaining the mentor role to parents and elders, written as a trust page.
- **Header and footer** link Together, Gatherings and For leaders.
- **Emails:**
  - The member welcome mentions prompts and the game.
  - The weekly community email gains "Gatherings near you" and "Play with your match".
  - The referral share text uses the game as its hook ("See how well you and a friend fit").

  Every changed email is proofed to the owner first.
- **Inside the app:**
  - The empty Discover deck offers the game, an alert and the invite.
  - A match's chat offers "Play Us together".
  - Profile > Edit leads with prompts.

## Social assets (one Claude Design brief, "Growth social set")

Templates the render pipeline fills, in the brand's existing social system (`Ahavah Social Templates.html`, `Ahavah Social Prompts and Values.html`):

- **Game:**
  - 8 archetype cards (feed 1080 x 1350 and story 1080 x 1920).
  - An "Us" score card.
  - The result link preview (1200 x 630).
  - A launch carousel: "Which kind of builder are you?"
- **Checklist:**
  - Progress card templates.
  - A promotion post that reuses the C1 carousel "Ten questions to ask early".
  - The leader pack as a printable PDF.
- **Prompts:** a "Question of the week" post, which is the existing conversation-starter template (D set) filled from the prompt bank, so one artwork system serves both.
- **Events:**
  - An event link preview.
  - A feed card and a story card filled from the event.
  - An "Ahavah will be there" badge.
- **Matchmaker:**
  - "Know someone single? Introduce them".
  - A families explainer carousel.
- **Ads:** a game-hook creative for the US women 25 to 44 test the owner is deciding on (W9). A quiz is a cleaner ad hook than matchmaking under Meta's dating rules.

No stock or staged faces of real members, no captions that rate people, nothing that says dating; the research guardrails (`docs/marketing/2026-09-19-social-content-cadence-research.md`) apply.

## Scheduler

New publishing kinds, each subjectless, rendered from its template and waiting for the owner's approval like every other post:

- `event`: created when an Ahavah-run or approved event publishes; scheduled 10 days and 2 days before; the story variant on the day.
- `prompt`: one "Question of the week" a week, drawn from the prompt bank in rotation, on the slot the brand calendar leaves empty.
- `tool`: a monthly game or checklist promotion from static Claude Design artwork, through the existing brand path.

Every post link carries UTM tags (`utm_source=facebook|instagram`, `utm_campaign={kind}`, `utm_content={slug}`), so first-touch capture credits it. The brand calendar is extended past 4 Nov to a monthly mix where one post in three is an open invitation (finding 50). The owner alert when a post enters review comes from the remediation (findings 10 and 23). Threads stays parked.

## Dashboard (one admin brief, extending the remediation's admin brief)

- **Growth.**
  - A Sources table on one taxonomy, with sign-ups and members who reached a first conversation per source:
    - `tool:game-me`, `tool:game-us`, `tool:knows-me`, `tool:checklist`
    - `event:{slug}`
    - `alert:visitor`
    - `intro`, `mentor`
    - `referral:{code}`
    - `utm:{source}/{campaign}`
  - Rows for Couple tools, Events, Alerts, Introductions and Mentors.
- **Events tab:** organiser and event approvals, invite-Ahavah requests, per-event views, RSVPs, confirmations and sign-ups.
- **Moderation > Text:** one queue for prompt answers, opening questions, like comments, event descriptions and introduction notes.
- **Publishing queue:** shows the new kinds with their week and age.
- **User drawer:** a member's prompts, alerts, introductions and mentor links.
- **Overview funnel:**
  - likes, then matches, then first messages, then replies (finding 29)
  - likes with a prompt comment against likes without

## Privacy and terms

Before the first of these launches:

- The privacy page names each new kind of stored data (tool results, RSVPs, alerts, introductions, mentor links and shared conversations), why it is kept, for how long, who can see it and how to delete it.
- The checklist's "never stored" line changes.
- Terms gain an organiser section.
- Consent wording for the RSVP and alert boxes goes through the ux-writing skill and the owner.

## Order

0. **Remediation finished.** Waves 1 to 3 deployed, held emails confirmed or rejected by the owner, briefs run in Claude Design, W9 decisions taken.
1. **Foundations.**
   - First-touch capture end to end (remediation, findings 24 and 42).
   - One `opengraph-image` helper with the brand's templates.
   - One leads table with consent and source, shared by tools, RSVPs and visitor alerts.
   - The new publishing kinds.
   - The privacy page.
2. Couple tools.
3. Profile prompts and the opening question.
4. Matchmaker step 1 (alerts).
5. Events v1.
6. Matchmaker steps 2 and 3.

## Briefs for Claude Design (written when the specs are approved)

1. Together: the tools pages, game, results and checklist v2.
2. Prompts and the opening question.
3. Events, the invite-Ahavah page and organiser management.
4. Matchmaker: alerts, introductions and families.
5. Growth social set (the templates above).
6. Marketing pages and landing sections.
7. Admin additions.

Every brief: mobile first at 390, then 768, then 1440; bento for dashboards; nothing scrolls sideways on a phone; all states.
