"""What a hard delete does beyond deleting the person row.

Both hard deletes run these in the transaction that deletes the person:
the deletion cron (service/cron/pendingdeletion) and the admin's
DELETE /admin/users/<uuid>. Until 13 Oct 2026 the admin route ran none
of them, so a member an admin deleted kept their photos and voice
recording on the CDN and their inbox and waitlist rows (Wave 1 review of
the health review remediation). The referral statements live in
service.referrals (Q_PURGE_REFERRALS_OF, Q_FORGET_CLICK_INVITER).

Before the person delete (`ids`: person ids). Photo and audio rows cascade
off person, but the CDN cleaners read only undeleted_photo and
undeleted_audio, so the uuids are staged first (F11):
"""

Q_STAGE_PHOTOS_FOR_REMOVAL = """
    INSERT INTO undeleted_photo (uuid)
    SELECT uuid FROM photo WHERE person_id = ANY(%(ids)s)
    ON CONFLICT DO NOTHING
"""

Q_STAGE_AUDIO_FOR_REMOVAL = """
    INSERT INTO undeleted_audio (uuid)
    SELECT uuid FROM audio WHERE person_id = ANY(%(ids)s)
    ON CONFLICT DO NOTHING
"""

# Tables with no cascading key to person (audit Privacy #1, #2).

# inbox: the chat server's last-message store, keyed on the member's JID
# name (person.uuid). Holds last-message bodies and peer JIDs.
Q_DELETE_INBOX_OF = """
    DELETE FROM inbox WHERE luser = ANY(%(uuids)s)
"""

# waitlist_signup: the pre-sign-up answers, keyed on email.
Q_DELETE_WAITLIST_OF = """
    DELETE FROM waitlist_signup WHERE email = ANY(%(emails)s)
"""

# beta_signup: the beta cohort row, keyed on email. Its person_id key does
# not reach a row whose person_id was never set, so it goes by email too.
Q_DELETE_BETA_SIGNUP_OF = """
    DELETE FROM beta_signup WHERE email = ANY(%(emails)s)
"""
