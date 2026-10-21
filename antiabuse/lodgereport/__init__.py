from database import api_tx
from antiabuse.sql import (
    Q_MAKE_REPORT,
    Q_INSERT_SKIPPED,
)
from datetime import datetime, timezone
from typing import Optional
import os
from service.config import EMAIL_DOMAIN
from smtp import aws_smtp
import traceback
import threading
import html
from emails.base import INK, INK_SOFT, SANS, button, render
import erlastic
import re
from dataclasses import dataclass
import random


@dataclass(frozen=True)
class EmailEntry:
    email: str
    count: int


# The app's report categories (ahavah-web block-report-sheet.tsx) and the
# titles it shows for them. The app sends `<category>` or
# `<category>: <details>`; older clients sent free text.
CATEGORY_TITLES = {
    'inappropriate-photos': 'Inappropriate photos',
    'harassment': 'Harassment or abusive messages',
    'spam-scam': 'Spam or scam',
    'underage': 'Underage user',
    'self-harm': 'Self-harm or suicide content',
    'other': 'Other',
}

# "Other" is not a reason on its own (owner, 21 Oct 2026).
OTHER_MIN_DETAILS = 10
OTHER_TOO_SHORT = 'Write at least 10 characters so we know what happened.'

# The Moderation tab of the admin dashboard. There is no admin base URL in
# service.config, so the host is the production one.
ADMIN_DASHBOARD_URL = 'https://admin.ahavah.app'


def parse_reason(reason: str) -> tuple[Optional[str], str]:
    """(category, details) for a reason the app sent, or (None, the text)
    for free text from an older client."""
    text = (reason or '').strip()
    head, sep, rest = text.partition(':')
    category = head.strip().lower()
    if category in CATEGORY_TITLES:
        return category, rest.strip() if sep else ''
    return None, text


def is_too_thin(reason: str) -> bool:
    """True for an "other" report with fewer than 10 characters of details."""
    category, details = parse_reason(reason)
    return category == 'other' and len(details) < OTHER_MIN_DETAILS


def report_subject(reason: str, is_automoded_bot: bool) -> str:
    category, _ = parse_reason(reason)
    subject = f'New report: {CATEGORY_TITLES[category]}' if category else 'New report'
    return subject + (' [automoded]' if is_automoded_bot else '')


def dashboard_url(reporter_uuid: str, reported_uuid: str) -> str:
    return (f'{ADMIN_DASHBOARD_URL}/?tab=moderation'
            f'&reporter={reporter_uuid}&reported={reported_uuid}')


def message_text(row: dict) -> str:
    """The text of a stored chat message, falling back to its search body
    when the stanza cannot be unpacked."""
    try:
        text = erlastic.decode(row['message'])[3][0][3][0][1]
        return text.decode('utf-8') if isinstance(text, bytes) else str(text)
    except Exception:
        return row.get('search_body') or ''


def first_name(name: Optional[str]) -> str:
    words = (name or '').split()
    return words[0] if words else 'Someone'


def _when(at: Optional[datetime]) -> str:
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f'{at.day} {at:%b %Y, %H:%M} UTC'


def _p(text: str, *, bold: bool = False, colour: str = INK_SOFT, gap: int = 12) -> str:
    weight = 'font-weight:700;' if bold else ''
    return (f'<p class="e-text" style="margin:0 0 {gap}px;font-family:{SANS};font-size:17px;'
            f'line-height:1.55;color:{colour};{weight}">{text}</p>')


def report_template(report: dict, reason: str) -> str:
    """The report email (TEC-1845, 21 Oct 2026): an alert that points to the
    dashboard. No ban links, photo links or messages; moderation is done in
    the dashboard."""
    category, details = parse_reason(reason)
    title = CATEGORY_TITLES[category] if category else 'New report'
    words = details
    count = int(report.get('message_count') or 0)
    reporter = html.escape(first_name(report.get('reporter_name')))
    reported = html.escape(first_name(report.get('reported_name')))

    body = (
        _p(html.escape(title), bold=True, colour=INK, gap=8)
        + (_p(html.escape(words).replace('\n', '<br/>'), gap=20) if words
           else _p('No details given.', gap=20))
        + _p(f'{reporter} (member {int(report["reporter_id"])}) reported '
             f'{reported} (member {int(report["reported_id"])})')
        + _p('From a conversation' if count else 'From their profile')
        + _p(f'{count} message{"" if count == 1 else "s"} between them')
        + _p(html.escape(_when(report.get('reported_at'))), gap=24)
        + button('Open in the dashboard',
                 html.escape(dashboard_url(report['reporter_uuid'], report['reported_uuid'])))
    )
    return render(
        title=html.escape(f'New report: {title}' if category else 'New report'),
        preheader=f'{reporter} reported {reported}.',
        body_html=body,
        footer_html='For Ahavah staff. Moderation is done in the dashboard.',
    )


