"""Together's emails (TEC-1845).

  answered  "{name} has answered. See how you fit." to whoever finished an
            Us game first (together_answered_email, export 4.10); for a
            couple checklist "{name} has finished the checklist. See where
            you agree." (together_ready_email; owner, 19 Oct 2026). Those are
            the subjects; the body is the title image ("See how you fit." or
            "See where you agree.") over "{name} has answered." or "{name}
            has finished." (Email titles for phones, owner, 19 Oct 2026).
  summary   the checklist summary (emails/marriage_checklist.py, stored
            wording) to a checklist player once they have finished and
            saved (together_summary_email; owner decision 12).
  invite    the link the player who saved sends to the other person
            (together_invite_email; built here, sent by tools_routes).

A player is mailed as a member (person_id, through the outbox, scope
notifications) or, with no account, as the lead their save recorded
(lead_id, through the outbox, only while AHAVAH_TOOL_LEADS_ENABLED is on).
Someone with neither is not mailed: they see the result when they come
back. Each queue runs behind a savepoint, so a mail failure never undoes a
player's finish or save. Names are escaped everywhere: a player chose
them.
"""
from __future__ import annotations

import html
import threading
import traceback
from typing import Callable, Optional

from antiabuse.antispam.signupemail import normalize_email
from emails.base import INK, MUTED, SANS, button, chip, is_suppressed_send, render, title_image
from service.campaigns import campaign_unsubscribed, held, outbox
from service.config import EMAIL_DOMAIN, WEB_BASE_URL
from service.unsubscribe import make_url as unsub_url

CAMPAIGN_ANSWERED = 'together_answered'
CAMPAIGN_READY = 'together_ready'
CAMPAIGN_SUMMARY = 'together_summary'
UNSUB_SCOPE = 'notifications'
FROM_ADDR = f'support@{EMAIL_DOMAIN}'
REPLY_TO = 'support@ahavah.app'

# The invite email (Together follow-ups, section 3). The frame draws its
# heading live in Ultra; display type in email is always a title image, so
# the title is one ("How well do you fit?", "The marriage checklist.") and
# the name moves into the line under it (Email titles for phones, owner,
# 19 Oct 2026). The checklist keeps its own privacy line: it shows each
# person's answers to the other once both finish, so the game's would be
# untrue there.
INVITE = {
    'game': dict(title=('title-together-invite', 'How well do you fit?', 250),
                 overline='How well do we fit?', lead='{name} invited you to play.',
                 preheader='A 2 minute game from Ahavah. Neither of you sees the other’s answers.',
                 line='A 2 minute game from Ahavah for people preparing for marriage. '
                      'No account needed.',
                 privacy='Neither of you sees the other’s answers. You both see the score.',
                 button='Start the game'),
    'checklist': dict(title=('title-checklist-invite', 'The marriage checklist.', 329),
                      overline=None, lead='{name} invited you.',  # no label: it repeated the title (owner, 19 Oct)
                      preheader='Answer on your own, then see where you agree.',
                      line='A free checklist for couples preparing for marriage: Scripture, your '
                           'own hopes and the hard questions.',
                      privacy='Your answers stay private until you have both finished.',
                      button='Start the checklist'),
}
# The answered email's title and the line under it. The subject stays the
# whole sentence.
ANSWERED = {
    'game': (('title-together-answered', 'See how you fit.', 195), '{name} has answered.'),
    'checklist': (('title-checklist-ready', 'See where you agree.', 248), '{name} has finished.'),
}
_PROOF_SESSION = '00000000-0000-0000-0000-000000000000'


def result_url(kind: str, session_uuid: str) -> str:
    path = '/together/game' if kind == 'game' else '/marriage-checklist'
    return f'{WEB_BASE_URL}{path}?session={session_uuid}'


def invite_url(invite_token: str) -> str:
    return f'{WEB_BASE_URL}/tools/i/{invite_token}'


def _title(stem: str, alt: str, width: int) -> str:
    """`width` is the image's natural CSS width (titles.json), so the title
    keeps its size on a phone instead of shrinking to fit."""
    return title_image(f'{stem}.png', f'{stem}-wht.png', alt, width)


