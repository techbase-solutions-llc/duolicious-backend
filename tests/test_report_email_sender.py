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
    report = dict(reporter_id=101, reporter_uuid='3f9a2c1e-7b6d-4e5f-8a9b-0c1d2e3f4a5b',
                  reporter_name='Miriam', reported_id=202,
                  reported_uuid='9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d', reported_name='Samuel',
                  message_count=0, reported_at=None)
    lodgereport._send_report_email(reason='other: asked me for money', report=report, is_automoded_bot=False)
    assert len(sent) == 1
    assert sent[0]['from_addr'] == f'support@{EMAIL_DOMAIN}'
    assert sent[0]['to_addr'] == lodgereport.REPORT_EMAILS[0].email
