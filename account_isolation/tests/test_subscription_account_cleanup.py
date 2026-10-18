"""Exercise actual unsubscribe/cleanup bodies with account-specific fake adapters."""
import asyncio
import json
import sys
from collections import defaultdict
from types import SimpleNamespace, MethodType
from unittest.mock import Mock
import pytest
from test_proxy_auth_commit import method

KEY = ('BHEL', 'NSE', 1)
ROW = json.dumps({'symbol': 'BHEL', 'exchange': 'NSE', 'mode': 1})


@pytest.fixture
def proxy(monkeypatch):
    flag = SimpleNamespace(enabled=True)
    monkeypatch.setitem(sys.modules, 'database.account_broker_db',
        SimpleNamespace(per_user_groww_enabled=lambda: flag.enabled))
    alice, bob = Mock(), Mock()
    for adapter in (alice, bob):
        adapter.unsubscribe.return_value = {'status': 'success'}
    p = SimpleNamespace(clients={1: object(), 2: object()}, user_mapping={1: 'alice', 2: 'bob'},
        broker_adapters={'alice': alice, 'bob': bob},
        user_broker_mapping={'alice': 'groww', 'bob': 'groww'},
        subscriptions={1: {ROW}, 2: {ROW}}, subscription_index={KEY: {1, 2}},
        order_subscribers=defaultdict(set, {'alice': {1}, 'bob': {2}}),
        adapter_auth_stamps={'alice': 'a', 'bob': 'b'}, client_auth_stamps={1: 'a', 2: 'b'})
    env = {'aio': asyncio, 'logger': Mock(), 'json': json, 'defaultdict': defaultdict,
           'normalize_mode': lambda value: (1, 'LTP')}
    for name in ('_drop_subscription_ownership', '_purge_client_subscription_ownership',
                 '_indexed_client_subscriptions', '_unsubscribe_owned_subscription', 'cleanup_client'):
        setattr(p, name, MethodType(method(name, env), p))
    return p, flag, alice, bob


def release(p, adapter):
    return p._unsubscribe_owned_subscription(1, adapter, *KEY, stored_rows=[ROW])


def test_other_account_does_not_keep_callers_broker_subscription(proxy):
    p, _, alice, bob = proxy
    assert release(p, alice) == (True, None)
    alice.unsubscribe.assert_called_once_with(*KEY)
    bob.unsubscribe.assert_not_called()
    assert p.subscription_index[KEY] == {2}
    assert p.subscriptions[2] == {ROW}


def test_same_account_second_socket_preserves_shared_subscription(proxy):
    p, _, alice, bob = proxy
    p.user_mapping[3] = 'alice'
    p.clients[3] = object()
    p.subscription_index[KEY].add(3)
    assert release(p, alice) == (True, None)
    alice.unsubscribe.assert_not_called()
    assert p.subscription_index[KEY] == {2, 3}


def test_failed_unsubscribe_keeps_retry_ownership(proxy):
    p, _, alice, bob = proxy
    alice.unsubscribe.return_value = {'status': 'error', 'message': 'retry'}
    assert release(p, alice) == (False, 'retry')
    assert p.subscription_index[KEY] == {1, 2}
    assert p.subscriptions[1] == {ROW}
    bob.unsubscribe.assert_not_called()


def test_wrong_adapter_rejected_without_mutation(proxy):
    p, _, alice, bob = proxy
    assert release(p, bob)[0] is False
    bob.unsubscribe.assert_not_called()
    assert p.subscription_index[KEY] == {1, 2}


def test_disconnect_keeps_other_account_feed_and_adapter(proxy):
    p, _, alice, bob = proxy
    asyncio.run(p.cleanup_client(1))
    alice.unsubscribe.assert_called_once_with(*KEY)
    alice.disconnect.assert_called_once()
    bob.unsubscribe.assert_not_called()
    bob.disconnect.assert_not_called()
    assert p.subscription_index[KEY] == {2}
    assert p.user_mapping == {2: 'bob'}
    assert p.broker_adapters == {'bob': bob}
    assert p.order_subscribers == {'bob': {2}}
    assert p.client_auth_stamps == {2: 'b'}


def test_disconnected_same_account_index_row_does_not_prevent_release(proxy):
    p, _, alice, bob = proxy
    p.user_mapping[3] = 'alice'
    p.subscription_index[KEY].add(3)
    assert release(p, alice) == (True, None)
    alice.unsubscribe.assert_called_once_with(*KEY)


def test_legacy_shared_index_behavior_preserved(proxy):
    p, flag, alice, bob = proxy
    flag.enabled = False
    assert release(p, alice) == (True, None)
    alice.unsubscribe.assert_not_called()
    assert p.subscription_index[KEY] == {2}
