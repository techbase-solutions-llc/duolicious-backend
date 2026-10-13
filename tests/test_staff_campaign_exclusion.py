"""Staff accounts and the campaign emails (owner decision, 13 Oct 2026).

The owner's own member account keeps receiving campaign email, so he sees
what members see. The two admin-only accounts never do."""
from service.growth.queries import _excluded


def test_both_admin_only_accounts_are_left_out_of_campaigns():
    ex = _excluded()
    assert 'admin@ahavah.app' in ex
    assert 'admin@techbaseltd.com' in ex


def test_the_owners_member_account_is_not_left_out():
    assert 'harrigan.tennyson@gmail.com' not in _excluded()
