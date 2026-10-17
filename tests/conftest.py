"""
Ahavah pytest fixtures.

Provides the named fixtures referenced throughout the implementation plan:
  - `client`       — Flask test client wired to the api package
  - `db`           — wraps `database.api_tx` for tests; rolls back after each test
  - `mock_rekognition` — MagicMock for boto3.client('rekognition') (Phase 4 photo moderation)
  - `signed_rc_event`  — helper to produce a signed RevenueCat webhook payload (Phase 5)
  - `stripe_signed_event` — helper to produce a Stripe webhook payload (Phase 3 ID verify)

  Removed 2026-05-15:
  - `redis_mock` / `deepl_mock` — fakeredis + DeepL fixtures. Translation
    feature pulled (orphan settings page + onboarding promise + service.
    translation_service module all deleted). Restore from git if
    chat-side translation is re-introduced.

These fixtures are forward-looking: most of the modules they mock don't exist
yet (Phase 2/3/4/5 add them). When those modules land, the fixtures auto-wire
via monkeypatch — tests just request the fixture by name.

For now `tests/test_smoke.py` exercises the fixtures end-to-end so we know
the harness itself works before any real code depends on it.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

# `service.api` exposes the Flask app via `service.api.decorators.app`.
# Import lazily inside fixtures so a fixture that doesn't need the Flask
# stack doesn't pay the import cost (or fail when the api package isn't on
# the path, e.g. running pytest from outside the container).


# ---------------------------------------------------------------------------
# Flask test client + DB transaction wrapper
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Returns the Flask app instance in test config."""
    from service.api.decorators import app as flask_app
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client. Use:
        r = client.post('/health'); assert r.status_code == 200
    """
    with app.test_client() as c:
        yield c


@pytest.fixture
def db():
    """DB context manager that rolls back after each test.

    Wraps `database.api_tx` such that anything written in the test is
    discarded — tests don't pollute each other's state. Until the migration
    helpers land in Phase 1+, this just yields the underlying api_tx
    function; tests that need state isolation will use a savepoint pattern
    until then.
    """
    from database import api_tx
    yield api_tx


# ---------------------------------------------------------------------------
# External-service mocks
# ---------------------------------------------------------------------------

# `redis_mock` + `deepl_mock` fixtures removed 2026-05-15 along with
# the service.translation_service module. They were the only call sites
# for fakeredis / DeepL in the test suite. Restore from git history if
# translation gets re-introduced.


@pytest.fixture
def mock_rekognition(monkeypatch):
    """MagicMock that stands in for the photo-moderation classifier.

    Audit correction (Task 0.0): Phase 4 Task 4.0 extends the existing ONNX
    `antiabuse.antiporn.predict_nsfw` instead of wiring AWS Rekognition,
    so this fixture monkeypatches `service.photo_moderation._predict_nsfw`
    (the lazy hook). The fixture name stays `mock_rekognition` for plan
    fidelity; tests using it should configure the mock's return value via
    `mock.return_value = [score_float, ...]` or by setting it as a callable.

    Test usage example:
        mock_rekognition.return_value = [0.95]   # rejected
    """
    mock = MagicMock(name='photo_moderation_classifier')
    # By default, return an empty list — tests must override.
    mock.return_value = []
    try:
        import service.photo_moderation as pm  # type: ignore
        # The mock IS the predict_nsfw callable for the test's duration.
        monkeypatch.setattr(pm, '_predict_nsfw', mock)
    except ImportError:
        pass
    return mock


# ---------------------------------------------------------------------------
# Webhook payload helpers (Phase 3 + Phase 5)
# ---------------------------------------------------------------------------

@dataclass
class SignedEvent:
    body: bytes
    sig: str


@pytest.fixture
def stripe_signed_event() -> Callable[..., SignedEvent]:
    """Produces a Stripe webhook payload + a signature header that
    `stripe.Webhook.construct_event` will accept under the test secret.
    Used by Phase 3's identity-verification tests.

    Test expectation (from plan Task 3.1 Step 2):
        payload = stripe_signed_event(
            type='identity.verification_session.verified',
            metadata={'user_id': str(user.id)},
            verified_outputs={'document': {'issuing_country': 'US'}},
        )
        client.post('/webhooks/stripe-identity',
                    data=payload.body, headers={'Stripe-Signature': payload.sig})
    """
    import hmac, hashlib, json, time

    def _build(type: str = 'identity.verification_session.verified',
               metadata: dict | None = None,
               verified_outputs: dict | None = None,
               last_verification_report: object | None = None,
               session_id: str = 'vs_test_session',
               last_error: dict | None = None,
               created: int | None = None,
               secret: str = 'whsec_test') -> SignedEvent:
        # The top-level `"object": "event"` and inner
        # `"object": "identity.verification_session"` discriminators are
        # required by stripe SDK 11+ — `Webhook.construct_event` parses them
        # to instantiate the correct StripeObject subclass and raises an
        # AttributeError on `__getattr__('object')` if missing.
        payload = {
            'id':      f'evt_test_{int(time.time() * 1000)}',
            'object':  'event',
            'type':    type,
            # Seconds since the epoch, as Stripe sends it. It is the only
            # ordering signal a webhook carries, so the recorder guards on
            # it: delivery is at least once and out of order, and a late
            # `created` must not overwrite a `requires_input` the member has
            # already been told about.
            'created': int(time.time()) if created is None else created,
            'data': {
                'object': {
                    'object':           'identity.verification_session',
                    'id':               session_id,
                    'metadata':         metadata or {},
                    # `last_error` rides on requires_input sessions and holds
                    # a machine code plus a reason string. It is an operator
                    # record. Tests use it to prove member-facing copy never
                    # repeats it back at the member.
                    'last_error':       last_error,
                    # Stripe does NOT send verified_outputs in a webhook: the
                    # API reference marks it "not returned by default; request
                    # it with the expand request parameter". Kept here only so
                    # a test can assert we do not depend on it. The document's
                    # issuing country comes from the VerificationReport named
                    # by last_verification_report.
                    'verified_outputs': verified_outputs or {},
                    'last_verification_report': last_verification_report,
                }
            },
        }
        body = json.dumps(payload).encode('utf-8')
        ts = str(int(time.time()))
        signed = f'{ts}.{body.decode()}'
        sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return SignedEvent(body=body, sig=f't={ts},v1={sig}')

    return _build


@pytest.fixture
def signed_rc_event() -> Callable[..., SignedEvent]:
    """Produces a RevenueCat webhook payload + bearer-auth header value.
    Used by Phase 5's IAP receipt-validation tests.

    Test expectation (from plan Task 5.2 Step 2):
        payload = signed_rc_event(
            type='INITIAL_PURCHASE',
            app_user_id=str(user.id),
            entitlement_id='premium',
            expires_at='2027-05-08T00:00:00Z',
        )
        client.post('/webhooks/revenuecat', data=payload.body,
                    headers={'Authorization': f'Bearer {RC_AUTH}'})
    """
    import json, time

    def _build(type: str = 'INITIAL_PURCHASE',
               app_user_id: str = '1',
               entitlement_id: str = 'premium',
               event_id: str | None = None,
               expires_at: str = '2099-01-01T00:00:00Z') -> SignedEvent:
        payload = {
            'event': {
                'id': event_id or f'rc_evt_{int(time.time() * 1000)}',
                'type': type,
                'app_user_id': app_user_id,
                'entitlement_id': entitlement_id,
                'expiration_at_ms': 0,
                'expiration_iso': expires_at,
            }
        }
        body = json.dumps(payload).encode('utf-8')
        # RC uses bearer-token auth, not signed payloads. The "sig" we return
        # is the bearer header value; tests pass it via Authorization.
        return SignedEvent(body=body, sig='Bearer test-rc-secret')

    return _build


# ---------------------------------------------------------------------------
# Shared person factory (2026-07-22).
#
# Every test file grew its own `_make_person` INSERT, and all of them omit
# `location_long_friendly` + `unit_id`. Both are NOT NULL with no default,
# so those helpers raise NotNullViolation against a correctly-migrated
# schema — 38 errors in the local suite, masking real signal. This is the
# one correct definition; new tests should use it.
# ---------------------------------------------------------------------------

@pytest.fixture
def make_person():
    from uuid import uuid4

    from database import api_tx

    created: list[int] = []

    def _make(name: str = 'Test', gender: str = 'Man', email: str | None = None) -> dict:
        # `email` defaults to the fixture's own @example.com address, which
        # emails.base.is_suppressed_send blocks on purpose. Pass a
        # @ahavah-test.invalid address when the test needs a MAILABLE person
        # (anything that reaches the outbox drain or a campaign send).
        address = email or f'fixture-{uuid4()}@example.com'
        with api_tx() as tx:
            row = tx.execute(
                """
                INSERT INTO person (
                    email, normalized_email, name, date_of_birth,
                    coordinates, gender_id, about,
                    location_short_friendly, location_long_friendly, unit_id
                )
                VALUES (
                    %(email)s, %(email)s, %(name)s, '1990-01-01',
                    ST_SetSRID(ST_MakePoint(0, 0), 4326)::geography,
                    (SELECT id FROM gender WHERE name = %(gender)s),
                    'about', 'Somewhere', 'Somewhere, Nowhere',
                    (SELECT id FROM unit LIMIT 1)
                )
                RETURNING id, uuid::text AS uuid
                """,
                dict(email=address, name=name, gender=gender),
            ).fetchone()
        created.append(row['id'])
        return row

    yield _make

    with api_tx() as tx:
        for pid in created:
            tx.execute('DELETE FROM person WHERE id = %(p)s', dict(p=pid))


# ---------------------------------------------------------------------------
# Email outbox (F07)
# ---------------------------------------------------------------------------
# Nothing in the codebase sends email synchronously any more: a campaign run,
# a welcome invite and a "your card is live" receipt all write an
# `email_outbox` row, and the `emailoutbox` cron drains it. A test that used
# to assert on a captured SMTP call now queues, drains here with a stub
# client, and asserts on what the drain handed SMTP.

@pytest.fixture
def outbox_drain():
    """Drain the outbox with a stub SMTP client; returns the list of send
    kwargs. Pass the person ids the test queued for: every OTHER due row is
    parked first, so one test's drain can never pick up another's leftovers
    (the suite shares one database and one outbox table)."""
    from database import api_tx
    from service.campaigns import outbox

    class _StubSmtp:
        def __init__(self):
            self.sent: list[dict] = []

        def send(self, **kw):
            self.sent.append(kw)
            return f'mid-{len(self.sent)}'

    def _drain(*person_ids: int) -> list[dict]:
        with api_tx() as tx:
            tx.execute(
                """UPDATE email_outbox SET next_attempt_at = NOW() + interval '1 hour'
                    WHERE state = 'queued'
                      AND (person_id IS NULL OR NOT (person_id = ANY(%(ids)s)))""",
                dict(ids=list(person_ids)))
        smtp = _StubSmtp()
        outbox.drain(api_tx, smtp)
        return smtp.sent

    return _drain


# ---------------------------------------------------------------------------
# Finish onboarding through the real route
# ---------------------------------------------------------------------------
# Seeds an onboardee with the fields Q_FINISH_ONBOARDING needs and a signed-in
# session, then POSTs /finish-onboarding with `body`. Returns (response, person
# id or None). The emails, the Meta event and the admin notice are replaced
# with no-ops. The person, onboardee and session are deleted afterwards.

@pytest.fixture
def finish_onboarding(client, monkeypatch):
    import hashlib
    import secrets
    from uuid import uuid4

    from database import api_tx
    import emails.member_welcome
    import emails.waitlist_admin
    import service.person as person_service

    monkeypatch.setattr(person_service.metapixel, 'send_complete_registration',
                        lambda **kw: None)
    monkeypatch.setattr(emails.member_welcome, 'send_member_welcome_async',
                        lambda *a, **kw: None)
    monkeypatch.setattr(emails.waitlist_admin, 'send_new_signup_notice_async',
                        lambda *a, **kw: None)

    emails_used: list[str] = []

    def _finish(body: dict | None = None, lead_source: str | None = None,
                photo: str | None = 'pending', email: str | None = None):
        # `photo`: the moderation status of the one photo the onboardee
        # uploaded (an upload starts 'pending'), or None for no photo. The
        # server requires one to finish (finding 94). `email`: the address
        # to sign up with, when the test needs to prepare something for it.
        email = email or f'onboard-{uuid4()}@example.com'
        emails_used.append(email)
        token = secrets.token_hex(64)
        with api_tx() as tx:
            tx.execute(
                """
                INSERT INTO onboardee (email, name, date_of_birth, coordinates,
                                       gender_id, lead_source)
                VALUES (%(e)s, 'Onboarding Test', '1992-02-02',
                        ST_SetSRID(ST_MakePoint(-59.6, 13.1), 4326)::geography,
                        (SELECT id FROM gender WHERE name = 'Woman'), %(ls)s)
                """,
                dict(e=email, ls=lead_source))
            if photo is not None:
                tx.execute(
                    """
                    INSERT INTO onboardee_photo (email, position, uuid, blurhash,
                                                 hash, moderation_status)
                    VALUES (%(e)s, 1, %(u)s, 'blur', %(h)s,
                            %(s)s::photo_moderation_status)
                    """,
                    dict(e=email, u=secrets.token_hex(32), h=secrets.token_hex(16),
                         s=photo))
            tx.execute(
                """
                INSERT INTO duo_session (session_token_hash, email, otp, signed_in)
                VALUES (%(h)s, %(e)s, '000000', TRUE)
                """,
                dict(h=hashlib.sha512(token.encode()).hexdigest(), e=email))
        r = client.post('/finish-onboarding', json=body or {},
                        headers={'Authorization': f'Bearer {token}'})
        with api_tx() as tx:
            row = tx.execute('SELECT id FROM person WHERE email = %(e)s',
                             dict(e=email)).fetchone()
        return r, (row['id'] if row else None)

    yield _finish

    with api_tx() as tx:
        for email in emails_used:
            tx.execute('DELETE FROM person WHERE email = %(e)s', dict(e=email))
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))
            tx.execute('DELETE FROM duo_session WHERE email = %(e)s', dict(e=email))


# ---------------------------------------------------------------------------
# Campaign link factory (Community Spotlight click receipts, wave 3b)
# ---------------------------------------------------------------------------
# Mints a real `/s/<key>` campaign link and hands back just the key, so a
# test can go straight to `record_click(tx, key, ...)` without repeating the
# make_campaign_link boilerplate every neighbouring test already had to write
# by hand. Opens (and closes) its own transaction -- callers must not already
# be inside one, since api_tx is never nested.

@pytest.fixture
def make_campaign_link():
    from uuid import uuid4

    from database import api_tx
    from service.campaigns import make_campaign_link as _make_link
    from service.config import WEB_BASE_URL

    def _make() -> str:
        with api_tx() as tx:
            url = _make_link(tx, f'test:{uuid4()}', f'{WEB_BASE_URL}/discover', None)
        return url.rsplit('/', 1)[1]

    return _make


# ---------------------------------------------------------------------------
# The owner's rest days (TEC-945)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'real_calendar: run against the real rest days in '
        'service/spotlight/restdays.py instead of an empty calendar')


@pytest.fixture(autouse=True)
def _calendar_without_rest_days(monkeypatch, request):
    """Every test runs as though no rest day is anywhere near.

    `dispatch_check` refuses to publish during one of the owner's rest
    periods, and it reads the real clock. Without this, every test that
    expects a row to dispatch would start failing on a real Sabbath (from
    17:00 Barbados the evening before), and a deploy on a Friday evening
    would be blocked by its own test suite. Tests of the rule itself either
    set their own dates on the module or opt out with
    `@pytest.mark.real_calendar`.

    KNOWN_THROUGH moves a year out for the same reason: brand posts refuse a
    slot past the last date the owner's calendar has been read for, and the
    real one is a fixed date that the calendar will overtake.
    """
    if request.node.get_closest_marker('real_calendar'):
        return
    from datetime import date, timedelta
    import service.spotlight.restdays as rd
    monkeypatch.setattr(rd, 'REST_DAYS', ())
    monkeypatch.setattr(rd, 'KNOWN_THROUGH', date.today() + timedelta(days=365))


# ---------------------------------------------------------------------------
# Photos and sessions (health review, Wave 2 photos lane)
# ---------------------------------------------------------------------------
# `add_photo(person_id, ...)` inserts a scored photo row with the given
# moderation status and face count, and returns its uuid. The row goes when
# make_person deletes the person (photo cascades). `sign_in(person)` gives a
# signed-in session for a make_person row and returns the request headers.

@pytest.fixture
def add_photo():
    import secrets

    from database import api_tx

    def _add(person_id: int, position: int = 1, status: str = 'approved',
             face_count: int | None = 1, face_confirmed: bool = False) -> str:
        uuid = secrets.token_hex(32)
        with api_tx() as tx:
            tx.execute(
                """
                INSERT INTO photo (uuid, person_id, position, blurhash, hash,
                                   nsfw_score, moderation_status, face_count,
                                   face_checked_at)
                VALUES (%(u)s, %(p)s, %(pos)s, %(b)s, %(h)s, 0.01,
                        %(s)s::photo_moderation_status, %(f)s,
                        CASE WHEN %(f)s::int IS NULL THEN NULL ELSE NOW() END)
                """,
                dict(u=uuid, p=person_id, pos=position, b=f'blur-{uuid[:8]}',
                     h=secrets.token_hex(16), s=status, f=face_count))
            if face_confirmed:
                tx.execute(
                    "UPDATE photo SET face_confirmed_at = NOW() WHERE uuid = %(u)s",
                    dict(u=uuid))
        return uuid

    return _add


@pytest.fixture
def sign_in():
    import hashlib
    import secrets

    from database import api_tx

    def _sign_in(person: dict) -> dict:
        tok = secrets.token_hex(32)
        with api_tx() as tx:
            email = tx.execute('SELECT email FROM person WHERE id = %(i)s',
                               dict(i=person['id'])).fetchone()['email']
            tx.execute(
                """INSERT INTO duo_session (session_token_hash, email, person_id,
                                            signed_in, otp)
                   VALUES (%(h)s, %(e)s, %(p)s, TRUE, '123456')""",
                dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=email,
                     p=person['id']))
        return {'Authorization': f'Bearer {tok}'}

    return _sign_in


# ---------------------------------------------------------------------------
# Sign-in codes through the real /request-otp route (TEC-1848)
# ---------------------------------------------------------------------------
# `signup_env.request(email, ip=..., **body)` posts /request-otp from a
# chosen client address. Nothing is mailed: `_send_otp` is replaced and
# every address it would have mailed lands in `signup_env.sent`.
# `signup_env.issued(token)` says whether a returned token is a real
# pending session (a code exists) or the decoy a refusal hands back.
#
# Flask-Limiter is switched off so a test sees only the rules it is about;
# the sign-up gate is open and the FireHOL list matches nothing. The
# new-address rules count in a private fakeredis, against a clock the test
# moves with `signup_env.advance(seconds)`. `signup_env.refusals()` lists
# the reasons recorded since the test began. The otp_request rows the test
# wrote are deleted afterwards.

@pytest.fixture
def signup_env(client, monkeypatch):
    import hashlib
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    import fakeredis

    from database import api_tx
    import service.person as person
    import service.signupguard as guard
    from service.api import decorators
    from service.api.decorators import limiter

    class _NotListed:
        def matches(self, _ip):
            return False

    sent: list[str] = []
    monkeypatch.setattr(person, '_send_otp', lambda email, otp: sent.append(email))
    monkeypatch.setattr(person, 'SIGNUPS_OPEN', True)
    monkeypatch.setattr(person, 'firehol', _NotListed())
    monkeypatch.setattr(limiter, 'enabled', False)
    # The local test/input switch that turns IP limits off must not turn
    # off the rules under test.
    monkeypatch.setattr(decorators, 'disable_ip_rate_limit', lambda: False)

    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    monkeypatch.setattr(guard, '_redis', lambda: redis)
    # 03:00 UTC on 14 Oct 2026: the rest of the UTC day is ahead of it.
    clock = {'t': 1791946800.0}
    monkeypatch.setattr(guard, '_now', lambda: clock['t'])

    def advance(seconds: float) -> None:
        clock['t'] += seconds

    # DNS never leaves the test. `signup_env.dns[domain]` is what a lookup
    # answers: True (takes mail, the default), False (cannot) or None (DNS
    # did not answer). `signup_env.dns_calls` lists the lookups made.
    dns: dict = {}
    dns_calls: list[str] = []

    def resolve(domain: str):
        dns_calls.append(domain)
        return dns.get(domain, True)

    monkeypatch.setattr(guard, '_resolve_mail_domain', resolve)

    started = datetime.now(timezone.utc)

    def refusals() -> list[str]:
        with api_tx('read committed') as tx:
            rows = tx.execute(
                """SELECT refused FROM otp_request
                    WHERE requested_at >= %(t)s AND refused IS NOT NULL
                    ORDER BY id""", dict(t=started)).fetchall()
        return [r['refused'] for r in rows]
    emails: list[str] = []

    def new_email(domain: str = 'gmail.com') -> str:
        # gmail.com is on the good-domain list, so a new address there gets
        # past the existing disposable-domain check. No dots or plus signs,
        # so normalisation leaves it as written.
        address = f'sg{uuid4().hex[:20]}@{domain}'
        emails.append(address)
        return address

    # Not 127.0.0.1: other tests in the shared database ban that address,
    # and a banned address is answered with a decoy, as a refusal is.
    def request(email: str, ip: str = '10.184.8.1', **body):
        emails.append(email)
        return client.post('/request-otp', json=dict(email=email, **body),
                           environ_base={'REMOTE_ADDR': ip})

    def issued(token: str) -> bool:
        with api_tx('read committed') as tx:
            row = tx.execute(
                'SELECT 1 FROM duo_session WHERE session_token_hash = %(h)s',
                dict(h=hashlib.sha512(token.encode()).hexdigest())).fetchone()
        return row is not None

    yield SimpleNamespace(sent=sent, request=request, issued=issued,
                          new_email=new_email, advance=advance,
                          refusals=refusals, redis=redis,
                          dns=dns, dns_calls=dns_calls)

    with api_tx() as tx:
        tx.execute('DELETE FROM otp_request WHERE requested_at >= %(t)s',
                   dict(t=started))
        for email in emails:
            tx.execute('DELETE FROM duo_session WHERE email = %(e)s', dict(e=email))
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=email))


# ---------------------------------------------------------------------------
# Growth foundations schema (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0066 is idempotent, so applying it here is what the deploy does.
# A test module that reads the lead table, the prompt bank or the new
# publishing kinds asks for it with
#     pytestmark = pytest.mark.usefixtures('growth_schema')

@pytest.fixture(scope='session')
def growth_schema():
    from pathlib import Path

    from database import api_tx

    path = (Path(__file__).resolve().parent.parent
            / 'migrations' / '0066_growth_foundations.sql')
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Quick questions (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0067 is idempotent, so applying it here is what the deploy does.
# A module that reads the quick-question tables asks for it with
#     pytestmark = pytest.mark.usefixtures('questions_schema')
# make_question() adds an active choice question with unique keys, so a
# test's answers and splits never meet another test's. drops.add() sets a
# question_drop row and puts back any row it replaced.

@pytest.fixture(scope='session')
def questions_schema(growth_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0067_quick_questions.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


@pytest.fixture
def make_question(questions_schema):
    import json
    from uuid import uuid4

    from database import api_tx

    made: list[str] = []

    def _make(labels=('Yes', 'No'), *, active: bool = True, sort: int = 0,
              text: str | None = None) -> dict:
        key = f'tq-{uuid4().hex[:10]}'
        fmt = 'either_or' if len(labels) == 2 else 'pick_one'
        options = [dict(key=f'c{i}-{uuid4().hex[:6]}', label=label) for i, label in enumerate(labels)]
        text = text or f'Test question {key}?'
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO prompt_bank (key, text, category, format, options, active, sort)
                   VALUES (%(k)s, %(t)s, 'test', %(f)s, %(o)s::jsonb, %(a)s, %(s)s)""",
                dict(k=key, t=text, f=fmt, o=json.dumps(options), a=active, s=sort))
        made.append(key)
        return dict(key=key, text=text, format=fmt, options=options)

    yield _make
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE prompt_key = ANY(%(k)s)', dict(k=made))
        tx.execute('DELETE FROM prompt_bank WHERE key = ANY(%(k)s)', dict(k=made))


