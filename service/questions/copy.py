"""What the quick-question pushes and the E2 line say (TEC-1845).

Draft copy from the spec. It goes through the ux-writing pass and the
owner's proofs (scripts/send_question_proofs.py) before any switch goes on.
Nothing here names a person or carries an answer: a lock screen shows it.
Each body stays within LOCK_SCREEN_CHARS. Owner decision 1 drops the
question on the first free day of the week, so no line names Sunday.
"""
from __future__ import annotations

LOCK_SCREEN_CHARS = 110

WEEKLY_TITLE = "This week's question"
# Not "see who picked the same" (the spec's draft): the card shows counts,
# not people, so it promised names it never gives.
WEEKLY_TAIL = 'One tap, then see how others answered.'
MATCH_TITLE = 'An easy first line'
MATCH_BODY = 'Your new match has a question waiting. Answer first, then see theirs.'
LAUNCH_TITLE = 'New on Ahavah: quick questions'
LAUNCH_TAIL = 'Answer with one tap.'

# Week 1 of the approved order, for proofs and previews: nothing per member.
SAMPLE_QUESTION = dict(
    key='mountains-or-sea', text='Would you rather wake up to mountains or the sea?',
    format='either_or',
    options=[dict(key='mountains', label='Mountains'), dict(key='sea', label='The sea')])


def in_sentence(label: str) -> str:
    """Options are written to read inside a sentence once their first
    letter is lower-cased (spec, The launch question set)."""
    return label[:1].lower() + label[1:]


def short_question(question: dict) -> str:
    """'Mountains or the sea?' or 'Coffee, tea or something else?'."""
    labels = [o['label'] for o in question['options']]
    parts = [labels[0], *(in_sentence(label) for label in labels[1:])]
    return f"{', '.join(parts[:-1])} or {parts[-1]}?"


def weekly_push(live_on: str, question: dict) -> dict:
    return dict(title=WEEKLY_TITLE, body=f'{short_question(question)} {WEEKLY_TAIL}',
                url='/discover?src=qpush', tag=f'question:{live_on}')


def launch_push(live_on: str, question: dict) -> dict:
    return dict(title=LAUNCH_TITLE, body=f'{short_question(question)} {LAUNCH_TAIL}',
                url='/discover?src=lpush', tag=f'question:{live_on}')


def match_question_push(other_uuid: str, match_id: str) -> dict:
    """Reuses the match's own tag, so it replaces the match notification."""
    return dict(title=MATCH_TITLE, body=MATCH_BODY,
                url=f'/chat/{other_uuid}?src=mpush', tag=f'match:{match_id}')


def e2_line(question: dict) -> str:
    return f"This week's question: {in_sentence(short_question(question))} Answer in the app."


# What scripts/send_question_proofs.py pushes to the owner's account: the
# real wording, with links that record no tap and open nobody's chat. The
# weekly and launch proofs share one tag, so a device that replaces by tag
# shows only the launch proof once both arrive.
PUSH_PROOFS = [
    dict(weekly_push('proof', SAMPLE_QUESTION), url='/discover', kind='question'),
    dict(match_question_push('proof', 'proof'), url='/inbox', kind='match_question'),
    dict(launch_push('proof', SAMPLE_QUESTION), url='/discover', kind='questions_launch'),
]
