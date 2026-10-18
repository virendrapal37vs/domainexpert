"""Internal envelope and actual proxy loop, with synthetic sockets and no broker."""
import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from test_proxy_auth_commit import method


@pytest.fixture
def ticks(monkeypatch):
    flag = SimpleNamespace(enabled=True)
    monkeypatch.setitem(sys.modules, 'database.account_broker_db', SimpleNamespace(per_user_groww_enabled=lambda: flag.enabled))
    sys.modules.pop('utils.account_market_data', None)
    import importlib
    account_market_data = importlib.import_module("utils.account_market_data")
    return flag, account_market_data


def test_envelope_uses_adapter_owner_and_preserves_payload(ticks):
    _, helper = ticks
    data = {'ltp': 123, 'owner': 'bob'}
    packed = helper.pack_account_tick('alice', data)
    assert helper.unpack_account_tick(packed) == ('alice', data)
    assert data == {'ltp': 123, 'owner': 'bob'}


@pytest.mark.parametrize('payload', [{'ltp': 1}, {'owner': 'alice', 'data': {}},
    {'_domainxpert_account_tick': 1, 'owner': '', 'data': {}},
    {'_domainxpert_account_tick': 1, 'owner': 'alice', 'data': []}])
def test_unowned_or_malformed_tick_dropped(ticks, payload):
    assert ticks[1].unpack_account_tick(payload) == (None, None)


def test_legacy_payload_unchanged(ticks):
    flag, helper = ticks
    flag.enabled = False
    data = {'ltp': 1}
    assert helper.pack_account_tick(None, data) is data
    assert helper.unpack_account_tick(data) == (None, data)


@pytest.mark.parametrize('owner,expected', [('alice', [1]), ('bob', [2]), (None, [])])
def test_real_listener_routes_only_tick_owner_and_skips_shared_cache(ticks, owner, expected):
    helper = ticks[1]
    payload = helper.pack_account_tick(owner, {'ltp': 123}) if owner else {'ltp': 123}
    proxy = SimpleNamespace(running=True, _cleanup_stale_throttle_entries=Mock(),
        _log_stale_adapters=Mock(), last_message_time={}, last_tick_time={},
        subscription_index={('BHEL', 'NSE', 1): {1, 2}}, clients={1: object(), 2: object()},
        user_mapping={1: 'alice', 2: 'bob'}, user_broker_mapping={'alice': 'groww', 'bob': 'groww'},
        send_message=AsyncMock(), _messages_processed=0)
    async def receive():
        proxy.running = False
        return [b'NSE_BHEL_LTP', json.dumps(payload).encode()]
    proxy.socket = SimpleNamespace(recv_multipart=receive)
    cache = Mock(side_effect=AssertionError('Shared cache must not receive account ticks'))
    env = {'aio': asyncio, 'json': json, 'logger': Mock(),
           'time': SimpleNamespace(time=lambda: 1), 'get_market_data_service': cache,
           'normalize_mode_or_none': lambda value: (1, 'LTP')}
    asyncio.run(method('zmq_listener', env)(proxy))
    assert [call.args[0] for call in proxy.send_message.call_args_list] == expected
    cache.assert_not_called()
    for call in proxy.send_message.call_args_list:
        assert call.args[1]['data'] == {'ltp': 123}
