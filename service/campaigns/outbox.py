"""Durable email outbox (F07) with visible uncertainty (F08).

Before this module, every campaign and transactional email was an SMTP call
made inside the request or script that decided to send it: an api restart
mid-run lost whatever had not gone out, a transient SMTP error lost the
message entirely, and a caller that retried could send twice. The outbox
splits that into two halves that can each fail independently:

  * ENQUEUE writes one row, in the SAME transaction as whatever decided to
    send (the candidate the invite belongs to, the receipt the "your card is
    live" email belongs to). The unique key (campaign, campaign_id,
    person_id) is now the idempotency point, so a retried request adds
    nothing rather than sending a second copy.

  * DRAIN reserves due rows in one transaction, talks to SMTP OUTSIDE any
    transaction, and records the outcome in another. SMTP is slow and can
    hang; holding a database transaction across it is what turned a mail
    hiccup into a lock pile-up.

F08 is the part that is easy to get wrong: a process that dies between
`smtp.send` returning and the acceptance being written leaves a row whose
real fate nobody knows. Re-sending it would double mail a member; dropping
it would silently lose the message. Neither is honest, so the reaper moves
such a row to `acceptance_unknown` and leaves it there for a human. That
state is surfaced by the admin status endpoint rather than swept up.

Nothing here nests a transaction: every function takes the transaction (or
raw connection) its caller already holds, and `drain` opens short ones in
sequence via the factory it is handed.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from emails.base import is_suppressed_send, mask_email
from service.campaigns import campaign_unsubscribed, can_send, log_send
from service.leads import lead_unsubscribed, news_refusal

# Backoff applied AFTER attempt n fails, indexed by n - 1. An attempt that
# takes the row to MAX_ATTEMPTS is terminal: it goes to 'failed' instead of
# being requeued, so the third entry is only reached if MAX_ATTEMPTS is
# raised. Deliberately short: these are transient SMTP errors, and a member
# waiting on a card-ready invite should not wait hours for the retry.
RETRY_BACKOFF_SECONDS = (60, 600, 3600)
MAX_ATTEMPTS = 3

# A row reserved longer than this had its drain die mid-flight (see F08 in
# the module docstring). Comfortably longer than any single SMTP call, so a
# merely slow send is never reaped out from under itself.
RESERVATION_TIMEOUT_SECONDS = 600

BATCH = 50

STATES = ('queued', 'reserved', 'accepted', 'acceptance_unknown', 'failed', 'skipped')

# Named post-send effects. A hook runs in the SAME transaction as the
# acceptance it belongs to, so `person.reinvite_sent_at` can never be stamped
# for a message that was not actually accepted by SMTP (the old
# `run_campaign(post_send=...)` callable stamped it around the send instead).
# A NAME is stored rather than a callable because the row outlives the
# process that wrote it: a pickled function could not survive a restart,
# which is the whole point of the outbox.
POST_SEND_HOOKS = {
    'reinvite_sent_at': lambda tx, person_id: tx.execute(
        "UPDATE person SET reinvite_sent_at = NOW() WHERE id = %(p)s", dict(p=person_id)),
}

# Payload keys a personal note may carry (see `enqueue`), passed to the
# mailer under the same names only when the row has them.
_PERSONAL_FIELDS = ('text_body', 'from_name', 'reply_to')

_Q_ENQUEUE = """
    INSERT INTO email_outbox (campaign, campaign_id, person_id, email, payload, exempt, unsub_scope,
                              next_attempt_at)
    VALUES (%(c)s, %(cid)s, %(pid)s, %(email)s, %(payload)s, %(exempt)s, %(scope)s,
            COALESCE(%(at)s, NOW()))
    ON CONFLICT (campaign, campaign_id, person_id) DO NOTHING
    RETURNING id
"""

# Lead mail (TEC-1845): the same table with lead_id in place of person_id.
# Its own partial unique index (migration 0066) is the idempotency point.
_Q_ENQUEUE_FOR_LEAD = """
    INSERT INTO email_outbox (campaign, campaign_id, lead_id, email, payload, exempt, unsub_scope,
                              next_attempt_at)
    VALUES (%(c)s, %(cid)s, %(lid)s, %(email)s, %(payload)s, %(exempt)s, 'news',
            COALESCE(%(at)s, NOW()))
    ON CONFLICT (campaign, campaign_id, lead_id) WHERE lead_id IS NOT NULL DO NOTHING
    RETURNING id
