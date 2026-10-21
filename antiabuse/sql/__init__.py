# The last 25 messages between a reporter and the person they reported, from
# the reporter's own archive, oldest first. Read by the dashboard's "Show
# messages" (service/api/admin/moderation_routes.py), never by the report
# email (TEC-1845). `held` marks a message kept in the unmatch hold.
Q_LAST_MESSAGES = """
WITH archive AS (
    SELECT mam_message.id, mam_message.direction, mam_message.message,
           mam_message.search_body, FALSE AS held
      FROM mam_message
      JOIN person
        ON person.id = mam_message.person_id
       AND person.uuid = %(subject_uuid)s
     WHERE mam_message.remote_bare_jid IN (%(subject_uuid)s::TEXT, %(object_uuid)s::TEXT)
    UNION ALL
    -- An unmatched conversation (TEC-1845, migration 0070) is held out of
    -- sight for exactly this: a report made after the unmatch.
    SELECT unmatched_message.id, unmatched_message.direction, unmatched_message.message,
           unmatched_message.search_body, TRUE AS held
      FROM unmatched_message
      JOIN person
        ON person.id = unmatched_message.person_id
       AND person.uuid = %(subject_uuid)s
     WHERE unmatched_message.remote_bare_jid IN (%(subject_uuid)s::TEXT, %(object_uuid)s::TEXT)
), last_messages AS (
    SELECT
        id,
        CASE
        WHEN direction = 'O'
            THEN 'reporter'
            ELSE 'accused'
        END AS sent_by,
        message,
        search_body,
        held
    FROM
        archive
    ORDER BY
        id DESC
    LIMIT 25
)
SELECT
    id,
    sent_by,
    message,
    search_body,
    held
FROM
    last_messages
ORDER BY
    id
"""

# What the report email says about a report (TEC-1845, 21 Oct 2026): who
# reported whom and how many messages the two have exchanged, counted in the
# reporter's archive and the unmatch hold as Q_LAST_MESSAGES reads them.
#
# It used to mint a banned_person_admin_token for both people and a
# deleted_photo_admin_token for every photo, for the email's one-click ban
# and photo-removal links. The email no longer carries them; moderation is
# done in the dashboard. Tokens already in an inbox still work through
# /admin/ban-link and /admin/delete-photo-link.
Q_MAKE_REPORT = """
WITH reporter AS (
    SELECT id, uuid, name FROM person WHERE uuid = uuid_or_null(%(subject_uuid)s::TEXT)
), reported AS (
    SELECT id, uuid, name FROM person WHERE uuid = uuid_or_null(%(object_uuid)s::TEXT)
)
SELECT
    reporter.id           AS reporter_id,
    reporter.uuid::TEXT   AS reporter_uuid,
    reporter.name         AS reporter_name,
    reported.id           AS reported_id,
    reported.uuid::TEXT   AS reported_uuid,
    reported.name         AS reported_name,
    (
        (SELECT count(*) FROM mam_message
          WHERE person_id = reporter.id
            AND remote_bare_jid IN (%(subject_uuid)s::TEXT, %(object_uuid)s::TEXT))
      + (SELECT count(*) FROM unmatched_message
          WHERE person_id = reporter.id
            AND remote_bare_jid IN (%(subject_uuid)s::TEXT, %(object_uuid)s::TEXT))
    )::INT                AS message_count,
    NOW()                 AS reported_at
FROM
    reporter, reported
"""

Q_INSERT_SKIPPED = """
WITH subject_person_id AS (
    SELECT
        id
    FROM
        person
    WHERE
        uuid = uuid_or_null(%(subject_uuid)s::TEXT)
), object_person_id AS (
    SELECT
        id
    FROM
        person
    WHERE
        uuid = uuid_or_null(%(object_uuid)s::TEXT)
), bot_report AS (
    SELECT
        (
            reporter.sign_up_time < now() - interval '1 month'
        AND
            reporter.verification_level_id >= 3
        OR
            reporter.roles && ARRAY['admin', 'mod']
        ) AS is_trustworthy
    FROM
        person AS reporter
    WHERE
        reporter.uuid = uuid_or_null(%(subject_uuid)s::TEXT)
    AND
        %(is_bot_report)s
), q1 AS (
    INSERT INTO skipped (
        subject_person_id,
        object_person_id,
        reported,
        report_reason
    ) VALUES (
        (SELECT id FROM subject_person_id),
        (SELECT id FROM object_person_id),
        %(reported)s,
        %(report_reason)s
    )
    -- Re-passing must RESTART the pass window (0036; 30 days since 0059).
    -- The old ON CONFLICT DO NOTHING left created_at at its original
    -- value, so once a pass was 7 days old the profile recycled into
    -- the deck EVERY session and re-passing was a silent no-op - the
    -- member could never pass them again ("my deck keeps resetting
    -- inconsistently", 2026-08-11: 96 percent of all passes were in
    -- this zombie state). Reports stay permanent: reported only ever
    -- escalates (OR), and a plain re-pass never overwrites a report's
    -- reason.
    -- A plain pass on a pair already reported keeps the report's time: the
    -- pair is blocked both ways, so there is no pass window to restart, and
    -- a moved created_at would read as a fresh report (migration 0072's
    -- person_report trigger files one whenever it moves).
    ON CONFLICT (subject_person_id, object_person_id) DO UPDATE SET
        created_at = CASE
            WHEN skipped.reported AND NOT EXCLUDED.reported THEN skipped.created_at
            ELSE NOW()
        END,
        reported = skipped.reported OR EXCLUDED.reported,
        report_reason = CASE
            WHEN EXCLUDED.reported THEN EXCLUDED.report_reason
            ELSE skipped.report_reason
        END
), q2 AS (
    DELETE FROM search_cache
    WHERE
        searcher_person_id = (SELECT id FROM subject_person_id) AND
        prospect_person_id = (SELECT id FROM object_person_id)
    OR
        searcher_person_id = (SELECT id FROM object_person_id) AND
        prospect_person_id = (SELECT id FROM subject_person_id)
), q3 AS (
    UPDATE
        person
    SET
        verification_required = TRUE
    FROM
        bot_report
    WHERE
        bot_report.is_trustworthy
    AND
        person.uuid = uuid_or_null(%(object_uuid)s::TEXT)
    RETURNING
        1
)
SELECT EXISTS (
    SELECT * FROM q3
) AS is_automoded_bot
"""
