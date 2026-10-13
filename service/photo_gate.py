"""The photo gate's switch (health review, 13 Oct 2026, findings 91 and 99).

A member with no photo of themselves sees no other member's photos while
the gate is on: the queries that hand out other members' photo ids return
none for them, unless it is their own profile or the pair is matched or has
exchanged a message. Admins are never gated. Who counts as able to see is
the SQL function can_view_photos() (migration 0062); the per-pair rule is
photos_visible_to().

The gate stays OFF until the prompt that tells a gated member why ships
(W8 design brief). Turn it on with AHAVAH_PHOTO_GATE_ENABLED=1 (or true,
yes, on) in the API's environment. Read on every request, so a test can
flip it and a restart is all production needs.

Every gated query takes the bind `%(photo_gate)s`; `gate_params()` gives
it. With the switch off each query answers exactly as it did before the
gate existed.
"""
from __future__ import annotations

import os

ENV_NAME = 'AHAVAH_PHOTO_GATE_ENABLED'


def photo_gate_enabled() -> bool:
    return os.environ.get(ENV_NAME, '').strip().lower() in ('1', 'true', 'yes', 'on')


def gate_params() -> dict:
    """The bind every gated query needs, merged into its params."""
    return dict(photo_gate=photo_gate_enabled())
