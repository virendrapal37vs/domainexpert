import ast
import __future__
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_function(file, name, env):
    tree = ast.parse((ROOT / file).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<real-service>', 'exec', flags=__future__.annotations.compiler_flag), env)
    return env[name]


@pytest.fixture
def routing(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'true')
    from utils.account_mode_context import read_account_mode
    monkeypatch.setitem(sys.modules, 'database.auth_db', SimpleNamespace(verify_api_key=lambda key: {'a-key': 'alice', 'b-key': 'bob'}.get(key)))
    monkeypatch.setitem(sys.modules, 'database.user_db', SimpleNamespace(find_user_by_exact_username=lambda name: name if name in ('alice', 'bob') else None))
    monkeypatch.setitem(sys.modules, 'database.account_mode_db', SimpleNamespace(get_account_analyze_mode=lambda owner: owner == 'alice'))
    monkeypatch.setitem(sys.modules, 'database.settings_db', SimpleNamespace(get_analyze_mode=read_account_mode))
    sandbox = Mock(return_value=(True, {'status': 'success', 'orderid': 'fake'}, 200))
    monkeypatch.setitem(sys.modules, 'services.sandbox_service', SimpleNamespace(sandbox_place_order=sandbox, sandbox_get_orderbook=sandbox, sandbox_get_positions=sandbox))
    return sandbox


def test_background_place_order_uses_api_owner(routing):
    from utils.service_mode import service_analyze_mode
    broker = Mock(return_value=None)
    fn = load_function('services/place_order_service.py', 'place_order_with_auth', {'copy': copy, 'service_analyze_mode': service_analyze_mode, 'import_broker_module': broker, 'bus': Mock(), 'OrderFailedEvent': Mock()})
    assert fn({}, 'fake-broker-token', 'groww', {'apikey': 'a-key'}, emit_event=False)[2] == 200
    broker.assert_not_called()
    routing.assert_called_once()
    # Bob's live mode does not inherit Alice's sandbox mode.
    assert fn({}, 'fake-broker-token', 'groww', {'apikey': 'b-key'}, emit_event=False)[2] == 404
    broker.assert_called_once_with('groww')


@pytest.mark.parametrize('file,name', [('services/orderbook_service.py', 'get_orderbook_with_auth'), ('services/positionbook_service.py', 'get_positionbook_with_auth')])
def test_background_books_use_api_owner(routing, file, name):
    broker = Mock(return_value=None)
    fn = load_function(file, name, {'import_broker_module': broker, 'logger': Mock()})
    assert fn('fake-token', 'groww', {'apikey': 'a-key'})[2] == 200
    broker.assert_not_called()
    assert fn('fake-token', 'groww', {'apikey': 'b-key'})[2] == 404
    broker.assert_called_once_with('groww')


def test_unknown_api_owner_never_reaches_broker(routing):
    from utils.service_mode import service_analyze_mode
    broker = Mock()
    fn = load_function('services/place_order_service.py', 'place_order_with_auth', {'copy': copy, 'service_analyze_mode': service_analyze_mode, 'import_broker_module': broker})
    with pytest.raises(ValueError):
        fn({}, 'fake-token', 'groww', {'apikey': 'invalid'}, emit_event=False)
    broker.assert_not_called()
    routing.assert_not_called()
