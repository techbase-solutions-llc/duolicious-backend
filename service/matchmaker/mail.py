"""Every matchmaker email and push (TEC-1845), on the brand shell, through
the durable outbox.

  members     mm_alert            new members who fit (4.1, 4.2), with the
                                  likes block when both are due (4.3)
              mm_intro            an introduction, to each of the two (5.2)
  visitors    mm_visitor_confirm  turn on your alert (4.4)
              mm_visitor_alert    someone who fits joined, weekly (4.5)
  others      mm_recommend        a recommendation, to the single (5.1)
              mm_mentor_invite    the mentor's invitation (6.1)

Each is behind its own switch and matchmaker_live (service.matchmaker.
CAMPAIGN_SWITCHES), read before queueing and again by the drain. Display
type is a title image, never a typed headline (TITLES); the export's
headings that carry a name or a count become the first body line under it
(plan item 25). Every name and note is escaped.

Recipients: a member is queued as the member (scope notifications), a
visitor as their alert:visitor lead. A recommended single and a mentor are
neither: their rows name recommendation_id or mentor_link_id (migration
0073), exempt, with no List-Unsubscribe, since each is sent once.

Pushes go after the deciding transaction commits (push_after_commit): from
a cron job through held.after_commit, from a request through the
collect_pushes() block the route wraps around its transaction.

Lines marked NEW LINE are not in the export; they wait for /copy-pass and
the owner (plan item 21).
"""
from __future__ import annotations

import contextvars
import html
import traceback
from contextlib import contextmanager
from typing import Callable, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from emails.base import INK, MUTED, SANS, button, chip, render, title_image
from service.campaigns import held
from service.config import EMAIL_DOMAIN, WEB_BASE_URL

CAMPAIGN_ALERT = 'mm_alert'
CAMPAIGN_VISITOR_CONFIRM = 'mm_visitor_confirm'
CAMPAIGN_VISITOR_ALERT = 'mm_visitor_alert'
CAMPAIGN_RECOMMEND = 'mm_recommend'
CAMPAIGN_INTRO = 'mm_intro'
CAMPAIGN_MENTOR_INVITE = 'mm_mentor_invite'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = f'support@{EMAIL_DOMAIN}'

# stem, alt, natural CSS width (ahavah-web scripts/render-email-titles.mjs,
# measured 20 Oct). Line breaks: "New people / who fit.", "Turn on / your
# alert.", "Someone who / fits joined.", "Someone / thought / of you.",
# "An / introduction." and "Be a mentor / on Ahavah.". Every alt but
# visitor_confirm's is a NEW LINE.
TITLES: dict[str, tuple[str, str, int]] = {
    'alert': ('title-alert-fits', 'New people who fit.', 274),
    'visitor_confirm': ('title-alert-confirm', 'Turn on your alert.', 252),
    'visitor_alert': ('title-alert-joined', 'Someone who fits joined.', 329),
    'recommend': ('title-recommend', 'Someone thought of you.', 218),
    'intro': ('title-introduction', 'An introduction.', 319),
    'mentor_invite': ('title-mentor-invite', 'Be a mentor on Ahavah.', 289),
}

ABOUT_AHAVAH = 'Ahavah is matchmaking for Torah-observant believers who hope to marry.'


# ---------------------------------------------------------------------------
# Links: every one a web page that acts by a script call, never the API, so
# a mail scanner opening a link confirms or accepts nothing.
# ---------------------------------------------------------------------------

def confirm_url(token: str) -> str:
    return f'{WEB_BASE_URL}/alerts/confirm/{token}'


def stop_url(token: str) -> str:
    return f'{WEB_BASE_URL}/alerts/stop/{token}'


def mentor_accept_url(token: str) -> str:
    return f'{WEB_BASE_URL}/mentor?invite={token}'


def intro_url(intro_id: int) -> str:
    return f'{WEB_BASE_URL}/matches?intro={intro_id}'


def see_who_joined_url() -> str:
    return f'{WEB_BASE_URL}/discover?fits=1'


