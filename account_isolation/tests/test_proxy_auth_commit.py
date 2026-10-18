"""Real proxy method bodies, fake broker adapters/sockets; no network."""
import ast
import asyncio
import __future__
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from unittest.mock import AsyncMock, Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]


def method(name, env):
    tree = ast.parse((ROOT / 'websocket_proxy/server.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WebSocketProxy')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real-proxy-method>', 'exec', flags=__future__.annotations.compiler_flag), env)
    if name == 'authenticate_client':
        inner = method('_authenticate_client', env)
        async def wrapped(proxy, client_id, data):
            from types import MethodType
            proxy._authenticate_client = MethodType(inner, proxy)
            return await env[name](proxy, client_id, data)
        return wrapped
    return env[name]


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setitem(sys.modules, 'database.account_broker_db', SimpleNamespace(per_user_groww_enabled=lambda: True))
    monkeypatch.setitem(sys.modules, 'utils.proxy_auth_state', SimpleNamespace(proxy_auth_stamp=lambda *args: 'synthetic-stamp'))
    return SimpleNamespace(user_mapping={}, user_broker_mapping={}, broker_adapters={},
                           client_auth_stamps={}, adapter_auth_stamps={},
                           send_error=AsyncMock(), send_message=AsyncMock(),
                           order_subscribers=defaultdict(set), clients={1: object()})


def test_failed_adapter_does_not_authenticate_or_allow_orders(proxy):
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'error', 'message': 'Synthetic init refusal'}
    env = {'aio': asyncio, 'verify_api_key': lambda key: 'alice', 'get_broker_name': lambda key: 'groww',
           'create_broker_adapter': lambda broker: adapter, 'logger': Mock()}
    asyncio.run(method('authenticate_client', env)(proxy, 1, {'api_key': 'fake-key'}))
    assert 1 not in proxy.user_mapping
    assert proxy.send_error.called
    proxy.send_error.reset_mock()
    asyncio.run(method('subscribe_orders_client', {})(proxy, 1, {}))
    assert proxy.send_error.call_args.args[1] == 'NOT_AUTHENTICATED'
    assert not proxy.order_subscribers


def test_success_binds_verified_owner_only_after_connect(proxy):
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'success'}
    def connect():
        assert 1 not in proxy.user_mapping
        return {'status': 'success'}
    adapter.connect.side_effect = connect
    env = {'aio': asyncio, 'verify_api_key': lambda key: 'alice', 'get_broker_name': lambda key: 'groww',
           'create_broker_adapter': lambda broker: adapter, 'logger': Mock()}
    asyncio.run(method('authenticate_client', env)(proxy, 1, {'api_key': 'fake-key', 'user_id': 'bob'}))
    assert proxy.user_mapping[1] == 'alice'
    assert proxy.send_message.call_args.args[1]['user_id'] == 'alice'


def test_authenticated_connection_cannot_switch_owner(proxy):
    proxy.user_mapping[1] = 'alice'
    verify = Mock(side_effect=AssertionError('Do not process a second identity'))
    asyncio.run(method('authenticate_client', {'verify_api_key': verify})(proxy, 1, {'api_key': 'bob-key'}))
    assert proxy.user_mapping[1] == 'alice'
    assert proxy.send_error.call_args.args[1] == 'REAUTHENTICATION_REQUIRES_RECONNECT'
    verify.assert_not_called()


def test_order_update_rechecks_current_client_owner(proxy):
    proxy.clients = {1: object(), 2: object()}
    proxy.user_mapping = {1: 'alice', 2: 'bob'}
    proxy.order_subscribers['alice'].update({1, 2})
    fn = method('_handle_order_update', {'json': json, 'aio': asyncio, 'logger': Mock()})
    asyncio.run(fn(proxy, json.dumps({'type': 'order_update', 'user_id': 'alice', 'orderid': 'alice-order'})))
    assert proxy.send_message.call_count == 1
    assert proxy.send_message.call_args.args[0] == 1


def lifecycle_env(adapter):
    return {'aio': asyncio, 'verify_api_key': lambda key: 'alice',
            'get_broker_name': lambda key: 'groww',
            'create_broker_adapter': lambda broker: adapter, 'logger': Mock()}


def test_failed_initialization_disconnects_created_adapter(proxy):
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'error', 'message': 'refused'}
    adapter.is_auth_error.return_value = False
    asyncio.run(method('authenticate_client', lifecycle_env(adapter))(proxy, 1, {'api_key': 'key'}))
    adapter.disconnect.assert_called_once()
    assert not proxy.broker_adapters
    assert not proxy.user_mapping
    assert not proxy.user_broker_mapping


def test_socket_removed_during_final_check_does_not_bind(proxy, monkeypatch):
    calls = []
    def stamp(*args):
        calls.append(args)
        if len(calls) == 2:
            proxy.clients.pop(1)
        return 'synthetic-stamp'
    monkeypatch.setitem(sys.modules, 'utils.proxy_auth_state', SimpleNamespace(proxy_auth_stamp=stamp))
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'success'}
    adapter.connect.return_value = {'status': 'success'}
    asyncio.run(method('authenticate_client', lifecycle_env(adapter))(proxy, 1, {'api_key': 'key'}))
    assert not proxy.user_mapping
    assert not proxy.client_auth_stamps
    assert not proxy.broker_adapters
    adapter.disconnect.assert_called_once()
    proxy.send_message.assert_not_called()


def test_changed_credentials_release_uncommitted_adapter(proxy, monkeypatch):
    stamps = iter(['before', 'after'])
    monkeypatch.setitem(sys.modules, 'utils.proxy_auth_state', SimpleNamespace(proxy_auth_stamp=lambda *args: next(stamps)))
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'success'}
    adapter.connect.return_value = {'status': 'success'}
    asyncio.run(method('authenticate_client', lifecycle_env(adapter))(proxy, 1, {'api_key': 'key'}))
    assert not proxy.user_mapping
    assert not proxy.broker_adapters
    adapter.disconnect.assert_called_once()


def test_successful_setup_keeps_adapter(proxy):
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'success'}
    adapter.connect.return_value = {'status': 'success'}
    asyncio.run(method('authenticate_client', lifecycle_env(adapter))(proxy, 1, {'api_key': 'key'}))
    assert proxy.broker_adapters['alice'] is adapter
    adapter.disconnect.assert_not_called()


def test_other_socket_adopting_adapter_prevents_disconnect(proxy, monkeypatch):
    calls = []
    def stamp(*args):
        calls.append(args)
        if len(calls) == 2:
            proxy.clients.pop(1)
            proxy.clients[2] = object()
            proxy.user_mapping[2] = 'alice'
        return 'synthetic-stamp'
    monkeypatch.setitem(sys.modules, 'utils.proxy_auth_state', SimpleNamespace(proxy_auth_stamp=stamp))
    adapter = Mock()
    adapter.initialize.return_value = {'status': 'success'}
    adapter.connect.return_value = {'status': 'success'}
    asyncio.run(method('authenticate_client', lifecycle_env(adapter))(proxy, 1, {'api_key': 'key'}))
    assert 1 not in proxy.user_mapping
    assert proxy.broker_adapters['alice'] is adapter
    adapter.disconnect.assert_not_called()
