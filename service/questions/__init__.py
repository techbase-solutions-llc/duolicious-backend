"""Quick questions, release 1 (TEC-1845).

docs/superpowers/specs/2026-10-13-profile-prompts-design.md (revision of
16 Oct) and docs/superpowers/plans/2026-10-16-quick-questions-release-1.md.

  bank      live questions, one member's answer, the split
  schedule  the weekly drop day and the current question
  member    what one member sees: the card, catch-up, Quick answers on a
            profile, the match question, the E2 line
  copy      push and E2 wording
  pushes    the silent-match, weekly and launch pushes
  admin     Admin > Questions

Dark until launch: while the questions_live switch is off
(AHAVAH_QUESTIONS_LIVE_ENABLED, service/campaigns/switches.py) a member gets
no card, no catch-up, no Quick answers and no match question, and an answer
is refused as closed; no push, E2 line or launch email goes, whichever way
its own switch is set. Admin > Questions and the owner's proofs
(scripts/send_question_proofs.py) work either way.
"""
from service.campaigns.switches import enabled


def live() -> bool:
    """The quick questions are launched: members see them."""
    return enabled('questions_live')


def switch_on(name: str) -> bool:
    """A question send's own switch, which counts only once the questions
    are live. Every question push, the E2 line and the launch email read
    their switch through this."""
    return live() and enabled(name)
