"""Actual subscription handler with synthetic independent broker adapters."""
import asyncio
import json
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from test_proxy_auth_commit import method

KEY = ('BHEL', 'NSE', 1)


@pytest.fixture
def setup():
    alice, bob = Mock(), Mock()
    for adapter in (alice, bob):
        adapter.subscribe.return_value = {'status': 'success'}
    proxy = SimpleNamespace(user_mapping={1: 'alice', 2: 'bob'},
        broker_adapters={'alice': alice, 'bob': bob},
        user_broker_mapping={'alice': 'groww', 'bob': 'groww'},
        subscriptions={}, subscription_index=defaultdict(set),
        send_message=AsyncMock(), send_error=AsyncMock())
    handler = method('subscribe_client', {'json': json,
        'normalize_mode': lambda value: (1, 'LTP')})
    def subscribe(client, **extra):
        asyncio.run(handler(proxy, client, {'symbol': 'BHEL', 'exchange': 'NSE',
                                           'mode': 1, **extra}))
    return proxy, alice, bob, subscribe


def test_same_symbol_subscribes_both_account_adapters(setup):
    p, alice, bob, subscribe = setup
    subscribe(1)
    subscribe(2)
    alice.subscribe.assert_called_once_with('BHEL', 'NSE', 1, 5)
    bob.subscribe.assert_called_once_with('BHEL', 'NSE', 1, 5)
    assert p.subscription_index[KEY] == {1, 2}
    assert len(p.subscriptions[1]) == len(p.subscriptions[2]) == 1


def test_payload_cannot_select_another_owner_or_adapter(setup):
    p, alice, bob, subscribe = setup
    subscribe(1, user_id='bob', username='bob', broker='other', request_id='a-request')
    alice.subscribe.assert_called_once()
    bob.subscribe.assert_not_called()
    assert p.subscription_index[KEY] == {1}
    assert p.send_message.call_args.args[0] == 1
    assert p.send_message.call_args.args[1]['request_id'] == 'a-request'


def test_missing_own_adapter_does_not_fall_back_to_other_account(setup):
    p, alice, bob, subscribe = setup
    del p.broker_adapters['alice']
    subscribe(1)
    bob.subscribe.assert_not_called()
    assert not p.subscriptions
    assert not p.subscription_index
    assert p.send_error.call_args.args[1] == 'BROKER_ERROR'


def test_failed_account_subscription_does_not_change_other_account(setup):
    p, alice, bob, subscribe = setup
    subscribe(2)
    alice.subscribe.return_value = {'status': 'error', 'message': 'synthetic refusal'}
    subscribe(1)
    assert p.subscription_index[KEY] == {2}
    assert 1 not in p.subscriptions
    assert len(p.subscriptions[2]) == 1
    assert p.send_message.call_args.args[1]['status'] == 'partial'


def test_anonymous_cannot_subscribe_with_supplied_owner(setup):
    p, alice, bob, subscribe = setup
    subscribe(3, user_id='alice')
    alice.subscribe.assert_not_called()
    bob.subscribe.assert_not_called()
    assert p.send_error.call_args.args[1] == 'NOT_AUTHENTICATED'
    assert not p.subscription_index
