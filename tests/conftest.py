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
    sql = path.read_text(encoding='utf-8')
    with api_tx() as tx:
        # Once 0071 has run (the shared test database), an outbox row may
        # name an organiser, and 0066's two-recipient check would refuse it.
        # Keep 0071's three-recipient check instead (TEC-1845).
        if tx.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'email_outbox' "
                      "AND column_name = 'organiser_id'").fetchone():
            sql = sql.replace('CHECK (num_nonnulls(person_id, lead_id) = 1)',
                              f'CHECK (num_nonnulls({_outbox_recipients(tx)}) = 1)')
        tx.execute(sql)


def _outbox_recipients(tx) -> str:
    """The recipient columns the shared test database's outbox has now:
    0071 adds organiser_id and 0073 recommendation_id and mentor_link_id.
    Re-running an older migration's check must keep the newer columns, or
    its ADD CONSTRAINT refuses a row another branch's test left behind
    (TEC-1845)."""
    cols = ['person_id', 'lead_id']
    for c in ('organiser_id', 'recommendation_id', 'mentor_link_id'):
        if tx.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'email_outbox' "
                      "AND column_name = %(c)s", dict(c=c)).fetchone():
            cols.append(c)
    return ', '.join(cols)


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

    migrations = Path(__file__).resolve().parent.parent / 'migrations'
    for name in ('0067_quick_questions.sql', '0077_push_tap_matchmaker_sources.sql'):
        with api_tx() as tx:
            tx.execute((migrations / name).read_text(encoding='utf-8'))


@pytest.fixture
def questions_live(monkeypatch):
    """The master switch on (AHAVAH_QUESTIONS_LIVE_ENABLED): the quick
    questions as members see them after launch. A module testing that
    behaviour asks for it beside questions_schema; tests/
    test_questions_live_switch.py tests the dark state."""
    monkeypatch.setenv('AHAVAH_QUESTIONS_LIVE_ENABLED', '1')


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


# ---------------------------------------------------------------------------
# Together (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0068 is idempotent, so applying it here is what the deploy does.
# A module that reads the tool tables asks for it with
#     pytestmark = pytest.mark.usefixtures('together_schema')