def _lead(text: str) -> str:
    """The line under the title that carries the name: body size, bold."""
    return (f'<p class="e-strong" style="margin:0 0 18px;font-family:{SANS};font-size:17px;'
            f'font-weight:700;line-height:1.55;color:{INK};">{text}</p>')


def answered_subject(name: str, kind: str = 'game') -> str:
    if kind == 'checklist':
        return f'{name} has finished the checklist. See where you agree.'
    return f'{name} has answered. See how you fit.'


def answered_html(name: str, cta: str, unsubscribe_url: str, seat: str = 'owner', kind: str = 'game') -> str:
    """`seat` is the recipient's: whoever finished first is mailed, the
    player who invited or the guest they invited, and the footer says which."""
    n = html.escape(name)
    why = (f'You get this because you invited {n} from ahavah.app/together.' if seat == 'owner'
           else f'You get this because {n} invited you from ahavah.app/together.')
    title, lead = ANSWERED['checklist' if kind == 'checklist' else 'game']
    body = _title(*title) + _lead(lead.format(name=n)) + button('See your comparison', cta)
    return render(title=html.escape(answered_subject(name, kind)),
                  preheader=f'{n} has finished the checklist.' if kind == 'checklist' else f'{n} has answered.',
                  body_html=body, footer_html=held.footer(why, unsubscribe_url))


def invite_subject(kind: str) -> str:
    """Fixed: the name is typed by whoever saved, and a subject from our
    domain is not theirs to write. The name is in the body, escaped."""
    return ('You are invited to play Together on Ahavah' if kind == 'game'
            else 'You are invited to the Ahavah marriage checklist')


def invite_html(kind: str, name: str, cta: str) -> str:
    n = html.escape(name)
    m = INVITE['game' if kind == 'game' else 'checklist']
    body = ((chip(m['overline']) if m['overline'] else '') + _title(*m['title']) + _lead(m['lead'].format(name=n))
            + held.para(m['line']) + held.para(m['privacy'], size=15, bottom=26, muted=True)
            + button(m['button'], cta)
            + f'<p class="e-text" style="margin:14px 0 0;font-family:{SANS};font-size:13px;'
              f'line-height:1.55;color:{MUTED};">We have not added you to any list.</p>')
    link = f'color:{MUTED};font-weight:600;text-decoration:underline;'
    footer = ('Ahavah &middot; Matchmaking for Torah-observant believers.<br/>'
              f'You’re receiving this because {n} asked us to send you this invite.'
              '<div style="margin-top:14px;">'
              f'<a href="https://ahavah.app/faq" style="{link}">Help</a>'
              '&nbsp;&nbsp;&middot;&nbsp;&nbsp;'
              f'<a href="https://ahavah.app/privacy" style="{link}">Privacy</a>'
              '&nbsp;&nbsp;&middot;&nbsp;&nbsp;'
              f'<a href="https://ahavah.app/terms" style="{link}">Terms</a>'
              '</div>')
    return render(title=html.escape(invite_subject(kind)), preheader=html.escape(m['preheader']),
                  body_html=body, footer_html=footer)


_Q_SEATS = """
    SELECT s.uuid::text AS uuid, s.kind, s.source, s.owner_email, s.owner_normalized_email,
           s.owner_person_id, s.owner_display,
           p.id, p.seat, p.role, p.email, p.normalized_email, p.person_id, p.display,
           p.finished_at
      FROM tool_session s JOIN tool_player p ON p.session_id = s.id
     WHERE s.id = %(s)s AND s.deleted_at IS NULL
"""
_Q_PERSON = 'SELECT id, email FROM person WHERE id = %(i)s'
_Q_MEMBER_BY_NE = 'SELECT id, email FROM person WHERE normalized_email = %(ne)s LIMIT 1'
_Q_LEAD = 'SELECT id FROM lead WHERE normalized_email = %(ne)s AND source = %(src)s'