def parse_email_string(email_string):
    # Regular expression to match an email followed optionally by a number
    pattern = r'(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b)(?:\s+(\d+))?'
    matches = re.findall(pattern, email_string)

    result = []
    for email, count in matches:
        # If no number is given, default to 1
        if count == '':
            count = 1
        else:
            count = int(count)
        result.append(EmailEntry(email, count))

    return result


REPORT_EMAIL = os.environ['DUO_REPORT_EMAIL']
REPORT_EMAILS = parse_email_string(REPORT_EMAIL)
PRIMARY_REPORT_EMAIL = REPORT_EMAILS[0].email
# Sent FROM Ahavah's own sender, as every other email is (21 Oct 2026). It
# used to go From: the report inbox (admin@techbaseltd.com), a domain the
# mailer cannot send for, so reports never arrived.
REPORT_FROM = f'support@{EMAIL_DOMAIN}'
print(REPORT_EMAILS)


def _sample_email_addresses(email_entries):
    # Extract the emails and their respective weights from the list of EmailEntry instances
    emails = [entry.email for entry in email_entries]
    weights = [entry.count for entry in email_entries]

    # Use random.choices() to perform weighted sampling and return a single email
    sampled_email = random.choices(emails, weights=weights, k=1)[0]  # Get the first item from the result

    return sampled_email


def _send_report_email(
    reason: str,
    report: dict,
    is_automoded_bot: bool,
):
    # The owner's "Email me when a report arrives" (TEC-1897). Read here,
    # after the report has committed, so turning it off never loses a report.
    from service.moderation import report_email_on
    if not report_email_on():
        return

    report_email = _sample_email_addresses(REPORT_EMAILS)

    try:
        aws_smtp.send(
            subject=report_subject(reason, is_automoded_bot),
            body=report_template(report=report, reason=reason),
            to_addr=report_email,
            from_addr=REPORT_FROM,
        )
    except:
        print(traceback.format_exc())


def lodge_report(
    subject_uuid: str,
    object_uuid: str,
    reason: str,
    is_automoded_bot: bool
):
    params = dict(
        subject_uuid=subject_uuid,
        object_uuid=object_uuid,
    )

    with api_tx() as tx:
        report = tx.execute(Q_MAKE_REPORT, params=params).fetchone()

    if not report:
        return

    threading.Thread(
        target=_send_report_email,
        kwargs=dict(
            report=dict(report),
            reason=reason,
            is_automoded_bot=is_automoded_bot,
        )
    ).start()


def is_bot_report(reason: str):
    detection_pattern = re.compile(
        r'\b(fake|(cat\s*fish(ing)?)|scam|scammer|bot)\b',
        re.I
    )

    cleaning_pattern = re.compile('[^0-9a-zA-Z]+')

    clean_reason = ' '.join(cleaning_pattern.sub(' ', reason).split())

    return bool(re.search(detection_pattern, clean_reason))


def skip_by_uuid(subject_uuid: str, object_uuid: str, reason: str):
    params = dict(
        subject_uuid=subject_uuid,
        object_uuid=object_uuid,
        reported=bool(reason),
        report_reason=reason or '',
        is_bot_report=is_bot_report(reason),
    )

    with api_tx() as tx:
        tx.execute(Q_INSERT_SKIPPED, params=params)
        row = tx.fetchone()

    if reason:
        lodge_report(
            subject_uuid=subject_uuid,
            object_uuid=object_uuid,
            reason=reason,
            is_automoded_bot=row['is_automoded_bot'],
        )
