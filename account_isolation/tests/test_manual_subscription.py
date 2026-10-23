"""Real SQLite approval, expiry, role and payment reference isolation checks."""
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
import pytest
from test_paper_dashboard import signed_client


@pytest.fixture
def billing_app(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    sys.modules.pop('services.manual_subscription', None)
    sys.modules.pop('blueprints.account_subscription', None)
    service = importlib.import_module('services.manual_subscription')
    service.init_db()
    bp = importlib.import_module('blueprints.account_subscription')
    main_app.template_folder = str(Path(__file__).resolve().parents[2] / 'templates')
    main_app.register_blueprint(bp.subscription_bp)
    bp.install_subscription_gate(main_app)
    return main_app, service


def post(client, path, **data):
    data['csrf_token'] = client.get('/csrf').json['csrf_token']
    return client.post(path, data=data)


def test_submit_approve_owner_isolation_and_repeat(billing_app):
    app, service = billing_app
    bob = signed_client(app, 'bob')
    alice = signed_client(app, 'alice')
    assert bob.get('/api/account/brokers/groww').status_code == 402
    assert post(bob, '/subscription/payment', utr='123456789012', username='alice', amount_paise='1', status='approved').status_code == 303
    row = service.rows()[0]
    assert row['username'] == 'bob' and row['amount_paise'] == 236000 and row['status'] == 'pending'
    assert bob.get('/api/account/brokers/groww').status_code == 402
    assert alice.get('/subscription?format=json').json['payments'] == []
    assert post(alice, '/subscription/payment', utr='123456789012').status_code == 409
    assert post(bob, '/subscription/payment', utr='999999999999').status_code == 409
    assert bob.get('/subscription/admin').status_code == 403
    url = f"/subscription/admin/{row['id']}"
    assert post(bob, url, bank_verified='yes', decision='approved').status_code == 403
    assert post(alice, url, decision='approved').status_code == 400
    assert post(alice, url, bank_verified='yes', decision='approved').status_code == 303
    assert bob.get('/api/account/brokers/groww').status_code == 200
    assert post(alice, url, bank_verified='yes', decision='approved').status_code == 409
    assert service.rows()[0]['reviewed_by'] == 'alice'
    html = bob.get('/subscription')
    assert html.headers['Cache-Control'] == 'no-store' and b'2,360' in html.data
    assert bob.get('/subscription/qr').mimetype == 'image/png'


def test_exemption_requires_persisted_owner_admin(billing_app):
    app, service = billing_app
    from database import user_db as users
    users.add_user(service.OWNER, service.OWNER, 'test', is_admin=True)
    owner = signed_client(app, service.OWNER)
    assert owner.get('/subscription?format=json').json['subscription']['exempt'] is True
    assert owner.get('/api/account/brokers/groww').status_code == 200
    # Neither arbitrary admin nor cookie email/role is an exemption.
    alice = signed_client(app, 'alice')
    with alice.session_transaction() as session:
        session['email'] = service.OWNER
        session['is_admin'] = True
    assert alice.get('/api/account/brokers/groww').status_code == 402
    user = users.find_user_by_exact_username(service.OWNER)
    user.is_admin = False
    users.db_session.commit()
    assert owner.get('/api/account/brokers/groww').status_code == 402


def test_expiry_calendar_renewal_rejection(billing_app, monkeypatch):
    app, service = billing_app
    bob = signed_client(app, 'bob')
    alice = signed_client(app, 'alice')
    from database.user_db import find_user_by_exact_username
    user = find_user_by_exact_username('bob')
    admin = find_user_by_exact_username('alice')
    monkeypatch.setattr(service, 'now', lambda: datetime(2026,1,31,12,tzinfo=timezone.utc))
    service.submit(user, '111111111111')
    service.review(service.rows()[0]['id'], admin, 'approved')
    assert service.status(user)['access_until'].startswith('2026-02-28T12:00')
    service.submit(user, '222222222222')
    service.review(service.rows()[0]['id'], admin, 'approved')
    assert service.status(user)['access_until'].startswith('2026-03-28T12:00')
    service.submit(user, '333333333333')
    service.review(service.rows()[0]['id'], admin, 'rejected')
    assert service.status(user)['access_until'].startswith('2026-03-28')
    monkeypatch.setattr(service, 'now', lambda: datetime(2026,3,28,12,tzinfo=timezone.utc))
    assert not service.status(user)['active']
    assert bob.get('/api/account/brokers/groww').status_code == 402


def test_anonymous_csrf_disabled_and_bad_reference(billing_app, monkeypatch):
    app, service = billing_app
    assert app.test_client().get('/subscription').status_code == 401
    bob = signed_client(app, 'bob')
    assert bob.post('/subscription/payment', data={'utr':'123456789012'}).status_code == 400
    for utr in ('', 'abcd', '123', '１２３４５６７８９０１２'):
        assert post(bob, '/subscription/payment', utr=utr).status_code == 409
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'false')
    assert bob.get('/subscription').status_code == 404
    assert bob.get('/api/account/brokers/groww').status_code == 200
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'false')
    assert bob.get('/api/account/brokers/groww').status_code == 503


def test_payment_gate_leaves_reports_readable_and_blocks_paper_write(billing_app):
    app, service = billing_app
    app.add_url_rule('/saved-report', endpoint='paper_preview.dashboard', view_func=lambda: {'ok':True})
    app.add_url_rule('/paper-write', endpoint='paper_preview.order', methods=['POST'], view_func=lambda: {'ok':True})
    app.add_url_rule('/broker-config', endpoint='auth.get_broker_config', view_func=lambda: {'ok':True})
    bob = signed_client(app, 'bob')
    assert bob.get('/saved-report').status_code == 200
    assert post(bob, '/paper-write').status_code == 402
    assert bob.get('/broker-config').json['subscription_url'] == '/subscription'


def test_concurrent_reference_claim_has_one_winner(billing_app):
    app, service = billing_app
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    def attempt(i):
        try:
            service.submit(SimpleNamespace(username=f'user{i}'), '123456789012')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    assert len(service.rows()) == 1
