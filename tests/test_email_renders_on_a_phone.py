"""Every Ahavah email fits a phone (docs/superpowers/plans/2026-10-18-email-phone-fit.md).

On 18 Oct 2026 Gmail on Android was rewriting most Ahavah emails ("Revert
auto-sizing") because the shell's card was a fixed 600px table: the text grew
about 1.4 times while the logo, padding and titles stayed put. A button label
that cannot wrap does the same once the shell is fluid. The earlier font fixes
never caught it because every check read source text or a desktop screenshot.

This renders every email in tests/email_samples.py and reads the HTML the
mailer ships. Anything inside an [if mso] comment is for desktop Outlook only
and is not checked; the parser skips comments.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from tests.email_samples import SAMPLES

PHONE = 320  # the narrowest phone we design for, in CSS px

_PX = re.compile(r'(?<![-\w])(min-width|width)\s*:\s*(\d+)px', re.I)


class _Wide(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        style = (a.get('style') or '').replace(' ', '')
        fluid_img = tag == 'img' and 'width:100%' in style
        width_attr = a.get('width')
        if width_attr and width_attr.isdigit() and int(width_attr) > PHONE and not fluid_img:
            self.problems.append(f'<{tag} width="{width_attr}">')
        for prop, px in _PX.findall(style):
            if int(px) > PHONE:
                self.problems.append(f'<{tag} style="{prop}:{px}px">')
        if 'white-space:nowrap' in style.lower() and tag in ('a', 'td', 'div', 'p', 'span'):
            self.problems.append(f'<{tag} white-space:nowrap>')


def _ids():
    return [s['name'] for s in SAMPLES]


def test_every_sample_builds():
    broken = [f"{s['name']}: {s['error']}" for s in SAMPLES if 'error' in s]
    assert not broken, broken
    assert len(SAMPLES) >= 60


@pytest.mark.parametrize('sample', SAMPLES, ids=_ids())
def test_nothing_is_wider_than_a_phone(sample):
    if 'error' in sample:
        pytest.skip('does not build; test_every_sample_builds reports it')
    p = _Wide()
    p.feed(sample['html'])
    assert not p.problems, f"{sample['name']} would make a phone shrink or rewrite it: {sorted(set(p.problems))}"


@pytest.mark.parametrize('sample', [s for s in SAMPLES if 'error' not in s and 'max-width:600px' in s['html']],
                         ids=lambda s: s['name'])
def test_the_shell_stops_text_enlarging(sample):
    # Gmail drops the <style> block, so the setting has to be inline.
    assert re.search(r'<body[^>]*-webkit-text-size-adjust:100%', sample['html']), sample['name']


@pytest.mark.parametrize('sample', [s for s in SAMPLES if 'error' not in s], ids=lambda s: s['name'])
def test_every_email_carries_the_brand_stack(sample):
    # Copies of the stack drifted: staff mail kept an Arial-first one after
    # the 20 Sep fix, and the report email had none, so it showed in Times.
    from emails.base import SANS
    assert SANS in sample['html'], f"{sample['name']} does not use emails.base.SANS"


# Display type belongs in an Ultra title image (title_image()). Typed
# headlines never show in Ultra, and they slipped past the source-text guard
# because their builders live outside the folders it scans (19 Oct 2026).
# This reads the rendered email instead, wherever the builder lives.
_HEADLINE = re.compile(r'<h[1-4]\b|font-size:\s*(2\d|[3-9]\d)px', re.I)

# Waiting for title images (brief 2026-10-19-email-titles-for-phones.md) or
# the owner's waiver. Remove a name when its email gets its title; the last
# test below fails until you do.
_AWAITING_TITLES = {
    'account_deletion_pending', 'marriage_checklist_results',
    'together_answered_game', 'together_ready_checklist', 'together_invite_game',
    'together_invite_checklist', 'together_checklist_summary',
    # older templates baselined in test_email_templates_use_the_brand_shell.py
    'community_invite', 'new_features', 'profile_nudge', 'referral_community',
}
# Large type that is data, not design: the sign-in code changes per email.
_BIG_DATA = {'otp_sign_in'}


def _headline_samples():
    return [s for s in SAMPLES if 'error' not in s and s['audience'] != 'staff'
            and s['name'] not in _BIG_DATA]


@pytest.mark.parametrize('sample', _headline_samples(), ids=lambda s: s['name'])
def test_no_typed_headlines(sample):
    if sample['name'] in _AWAITING_TITLES:
        pytest.skip('waiting for its title image')
    m = _HEADLINE.search(sample['html'])
    assert not m, f"{sample['name']} types a headline ({m.group(0)}); use title_image()"


def test_awaiting_titles_is_current():
    names = {s['name'] for s in SAMPLES}
    unknown = sorted(_AWAITING_TITLES - names)
    assert not unknown, f'not in tests/email_samples.py: {unknown}'
    done = sorted(s['name'] for s in SAMPLES
                  if s['name'] in _AWAITING_TITLES and 'error' not in s and not _HEADLINE.search(s['html']))
    assert not done, f'these have their titles now; remove them from _AWAITING_TITLES: {done}'