"""

# Organiser mail (TEC-1845, migration 0071): a gathering's organiser is
# neither a member nor a lead. Its own partial unique index is the
# idempotency point.
_Q_ENQUEUE_FOR_ORGANISER = """
    INSERT INTO email_outbox (campaign, campaign_id, organiser_id, email, payload, exempt, unsub_scope)
    VALUES (%(c)s, %(cid)s, %(oid)s, %(email)s, %(payload)s, TRUE, 'notifications')
    ON CONFLICT (campaign, campaign_id, organiser_id) WHERE organiser_id IS NOT NULL DO NOTHING
    RETURNING id
"""

# Matchmaker mail (TEC-1845, migration 0073): a recommended single and a
# mentor are neither members nor leads. Each has its own partial unique
# index as the idempotency point. Exempt, no List-Unsubscribe: each is sent
# once, about something a member asked for.
_Q_ENQUEUE_FOR_RECOMMENDATION = """
    INSERT INTO email_outbox (campaign, campaign_id, recommendation_id, email, payload, exempt, unsub_scope)
    VALUES (%(c)s, %(cid)s, %(rid)s, %(email)s, %(payload)s, TRUE, 'notifications')
    ON CONFLICT (campaign, campaign_id, recommendation_id) WHERE recommendation_id IS NOT NULL DO NOTHING
    RETURNING id
"""

_Q_ENQUEUE_FOR_MENTOR_LINK = """
    INSERT INTO email_outbox (campaign, campaign_id, mentor_link_id, email, payload, exempt, unsub_scope)
    VALUES (%(c)s, %(cid)s, %(mid)s, %(email)s, %(payload)s, TRUE, 'notifications')
    ON CONFLICT (campaign, campaign_id, mentor_link_id) WHERE mentor_link_id IS NOT NULL DO NOTHING
    RETURNING id
"""

# The inner SELECT takes the row locks with SKIP LOCKED, so a second drain
# running at the same moment simply does not see the rows this one is about
# to reserve -- it never blocks on them, and never reserves them twice.
# The rows are picked once, in a MATERIALIZED CTE, and then updated. The
# older `WHERE id IN (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED)` let
# Postgres run the sub-select more than once as a join, so one drain could
# reserve more than `n` rows (seen in tests: limit=1 returned 2); the extra
# rows were never sent and the reaper would have moved them to
# acceptance_unknown. Fixed 16 Oct 2026.
_Q_RESERVE = """
    WITH picked AS MATERIALIZED (
        SELECT id FROM email_outbox
         WHERE state = 'queued' AND next_attempt_at <= NOW()
         ORDER BY id
         LIMIT %(n)s
         FOR UPDATE SKIP LOCKED
    )
    UPDATE email_outbox o
       SET state = 'reserved', reserved_at = NOW(), attempts = o.attempts + 1
      FROM picked
     WHERE o.id = picked.id
    RETURNING o.*
"""

_Q_REAP = """
    UPDATE email_outbox
       SET state = 'acceptance_unknown', last_error = 'reservation expired'
     WHERE state = 'reserved'
       AND reserved_at < NOW() - make_interval(secs => %(s)s)
"""

_Q_ACCEPT = """
    UPDATE email_outbox
       SET state = 'accepted', sent_at = NOW(), provider_message_id = %(mid)s, last_error = NULL
     WHERE id = %(id)s
    RETURNING person_id, campaign, campaign_id, payload
"""

_Q_SKIP = """
    UPDATE email_outbox SET state = 'skipped', last_error = %(reason)s WHERE id = %(id)s
"""

_Q_REQUEUE = """
    UPDATE email_outbox
       SET state = 'queued', reserved_at = NULL, last_error = %(err)s,
           next_attempt_at = NOW() + make_interval(secs => %(backoff)s)
     WHERE id = %(id)s
