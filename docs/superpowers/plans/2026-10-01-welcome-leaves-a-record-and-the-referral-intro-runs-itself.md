Linear: TEC-1613

# The welcome email leaves a record, and the referral intro runs itself

**Goal:** Every welcome email can be proven accepted by the mail server, and every member gets their invite link a week after joining without anyone running a script.

**Architecture:** Both ride the durable outbox that already carries every campaign (`service/campaigns/outbox.py`), so acceptance lands in `email_send_log` and the Growth > Emails index can show them as system campaigns beside E4 and E5. The welcome swaps a direct SMTP call for `outbox.enqueue`. The referral intro gains a daily cron that queues it for members seven days in.

**Spec:** Owner ask 1 Oct 2026 on TEC-1613.

## Global constraints

- No em dashes. Sentence case. Torah-observant believers, never Jewish framing.
- Never nest `api_tx`. No literal `%` in psycopg SQL.
- A new cron env var must be allowed through every compose file it is read in (lesson from TEC-1188).
- Commits by explicit path, `Refs: TEC-1613`.

## Facts, 1 Oct 2026

- `email_send_log` carries `e1`..`e6` and `e4`/`e5` system sends. Nothing for the welcome.
- 32 members joined after the beta and never had the referral intro; 1 of them has no referral code, 3 joined less than 7 days ago. So the first tick queues up to 28, less any held by the 7 day frequency cap after today's sends (those retry the following week under a new per-week id).
- The beta-era intro footer says "because you opted into the Ahavah beta" with the `beta` unsubscribe scope. A member who joined after the beta needs the member footer and the `notifications` scope.

### Task 1: The welcome goes through the outbox

- Modify `emails/member_welcome.py`: `send_member_welcome(email)` opens one `api_tx`, reads the member (id, expiry, code), builds the html and calls `outbox.enqueue(campaign='welcome', campaign_id=f'welcome-{id}', exempt=True, unsub_scope='notifications')`. Returns True when a row was queued. The async wrapper is unchanged.
- Test `tests/test_member_welcome.py`: a granted member gets exactly one `email_outbox` row for `welcome-<id>`; a second call queues nothing; a member without a code queues nothing.

### Task 2: The referral intro has a member variant and a cron

- Modify `emails/referral_intro.py`: `referral_intro_html(email, code, member=False)`; `member=True` uses the standard member footer and the `notifications` scope.
- Create `service/cron/referralintro/__init__.py`: `queue_due(tx, now) -> int` selects activated members with a code, joined over `REFERRAL_INTRO_AFTER_DAYS` (7) ago, not staff, not excluded, no beta intro, no `referral` row in `email_send_log`, not unsubscribed, not suppressed; enqueues `campaign='referral'`, `campaign_id=f'referral-{id}-{isoyear}w{week:02d}'`, `cap_days=7`. `referral_intro_forever()` polls every `DUO_CRON_REFERRAL_INTRO_POLL_SECONDS` (86400), off when `DUO_CRON_REFERRAL_INTRO_ENABLED=0`.
- Register in `service/cron/__init__.py`; add both env vars to `docker-compose.yml`, `docker-compose.production.yml` and `docker-compose.test.yml` beside the community weekly ones.
- Test `tests/test_referral_intro_cron.py`: due member queued once; too new not; beta intro already sent not; a `referral` row in the send log stops it; staff not; second tick same week queues nothing; the html carries the member footer.

### Task 3: Both are listed

- Modify `service/api/admin/growth_routes.py`: the system list becomes `('e4', 'e5', 'welcome', 'referral')`.
- Modify `tests/test_growth_routes.py` expectations.
- Admin: `NAMES.welcome = "Member welcome"`, `NAMES.referral = "Referral intro"`, `ORDER` extended.

### Task 4: Verify, deploy, record

- API suite, admin suite. Deploy API then admin. Watch the first cron tick on the droplet: expect up to 28 queued, some skipped by the cap. Comment on TEC-1613, mark Done.
