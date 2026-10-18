"""Real subscription release bodies, synthetic registry and unsubscribe transport."""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_strategy_account_guard import function

FILE = 'services/flow_executor_service.py'
ENTRY = ('BHEL', 'NSE', 'LTP')


@pytest.fixture
def release(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')
    monkeypatch.setitem(sys.modules,'database.flow_db',SimpleNamespace(
        get_account_workflow=lambda wid, owner: object() if wid == 1 and owner == 'alice' else None))
    send = Mock(return_value=(True, {}, 200))
    monkeypatch.setitem(sys.modules,'services.websocket_service',SimpleNamespace(unsubscribe_from_symbols=send))
    env = {'_workflow_subscriptions_lock': threading.RLock(),
        '_workflow_subscriptions': {1: {ENTRY}, 2: {ENTRY}},
        '_workflow_subscription_versions': {1: {ENTRY:1}, 2:{ENTRY:2}},
        '_workflow_subscription_owners': {1:{ENTRY:('alice','groww')}, 2:{ENTRY:('bob','groww')}},
        'logger': Mock(), '_subscription_owner': Mock(side_effect=AssertionError('No fallback allowed'))}
    for name in ('_forget_released_subscription','_release_shared_workflow_owner','release_workflow_subscriptions'):
        function(FILE,name,env)
    return env, send


@pytest.mark.parametrize('owner',[None,'','bob'])
def test_unverified_owner_cannot_clean_registry(release, owner):
    env, send = release
    with pytest.raises(ValueError):
        env['release_workflow_subscriptions'](1,owner_username=owner)
    send.assert_not_called()
    assert env['_workflow_subscriptions'][1] == {ENTRY}


def test_release_calls_only_correct_account_and_keeps_bob(release):
    env, send = release
    assert env['release_workflow_subscriptions'](1,owner_username='alice') == 1
    send.assert_called_once_with('alice','groww',[{'symbol':'BHEL','exchange':'NSE'}],'LTP')
    assert 1 not in env['_workflow_subscriptions']
    assert env['_workflow_subscriptions'][2] == {ENTRY}


@pytest.mark.parametrize('record',[None,('bob','groww'),('alice','unknown')])
def test_missing_or_conflicting_subscription_owner_retained(release, record):
    env, send = release
    env['_workflow_subscription_owners'][1] = {} if record is None else {ENTRY:record}
    assert env['release_workflow_subscriptions'](1,owner_username='alice') == 0
    send.assert_not_called()
    assert env['_workflow_subscriptions'][1] == {ENTRY}


def test_failed_release_retains_retry_record(release):
    env, send = release
    send.return_value = (False,{},503)
    assert env['release_workflow_subscriptions'](1,owner_username='alice') == 0
    assert env['_workflow_subscriptions'][1] == {ENTRY}


def test_same_owner_workflow_keeps_shared_feed(release):
    env, send = release
    env['_workflow_subscription_owners'][2][ENTRY] = ('alice','groww')
    assert env['release_workflow_subscriptions'](1,owner_username='alice') == 1
    send.assert_not_called()
    assert env['_workflow_subscriptions'][2] == {ENTRY}


def test_unowned_other_workflow_cannot_suppress_account_unsubscribe(release):
    env, send = release
    env['_workflow_subscription_owners'][2] = {}
    assert env['release_workflow_subscriptions'](1,owner_username='alice') == 1
    send.assert_called_once()
