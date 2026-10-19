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
