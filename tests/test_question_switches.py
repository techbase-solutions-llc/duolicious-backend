"""The quick-question switches (TEC-1845, spec "Notifications" and "Launch").

Each is off unless its variable is set, and each variable is passed through
to both the api and the cron containers, defaulting to 0: without the
pass-through a switch can never be turned on. tests/test_return_mail_cron.py
already checks that every switch reads as off unless set.
"""
import pathlib

import pytest

from service.campaigns.switches import SWITCHES

NEW = {
    'question_push': 'AHAVAH_QUESTION_PUSH_ENABLED',
    'match_question_push': 'AHAVAH_MATCH_QUESTION_PUSH_ENABLED',
    'e2_question_line': 'AHAVAH_E2_QUESTION_LINE_ENABLED',
    'questions_launch_email': 'AHAVAH_QUESTIONS_LAUNCH_EMAIL_ENABLED',
    'questions_launch_push': 'AHAVAH_QUESTIONS_LAUNCH_PUSH_ENABLED',
}


def test_the_switches_and_their_variables():
    assert {k: SWITCHES.get(k) for k in NEW} == NEW


@pytest.mark.parametrize('env', sorted(NEW.values()))
def test_the_compose_file_passes_each_to_the_api_and_the_cron(env):
    text = pathlib.Path('/app/docker-compose.production.yml').read_text()
    assert text.count(f'{env}: ${{{env}:-0}}') == 2, (
        f'{env} must be passed through in both the api and the cron blocks, defaulting to 0')
