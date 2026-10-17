"""Together, release 1: the couple tools (TEC-1845).

docs/superpowers/specs/2026-10-13-couple-tools-design.md and
docs/superpowers/plans/2026-10-17-together-release-1.md.

  questions  the game's question keys and options
  scoring    the port of the web's scoring engine, the Us result
  results    the Me archetype, knows-me guesses, the board
  checklist  checklist keys, the comparison, the top items
  sessions   start, answer, finish, read, save, join, share, delete
  mail       the invite, answered, ready and summary emails
  retention  the 12 month sweep
  admin      counts for Admin > Growth, never answers

Dark until launch: while the together_live switch is off
(AHAVAH_TOGETHER_LIVE_ENABLED, service/campaigns/switches.py) every /tools
route but /tools/status answers 404 and no Together email is queued or
sent, whichever way its own switch is set. The proofs
(scripts/send_together_proofs.py) and the admin counts work either way.
"""
from service.campaigns.switches import enabled

# Each Together email's outbox campaign and its switch. The outbox drain
# reads it again at send time (service/campaigns/outbox.py), so a switch
# turned off after a row was queued stops it.
CAMPAIGN_SWITCHES = {
    'together_answered': 'together_answered_email',
    'together_ready': 'together_ready_email',
    'together_summary': 'together_summary_email',
}


def live() -> bool:
    """Together is launched: the routes answer."""
    return enabled('together_live')


def switch_on(name: str) -> bool:
    """An email's own switch, which counts only once Together is live."""
    return live() and enabled(name)
