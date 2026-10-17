"""Execute real service bodies up to the mode gate; no broker operations."""
import ast
import __future__
import copy
from pathlib import Path
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = [
 ('modify_order_service.py', 'modify_order_with_auth', {}),
 ('cancel_order_service.py', 'cancel_order_with_auth', 'fake-order'),
 ('cancel_all_order_service.py', 'cancel_all_orders_with_auth', {}),
 ('close_position_service.py', 'close_position_with_auth', {}),
 ('place_gtt_order_service.py', 'place_gtt_order_with_auth', {}),
 ('modify_gtt_order_service.py', 'modify_gtt_order_with_auth', {}),
 ('cancel_gtt_order_service.py', 'cancel_gtt_order_with_auth', 'fake-trigger'),
 ('place_smart_order_service.py', 'place_smart_order_with_auth', {}),
]


class ModeGateReached(Exception):
    pass


@pytest.mark.parametrize('file,name,data', CASES)
def test_real_services_propagate_background_key(file, name, data):
    tree = ast.parse((ROOT / 'services' / file).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    mode = Mock(side_effect=ModeGateReached)
    env = {'copy': copy, 'service_analyze_mode': mode, 'logger': Mock(), 'validate_smart_order': lambda data: (True, None), 'validate_gtt_order': lambda *a, **kw: (True, None)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<real-service>', 'exec', flags=__future__.annotations.compiler_flag), env)
    try:
        env[name](data, 'synthetic-token', 'groww', {'apikey': 'bob-key'})
    except ModeGateReached:
        pass
    mode.assert_called_once_with(api_key='bob-key')
