import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from utils.sandbox_quote_owner import quote_api_key, fetch_record_quotes


@pytest.fixture
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    lookup = Mock(side_effect=lambda user: {'alice': 'a-key', 'bob': 'b-key'}.get(user))
    monkeypatch.setitem(sys.modules, 'database.auth_db', SimpleNamespace(get_api_key_for_tradingview=lookup))
    return lookup


def test_exact_owner_key(scoped):
    assert quote_api_key('alice') == 'a-key'
    assert quote_api_key('bob') == 'b-key'


@pytest.mark.parametrize('owner', [None, '', 'missing'])
def test_missing_owner_has_no_fallback(scoped, owner):
    assert quote_api_key(owner) is None


def test_same_symbol_isolated_by_owner(scoped):
    engine = Mock()
    engine._fetch_quotes_batch.side_effect = lambda symbols, user_id: {('BHEL', 'NSE'): {'ltp': 10 if user_id == 'alice' else 20}}
    records = [SimpleNamespace(user_id=user, symbol='BHEL', exchange='NSE') for user in ('alice', 'bob', None)]
    quotes = fetch_record_quotes(engine, records)
    assert quotes[('alice', 'BHEL', 'NSE')]['ltp'] == 10
    assert quotes[('bob', 'BHEL', 'NSE')]['ltp'] == 20
    assert len(quotes) == 2
    assert engine._fetch_quotes_batch.call_count == 2


def test_unavailable_owner_quotes_not_replaced(scoped):
    engine = Mock()
    engine._fetch_quotes_batch.side_effect = lambda symbols, user_id: {} if user_id == 'bob' else {('BHEL', 'NSE'): {'ltp': 10}}
    records = [SimpleNamespace(user_id=user, symbol='BHEL', exchange='NSE') for user in ('alice', 'bob')]
    quotes = fetch_record_quotes(engine, records)
    assert ('bob', 'BHEL', 'NSE') not in quotes


def test_engine_quote_method_uses_owner_key(scoped):
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'sandbox/execution_engine.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExecutionEngine')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_fetch_quote')
    api = Mock(return_value=(True, {'data': {'ltp': 42}}, 200))
    env = {'quote_api_key': quote_api_key, 'get_quotes': api, 'logger': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<real-engine-method>', 'exec'), env)
    assert env['_fetch_quote'](None, 'BHEL', 'NSE', user_id='bob') == {'ltp': 42}
    assert api.call_args.kwargs['api_key'] == 'b-key'
    api.reset_mock()
    assert env['_fetch_quote'](None, 'BHEL', 'NSE') is None
    api.assert_not_called()


def test_real_polling_cycle_keeps_quote_owners_separate(scoped):
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'sandbox/execution_engine.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExecutionEngine')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'check_and_execute_pending_orders')
    orders = [SimpleNamespace(user_id=user, symbol='BHEL', exchange='NSE') for user in ('alice', 'bob')]
    rows = Mock()
    rows.query.filter.return_value.all.return_value = orders
    env = {'SandboxOrders': rows, 'fetch_record_quotes': fetch_record_quotes, 'logger': Mock(), 'time': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<real-polling-cycle>', 'exec'), env)
    engine = Mock(order_rate_limit=10)
    engine._fetch_quotes_batch.side_effect = lambda symbols, user_id: {('BHEL', 'NSE'): {'ltp': 10 if user_id == 'alice' else 20}}
    env['check_and_execute_pending_orders'](engine)
    assert engine._process_order.call_args_list[0].args == (orders[0], {'ltp': 10})
    assert engine._process_order.call_args_list[1].args == (orders[1], {'ltp': 20})


def test_legacy_quote_batch_unchanged(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    engine = Mock()
    engine._fetch_quotes_batch.return_value = {('BHEL', 'NSE'): {'ltp': 1}}
    records = [SimpleNamespace(user_id=user, symbol='BHEL', exchange='NSE') for user in ('alice', 'bob')]
    assert len(fetch_record_quotes(engine, records)) == 2
    engine._fetch_quotes_batch.assert_called_once_with([('BHEL', 'NSE')])
