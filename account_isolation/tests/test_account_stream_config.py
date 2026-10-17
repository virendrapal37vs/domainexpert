import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from utils.account_stream_config import own_groww_config


@pytest.fixture
def lookup(monkeypatch):
    monkeypatch.setenv('VALID_BROKERS', 'groww')
    monkeypatch.setenv('BROKER_API_KEY', 'global-key-must-not-be-used')
    fn = Mock(side_effect=lambda user: {'alice': ('alice-key', 'alice-secret'), 'bob': ('bob-key', 'bob-secret')}.get(user))
    monkeypatch.setitem(sys.modules, 'database.account_broker_db', SimpleNamespace(get_groww_credentials=fn))
    return fn


def record(name='alice', broker='groww', revoked=False):
    return SimpleNamespace(name=name, broker=broker, is_revoked=revoked)


def test_own_credentials_only(lookup):
    assert own_groww_config('alice', record()) == dict(broker_name='groww', api_key='alice-key', api_secret='alice-secret')
    assert own_groww_config('bob', record('bob'))['api_key'] == 'bob-key'


@pytest.mark.parametrize('auth', [None, record('bob'), record(revoked=True), record(broker='angel')])
def test_invalid_auth_no_fallback(lookup, auth):
    assert own_groww_config('alice', auth) is None
    lookup.assert_not_called()


def test_missing_credentials_no_fallback(lookup):
    assert own_groww_config('missing', record('missing')) is None


def test_disabled_broker(lookup, monkeypatch):
    monkeypatch.setenv('VALID_BROKERS', 'angel')
    assert own_groww_config('alice', record()) is None
    lookup.assert_not_called()