def _address(row: dict) -> dict:
    if row['seat'] == 'owner':
        return dict(email=row['owner_email'], normalized_email=row['owner_normalized_email'],
                    person_id=row['owner_person_id'])
    return dict(email=row['email'], normalized_email=row['normalized_email'],
                person_id=row['person_id'])


def _recipient(tx, *, email: Optional[str], normalized_email: Optional[str],
               person_id: Optional[int], source: str) -> Optional[dict]:
    from service.leads import tool_leads_enabled
    row = tx.execute(_Q_PERSON, dict(i=person_id)).fetchone() if person_id is not None else None
    if row is None and normalized_email:
        row = tx.execute(_Q_MEMBER_BY_NE, dict(ne=normalized_email)).fetchone()
    if row is not None:
        return dict(person_id=row['id'], email=row['email'])
    if not email or not normalized_email or not tool_leads_enabled():
        return None
    lead = tx.execute(_Q_LEAD, dict(ne=normalized_email, src=source)).fetchone()
    return dict(lead_id=lead['id'], email=email) if lead else None


def _queue(tx, *, campaign: str, campaign_id: str, to: dict, subject: str,
           html_for: Callable[[str], str]) -> Optional[int]:
    if is_suppressed_send(to['email']):
        return None
    if 'person_id' in to:
        if campaign_unsubscribed(tx, to['person_id'], UNSUB_SCOPE):
            return None
        unsub = unsub_url(UNSUB_SCOPE, to['email'], WEB_BASE_URL)
        return held.queue(tx, campaign=campaign, campaign_id=campaign_id,
                          person_id=to['person_id'], email=to['email'], subject=subject,
                          html=html_for(unsub), from_addr=FROM_ADDR, unsub_scope=UNSUB_SCOPE,
                          unsub_url=unsub)
    from service.leads import lead_unsubscribed
    if lead_unsubscribed(tx, to['lead_id']):
        return None
    unsub = unsub_url('news', to['email'], WEB_BASE_URL)
    return outbox.enqueue_for_lead(tx, campaign=campaign, campaign_id=campaign_id,
                                   lead_id=to['lead_id'], email=to['email'], subject=subject,
                                   html=html_for(unsub), from_addr=FROM_ADDR,
                                   list_unsubscribe=held.list_unsubscribe(unsub), marketing=False)


def _guarded(tx, name: str, fn: Callable[[], Optional[int]]) -> Optional[int]:
    tx.execute(f'SAVEPOINT {name}')
    try:
        out = fn()
    except Exception:
        tx.execute(f'ROLLBACK TO SAVEPOINT {name}')
        print(traceback.format_exc())
        return None
    tx.execute(f'RELEASE SAVEPOINT {name}')
    return out


def queue_answered(tx, session_pk: int, notify_player_id: int) -> Optional[int]:
    """The other player has finished: tell the one who finished first."""
    from service.tools import switch_on
    rows = [dict(r) for r in tx.execute(_Q_SEATS, dict(s=session_pk)).fetchall()]
    me = next((r for r in rows if r['id'] == notify_player_id), None)
    if me is None:
        return None
    other = next((r for r in rows if r['seat'] != me['seat']), None)
    name = (other['owner_display'] if other and other['seat'] == 'owner'
            else other['display'] if other else None)
    game = me['kind'] == 'game'
    if not name or not switch_on('together_answered_email' if game else 'together_ready_email'):
        return None

    def go():
        to = _recipient(tx, source=me['source'], **_address(me))
        if to is None:
            return None
        cta = result_url(me['kind'], me['uuid'])
        return _queue(tx, campaign=CAMPAIGN_ANSWERED if game else CAMPAIGN_READY,
                      campaign_id=me['uuid'], to=to, subject=answered_subject(name, me['kind']),
                      html_for=lambda u: answered_html(name, cta, u, me['seat'], me['kind']))
    return _guarded(tx, 'together_answered', go)


