Linear: TEC-1845

# Couple tools: the marriage checklist, version 2, and the compatibility game

## Why

Ahavah grows by 2 to 4 members a week and 54 of 58 members came from sources nobody recorded. The owner wants things people use and share without joining first, that bring their email and their friends. Two tools, one page: "For couples and the single season" at `ahavah.app/together` (name to confirm).

## Owner decisions (13 Oct 2026)

- Results may be stored, with consent and a private link.
- Plural marriage stays out of the game for now.
- Screens and share images are designed in Claude Design first.

## Who it is for

- A single person who wants to know what they are looking for, or to see how they compare with someone.
- A courting or engaged couple, or a married couple, who want to compare answers.
- Friends in a group chat who want to see who knows them best.
- Assembly leaders who run marriage preparation (the leader pack, phase 2).

## Identity: light, and only when needed

- Playing needs nothing: no email, no account.
- Saving a result, comparing with someone and getting the share image needs an email confirmed by a 6-digit code. This is the same one-time code and onboardee session the checklist already uses (`POST /request-otp`, `/check-otp`, `expected_onboarding_status=None`), so no new auth.
- Joining Ahavah from a result carries the answers into onboarding: game answers fill the matching profile fields; checklist answers become profile prompt drafts (see the prompts spec).

## Tool 1: compatibility game ("How well do we fit?")

**Format.** About 15 questions in 6 short rounds, one question per screen, about two minutes. Rounds: Sabbath and calendar; the feasts; family and children; home and roles; moving and language; how we talk and decide. Plus 3 light questions that do not score ("Your ideal Sabbath afternoon"), so it feels like a game, not a form.

**Scoring.** Reuses the existing engine (`ahavah-web/src/lib/scoring/compute-compatibility.ts`, 9 axes). Each scored question maps to a profile field the engine already reads, so a game result and a profile score mean the same thing. The plural marriage axis has weight 0 and no question. The rules are ported to Python in the API, with a cross-repo test that both copies give identical scores for the same answers (the pattern the rest-days copy already uses), so a stored result is computed on the server and cannot be tampered with.

**Three modes.**

1. **Me.** Your profile in a sentence plus an archetype from your strongest axes, for example "The Feast Host", "The Steady Builder", "The Family Founder", "The Faithful Student", "The Peacemaker", "The Explorer" (about 8 archetypes; names and lines go through the copy pass and the owner). Share card: the archetype and its line. Identity is what people share; a result that says something about you travels further than a score.
2. **Us.** You send a link to one person (an intended, a spouse, a friend). They play the same questions. Both see a score ring, the 3 areas where you align most, the 2 to talk about, and per-round bars. Nothing shows until both have answered (simultaneous reveal, as couples apps such as Paired do).
3. **Who knows me best.** You answer about yourself, post the link in a group chat, friends guess your answers, and a leaderboard ranks them. This is the format friendship-quiz apps spread with in WhatsApp and Instagram stories.

**Share image.** Every result has a generated image (Next.js `opengraph-image` with `ImageResponse`, the convention the app already uses for `apple-icon.tsx`), drawn from a Claude Design template:

- Link preview: 1200 x 630.
- Story card: 1080 x 1920, saved to the phone for Instagram or WhatsApp status.

It shows first names or initials (the player chooses), the score or the archetype, and the Ahavah mark. It never shows answers. Share text is pre-written ("We are 82% aligned on Ahavah. How well do you fit with someone? ahavah.app/together"), and the link carries UTM tags so first-touch capture records it.

**Calls to action.** On every result, two invitations:

- "Find people who answered like you", which leads to sign-up with the answers carried over.
- "Play with someone else".

Members can also play "Us" with a match from the chat, as a conversation starter.

## Tool 2: marriage checklist, version 2

Today: three sections (scripture with a stance, your own nice-to-haves, challenges). Results are emailed to you and an optional spouse address, and never stored. One send since July.

Changes:

- **Couple mode.** Invite your intended or spouse by link. Each answers privately. The comparison opens when both are done:
  - "Where you agree", item by item, with the importance each person gave it.
  - "Talk about these", for differing stances or importance two or more points apart.
  - Each person's own items side by side.
- **Single mode, "My non-negotiables".** The single's top items become profile prompt drafts if they join.
- **Stored with consent.** Answers are kept behind a private link and the confirmed email. Either person can delete the shared comparison. The checklist's "never stored" line, the privacy page and the API docstring change together.
- **Share image.** Progress only: "We completed the Ahavah marriage checklist: 18 of 22 in agreement", or "I wrote my non-negotiables".
- **Leader pack (phase 2).** A printable version of the checklist and a short guide for assembly leaders and premarital counsellors. It is the thing the events and outreach work hands out.

## Data (API)

New tables (one migration):

- `tool_session`: id, kind (`game` | `checklist`), mode (`me` | `us` | `knows_me` | `couple` | `single`), owner_email, owner_person_id (nullable), owner_display (first name or initials), share_token (unguessable, for the result page), invite_token (for the second player), created_at, completed_at, deleted_at, utm/source.
- `tool_answer`: session_id, player (`owner` | `guest` | guest index for knows_me), question_key, answer (jsonb), answered_at.
- `tool_result`: session_id, score, breakdown (jsonb), archetype, computed_at.

Rules:

- Answers are only readable by the two players through their tokens, and by no admin screen except as counts.
- Rows are deleted 12 months after the last visit, or on request.
- Guests in "knows me" give only a display name.

## API

- `POST /tools/sessions`: start; no auth.
- `POST /tools/sessions/{id}/answers`: no auth, bound to a client token.
- `POST /tools/sessions/{id}/claim`: email and code; stores the result and issues share and invite tokens.
- `GET /tools/r/{share_token}`: public summary for the result page and image; no answers.
- `GET /tools/i/{invite_token}`: the second player's start.
- `DELETE /tools/sessions/{id}`.

Rate limits follow the checklist's (5 an hour per recipient for invite emails).

## Admin

Growth gets a "Couple tools" row: started, completed, emails confirmed, invites sent and accepted, shares (link opens from a share token), sign-ups that came from a tool.

## Measurement

- Completion rate per mode.
- Invite acceptance rate (the viral step).
- Share-link opens per result.
- Sign-ups with `lead_source = tool:*`.

Target for the first 60 days, as an assumption to test: 1 in 5 completed "Us" games brings a new person who also completes.

## Rollout

1. Claude Design brief: the together page, game screens, results for each mode, checklist v2 comparison, both share image templates, mobile first at 390.
2. Game "Me" and "Us" with share images.
3. "Who knows me best".
4. Checklist couple mode.
5. Leader pack.

## Out of scope

- Plural marriage questions (owner decision).
- Public leaderboards across strangers.
- Any display of individual answers on a share image.
- Paid features.

## Risks

- **Sensitive answers.** No answers are ever on public cards, and results are behind unguessable tokens.
- **Spam from invite emails.** Same per-recipient limits as the checklist; Turnstile once keys exist.
- **The archetypes read as horoscope.** Keep them grounded in what the person said, one line each, reviewed by the owner.

## Surfaces, social, scheduler and dashboard

See `2026-10-13-growth-features-surfaces-and-ops-design.md`: the marketing pages and landing sections, the promotion templates in the growth social set, the publishing kinds, the shared lead sources, the admin additions, the privacy work and the build order all live there.