@pytest.fixture
def drops(questions_schema):
    from database import api_tx

    made: list = []
    saved: list[dict] = []

    def _add(live_on, key: str, approved: bool = True) -> None:
        with api_tx() as tx:
            old = tx.execute(
                'SELECT live_on, prompt_key, approved_at, created_at FROM question_drop WHERE live_on = %(d)s',
                dict(d=live_on)).fetchone()
            if old is not None and live_on not in made:
                saved.append(dict(old))
            tx.execute('DELETE FROM question_drop WHERE live_on = %(d)s', dict(d=live_on))
            tx.execute(
                """INSERT INTO question_drop (live_on, prompt_key, approved_at)
                   VALUES (%(d)s, %(k)s, CASE WHEN %(a)s::boolean THEN NOW() END)""",
                dict(d=live_on, k=key, a=approved))
        made.append(live_on)

    yield _add
    with api_tx() as tx:
        tx.execute('DELETE FROM question_drop WHERE live_on = ANY(%(d)s)', dict(d=made))
        for row in saved:
            tx.execute(
                """INSERT INTO question_drop (live_on, prompt_key, approved_at, created_at)
                   VALUES (%(live_on)s, %(prompt_key)s, %(approved_at)s, %(created_at)s)
                   ON CONFLICT (live_on) DO NOTHING""", row)