@pytest.fixture(scope='session')
def together_schema(growth_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0068_together.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Gatherings (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0071 is idempotent, so applying it here is what the deploy does.
# A module that reads the gathering tables asks for it with
#     pytestmark = pytest.mark.usefixtures('events_schema')

@pytest.fixture(scope='session')
def events_schema(together_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0071_events.sql'
    with api_tx() as tx:
        # Once 0073 has run, keep its five-recipient check (TEC-1845).
        cols = _outbox_recipients(tx)
        if 'organiser_id' not in cols:
            cols += ', organiser_id'
        sql = path.read_text(encoding='utf-8').replace(
            'CHECK (num_nonnulls(person_id, lead_id, organiser_id) = 1)',
            f'CHECK (num_nonnulls({cols}) = 1)')
        tx.execute(sql)


# Migration 0076 (TEC-1845, inviting gathering guests to join): one
# invitation per address. Idempotent, applied here as the deploy does.
# Autouse, as unmatch_schema is: the lead retention sweep
# (service/events/retention.py) reads lead_join_invite, and tests that run
# the whole sweep do not ask for the gathering tables by name.

@pytest.fixture(scope='session', autouse=True)
def join_invite_schema(events_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0076_lead_join_invite.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


_EVENT_SWITCH_VARS = (
    'AHAVAH_EVENTS_LIVE_ENABLED', 'AHAVAH_EVENTS_HOSTING_ENABLED',
    'AHAVAH_EVENTS_LIST_ENABLED', 'AHAVAH_EVENTS_INVITE_ENABLED',
    'AHAVAH_EVENTS_CONFIRM_EMAIL_ENABLED', 'AHAVAH_EVENTS_REMINDER_EMAIL_ENABLED',
    'AHAVAH_EVENTS_CHANGE_EMAIL_ENABLED', 'AHAVAH_EVENTS_CANCEL_EMAIL_ENABLED',
    'AHAVAH_EVENTS_DIGEST_EMAIL_ENABLED', 'AHAVAH_EVENTS_MANAGE_EMAIL_ENABLED',
)


@pytest.fixture
def events_live(monkeypatch):
    """Every gathering switch on: the release as it is after launch. A test
    of a dark or closed state deletes the one variable it is about."""
    for env in _EVENT_SWITCH_VARS:
        monkeypatch.setenv(env, '1')


@pytest.fixture
def mail_allowed(monkeypatch):
    """service.leads.mail_refusal lets every address through, so a route
    test never waits on Redis or a DNS lookup of a test domain. The rules
    themselves are tested in tests/test_lead_mail.py."""
    import service.leads as leads
    monkeypatch.setattr(leads, 'mail_refusal', lambda **kw: None)


@pytest.fixture
def organiser(events_schema):
    """organiser(kind='fellowship_leader', approved=True) -> dict(id, email,
    token, headers): a verified organiser (approved now when asked) with a
    fresh magic link. Its rows go afterwards (gatherings, links and outbox
    rows cascade)."""
    from uuid import uuid4

    from database import api_tx
    from service.events.organisers import issue_link

    made: list[int] = []

    def _make(kind: str = 'fellowship_leader', approved: bool = True,
              name: str = 'Grace Fellowship') -> dict:
        email = f'organiser-{uuid4().hex[:12]}@ahavah-test.invalid'
        with api_tx() as tx:
            oid = tx.execute(
                """INSERT INTO organiser (name, kind, email, normalized_email,
                                          verified_at, approved_at)
                   VALUES (%(n)s, %(k)s, %(e)s, %(e)s, NOW(),
                           CASE WHEN %(a)s::boolean THEN NOW() END)
                   RETURNING id""",
                dict(n=name, k=kind, e=email, a=approved)).fetchone()['id']
            token = issue_link(tx, oid)
        made.append(oid)
        return dict(id=oid, email=email, token=token,
                    headers={'X-Organiser-Token': token})

    yield _make

    with api_tx() as tx:
        tx.execute('DELETE FROM organiser WHERE id = ANY(%(i)s)', dict(i=made))


@pytest.fixture
def together_live(monkeypatch):
    """The master switch on (AHAVAH_TOGETHER_LIVE_ENABLED): Together as
    players see it after launch. tests/test_tool_sessions.py tests the
    dark state."""
    monkeypatch.setenv('AHAVAH_TOGETHER_LIVE_ENABLED', '1')


@pytest.fixture
def no_limits(monkeypatch):
    """Flask-Limiter off, so a test sees only the rules it is about."""
    from service.api.decorators import limiter
    monkeypatch.setattr(limiter, 'enabled', False)


@pytest.fixture
def tool_visitor():
    """A visitor with no account who confirmed an address with a sign-in
    code: an onboardee session, as /check-otp leaves it. Returns
    (email, headers). Sessions, onboardees and leads for the address are
    deleted afterwards."""
    import hashlib
    import secrets
    from uuid import uuid4

    from database import api_tx

    made: list[str] = []

    def _make(email: str | None = None) -> tuple[str, dict]:
        address = email or f'visitor-{uuid4().hex[:12]}@ahavah-test.invalid'
        tok = secrets.token_hex(32)
        with api_tx() as tx:
            tx.execute(
                """INSERT INTO duo_session (session_token_hash, email, signed_in, otp)
                   VALUES (%(h)s, %(e)s, TRUE, '123456')""",
                dict(h=hashlib.sha512(tok.encode()).hexdigest(), e=address))
        made.append(address)
        return address, {'Authorization': f'Bearer {tok}'}

    yield _make

    with api_tx() as tx:
        for address in made:
            tx.execute('DELETE FROM duo_session WHERE email = %(e)s', dict(e=address))
            tx.execute('DELETE FROM onboardee WHERE email = %(e)s', dict(e=address))
            tx.execute('DELETE FROM lead WHERE email = %(e)s', dict(e=address))


# ---------------------------------------------------------------------------
# Unmatch (TEC-1845)
# ---------------------------------------------------------------------------
# Migration 0070 is idempotent, so applying it here is what the deploy does.
# Autouse: from 0070 on, is_blocked_pair and is_deck_suppressed read
# unmatched_pair, and every visibility query in the API calls one of them.

@pytest.fixture(scope='session', autouse=True)
def unmatch_schema():
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0070_unmatch.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


# unmatch_pair: two members with their sign-in headers. The inbox has no key
# to person, so the inbox rows a test wrote for them are deleted afterwards;
# everything else keyed to them goes with make_person's delete.

@pytest.fixture
def unmatch_pair(make_person, sign_in):
    from types import SimpleNamespace

    from database import api_tx

    a = make_person(name='Hadassah', gender='Woman')
    b = make_person(name='Samuel', gender='Man')
    yield SimpleNamespace(a=a, b=b, a_headers=sign_in(a), b_headers=sign_in(b))
    with api_tx() as tx:
        tx.execute('DELETE FROM inbox WHERE luser = ANY(%(u)s)', dict(u=[a['uuid'], b['uuid']]))


@pytest.fixture
def outbox_rows(events_schema):
    """outbox_rows(campaign) -> the email_outbox rows of one campaign, as
    dicts, oldest first. Rows for organisers and leads go with them."""
    from database import api_tx

    def _rows(campaign: str) -> list[dict]:
        with api_tx('read committed') as tx:
            return [dict(r) for r in tx.execute(
                'SELECT * FROM email_outbox WHERE campaign = %(c)s ORDER BY id',
                dict(c=campaign)).fetchall()]

    return _rows


def _event_rows_cleanup(tx, slugs):
    """What a test's gatherings leave beside their own rows: their leads
    (and so the leads' outbox rows) and their posts."""
    for s in slugs:
        tx.execute('DELETE FROM lead WHERE source = %(s)s', dict(s=f'event:{s}'))
        keys = [r['request_key'] for r in tx.execute(
            'SELECT DISTINCT request_key FROM publishing_queue WHERE request_key LIKE %(p)s',
            dict(p=f'event:{s}:%')).fetchall()]
        if keys:
            tx.execute('DELETE FROM publishing_queue WHERE request_key = ANY(%(k)s)', dict(k=keys))
            tx.execute('DELETE FROM spotlight_revision WHERE request_key = ANY(%(k)s)', dict(k=keys))
            tx.execute('DELETE FROM campaign_link WHERE kind = ANY(%(k)s)',
                       dict(k=[f'post:{k}' for k in keys]))


@pytest.fixture
def event_cleanup():
    """event_cleanup(slug): forget this gathering's leads and posts after
    the test (its rows go with its organiser)."""
    from database import api_tx
    slugs: list[str] = []
    yield slugs.append
    with api_tx() as tx:
        _event_rows_cleanup(tx, slugs)


@pytest.fixture
def published(organiser, event_cleanup):
    """published(**over) -> slug: an approved organiser's published
    gathering 30 days ahead, in Dallas, inserted directly (no posts). Any
    column may be overridden; `organiser_row` gives an organiser dict from
    the organiser fixture to host it."""
    from datetime import datetime, time, timedelta, timezone
    from uuid import uuid4

    from database import api_tx
    from service.events.fields import region_for

    def _make(organiser_row: dict | None = None, **over) -> str:
        o = organiser_row or organiser()
        day = (datetime.now(timezone.utc) + timedelta(days=30)).date()
        start = datetime.combine(day, time(0, 0), timezone.utc)
        row = dict(
            slug=f'test-gathering-{uuid4().hex[:8]}', title='Marriage preparation evening',
            starts_at=start, ends_at=start + timedelta(hours=3), tz='America/Chicago',
            tz_label='Central Time', mode='in_person', city='Dallas', country='United States',
            venue='Grace Fellowship hall, 14 Elm Street, Dallas', venue_visibility='confirmed',
            online_url=None, description='An evening for single believers who hope to marry.',
            capacity=None, tags=['singles_welcome'], feast=None, show_going=False,
            status='published', published_at=datetime.now(timezone.utc))
        row.update(over)
        for k in ('starts_at', 'ends_at'):
            if isinstance(row[k], str):
                row[k] = datetime.fromisoformat(row[k])
        if 'ends_at' not in over and 'starts_at' in over:
            row['ends_at'] = row['starts_at'] + timedelta(hours=3)
        if row['mode'] == 'online':
            row.update(city=over.get('city'), country=over.get('country'), venue=None)
            row['online_url'] = row['online_url'] or 'https://meet.example.com/ahavah-test'
        row.setdefault('region', 'online' if row['mode'] == 'online' else region_for(row['country']))
        cols = list(row)
        with api_tx() as tx:
            tx.execute(
                f"""INSERT INTO event (organiser_id, {', '.join(cols)})
                    VALUES (%(oid)s, {', '.join(f'%({c})s' for c in cols)})""",
                dict(row, oid=o['id']))
        event_cleanup(row['slug'])
        return row['slug']

    return _make


@pytest.fixture
def confirmed_guest():
    """confirmed_guest(slug, *, name, email, party_size, share) -> dict(id,
    email, token): a confirmed going RSVP with a token, inserted directly,
    with its confirmed event:{slug} lead as a visitor's has (none for a
    member, given person_id). It goes with its gathering; the lead with
    event_cleanup."""
    from uuid import uuid4

    from database import api_tx
    from service.leads import confirm_lead, new_token, record_lead

    def _make(slug: str, *, name: str = 'Hannah Okafor', email: str | None = None,
              party_size: int = 1, share: bool = False, person_id: int | None = None) -> dict:
        address = email or f'guest-{uuid4().hex[:10]}@ahavah-test.invalid'
        token, hashed = new_token()
        with api_tx() as tx:
            lead_id = None
            if person_id is None:
                lead_id = record_lead(tx, email=address, source=f'event:{slug}')
                if lead_id is not None:
                    confirm_lead(tx, lead_id, 'link')
            rid = tx.execute(
                """INSERT INTO event_rsvp (event_id, name, email, normalized_email, party_size,
                                           confirmed_at, token_hash, confirm_by,
                                           share_email_with_organiser, source, person_id, lead_id)
                   SELECT id, %(n)s, %(e)s, %(e)s, %(p)s, NOW(), %(h)s, NOW() + interval '7 days',
                          %(sh)s, 'event:' || slug, %(pid)s, %(l)s
                     FROM event WHERE slug = %(slug)s
                   RETURNING id""",
                dict(n=name, e=address, p=party_size, h=hashed, sh=share, slug=slug,
                     pid=person_id, l=lead_id)).fetchone()['id']
        return dict(id=rid, email=address, token=token)

    return _make


@pytest.fixture
def fake_bucket(monkeypatch):
    """service.spotlight.storage._bucket replaced with a recorder:
    `.puts` holds (key, body, acl) per put_object, `.deletes` the keys
    delete_objects was asked to remove."""
    import service.spotlight.storage as storage

    class _Bucket:
        name = 'test-bucket'

        def __init__(self):
            self.puts: list[tuple] = []
            self.deletes: list[str] = []

        def put_object(self, Key, Body, ACL='private', ContentType=None, **kw):
            self.puts.append((Key, Body, ACL))

        def delete_objects(self, Delete):
            self.deletes.extend(o['Key'] for o in Delete['Objects'])
            return {'Deleted': Delete['Objects']}

    bucket = _Bucket()
    monkeypatch.setattr(storage, '_bucket', lambda: bucket)
    return bucket


@pytest.fixture
def admin_headers(make_person):
    """Request headers for a signed-in admin (roles ['admin']), built as
    tests/test_admin_tool_counts.py builds one."""
    import hashlib
    import secrets

    from database import api_tx

    p = make_person(name='EventsAdmin')
    tok = secrets.token_hex(32)
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s", dict(i=p['id']))
        tx.execute(
            """INSERT INTO duo_session (session_token_hash, email, person_id, signed_in, otp)
               SELECT %(h)s, email, id, TRUE, '123456' FROM person WHERE id = %(i)s""",
            dict(h=hashlib.sha512(tok.encode()).hexdigest(), i=p['id']))
    return {'Authorization': f'Bearer {tok}'}


# Migration 0072 (TEC-1845 admin audit): the ledger's admin reasons, the admin
# deactivation flag the sign-in queries read, and the other serious fixes. It
# is idempotent, so applying it once per session is what the deploy does.

@pytest.fixture(scope='session', autouse=True)
def admin_fixes_schema():
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0072_admin_serious_fixes.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# Matchmaker (TEC-1845)
# ---------------------------------------------------------------------------
# Migrations 0073 and 0074 are idempotent, so applying them here is what the
# deploy does. 0073 needs 0066 (lead) and 0071 (email_outbox.organiser_id)
# first.
# Autouse, as unmatch_schema is: from 0073 on the likes email and the deck
# read match_alert and shared_conversation, so every session needs it.

@pytest.fixture(scope='session', autouse=True)
def matchmaker_schema(events_schema):
    from pathlib import Path

    from database import api_tx

    migrations = Path(__file__).resolve().parent.parent / 'migrations'
    for name in ('0073_matchmaker.sql', '0074_matchmaker_alert_change.sql'):
        with api_tx() as tx:
            tx.execute((migrations / name).read_text(encoding='utf-8'))


# Migrations 0080 to 0082 (TEC-1845, in-app entry plan release 3): the
# member who made an organiser in the app, the share tags on a gathering's
# views and RSVPs, and the recommended single's landing token. Idempotent,
# applied here as the deploy does; autouse because the organiser, RSVP and
# recommendation code read the new columns.

@pytest.fixture(scope='session', autouse=True)
def release3_schema(matchmaker_schema):
    from pathlib import Path

    from database import api_tx

    migrations = Path(__file__).resolve().parent.parent / 'migrations'
    for name in ('0080_organiser_member.sql', '0081_event_share_tags.sql',
                 '0082_recommendation_landing.sql'):
        with api_tx() as tx:
            tx.execute((migrations / name).read_text(encoding='utf-8'))


_MATCHMAKER_SWITCH_VARS = (
    'AHAVAH_MATCHMAKER_LIVE_ENABLED', 'AHAVAH_MATCHMAKER_ALERTS_ENABLED',
    'AHAVAH_MATCHMAKER_VISITOR_ALERTS_ENABLED', 'AHAVAH_MATCHMAKER_INTRODUCTIONS_ENABLED',
    'AHAVAH_MATCHMAKER_MENTORS_ENABLED', 'AHAVAH_MATCHMAKER_ALERT_EMAIL_ENABLED',
    'AHAVAH_MATCHMAKER_VISITOR_CONFIRM_EMAIL_ENABLED', 'AHAVAH_MATCHMAKER_VISITOR_ALERT_EMAIL_ENABLED',
    'AHAVAH_MATCHMAKER_RECOMMEND_EMAIL_ENABLED', 'AHAVAH_MATCHMAKER_INTRO_EMAIL_ENABLED',
    'AHAVAH_MATCHMAKER_MENTOR_INVITE_EMAIL_ENABLED', 'AHAVAH_MATCHMAKER_ALERT_PUSH_ENABLED',
    'AHAVAH_MATCHMAKER_INTRO_PUSH_ENABLED',
)


@pytest.fixture
def matchmaker_live(monkeypatch):
    """Every matchmaker switch on: the release as it is after launch. A test
    of a dark or closed state deletes the one variable it is about."""
    for env in _MATCHMAKER_SWITCH_VARS:
        monkeypatch.setenv(env, '1')


@pytest.fixture
def member_pair(make_person, add_photo):
    """member_pair(gender_a='Woman', gender_b='Man') -> (a, b): two activated
    members, each with an approved photo, each looking for the other's
    gender. Their rows go with make_person."""
    from database import api_tx

    def _make(gender_a: str = 'Woman', gender_b: str = 'Man', *, name_a: str = 'Miriam',
              name_b: str = 'Daniel') -> tuple[dict, dict]:
        a = make_person(name=name_a, gender=gender_a)
        b = make_person(name=name_b, gender=gender_b)
        with api_tx() as tx:
            for me, other in ((a, gender_b), (b, gender_a)):
                tx.execute('UPDATE person SET activated = TRUE, last_online_time = NOW() '
                           'WHERE id = %(i)s', dict(i=me['id']))
                tx.execute("""INSERT INTO search_preference_gender (person_id, gender_id)
                              SELECT %(i)s, id FROM gender WHERE name = %(g)s""",
                           dict(i=me['id'], g=other))
        add_photo(a['id'])
        add_photo(b['id'])
        return a, b

    return _make


@pytest.fixture
def introducer_with_two(make_person, add_photo, sign_in):
    """introducer_with_two() -> (headers, miriam, daniel, hannah): Hannah,
    signed in, is matched with Miriam (a woman looking for men) and with
    Daniel (a man looking for women). All three are activated members with
    an approved photo. Rows go with make_person."""
    from database import api_tx

    def _member(name, gender, looks_for):
        from uuid import uuid4
        p = make_person(name=name, gender=gender,
                        email=f"{name.split()[0].lower()}-{uuid4().hex[:8]}@ahavah-test.invalid")
        with api_tx() as tx:
            tx.execute('UPDATE person SET activated = TRUE, last_online_time = NOW() WHERE id = %(i)s',
                       dict(i=p['id']))
            if looks_for:
                tx.execute("""INSERT INTO search_preference_gender (person_id, gender_id)
                              SELECT %(i)s, id FROM gender WHERE name = %(g)s""", dict(i=p['id'], g=looks_for))
        add_photo(p['id'])
        return p

    def _match(a, b):
        with api_tx() as tx:
            tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                       'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                       dict(a=a['id'], b=b['id']))

    def _make(introducer_name: str = 'Hannah Levi'):
        hannah = _member(introducer_name, 'Woman', 'Man')
        miriam = _member('Miriam Cohen', 'Woman', 'Man')
        daniel = _member('Daniel Stone', 'Man', 'Woman')
        _match(hannah, miriam)
        _match(hannah, daniel)
        return sign_in(hannah), miriam, daniel, hannah

    _make.member = _member
    _make.match = _match
    return _make


@pytest.fixture
def single_with_mentor(make_person, add_photo, sign_in):
    """single_with_mentor() -> (single, match, h_single, h_match): Rivka is
    matched with Samuel and has a confirmed mentor (Ruth, an account and a
    live link). single['link_id'] and single['mentor_account_id'] name them.
    Rows go with make_person; the mentor account goes afterwards."""
    from uuid import uuid4

    from database import api_tx

    accounts: list[int] = []

    def _make(single_name: str = 'Rivka Levi', match_name: str = 'Samuel Stone'):
        def member(name, gender):
            p = make_person(name=name, gender=gender,
                            email=f"{name.split()[0].lower()}-{uuid4().hex[:8]}@ahavah-test.invalid")
            with api_tx() as tx:
                tx.execute('UPDATE person SET activated = TRUE WHERE id = %(i)s', dict(i=p['id']))
            add_photo(p['id'])
            return p
        single = member(single_name, 'Woman')
        match = member(match_name, 'Man')
        mentor_email = f'ruth.{uuid4().hex[:8]}@ahavah-test.invalid'
        with api_tx() as tx:
            tx.execute('INSERT INTO ahavah_match (user_a_id, user_b_id) '
                       'VALUES (LEAST(%(a)s::int, %(b)s::int), GREATEST(%(a)s::int, %(b)s::int))',
                       dict(a=single['id'], b=match['id']))
            acc = tx.execute('INSERT INTO mentor_account (email, normalized_email) VALUES (%(e)s, %(e)s) '
                             'RETURNING id', dict(e=mentor_email)).fetchone()['id']
            link = tx.execute(
                """INSERT INTO mentor_link (single_person_id, mentor_email, mentor_normalized_email, relation,
                                            mentor_account_id, invite_expires_at, confirmed_at)
                   VALUES (%(s)s, %(e)s, %(e)s, 'parent', %(a)s, NOW() + interval '14 days', NOW())
                   RETURNING id""", dict(s=single['id'], e=mentor_email, a=acc)).fetchone()['id']
        accounts.append(acc)
        single = dict(single, link_id=link, mentor_account_id=acc, mentor_email=mentor_email)
        return single, match, sign_in(single), sign_in(match)

    yield _make
    with api_tx() as tx:
        # A confirmed live link must name its account, so the links end first.
        tx.execute('UPDATE mentor_link SET revoked_at = COALESCE(revoked_at, NOW()) '
                   'WHERE mentor_account_id = ANY(%(i)s)', dict(i=accounts))
        tx.execute('DELETE FROM mentor_account WHERE id = ANY(%(i)s)', dict(i=accounts))


# ---------------------------------------------------------------------------
# Admin, acting on the community (TEC-1897)
# ---------------------------------------------------------------------------
# Migration 0075 is idempotent, so applying it here is what the deploy does.
# It needs 0072 (person_report) first. Autouse: from TEC-1897 on, every
# presence bump writes member_online_day and the report email reads
# admin_alert_pref, and a database without them would stop moving
# last_online_time for every test file.

@pytest.fixture(scope='session', autouse=True)
def admin_community_schema(admin_fixes_schema):
    from pathlib import Path

    from database import api_tx

    path = Path(__file__).resolve().parent.parent / 'migrations' / '0075_admin_community.sql'
    with api_tx() as tx:
        tx.execute(path.read_text(encoding='utf-8'))


@pytest.fixture
def admin_bearer(make_person, sign_in):
    """The Authorization header of a signed-in admin. The account has the
    admin role, so the member rule leaves it out of every count."""
    from database import api_tx

    p = make_person(name='CommunityAdmin')
    with api_tx() as tx:
        tx.execute("UPDATE person SET roles = ARRAY['admin']::TEXT[] WHERE id = %(i)s",
                   dict(i=p['id']))
    return sign_in(p)
