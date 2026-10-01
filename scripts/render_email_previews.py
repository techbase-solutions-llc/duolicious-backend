"""Render E3 and E6 to HTML files so the owner can read them before a send.

    PYTHONPATH=/app python3 scripts/render_email_previews.py OUT_DIR

Uses each sender's own build_for, so what is written is what a member would
get, down to the tracked links (minted against the database this runs on;
use the test database). Nothing is sent.
"""
from __future__ import annotations

import sys
from pathlib import Path

from emails.send_notifications_nudge import build_for as build_e6, preview_row as row_e6
from emails.send_reinvite import build_for as build_e3, preview_row as row_e3

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

subject, html = build_e3(dict(row_e3('preview@ahavah-test.invalid'), name='Sarah', total_new=9, gender_label='men'))
(out / 'e3-reinvite.html').write_text(html, encoding='utf-8')
print('e3', subject)

subject, html = build_e6(dict(row_e6('preview@ahavah-test.invalid'), name='Angel'))
(out / 'e6-notifications.html').write_text(html, encoding='utf-8')
print('e6', subject)
