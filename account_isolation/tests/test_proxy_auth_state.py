import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from test_proxy_auth_commit import method


@pytest.fixture
def auth_rows(main_app):
    auth = importlib.import_module('database.auth_db')
    auth.Base.metadata.create_all(auth.engine)
    for owner, key in [('alice', 'a-key'), ('bob', 'b-key')]:
        auth.db_session.add(auth.Auth(name=owner, broker='groww', auth=auth.encrypt_token(owner + '-token'), is_revoked=False))
        auth.db_session.add(auth.ApiKeys(user_id=owner, api_key_hash=auth.ph.hash(key + auth.PEPPER), api_key_encrypted='not-used'))
    auth.db_session.commit()
    return auth


def test_fresh_key_verified_for_exact_owner(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    stamp = proxy_auth_stamp('alice', 'groww', 'a-key')
    assert stamp and len(stamp) == 64
    assert 'a-key' not in stamp
    assert proxy_auth_stamp('alice', 'groww', 'b-key') is None
    assert proxy_auth_stamp('alice', 'other-broker', 'a-key') is None


def test_revocation_is_owner_scoped(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    bob = proxy_auth_stamp('bob', 'groww')
    auth_rows.Auth.query.filter_by(name='alice').update({'is_revoked': True})
    auth_rows.db_session.commit()
    assert proxy_auth_stamp('alice', 'groww') is None
    assert proxy_auth_stamp('bob', 'groww') == bob


def test_token_rotation_changes_stamp(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    old = proxy_auth_stamp('alice', 'groww')
    auth_rows.Auth.query.filter_by(name='alice').update({'auth': auth_rows.encrypt_token('new-token')})
    auth_rows.db_session.commit()
    assert proxy_auth_stamp('alice', 'groww') != old


def test_same_token_reencryption_keeps_stamp(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    old = proxy_auth_stamp('alice', 'groww')
    auth_rows.Auth.query.filter_by(name='alice').update({'auth': auth_rows.encrypt_token('alice-token')})
    auth_rows.db_session.commit()
    assert proxy_auth_stamp('alice', 'groww') == old


def test_key_rotation_rejects_old_key(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    old = proxy_auth_stamp('alice', 'groww')
    auth_rows.ApiKeys.query.filter_by(user_id='alice').update({'api_key_hash': auth_rows.ph.hash('new-key' + auth_rows.PEPPER)})
    auth_rows.db_session.commit()
    assert proxy_auth_stamp('alice', 'groww', 'a-key') is None
    assert proxy_auth_stamp('alice', 'groww', 'new-key') != old


def test_missing_user_or_key_rejected(auth_rows):
    from utils.proxy_auth_state import proxy_auth_stamp
    assert proxy_auth_stamp('missing', 'groww') is None
    auth_rows.ApiKeys.query.filter_by(user_id='alice').delete()
    auth_rows.db_session.commit()
    assert proxy_auth_stamp('alice', 'groww') is None


def test_protected_delivery_closes_revoked_socket_only(monkeypatch):
    monkeypatch.setitem(sys.modules, 'database.account_broker_db', SimpleNamespace(per_user_groww_enabled=lambda: True))
    monkeypatch.setitem(sys.modules, 'utils.proxy_auth_state', SimpleNamespace(proxy_auth_stamp=lambda owner, broker: 'bob-stamp' if owner == 'bob' else None))
    alice, bob = SimpleNamespace(send=AsyncMock(), close=AsyncMock()), SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    proxy = SimpleNamespace(user_mapping={1: 'alice', 2: 'bob'}, user_broker_mapping={'alice': 'groww', 'bob': 'groww'}, client_auth_stamps={1: 'old', 2: 'bob-stamp'}, clients={1: alice, 2: bob})
    authorize = method('_account_authorized', {'aio': asyncio})
    proxy._account_authorized = lambda client_id: authorize(proxy, client_id)
    import json
    send = method('send_message', {'json': json, 'websockets': SimpleNamespace(exceptions=SimpleNamespace(ConnectionClosed=RuntimeError)), 'logger': Mock()})
    asyncio.run(send(proxy, 1, {'type': 'order_update', 'orderid': 'alice-order'}))
    alice.send.assert_not_called()
    alice.close.assert_called_once()
    asyncio.run(send(proxy, 2, {'type': 'order_update', 'orderid': 'bob-order'}))
    bob.send.assert_called_once()
    bob.close.assert_not_called()


def test_revoked_client_cannot_process_subscription_action():
    import json
    proxy = SimpleNamespace(user_mapping={1: 'alice'}, _account_authorized=AsyncMock(return_value=False), subscribe_client=AsyncMock(), send_error=AsyncMock())
    process = method('process_client_message', {'json': json, 'logger': Mock()})
    asyncio.run(process(proxy, 1, json.dumps({'action': 'subscribe', 'symbols': []})))
    proxy._account_authorized.assert_awaited_once_with(1)
    proxy.subscribe_client.assert_not_called()
