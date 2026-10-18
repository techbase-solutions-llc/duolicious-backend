# Together: the lines the design did not have

Linear: TEC-1845. For the owner to read before Together goes live (plan `2026-10-17-together-release-1.md`, Task 29 Step 3, Spec conflicts items 2 to 6, 9 and 18). Each line is in the code now, marked "Not in the export". Nothing launches on a line you have not read.

## The game

Round intros (only "The feasts" was in the design):

- Sabbath and calendar: "How you count the days, and where you are in your walk."
- The feasts: "Which appointed times you keep, and the one you wait for all year." (from the design)
- Family and children: "The children you have, and the home you hope to fill."
- Home and roles: "Where you want to live, and who sets the Sabbath table."
- Moving and language: "Where you live now, how far you would go and what you speak."
- How we talk and decide: "How fast, how often and how you like to talk."

"You in a sentence" on the Me result. The design gave one example; the app builds the sentence from up to 3 parts, for example "You keep the spring and autumn feasts, hope for a large family and would move countries for the right marriage." The parts:

- Feasts: "keep the spring and autumn feasts", "keep the spring feasts", "keep the autumn feasts"
- Children: "hope for a large family", "hope for children", "are open to more children", "are open to a blended family", "do not hope for children"
- Moving: "would move countries for the right marriage", "would move for the right marriage", "hope your spouse would move", "want to stay where you are"

Who knows me best, a friend's result: "You are first on {name}'s board." or "You are number {place} on {name}'s board."

A shared link that has already been used: "This link has already been used."

A link opened too often from one network (more than 3 times a day): "This link has been opened too many times today. Try again tomorrow."

Before a guest has joined (the design named the guest "Rivka" before anyone had joined):

- "Send your link"
- "Waiting for the other player"
- "Their email"
- "The other person will see this when you compare"

On the second player's start, the send-link screen and the invite email: "Neither of you sees the other's answers. You both see the score." (The design said "you will not see hers", but the app does not know anyone's pronoun.)

## The marriage checklist, version 2

- Intro, step 3, "Compare": "Answer on your own, or invite your intended or spouse and see where you agree."
- Intro lede, with "and send a personal summary to you both" taken out, since each person now gets their own summary: "Read the passages set for a husband and a wife, then add your own nice-to-haves and challenges. Rate what matters most to you."
- If the checklist cannot start: "We could not start the checklist. Try again."
- Search description: "A free, guided marriage checklist for Torah-observant couples. Work through biblical obligations, rate what matters most to you, and compare answers with your intended or spouse. Your answers stay private and you can delete them at any time."
- Search step 4, "Compare your answers": "Invite your intended or spouse, then see where you agree and what to talk about."
- Questions and answers:
  - Is the marriage checklist free? "Yes. The checklist is a free activity from Ahavah. You confirm your email with a one-time code to save your answers or to compare them with someone, and no matchmaking profile is required."
  - Do you store my answers? "Yes, once you save them. We keep them behind a private link so you can come back to them. Only you and the person you invite can see them, and either of you can delete them at any time. We delete them 12 months after your last visit."
  - Can I use it if I am single? "Yes. Answer on your own to write down your non-negotiables, or invite someone you are courting to answer too and compare."
  - How does my spouse get the results? "Invite your intended or spouse by link or email. Each of you answers privately, and once you have both finished you each see where you agree and what to talk about. We also email each of you your own summary."

## Share text

- A couple's checklist: "We completed the Ahavah marriage checklist: {agree} of {total} in agreement. ahavah.app/marriage-checklist"
- A single's checklist: "I wrote my non-negotiables. ahavah.app/marriage-checklist"
- Inviting someone to the checklist: "Will you take the Ahavah marriage checklist with me? {link}"

## The emails

The 5 proofs went to your inbox on 18 Oct, each marked [PROOF].

- The invite email's footer: "We have not added you to any list."
- The checklist's "your comparison is ready" email uses the game's wording from the design (4.10): "Rivka has answered. See how you fit." with the button "See your comparison". The design has no checklist version. If you want one, a suggestion: "Rivka has finished the checklist. See where you agree."