@pytest.fixture
def push_member(make_person):
    """A mailable member with one push subscription in time zone `tz`,
    last online `online_days_ago` days ago."""
    from uuid import uuid4

    from database import api_tx

    def _make(name: str, *, tz: str | None = 'UTC', gender: str = 'Woman',
              online_days_ago: int = 1, push: bool = True) -> dict:
        p = make_person(name=name, gender=gender,
                        email=f'{name.lower()}-{uuid4().hex[:8]}@ahavah-test.invalid')
        with api_tx() as tx:
            tx.execute("UPDATE person SET last_online_time = NOW() - make_interval(days => %(d)s) "
                       "WHERE id = %(i)s", dict(d=online_days_ago, i=p['id']))
            if push:
                tx.execute(
                    """INSERT INTO push_subscription (person_id, endpoint, p256dh, auth, tz)
                       VALUES (%(i)s, %(e)s, 'k', 'a', %(tz)s)""",
                    dict(i=p['id'], e=f'https://push.test/{uuid4()}', tz=tz))
        return p

    return _make


@pytest.fixture
def pushed_questions(monkeypatch):
    """Every quick-question push, captured instead of sent, each reaching
    1 device."""
    from service.questions import pushes as qp

    sent: list[dict] = []
    monkeypatch.setattr(qp, '_push', lambda person_id, title, body, url, tag: sent.append(
        dict(person_id=person_id, title=title, body=body, url=url, tag=tag)) or 1)
    monkeypatch.setattr(qp, 'PUSH_READY', lambda: True)
    return sent