"""

_Q_FAIL = """
    UPDATE email_outbox
       SET state = 'failed', reserved_at = NULL, last_error = %(err)s
     WHERE id = %(id)s
"""

_Q_STATUS = """
    SELECT state, count(*) AS n FROM email_outbox
     WHERE campaign = %(c)s AND campaign_id = %(cid)s
     GROUP BY state
"""

# Task 7 (Wave 3b): the cross-campaign view `status()` above cannot give,
# since it requires the caller to already know the (campaign, campaign_id)
# they are asking about. A row genuinely stuck in `acceptance_unknown` (F08)
# needs a human either way; this is what lets one be found in the first
# place. Grouped by run, not by campaign alone, since two different runs of
# the same campaign are two different things to look at.
_Q_UNKNOWN_SUMMARY = """
    SELECT campaign, campaign_id, count(*) AS n
      FROM email_outbox
     WHERE state = 'acceptance_unknown'
     GROUP BY campaign, campaign_id
     ORDER BY max(reserved_at) DESC
"""


def enqueue(tx, *, campaign: str, campaign_id: str, person_id: int, email: str,
            subject: str, html: str, from_addr: Optional[str], unsub_scope: str,
            list_unsubscribe: Optional[str] = None, exempt: bool = False,
            cap_days: int = 7, post_send: Optional[str] = None,
            requires_spotlight_opt_in: bool = False,
            not_before: Optional[datetime] = None,
            text: Optional[str] = None, from_name: Optional[str] = None,
            reply_to: Optional[str] = None) -> Optional[int]:
    """Queue one message. Returns the new row id, or None when this exact
    (campaign, campaign_id, person_id) was already queued, sent, skipped or
    failed -- which is what makes a retried caller safe.

    `from_addr` None sends from the mailer's default address (the like,
    match and message emails, which never named one).

    `not_before` holds the row until that instant: the drain only reserves
    rows whose next_attempt_at has passed, so a message can be queued today
    for a chosen slot (owner decision 1 Oct 2026, TEC-1613: the referral
    intros held by the cap go out two days later).

    Call this inside the transaction that decided to send, never around it:
    the invite and the candidate it belongs to either both commit or neither
    does.

    `post_send` is a KEY of POST_SEND_HOOKS, not a callable (see the note
    there). `cap_days` rides along so the drain's own frequency re-check uses
    the campaign's real window rather than the 7-day default -- E2's weekly
    cadence is a 6-day cap, and re-checking it at 7 would hold back exactly
    the member the 6-day window exists to reach.

    `requires_spotlight_opt_in` marks a message that exists only because the
    member consented to Community Spotlight (E4, E5). It rides in the payload
    rather than being inferred from the campaign name so the drain does not
    have to keep a list of which campaigns are Spotlight's, and it is what
    `_refusal` re-reads consent for at send time (fix wave item 2).

    `text`, `from_name` and `reply_to` are for a note sent personally by
    someone (the owner's note to the Spotlight candidates): a text/plain
    part, the display name on From and a Reply-To. Each is stored only when
    given, and the drain hands the mailer only what was stored, so every
    other message is sent exactly as before."""
    if post_send is not None and post_send not in POST_SEND_HOOKS:
        raise ValueError(f'unknown post_send hook: {post_send}')
    payload = dict(subject=subject, html=html, from_addr=from_addr,
                   list_unsubscribe=list_unsubscribe, post_send=post_send,
                   cap_days=int(cap_days),
                   requires_spotlight_opt_in=bool(requires_spotlight_opt_in))
    for key, value in (('text_body', text), ('from_name', from_name), ('reply_to', reply_to)):
        if value:
            payload[key] = value
    row = tx.execute(_Q_ENQUEUE, dict(c=campaign, cid=campaign_id, pid=person_id, email=email,
                                      payload=json.dumps(payload), exempt=bool(exempt),
                                      scope=unsub_scope, at=not_before)).fetchone()
    return row['id'] if row else None


def enqueue_for_lead(tx, *, campaign: str, campaign_id: str, lead_id: int, email: str,
                     subject: str, html: str, from_addr: Optional[str],
                     list_unsubscribe: Optional[str] = None, marketing: bool = False,
                     requested: bool = False,
                     not_before: Optional[datetime] = None) -> Optional[int]:
    """Queue one message for a lead: someone with no account who gave an
    email (service/leads). Returns the new row id, or None when this exact
    (campaign, campaign_id, lead_id) is already in the outbox or, for
    marketing mail, when service.leads.news_refusal refuses it.

    `marketing` is False for mail the visitor asked for in that very request
    (a confirmation, a reminder of a gathering they said they would attend),
    which goes even after they leave the news mail, and True for news (an
    alert, gatherings near them). News goes only to a confirmed address
    whose box was ticked, and stops once the lead leaves it. `requested` is
    True only for an alert:visitor lead's own alert: the visitor asked for
    that mail, so it needs no ticked box, though it still needs a confirmed
    address. The drain checks all of this again (_refusal). A lead has no
    frequency cap, no send log and no post-send hook: all three are keyed
    on a member."""
    if marketing and news_refusal(tx, lead_id, requested=requested):
        return None
    payload = dict(subject=subject, html=html, from_addr=from_addr,
                   list_unsubscribe=list_unsubscribe, post_send=None, cap_days=0,
                   requires_spotlight_opt_in=False, requested=requested is True)
    row = tx.execute(_Q_ENQUEUE_FOR_LEAD, dict(
        c=campaign, cid=campaign_id, lid=lead_id, email=email,
        payload=json.dumps(payload), exempt=not marketing, at=not_before)).fetchone()
    return row['id'] if row else None


def enqueue_for_organiser(tx, *, campaign: str, campaign_id: str, organiser_id: int, email: str,
                          subject: str, html: str, from_addr: Optional[str]) -> Optional[int]:
    """Queue one message for a gathering's organiser (TEC-1845): their
    manage link, their digest, an approval note. Always exempt: it is mail
    about the gathering they run, with no news in it, so it has no
    unsubscribe, cap, send log or hook. Returns the new row id, or None
    when this exact (campaign, campaign_id, organiser_id) is already in the
    outbox."""
    payload = dict(subject=subject, html=html, from_addr=from_addr, list_unsubscribe=None,
                   post_send=None, cap_days=0, requires_spotlight_opt_in=False)
    row = tx.execute(_Q_ENQUEUE_FOR_ORGANISER, dict(
        c=campaign, cid=campaign_id, oid=organiser_id, email=email,
        payload=json.dumps(payload))).fetchone()
    return row['id'] if row else None


def _exempt_payload(subject: str, html: str, from_addr: Optional[str]) -> str:
    return json.dumps(dict(subject=subject, html=html, from_addr=from_addr, list_unsubscribe=None,
                           post_send=None, cap_days=0, requires_spotlight_opt_in=False))


def enqueue_for_recommendation(tx, *, campaign: str, campaign_id: str, recommendation_id: int,
                               email: str, subject: str, html: str,
                               from_addr: Optional[str]) -> Optional[int]:
    """Queue the one email a recommended single gets (TEC-1845). They are
    neither a member nor a lead: "nobody gives their own email there"
    (service/leads/sources.py). Exempt, with no unsubscribe, since it is
    sent once ever. Returns the new row id, or None when this exact
    (campaign, campaign_id, recommendation_id) is already in the outbox."""
    row = tx.execute(_Q_ENQUEUE_FOR_RECOMMENDATION, dict(
        c=campaign, cid=campaign_id, rid=recommendation_id, email=email,
        payload=_exempt_payload(subject, html, from_addr))).fetchone()
    return row['id'] if row else None


def enqueue_for_mentor_link(tx, *, campaign: str, campaign_id: str, mentor_link_id: int,
                            email: str, subject: str, html: str,
                            from_addr: Optional[str]) -> Optional[int]:
    """Queue a mentor's invitation (TEC-1845): a mentor has no account, only
    the link a single made. Exempt, no unsubscribe. Returns the new row id,
    or None when already queued."""
    row = tx.execute(_Q_ENQUEUE_FOR_MENTOR_LINK, dict(
        c=campaign, cid=campaign_id, mid=mentor_link_id, email=email,
        payload=_exempt_payload(subject, html, from_addr))).fetchone()
    return row['id'] if row else None


def reserve(tx, limit: int = BATCH) -> list[dict]:
    """Claim up to `limit` due rows for this drain and return them in full.

    `tx` may be an `api_tx` transaction OR a raw psycopg connection -- both
    expose `.execute` -- exactly as `lock_request_rows` in
    service/spotlight/queue.py does, so a test can hold two independent
    reservations open on separate connections and prove the SKIP LOCKED
    behaviour rather than assuming it."""
    return tx.execute(_Q_RESERVE, dict(n=limit)).fetchall()


def reap_reserved(tx) -> int:
    """Move every reservation older than RESERVATION_TIMEOUT_SECONDS to
    `acceptance_unknown` and return how many. These are NOT retried: see the
    F08 paragraph in the module docstring."""
    return tx.execute(_Q_REAP, dict(s=RESERVATION_TIMEOUT_SECONDS)).rowcount


def mark_accepted(tx, id: int, provider_message_id: Optional[str]) -> None:
    """The message was accepted by SMTP. Records the acceptance, writes the
    frequency-cap send log, and runs the row's post-send hook -- all three in
    this one transaction, so none of them can be true without the others."""
    row = tx.execute(_Q_ACCEPT, dict(id=id, mid=str(provider_message_id) if provider_message_id else None)).fetchone()
    if not row:
        return
    # Lead mail (TEC-1845) has no member: the send log and the hooks are
    # keyed on person_id. The accepted outbox row is its record.
    if row['person_id'] is None:
        return
    log_send(tx, row['person_id'], row['campaign'], row['campaign_id'],
             str(provider_message_id) if provider_message_id else None)
    hook_name = (row['payload'] or {}).get('post_send')
    if hook_name:
        hook = POST_SEND_HOOKS.get(hook_name)
        if hook is None:
            # Should be unreachable: enqueue validates the name. A row
            # written by an older deploy whose hook has since been removed
            # lands here, and losing the side effect is better than losing
            # the acceptance record of a message that really did go out.
            print(f'email_outbox: unknown post_send hook {hook_name!r} on row {id}')
        else:
            hook(tx, row['person_id'])


def mark_skipped(tx, id: int, reason: str) -> None:
    """A send-time re-check refused this row: 'withdrawn', 'suppressed',
    'unsubscribed', 'capped', 'switched_off' or 'member_now'. Terminal, and
    deliberately distinct from 'failed' -- nothing went wrong, we simply
    must not send it. The same
    state and reason string `withdraw_member` writes directly onto the
    Spotlight invites it finds still queued."""
    tx.execute(_Q_SKIP, dict(id=id, reason=reason))


def mark_failed_attempt(tx, id: int, error: str, attempts: int) -> None:
    """SMTP refused (or blew up). Requeue on the backoff while attempts are
    left, otherwise park the row in 'failed' where the admin status endpoint
    can see it. `attempts` is the row's count AFTER `reserve` incremented
    it, i.e. the number of attempts made so far."""
    err = (error or '')[:2000]
    if attempts < MAX_ATTEMPTS:
        backoff = RETRY_BACKOFF_SECONDS[min(attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
        tx.execute(_Q_REQUEUE, dict(id=id, err=err, backoff=backoff))
    else:
        tx.execute(_Q_FAIL, dict(id=id, err=err))


_Q_SPOTLIGHT_CONSENT = """
    SELECT spotlight_opt_in, activated FROM person WHERE id = %(p)s
"""


def _is_member_address(tx, email: str) -> bool:
    from service.leads import clean_email
    cleaned = clean_email(email)
    if cleaned is None:
        return False
    return tx.execute('SELECT 1 FROM person WHERE normalized_email = %(ne)s LIMIT 1',
                      dict(ne=cleaned[1])).fetchone() is not None


def _refusal(tx, row: dict) -> Optional[str]:
    """The send-time re-checks, in the order they cost. None means send.

    These run again here, not only at enqueue time, because the gap between
    the two can be long: a member may have unsubscribed, been mailed by
    another campaign, or had their address suppressed since the row was
    written.

    Consent comes first (fix wave item 2). A Spotlight invite is queued
    inside the transaction that created the candidate, and the member can
    withdraw at any point after that -- opt out, delete their account, be
    deactivated or banned. `withdraw_member` marks the rows it can see
    `skipped` in its own transaction, but a row enqueued on either side of
    that sweep, or by a producer racing it, is still queued when the drain
    arrives. Mailing a withdrawn member is the consent breach the whole
    withdrawal path exists to prevent, so the drain re-reads consent rather
    than trusting the row: a missing person, a cleared `spotlight_opt_in` or
    a deactivated account all refuse. Only messages that carry
    `requires_spotlight_opt_in` are checked, so no other campaign pays for
    the read."""
    payload = row['payload'] or {}
    # Together (TEC-1845): each email's switch, and together_live, are read
    # again here, for a member or a lead, so turning one off stops what is
    # already queued.
    from service.tools import CAMPAIGN_SWITCHES, switch_on
    together = row['campaign'] in CAMPAIGN_SWITCHES
    if together and not switch_on(CAMPAIGN_SWITCHES[row['campaign']]):
        return 'switched_off'
    # Gatherings (TEC-1845): the same, for a member, a lead or an organiser.
    from service import events
    if row['campaign'] in events.CAMPAIGN_SWITCHES and not events.switch_on(
            events.CAMPAIGN_SWITCHES[row['campaign']]):
        return 'switched_off'
    # Matchmaker (TEC-1845): the same, for any recipient.
    from service import matchmaker
    if row['campaign'] in matchmaker.CAMPAIGN_SWITCHES and not matchmaker.switch_on(
            matchmaker.CAMPAIGN_SWITCHES[row['campaign']]):
        return 'switched_off'
    # A recommended single (TEC-1845) is neither a member nor a lead: the
    # suppression list applies, and the email is not sent once the address
    # has joined (they are a member now, and the app speaks for itself).
    if row.get('recommendation_id') is not None:
        if is_suppressed_send(row['email']):
            return 'suppressed'
        return 'member_now' if _is_member_address(tx, row['email']) else None
    # A mentor's invitation (TEC-1845): not once the single has ended the link.
    if row.get('mentor_link_id') is not None:
        if is_suppressed_send(row['email']):
            return 'suppressed'
        live_link = tx.execute('SELECT 1 FROM mentor_link WHERE id = %(i)s AND revoked_at IS NULL',
                               dict(i=row['mentor_link_id'])).fetchone()
        return None if live_link else 'withdrawn'
    # An organiser (TEC-1845) is neither a member nor a lead: only the
    # suppression list applies.
    if row.get('organiser_id') is not None:
        return 'suppressed' if is_suppressed_send(row['email']) else None
    # Lead mail (TEC-1845): there is no member to read consent, campaign
    # scopes or caps from. Suppression applies to every address. Mail the
    # visitor asked for (exempt) still goes; news is re-checked here as at
    # enqueue: refused once the lead has left it, while the address is
    # unconfirmed, and without a ticked box unless the visitor requested it.
    # A Together email is queued exempt, but its footer offers the news
    # link, so a lead who has left the news mail gets no more of it, as a
    # member who left notifications is refused below.
    if row.get('lead_id') is not None:
        if is_suppressed_send(row['email']):
            return 'suppressed'
        if not row['exempt']:
            return news_refusal(tx, row['lead_id'], requested=payload.get('requested') is True)
        if together and lead_unsubscribed(tx, row['lead_id']):
            return 'unsubscribed'
        return None
    if payload.get('requires_spotlight_opt_in'):
        consent = tx.execute(_Q_SPOTLIGHT_CONSENT, dict(p=row['person_id'])).fetchone()
        if not consent or not consent['spotlight_opt_in'] or not consent['activated']:
            return 'withdrawn'
    if is_suppressed_send(row['email']):
        return 'suppressed'
    if campaign_unsubscribed(tx, row['person_id'], row['unsub_scope']):
        return 'unsubscribed'
    if not can_send(tx, row['person_id'], row['campaign'], row['campaign_id'],
                    cap_days=int(payload.get('cap_days') or 7), exempt=bool(row['exempt'])):
        return 'capped'
    return None


def drain(tx_factory, smtp, limit: int = BATCH) -> dict:
    """Send up to `limit` messages. Returns dict(reserved, accepted, skipped,
    failed, unknown_reaped).

    Transaction shape, which is the whole point of this function: the reaper
    runs once, in its own transaction, at the start. Then each message gets
    FOUR short transactions of its own -- reserve it, re-check it, (SMTP with
    no transaction open), record the outcome -- and only then is the next one
    reserved.

    Reserving ONE row per iteration rather than the whole batch up front is
    deliberate. A drain that dies part way through (deploy, OOM, container
    kill) leaves every row it had already claimed stuck in 'reserved' until
    the reaper times them out, and every one of those is a message whose fate
    nobody can be sure of. Claiming them one at a time means at most the
    single message actually in flight is stranded; everything else is still
    'queued' and the next drain simply picks it up.

    `smtp.send` must never run inside a transaction -- it is a network round
    trip to a third party, and holding row locks across it is how a mail
    outage becomes a database outage."""
    with tx_factory() as tx:
        unknown_reaped = reap_reserved(tx)

    reserved = accepted = skipped = failed = 0
    while reserved < limit:
        with tx_factory() as tx:
            claimed = reserve(tx, limit=1)
        if not claimed:
            break
        row = claimed[0]
        reserved += 1
        payload = row['payload'] or {}
        with tx_factory() as tx:
            reason = _refusal(tx, row)
            if reason is not None:
                mark_skipped(tx, row['id'], reason)
        if reason is not None:
            skipped += 1
            print(f"email_outbox: skipped {row['campaign']} for {mask_email(row['email'])} ({reason})")
            continue
        personal = {k: payload[k] for k in _PERSONAL_FIELDS if payload.get(k)}
        try:
            message_id = smtp.send(subject=payload.get('subject'), body=payload.get('html'),
                                   to_addr=row['email'], from_addr=payload.get('from_addr'),
                                   list_unsubscribe=payload.get('list_unsubscribe'), **personal)
        except Exception as e:      # noqa: BLE001 -- any SMTP failure is a retryable attempt
            with tx_factory() as tx:
                mark_failed_attempt(tx, row['id'], str(e), int(row['attempts']))
            failed += 1
            print(f"email_outbox: attempt {row['attempts']} failed for {mask_email(row['email'])}: {e}")
            continue
        with tx_factory() as tx:
            mark_accepted(tx, row['id'], message_id)
        accepted += 1
        print(f"email_outbox: sent {row['campaign']} to {mask_email(row['email'])}")

    return dict(reserved=reserved, accepted=accepted, skipped=skipped, failed=failed,
                unknown_reaped=unknown_reaped)


def status(tx, campaign: str, campaign_id: str) -> dict[str, Any]:
    """Counts per state for one run, every state present even at zero so the
    admin dashboard never has to guess whether a missing key means zero or a
    state it does not know about.

    A state this build has never heard of (a row written by a newer deploy
    during a rollout, say) is bucketed under `other` rather than raising: the
    dashboard losing the label is a far smaller problem than the dashboard
    500ing. The `other` key only appears when there is something in it, so
    the normal shape stays the six states above."""
    out: dict[str, Any] = {s: 0 for s in STATES}
    for r in tx.execute(_Q_STATUS, dict(c=campaign, cid=campaign_id)).fetchall():
        if r['state'] in out:
            out[r['state']] = int(r['n'])
        else:
            out['other'] = out.get('other', 0) + int(r['n'])
    return out


def unknown_summary(tx) -> list[dict]:
    """Every (campaign, campaign_id) run with at least one row genuinely
    stuck in `acceptance_unknown`, newest first. `status()` above answers
    the same question for one run, but only for a campaign_id the caller
    already knows; this is the index that lets an operator find it without
    that."""
    return [dict(campaign=r['campaign'], campaign_id=r['campaign_id'], n=int(r['n']))
            for r in tx.execute(_Q_UNKNOWN_SUMMARY).fetchall()]
