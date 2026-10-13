Linear: TEC-1845

# Events by Ahavah

## Why

The people Ahavah serves gather in assemblies, Shabbat fellowships and feast sites, and that is where trust is given. Women are the constraint: 19 of 27 people who joined since August are men. Communities are where to reach women honestly. Comparable apps run events (Muzz city events; Devout partners with churches; Christian Connection lets members host meetups). Partiful grew because each invite link is its own landing page and guests RSVP without an account.

## Owner decisions (13 Oct 2026)

Non-members can RSVP. Screens are designed in Claude Design first.

## Three parts

**1. Event pages.**

- An approved organiser (an assembly, a fellowship leader, a ministry, or Ahavah itself) creates an event: title, date and time with time zone, in person (city, venue shown after RSVP if the organiser wants) or online, description, capacity, cover image, and an optional "singles welcome" or "marriage preparation" tag.
- Each event lives at `ahavah.app/e/{slug}` with a generated share image: title, date, place, organiser, Ahavah mark.
- The page shows the date, place, organiser, description, how many are going (optional) and an RSVP form.
- Feast days come from the owner's calendar (`service/spotlight/restdays.py` and the Biblical Calendar Engine), so a Sukkot gathering is labelled with its biblical name.

**2. RSVP without an account.**

- A guest gives a name, an email and the number of guests, ticks one optional box ("Tell me about Ahavah events and members near me"; unticked by default), and confirms by tapping a link in the confirmation email.
- They get an add-to-calendar file, a reminder the day before, and a note if the organiser changes or cancels.
- Every confirmed RSVP is a lead with a source (`event:{slug}`). The optional box is the only marketing consent.

**3. "Invite Ahavah to your gathering".**

- A page for leaders: what Ahavah can bring (a short talk on preparing for marriage, a table, the marriage checklist session, the compatibility game on attendees' phones) and a request form (gathering, dates, place, expected numbers, contact).
- Requests land in the admin.
- Approved events can show "Ahavah will be there".
- A downloadable leader pack ships with the checklist's leader version.

## Organisers

- Anyone can request to host by filling the form with a verified email.
- An admin approves an organiser once; their later events publish without review unless flagged.
- Organisers manage their event and see their RSVP list through a magic link emailed to them. No Ahavah account is needed.
- Organisers see names and party sizes. Emails are visible only if the guest ticked "share my email with the organiser".

## Data (API)

- `organiser`: id, name, kind, email, verified_at, approved_at, approved_by.
- `event`: id, slug, organiser_id, title, starts_at, ends_at, tz, mode, city, country, venue, venue_visibility, description, capacity, tags, cover_key, status (`draft` | `pending` | `published` | `cancelled`), created_at.
- `event_rsvp`: id, event_id, name, email, party_size, status (`going` | `cancelled`), confirmed_at, share_email_with_organiser, marketing_consent, source, person_id (when the guest is or becomes a member).
- `ahavah_invite_request`: gathering, dates, place, numbers, contact, status.

Emails (confirmation, reminder, change, cancellation, organiser digest) go through the durable outbox on the brand shell. Each new template goes to the owner as a proof before it is switched on.

## API

- Public: `GET /events?region=`, `GET /events/{slug}`, `POST /events/{slug}/rsvp`, `GET /rsvp/confirm/{token}`, `POST /rsvp/{token}/cancel`, `POST /host-requests`, `POST /invite-ahavah`.
- Organiser via magic link: create, edit and cancel events; list RSVPs.
- Admin: approve organisers, approve events, list invite requests.

## Admin

An Events tab:

- Pending organisers and events.
- Invite requests.
- Per event: page views, RSVPs, confirmed, attended (organiser can mark), and sign-ups attributed to the event.

## Measurement

- RSVPs per event.
- Confirmation rate.
- Share of RSVPs that are new emails.
- Sign-ups with `lead_source = event:*`.
- Women among RSVPs.

## Rollout

1. Brief: event page, RSVP and confirmation, organiser management, events list, invite-Ahavah page, admin tab, share image.
2. Ahavah-run events first (owner as organiser), to prove the page and RSVP.
3. Organiser requests and approvals.
4. Events list by region.
5. Invite-Ahavah page with the leader pack.

## Out of scope

- Ticket sales and payments.
- Seating.
- In-app chat between guests.
- Public guest lists.

## Risks

- **Fake organisers.** Approval once, and a flag to pull any event.
- **Guests' safety at in-person events.** Venue can be shown only after RSVP, and safety guidance is on every in-person page.
- **Spam via RSVP.** Per-email and per-IP limits; Turnstile once keys exist.

## Surfaces, social, scheduler and dashboard

See `2026-10-13-growth-features-surfaces-and-ops-design.md`: the marketing pages and landing sections, the promotion templates in the growth social set, the publishing kinds, the shared lead sources, the admin additions, the privacy work and the build order all live there.