## Launch posts (captions 1 and 4; 2 and 3 are the design's own)

- Caption 1: "New on Ahavah: Together. Two free tools for anyone preparing for marriage. Play a 2 minute game alone, with one person or with friends, and see how well you fit. No account needed."
- Caption 4: "How well do your friends know you? Play Who knows me best on Ahavah and post your link in a group chat."

## Held back, not shown

"If you join Ahavah, these can become your profile prompts." is in the design but is not true yet (prompt drafts come with quick questions release 2), so it stays hidden.

## Lines added overnight by the review fixes (18 Oct)

A review of the web screens found 38 faults; the fixes needed these lines, none of them in the design:

- A friend filling in missed guesses: "Every question needs a guess before you can finish."
- Reopening a saved result from an email: "Confirm your email to open your result" (or "...open your checklist"), with "We send a 6-digit code to your email."
- An empty name on the save step: "Enter the name to show on your result."
- A name with < or > in it: "Enter a name without < or >."
- After Share falls back to copying: "Link copied"
- Failures: "We could not delete this result. Check your connection and try again.", "We could not remove that name. Check your connection and try again." and "We could not put that name back. Check your connection and try again."
- The checklist FAQ's last sentence is now "If you saved with your email, we also email you your own summary." (a partner who joined with only a name is not emailed, so the old line promised too much).
- The checklist's search step description, once version 2 is live: "Work through biblical obligations, rate what matters most to you and compare answers with your intended or spouse."
- A delete link now sits on the Me result, the Who knows me best board, the Us and checklist waiting screens and the single checklist result, using the design's own delete dialog and lines, because the save screen promises "Either of you can delete them at any time".

## Decisions the review left for you

1. The "Find people who answered like you" button is 336px wide but a 320px phone gives it 280px. Pill buttons never wrap, so it needs either a shorter label on phones (for example "Find people like you") or a smaller pill without its icon.
2. A member who opens their own invite link sees "This link has already been used." The API does not say which session is theirs, so the page cannot send them to it. Either we change the API to return it, or the line becomes "This is your own link. Send it to the other person."
3. The couple waiting screen's delete asks "Delete this result? The link will stop working for everyone." The checklist's own line, "Delete this comparison for both of you?", would also fit.
4. The checklist page's general search description still says "share a personal summary" in both versions.

## Copy pass: proposed changes (18 Oct, not applied)

Run with `/copy-pass`: `ux-writing` on the screen lines, `humanizer` rules on the prose. The prose scored 0 ("Clean") on the detector and passed the house style check. Each change below waits for your yes; anything not listed stays as written above.

| Where | Now | Proposed | Why |
| --- | --- | --- | --- |
| Round intro, Family and children | The children you have, and the home you hope to fill. | The children you have, and the family you hope for. | "Fill" assumes children; some players want none. |
| Round intro, Moving and language | Where you live now, how far you would go and what you speak. | Where you live now, how far you would go and the languages you speak. | Clearer. |
| Round intro, How we talk and decide | How fast, how often and how you like to talk. | How fast you want courtship to go, and how you like to talk. | "How fast" had no subject. |
| You in a sentence, no children | do not hope for children | are not hoping for children | Reads less cold in "You ... and ...". |
| Link already used (title) | This link has already been used. | Someone has already joined with this link. | Says what happened. |
| Join limit | This link has been opened too many times today. Try again tomorrow. | This link has been used too many times today. Try again tomorrow. | The limit counts joins, not openings. |
| Checklist, waiting | Waiting for the other player | Waiting for the other person | The checklist is not a game. |
| Checklist search description | ...rate what matters most to you, and compare answers... | ...rate what matters most to you and compare answers... | No serial comma. |
| Launch caption 1 | Play a 2 minute game | Play a 2-minute game | Compound adjective. |

Kept on purpose: the friend's board lines, the pre-guest lines other than the checklist's "waiting", the privacy line, the checklist questions and answers, the share texts and the invite email footer. They are short, true to what the app does and already in the house style.

## A rule to approve

The Me result picks one of 8 kinds from a points table (plan Task 4). The rule is ours, not the design's; the brief asks you to approve it.
