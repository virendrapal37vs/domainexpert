"""Manual quote valuation through real SQLite, session and CSRF guards."""
import importlib
import time
from decimal import Decimal
import pytest
from test_paper_dashboard import dashboard_app, seed, signed_client

URL = '/paper-preview/dashboard/quote'


@pytest.fixture(autouse=True)
def csrf_route(dashboard_app):
    from flask_wtf.csrf import generate_csrf
    app, _, _ = dashboard_app
    app.add_url_rule('/valuation-csrf', endpoint='auth.get_csrf_token',
                     view_func=lambda: {'csrf_token': generate_csrf()})



def setup_quote(monkeypatch, credentials=None, price=420, age=1):
    store = importlib.import_module('database.account_broker_db')
    monkeypatch.setattr(store, 'get_groww_credentials', lambda owner: (credentials.append(owner) or (owner+'-key', 'secret')) if credentials is not None else None)
    provider = importlib.import_module('services.groww_paper_quote')
    calls = []
    def quote(creds):
        calls.append(creds)
        return dict(ltp=price, last_trade_time=time.time()-age), None
    monkeypatch.setattr(provider, 'fetch_quote', quote)
    return provider, calls


def post(client, **kwargs):
    token = client.get('/valuation-csrf').json['csrf_token']
    return client.post(URL+'?format=json', headers={'X-CSRFToken':token}, json=kwargs)


@pytest.mark.parametrize('price,expected', [(420,20), (390,-10)])
def test_owner_quote_and_decimal_pnl(dashboard_app, monkeypatch, price, expected):
    app, db, _ = dashboard_app
    seed(db)
    owners = []
    _, calls = setup_quote(monkeypatch, owners, price)
    alice = signed_client(app,'alice')
    result = post(alice, username='bob', quantity=999, price=1)
    assert result.status_code == 200
    value = result.json['valuation']
    assert value['quantity'] == 1 and value['unrealized_pnl'] == expected
    assert value['valid_until'] == value['last_trade_time']+120
    assert owners == ['alice'] and calls == [('alice-key','secret')]
    bob = post(signed_client(app,'bob')).json['valuation']
    assert bob['quantity'] == 2 and bob['unrealized_pnl'] == expected*2
    assert owners == ['alice','bob']
    assert db.SandboxOrders.query.count() == 4
    assert db.SandboxFunds.query.filter_by(user_id='alice').first().available_balance == Decimal('1000')
    assert db.SandboxPositions.query.filter_by(user_id='alice',symbol='DXBHEL').first().accumulated_realized_pnl == Decimal('10')


def test_no_network_on_get_export_or_closed_position(dashboard_app, monkeypatch):
    app, db, _ = dashboard_app
    owners=[]
    _, calls=setup_quote(monkeypatch, owners)
    client=signed_client(app,'bob')
    assert client.get('/paper-preview/dashboard').status_code == 200
    assert client.get('/paper-preview/dashboard/export/positions.csv').status_code == 200
    result=post(client)
    assert result.json['valuation']['status'] == 'closed'
    assert result.json['valuation']['unrealized_pnl'] == 0
    assert calls == [] and owners == []
    assert db.SandboxFunds.query.count() == 0


def test_auth_csrf_flag_and_method_guards(dashboard_app, monkeypatch):
    app, db, _=dashboard_app
    seed(db)
    owners=[]
    _,calls=setup_quote(monkeypatch, owners)
    client=signed_client(app,'alice')
    assert client.post(URL,json={}).status_code == 400
    anonymous=app.test_client()
    csrf=anonymous.get('/valuation-csrf').json['csrf_token']
    assert anonymous.post(URL,json={},headers={'X-CSRFToken':csrf}).status_code == 401
    assert client.get(URL).status_code in (403,405)
    monkeypatch.setenv('DOMAINXPERT_GROWW_PAPER_PREVIEW','false')
    assert post(client).status_code == 403
    assert owners == [] and calls == []


@pytest.mark.parametrize('age', [121,-10])
def test_stale_or_future_quote_never_returns_estimate(dashboard_app, monkeypatch, age):
    app,db,_=dashboard_app
    seed(db)
    setup_quote(monkeypatch, [], age=age)
    result=post(signed_client(app,'alice'))
    assert result.status_code == 503
    assert result.json['valuation']['unrealized_pnl'] is None
    assert 'quote_price' not in result.json['valuation']


def test_credential_error_replaces_prior_success(dashboard_app, monkeypatch):
    app,db,_=dashboard_app
    seed(db)
    provider,calls=setup_quote(monkeypatch, [])
    client=signed_client(app,'alice')
    csrf=client.get('/valuation-csrf').json['csrf_token']
    first=client.post(URL,data={'csrf_token':csrf})
    assert first.status_code == 200 and b'data-valuation-expiry=' in first.data
    assert first.headers['Cache-Control'] == 'no-store'
    monkeypatch.setattr(provider,'fetch_quote',lambda _: (None,'secret raw provider error'))
    failed=client.post(URL,data={'csrf_token':csrf})
    assert failed.status_code == 503
    assert b'data-valuation-expiry=' not in failed.data
    assert b'secret raw provider error' not in failed.data
    store=importlib.import_module('database.account_broker_db')
    monkeypatch.setattr(store,'get_groww_credentials',lambda _:None)
    assert post(client).json['valuation']['unrealized_pnl'] is None


def test_position_reloaded_after_quote(dashboard_app, monkeypatch):
    app,db,_=dashboard_app
    seed(db)
    provider,_=setup_quote(monkeypatch, [])
    def quote(_):
        # Simulate another request closing the position during the network call.
        row=db.SandboxPositions.query.filter_by(user_id='alice',symbol='DXBHEL').first()
        row.quantity=0
        db.db_session.commit()
        return dict(ltp=420,last_trade_time=time.time()),None
    monkeypatch.setattr(provider,'fetch_quote',quote)
    value=post(signed_client(app,'alice')).json['valuation']
    assert value['quantity'] == 0 and value['unrealized_pnl'] == 0
