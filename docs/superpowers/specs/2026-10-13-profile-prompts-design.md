Linear: TEC-1845

# Profile prompts and the opening question

## Revision, 16 Oct 2026: fun questions in the app

On 16 Oct the owner asked for the fun questions in the guide to live in the app, as a way for members to fill out their profiles and come back to the app, with push notifications, rather than as a page on the website (paraphrased from his message). The guide stays live at `/resources/fun-questions-to-get-to-know-your-match`. This revision turns its 34 questions into the first release of this spec.

The revision comes from a synthesis of 3 designs and 2 judges on 16 Oct, read against ahavah-api `origin/ahavah/main` at f66a278 and ahavah-web `origin/master` at 72ca8dc. It is a proposal until the owner settles the decisions listed under "Owner decisions" below. The owner asked for a launch section after the design was agreed; it is under "Launch" and was read against the same commits and ahavah-admin as checked out on 16 Oct (42a3fea).

### What changes

1. **Release 1 is quick questions answered with a tap.** One answer bank per member. A new question each week on a card in the app, a catch-up run for new members and anyone behind, a "Quick answers" section on the profile that a viewer unlocks by answering, a meter on the profile-finish card and a shared question in the empty chat of a new match.
2. **Release 1 carries no free text.** Answers are either-or or pick-one choices from fixed options, so nothing a member writes reaches another member before a person can review it. The Moderation > Text queue this spec relies on does not exist and is not in Foundations.
3. **Release 1 adds notifications.** The spec before this revision never said when or how a member hears about any of its features. Release 1 adds a push event kind, `questions`, with 2 triggers and a budget of 1 push per member per question week (Sunday to Saturday, keyed by `question_drop.live_on`), each behind a switch that stays off until the owner has seen a proof on his own device. Email gets one line in Monday's E2, behind its own switch, and no new send.
4. **Everything with free text moves to release 2**, which starts once the text moderation queue exists: written answers (the spec's profile prompts), likes on an answer with a comment, the opening question and drafts from the couple tools. Release 2 also adds the same-answer chip on Discover.
5. **Release 1 has a launch.** A launch email to every member who has not left campaign emails, answerable with one tap from the email and then a sign-in where the browser has no session, a matching one-line push and a series of 4 social posts over 2 weeks. Each goes to the owner as a proof first, and nothing reaches members or social until he confirms.

### What this supersedes in the rest of the spec

| Section | Before this revision | Now |
|---|---|---|
| What members get | 3 written prompts, replies with a comment and the opening question, all at launch | Release 1 is quick questions. The prompts, replies and opening question are release 2. |
| Prompts on Discover | One prompt as a slide in the photo rotation | Nothing on Discover in release 1. The same-answer chip comes first in release 2. Whether a written answer joins the card is decided then. |
| Onboarding | One prompt asked during onboarding, skippable | Replaced by the catch-up run, offered once through the next-action card on Discover. No onboarding screen changes. |
| The nudge | Profile-finish card says "Answer 2 more prompts" until a member has 3 | The profile-finish card gains a meter, "3 of 5 quick answers". |
| Empty chat | The other person's opening question with a reply box | A question both members answer, then "Ask why?". Room stays for the opening question and the introducer's note. |
| Data | `profile_prompt`, `person.opening_question`, `liked.comment` and `liked.prompt_key` at launch | Release 1 adds `prompt_answer`, `question_drop`, `match_question`, `push_tap`, 2 columns on `prompt_bank`, `push_subscription.tz`, 2 columns on `notification_preference` and 1 on `person`. The rest waits for release 2. |
| API | `PATCH /profile-info` accepts prompts | `PATCH /profile-info` takes one field per request (`check_exactly_one`), so answers get `PUT /answers/{key}`. |
| Moderation | Flagged text goes to a new Moderation > Text queue | Release 1 has no free text. Release 2 cannot start until the queue is built. |
| Screens | 7 screens for prompts, replies and the opening question | 7 release 1 screens, plus the launch email with its title image, the page an email answer lands on and 4 social artworks, listed under "Screens". |
| Launch | Not covered | A launch email, a launch push and 4 social posts, each proofed to the owner first. |
| Measurement | Shares of members with 3 prompts | Counts, against a 13 Oct baseline. The 6-week target stays. Launch counts added. |
| Rollout | 6 steps, all at launch | Release 1, its launch, then release 2. |

### What stays

- The owner's approval of this spec on 13 Oct, for the problem and the aim: every new conversation starts with something to answer.
- No question or prompt about plural marriage. This now covers the quick questions too.
- Wording goes through the ux-writing skill and the owner.
- The out-of-scope list.
- The target of at least 3 two-sided conversations a week within 6 weeks of launch, as an assumption.
- Nothing is written into the chat server.

## Why

Members like each other (18 likes a week) but rarely talk: 7 matches and 3 two-sided conversations ever, and no message since 2 Oct (health review, 13 Oct). A profile today is photos plus structured answers, so a like gives nothing to reply to. On 13 Oct, 37 members had been active within 30 days and 11 of 58 had a push subscription.

Two proven fixes, both kept:

- Prompts a member answers in their own words, which others can reply to. Hinge reports that a like sent with a comment is twice as likely to lead to a date.
- An opening question a match answers as the first message. Bumble's Opening Moves; Bumble reported more chats started and answered, in company figures.

The revision adds a lighter first step. Quick questions take one tap, give a profile something to unlock and give a new match a question they have both already answered. They need no moderation, so they can ship before the text queue exists.

## Release 1: quick questions

### What members get

1. **The weekly question.** Each Sunday a "Quick question" card appears as a new kind in `useNextAction`, which renders only on /discover (`discover/page.tsx:255` and `:918`). One tap answers it. Once 5 members have answered, the card shows the split as counts.
   - `selectNextAction` (`next-action.ts:70-79`) shows one primary card and folds every other live kind into "And {n} more" as a link row (`next-action.tsx:222-236`). So a member with a match from the last 72 hours, a hidden profile or a pending verification sees the question only as a row, with no options. Proposed rank: between verification-pending (4) and profile-finish (5) in `NEXT_ACTION_RANK` (`next-action.ts:47-55`), below message-failed, new-match and profile-incomplete. The plan picks the number; rank 7 is vacant but sits below add-city.
   - Proposed: tapping the row, or landing on `/discover?src=qpush` or `?src=lpush`, brings the question card to the top for that visit, with the other kinds in "And {n} more".
2. **The catch-up run.** New members and anyone with live questions they have not answered are offered a run once, through the same card. It is skippable: one tap card at a time, with a progress bar. At launch only the first week's question is live, so read strictly the run has nothing to offer and the meter's 5 takes 5 weeks. Proposed: the run offers every active question from launch, and `question_drop` decides only which question gets the weekly card, push and split (decision 10).
   - Proposed order: when a member qualifies for both, this week's question takes the card first. The catch-up offer takes it on a later visit once that is answered, and this week's question is left out of the run.
   - A declined offer is stored server side, in `person.question_catchup_declined_at`, so it is not made again on another device.
3. **Quick answers on the profile.** Another member's profile shows a "Quick answers" section of chips after the bio. Where the viewer has not answered a question, its chip shows "Answer to see theirs", and answering reveals theirs. Answers the 2 members share are highlighted. Proposed: the member's own profile shows their own Quick answers with a "Change" on each, so past weeks' answers can be read and changed; the catch-up run shows only unanswered questions, and without this nothing would.
4. **The meter.** The profile-finish card gains "3 of 5 quick answers". The answers sit apart from the profile steps and do not count in "{n} steps left". Proposed: while a member has fewer than 5 answers and no other step left, the card stays with the meter alone; its copy is in the brief.
5. **The shared question in a new match.** In a matched chat, both members get the same question. Each answers first, then both answers show with "Ask why?".
   - While the chat is empty, the block takes the place of "Say hello to start the conversation." (`chat-thread-view.tsx:299-302`, shown only when `messages.length === 0`). Once anyone writes, the block stays as the first item in the history, above the messages, and scrolls with them. Otherwise a member whose match wrote before they answered would never see the question.
   - "Ask why?" fills the reply box directly from inside the chat view. The `?prefill=` effect (`:205-217`) runs once on mount and then deletes itself from the URL, so it cannot be reused from inside an open thread. It stays for links that come in from outside the chat.
   - The block leaves room for the opening question and the introducer's note.

### Answer formats

- Release 1 has 2 formats. Either-or has 2 buttons. Pick-one has 3 or 4 options of up to 40 characters each.
- 14 of the guide's 34 questions already have fixed choices. They launch active. The other 20 are open questions; they are seeded inactive and wait for written answers in release 2.
- Release 2 adds an optional "why" of up to 150 characters and written answers to the 20 open questions.
- Judge 1 would have let written answers go live after the bio checks. Release 1 stays taps only, because nothing reviews free text today and public payloads must carry approved text only.
- Cadence is 1 question a week, not the 2 one design proposed: 14 questions at 2 a week would run out in 7 weeks, and the existing pushes already reach these 37 active members.

### The launch question set

All 34 come from the guide, in its 6 groups. The group becomes `category` in `prompt_bank`. Option wording is proposed and needs the owner's approval (decision 2).

Active in release 1, with choices:

| Guide group | Question as the card shows it | Format | Options (proposed) |
|---|---|---|---|
| Would you rather | Would you rather host the feast meal or be the guest who brings dessert? | either-or | Hosting the feast meal / Bringing dessert |
| Would you rather | Would you rather wake up to mountains or the sea? | either-or | Mountains / The sea |
| Would you rather | Would you rather spend a week in a cabin with no signal or a week exploring a city you have never seen? | either-or | A cabin with no signal / A new city to explore |
| Would you rather | Would you rather grow your own vegetables or know every good market stall for miles around? | either-or | Growing vegetables / Knowing every good market stall |
| Would you rather | Would you rather learn a new language or a new instrument? | either-or | A new language / A new instrument |
| Mornings, evenings and how you rest | Coffee, tea or something else? | pick-one | Coffee / Tea / Something else |
| Mornings, evenings and how you rest | Are you up with the sun, or do you do your best thinking after dark? | either-or | Early mornings / Late evenings |
| Mornings, evenings and how you rest | What does the best Sabbath afternoon look like to you? | pick-one | A long walk / A nap / A table full of friends |
| Mornings, evenings and how you rest | When you need to recharge, do you look for people or for quiet? | either-or | People / Quiet |
| Family life and traditions | Big family table or small and cosy? | either-or | A big family table / Small and cosy |
| Little preferences that reveal a lot | Window seat or aisle? | either-or | The window seat / The aisle seat |
| Little preferences that reveal a lot | Are you early, on time or a little late? | pick-one | Early / On time / A little late |
| Little preferences that reveal a lot | Do you plan a trip down to the hour or decide when you get there? | either-or | Planning to the hour / Deciding on the day |
| Little preferences that reveal a lot | City, small town or a long drive to the nearest neighbour? | pick-one | The city / A small town / A long drive to the nearest neighbour |

Each option is written so it reads inside a sentence once its first letter is lower-cased, with no "I" or "my", because the empty-chat block and the answer page set it into lines such as "You both picked {option}." and "What made you pick {option}?". Buttons and chips show it with a capital. The earlier wording ("Grow my own vegetables", "A city I have never seen", "Up with the sun") gave lines like "You both picked Grow my own vegetables."

Two questions are shortened for a tap answer. The guide's "Coffee, tea or something else? How do you take it?" loses its second half, and the Sabbath afternoon question moves its 3 examples into the options. The full wording returns with written answers.

Seeded inactive, for written answers in release 2:

- Favourites: What dish could you cook for guests without looking at a recipe? Which feast food do you look forward to all year? What song have you played so many times you know every word? Which book or album would you hand to a friend who wanted to understand you? What hobby have you always meant to start? What are you surprisingly good at? Which place have you visited that you would happily go back to tomorrow?
- Mornings, evenings and how you rest: What does the first hour of your day look like?
- Describe your ideal: Describe your ideal free day from the moment you wake up. Describe your ideal kitchen table: how big, how many chairs and what usually ends up on it. Describe your ideal trip, including how you would get there. Describe your ideal picnic, right down to what is in the basket.
- Family life and traditions: What family tradition would you love to carry on? Who is the best cook in your family, and what do they make? What feast gathering has been your favourite so far, and what made it so good? Which game always comes out when your family gets together? Do you have a pet, or one you dream of having?
- Little preferences that reveal a lot: Which chore do you secretly enjoy? What is one thing in your home with a story behind it? What small thing always makes your day better?

The longest question is 103 characters, inside the 120-character limit on `prompt_bank.text`.

Proposed first 6 weeks, for the owner to approve or reorder (decision 2): mountains or the sea, window seat or aisle, the best Sabbath afternoon, early or on time or late, host the feast meal or bring dessert, people or quiet.

Keys are shared with the social question of the week (plan Task 11, merged in 8427e56). `queue_question_of_week` posts the active prompt posted least recently, so seeding the 14 as active makes them its pool too. Aligning the social post with the app's `question_drop` is not part of this design.

### Where answers show

- The profile's Quick answers section. The server enforces "answer to see theirs" in `/prospect-profile`.
- The question card, with the split from 5 answers.
- The chat block of a match.
- The member's own profile, to themselves.
- Not on Discover in release 1. Judge 1 wanted the same-answer chip now. It needs a per-viewer join on `Q_CACHED_SEARCH` and would rarely show while members hold few answers, so it comes first in release 2.
- Never to signed-out viewers, on `limited` (hidden) profiles, in push text or in `ahavah_extra`.

### Notifications

Push:

- A new event kind, `questions`, push only, with `push_questions` and entries in `_EVENT_COLUMN`, `_EVENT_DEFAULTS`, `_MATRIX_DEFAULTS`, `PatchNotificationPreferences` and the web's `EVENTS` list.
  - It has no email column. Like `weekly`, its `_EMAIL_COLUMN` and `_EMAIL_DEFAULTS` entries point at the push column and it is never emailed (`service/notifications/__init__.py:364`).
  - In the web, `EVENTS` (`settings/notifications/page.tsx:52-88`) makes `emailKey` optional for this row, and `EMAIL_KEYS` (`:91`), which "Turn off all notification emails" clears, skips it.
  - With no `email_*` column, `_Q_UNSUBSCRIBED['notifications']` and `['campaigns']` in `service/campaigns/__init__.py` and the footer unsubscribe writer (`service/unsubscribe/__init__.py:106-112`), which all list the 5 `email_*` columns, need no change.
  - The default of `push_questions` is decision 11. It decides whether the launch push reaches the 11 members with push or none of them.
- 2 triggers share a budget of 1 push per member per question week. A question week runs Sunday to Saturday from its `question_drop.live_on`. An ISO week ends on a Sunday, so an ISO key would name the week that is ending.
  1. Silent match: 24 hours after a match with no message, once per match, to both members (decision 3). When both triggers are due, it takes priority. Once that question week's push has gone, a silent match gets no question push that week, so no member gets a Sunday question push and a Monday silent-match push. The 3-day `match_reminder` still reaches that match.
  2. Weekly question: Sunday 18:00 local time, only if no silent-match push went that week, and only to members active in the last 60 days who are opted in and have not answered.
- Neither push goes to a member who left campaign emails. Each send skips anyone for whom `campaign_unsubscribed(tx, person_id, 'campaigns')` is true, as `scripts/push_reactivation.py:45` does before a campaign push. The launch push follows the same rule.
- Quiet hours run from 21:00 to 08:00 local. The time zone comes from `push_subscription.tz`, saved at subscribe time, with US Eastern when it is missing.
- Nothing goes on Friday or Saturday; a silent-match push due on either day waits for Sunday. Which rest-day rule applies is decision 1. Under the lunar rule, every Sunday up to 9 Nov is itself a rest day, so no Sunday push can go before then.
- Sends use `send_to_user_safe`, never `notify()`, which falls back to email.
- Each send follows the `_already`, `_log_push`, `held.after_commit` pattern in `emails/reminders.py`, logged in `push_send_log`: campaign `question` keyed by the question week's `live_on` date, and campaign `match_question` with the match id.
- The 3-day gap. `nudged_recently_sql` (`service/campaigns/held.py:49`) reads only `email_outbox`, for the campaigns in `_GAP_CAMPAIGNS` (`held.py:37`).
  - Proposed, as both judges confirmed: `question` and `match_question` join `_GAP_CAMPAIGNS`, and `nudged_recently_sql` also reads `push_send_log` for them. Without the first change the new pushes do not count at all.
  - Only 3 jobs call `nudged_recently_sql`: `likes_waiting_weekly.py:78`, `one_photo_nudge.py:59` and `profile_views_weekly.py:68`. `queue_match_reminders` and `queue_message_reminders` in `emails/reminders.py` do not. So the change holds back only those 3 weekly emails.
  - It has a cost. `one_photo` goes on Tuesday and `profile_views` on Wednesday, both at 12:00 UTC (`WEEKDAY` and `SEND_HOUR_UTC` in `held.py`). Tuesday's falls less than 3 days after a Sunday 18:00 push in any time zone, and Wednesday's does for any member west of UTC+6, which includes the US Eastern default. So every week both would be skipped for every member who had the question push and qualifies for them. The plan's test of the gap covers that loss. If the owner would rather keep those emails (decision 12), the pushes stay out of `_GAP_CAMPAIGNS` and the gap keeps reading only the outbox.
  - Proposed: the weekly push and the launch push are themselves held by the gap. Each checks `nudged_recently_sql` and skips a member queued a gap campaign in the last 3 days. The silent-match push is not held. It goes once per match, 24 hours in, and a hold would lose it.
- Pushes stop after 2 in a row with no visit, until the member returns. One design said 3; 2 wins because these pushes arrive on top of the like, match and message pushes.
- Tags stay stable: `question:{live_on}`, and the silent-match push reuses `match:{id}` so it replaces the earlier match notification. Whether iOS replaces by tag is unverified; the owner's proof should test it.
- URLs carry `?src=qpush`, `?src=mpush` or `?src=lpush`. Nothing records a tap today: the web reads only utm keys into first touch, and `public/sw.js` only opens the URL. So when the web app lands on a `?src=` URL it calls a new `POST /push-taps`, which writes a `push_tap` row (see Data).
- Switches in `SWITCHES` in `service/campaigns/switches.py`, each off by default: `question_push` (`AHAVAH_QUESTION_PUSH_ENABLED`), `match_question_push` (`AHAVAH_MATCH_QUESTION_PUSH_ENABLED`) and `e2_question_line` (`AHAVAH_E2_QUESTION_LINE_ENABLED`), with the 2 launch switches under Launch.
  - Each of the 5 variables also needs its pass-through, in the form `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}`, in both environment blocks of `docker-compose.production.yml` that carry the existing switches: the `api` service (lines 129 to 138) and the `cron` service (lines 297 to 306). Without it a switch can never be turned on.
- Guard rail: if 2 or more members switch the push off in one week, move to a fortnightly push. Switch-offs are counted from `notification_preference.push_questions_off_at` (see Data).
- `match_reminder` already pushes "Say hello to your match" to a silent match at 3 and 10 days (`emails/reminders.py:51`). Its query does not read the gap, so a match that gets the 24-hour question push also gets the 3-day reminder 2 days later, unless the plan also makes `queue_match_reminders` and `queue_message_reminders` read the gap. Proposed: let both go, since they say different things. The plan tests a match that gets both.

Email: one line in Monday's E2 and no new send. Only 11 of 58 members have push, so the card and the E2 line carry most of the reach.

- The line names the question that went live the Sunday before.
- E2 is a live email, and `switches.py` says every new or changed email ships behind its own switch, so the line goes behind `e2_question_line`.
- E2 is a campaigns-scope email, so the campaigns unsubscribe already governs the line. A notifications-scope toggle would be steering a campaign, so release 1 has no `email_questions`.

Draft copy names nobody and carries no answer text:

- Weekly push: "This week's question" / "Mountains or the sea? One tap, then see who picked the same." The card shows counts, not people, so "see who picked the same" may promise more than it gives; the ux-writing pass should check it.
- Silent-match push: "An easy first line" / "Your new match has a question waiting. Answer first, then see theirs."
- E2 line: "This week's question: window seat or aisle? Answer in the app."
- In the app: the card label "Quick question", the lock "Answer to see theirs" and the chat prompt "You both answered. Ask why?"

### Privacy

- Answers live in their own table, and only signed-in members see them.
- A split shows only from 5 answers, so a small count cannot point to a person.
- Lock screens show no names and no answers.
- Before launch, the privacy page names quick answers and the stored time zone.

### Launch

The owner asked for this after the design was agreed. Once release 1 is live, members hear about it through 3 channels: an email, a push and 4 social posts. Each goes to the owner as a proof first: the email to his inbox through `scripts/send_proofs.py`, the push to his own devices only and the posts as previews in the publishing queue, where every post already waits for his approval. Nothing reaches members or social until he confirms. Every line of copy below is proposed and goes through the ux-writing pass and his proof.

**The launch email.**

- Audience: every member who has not left campaign emails, through `unsubscribed_predicate_sql('campaigns', ...)` and `suppressed_predicate_sql` in `service/campaigns/__init__.py`, as the other campaigns select. Members away more than 30 days are included; for them it is a reason to come back.
- It goes once per member ever, as campaign `questions_launch` in `email_send_log`. E2 goes to every member every Monday, so a launch email held to the 7-day campaign cap would be skipped for nearly everyone, as 30 referral intros were from 1 Oct. It joins `SELF_CAPPED_CAMPAIGNS` and is queued `exempt`, as `spotlight_note` is.
- The shell is the standard `emails/base.render`, with `chip`, `button` and `callout` from `emails/base.py` and the campaigns footer and unsubscribe the other campaigns carry.
- The display title is a new title image asset designed in Claude Design, never hand-rolled type: `title-quick-questions.png` (dark ink) and `title-quick-questions-wht.png` (white ink), exported at 2x and placed with `title_image()` at the width the design sets, inside the 360 to 528 px the existing titles use. Alt text "Quick questions." The design brief asks for it.
- Proposed timing: the Sunday the first question goes live, at `SEND_HOUR_UTC` (12:00 UTC), under whichever rest-day rule decision 1 settles. Under the lunar rule every Sunday up to 9 Nov is a rest day, so there is no launch Sunday until the ninth month is read (decision 8). The E2 of the next day, the Monday after the launch Sunday, leaves out its question line for members who had the launch email.
- Content, in order: the title image, a chip, what is new, the first week's question with one button per option, a short "Also new on Ahavah" list and the footer.
- **One tap per option, then sign-in if needed.** Each option button is its own campaign link (`make_campaign_link`, kind `questions_launch`), so clicks count per option. It lands on `/q/{prompt_key}/{choice_key}` in the web app, a path `valid_target_path` accepts. The page saves the answer with `PUT /answers/{key}` only once the member is signed in. A signed-out member goes to sign-in and comes back to the page, as email links have since ahavah-web `0b6834c`. A click alone never records an answer, because mail scanners open links. Proposed: if the member has already answered, the page shows that answer with "Change to {option}" and does not overwrite it. Once saved, the page shows the answered card, with the split from 5 answers, and a way on to Discover.
- **The signed-out path is common.** On an iPhone, an installed web app keeps its sign-in apart from Safari, and a link in Mail opens in Safari. So every iOS push subscriber who taps an option lands signed out and signs in with a code before the answer saves. So do the 21 of 58 members who have been away more than 30 days and have no session. The brief draws this path as the main one on iOS.
- **"Also new on Ahavah"** lists 3 improvements members have not been told about, as the owner named them. Checked on ahavah-web `origin/master` at 72ca8dc:
  - Likes members can see and answer from Liked you. New likes take Premium members to Liked you (`3251bd4`). A card opens the profile, where the member likes back; the card has no button of its own (`src/app/matches/page.tsx:751-756`). Every member holds Premium today and 14 lapse from 16 Dec, so the line stays true for them only until then. The email should go before 16 Dec, or the line changes.
  - Discover no longer stops at 10 profiles (`5b41dbb`, the deck pages past the first ten).
  - Reminders when a match or a message is waiting: `match_reminder` and `message_reminder` in `emails/reminders.py`, switched on in production on 14 Oct.

Draft email copy. It names nobody and carries no answer text.

- Subject: "New on Ahavah: quick questions"
- Preheader: "This week's is mountains or the sea. Tap your answer."
- Chip: "New in the app"
- Body: "Each Sunday a light question now waits for you in the app. Answer it with one tap, and once 5 members have answered you can see how the answers split. On someone's profile, answer the same questions to see what they picked. When you match, you both get one question to answer, so your first message has somewhere to start."
- The question: "This week: would you rather wake up to mountains or the sea?" with the buttons "Mountains" and "The sea", and under them "Tap your answer. We'll save it once you're signed in."
- "Also new on Ahavah":
  - "See who liked you in Liked you, and like them back from their profile."
  - "Discover now keeps going past the first 10 profiles."
  - "A reminder when a match or a message is waiting for you."

The body and the captions below name Sunday. Under decision 1 each such line has an "each week" version, which the brief gives beside it.

**The launch push.**

- One line to members with a push subscription and `push_questions` on, skipping anyone who left campaign emails (`campaign_unsubscribed(tx, person_id, 'campaigns')`, as `scripts/push_reactivation.py` does). Who that is depends on the default of `push_questions`, decision 11.
- It is the launch week's `questions` push: logged in `push_send_log` as campaign `question` keyed by that question week's `live_on`, so it spends the 1-a-week budget and no weekly question push goes that week. Quiet hours, no Friday or Saturday, the 3-day gap and the stop after 2 pushes with no visit all apply.
- Sent with `send_to_user_safe`, tag `question:{live_on}`, to `/discover?src=lpush`, which brings the question card to the top for that visit, so launch taps count apart from weekly ones.
- Proposed timing: Sunday 18:00 local, the day the email goes. Under the lunar rule that waits for a Sunday after 9 Nov (decision 8).
- Draft: "New on Ahavah: quick questions" / "Mountains or the sea? Answer with one tap."

**Switches.** `questions_launch_email` and `questions_launch_push` join `SWITCHES` in `service/campaigns/switches.py`, both off by default (proposed variables `AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED` and `AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED`), each with its pass-through in the `api` and `cron` blocks of `docker-compose.production.yml` as listed under Notifications. They go on only after the owner confirms his proofs.

**The social series.** 4 posts over 2 weeks to promote and explain the feature.

- They are entries in the brand calendar, `ahavah-admin/content/social-calendar.json`, which the daily `social-queue` cron reads and queues in the API for the owner to approve. Each entry names Facebook and Instagram, an image under `assets/social/` at 1080 by 1350 JPEG and `promotional: true`, so none lands on a high day.
- The API appends the post's tracking link on Facebook and leaves the Instagram caption without one (`LINKLESS_PLATFORMS` in `service/campaigns/__init__.py`). So captions carry no link and never say "link below"; they name the app instead.
- Calendar entries carry no target path. ahavah-admin's `social-queue.ts` sends slug, caption, `scheduled_for` and platforms only, so the API falls back to `/` (`spotlight_routes.py:1286`) and each Facebook link lands on the home page, not on the app or the question. Proposed: `CalendarEntry` and the queue call gain a target path, set to `/discover` for these 4 posts. Without it the clicks still count but lead to no answer.
- The calendar refuses any date past `KNOWN_THROUGH` (9 Nov 2026) until the next month's rest days are read. `rest-days.ts` applies the lunar rule to every post, whatever decision 1 says. Under it, `restdays.py` marks both candidate dates of each provisional eighth-month Sabbath as rest days: 18 and 19 Oct, 25 and 26 Oct, 1 and 2 Nov, and 8 and 9 Nov, which is every Sunday and Monday up to `KNOWN_THROUGH`, each from 17:00 Barbados time the evening before. So post 1 can never go on a Sunday before 9 Nov; it goes on the launch day or the next free day. Counted from Sunday 25 Oct, post 1 would slide to Tuesday 27 Oct and post 4 (day 11) would fall on Thursday 5 Nov. A series whose last post falls after 9 Nov needs the ninth month read first.
- The question of the week (plan Task 11, cron `DUO_CRON_QUESTION_OF_WEEK_ENABLED`) stays off for the 2 weeks, so the feeds never carry 2 question posts in one week.
- The artwork is designed in Claude Design as part of the brief, in the style of the conversation-starter cards.

Proposed schedule, counted from the launch day, each post moving to the next day the rest-day rules allow:

| Post | Day | Purpose | Caption (draft) |
|---|---|---|---|
| 1 | Launch day or the next free day | Announcement | Something new on Ahavah: quick questions. Each Sunday a light question waits for you in the app, and you answer it with one tap. Answer the same questions as someone to see what they picked. When you match, you both get one question, so your first message has somewhere to start. Open the Ahavah app to answer this week's. |
| 2 | Day 3, Wednesday | How it works | How quick questions work. 1. A new question arrives in the Ahavah app each Sunday. 2. Tap your answer. Once 5 members have answered, you can see how the answers split. 3. On a profile, answer a question to see their answer. When you match, you both answer the same question, then see each other's. |
| 3 | Day 9, Tuesday | Would you rather, inviting replies | Would you rather spend a week in a cabin with no signal or a week exploring a city you have never seen? Tell us in the comments. There is a new question like this in the Ahavah app every Sunday. |
| 4 | Day 11, Thursday | Weekly question reminder | This week's quick question is waiting in the Ahavah app: window seat or aisle? One tap to answer, then see how members answered. |

Post 3 uses a question outside the proposed first 6 weeks, so it gives away no week of the app. Post 4 names week 2's question and changes if the owner reorders the schedule (decision 2).

## Release 2: written answers, replies and the opening question

This is the spec as approved on 13 Oct, held until the Moderation > Text queue exists. Its order: the text queue, then written answers and pins (folding in the profile prompts below), likes on an answer with a comment, the same-answer chip on Discover and new themed runs. A "both answered" push follows only if the numbers support it.

**Prompts.**

- Each member picks up to 3 from a bank of about 40 questions written for Torah-observant believers seeking marriage. With this revision, the 20 open questions from the guide join the bank for the lighter end of it.
- Each answer is up to 200 characters.
- Prompts appear on the profile (all three). The Discover slide is superseded; see the revision table.
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

**Reply to a prompt.** On the profile, a member can like a specific prompt or answer and add a comment of up to 150 characters. The receiver sees the comment with the like in Liked you. If they match, the comment appears at the top of the conversation as "{Name} replied to: {prompt}", so the chat starts with something to answer. Whether a comment sits behind the Liked you paywall is decision 6.

**Opening question.** Each member can set one question of their own, or pick one of 10 suggestions ("What does a good Sabbath look like for you?"). When two members match, the empty chat shows the other person's opening question with a reply box, beside the shared quick question. The reply is sent as a normal first message, quoting the question.

**Onboarding.** Superseded by the catch-up run. The profile-finish card's meter extends to written answers. People who come from the couple tools start with drafts from their checklist or game answers, never shown to anyone until the member taps.

## Data (API)

Release 1, in the next free migration (0067: 0066 is merged on `ahavah/main` and created `prompt_bank` empty):

- `prompt_bank` gains `format` (`either_or` | `pick_one` | `text`) and `options jsonb`. Seed the 14 choice questions active and the other 20 inactive.
- `prompt_answer(person_id, prompt_key, choice_key, text null, text_status null, created_at, updated_at)`, primary key (person_id, prompt_key). Release 1 never fills `text`.
- `question_drop(prompt_key, live_on date unique)`: the approved schedule.
- `match_question(match_id, prompt_key, offered_at)`, so both members see the same question. Which question is offered is not settled; proposed: an active question neither member has answered, otherwise any active one.
- `push_subscription.tz text null`.
- `notification_preference.push_questions`, with its default set by decision 11. Release 1 has no `email_questions`; see Notifications.
- `notification_preference.push_questions_off_at timestamptz null`, set when a member turns `push_questions` off and cleared when they turn it back on, so switch-offs can be counted by week. Today the table has only `updated_at`, which cannot tell a switch-off from any other change, and only `push_likes` has a stamp of its own (`chosen_at`, migration 0057).
- `push_tap(person_id, src, tapped_at)`, written by `POST /push-taps` when the web app lands on a URL with `?src=qpush`, `mpush` or `lpush`. It feeds the tap counts under Measurement and in Admin > Questions.
- `person.question_catchup_declined_at timestamptz null`, so a declined catch-up offer holds on every device.

The launch adds no table: campaign `questions_launch` in `email_send_log` and `SELF_CAPPED_CAMPAIGNS`, the 2 launch switches, the 2 title images in `emails/assets/` and 4 calendar entries in ahavah-admin, with the target path field proposed under Launch.

Release 2, as the spec had them:

- `profile_prompt`: person_id, prompt_key, answer, position (1 to 3), moderation_status (`pending` | `approved` | `rejected`), updated_at. Whether it folds into `prompt_answer` (using `text` and `text_status`) is decision 4.
- `person.opening_question` (text, nullable) with `opening_question_status`.
- `liked.comment` (text, nullable) and `liked.prompt_key` (nullable).

Old Duolicious `question` and `answer` tables stay empty and unused.

## Moderation

Release 1 carries no free text, so it needs no queue. In release 2, answers and comments pass the existing text filters on save, and anything flagged goes to a Moderation > Text queue (in the admin design brief). That queue does not exist and is not in Foundations, so it is the first item of release 2. Whether every written answer waits for a person, not only flagged ones, is decision 5.

## API

Release 1:

- `GET /questions/current` and `GET /questions/catch-up`, and `POST /questions/catch-up/decline`, which sets `person.question_catchup_declined_at`.
- `PUT /answers/{key}`, and `GET /answers`, the member's own answers for their own profile.
- `/prospect-profile` gains `quick_answers`, filtered for the viewer: a question the viewer has not answered comes back locked, with no choice.
- A new `GET /conversation-context/{uuid}` returns the match question, plus both answers once both members have answered, and whether the other member has answered. No such route exists at f66a278 and nothing in ahavah-web calls one; the nearest existing route is `/conversation-prospect/<uuid>`. The plan may instead add the match question to `/conversation-prospect`.
- `POST /push-taps`, which writes a `push_tap` row.
- Admin endpoints for Admin > Questions.
- The launch email's answer page, `/q/{key}/{choice}`, is a web route that calls `PUT /answers/{key}`; it needs no endpoint of its own.

Release 2, as the spec had them:

- `GET /prompt-bank`.
- `GET /profile-info` and the profile payload gain `prompts` and `opening_question`, approved text only.
- Prompts and the opening question are saved through their own endpoint or a new field shape, because `PATCH /profile-info` takes one field per request.
- The like endpoint accepts optional `prompt_key` and `comment`, and `/likes/incoming` returns them.
- The `GET /conversation-context/{uuid}` added in release 1 also returns the like comment and both opening questions.

Nothing is written into the chat server, so no change to the XMPP side.

## Screens (Claude Design brief)

Release 1, briefed into the existing Ahavah Claude Design project (`ahavah-web/docs/design-briefs/2026-10-13-profile-prompts.md`):

1. The question card, in 3 states.
2. The catch-up run.
3. The Quick answers section, with its locked state, and the member's own view with "Change".
4. The meter on the profile-finish card, including the card with the meter alone.
5. The chat block, while the chat is empty and above the messages once anyone writes.
6. The Settings > Notifications row, push only.
7. Admin > Questions: the bank and its options, where the owner switches a question on or off and edits option wording; the 6-week schedule for approval, where he reorders weeks and puts a question from the bank into an empty week; counts and splits by sex; pushes sent (`push_send_log`), tapped (`push_tap`) and switched off (`push_questions_off_at`); and the state of each switch.

For the launch, in the same brief:

8. The launch email, with its new title image asset.
9. The page an email answer lands on, `/q/{key}/{choice}`.
10. The 4 social artworks.

The spec's earlier screens (the prompt picker and editor, the reply sheet, the Liked you comment, the conversation header with the reply and the opening question, the admin text queue) are briefed again for release 2.

Mobile first at 390.

## Measurement

Counts, not percentages. The baseline on 13 Oct is 37 members active within 30 days and 11 with push. The targets are assumptions (decision 7).

- Members with at least 1 answer by week 4, split by sex: 25 or more.
- Members with 5 or more answers.
- Weekly pushes tapped (from `push_tap`), with fewer than 2 switch-offs a week (from `push_questions_off_at`). 2 or more triggers the guard rail under Notifications.
- Silent-match pushes followed by a first message within 48 hours.
- Two-sided conversations a week, against the target of at least 3 a week within 6 weeks of launch.
- Launch: email clicks per option and the answers saved from them, launch push taps (`?src=lpush`, from `push_tap`), Facebook clicks on each post's tracking link and switch-offs in launch week. The Facebook clicks lead to an answer only if the calendar entries gain the target path proposed under Launch; otherwise they land on the home page. Instagram posts carry no link, so their clicks show only through the profile link.

Release 2 adds the spec's measures: members with 3 written answers, likes with a comment and their match rate against likes without, and matches with a first message within 48 hours, before and after.

## Rollout

1. Brief (release 1).
2. Data and API, with the bank seeded, every switch off and all 5 pass-throughs in `docker-compose.production.yml`.
3. The question card, the catch-up run, Quick answers, the meter and the chat block.
4. The Settings row, both pushes and the E2 line, proofed to the owner (the pushes on his own device) before `question_push`, `match_question_push` or `e2_question_line` goes on.
5. Admin > Questions.
6. Launch: the title image and the 4 artworks back from Claude Design; the target path in ahavah-admin's calendar entries; the email, the push and the posts proofed to the owner; the launch switches on and the calendar entries added only after he confirms.
7. Release 2, starting with the text moderation queue.

Release 1 should take about a week once the screens return.

## Owner decisions

Recorded on 13 Oct: the spec approved; no prompt about plural marriage; wording through the ux-writing skill and the owner; the out-of-scope list below.

Needed for this revision:

1. Which rest-day rule the Sunday push follows: the lunar rule in `restdays.py`, whose `KNOWN_THROUGH` is 9 Nov 2026 (24 days from 16 Oct), or the Friday and Saturday rule held mail uses. Under the lunar rule, `restdays.py` marks both candidate dates of each provisional eighth-month Sabbath as rest days (18 and 19 Oct, 25 and 26 Oct, 1 and 2 Nov, 8 and 9 Nov), each from 17:00 Barbados time the evening before. Every Sunday up to 9 Nov is one of them, so no Sunday 18:00 push can go before 15 Nov, which is past `KNOWN_THROUGH`. The lines that name Sunday are drawn both ways.
2. Approval of the 14 choice questions, their option wording (written to read inside a sentence) and the first 6-week schedule.
3. Whether the silent-match push goes to both members.
4. Whether `profile_prompt` folds into `prompt_answer` in release 2.
5. Confirmation that written answers wait for a person to review them.
6. The Liked you paywall for comments, before release 2. 14 members' Premium lapses from 16 Dec.
7. Agreement to the targets under Measurement.
8. The launch Sunday, for the email, the push and the first post. Under the lunar rule there is no launch Sunday until the ninth month is read, because every Sunday up to 9 Nov is a rest day (decision 1). The posts follow the lunar rule whatever decision 1 says, so post 1 goes on the launch day or the next free day. A series that runs past 9 Nov needs the next month's rest days read first.
9. The launch copy: the email with its "Also new on Ahavah" list, the push and the 4 captions, approved through his proofs. If the email goes after 16 Dec, the Liked you line changes.
10. Whether the catch-up run offers every active question from launch, so the meter and Quick answers can fill in the first week, rather than only the questions already dropped.
11. The default of `push_questions`. On, the launch push and the weekly push can reach the 11 members with push from launch; off, they reach nobody until a member turns it on. Proposed: on, since those members have already allowed push; `push_likes` and `push_profile_views` default to off, so this would differ from them.
12. Whether the question pushes count towards the 3-day gap. Proposed: yes, as both judges confirmed, at the cost of Tuesday's `one_photo` and Wednesday's `profile_views` email each week for members who had the Sunday push (see Notifications).

## Out of scope

- Voice prompts (later).
- AI-suggested openers.
- Hinge's "Your Turn" limits (the pool is too small; revisit past a few hundred members).

## Surfaces, social, scheduler and dashboard

See `2026-10-13-growth-features-surfaces-and-ops-design.md`: the marketing pages and landing sections, the promotion templates in the growth social set, the publishing kinds, the shared lead sources, the admin additions, the privacy work and the build order all live there.
