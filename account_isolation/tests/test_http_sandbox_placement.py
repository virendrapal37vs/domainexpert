"""Real REST resource/schema/service/OMS, synthetic API-key lookup, offline SQLite."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_rest_key_owner_reaches_real_sandbox_oms(tmp_path):
    script = r'''
import logging, socket, sys, os
from types import ModuleType, SimpleNamespace
from flask import Flask
from flask_restx import Api

def forbidden(*a, **kw):
    raise AssertionError('Live broker/network path forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden

def stub(name, **attrs):
    m = ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m
# Load actual schema/resource modules without starting unrelated REST namespaces.
package = ModuleType('restx_api')
package.__path__ = [os.path.join(os.environ['PYTHONPATH'], 'restx_api')]
sys.modules['restx_api'] = package
keys = {'synthetic-alice-key': 'alice', 'synthetic-bob-key': 'bob'}
stub('utils.logging', get_logger=logging.getLogger)
stub('database.auth_db', verify_api_key=keys.get,
     get_auth_token_broker=lambda key: ('synthetic-token', 'groww') if key in keys else (None, None),
     get_api_key_for_tradingview=lambda owner: 'synthetic-'+owner+'-key')
stub('database.user_db', find_user_by_exact_username=lambda owner: owner if owner in keys.values() else None)
stub('database.account_mode_db', get_account_analyze_mode=lambda owner: True)
from utils.account_mode_context import read_account_mode
stub('database.settings_db', get_analyze_mode=read_account_mode)
stub('database.token_db', get_symbol_info=lambda *a: SimpleNamespace(lotsize=1, contract_value=1))
stub('database.symbol', SymToken=object)
quote_keys = []
def quote(**kw):
    assert kw['api_key'] in keys
    quote_keys.append(kw['api_key'])
    return True, {'data': {'ltp': 100, 'low': 80, 'high': 120}}, 200
stub('services.quotes_service', get_quotes=quote, get_multiquotes=forbidden)
stub('services.market_data_service', get_market_data_service=forbidden)
stub('services.order_router_service', should_route_to_pending=lambda *a: False, queue_order=forbidden)
from dataclasses import dataclass
@dataclass
class Event:
    pass
stub('utils.event_bus', Event=Event, bus=SimpleNamespace(publish=lambda event: None))
stub('sandbox.websocket_execution_engine', is_websocket_execution_engine_running=lambda: False,
     peek_websocket_execution_engine=lambda: None)
# Rate limiting is outside this ownership integration; leave resource/schema intact.
stub('limiter', limiter=SimpleNamespace(limit=lambda *a: lambda fn: fn))
from database import sandbox_db as db
from sandbox.fund_manager import FundManager
from sandbox.order_manager import OrderManager
from sandbox.execution_engine import ExecutionEngine
from services import place_order_service as service
service.import_broker_module = forbidden
OrderManager._publish_order_update_event = lambda *a, **kw: None
ExecutionEngine._publish_fill_event = lambda *a, **kw: None
ExecutionEngine._publish_order_update_event = lambda *a, **kw: None
db.Base.metadata.create_all(db.engine)
for owner in keys.values():
    assert FundManager(owner).initialize_funds()[0]
from restx_api.place_order import api as namespace
app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='synthetic-http-test')
api = Api(app, doc=False); api.add_namespace(namespace, path='/api/v1/placeorder')
client = app.test_client()
# A conflicting browser session must not override the REST API key owner.
with client.session_transaction() as session:
    session.update(user='bob', logged_in=True)
def payload(key, qty):
    return dict(apikey=key, strategy='offline-http', symbol='BHEL', exchange='NSE',
                action='BUY', quantity=qty, pricetype='LIMIT', price=90, product='CNC')
for key, owner in keys.items():
    before = db.SandboxOrders.query.count()
    response = client.post('/api/v1/placeorder', json=payload(key, 3 if owner == 'alice' else 7))
    assert response.status_code == 200, response.json
    assert response.json['mode'] == 'analyze'
    assert db.SandboxOrders.query.count() == before + 1
    row = db.SandboxOrders.query.filter_by(orderid=response.json['orderid']).one()
    assert row.user_id == owner and row.order_status == 'open'
    assert quote_keys[-1] == key
before = db.SandboxOrders.query.count()
for body in [payload('invalid-key', 5), {k:v for k,v in payload('synthetic-alice-key',5).items() if k != 'apikey'},
             dict(payload('synthetic-alice-key',5), username='bob', user_id='bob')]:
    response = client.post('/api/v1/placeorder', json=body)
    assert response.status_code in (400, 403), response.json
    assert db.SandboxOrders.query.count() == before
# Clear browser session: a valid API key still owns the request.
with client.session_transaction() as session:
    session.clear()
response = client.post('/api/v1/placeorder', json=payload('synthetic-alice-key', 2))
assert response.status_code == 200, response.json
assert db.SandboxOrders.query.filter_by(orderid=response.json['orderid']).one().user_id == 'alice'
assert sorted(row.quantity for row in db.SandboxOrders.query.filter_by(user_id='alice')) == [2,3]
assert [row.quantity for row in db.SandboxOrders.query.filter_by(user_id='bob')] == [7]
assert db.SandboxTrades.query.count() == db.SandboxPositions.query.count() == 0
assert db.SandboxFunds.query.filter_by(user_id='alice').one().used_margin == 450
assert db.SandboxFunds.query.filter_by(user_id='bob').one().used_margin == 630
db.db_session.remove(); db.engine.dispose()
print('PASS: REST key ownership survives schema, mode routing, sandbox service and OMS')
'''
    env = os.environ.copy()
    env.update(SANDBOX_DATABASE_URL='sqlite:///' + str(tmp_path / 'http-paper.db'),
               DOMAINXPERT_PER_USER_GROWW='true', DOMAINXPERT_ACCOUNT_MODES='true',
               PYTHONPATH=str(ROOT))
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, env=env,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
