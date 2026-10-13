Linear: TEC-1848

# Free bot protection at sign-up

Owner decision, 13 Oct 2026 (finding 43): no Cloudflare account and no new cost. Turnstile stays built and switched off.

## The problem, in numbers

In the 30 days to 13 Oct, 151 sign-up codes went to addresses that never entered them. 61 of those came from 3 IP addresses, mostly between 15 September and 3 October. Codes mailed to strangers draw spam complaints, and complaints hurt the delivery of real codes.

## What exists today

- `POST /request-otp` allows 3 a minute and 40 a day per IP, plus 5 an hour and 20 a day per recipient (`service/api/__init__.py:180`, `service/api/decorators.py:139-168`).
- A honeypot field, `website`, is checked in `service/person/__init__.py:366`. It only works if the sign-up form sends the hidden field, and the web form does not render it today.
- `service/antibot` holds the Turnstile check, off with no keys.

## What we will build

1. **Tighter limits for addresses with no account.** A request for an address that has no account counts against a per-IP limit of 5 an hour and 10 a day, and a per-network limit (IPv4 /24, IPv6 /64) of 20 a day. Requests for existing accounts keep today's limits, so members signing in are unaffected. Admin emails stay exempt, as they are from the FireHOL list.
2. **Distinct new addresses per network.** One network may ask for codes for at most 5 different new addresses a day. This is the pattern behind the 61: one source cycling through many addresses.
3. **The honeypot, wired.** The sign-up form renders the hidden `website` field (visually hidden, `autocomplete="off"`, `tabindex="-1"`, `aria-hidden`), so a form-filling bot reveals itself. A hit returns the normal success response and sends nothing.
4. **A timing check.** The sign-up page issues a signed timestamp when it loads; a request for a new address that arrives under 2 seconds after it, or with a missing or forged stamp, is treated like a honeypot hit. Existing members signing in skip it.
5. **Undeliverable domains.** A new address whose domain has no MX record, or is on the repo's existing bad-domain list (`email-domains-bad.sql`), gets no code. The answer the visitor sees is the same as for any send, so it reveals nothing.
6. **A number to watch.** Admin > System shows codes requested and never entered, per day, split into new and existing addresses. The plan works if that line falls.

## Not in this plan

Turnstile or any other third-party challenge; blocking whole countries; CAPTCHA puzzles.

## Tests

Each rule gets an API test (limit reached for new addresses while an existing member still signs in; the sixth distinct new address from one network refused; honeypot and timing hits send nothing and look like success; an MX-less domain gets no code). The web gets a test that the hidden field renders and is submitted, and one that the timestamp is sent.

## What changes for members

Nothing visible. A person who requests codes for many new addresses from one network sees the same screen and gets no further codes until the next day.

## Order and cost

API first, then the web form (the hidden field and the stamp are logic, not layout). About a day of work. No cost.
