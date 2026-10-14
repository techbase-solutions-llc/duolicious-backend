"""E1 and E4 say what the web lane's Spotlight copy says (findings 79 and
82): the card shows the main profile photo, first name, age and country,
and nothing else; nothing is posted until the member approves that exact
card. Held behind AHAVAH_SPOTLIGHT_COPY_ENABLED, which defaults to the old
copy because E4 is live. Both referral emails call a Boost a 30-minute
boost on Discover (decision 89)."""
import pytest

from emails.referral_community import referral_community_html
from emails.referral_intro import referral_intro_html
from emails.spotlight_announcement import spotlight_announcement_html
from emails.spotlight_card_ready import card_ready_html

ENV = 'AHAVAH_SPOTLIGHT_COPY_ENABLED'


def _e1():
    return spotlight_announcement_html('https://ahavah.app/s/c', 'https://ahavah.app/s/p', 'https://ahavah.app/u/x')


def _e4():
    return card_ready_html('Miriam', 'member of the week', 'https://ahavah.app/spotlight/card/t', 7,
                           'https://ahavah.app/u/x')


def test_off_e1_and_e4_keep_the_live_copy(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert 'one photo you choose' in _e1()
    assert 'choose the photo you prefer' in _e4()


@pytest.mark.parametrize('render', [_e1, _e4])
def test_on_both_say_main_profile_photo_and_that_exact_card(monkeypatch, render):
    monkeypatch.setenv(ENV, '1')
    html = render()
    assert 'main profile photo, first name, age and country, and nothing else' in html
    assert 'until you approve that exact card' in html
    assert 'photo you choose' not in html and 'choose the photo' not in html
    assert chr(0x2014) not in html


def test_on_e1_says_why_and_drops_the_serial_comma(monkeypatch):
    monkeypatch.setenv(ENV, '1')
    html = _e1()
    assert 'believers who have not heard of Ahavah see real people here' in html
    assert 'member of the week, and the occasional' not in html


def test_e4_queued_for_a_member_follows_the_switch(monkeypatch):
    import emails.spotlight_card_ready as e4
    monkeypatch.setenv(ENV, '1')
    assert 'main profile photo' in _e4()
    monkeypatch.setenv(ENV, '0')
    assert 'main profile photo' not in _e4()
    assert e4.preheader() == 'Review your card, choose your photo, and approve or skip.'


def test_both_referral_emails_call_a_boost_a_boost():
    for html in (referral_intro_html('a@ahavah-test.invalid', 'CODE1'),
                 referral_intro_html('a@ahavah-test.invalid', 'CODE1', member=True),
                 referral_community_html('a@ahavah-test.invalid', 'CODE1')):
        assert 'a 30-minute boost on Discover' in html
        assert '30-minute spotlight' not in html
