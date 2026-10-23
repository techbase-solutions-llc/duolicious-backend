# Gatherings in the weekly community email and the member welcome
Linear: TEC-1845 (the follow-up named in the events plan's item 20; open its own issue at the start, see Task 8 Step 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner asked on 22 Oct 2026, the day gatherings went live, for two changes to member email: the weekly community email (E2) gains a "Gatherings near you" section with up to 3 upcoming gatherings in the member's region and online, left out when there are none; and the member welcome mentions gatherings. Both ship dark, each behind its own switch, and reach members only after the owner has seen and confirmed a proof.

**Architecture:** One read in `service/events/public.py` picks the gatherings a member sees, from the member's `person.country` (an alpha-2 code) through `service.matchmaker.regions.region_of`, plus every online gathering. E2 computes the lists once per run (one per region, one for members with no country), as it already does for the week's newcomers, and each recipient's row picks its region's list. The welcome gains a short mention that links to `/events?region={region}`. Two new switches, `e2_gatherings` and `welcome_gatherings`, each count only while `events_live` and `events_list` are on, because both blocks link to `/events`, which answers 404 until the list is open. Display type is a title image, so the section heading and anything else the brief returns as display type come from Claude Design first.

**Tech Stack:** Python 3, Flask, psycopg 3, PostgreSQL, pytest in the `docker-compose.test.yml` api container (ahavah-api). No web or admin change.

**Sources:** The events plan, `docs/superpowers/plans/2026-10-21-events-release-1.md`, "Spec conflicts" item 20. The growth spec, `docs/superpowers/specs/2026-10-13-growth-features-surfaces-and-ops-design.md`, "Marketing surfaces", Emails. The marketing brief, `ahavah-web/docs/design-briefs/2026-10-13-marketing-pages-and-landing.md`, section 4. The designed frames: `ahavah-web/Claude Design/Ahavah Marketing Pages and Landing.html`, section 4 (`pages/p11-marketing.js` lines 36 to 42, `pages/p11-mk.js` `weekly()`, `gCard()`, `GS`), copy `handoff/copy/11-marketing-pages-and-landing.md` section 4. The landing's line for "nothing near" is copy 1.5 of the same file. Title image family: `Ahavah Email Titles for Phones.html`, copy `handoff/copy/16-email-titles-for-phones.md`.

## What the design covers, and what it does not

- **The weekly section is designed.** Frames 4.2 to 4.5 draw "Gatherings near you" inside E2 below the existing content: up to 3 compact cards (a date block of weekday, day and month; the title; the city or "Online"; the organiser; "Ahavah will be there" where it applies) and "See all gatherings", at 390 and 600, with 3 gatherings, 1 gathering and none (the block left out). This plan follows those frames.
- **Two details of that frame break the email rules and need Claude Design.** The heading "Gatherings near you" is typed bold sans at 18 px; the house rule puts display type in a title image, and the welcome already has a subhead image in this family (`subhead-welcome`, "Know someone else seeking marriage?"). The date block's day number is typed at 20 px, which `tests/test_email_renders_on_a_phone.py` (`_HEADLINE`, any `font-size` of 20 px or more) rejects as a typed headline. Task 1's brief asks for the subhead image and an email-safe date block.
- **The welcome's mention of gatherings is not designed.** Frame 4.1 ("Member welcome, with the block") draws "2 things to try first" with "Answer a prompt" and "Play the compatibility game with someone". It names no gathering, and neither does the growth spec ("The member welcome mentions prompts and the game") nor the events brief or its copy (`10-events.md`, `10-events-emails.md`, `p10-emails.js`). The events plan's item 20 grouped "the welcome's mention" with the weekly section; the owner's ask of 22 Oct is for gatherings. So the welcome part starts with a brief (Task 1), and Task 5 waits for its frame.
- **Not in this plan:** "Play with your match" (frame 4.2's second block) and the welcome's prompt and game rows (frame 4.1). Both are designed; the owner asked for gatherings only. See "Owner decisions", items 1 and 2.

## Before you start

- ahavah-api: branch `gatherings-in-member-emails` from `ahavah/main` (6cdce74 on 22 Oct, which holds the merged events release and Matchmaker's `service/matchmaker/regions.py`). Use superpowers:using-git-worktrees. `service/campaigns/switches.py`, `docker-compose.production.yml`, `tests/email_samples.py` and `scripts/send_proofs.py` are edited by other branches too: on a rebase keep every side's lines.
- API tests run with:
  `cd /d/Antigravity/ahavah-api && MSYS_NO_PATHCONV=1 docker compose -p ahavah-api -f docker-compose.test.yml run --rm -v /d/Antigravity/ahavah-api:/app -e INSIDE_CONTAINER=1 --entrypoint bash api /app/tests/run.sh tests/<file>.py -q -p no:warnings`
  The `-p ahavah-api` is required. The database is the shared `ahavah-api-postgres-1`; never remove, reset or recreate it or its volume. In a worktree, change the path in both the `cd` and the `-v` mount.
- Commits: explicit paths in `git add`, `git -c user.email=admin@techbaseltd.com commit`, footer `Refs: TEC-1845` (or the new issue once opened), no attribution trailers. Never push until Task 8 says so, and then only with the owner's go.
- Line numbers are hints measured on 22 Oct. Trust the code over the number.
- **E2 may not be sending at all.** Its cron needs `DUO_CRON_COMMUNITY_WEEKLY_ENABLED=1`, and Linear TEC-1306 ("Turn the community-weekly cron on", Todo) says it is not yet on. The production `.env` cannot be read from the repo. Until it is on, the weekly section reaches members only when an operator presses Send in Growth > Emails. Owner decision 9.

## Global Constraints

Every task's requirements include these.

- **Copy.** Sentence case, British spelling, no em dashes, digits for numbers, no serial comma. Never "dating"; never "diaspora" in an email. Torah-observant believers, never Jewish framing; feasts by their biblical English names; no countdowns, no "spots filling fast", no exclamation marks. Strings come verbatim from `handoff/copy/11-marketing-pages-and-landing.md` section 4 (and copy 1.5 for the online-only line) or from Task 1's returned copy. Every line this plan adds that the export does not have is marked `# NEW LINE` in code and listed in Task 7 for `/copy-pass` (humanizer for email prose) and the owner. This covers code comments and commit messages too.
- **Display type.** Email display titles are pre-rendered title images through `emails.base.title_image()`, never typed headlines. `tests/test_email_renders_on_a_phone.py` rejects any `<h1>` to `<h4>` and any type of 20 px or more. The section heading and the welcome's mention use what Task 1 returns; nothing is typed at display size while the images are missing.
- **Samples and the phone check.** Every new email state gets a row in `tests/email_samples.py`, so `test_email_renders_on_a_phone.py` covers it: nothing wider than a phone, the brand stack, no typed headline, no phone text under 10 px.
- **Switches.** Each new member-facing send is behind its own switch in `service/campaigns/switches.py`, off unless its variable is 1, true, yes or on, passed through as `AHAVAH_X_ENABLED: ${AHAVAH_X_ENABLED:-0}` in both the api and the cron blocks of `docker-compose.production.yml`. Each also needs `events_live` and `events_list` (through `service.events.surface_on('events_list')`), because both blocks link to `/events`.
- **Proofs.** Proofs go to `scripts/send_proofs.PROOF_TO` only, straight through the mailer, never the outbox; sample data only; no switch read or changed; every unsubscribe and tracked link inert, as `_inert` makes them. No switch flips before the owner confirms the proof.
- **Rest days.** The owner's rest days (`service/spotlight/restdays.py`) are known only to 9 Nov 2026 (`KNOWN_THROUGH`). E2 already skips a rest period (`service/campaigns/schedule.campaign_rest_now`, read by the cron and the Send button); this plan keeps that and adds no new send time. The provisional eighth-month Sabbaths block 26 Oct, 2 Nov and 9 Nov, each a Monday, so the earliest E2 that could carry the section is Monday 16 Nov, after `KNOWN_THROUGH`. The welcome is sent when a member finishes sign-up, as today, whatever the day; this plan does not change when it sends. A gathering's own date may fall on a Sabbath (events plan item 17); that is the organiser's matter and does not hide it. This plan changes neither `restdays.py` nor `ahavah-admin/src/lib/rest-days.ts`.
- **Privacy and safety.** The block shows only what `public.card()` returns, which never carries the venue or the call link. Organiser text (title, organiser name, city) is escaped with `html.escape(..., quote=True)` everywhere it lands. Only gatherings the public may find appear: published, not paused, not cancelled, not started.
- **Leads.** A member is never a lead. Links from these emails credit E2 or the welcome through `make_campaign_link`, never `event:{slug}`.

## Review focus

The inputs most likely to bite a member first. Each has a test in the task named.

1. A member whose country is empty or not a two-letter code: they get online gatherings only, and the block is left out when there are none. Task 3, `test_a_member_with_no_country_sees_online_only`.
2. A gathering that fills, is paused, is cancelled or starts between the run's start and a recipient's turn: the lists are computed at the start of the run, so the run can show a gathering that filled minutes earlier; the page then says it is full. Task 3 excludes full gatherings at read time, `test_a_full_gathering_is_left_out`.
3. An organiser's title or name carrying markup or quotes: escaped in the card and in the `alt` of any image. Task 4, `test_gathering_text_is_escaped`.
4. The switch on while the list is dark: no block, so no member is sent to a `/events` that answers 404. Task 2, `test_both_need_events_live_and_the_list`.
5. One bad gathering row (a time zone the server does not know) must not stop the weekly send, which builds per recipient inside `run_campaign`: the block falls back to leaving that card out and logs it, as `_safe_spotlight_block` does. Task 4, `test_a_bad_gathering_drops_its_card_not_the_send`.

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `ahavah-web/docs/design-briefs/2026-10-22-gatherings-in-member-emails.md` | Create (Task 1) | The brief, as sent |
| `service/campaigns/switches.py`, `docker-compose.production.yml` | Modify | 2 switches and their pass-throughs |
| `service/events/__init__.py` | Modify | `member_email_on(name)` |
| `service/events/public.py` | Modify | `gatherings_for_members(tx, now)`, `for_member(lists, country)` |
| `service/events/fields.py` | Modify | `date_block(starts_at, tz)` |
| `emails/community_weekly.py` | Modify | `_gatherings_block`, the `gatherings` and `gatherings_online_only` arguments |
| `emails/send_community_weekly.py` | Modify | The lists in the week context, `p.country` on each recipient, both builders, the previews |
| `emails/member_welcome.py` | Modify (Task 5) | The mention, from Task 1's frame |
| `emails/assets/subhead-gatherings*.png` (and any other image Task 1 returns) | Add | Synced from `ahavah-web/public/email/` |
| `scripts/send_proofs.py` | Modify | 2 proofs, held while their images are missing |
| `tests/email_samples.py` | Modify | 4 new rows |
| `tests/test_gathering_email_switches.py`, `tests/test_events_near_member.py`, `tests/test_e2_gatherings.py`, `tests/test_welcome_gatherings.py` | Create | One per task |
| `tests/test_send_proofs.py` | Modify | `EXPECTED_EMAILS` |

## Task 1: The Claude Design brief, then the handoff

Owner-facing; no code. The house rule: all new UI, emails included, comes from a brief into the existing Claude Design project `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`, never a new one.

- [ ] **Step 1: Save the brief** below to `ahavah-web/docs/design-briefs/2026-10-22-gatherings-in-member-emails.md`, run its copy through `/copy-pass` (humanizer), then send it with `/brief` into project `bd2e1ca9-f678-4567-a6eb-79afd75b2ef7`. Attach `Ahavah Marketing Pages and Landing.html` section 4, `Ahavah Email Titles for Phones.html`, `Ahavah Email Templates.html`, `emails/member_welcome.py` and `emails/community_weekly.py` as context.
- [ ] **Step 2: When it returns, `/handoff`** the frames into `ahavah-web/Claude Design/` and the title PNGs (light and `-wht`) into `ahavah-web/public/email/`; then in ahavah-api run `./scripts/sync_email_assets.sh` and note each image's natural CSS width from the returned table. Audit the handoff against this brief before building: every state drawn, every string listed, nothing at 20 px or more typed.
- [ ] **Step 3: The owner reads the frames and every string** (Task 7 lists them). Tasks 2 to 4 may start before he does; Task 5 waits for this step.
- [ ] **Step 4: Commit** the brief and the handoff in ahavah-web (`docs(design): brief and handoff for gatherings in the member emails`), and the synced assets in ahavah-api (`feat(email): the gatherings subhead title`).

The brief's text:

```markdown
# Design brief: gatherings in the weekly community email and the member welcome

Date: 2026-10-22. Repo target: `ahavah-api` (`emails/community_weekly.py`, `emails/member_welcome.py`, `emails/assets/`) and `ahavah-web/public/email/`. Linear TEC-1845. Builds on `Ahavah Marketing Pages and Landing.html` section 4 (frames 4.1 to 4.5), `Ahavah Email Titles for Phones.html` (the title recipe and line breaks) and `Ahavah Email Templates.html` (the shell). Voice: `briefs/ahavah-audience-and-voice.md`.

## Goal

Gatherings went live on 22 Oct. The owner wants members to hear about them in 2 emails they already get: the weekly community email gains "Gatherings near you", and the member welcome mentions gatherings. The weekly section is drawn (4.2 to 4.5) but needs 2 changes to meet the email rules. The welcome's mention is not drawn: 4.1 draws "2 things to try first" with a prompt and the game, and no gathering.

## Scope

1. **A subhead title image, "Gatherings near you."** for the weekly section, replacing the typed 18 px heading in 4.2 and 4.3. Display type in our emails is always a title image (Ultra 400, tracking -0.022em, line height 1.0, 2x, light PNG in #5524F5 and dark PNG in #FFFFFF, transparent, trimmed to the ink), in the family of `subhead-welcome`. Give its line breaks and natural CSS width, wrapped to about 280 px as the phone titles are.
2. **The date block of the gathering card at email sizes.** In 4.2 the day number is typed at 20 px. In email, type of 20 px or more must be a title image, and a date changes per card, so it cannot be one. Redraw the date block with the day number at 18 px or less, or propose another way to show the date that keeps the card's shape. Cards stack; nothing scrolls sideways at 390.
3. **The member welcome's mention of gatherings** (new). Under the existing welcome content, a short block that tells a new member gatherings exist (in person and online, hosted by assemblies, fellowship leaders and Ahavah) and links to the list near them (`ahavah.app/events?region={their region}`). It must read well when the member's region has no in-person gathering yet. No live list of gatherings in the welcome: it is sent once, at sign-up. Show how it sits beside 4.1's "2 things to try first" if the owner later adds that block (see Open questions). Any display type in it is a title image; draw that image too.
4. **The weekly section when every card is online** and the member has a region: the landing uses "Nothing near you yet. These are online." (copy 1.5). Draw it in the email, or say if the email should leave the line out.

## States

Weekly: 3 gatherings with "Ahavah will be there" on one; 1 gathering; every card online with the line from scope 4; none (section left out, as 4.4 and 4.5 show). Welcome: with the mention. Each at 390 first, then 600, light and dark, with Gmail's forced dark mode noted where the title images sit.

## Copy

Use the strings already approved where they fit: "Gatherings near you", "See all gatherings", "Ahavah will be there", "Online", "Nothing near you yet. These are online.", "See gatherings near you". Any new line is proposed, goes through the copy pass and the owner's proof before it ships, and must be listed. Sentence case. Never an em dash. British spelling. Digits for numbers. No serial comma. Marriage and courtship, never "dating". Never "diaspora". Torah-observant believers, never Jewish framing. Warm and unhurried: no countdowns, no urgency, no exclamation marks. No figure typed into a frame as a fact.

## Layout

- The shell in `emails/base.py` (600 px container, fluid on a phone). Design at 390 first.
- Nothing scrolls sideways on a phone. Touch targets at least 44 px.
- No typed headline: no type of 20 px or more anywhere in the email body.

## Open questions for the owner (draw the default, mark the alternative)

1. Does the welcome also get 4.1's "Answer a prompt" and "Play the compatibility game with someone" now, with gatherings as a third row, or only the gatherings mention? Default: only the gatherings mention.
2. Does the weekly email also get 4.2's "Play with your match" now? Default: not in this round.

## Definition of done

- The subhead title image (light and dark PNG, natural width, line breaks), and any title image the welcome mention needs, exported to `export/email/`.
- The weekly section in every state above and the welcome with its mention, at 390 and 600, light and dark.
- Reply with every string used, screen by screen, and every changed or new line marked.
```

## Task 2: The two switches

**Files:**
- Modify: `service/campaigns/switches.py`, `docker-compose.production.yml` (the api block near line 157 and the cron block near line 373, beside the events switches), `service/events/__init__.py`
- Test: `tests/test_gathering_email_switches.py` (create)

**Interfaces:**
- `SWITCHES` gains, with a comment in the file's style ("the gatherings section in E2 and the welcome's mention (TEC-1845), each off until the owner has seen its proof; each needs events_live and events_list, since both link to /events"):
  - `'e2_gatherings': 'AHAVAH_E2_GATHERINGS_ENABLED'`
  - `'welcome_gatherings': 'AHAVAH_WELCOME_GATHERINGS_ENABLED'`
- `docker-compose.production.yml`: `AHAVAH_E2_GATHERINGS_ENABLED: ${AHAVAH_E2_GATHERINGS_ENABLED:-0}` and `AHAVAH_WELCOME_GATHERINGS_ENABLED: ${AHAVAH_WELCOME_GATHERINGS_ENABLED:-0}` in both blocks. The welcome is built in the api and E2 in the cron and the api (Send), so both go to both.
- `service/events/__init__.py`: `def member_email_on(name: Literal['e2_gatherings', 'welcome_gatherings']) -> bool: return surface_on('events_list') and enabled(name)`.

- [ ] **Step 1: Write the failing test** `tests/test_gathering_email_switches.py`, in the shape of `tests/test_events_switches.py`: `test_the_switches_and_their_variables` (both names map to their variables); `test_the_compose_file_passes_each_to_the_api_and_the_cron` (each `X: ${X:-0}` appears exactly twice); `test_off_by_default` (no variable set: `member_email_on` is False for both); `test_both_need_events_live_and_the_list` (own switch on alone: False; with `events_live`: False; with `events_live` and `events_list`: True; a typo such as `"1 "` in the own switch reads as on only as `enabled()` already allows, and `"maybe"` reads as off).
- [ ] **Step 2: Run it to verify it fails.** Expected: `KeyError: 'e2_gatherings'`.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run it to verify it passes**, with `tests/test_events_switches.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/campaigns/switches.py docker-compose.production.yml service/events/__init__.py tests/test_gathering_email_switches.py
git -c user.email=admin@techbaseltd.com commit -m "feat(email): switches for gatherings in the weekly email and the welcome, both off" -m "Refs: TEC-1845"
```

## Task 3: Which gatherings a member sees

**Files:**
- Modify: `service/events/public.py`, `service/events/fields.py`
- Test: `tests/test_events_near_member.py` (create)

**Interfaces:**
- `fields.date_block(starts_at: datetime, tz: str) -> tuple[str, str, str]`: the start in the gathering's own zone as the card's 3 parts, `('Sat', '7', 'Nov')`, from the module's existing `_DAYS` and `_MONTHS` cut to 3 letters. Raises `zoneinfo.ZoneInfoNotFoundError` on an unknown zone (Task 4 catches it per card).
- `public.gatherings_for_members(tx, *, now: datetime, limit: int = 3) -> dict[Optional[str], list[dict]]`: one read of every gathering the public may find (`_VISIBLE`, `status = 'published'`), that has not started (`starts_at > now`) and is not full (`capacity IS NULL OR going_now < capacity`), ordered by `starts_at, id`. Returns, for each of the 6 regions in `service.matchmaker.regions.REGIONS`, the first `limit` gatherings whose `region` is that region or `'online'`; for the key `None`, the first `limit` online gatherings only. Each item is `card(row)` plus `date_block`'s parts under `date`. One query, then grouped in Python; never a query per member.
- `public.for_member(lists: dict, country: Optional[str]) -> tuple[list[dict], bool]`: the member's list, `lists[region_of(country)]` (a missing or unknown code gives `None`, so online only), and `online_only`: True when the member has a region, the list is not empty and every card in it is online. That flag draws "Nothing near you yet. These are online." (Owner decision 5).
- "Near you" is the member's continent, by `service.matchmaker.regions.region_of` (alpha-2, UN M49 with the Map's rules), not the member's country alone. Online gatherings count as near everyone. Owner decision 3.

- [ ] **Step 1: Write the failing tests** `tests/test_events_near_member.py`, creating organisers and gatherings with the fixtures `tests/test_events_public.py` uses:
  - `test_a_member_sees_their_region_and_online` (BB member: Dallas and an online one, not London)
  - `test_three_at_most_by_start`
  - `test_a_member_with_no_country_sees_online_only` (`None`, `''` and `'Barbados'` all give the online list)
  - `test_none_at_all_gives_an_empty_list` (and `online_only` False)
  - `test_online_only_is_true_only_with_a_region_and_every_card_online`
  - `test_draft_pending_paused_and_cancelled_are_left_out`
  - `test_a_gathering_that_has_started_is_left_out`
  - `test_a_full_gathering_is_left_out` (capacity 2, 2 confirmed places)
  - `test_no_card_carries_the_venue_or_the_call_link` (a private venue "14 Elm Street" and `online_url`: neither string in `repr` of the result)
  - `test_one_query_for_every_region` (count `tx.execute` calls through a wrapper: 1)
  - `test_the_date_block_is_in_the_gatherings_own_zone` (21:00 UTC Friday in `America/Chicago` is `('Fri', ...)`; 01:00 UTC Saturday in `America/Chicago` is still Friday)
- [ ] **Step 2: Run them to verify they fail.** Expected: `AttributeError` for the new functions.
- [ ] **Step 3: Implement** to the interfaces above.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_events_public.py` and `tests/test_events_fields.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add service/events/public.py service/events/fields.py tests/test_events_near_member.py
git -c user.email=admin@techbaseltd.com commit -m "feat(events): the gatherings near a member, by region and online, in one read" -m "Refs: TEC-1845"
```

## Task 4: "Gatherings near you" in the weekly community email

Frames 4.2 to 4.5, with Task 1's subhead image and date block. Starts once Task 1 Step 2 has the image and its width; until then build against a placeholder name and keep the switch off.

**Files:**
- Modify: `emails/community_weekly.py`, `emails/send_community_weekly.py`
- Test: `tests/test_e2_gatherings.py` (create)

**Interfaces:**
- `community_weekly.py`:
  - `_gatherings_block(gatherings: list[dict], online_only: bool, see_all_url: str, card_url: Callable[[str], str]) -> str`. Empty list: `''`. Otherwise, in the order of frame 4.2: `title_image("subhead-gatherings.png", "subhead-gatherings-wht.png", "Gatherings near you.", <width from Task 1>)`; when `online_only`, "Nothing near you yet. These are online." as a body line (17 px, `INK_SOFT`); one card per gathering as a table row (email-safe, no flexbox), each card a link to `card_url(slug)`, with the date block from Task 1, the title (escaped, bold, 15 px), the city and country or "Online" (escaped, 13 px, `MUTED`), the organiser's name (escaped) and "Ahavah will be there" as a lime chip when `ahavah_attending`; then "See all gatherings" as a text link to `see_all_url`. No type of 20 px or more; no `<h1>` to `<h4>`. Each card is built inside a `try`: a card that raises (a bad zone, a missing field) is dropped with a printed warning, never the email.
  - `community_weekly_html(...)` gains keyword arguments `gatherings: Optional[list[dict]] = None`, `gatherings_online_only: bool = False`, `gatherings_see_all_url: Optional[str] = None`, `gathering_url: Optional[Callable[[str], str]] = None`. The block goes after the community-size line and before the button (frame 4.2 places it after the existing content; the call to action stays last of the main content). Left out, the email is byte for byte as it was (`test_off_the_email_is_unchanged`).
  - When the block is present the preheader is "New members, gatherings near you and this week's spotlight." `# NEW LINE`; otherwise it stays as it is.
- `send_community_weekly.py`:
  - `_week_context()` gains `gatherings`: `public.gatherings_for_members(tx, now=...)` when `member_email_on('e2_gatherings')`, else `{}`. Computed once per run with the rest of the week, never per recipient.
  - `_Q_RECIPIENTS` selects `p.country` as well.
  - `_gathering_parts(tx, row, week, dry) -> dict`: `{}` when `week['gatherings']` is empty; otherwise `for_member(week['gatherings'], row.get('country'))`, the see-all link `make_campaign_link(tx, 'e2', f"{WEB_BASE_URL}/events?region={region}" (or "/events" with no region), pid, dry_run=dry)` and `gathering_url` minting `make_campaign_link(tx, 'e2', f"{WEB_BASE_URL}/e/{slug}", pid, dry_run=dry)` per card. No list, no links minted.
  - Both `build_for` and `_build_personal` pass these to `community_weekly_html`. A preview row (`person_id` 0, no country) gets the `None` list.
  - `preview_gatherings(to: str) -> tuple[str, str]`: E2 as every member gets it with frame 4.2's 3 sample gatherings (`GS` in `p11-mk.js`: "Marriage preparation evening", Sat 7 Nov, Dallas, United States, Grace Fellowship, Ahavah will be there; "Preparing for marriage: a talk and questions", Thu 12 Nov, Online, Ahavah; "Fellowship meal for singles", Sat 21 Nov, Atlanta, United States, Living Waters Assembly). Links go straight to `/e/{slug}` and `/events?region=north-america`; nothing is minted or stored.

- [ ] **Step 1: Write the failing tests** `tests/test_e2_gatherings.py`, in the shape of `tests/test_e2_question_line.py`:
  - `test_off_by_default_e2_has_no_gatherings_and_mints_no_link` (gatherings exist; no switch: no "Gatherings near you", no `/events` link, no new `campaign_link` rows)
  - `test_on_without_the_list_switch_there_is_still_no_block`
  - `test_on_a_member_in_north_america_sees_dallas_and_online_not_london`
  - `test_on_a_member_with_no_gatherings_gets_no_block` (the email equals the off email)
  - `test_on_every_card_online_says_nothing_near_yet`
  - `test_the_personal_e2_carries_it_too`
  - `test_the_links_are_campaign_links_to_the_page_and_the_list` (each card's `/s/` key resolves to `/e/{slug}`; see-all to `/events?region=north-america`)
  - `test_gathering_text_is_escaped` (title `Evening <script>"x"</script>` and organiser `A & B`: escaped in the HTML, no raw `<script>`)
  - `test_a_bad_gathering_drops_its_card_not_the_send` (a card with `tz='Not/AZone'`: the email builds with the other cards and a warning is printed)
  - `test_the_week_lists_are_read_once_per_run` (patch `gatherings_for_members` to count: 1 call for 3 recipients)
  - `test_off_the_email_is_unchanged` (compare `community_weekly_html` with and without `gatherings=None` against the existing sample)
  - `test_the_proof_shows_three_gatherings_and_writes_nothing` (`preview_gatherings`: the 3 titles, "Ahavah will be there" once, no new rows in `campaign_link` or `email_outbox`)
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces above, matching frames 4.2 and 4.3 at 390 and 600 by eye in a browser from `preview_gatherings`.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_community_weekly.py`, `tests/test_e2_personal.py`, `tests/test_e2_question_line.py`, `tests/test_e2_newcomers_fit.py` and `tests/test_cron_community_weekly.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add emails/community_weekly.py emails/send_community_weekly.py tests/test_e2_gatherings.py
git -c user.email=admin@techbaseltd.com commit -m "feat(email): Gatherings near you in the weekly community email, behind its switch" -m "Refs: TEC-1845"
```

## Task 5: The welcome's mention of gatherings

Waits for Task 1 Step 3 (the frame and the owner's read). The interfaces below fix behaviour; the markup and the words come from the returned frame.

**Files:**
- Modify: `emails/member_welcome.py`
- Test: `tests/test_welcome_gatherings.py` (create)

**Interfaces:**
- `_Q_MEMBER` selects `country` as well.
- `_gatherings_mention(events_url: str) -> str`: the block Task 1 returns, with its title image if it has one, linking to `events_url`. No live list of gatherings, no count.
- `member_welcome_html(premium_until, invite_url, unsubscribe_url, *, events_url: Optional[str] = None)`: the mention goes where the frame puts it when `events_url` is given; left out, the email is as it was.
- `send_member_welcome(email)`: when `member_email_on('welcome_gatherings')`, `events_url = make_campaign_link(tx, 'welcome', f"{WEB_BASE_URL}/events?region={region}", row['id'])` with `region = region_of(row['country'])`, or `/events` with none. The welcome stays exempt from the frequency cap and latched on the Premium grant, as today. If `make_campaign_link` does not accept the kind `'welcome'`, use the kind the welcome's existing links would use and say so in the commit; check `service/campaigns/__init__.py` before choosing.
- `preview_welcome_gatherings(to: str) -> tuple[str, str]`: the welcome with the mention, sample Premium date and code, the link straight to `/events?region=north-america`; writes nothing.

- [ ] **Step 1: Write the failing tests** `tests/test_welcome_gatherings.py`: `test_off_by_default_the_welcome_is_unchanged`, `test_on_without_the_list_switch_there_is_no_mention`, `test_on_the_mention_links_to_the_list_in_the_members_region` (a BB member: `/events?region=north-america` behind the `/s/` key), `test_a_member_with_no_country_gets_the_whole_list`, `test_still_one_welcome_per_member` (as `tests/test_member_welcome.py`'s latch test), `test_the_proof_writes_nothing`.
- [ ] **Step 2: Run them to verify they fail.** Expected: failures.
- [ ] **Step 3: Implement** to the interfaces and the frame.
- [ ] **Step 4: Run them to verify they pass**, with `tests/test_member_welcome.py` and `tests/test_unsubscribe_campaigns.py`. Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add emails/member_welcome.py tests/test_welcome_gatherings.py
git -c user.email=admin@techbaseltd.com commit -m "feat(email): the member welcome mentions gatherings near them, behind its switch" -m "Refs: TEC-1845"
```

## Task 6: The samples, the phone check and the proofs

**Files:**
- Modify: `tests/email_samples.py` (section 6, after `e2_community_weekly_question_line`; section 4, after `member_welcome`), `scripts/send_proofs.py`, `tests/test_send_proofs.py`

**Interfaces:**
- `tests/email_samples.py` gains, each with `audience='member'` and a `sent_now` of `'HELD: ... with AHAVAH_E2_GATHERINGS_ENABLED (or AHAVAH_WELCOME_GATHERINGS_ENABLED), AHAVAH_EVENTS_LIVE_ENABLED and AHAVAH_EVENTS_LIST_ENABLED on (' + SWITCH_NOTE + ')'`:
  - `e2_community_weekly_gatherings` (3 gatherings, frame 4.2's samples)
  - `e2_community_weekly_gatherings_one` (1 gathering, frame 4.3)
  - `e2_community_weekly_gatherings_online_only` (2 online cards and the "Nothing near you yet" line)
  - `member_welcome_gatherings` (after Task 5)
  None of them joins `_AWAITING_TITLES`: the section is not built at display size without its image.
- `scripts/send_proofs.py` `_emails()` gains `('e2_gatherings', 'Weekly email with Gatherings near you (events item 20)', send_community_weekly.preview_gatherings, send_community_weekly.FROM_ADDR)` and `('welcome_gatherings', 'Member welcome with the gatherings mention (events item 20)', member_welcome.preview_welcome_gatherings, member_welcome.FROM_ADDR)`. Their card and list links go through `_inert` like every proof. While any image named in Task 1's handoff is missing from `emails/assets/` (light or `-wht`), `plan()` leaves these 2 out and `main()` prints `waiting for title images: <stems>`; the other proofs go as before.
- `tests/test_send_proofs.py`: `EXPECTED_EMAILS` gains both names; a new `test_the_gatherings_proofs_wait_for_their_images` monkeypatches the assets check.

- [ ] **Step 1: Add the sample rows and the proof test changes**, then run `tests/test_email_renders_on_a_phone.py` and `tests/test_send_proofs.py`. Expected: the new rows fail only while their builders are missing; once Tasks 4 and 5 are in, all pass, including `test_no_typed_headlines` and `test_nothing_is_wider_than_a_phone` for each new row.
- [ ] **Step 2: Add the 2 proofs** to `scripts/send_proofs.py`.
- [ ] **Step 3: Run** `tests/test_email_renders_on_a_phone.py`, `tests/test_send_proofs.py`, `tests/test_send_event_proofs.py`, then the whole suite `tests/run.sh -q -p no:warnings`. Expected: all pass.
- [ ] **Step 4: Commit**

```bash
git add tests/email_samples.py scripts/send_proofs.py tests/test_send_proofs.py
git -c user.email=admin@techbaseltd.com commit -m "test(email): the gatherings emails in the phone check, and their proofs to the owner" -m "Refs: TEC-1845"
```

## Task 7: The new lines, through /copy-pass and the owner

Owner-facing; no code unless he changes a line.

- [ ] **Step 1: Run `/copy-pass` (humanizer)** on every line marked `# NEW LINE` and every new string Task 1 returned. Known before the handoff: the E2 preheader "New members, gatherings near you and this week's spotlight."; the welcome mention's lines (from Task 1); the subhead "Gatherings near you." (with its full stop, as the other titles have). Lines reused from approved copy are listed but not rewritten: "Gatherings near you", "See all gatherings", "Ahavah will be there", "Online", "Nothing near you yet. These are online.", "See gatherings near you".
- [ ] **Step 2: Check each line by hand** against the copy rules: no em dash, no serial comma, sentence case, British spelling, never "dating", never "diaspora". Then run the gate on a scratch file of the lines: `node ~/.claude/skills/avoid-ai-writing/bin/avoid-ai-writing-gate.js --threshold 6 <file>`.
- [ ] **Step 3: Hand him the list** with the "Owner decisions" below. His changes go into Tasks 4 and 5 and their tests, committed as `fix(email): the owner's wording for gatherings in the member emails`.

## Task 8: The launch, in order

Operational. Each step names who acts. Nothing reaches a member before the owner confirms its proof.

- [ ] **Step 1: Ship the API, dark.** With the owner's go, merge to `ahavah/main`; the push deploys. With both switches at `0`, check in Growth > Emails that Preview of E2 shows no "Gatherings near you".
- [ ] **Step 2: Proofs to the owner.** Inside the api container: `python -m scripts.send_proofs` (dry run: both gatherings proofs listed, no "waiting for title images" line), then `python -m scripts.send_proofs --send`. He checks both at 390 and 600, light and dark, Gmail's forced dark mode included, reads every line and taps each card.
- [ ] **Step 3: Check the dependencies before any switch.** `curl -s https://api.ahavah.app/events/status` shows `"live":true` and `"list":true` (the events plan's Task 27 Steps 8 and 11). For E2: `restdays.KNOWN_THROUGH` and `ahavah-admin/src/lib/rest-days.ts` cover the next Monday send (16 Nov or later needs the owner's calendar re-read first; this plan does not edit them), and the weekly cron is on (TEC-1306) or the owner knows it goes only by the Send button.
- [ ] **Step 4: Switch on, after he confirms each proof.** In the production environment `docker-compose.production.yml` reads, for both api and cron, then restart both: `AHAVAH_WELCOME_GATHERINGS_ENABLED=1`; `AHAVAH_E2_GATHERINGS_ENABLED=1`.
- [ ] **Step 5: A real check.** Sign up a test member with a North American country on a phone: the welcome arrives with the mention and its link opens `/events` on North America. In Growth > Emails, Preview E2 to the owner's address: the section shows. After the first real Monday send, Growth > Emails shows the E2 clicks; check none of the gathering links answers 404.
- [ ] **Step 6: If anything is wrong**, set the switch back to `0` and restart: the block disappears from the next build. Rows already queued in the outbox keep the HTML they were built with.
- [ ] **Step 7: Linear.** Open the issue for this follow-up at the start (events plan Task 27 Step 12 asked for it; none was found on 22 Oct by a search for "gatherings" and "weekly email"), move it as tasks land, and run `/linear-sync` before the session's final commit.

---

## Owner decisions

Each has the default this plan builds. He may change any of them.

1. **"Play with your match" in the weekly email** (frame 4.2, designed). Default: not in this plan; he asked for gatherings only. It needs a member-has-a-match read and Together's game to be live.
2. **The welcome's "2 things to try first"** (frame 4.1, designed: prompts and the game). Default: not in this plan; the welcome gains only the gatherings mention. If he wants both, the brief asks Design to show them together.
3. **What "near you" means.** Default: the member's continent from their country (`region_of`, the Map's 6 regions), plus every online gathering, as the landing and `/events` do. The alternative is the member's own country only for in-person gatherings, which would leave most members with online gatherings alone while gatherings are few.
4. **Members with no country on their profile.** Default: online gatherings only; the welcome links to the whole list.
5. **Every card online.** Default: the landing's line "Nothing near you yet. These are online." above the cards (copy 1.5), since the heading says "near you". The alternative is the frames as drawn, with no line. Task 1 asks Design to draw it.
6. **No gatherings at all.** Default: the section is left out of E2 (brief and frame 4.4); no line saying there are none.
7. **Which gatherings count.** Default: published, not paused, not cancelled, not yet started and not full; the next 3 by start, however far ahead. Gatherings the member has already RSVPed to still show. He may want a horizon (for example the next 8 weeks) or to leave out a member's own RSVPs.
8. **The heading as a title image.** Default: "Gatherings near you." as a subhead image (`subhead-gatherings`), in the family of `subhead-welcome`, replacing the frame's typed 18 px heading; the date block's day number at 18 px or less, not the frame's 20 px. Both come back from Task 1.
9. **E2 may not be sending.** TEC-1306 (Todo) says the weekly cron is not yet on. Default: this plan does not turn it on; the section reaches members through the Send button until he does.
10. **E2 after 9 Nov.** The rest-day calendar is known only to 9 Nov, and 26 Oct, 2 Nov and 9 Nov are blocked Mondays, so the first E2 that could carry the section is 16 Nov. The E2 cron checks `is_rest_period` but not `is_beyond_known`, so it would send on 16 Nov without his calendar. Default: no change to E2's timing in this plan; the E2 switch waits until he has extended `restdays.py` and `rest-days.ts` past the send date (Task 8 Step 3). The alternative is to make E2 hold beyond `KNOWN_THROUGH`, as the quick questions schedule does (`service/questions/schedule.py`), which changes E2 as a whole and needs its own proof.
11. **The E2 preheader.** Default: "New members, gatherings near you and this week's spotlight." when the section is present (NEW LINE). Today's preheader has a serial comma; this plan leaves it as it is when the section is absent.
12. **Rest days and the welcome.** Default: the welcome goes when a member finishes sign-up, whatever the day, as today; the mention adds no new send.
13. **Click credit.** Default: links from E2 count as E2 clicks and links from the welcome as welcome clicks (`make_campaign_link`); a member who then RSVPs is a member RSVP, never an `event:{slug}` lead.

## Self-review

**Coverage.**

| Requirement | Task |
|---|---|
| E2 "Gatherings near you", up to 3, left out when none (brief section 4, frames 4.2 to 4.5) | 3, 4 |
| The welcome mentions gatherings (owner, 22 Oct) | 1, 5 |
| A brief where no frame exists, into project bd2e1ca9-f678-4567-a6eb-79afd75b2ef7 | 1 |
| Display type only as title images | 1, 4, 5, 6 |
| Every new email state in `tests/email_samples.py` and the phone check | 6 |
| Switches off by default, through compose for api and cron, needing events_live and events_list | 2 |
| Proofs to `PROOF_TO` before any switch | 6, 8 |
| Rest days respected, known only to 9 Nov | Global Constraints, 8, decision 10 |
| Near you by region, online for everyone, the empty case | 3, decisions 3 to 7 |
| Copy rules and new lines through /copy-pass | 7 |

**Unverified while writing this plan:** that `make_campaign_link` accepts the kind `'welcome'` (Task 5 checks); the subhead image's width and the welcome's words (Task 1 returns them); whether `DUO_CRON_COMMUNITY_WEEKLY_ENABLED` is set in production (TEC-1306 says not yet, the `.env` is not readable from the repo); whether `events_list` is on in production today (the events plan opens it in its Task 27 Step 11, on the owner's word).

## Owner's answer (22 Oct 2026)

Asked directly: "Should I build to every suggested answer in all three plans: the 8 in-app decisions, the 11 for inviting gathering guests to join and the 13 for gatherings in the emails?" He chose "Yes, all suggestions". Build to every suggested default here; any he later changes is applied then. He also approved deploying the member sign-out fix once its tests and build pass.
