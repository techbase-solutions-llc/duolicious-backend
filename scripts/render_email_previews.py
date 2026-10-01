"""Render every variant the owner is about to send, so they can read each
one first (TEC-1607).

    PYTHONPATH=/app python3 scripts/render_email_previews.py OUT_DIR

Uses each sender's own build_for, so what is written is what a member would
get, down to the tracked links (minted against the database this runs on;
use the test database). The push is a plain HTML card of the exact title
and body. Nothing is sent.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

from emails.send_notifications_nudge import build_for as build_e6, preview_row as row_e6
from emails.send_reinvite import (build_for as build_e3, preview_row as row_e3,
                                  preview_row_unmatched as row_e3_unmatched)
from scripts.push_reactivation import TITLE, body_for

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

subject, page = build_e3(dict(row_e3('preview@ahavah-test.invalid'), name='Sarah', total_new=9, gender_label='men'))
(out / 'e3-reinvite.html').write_text(page, encoding='utf-8')
print('e3 matched', subject)

subject, page = build_e3(dict(row_e3_unmatched('preview@ahavah-test.invalid'), name='Brandon'))
(out / 'e3-reinvite-unmatched.html').write_text(page, encoding='utf-8')
print('e3 unmatched', subject)

subject, page = build_e6(dict(row_e6('preview@ahavah-test.invalid'), name='Angel'))
(out / 'e6-notifications.html').write_text(page, encoding='utf-8')
print('e6', subject)

card = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;padding:40px;background:#ECE9E0;font-family:-apple-system,'Segoe UI',Arial,sans-serif}}
.n{{width:380px;background:#fff;border-radius:18px;padding:16px 18px;box-shadow:0 10px 30px rgba(15,11,31,.18);display:flex;gap:14px}}
.i{{width:40px;height:40px;border-radius:10px;background:#D7FF81;flex:none;display:flex;align-items:center;justify-content:center;font-weight:900;color:#0F0B1F}}
.a{{font-size:12px;color:#6A6580;margin-bottom:2px}}.t{{font-weight:700;font-size:15px;color:#0F0B1F}}.b{{font-size:14px;color:#0F0B1F;margin-top:2px}}
</style></head><body>
<div class="n"><div class="i">A</div><div><div class="a">ahavah.app</div>
<div class="t">{html.escape(TITLE)}</div><div class="b">{html.escape(body_for(7))}</div></div></div>
<p style="font-size:12px;color:#6A6580;max-width:380px">The number is each member's own count. Tapping opens the discover page.</p>
</body></html>"""
(out / 'push-reactivation.html').write_text(card, encoding='utf-8')
print('push', TITLE, '/', body_for(7))
