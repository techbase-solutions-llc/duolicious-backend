Linear: TEC-1845

# Matchmaker: alerts, introductions and family involvement

## Why

In this community, marriages are often helped along by parents, elders and friends. Ahavah can make room for that without ever giving outsiders the member base to browse. Two things went wrong elsewhere:

- Hinge's standalone matchmaker app was criticised for showing profiles by default.
- Tinder's Matchmaker raised privacy concerns about sharing a person's profile with outsiders.

Two things worked:

- Muzz's wali feature, where a family member joins chats with consent.
- Loop, where introductions need both people to say yes.

## Owner decisions (13 Oct 2026)

A parent or mentor role is welcome. Screens are designed in Claude Design first.

## Principles

- Nobody browses anyone they could not already see as a member.
- Every introduction needs both people to accept.
- A mentor sees only what the single chooses to share, and the other person is always told a mentor is involved.

## Step 1: "Tell me when someone fits"

**For members.**

- From the empty deck, or from Filters, a member saves their criteria: age band, countries, willing to relocate, observance, Sabbath and calendar, wants children. These are the deck's existing filters plus the computed age band.
- When a new member who fits joins, they get one notice: email and push, at most one a day, batched. It names nobody and shows a count and a "See who joined" button.
- The likes-waiting email already being built carries the same line, so a member is never sent two emails for one reason.

**For visitors.**

- On the landing page and the "all caught up" screen: "Not ready to join? Tell me when someone who fits joins." The visitor gives an email (confirmed by link), who they are looking for (a man or a woman, an age band, a region) and an optional first name.
- When a member who fits joins, they get one email: "Someone who fits what you are looking for joined Ahavah", with a count only and a link to sign up with the criteria carried over.
- Source: `alert:visitor`.

**Data.**

- `match_alert`: owner person_id or email, criteria (jsonb), confirmed_at, last_sent_at, active.

A cron checks new members against active alerts using the search query's own predicates, and sends through the outbox. New templates are proofed to the owner first.

## Step 2: "Introduce someone"

**Recommend Ahavah to a single.** Anyone (a member, a parent, a friend) can send a single a personal invitation with a note: "I think you would be a good fit for Ahavah." It uses the existing referral code when sent by a member; otherwise it is a tracked invitation. The single gets one email; nothing is shared about them.

**Suggest two people for each other.**

- A member can suggest an introduction between two members they can already see, for example two friends from their assembly who are both on Ahavah.
- Each person gets a private notice: "{Introducer's first name} thinks you and {first name} might be a good fit", the other person's card, and Accept or Not for me.
- Only if both accept are they matched, with the introducer's note at the top of the chat.
- Nobody learns of a decline.
- Limits: an introducer can suggest each person once, and 5 pairs a week.

**Data.**

- `introduction`: introducer_person_id, a_person_id, b_person_id, note, a_response, b_response, matched_at, created_at.

## Step 3: family involvement (mentor)

**Invite a mentor.**

- A single invites a parent, elder or mentor by email from Settings.
- The mentor confirms their email and gets a mentor account: no profile, never in search, no photos of their own.
- The single can remove them at any time.

**What a mentor sees.**

- The single's matches as the single sees them (first name, age, photos, prompts).
- Any conversation the single chooses to share, one conversation at a time, read only.
- The mentor can leave the single a private note on a match ("Ask about her family's assembly"). The match never sees these notes.

**Chaperone in a conversation (phase 3b).** The single can invite their mentor into a specific conversation as a third participant, after the other person agrees. Every message then shows to all three. This needs group conversations in the chat server, so it ships after the read-only sharing has proved itself.

**Disclosure.** A match whose conversation is shared with a mentor sees a small "{Name}'s mentor can read this conversation" notice in the chat header. A member can choose, in Settings, not to be matched with members who share conversations.

**Data.**

- `mentor_link`: single_person_id, mentor_email, mentor_account_id, confirmed_at, revoked_at.
- `shared_conversation`: single_person_id, other_person_uuid, shared_at, revoked_at.
- `mentor_note`: mentor_account_id, single_person_id, about_person_uuid, note, created_at.

Mentor accounts are a role on a new `mentor_account` table, not a `person` row, so no search or count query can include them.

## Screens (Claude Design brief)

- Saved criteria and alert settings.
- Visitor "tell me when" form.
- Alert email.
- Introduce someone: recommend, and suggest two.
- The accept or decline card.
- Mentor invite and settings.
- The mentor's view.
- Shared conversation notice.
- Chaperone invite (3b).

Mobile first at 390.

## Measurement

- Alerts created, and sign-ups from visitor alerts.
- Introductions suggested, accepted by both, and conversations from them.
- Mentors invited and active.
- Members choosing not to be matched with shared conversations.

## Rollout

1. Brief for all steps.
2. Step 1 for members.
3. Step 1 for visitors.
4. Step 2.
5. Step 3 read-only.
6. Step 3b chaperone.

## Out of scope

- Professional matchmakers with access to the member base.
- Paid matchmaking.
- Introducers seeing anyone they could not already see.

## Risks

- **Pressure or control in families.** The single controls everything, can remove a mentor at any time, and the other person is always told.
- **Introductions used to harass.** Weekly limits, one suggestion per person, and silent declines; reports go to moderation.

## Surfaces, social, scheduler and dashboard

See `2026-10-13-growth-features-surfaces-and-ops-design.md`: the marketing pages and landing sections, the promotion templates in the growth social set, the publishing kinds, the shared lead sources, the admin additions, the privacy work and the build order all live there.
