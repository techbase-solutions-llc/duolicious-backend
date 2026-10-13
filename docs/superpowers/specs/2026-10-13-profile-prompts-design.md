Linear: TEC-1845

# Profile prompts and the opening question

## Why

Members like each other (18 likes last week) but rarely talk: 7 matches and 3 two-sided conversations ever. A profile today is photos plus structured answers, so a like gives nothing to reply to. Two proven fixes:

- Prompts a member answers in their own words, which others can reply to. Hinge reports that a like sent with a comment is twice as likely to lead to a date.
- An opening question a match answers as the first message. Bumble's Opening Moves; Bumble reported more chats started and answered, in company figures.

## What members get

**Prompts.**

- Each member picks up to 3 from a bank of about 40 questions written for Torah-observant believers seeking marriage.
- Each answer is up to 200 characters.
- Prompts appear on the Discover card (one, rotating with photos) and on the profile (all three).
- Example prompts (wording through the ux-writing skill and the owner):
  - "How I keep Sabbath"
  - "The feast I look forward to most, and why"
  - "What I am studying in Torah right now"
  - "The home I hope to build"
  - "A verse that carried me through my single season"
  - "My family would describe me as"
  - "Something I am learning to do well"
  - "The way to my heart is" (kept light)
- No prompt about plural marriage.

**Reply to a prompt.** On the Discover card or the profile, a member can like a specific prompt and add a comment of up to 150 characters. The receiver sees the comment with the like in Liked you. If they match, the comment appears at the top of the conversation as "{Name} replied to: {prompt}", so the chat starts with something to answer.

**Opening question.** Each member can set one question of their own, or pick one of 10 suggestions ("What does a good Sabbath look like for you?"). When two members match, the empty chat shows the other person's opening question with a reply box. The reply is sent as a normal first message, quoting the question.

**Onboarding.** One prompt is asked during onboarding (skippable). After that, the existing profile-finish card nudges members until they have 3. People who come from the couple tools start with drafts from their checklist or game answers.

## Data (API)

- `prompt_bank`: key, text, category, active, sort. Seeded by migration; edited by admins later.
- `profile_prompt`: person_id, prompt_key, answer, position (1 to 3), moderation_status (`pending` | `approved` | `rejected`), updated_at.
- `person.opening_question` (text, nullable) with `opening_question_status`.
- `liked.comment` (text, nullable) and `liked.prompt_key` (nullable).

Moderation: answers and comments pass the existing text filters on save. Anything flagged goes to a new Moderation > Text queue (in the admin design brief); approved text shows immediately unless flagged. Old Duolicious `question` and `answer` tables stay empty and unused.

## API

- `GET /prompt-bank`.
- `GET /profile-info` and the Discover and profile payloads gain `prompts` and `opening_question`, for approved text only.
- `PATCH /profile-info` accepts `prompts` (up to 3) and `opening_question`.
- The like endpoint accepts optional `prompt_key` and `comment`.
- `/likes/incoming` returns them.
- A new `GET /conversation-context/{uuid}` returns the like comment and both opening questions for a matched pair; the web renders them above the chat.

Nothing is written into the chat server, so no change to the XMPP side.

## Screens (Claude Design brief)

1. Prompt picker and editor (onboarding step and Profile > Edit).
2. A prompt on the Discover card and on the profile, with a reply control.
3. Reply-with-comment sheet.
4. Liked you card showing the comment.
5. Conversation header with the reply and the opening question.
6. Empty-chat state with the opening question and a reply box.
7. Admin text moderation queue.

Mobile first at 390.

## Measurement

- Share of members with 3 prompts.
- Likes with a comment, and their match rate against likes without.
- Matches with a first message within 48 hours, before and after.
- Two-sided conversations a week.

Target, as an assumption: two-sided conversations from 3 ever to at least 3 a week within 6 weeks of launch.

## Rollout

1. Brief.
2. Data and API with the bank seeded.
3. Profile editor and display.
4. Reply-with-comment.
5. Opening question.
6. Onboarding step and nudges.

## Out of scope

- Voice prompts (later).
- AI-suggested openers.
- Hinge's "Your Turn" limits (the pool is too small; revisit past a few hundred members).

## Surfaces, social, scheduler and dashboard

See `2026-10-13-growth-features-surfaces-and-ops-design.md`: the marketing pages and landing sections, the promotion templates in the growth social set, the publishing kinds, the shared lead sources, the admin additions, the privacy work and the build order all live there.
