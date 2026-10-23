"""No broker calls: expiry checks for cached tokens and background dispatch."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import importlib
import pytest
from test_razorpay_subscription import gateway_app, make_order, post, signed
from test_paper_dashboard import signed_client
from test_subscription_api_access import api_identity
from test_flow_execution_owner import owned
from test_flow_owner_storage import flows


def test_cached_and_fresh_background_tokens_stop_at_expiry(gateway_app, monkeypatch):
    app, billing, gateway, state = gateway_app
    auth = api_identity('bob', 'background-key')
    bob = signed_client(app, 'bob')
    assert auth.get_auth_token('bob') is None
    assert auth.get_auth_token_fresh('bob') is None
    order = make_order(bob, state)
    assert post(bob, '/subscription/razorpay/verify', signed(order['order_id'])).json['active']
    assert auth.get_auth_token('bob') == 'synthetic-token'
    assert auth.get_auth_token_fresh('bob') == 'synthetic-token'
    expiry = datetime.fromisoformat(gateway.own_order(order['order_id'])['access_until'])
    monkeypatch.setattr(billing, 'now', lambda: expiry)
    assert auth.get_auth_token('bob') is None
    assert auth.get_auth_token('bob', bypass_cache=True) is None
    assert auth.get_auth_token_fresh('bob') is None


@pytest.mark.parametrize('expired', [False, True])
def test_unpaid_pending_order_stops_before_claim_or_credentials(gateway_app, monkeypatch, expired):
    if expired:
        from database.user_db import engine
        billing = gateway_app[1]
        with engine.begin() as conn:
            conn.execute(billing.payments.insert().values(username='bob', utr='123456789012',
                amount_paise=236000, status='approved', submitted_at='2020-01-01T00:00:00+00:00',
                access_until='2020-02-01T00:00:00+00:00'))
    service = importlib.import_module('services.pending_order_execution_service')
    pending = SimpleNamespace(id=1, user_id='bob', status='approved')
    monkeypatch.setattr(service, 'get_pending_order_by_id', lambda oid: pending)
    claim, key, token, update = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(service, 'claim_pending_order_for_execution', claim)
    monkeypatch.setattr(service, 'get_api_key_for_tradingview', key)
    monkeypatch.setattr(service, 'get_auth_token', token)
    monkeypatch.setattr(service, 'update_broker_status', update)
    success, result, code = service.execute_approved_order(1)
    assert not success and code == 402
    assert result['subscription_url'] == '/subscription'
    for operation in (claim, key, token, update):
        operation.assert_not_called()
    assert pending.status == 'approved'


def test_paid_pending_order_reaches_existing_execution_claim(gateway_app, monkeypatch):
    app, billing, gateway, state = gateway_app
    bob = signed_client(app, 'bob')
    order = make_order(bob, state)
    assert post(bob, '/subscription/razorpay/verify', signed(order['order_id'])).json['active']
    service = importlib.import_module('services.pending_order_execution_service')
    pending = SimpleNamespace(id=1, user_id='bob', status='approved')
    monkeypatch.setattr(service, 'get_pending_order_by_id', lambda oid: pending)
    claim = Mock(return_value=False)  # Existing duplicate claim prevents any send.
    monkeypatch.setattr(service, 'claim_pending_order_for_execution', claim)
    success, result, code = service.execute_approved_order(1)
    assert not success and code == 409
    claim.assert_called_once_with(1)


def test_flow_rechecks_subscription_before_each_broker_node(owned, monkeypatch):
    flows, auth, workflow_id, other_id, validate = owned
    from services import manual_subscription as billing
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    billing.init_db()
    expiry = datetime(2030, 1, 1, tzinfo=timezone.utc)
    from database.user_db import engine
    with engine.begin() as conn:
        conn.execute(billing.payments.insert().values(username='alice', utr='123456789012',
            amount_paise=236000, status='approved', submitted_at='2026-01-01T00:00:00+00:00',
            access_until=expiry.isoformat()))
    monkeypatch.setattr(billing, 'now', lambda: expiry.replace(year=2029))
    assert validate(workflow_id, 'a-key') == 'alice'
    from services import account_flow_execution as execution
    # Exercise the broker boundary with a fake client; no execution flag or
    # real broker is enabled, and no graph/trigger is started by this test.
    monkeypatch.setattr(execution, 'account_flow_execution_enabled', lambda: True)
    broker = Mock()
    client = execution.AccountFlowClient(workflow_id, 'alice', 'a-key', broker)
    client.place_order(symbol='SYNTHETIC')
    broker.place_order.assert_called_once()
    monkeypatch.setattr(billing, 'now', lambda: expiry)
    with pytest.raises(ValueError):
        client.place_order(symbol='SYNTHETIC')
    broker.place_order.assert_called_once()
