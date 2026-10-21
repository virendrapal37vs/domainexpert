"""Actual sandbox managers and SQLite; seeded paper records, no fills or broker I/O."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_sandbox_accounts_with_real_sqlite(tmp_path):
    code = r'''
import logging, socket, sys
from types import ModuleType
from datetime import datetime
from decimal import Decimal

def forbidden(*a, **k):
    raise AssertionError('Broker/network access forbidden in offline sandbox check')
socket.socket.connect = forbidden
socket.create_connection = forbidden

def stub(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module

stub('utils.logging', get_logger=logging.getLogger)
stub('database.token_db', get_symbol_info=forbidden)
stub('database.symbol', SymToken=object)
stub('services.quotes_service', get_quotes=forbidden, get_multiquotes=forbidden)
stub('services.market_data_service', get_market_data_service=forbidden)
from database import sandbox_db as db
from sandbox.fund_manager import FundManager
from sandbox.order_manager import OrderManager
from sandbox.position_manager import PositionManager

db.Base.metadata.create_all(db.engine)
alice, bob = FundManager('alice'), FundManager('bob')
for manager in (alice, bob):
    assert manager.initialize_funds()[0]
    # Reset scheduling is outside this ownership test; use current seeded balance.
    manager._check_and_reset_funds = lambda funds: None
before = bob.get_funds().copy()
assert alice.block_margin(1250)[0]
assert bob.get_funds() == before
assert alice.get_funds()['availablecash'] == before['availablecash'] - 1250
assert alice.get_funds()['utiliseddebits'] == 1250
assert bob.block_margin(250)[0]
assert alice.get_funds()['utiliseddebits'] == 1250
assert bob.get_funds()['utiliseddebits'] == 250

for owner, qty in [('alice', 3), ('bob', 7)]:
    db.db_session.add(db.SandboxOrders(orderid=owner+'-order', user_id=owner,
        symbol='BHEL', exchange='NSE', action='BUY', quantity=qty,
        pending_quantity=qty, price=100, price_type='LIMIT', product='MIS',
        order_status='open', order_timestamp=datetime.now()))
    db.db_session.add(db.SandboxPositions(user_id=owner, symbol='BHEL',
        exchange='NSE', product='MIS', quantity=qty, average_price=100))
db.db_session.commit()

for owner, other, qty in [('alice', 'bob', 3), ('bob', 'alice', 7)]:
    orders = OrderManager(owner)
    ok, book, status = orders.get_orderbook()
    assert ok and status == 200, book
    assert [o['orderid'] for o in book['data']['orders']] == [owner+'-order']
    assert orders.get_order_status(other+'-order')[2] == 404
    assert orders.modify_order(other+'-order', {'quantity': 99})[2] == 404
    assert orders.cancel_order(other+'-order')[2] == 404
    positions = PositionManager(owner)
    # Explicitly skip market valuation; exercise actual owner-scoped position read.
    positions._update_single_position_mtm = lambda position: None
    position = positions.get_position_for_symbol('BHEL', 'NSE', 'MIS')
    assert position['quantity'] == qty, position
    assert position['average_price'] == 100

# Reopen the session: blocked cross-account writes left durable rows untouched.
db.db_session.remove()
for owner, qty in [('alice', 3), ('bob', 7)]:
    row = db.SandboxOrders.query.filter_by(orderid=owner+'-order').one()
    assert row.quantity == qty and row.order_status == 'open'
    assert db.SandboxPositions.query.filter_by(user_id=owner).one().quantity == qty
assert db.SandboxFunds.query.filter_by(user_id='alice').one().used_margin == Decimal('1250')
assert db.SandboxFunds.query.filter_by(user_id='bob').one().used_margin == Decimal('250')
db.db_session.remove()
db.engine.dispose()
print('PASS: SQLite paper books, same-symbol positions and margin writes stay account-owned')
'''
    env = os.environ.copy()
    env.update(SANDBOX_DATABASE_URL='sqlite:///' + str(tmp_path / 'paper.db'),
               DOMAINXPERT_PER_USER_GROWW='true', PYTHONPATH=str(ROOT))
    # Empty cwd prevents implicit .env loading from a real installation.
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
