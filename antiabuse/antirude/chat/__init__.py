from antiabuse.normalize import normalize_string
from antiabuse.normalize.normalizationlists import chat
import re


_needle = '(' + '|'.join(f'{re.escape(s)}' for s in chat) + ')'


_rude_pattern = (
    r'((?<=[^a-z0-9])|^)' +
    f'{_needle}' +
    r'((?=[^a-z0-9])|$)')


_rude_matcher = re.compile(_rude_pattern, re.IGNORECASE)


def is_rude(s: str) -> bool:
    return \
            bool(_rude_matcher.search(
                normalize_string(s, chat, do_remove_modifiers=False))) or \
            bool(_rude_matcher.search(
                normalize_string(s, chat, do_remove_modifiers=True)))


def rude_matches(s: str) -> list[str]:
    """The listed words or phrases a message matched, in the list's own
    spelling, each once. Moderation shows these instead of the message
    (owner, 13 Oct 2026): a moderator sees why it was flagged, never what
    else the member wrote."""
    found: list[str] = []
    for remove_modifiers in (False, True):
        normalized = normalize_string(s, chat, do_remove_modifiers=remove_modifiers)
        for m in _rude_matcher.finditer(normalized):
            word = m.group(2).lower()
            if word not in found:
                found.append(word)
    return found
