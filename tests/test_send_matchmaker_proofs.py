"""scripts/send_matchmaker_proofs.py (TEC-1845): one proof of each
matchmaker email to the owner's address and each push to the owner's own
device only. A dry run by default; nothing recorded; no switch read or
changed; no live link; no email sent while a title image is missing."""
import os
import re

import pytest

from database import api_tx
from scripts import send_matchmaker_proofs as mp

ORDER = ['mm_alert_several', 'mm_alert_one', 'mm_alert_with_likes', 'mm_visitor_confirm', 'mm_visitor_alert',
         'mm_recommend', 'mm_intro', 'mm_mentor_invite']
_TABLES = ('email_outbox', 'email_send_log', 'match_alert', 'recommendation', 'introduction', 'mentor_link',
           'lead', 'push_send_log')


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
def smtp(monkeypatch, matchmaker_schema, tmp_path):
    """The proof mailer, with every title image present (a scratch copy of
    emails/assets with the 6 matchmaker stems added), so --send goes."""
    import shutil
    import emails.base as base
    from service.matchmaker.mail import TITLES
    assets = tmp_path / 'assets'
    shutil.copytree(base.ASSETS_DIR, assets)
    for stem, _alt, _w in TITLES.values():
        for suffix in ('', '-wht'):
            (assets / f'{stem}{suffix}.png').write_bytes(b'png')
    monkeypatch.setattr(base, 'ASSETS_DIR', assets)
    s = _Smtp()
    monkeypatch.setattr(mp, '_smtp', lambda: s)
    return s


@pytest.fixture
def pushed(monkeypatch):
    sent = []
    monkeypatch.setattr(mp, '_subscriptions', lambda pid: [dict(endpoint=f'https://push.test/{pid}', p256dh='k', auth='a',
                                                                person_id=pid)])
    monkeypatch.setattr(mp, '_push_one', lambda sub, payload: sent.append((sub['person_id'], payload)))
    return sent


def test_the_plan_lists_the_8_emails_in_order():
    assert [e['name'] for e in mp.plan()] == ORDER
    assert all(e['subject'].startswith('[PROOF] ') for e in mp.plan())


def test_every_proof_goes_to_the_owner_only(smtp, monkeypatch):
    for env in list(os.environ):
        if env.startswith('AHAVAH_') and env.endswith('_ENABLED'):
            monkeypatch.delenv(env)
    env_before, before = dict(os.environ), _counts()
    mp.main(['--send'])
    assert {s['to_addr'] for s in smtp.sent} == {'harrigan.tennyson@gmail.com'} and len(smtp.sent) == 8
    assert _counts() == before and dict(os.environ) == env_before


def test_a_dry_run_sends_nothing(smtp, pushed, capsys):
    before = _counts()
    mp.main([])
    assert smtp.sent == [] and pushed == [] and _counts() == before
    assert 'DRY RUN' in capsys.readouterr().out


def test_every_link_in_a_proof_is_inert():
    from service.config import API_BASE_URL, WEB_BASE_URL
    # Plain pages that carry nothing of anyone's may stay.
    plain = {'https://ahavah.app/faq', f'{WEB_BASE_URL}/discover?fits=1', f'{WEB_BASE_URL}/matches?tab=likes',
             f'{WEB_BASE_URL}/auth/sign-up?from=alert'}
    for e in mp.plan():
        hrefs = set(re.findall(r'<a\s[^>]*href="([^"]+)"', e['html']))
        assert hrefs, e['name']
        assert hrefs <= plain | {mp.PROOF_LINK_DISABLED}, (e['name'], hrefs - plain)
        for live in ('/alerts/confirm/', '/alerts/stop/', '/mentor?invite=', '/i/', '/matches?intro=', '/u/'):
            assert f'{WEB_BASE_URL}{live}' not in e['html'] and f'{API_BASE_URL}{live}' not in e['html'], \
                (e['name'], live)


def test_the_pushes_go_to_the_owners_device_only(pushed, capsys):
    before = _counts()
    mp.main(['--push'])
    assert [pid for pid, _ in pushed] == [mp.PUSH_PERSON_ID] * 3
    bodies = [p['body'] for _, p in pushed]
    assert bodies == ['2 new members fit what you are looking for',
                      'Hannah thinks you and Miriam might be a good fit', 'Miriam and Daniel both said yes.']
    assert all(p['title'].startswith('[Proof] ') for _, p in pushed) and _counts() == before


def test_no_switch_is_read(monkeypatch, capsys):
    import service.campaigns.switches as switches

    def refuse(name):
        raise AssertionError(f'read the switch {name}')
    monkeypatch.setattr(switches, 'enabled', refuse)
    assert len(mp.plan()) == 8 and len(mp.pushes()) == 3
    mp.main([])


def test_it_will_not_send_while_a_title_image_is_missing(monkeypatch, tmp_path, capsys):
    import emails.base as base
    from service.matchmaker.mail import TITLES
    s = _Smtp()
    monkeypatch.setattr(mp, '_smtp', lambda: s)
    monkeypatch.setattr(base, 'ASSETS_DIR', tmp_path)
    assert mp.missing_titles() == [stem for stem, _, _ in TITLES.values()]
    with pytest.raises(SystemExit) as e:
        mp.main(['--send'])
    assert e.value.code == 1 and s.sent == []
    assert 'title-alert-fits' in capsys.readouterr().out