def join_url() -> str:
    return f'{WEB_BASE_URL}/auth/sign-up?from=alert'


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------

def _e(text: object) -> str:
    return html.escape('' if text is None else str(text))


def _title(key: str) -> str:
    stem, alt, width = TITLES[key]
    return title_image(f'{stem}.png', f'{stem}-wht.png', alt, width)


def _lead(text: str) -> str:
    """The line under the title that carries a name or a count: body size, bold."""
    return (f'<p class="e-strong" style="margin:0 0 18px;font-family:{SANS};font-size:17px;'
            f'font-weight:700;line-height:1.55;color:{INK};">{text}</p>')


def _link(label: str, href: str) -> str:
    return (f'<p style="margin:0 0 18px;font-family:{SANS};font-size:16px;line-height:1.5;">'
            f'<a href="{_e(href)}" style="color:{INK};font-weight:700;text-decoration:underline;">{label}</a></p>')


def _after_button(text: str, size: int = 15) -> str:
    return (f'<p class="e-text" style="margin:14px 0 0;font-family:{SANS};font-size:{size}px;'
            f'line-height:1.55;color:{MUTED};">{text}</p>')


def _gap() -> str:
    return '<div style="height:18px;line-height:18px;">&nbsp;</div>'


def _note_panel(note: str, signed: str) -> str:
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 22px;">
      <tr><td class="e-callout" bgcolor="#F4F2EC" style="padding:14px 16px;background:#F4F2EC;border-radius:12px;font-family:{SANS};color:{INK};">
        <p class="e-text" style="margin:0 0 6px;font-family:{SANS};font-size:15px;font-weight:500;line-height:1.5;color:{INK};">“{_e(note)}”</p>
        <p class="e-text" style="margin:0;font-family:{SANS};font-size:13px;font-weight:500;line-height:1.5;color:{MUTED};">{_e(signed)}</p>
      </td></tr>
    </table>"""


def _footer(reason: str, link_label: Optional[str] = None, link_url: Optional[str] = None, *,
            your_ahavah: bool = False) -> str:
    """With `your_ahavah`, the "Your Ahavah" line under the reason (release
    4, frame 1.7, the mentor's; emails/your_ahavah_line.py)."""
    from emails import your_ahavah_line
    style = f'color:{MUTED};font-weight:600;text-decoration:underline;'
    first = (f'<a href="{_e(link_url)}" style="{style}">{link_label}</a>'
             '&nbsp;&nbsp;&middot;&nbsp;&nbsp;') if link_label and link_url else ''
    return ('Ahavah &middot; Matchmaking for Torah-observant believers.<br/>'
            f'{reason}'
            + (your_ahavah_line.block() if your_ahavah else '')
            + f'<div style="margin-top:14px;">{first}'
            f'<a href="https://ahavah.app/faq" style="{style}">Help</a></div>')


def _shell(subject: str, preheader: str, body: str, footer: str) -> str:
    return render(title=_e(subject), preheader=preheader, body_html=body, footer_html=footer)


def _greeting(first_name: Optional[str]) -> str:
    return held.para(f'Hello {_e(first_name)}.') if first_name else ''  # NEW LINE


# ---------------------------------------------------------------------------
# The words that carry a count
# ---------------------------------------------------------------------------

def fits_line(n: int) -> str:
    """1.11, 1.12, 4.1 and 4.2."""
    if n == 1:
        return '1 new member fits what you are looking for'
    return f'{n} new members fit what you are looking for'


def likes_line(n: int) -> str:
    """4.3; the singular is a NEW LINE."""
    if n == 1:
        return '1 person is also waiting for your answer'  # NEW LINE
    return f'{n} people are also waiting for your answer'


def visitor_count_line(n: int) -> str:
    """4.5; the plural is a NEW LINE."""
    tail = 'Join to see who, and we will carry over what you are looking for.'
    if n == 1:
        return f'1 new member this week. {tail}'
    return f'{n} new members this week. {tail}'  # NEW LINE


# ---------------------------------------------------------------------------
# The builders, each -> (subject, html)
# ---------------------------------------------------------------------------

def alert_email(n: int, cta_url: str, stop: str, *, likes: int = 0) -> tuple[str, str]:
    """4.1 and 4.2; with `likes`, the 4.3 block, one email for both."""
    subject = fits_line(n)
    body = (chip('This week' if likes else 'New members') + _title('alert') + _lead(_e(subject))
            + held.para('We never name anyone in an email. Open Ahavah to see them.')
            + button('See who joined', cta_url))
    if likes:
        body += (_gap() + held.para(f'<b>{_e(likes_line(likes))}</b>', bottom=8)
                 + _link('See who liked you', f'{WEB_BASE_URL}/matches?tab=likes'))
        reason = 'One email for both, at most once a day. Change it in Settings, under Notifications.'
    else:
        reason = 'You set this alert in Ahavah. Change it in Settings, under Notifications.'
    return subject, _shell(subject, _e(subject), body, _footer(reason, 'Stop these emails', stop))


def visitor_confirm_email(words: str, confirm: str, first_name: Optional[str]) -> tuple[str, str]:
    """4.4."""
    subject = 'Turn on your Ahavah alert'  # NEW LINE
    line = f'You asked us to email you when someone who fits joins Ahavah: {_e(words)}.'
    body = (chip('Your alert') + _title('visitor_confirm') + _greeting(first_name)
            + held.para(line) + button('Turn on my alert', confirm))
    return subject, _shell(subject, line, body, _footer(
        'If this was not you, ignore this email and we will not send anything else.'))


def visitor_alert_email(n: int, first_name: Optional[str], stop: str) -> tuple[str, str]:
    """4.5: its heading is the subject; the title is the shorter line."""
    subject = 'Someone who fits what you are looking for joined Ahavah'
    line = visitor_count_line(n)
    body = (chip('Your alert') + _title('visitor_alert') + _greeting(first_name)
            + _lead(_e(line)) + button('Join to see them', join_url())
            + _after_button(ABOUT_AHAVAH))
    return subject, _shell(subject, _e(line), body, _footer(
        'You asked us to tell you when someone who fits joins.', 'Stop these emails', stop))


def recommend_email(sender: str, note: str, cta_url: str) -> tuple[str, str]:
    """5.1."""
    who = _e(sender)
    subject = f'{sender} thinks Ahavah could be right for you'
    body = (_title('recommend') + _lead(f'{who} thinks Ahavah could be right for you.')
            + _note_panel(note, sender) + held.para(ABOUT_AHAVAH)
            + button('Have a look', cta_url))
    return subject, _shell(subject, _e(subject), body, _footer(
        f'{who} gave us your email to send this once. We have not shared anything about you, '
        'and we will not email you again unless you join.'))


def intro_email(introducer: str, other: str, cta_url: str, unsub_url: str) -> tuple[str, str]:
    """5.2. The note is never in the email: it waits in the app."""
    i, o = _e(introducer), _e(other)
    subject = f'{introducer} thinks you and {other} might be a good fit'
    body = (chip('Introduction') + _title('intro') + _lead(f'{i} thinks you and {o} might be a good fit.')
            + held.para(f'Open Ahavah to see {o} and {i}’s note, then decide privately. '
                        'Nobody is told if you say no.')
            + button('See the introduction', cta_url))
    return subject, _shell(subject, _e(subject), body, _footer(
        'You get introduction emails because you are a member of Ahavah. '
        'Change this in Settings, under Notifications.', 'Unsubscribe', unsub_url))


Pronoun = Literal['she', 'he', 'they']


def pronoun_for(gender_name: Optional[str]) -> Pronoun:
    return {'Woman': 'she', 'Man': 'he'}.get(gender_name or '', 'they')  # type: ignore[return-value]


def mentor_invite_email(single: str, pronoun: Pronoun, accept_url: str, *,
                        your_ahavah: bool = False) -> tuple[str, str]:
    """6.1."""
    s = _e(single)
    sees, chooses = ('see', 'choose') if pronoun == 'they' else ('sees', 'chooses')
    subject = f'{single} invited you to be a mentor on Ahavah'
    body = (chip('Mentor invitation') + _title('mentor_invite')
            + _lead(f'{s} invited you to be a mentor on Ahavah.')
            + held.para(f'As a mentor you see {s}’s matches as {pronoun} {sees} them, and only the '
                        f'conversations {pronoun} {chooses} to share, read only. You never see anyone else.')
            + button('Accept and sign in', accept_url)
            + _after_button(f'{s} can end this at any time.'))
    return subject, _shell(subject, _e(subject), body, _footer(
        f'If you do not know {s}, ignore this email and nothing will happen.', your_ahavah=your_ahavah))


# ---------------------------------------------------------------------------
# Pushes, each -> dict(title, body, url, tag)
# ---------------------------------------------------------------------------
# Each push's link carries its own ?src=, which the web app posts to
# POST /push-taps on landing, as the question pushes' qpush, mpush and
# lpush (plan 2026-10-22, fix 11). duotypes.PostPushTap accepts them.

ALERT_SRC = 'mmalert'
INTRO_SRC = 'mmintro'
TOLD_SRC = 'mmtold'


def with_src(url: str, src: str) -> str:
    """`url` with ?src=`src`, joined to any query it already has."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + [('src', src)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def without_src(url: str) -> str:
    """`url` with no ?src=, for a proof push whose tap must count as nothing."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != 'src']
    return urlunsplit(parts._replace(query=urlencode(query)))


def alert_push(n: int) -> dict:
    """1.11 and 1.12."""
    return dict(title='Ahavah', body=fits_line(n), url=with_src('/discover?fits=1', ALERT_SRC), tag='mm-alert')


def intro_push(intro_id: int, introducer: str, other: str) -> dict:
    """The 5c heading."""
    return dict(title='Ahavah', body=f'{introducer} thinks you and {other} might be a good fit',
                url=with_src(f'/matches?intro={intro_id}', INTRO_SRC), tag=f'mm-intro-{intro_id}')


def introducer_push(intro_id: int, a: str, b: str) -> dict:
    """5c.8."""
    return dict(title='Ahavah', body=f'{a} and {b} both said yes.', url=with_src('/matches', TOLD_SRC),
                tag=f'mm-told-{intro_id}')


# A request's pushes, sent once its transaction has committed (see
# collect_pushes). None outside such a block: a cron job's go through
# held.after_commit, which the returnmail cron runs after each job commits.
_PENDING: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar('mm_pushes', default=None)


def _send_push(person_id: int, push: dict, event_kind: Optional[str]) -> None:
    from service.notifications import send_to_user_safe
    send_to_user_safe(person_id, push['title'], push['body'], push['url'], push['tag'],
                      event_kind=event_kind)  # type: ignore[arg-type]


def push_after_commit(person_id: int, push: dict, switch: str,
                      event_kind: Optional[str] = None) -> None:
    """Send `push` to the member once the caller's transaction commits,
    while `switch` (and matchmaker_live) is on. `event_kind` makes the send
    honour the member's own push setting for that kind (an introduction
    follows Matches)."""
    from service.matchmaker import switch_on
    if not switch_on(switch):
        return
    after_commit(lambda: _send_push(person_id, push, event_kind))


def after_commit(fn) -> None:
    """Run fn once the caller's transaction has committed: inside a
    collect_pushes() block at its end, otherwise through held.after_commit
    (the returnmail cron runs those after each job)."""
    pending = _PENDING.get()
    if pending is not None:
        pending.append(fn)
    else:
        held.after_commit(fn)


@contextmanager
def collect_pushes():
    """Wrap a request's transaction: the pushes it decides go only after it
    has committed, and none goes if it raises."""
    pending: list = []
    token = _PENDING.set(pending)
    try:
        yield
    except BaseException:
        pending.clear()
        raise
    finally:
        _PENDING.reset(token)
    for send in pending:
        try:
            send()
        except Exception:
            print(traceback.format_exc())


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

def campaign_on(campaign: str) -> bool:
    from service.matchmaker import CAMPAIGN_SWITCHES, switch_on
    return switch_on(CAMPAIGN_SWITCHES[campaign])


def guarded(tx, name: str, fn: Callable[[], Optional[int]]) -> Optional[int]:
    """Run fn behind a savepoint: a mail failure never undoes the caller."""
    tx.execute(f'SAVEPOINT {name}')
    try:
        out = fn()
    except Exception:
        tx.execute(f'ROLLBACK TO SAVEPOINT {name}')
        print(traceback.format_exc())
        return None
    tx.execute(f'RELEASE SAVEPOINT {name}')
    return out


def queue_member(tx, *, campaign: str, campaign_id: str, person_id: int, subject: str,
                 html_: str) -> Optional[int]:
    """A member's matchmaker email (scope notifications), or None when it
    is switched off, suppressed or already queued."""
    from emails.base import is_suppressed_send
    from service.unsubscribe import make_url
    if not campaign_on(campaign):
        return None
    row = tx.execute('SELECT email FROM person WHERE id = %(i)s', dict(i=person_id)).fetchone()
    if row is None or is_suppressed_send(row['email']):
        return None
    unsub = make_url(UNSUB_SCOPE, row['email'], WEB_BASE_URL)
    return held.queue(tx, campaign=campaign, campaign_id=campaign_id, person_id=person_id,
                      email=row['email'], subject=subject, html=html_, from_addr=FROM_ADDR,
                      unsub_scope=UNSUB_SCOPE, unsub_url=unsub)


def notifications_unsub_url(email: str) -> str:
    from service.unsubscribe import make_url
    return make_url(UNSUB_SCOPE, email, WEB_BASE_URL)


# ---------------------------------------------------------------------------
# Proof previews: sample data only (Hannah, Miriam, Rivka; 2 members; 5 likes)
# ---------------------------------------------------------------------------

_SAMPLE_TOKEN = 'proof-token-not-real-000000000000'


def preview_alert_several(to: str) -> tuple[str, str]:
    return alert_email(2, see_who_joined_url(), stop_url(_SAMPLE_TOKEN))


def preview_alert_one(to: str) -> tuple[str, str]:
    return alert_email(1, see_who_joined_url(), stop_url(_SAMPLE_TOKEN))


def preview_alert_with_likes(to: str) -> tuple[str, str]:
    return alert_email(2, see_who_joined_url(), stop_url(_SAMPLE_TOKEN), likes=5)


def preview_visitor_confirm(to: str) -> tuple[str, str]:
    return visitor_confirm_email('a man aged 26 to 34 in North America', confirm_url(_SAMPLE_TOKEN),
                                 'Hannah')


def preview_visitor_alert(to: str) -> tuple[str, str]:
    return visitor_alert_email(1, 'Hannah', stop_url(_SAMPLE_TOKEN))


def preview_recommend(to: str) -> tuple[str, str]:
    return recommend_email('Hannah', 'I think you would be a good fit for Ahavah.',
                           f'{WEB_BASE_URL}/i/HANNAH7K')


def preview_intro(to: str) -> tuple[str, str]:
    return intro_email('Hannah', 'Miriam', intro_url(1), notifications_unsub_url(to))


def preview_mentor_invite(to: str) -> tuple[str, str]:
    return mentor_invite_email('Rivka', 'she', mentor_accept_url(_SAMPLE_TOKEN))


def preview_mentor_invite_your_ahavah(to: str) -> tuple[str, str]:
    """Release 4, 1.7: the invitation with the "Your Ahavah" line."""
    return mentor_invite_email('Rivka', 'she', mentor_accept_url(_SAMPLE_TOKEN), your_ahavah=True)
