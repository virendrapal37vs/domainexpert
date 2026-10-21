"""Real OMS and fill engine with fixed offline prices and a disposable database."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('close_price', [None, 110, 70], ids=['buy-only', 'close-profit', 'close-loss'])
def test_two_accounts_place_and_fill_without_crossing_books(tmp_path, close_price):
    code = r'''
import logging, socket, sys, os
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
stub('database.token_db', get_symbol_info=lambda *a: SimpleNamespace(lotsize=1, contract_value=1))
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

if os.environ.get('PAPER_CLOSE_PRICE'):
    close_price = int(os.environ['PAPER_CLOSE_PRICE'])
    bob_before = funds['bob'].get_funds().copy()
    ok, response, status = OrderManager('alice').place_order({
        'symbol': 'BHEL', 'exchange': 'NSE', 'action': 'SELL', 'quantity': 3,
        'price': close_price, 'price_type': 'LIMIT', 'product': 'CNC',
        'strategy': 'synthetic-account-close'}, prefetched_quote={'ltp': close_price - 1})
    assert ok and status == 200, response
    closing_id = response['orderid']
    row = db.SandboxOrders.query.filter_by(orderid=closing_id).one()
    assert row.order_status == 'open'
    assert funds['bob'].get_funds() == bob_before
    engine._process_order(row, {'ltp': close_price, 'low': 60, 'high': 120})
    db.db_session.remove()
    def verify_close():
        closed = db.SandboxPositions.query.filter_by(user_id='alice').one()
        pnl = Decimal(3 * (close_price - 90))
        assert closed.quantity == 0 and closed.margin_blocked == 0
        assert closed.accumulated_realized_pnl == pnl
        assert closed.today_realized_pnl == pnl
        actual = funds['alice'].get_funds()
        assert actual['availablecash'] == capital + float(pnl), actual
        assert actual['utiliseddebits'] == 0
        assert actual['total_realized_pnl'] == float(pnl)
        assert actual['today_realized_pnl'] == float(pnl)
        assert funds['bob'].get_funds() == bob_before
        bob_pos = db.SandboxPositions.query.filter_by(user_id='bob').one()
        assert bob_pos.quantity == 7 and bob_pos.average_price == Decimal('90')
        assert bob_pos.margin_blocked == Decimal('630')
        assert db.SandboxTrades.query.filter_by(user_id='bob').count() == 1
        assert db.SandboxTrades.query.filter_by(user_id='alice').count() == 2
        sell = db.SandboxTrades.query.filter_by(orderid=closing_id).one()
        assert sell.user_id == 'alice' and sell.action == 'SELL'
        assert sell.price == Decimal(close_price) and sell.quantity == 3
        close_order = db.SandboxOrders.query.filter_by(orderid=closing_id).one()
        assert close_order.order_status == 'complete' and close_order.pending_quantity == 0
    verify_close()
    # Replay the close: realized P&L and released cash must not be credited twice.
    engine._process_order(db.SandboxOrders.query.filter_by(orderid=closing_id).one(),
                          {'ltp': close_price, 'low': 60, 'high': 120})
    db.db_session.remove()
    verify_close()
    assert [owner for kind, owner in events if kind == 'fill'] == ['alice', 'bob', 'alice']
db.db_session.remove()
db.engine.dispose()
print('PASS: real placement, fixed-price fills and duplicate replay stay account-owned')
'''
    env = os.environ.copy()
    env.update(SANDBOX_DATABASE_URL='sqlite:///' + str(tmp_path / 'fills.db'),
               DOMAINXPERT_PER_USER_GROWW='true', PYTHONPATH=str(ROOT),
               PAPER_CLOSE_PRICE='' if close_price is None else str(close_price))
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
