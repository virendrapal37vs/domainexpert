import importlib
import sys
import pytest


@pytest.fixture
def modes(main_app):
    sys.modules.pop('database.account_mode_db', None)
    module = importlib.import_module('database.account_mode_db')
    module.init_account_mode_db()
    return module


def test_new_accounts_default_analyze(modes):
    assert modes.get_account_analyze_mode('alice') is True
    assert modes.get_account_analyze_mode('bob') is True


def test_users_do_not_change_each_other(modes):
    modes.set_account_analyze_mode('alice', False)
    assert modes.get_account_analyze_mode('alice') is False
    assert modes.get_account_analyze_mode('bob') is True
    modes.set_account_analyze_mode('bob', True)
    assert modes.get_account_analyze_mode('alice') is False
    modes.set_account_analyze_mode('alice', True)
    assert modes.get_account_analyze_mode('alice') is True


@pytest.mark.parametrize('username', [None, '', 'missing'])
def test_requires_existing_owner(modes, username):
    with pytest.raises(ValueError):
        modes.get_account_analyze_mode(username)
    with pytest.raises(ValueError):
        modes.set_account_analyze_mode(username, False)


def test_rejects_non_boolean(modes):
    with pytest.raises(ValueError):
        modes.set_account_analyze_mode('alice', 'false')
    assert modes.get_account_analyze_mode('alice') is True


def test_persists_across_session(modes):
    modes.set_account_analyze_mode('alice', False)
    modes.db_session.remove()
    assert modes.get_account_analyze_mode('alice') is False
