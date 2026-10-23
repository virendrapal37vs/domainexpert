"""HTTP access transitions without changing real accounts or calling a broker."""
from datetime import datetime, timedelta, timezone
from test_razorpay_subscription import gateway_app, post, make_order, signed
from test_paper_dashboard import signed_client


def test_paid_session_loses_write_access_at_expiry(gateway_app, monkeypatch):
    app, billing, gateway, state = gateway_app
    calls = []
    def write():
        calls.append('write')
        return {'ok': True}
    app.add_url_rule('/expiry-paper-write', endpoint='paper_preview.expiry_write',
                     methods=['POST'], view_func=write)
    app.add_url_rule('/expiry-saved-report', endpoint='paper_preview.expiry_report',
                     view_func=lambda: {'ok': True})
    bob = signed_client(app, 'bob')
    alice = signed_client(app, 'alice')
    # An unpaid account is rejected before the protected handler runs.
    assert bob.get('/api/account/brokers/groww').status_code == 402
    assert post(bob, '/expiry-paper-write', {}).status_code == 402
    assert calls == []
    order = make_order(bob, state)
    assert post(bob, '/subscription/razorpay/verify',
                signed(order['order_id'])).json['active'] is True
    assert bob.get('/api/account/brokers/groww').status_code == 200
    assert post(bob, '/expiry-paper-write', {}).status_code == 200
    assert calls == ['write']
    assert alice.get('/api/account/brokers/groww').status_code == 402
    saved = gateway.own_order(order['order_id'])
    expiry = datetime.fromisoformat(saved['access_until'])
    monkeypatch.setattr(billing, 'now', lambda: expiry - timedelta(microseconds=1))
    assert bob.get('/api/account/brokers/groww').status_code == 200
    # The same signed-in browser loses access at the exact expiry boundary.
    monkeypatch.setattr(billing, 'now', lambda: expiry)
    assert bob.get('/api/account/brokers/groww').status_code == 402
    assert post(bob, '/expiry-paper-write', {}).status_code == 402
    assert calls == ['write']
    assert bob.get('/expiry-saved-report').status_code == 200
    assert gateway.own_order(order['order_id'])['access_until'] == saved['access_until']


def test_owner_exemption_does_not_transfer_through_session(gateway_app):
    app, billing, gateway, state = gateway_app
    from database import user_db as users
    users.add_user(billing.OWNER, billing.OWNER, 'test', is_admin=True)
    owner = signed_client(app, billing.OWNER)
    assert owner.get('/api/account/brokers/groww').status_code == 200
    bob = signed_client(app, 'bob')
    with bob.session_transaction() as session:
        session['email'] = billing.OWNER
        session['is_admin'] = True
    assert bob.get('/api/account/brokers/groww').status_code == 402
