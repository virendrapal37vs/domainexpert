"""Fresh billing enforcement despite API-key, broker and token caches."""
from datetime import datetime
import pytest
from test_razorpay_subscription import gateway_app, make_order, post, signed
from test_paper_dashboard import signed_client


def api_identity(owner, key):
    from database import auth_db as auth
    auth.Base.metadata.create_all(auth.engine)
    auth.db_session.add(auth.Auth(name=owner, broker='groww',
        auth=auth.encrypt_token('synthetic-token'), is_revoked=False))
    auth.db_session.add(auth.ApiKeys(user_id=owner,
        api_key_hash=auth.ph.hash(key + auth.PEPPER), api_key_encrypted='unused'))
    auth.db_session.commit()
    return auth


def test_cached_api_and_proxy_access_expire_and_renew(gateway_app, monkeypatch):
    app, billing, gateway, state = gateway_app
    from utils.proxy_auth_state import proxy_auth_stamp
    auth = api_identity('bob', 'bob-synthetic-key')
    bob = signed_client(app, 'bob')
    key = 'bob-synthetic-key'
    assert auth.verify_api_key(key) is None
    assert auth.get_broker_name(key) is None
    assert auth.get_auth_token_broker(key) == (None, None)
    assert proxy_auth_stamp('bob', 'groww', key) is None
    order = make_order(bob, state)
    assert post(bob, '/subscription/razorpay/verify', signed(order['order_id'])).json['active']
    assert auth.verify_api_key(key) == 'bob'
    assert auth.get_broker_name(key) == 'groww'
    assert auth.get_auth_token_broker(key) == ('synthetic-token', 'groww')
    assert proxy_auth_stamp('bob', 'groww', key)
    until = datetime.fromisoformat(gateway.own_order(order['order_id'])['access_until'])
    monkeypatch.setattr(billing, 'now', lambda: until)
    assert auth.verify_api_key(key) is None
    assert auth.get_broker_name(key) is None
    assert auth.get_auth_token_broker(key) == (None, None)
    assert auth.get_auth_token_broker(key, include_feed_token=True) == (None, None, None)
    assert proxy_auth_stamp('bob', 'groww') is None
    # Expiry is not a bad API key; renewal restores the same valid key.
    with auth.engine.begin() as conn:
        conn.execute(gateway.orders.update().where(gateway.orders.c.username == 'bob')
            .values(access_until=until.replace(year=until.year + 1).isoformat()))
    assert auth.verify_api_key(key) == 'bob'
    assert proxy_auth_stamp('bob', 'groww')


def test_missing_ledger_and_nonstaging_fail_closed(gateway_app, monkeypatch):
    app, billing, gateway, state = gateway_app
    from utils.subscription_access import subscription_access_allowed
    assert not subscription_access_allowed('missing')
    from database.user_db import engine
    billing.payments.drop(engine)
    assert not subscription_access_allowed('bob')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'false')
    assert not subscription_access_allowed('bob')
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'false')
    assert subscription_access_allowed('bob')


def test_expired_proxy_closes_before_legacy_delivery(gateway_app, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from test_proxy_auth_commit import method
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    socket = SimpleNamespace(close=AsyncMock())
    proxy = SimpleNamespace(user_mapping={1: 'bob'}, clients={1: socket})
    authorize = method('_account_authorized', {'aio': asyncio})
    assert asyncio.run(authorize(proxy, 1)) is False
    socket.close.assert_awaited_once_with(code=1008,
        reason='Subscription access expired or unavailable')


def test_private_browser_events_stop_at_subscription_expiry(gateway_app, monkeypatch):
    import threading
    from unittest.mock import Mock
    from utils.account_socket import emit_account
    app, billing, gateway, state = gateway_app
    bob = signed_client(app, 'bob')
    socket = Mock()
    socket._account_connections = {}
    socket._account_connection_lock = threading.RLock()
    emit_account(socket, 'bob', 'order_event', {'id': 'synthetic'})
    socket.emit.assert_not_called()
    order = make_order(bob, state)
    assert post(bob, '/subscription/razorpay/verify', signed(order['order_id'])).json['active']
    emit_account(socket, 'bob', 'order_event', {'id': 'synthetic'})
    socket.emit.assert_called_once()
    socket.reset_mock()
    expiry = datetime.fromisoformat(gateway.own_order(order['order_id'])['access_until'])
    monkeypatch.setattr(billing, 'now', lambda: expiry)
    emit_account(socket, 'bob', 'order_event', {'id': 'synthetic'})
    socket.emit.assert_not_called()
