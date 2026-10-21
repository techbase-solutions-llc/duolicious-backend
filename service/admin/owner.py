"""The owner's own account (TEC-1897, owner's answers of 20 Oct 2026).

Some admin settings are the owner's alone: "Email me when a report arrives"
can be changed only from his account, and other admins see it read-only.
His account is the one signed in with his address, the address every proof
and owner alert goes to (scripts/send_proofs.py PROOF_TO). Three accounts
hold the admin role; no id is written here, so a copied database or a
re-created account cannot make someone else the owner.
"""
from __future__ import annotations

from typing import Optional

OWNER_EMAILS = frozenset({'harrigan.tennyson@gmail.com'})


def is_owner(email: Optional[str]) -> bool:
    return (email or '').strip().lower() in OWNER_EMAILS
