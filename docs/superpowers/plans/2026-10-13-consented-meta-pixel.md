Linear: TEC-1849

# A consented Meta Pixel on the public pages, with no spend

Owner decision, 13 Oct 2026 (finding 46): no more ad spend, but try the Pixel again, or a free workaround. F07 removed the Pixel snippet on 9 September as a privacy decision.

## Where things stand

- The web keeps the typed helper `src/lib/meta-pixel.ts` and fires `CompleteRegistration` with event id `reg-<person_uuid>` on a fresh onboarding finish, but the base snippet is gone from `src/app/layout.tsx`, so nothing loads and the helper no-ops.
- The API has the Conversions API sender (`service/metapixel.py`), switched off: `AHAVAH_META_PIXEL_ID` and `AHAVAH_META_CAPI_ACCESS_TOKEN` are not set in production, and `AHAVAH_REGISTRATION_TELEMETRY` gates it.
- `/legal/privacy` says "We don't share your data with advertisers". Any Pixel or Conversions API event contradicts that line as written.

## What we propose

1. **The Pixel on public pages only, after consent.** The marketing pages (`/`, `/faq`, `/together`, `/events`, guides) show a small consent bar: accept or decline, remembered on the device. Only after "accept" does the snippet load and fire `PageView`. It never loads inside the signed-in app (Discover, chat, profiles, settings), so nothing about members' activity reaches Meta.
2. **One conversion event.** `CompleteRegistration` fires from the browser if the visitor accepted, and from the server through the Conversions API with the same event id, so Meta counts it once. The server copy sends only what Meta requires for matching: a hashed email and the event id. No name, age, photos, answers or messages.
3. **The free workaround if the Pixel is not wanted.** The Conversions API alone, with no browser script, sending the same single event. Combined with the source capture now live (the first touch, live since web 01d57d7), the dashboard can already show which link each member came from without Meta at all.
4. **The privacy pages.** The "advertisers" line changes to say what is true, for the owner's approval: "If you accept cookies on our public pages, Meta measures which of our posts and ads brought you to Ahavah. Inside the app nothing is shared with Meta."

## What the owner needs to do (free)

- In Meta Events Manager, create a dataset (Pixel) for ahavah.app under the Ahavah portfolio and generate a Conversions API token. I set both in Vercel and on the server; neither goes in chat.
- Approve the privacy line and the consent bar wording.
- The dating advertiser permission is only needed to run ads, which are off; it is not needed for the Pixel.

## Design

The consent bar is new UI, so it goes to Claude Design as a brief before any code: one line of text, accept and decline, mobile first at 390, no layout shift.

## Tests

Web: the snippet is absent until consent; absent on every signed-in route; present after accept; decline is remembered. API: the Conversions API event carries only the hashed email and event id, and a Meta failure never slows or fails onboarding (already the design; pinned by a test).

## Cost

No spend. About half a day of code after the consent bar design returns, plus the owner's 15 minutes in Events Manager.
