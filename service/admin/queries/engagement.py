"""What members actually do: likes, matches, and conversations.

None of this was visible anywhere in the admin until 2026-09-24, while
production held 98 likes, 5 mutual matches and 29 messages across 9
conversations. The owner asked for it in these words: "does the dashboard
show likes, matches and ongoing chats? (not the content of the chat just
chats initiated and chats responded to)".

CONTENT IS NEVER READ.

`mam_message` holds the text of every message members have sent each other.
No query in this module may reference `message`, `search_body` or
`translations`. That is not a matter of care: `tests/test_admin_engagement.py`
reads this file and fails if any of those names appear in it, so a later edit
cannot widen the surface quietly.

FOUR THINGS ABOUT THESE TABLES, EACH OF WHICH WOULD GIVE A PLAUSIBLE WRONG
ANSWER.

1. `liked` is one row per direction (`liker_id`, `liked_id`, `created_at`,
   `is_super`). A match is a pair where both directions exist, so counting
   matches without a `liker_id < liked_id` guard counts every match twice.

2. `mam_message` stores every message TWICE, once in each participant's
   archive, as `direction` 'I' and 'O'. Production held 58 rows for 29
   messages. Every query here filters to the outgoing copy, which is also
   what makes `person_id` mean "the sender".

3. `mam_message` has no timestamp column. Its `id` is a MongooseIM MAM id:
   microseconds since the epoch, shifted left by 8 bits, so
   `to_timestamp(id / 1000000 / 256)` decodes it. Verified against
   production on 2026-09-24: oldest row 2026-07-09, newest 2026-09-21, both
   inside the product's life.

4. `remote_bare_jid` is the OTHER party's `person.uuid`. On 2026-09-24 all
   58 rows joined cleanly to `person` on it, and it carried no domain part.
   `split_part(..., '@', 1)` is used anyway: it is a no-op on a bare uuid
   and keeps working if the chat service ever starts qualifying JIDs.
"""
from __future__ import annotations

# One row per message actually sent, with both ends resolved to person ids
# and the pair normalised so {a,b} and {b,a} are the same conversation.
# Everything below builds on this, which is why the traps are handled once.
_SENT_MESSAGES = """
    SELECT
        m.person_id                                   AS sender_id,
        p.id                                          AS recipient_id,
        LEAST(m.person_id, p.id)                      AS lo,
        GREATEST(m.person_id, p.id)                   AS hi,
        to_timestamp(m.id / 1000000 / 256)            AS sent_at
      FROM mam_message m
      JOIN person p
        ON p.uuid::text = split_part(m.remote_bare_jid, '@', 1)
     WHERE m.direction = 'O'
"""

Q_ENGAGEMENT_KPIS = f"""
    WITH sent AS ({_SENT_MESSAGES}),
    -- One row per conversation, carrying how many distinct people have
    -- written in it. Two means both sides did.
    convo AS (
        SELECT lo, hi, COUNT(DISTINCT sender_id) AS voices
          FROM sent GROUP BY lo, hi
    )
    SELECT
        (SELECT COUNT(*) FROM liked) AS likes_total,

        (SELECT COUNT(*) FROM liked
          WHERE created_at > NOW() - INTERVAL '7 days') AS likes_7d,

        -- Both directions of a mutual like are rows, so this guard is what
        -- stops every match being counted twice.
        (SELECT COUNT(*) FROM liked a
           JOIN liked b ON a.liker_id = b.liked_id AND a.liked_id = b.liker_id
          WHERE a.liker_id < a.liked_id) AS matches_total,

        -- Someone reached out. Whether anyone answered is the next figure.
        (SELECT COUNT(*) FROM convo) AS conversations_total,

        -- Both people have written in it. This is the number the owner
        -- asked for and the one that says whether the product is doing its
        -- job: a pile of unanswered openers looks identical to a busy
        -- community until the two are split apart.
        (SELECT COUNT(*) FROM convo WHERE voices >= 2) AS conversations_answered,

        (SELECT COUNT(*) FROM sent) AS messages_total,

        (SELECT COUNT(*) FROM sent
          WHERE sent_at > NOW() - INTERVAL '7 days') AS messages_7d
"""
