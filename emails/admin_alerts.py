"""Alerts to the owner alone (TEC-1897; frame G.8, the posts waiting for
approval).

Never to a member. Sent straight through the mailer to OWNER_TO by
service/cron/adminalerts, behind the admin_alerts_cron and stale_post_alert
switches, and proofed first by scripts/send_admin_alert_proofs.py. No member
is named. The heading is bold body text: the shell's display titles are
pre-rendered images and none exists for this line.

There is no report alert here. The report email antiabuse/lodgereport
already sends to DUO_REPORT_EMAIL is the report alert, and the owner's
"Email me when a report arrives" (admin_alert_pref) is its switch.

Copy marked for /copy-pass (ux-writing) and the owner before the switch is
turned on: "1 post is waiting for approval", "N posts are waiting for
approval", "Roundup, week 41, 4 members. In review since 5 Oct.", "Brand
post. In review since 12 Oct.", "Admin alert · 14 Oct, 07:00 Barbados",
"Open the queue", "Sent once a day while a post has waited more than 24
hours."
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from zoneinfo import ZoneInfo

from emails.base import INK, INK_SOFT, SANS, button, chip, render

# The owner's address, the one every proof already goes to
# (scripts/send_proofs.py PROOF_TO; service/admin/owner.py).
OWNER_TO = 'harrigan.tennyson@gmail.com'
ADMIN_URL = 'https://admin.ahavah.app'
# None: the mailer's default sender, as the like and match emails use.
FROM_ADDR = None
BARBADOS = ZoneInfo('America/Barbados')

# The admin's own labels for a post kind (ahavah-admin src/lib/growth-api.ts
# KIND_BADGES), so the email and the queue name a post the same way.
KIND_LABELS = {
    'welcome': 'Welcome',
    'roundup': 'Roundup',
    'member_of_week': 'Member of the week',
    'highlight': 'Highlight',
    'brand': 'Brand post',
}


def _day(at: datetime) -> str:
    b = at.astimezone(BARBADOS)
    return f'{b.day} {b:%b}'


def _stamp(now: datetime) -> str:
    b = now.astimezone(BARBADOS)
    return f'Admin alert · {b.day} {b:%b}, {b:%H:%M} Barbados'


def post_line(post: dict) -> str:
    since = _day(post['in_review_since'])
    if post['kind'] == 'roundup' and post.get('week') is not None:
        n = post.get('members')
        who = '' if n is None else f", {n} {'member' if n == 1 else 'members'}"
        return f"Roundup, week {post['week']}{who}. In review since {since}."
    return f"{KIND_LABELS.get(post['kind'], 'Post')}. In review since {since}."


def _email(now: datetime, heading: str, lines: list[str], label: str, url: str, footer: str) -> str:
    items = ''.join(
        f'<li style="margin:0 0 8px;">{_html.escape(line)}</li>' for line in lines)
    body = f"""
{chip(_html.escape(_stamp(now)))}
<p class="e-text" style="margin:18px 0 12px;font-family:{SANS};font-size:20px;line-height:1.35;font-weight:800;color:{INK};">{_html.escape(heading)}</p>
<ul class="e-text" style="margin:0 0 20px;padding-left:18px;font-family:{SANS};font-size:15px;line-height:1.5;color:{INK_SOFT};">{items}</ul>
{button(label, url)}
"""
    return render(title=heading, preheader=heading, body_html=body, footer_html=_html.escape(footer))


def stale_posts_email(posts: list[dict], now: datetime) -> tuple[str, str]:
    n = len(posts)
    heading = '1 post is waiting for approval' if n == 1 else f'{n} posts are waiting for approval'
    return heading, _email(now, heading, [post_line(p) for p in posts], 'Open the queue',
                           f'{ADMIN_URL}/?tab=growth',
                           'Sent once a day while a post has waited more than 24 hours.')


def preview_stale(to: str) -> tuple[str, str]:
    from datetime import timezone
    now = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)
    posts = [
        dict(kind='roundup', week=41, members=4, in_review_since=datetime(2026, 10, 5, 15, tzinfo=timezone.utc)),
        dict(kind='roundup', week=42, members=2, in_review_since=datetime(2026, 10, 12, 15, tzinfo=timezone.utc)),
    ]
    return stale_posts_email(posts, now)
