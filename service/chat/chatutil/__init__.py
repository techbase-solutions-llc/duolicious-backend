from async_lru_cache import AsyncLruCache
from database.asyncdatabase import api_tx
from lxml import etree
from typing import Literal
import datetime
import os


# XMPP server local domain (MongooseIM LSERVER). Sourced from the env so
# dev / staging / production can each point at their own chat host. The
# default matches `service.config.XMPP_DOMAIN`; defined here as a plain
# `os.environ.get(...)` to avoid pulling the `service` package into
# `service.chat.chatutil` and creating an import-order surprise.
LSERVER = os.environ.get("AHAVAH_XMPP_DOMAIN", "ahavah.app")


# Reports/blocks only (migration 0035). This used to match ANY skipped
# row, so a plain pass between two MATCHED people silently killed their
# ability to message each other.
# A message passes only between a man and a woman (TEC-2038): a match is
# the only way into a chat, and a same-gender match made before likes
# checked gender must not carry messages.
Q_IS_SKIPPED = """
SELECT 1 WHERE is_blocked_pair(%(from_id)s, %(to_id)s)
    -- Staff are hidden from members, so no message crosses (TEC-2040).
    OR is_staff_hidden(%(from_id)s, %(to_id)s)
    OR is_staff_hidden(%(to_id)s, %(from_id)s)
    OR NOT EXISTS (
        SELECT 1
        FROM person mw_x
        JOIN gender mw_xg ON mw_xg.id = mw_x.gender_id
        JOIN person mw_y ON mw_y.id = %(to_id)s
        JOIN gender mw_yg ON mw_yg.id = mw_y.gender_id
        WHERE mw_x.id = %(from_id)s
          AND ((mw_xg.name = 'Man' AND mw_yg.name = 'Woman')
            OR (mw_xg.name = 'Woman' AND mw_yg.name = 'Man'))
    )
"""


# An inbox thread no one sees: the two are a reported or blocked pair, a
# tester and a member (is_blocked_pair holds both, TEC-2135), or the other
# person is deactivated or waiting to be deleted. Hidden, never deleted.
# Q_GET_INBOX (which the web's unread badge sums) and the unread-message
# push both read it, so the badge and the push agree with the list.
# remote_bare_jid is uuid@domain.
INBOX_THREAD_HIDDEN_SQL = """EXISTS (
        SELECT 1
        FROM person me
        JOIN person peer
          ON peer.uuid = uuid_or_null(split_part(inbox.remote_bare_jid, '@', 1))
        WHERE me.uuid = uuid_or_null(inbox.luser)
          AND (is_blocked_pair(me.id, peer.id)
               -- Staff, to a member (TEC-2040).
               OR is_staff_hidden(me.id, peer.id)
               OR NOT peer.activated
               OR peer.deletion_requested_at IS NOT NULL)
    )"""


Q_FETCH_PERSON_ID = """
SELECT id FROM person WHERE uuid = uuid_or_null(%(username)s)
"""


# A confirmed mutual match. `ahavah_match` stores the pair with
# LEAST/GREATEST ordering, so check both orientations rather than
# assuming which side is user_a.
Q_IS_MATCHED = """
SELECT
    1
FROM
    ahavah_match
WHERE
    user_a_id = %(from_id)s AND user_b_id = %(to_id)s
OR
    user_a_id = %(to_id)s   AND user_b_id = %(from_id)s
"""


def build_element(
    tag: str,
    text: str | None = None,
    attrib: dict | None = None,
    ns: str | None = None
) -> etree._Element:
    """
    Helper function to create an XML element.
    """
    element = etree.Element(tag)

    if ns is not None:
        element.set('xmlns', ns)

    for key, value in (attrib or {}).items():
        element.set(key, value)

    if text is not None:
        element.text = text

    return element


def format_timestamp(microseconds: int) -> str:
    """
    Converts a timestamp in microseconds to an ISO 8601 string.
    """
    timestamp_sec = microseconds / 1e6  # Convert microseconds to seconds
    dt = datetime.datetime.utcfromtimestamp(timestamp_sec)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def to_bare_jid(jid: str | None):
    if jid is None:
        return None

    try:
        return jid.split('@')[0]
    except:
        return None


def message_string_to_etree(
    to_username: str,
    from_username: str,
    id: str,
    type: Literal['chat', 'typing'] = 'chat',
    message_body: str | None = None,
    audio_uuid: str | None = None,
) -> etree._Element:
    message_etree = build_element(
        'message',
        attrib={
            'from': f'{from_username}@{LSERVER}',
            'to': f'{to_username}@{LSERVER}',
            'id': id,
            'type': type,
        } | ({
            'audio_uuid': audio_uuid
        } if audio_uuid else {

        }),
        ns='jabber:client',
    )

    if message_body is not None:
        body = build_element('body', text=message_body)

        request = build_element(
            'request',
            ns='urn:xmpp:receipts'
        )

        message_etree.extend([body, request])

    return message_etree


@AsyncLruCache(ttl=5)  # 5 seconds
async def fetch_is_skipped(from_id: int, to_id: int) -> bool:
    async with api_tx('read committed') as tx:
        await tx.execute(Q_IS_SKIPPED, dict(from_id=from_id, to_id=to_id))
        row = await tx.fetchone()

    return bool(row)


@AsyncLruCache(ttl=5)  # 5 seconds
async def fetch_is_matched(from_id: int, to_id: int) -> bool:
    """TRUE when the two people hold a confirmed mutual match. Matched
    pairs have each opted in to the other, so consent-based gates (the
    location age-verification hold) do not apply between them."""
    async with api_tx('read committed') as tx:
        await tx.execute(Q_IS_MATCHED, dict(from_id=from_id, to_id=to_id))
        row = await tx.fetchone()

    return bool(row)


@AsyncLruCache()
async def fetch_id_from_username(username: str) -> int | None:
    async with api_tx('read committed') as tx:
        await tx.execute(Q_FETCH_PERSON_ID, dict(username=username))
        row = await tx.fetchone()

    return row.get('id') if row else None
