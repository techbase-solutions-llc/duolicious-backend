"""The report email is sent from Ahavah's own sender (owner, 21 Oct 2026).

It went out From: DUO_REPORT_EMAIL (admin@techbaseltd.com), a domain the
mailer cannot send for, so it never reached the inbox and the failure was
only printed by the background thread. Every other Ahavah email comes from
support@<EMAIL_DOMAIN>; this one must too. It still goes TO DUO_REPORT_EMAIL.
"""
import antiabuse.lodgereport as lodgereport
from service.config import EMAIL_DOMAIN


def test_the_report_email_comes_from_the_ahavah_sender(monkeypatch):
    sent = []
    monkeypatch.setattr(lodgereport.aws_smtp, 'send', lambda **kw: sent.append(kw))
    obj = [dict(id=101, token='reporter-token', name='Reporter', photo_links=[]),
           dict(id=202, token='accused-token', name='Accused', photo_links=[])]
    lodgereport._send_report_email(reason='other', report_obj=obj, last_messages=[], is_automoded_bot=False)
    assert len(sent) == 1
    assert sent[0]['from_addr'] == f'support@{EMAIL_DOMAIN}'
    assert sent[0]['to_addr'] == lodgereport.REPORT_EMAILS[0].email
