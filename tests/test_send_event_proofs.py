"""scripts/send_event_proofs.py (TEC-1845): one proof of each gathering
email to the owner's address only. A dry run by default; nothing recorded;
no switch read or changed; no live link; no send while a title image is
missing."""
import os
import re

import pytest

from database import api_tx
from scripts import send_event_proofs as ep

ORDER = ['event_confirm', 'event_confirm_online', 'event_reminder', 'event_reminder_online', 'event_change',
         'event_cancelled', 'event_digest', 'event_manage', 'event_approved', 'event_live',
         'event_live_kit', 'event_live_kit_online', 'event_digest_share', 'event_confirm_join', 'event_confirm_online_join', 'event_reminder_join',
         'event_reminder_online_join', 'event_join_invite', 'event_join_invite_online',
         # Release 4's follow-ups: the "Your Ahavah" line (1.6, 1.8) and the
         # refusal of a request to host (8.7).
         'event_your_ahavah_organiser', 'event_your_ahavah_guest', 'event_host_refused']
_TABLES = ('email_outbox', 'email_send_log', 'event_rsvp', 'organiser_link', 'lead')


def _counts():
    with api_tx('read committed') as tx:
        return {t: tx.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n'] for t in _TABLES}


class _Smtp:
    def __init__(self):
        self.sent = []

    def send(self, **kw):
        self.sent.append(kw)
        return 'proof-id'


@pytest.fixture
def smtp(monkeypatch, events_schema):
    s = _Smtp()
    monkeypatch.setattr(ep, '_smtp', lambda: s)
    return s


def test_the_plan_lists_the_22_emails_in_order():
    assert [e['name'] for e in ep.plan()] == ORDER
    assert all(e['subject'].startswith('[PROOF] ') for e in ep.plan())


def test_every_proof_goes_to_the_owner_only(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    ep.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'} and len(smtp.sent) == 22
    assert _counts() == before and dict(os.environ) == env_before


def test_a_dry_run_sends_nothing(smtp, capsys):
    before = _counts()
    ep.main([])
    assert smtp.sent == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_every_link_in_a_proof_is_inert():
    from service.config import API_BASE_URL, WEB_BASE_URL
    # Plain pages that carry nothing of anyone's may stay: Help, the list of
    # gatherings, the sample call link and the sample gathering's public
    # page and share images (the live email's kit, 10.1).
    plain = {'https://ahavah.app/faq', f'{WEB_BASE_URL}/events', 'https://meet.example.com/ahavah-talk'}
    for e in ep.plan():
        hrefs = {h for h in re.findall(r'<a\s[^>]*href="([^"]+)"', e['html'])
                 if not h.startswith(f'{WEB_BASE_URL}/e/')}
        assert hrefs, e['name']
        assert hrefs <= plain | {ep.PROOF_LINK_DISABLED}, (e['name'], hrefs - plain)
        for live in (f'{WEB_BASE_URL}/rsvp/', f'{API_BASE_URL}/rsvp/', '/host/gatherings?t=', '/guests?t=', '/u/'):
            assert live not in e['html'], (e['name'], live)


def test_no_switch_is_read(monkeypatch, capsys):
    import service.campaigns.switches as switches

    def refuse(name):
        raise AssertionError(f'read the switch {name}')
    monkeypatch.setattr(switches, 'enabled', refuse)
    assert len(ep.plan()) == 22
    ep.main([])


def test_it_will_not_send_while_a_title_image_is_missing(smtp, monkeypatch, tmp_path, capsys):
    import emails.base as base
    monkeypatch.setattr(base, 'ASSETS_DIR', tmp_path)
    assert ep.missing_titles() == [stem for stem, _, _ in __import__('service.events.mail', fromlist=['TITLES']).TITLES.values()]
    with pytest.raises(SystemExit) as e:
        ep.main(['--send'])
    assert e.value.code == 1 and smtp.sent == []
    assert 'title-event-confirm' in capsys.readouterr().out


def test_the_title_images_are_all_here_now():
    assert ep.missing_titles() == []


def test_the_join_links_are_inert():
    """A proof click credits nothing (TEC-1845, inviting guests to join)."""
    joins = [e for e in ep.plan() if 'join' in e['name']]
    assert len(joins) == 6
    for e in joins:
        assert '/auth/sign-up' not in e['html'] and 'src=event' not in e['html'], e['name']
        assert ep.PROOF_LINK_DISABLED in e['html'], e['name']


def test_the_your_ahavah_proofs_carry_the_line_with_its_link_inert():
    """Release 4, 1.6 and 1.8: the organiser's and a guest's email with the
    line; /your-ahavah is dark until the light sign-in opens, so the proof
    link is inert too."""
    from service.config import WEB_BASE_URL
    plan = {e['name']: e for e in ep.plan()}
    for name in ('event_your_ahavah_organiser', 'event_your_ahavah_guest'):
        html = plan[name]['html']
        assert 'Everything held under this email is in' in html and ', where you can also delete it.' in html
        assert f'{WEB_BASE_URL}/your-ahavah' not in html, name
    assert 'You are getting this because you host this gathering on Ahavah.' in plan['event_your_ahavah_organiser']['html']
    assert 'You are getting this because you RSVPed to a gathering on Ahavah.' in plan['event_your_ahavah_guest']['html']
    for name, e in plan.items():
        if 'your_ahavah' not in name:
            assert 'where you can also delete it' not in e['html'], name


def test_the_refusal_proof_carries_a_sample_reason():
    e = {e['name']: e for e in ep.plan()}['event_host_refused']
    assert e['subject'] == '[PROOF] Your request to host on Ahavah'
    assert 'We could not approve your request to host on Ahavah.' in e['html']
    assert 'title-note.png' in e['html']
