import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]


def method(file, class_name, name, env):
    tree = ast.parse((ROOT / file).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real-sandbox-method>', 'exec'), env)
    return env[name]


@pytest.fixture(autouse=True)
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')


def test_tick_does_not_fill_other_users():
    env = {}
    callback = method('sandbox/websocket_execution_engine.py', 'WebSocketExecutionEngine', '_on_market_data', env)
    engine = Mock(_running=True)
    callback(engine, {'symbol': 'BHEL', 'exchange': 'NSE', 'data': {'ltp': 42}})
    engine._check_and_execute_order.assert_not_called()
    engine._check_gtt_legs.assert_not_called()


def test_ws_start_rejected():
    callback = method('sandbox/websocket_execution_engine.py', 'WebSocketExecutionEngine', 'start', {})
    with pytest.raises(RuntimeError):
        callback(Mock(_running=False))


def test_position_cache_bypassed():
    shared_cache = Mock(side_effect=AssertionError('Shared cache must not be read'))
    fn = method('sandbox/position_manager.py', 'PositionManager', '_fetch_quotes_from_websocket', {'scoped_quotes_enabled': lambda: True, 'get_market_data_service': shared_cache})
    assert fn(SimpleNamespace(user_id='bob'), [('BHEL', 'NSE')]) == {}
    shared_cache.assert_not_called()


@pytest.mark.parametrize('file,cls', [('sandbox/position_manager.py', 'PositionManager'), ('sandbox/holdings_manager.py', 'HoldingsManager')])
def test_rest_quotes_use_account_key(file, cls):
    from utils.sandbox_quote_owner import scoped_quotes_enabled
    key = Mock(return_value='bob-key')
    quote = Mock(return_value=(True, {'data': {'ltp': 42}}, 200))
    fn = method(file, cls, '_fetch_quote', {'quote_api_key': key, 'scoped_quotes_enabled': scoped_quotes_enabled, 'get_quotes': quote, 'logger': Mock()})
    assert fn(SimpleNamespace(user_id='bob'), 'BHEL', 'NSE') == {'ltp': 42}
    key.assert_called_once_with('bob')
    assert quote.call_args.kwargs['api_key'] == 'bob-key'
    key.return_value = None
    quote.reset_mock()
    assert fn(SimpleNamespace(user_id='bob'), 'BHEL', 'NSE') is None
    quote.assert_not_called()


def test_engine_manager_forces_polling(monkeypatch):
    import os
    import threading
    monkeypatch.setenv('SANDBOX_ENGINE_TYPE', 'websocket')
    tree = ast.parse((ROOT / 'sandbox/execution_thread.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'start_execution_engine')
    worker = Mock()
    upgrade = Mock()
    env = {'os': os, 'logger': Mock(), '_thread_lock': threading.Lock(), '_execution_thread': None, '_websocket_engine': None, '_current_engine_type': None, '_auto_upgrade_thread': None, '_auto_upgrade_enabled': True, 'ExecutionEngineThread': worker, '_start_gtt_maintenance': Mock(), '_start_websocket_upgrade_watcher': upgrade}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real-engine-start>', 'exec'), env)
    assert env['start_execution_engine']()[0] is True
    worker.return_value.start.assert_called_once()
    assert env['_current_engine_type'] == 'polling'
    assert env['_auto_upgrade_enabled'] is False
    upgrade.assert_not_called()
