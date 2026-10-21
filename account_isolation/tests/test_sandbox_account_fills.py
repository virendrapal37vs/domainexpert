"""Real OMS and fill engine with fixed offline prices and a disposable database."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_two_accounts_place_and_fill_without_crossing_books(tmp_path):
    code = r'''
import logging, socket, sys
from types import ModuleType, SimpleNamespace
from decimal import Decimal

def forbidden(*a, **k):
    raise AssertionError('External access forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden

def stub(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module

stub('utils.logging', get_logger=logging.getLogger)
stub('database.token_db', get_symbol_info=lambda *a: SimpleNamespace(lotsize=1))
stub('database.symbol', SymToken=object)
stub('database.auth_db', get_auth_token_broker=forbidden)
stub('services.quotes_service', get_quotes=forbidden, get_multiquotes=forbidden)
stub('sandbox.websocket_execution_engine',
     is_websocket_execution_engine_running=lambda: False,
     peek_websocket_execution_engine=lambda: None)
from database import sandbox_db as db
from sandbox.fund_manager import FundManager
from sandbox.order_manager import OrderManager
from sandbox.execution_engine import ExecutionEngine

db.Base.metadata.create_all(db.engine)
# Event delivery is outside this DB/fill test; capture its account identity.
events = []
OrderManager._publish_order_update_event = lambda self, order, **kw: events.append(('order', order.user_id))
ExecutionEngine._publish_fill_event = lambda self, **kw: events.append(('fill', kw['user_id']))
ExecutionEngine._publish_order_update_event = lambda self, order, **kw: events.append(('update', order.user_id))
funds = {owner: FundManager(owner) for owner in ('alice', 'bob')}
for manager in funds.values():
    assert manager.initialize_funds()[0]
    manager._check_and_reset_funds = lambda row: None
capital = funds['bob'].get_funds()['availablecash']
orders = {}
for owner, qty in [('alice', 3), ('bob', 7)]:
    ok, response, status = OrderManager(owner).place_order({
        'symbol': 'BHEL', 'exchange': 'NSE', 'action': 'BUY', 'quantity': qty,
        'price': 90, 'price_type': 'LIMIT', 'product': 'CNC',
        'strategy': 'synthetic-account-check'}, prefetched_quote={'ltp': 100})
    assert ok and status == 200, response
    orders[owner] = response['orderid']
    row = db.SandboxOrders.query.filter_by(orderid=orders[owner]).one()
    assert row.order_status == 'open'
    assert db.SandboxTrades.query.count() == 0
    assert db.SandboxPositions.query.count() == 0
    assert funds[owner].get_funds()['availablecash'] == capital - qty * 90
    if owner == 'alice':
        assert funds['bob'].get_funds()['availablecash'] == capital

engine = ExecutionEngine()
def fill(owner):
    row = db.SandboxOrders.query.filter_by(orderid=orders[owner]).one()
    engine._process_order(row, {'ltp': 90, 'low': 80, 'high': 110})
    db.db_session.remove()
    row = db.SandboxOrders.query.filter_by(orderid=orders[owner]).one()
    assert row.order_status == 'complete'
    assert row.pending_quantity == 0 and row.filled_quantity == row.quantity
    assert row.average_price == Decimal('90')

fill('alice')
assert db.SandboxPositions.query.filter_by(user_id='bob').count() == 0
assert db.SandboxTrades.query.filter_by(user_id='bob').count() == 0
assert db.SandboxOrders.query.filter_by(orderid=orders['bob']).one().order_status == 'open'
assert funds['bob'].get_funds()['availablecash'] == capital - 630
fill('bob')
for owner, qty in [('alice', 3), ('bob', 7)]:
    position = db.SandboxPositions.query.filter_by(user_id=owner, symbol='BHEL').one()
    assert position.quantity == qty and position.average_price == Decimal('90')
    assert position.margin_blocked == Decimal(qty * 90)
    trade = db.SandboxTrades.query.filter_by(user_id=owner).one()
    assert trade.orderid == orders[owner] and trade.quantity == qty
    assert funds[owner].get_funds()['availablecash'] == capital - qty * 90
    assert funds[owner].get_funds()['utiliseddebits'] == qty * 90
# Repeat the same fill decision: no second trade, position increment or margin debit.
fill('alice')
fill('bob')
assert db.SandboxTrades.query.count() == 2
for owner, qty in [('alice', 3), ('bob', 7)]:
    assert db.SandboxPositions.query.filter_by(user_id=owner).one().quantity == qty
    assert funds[owner].get_funds()['utiliseddebits'] == qty * 90
assert [owner for kind, owner in events if kind == 'fill'] == ['alice', 'bob']
db.db_session.remove()
db.engine.dispose()
print('PASS: real placement, fixed-price fills and duplicate replay stay account-owned')
'''
    env = os.environ.copy()
    env.update(SANDBOX_DATABASE_URL='sqlite:///' + str(tmp_path / 'fills.db'),
               DOMAINXPERT_PER_USER_GROWW='true', PYTHONPATH=str(ROOT))
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