def queue_summary(tx, session_pk: int, player_id: int) -> Optional[int]:
    """A checklist player who has finished and can be reached gets their
    summary, once (the outbox's key: the session and the player)."""
    from service.tools import switch_on
    from service.tools.checklist import to_summary_answers
    from service.tools.sessions import answers_of
    if not switch_on('together_summary_email'):
        return None
    rows = [dict(r) for r in tx.execute(_Q_SEATS, dict(s=session_pk)).fetchall()]
    me = next((r for r in rows if r['id'] == player_id), None)
    if me is None or me['kind'] != 'checklist' or me['finished_at'] is None:
        return None

    def go():
        from emails.marriage_checklist import SUBJECT, checklist_results_html
        to = _recipient(tx, source=me['source'], **_address(me))
        answers = answers_of(tx, player_id)
        if to is None or not answers:
            return None
        body = checklist_results_html(me['role'], to_summary_answers(answers), stored=True)
        return _queue(tx, campaign=CAMPAIGN_SUMMARY, campaign_id=f"{me['uuid']}-{player_id}",
                      to=to, subject=SUBJECT, html_for=lambda _u: body)
    return _guarded(tx, 'together_summary', go)


def after_finish(tx, player: dict, event: Optional[dict]) -> None:
    if player['kind'] == 'checklist':
        queue_summary(tx, player['session_id'], player['player_id'])
    if event:
        queue_answered(tx, player['session_id'], event['notify_player_id'])


def preview_answered(to: str) -> tuple[str, str]:
    return answered_subject('Rivka'), answered_html(
        'Rivka', result_url('game', _PROOF_SESSION), unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL))


def preview_ready(to: str) -> tuple[str, str]:
    return answered_subject('Rivka', 'checklist'), answered_html(
        'Rivka', result_url('checklist', _PROOF_SESSION), unsub_url(UNSUB_SCOPE, to, WEB_BASE_URL),
        kind='checklist')


def preview_invite_game(to: str) -> tuple[str, str]:
    return invite_subject('game'), invite_html('game', 'Rivka', invite_url('proof'))


def preview_invite_checklist(to: str) -> tuple[str, str]:
    return invite_subject('checklist'), invite_html('checklist', 'Rivka', invite_url('proof'))


def preview_summary(to: str) -> tuple[str, str]:
    from emails.marriage_checklist import SUBJECT, checklist_results_html
    sample = [dict(section='biblical', ref='Genesis 2:18-24', importance=5, stance='agree',
                   comment='We leave and cleave, and build our own home.'),
              dict(section='nice-to-have', title='We pray together every evening', importance=5,
                   frequency='daily')]
    return SUBJECT, checklist_results_html('wife', sample, stored=True)


def prepare_invite(tx, player: dict, to_email: str, *, count: bool) -> dict:
    """The invite the player who saved an Us game or a couple checklist
    sends to the other person. `count` adds it to the session's tally
    (Admin > Growth); a refused address is not counted."""
    from service.tools.sessions import TWO_PLAYER, ToolError
    if player['seat'] != 'owner':
        raise ToolError('not_allowed', 403)
    if player['mode'] not in TWO_PLAYER:
        raise ToolError('bad_mode')
    if not player['invite_token'] or not player['owner_display']:
        raise ToolError('not_saved', 409)
    if normalize_email(to_email) == player['owner_normalized_email']:
        raise ToolError('own_address')
    if count:
        tx.execute('UPDATE tool_session SET invite_emails = invite_emails + 1 WHERE id = %(i)s',
                   dict(i=player['session_id']))
    name = player['owner_display']
    return dict(to=to_email, subject=invite_subject(player['kind']),
                html=invite_html(player['kind'], name, invite_url(player['invite_token'])))


def send_invite_later(msg: dict) -> None:
    """Straight to the mailer once the request has committed, as the
    checklist's spouse email is sent: the recipient is neither a member
    nor a lead, so the outbox, which names one, cannot hold it. A
    suppressed address is sent nothing; the caller answers as for a send."""
    if is_suppressed_send(msg['to']):
        return

    def _go():
        try:
            from smtp import aws_smtp
            aws_smtp.send(subject=msg['subject'], body=msg['html'], to_addr=msg['to'],
                          from_addr=FROM_ADDR, reply_to=REPLY_TO)
        except Exception:
            print(traceback.format_exc())
    threading.Thread(target=_go, daemon=True).start()
