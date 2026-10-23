"""Read-only dashboard against real per-account SQLite records."""
import importlib
import socket
from decimal import Decimal
import pytest


@pytest.fixture
def dashboard_app(main_app, tmp_path, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    monkeypatch.setenv('DOMAINXPERT_PAPER_PREVIEW', 'true')
    monkeypatch.setenv('DOMAINXPERT_GROWW_PAPER_PREVIEW', 'true')
    monkeypatch.setenv('SANDBOX_DATABASE_URL', 'sqlite:///' + str(tmp_path / 'paper.db'))
    import sys
    previous = sys.modules.pop('database.sandbox_db', None)
    if previous:
        previous.db_session.remove()
    db = importlib.import_module('database.sandbox_db')
    db.Base.metadata.create_all(db.engine)
    staging = importlib.import_module('utils.staging_mode')
    validations = []
    monkeypatch.setattr(staging, 'validate_staging_config', lambda root: validations.append(root))
    main_app.template_folder = str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'templates')
    main_app.register_blueprint(importlib.import_module('blueprints.paper_preview').paper_preview_bp)
    staging.install_staging_gate(main_app)
    def forbidden(*args, **kwargs):
        raise AssertionError('Dashboard must not contact broker or decrypt secrets')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    store = importlib.import_module('database.account_broker_db')
    store.save_groww_credentials('alice', 'private-key', 'private-secret')
    monkeypatch.setattr(store, 'get_groww_credentials', forbidden)
    yield main_app, db, validations
    db.db_session.remove()
    db.engine.dispose()


def signed_client(app, owner):
    client = app.test_client()
    with client.session_transaction() as session:
        session['user'] = owner
    return client


def seed(db):
    for owner, cash in [('alice', 1000), ('bob', 2000)]:
        db.db_session.add(db.SandboxFunds(user_id=owner, available_balance=cash, used_margin=400))
    for owner, symbol, qty, pnl in [('alice', 'DXBHEL', 1, 10), ('alice', 'DXPAPER', 0, 30), ('alice', 'BHEL', 50, 900), ('bob', 'DXBHEL', 2, 99)]:
        db.db_session.add(db.SandboxPositions(user_id=owner, symbol=symbol, exchange='NSE', product='CNC', quantity=qty, average_price=400, accumulated_realized_pnl=pnl))
        db.db_session.add(db.SandboxOrders(user_id=owner, orderid=owner + '-' + symbol, symbol=symbol,
            exchange='NSE', product='CNC', action='BUY', quantity=max(1, qty), price_type='LIMIT',
            price=400, average_price=400, pending_quantity=0, order_status='complete'))
    db.db_session.commit()


def test_dashboard_owner_scoping_and_no_mutation(dashboard_app):
    app, db, validations = dashboard_app
    seed(db)
    url = '/paper-preview/dashboard'
    assert app.test_client().get(url).status_code == 401
    alice = signed_client(app, 'alice')
    response = alice.get(url + '?format=json&username=bob&symbol=BHEL')
    assert response.status_code == 200
    data = response.json
    assert data['username'] == 'alice' and data['available_cash'] == 1000
    assert data['preview_realized_pnl'] == 40 and data['open_positions'] == 1
    assert data['groww_credentials_saved'] is True and data['paper_only'] is True
    assert {row['symbol'] for row in data['positions']} == {'DXPAPER', 'DXBHEL'}
    assert {row['orderid'] for row in data['orders']} == {'alice-DXPAPER', 'alice-DXBHEL'}
    html = alice.get(url)
    assert html.headers['Cache-Control'] == 'no-store'
    assert b'Paper trading dashboard' in html.data
    assert b'bob-DXBHEL' not in html.data and b'private-key' not in html.data
    assert b'private-secret' not in html.data and b'alice-BHEL' not in html.data
    bob = signed_client(app, 'bob').get(url + '?format=json').json
    assert bob['available_cash'] == 2000 and bob['preview_realized_pnl'] == 99
    assert bob['groww_credentials_saved'] is False
    assert all(row['orderid'].startswith('bob-') for row in bob['orders'])
    assert db.SandboxOrders.query.count() == 4
    assert db.SandboxFunds.query.filter_by(user_id='alice').first().available_balance == Decimal('1000')
    assert validations


def test_empty_dashboard_does_not_initialize_funds(dashboard_app):
    app, db, _ = dashboard_app
    client = signed_client(app, 'bob')
    result = client.get('/paper-preview/dashboard?format=json').json
    assert result['available_cash'] is None and result['used_margin'] is None
    assert result['orders'] == [] and result['open_positions'] == 0
    assert db.SandboxFunds.query.count() == 0
    assert b'No preview orders yet' in client.get('/paper-preview/dashboard').data


def test_dashboard_gate_and_latest_fifty(dashboard_app, monkeypatch):
    app, db, _ = dashboard_app
    client = signed_client(app, 'alice')
    for index in range(55):
        db.db_session.add(db.SandboxOrders(user_id='alice', orderid=f'a-{index}', symbol='DXBHEL', exchange='NSE',
            product='CNC', action='BUY', quantity=1, price_type='LIMIT', pending_quantity=1, order_status='open'))
    db.db_session.commit()
    data = client.get('/paper-preview/dashboard?format=json').json
    assert len(data['orders']) == 50
    assert data['orders'][0]['orderid'] == 'a-54' and data['orders'][-1]['orderid'] == 'a-5'
    assert data['orders'][0]['price'] is None
    monkeypatch.setenv('DOMAINXPERT_GROWW_PAPER_PREVIEW', 'false')
    assert b'Groww quote simulation</a>' not in client.get('/paper-preview/dashboard').data
    monkeypatch.setenv('DOMAINXPERT_PAPER_PREVIEW', 'false')
    assert client.get('/paper-preview/dashboard').status_code == 403
