import ast
import __future__
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[2]


def function(name, env):
    tree = ast.parse((ROOT / 'services/openscript_runner_service.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<real-openscript-function>', 'exec', flags=__future__.annotations.compiler_flag), env)
    return env[name]


@pytest.fixture
def owner_context(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'true')
    monkeypatch.setitem(sys.modules, 'database.account_broker_db', SimpleNamespace(per_user_groww_enabled=lambda: True))
    monkeypatch.setitem(sys.modules, 'database.auth_db', SimpleNamespace(verify_api_key=lambda key: {'a-key': 'alice', 'b-key': 'bob'}.get(key)))
    monkeypatch.setitem(sys.modules, 'database.user_db', SimpleNamespace(find_user_by_exact_username=lambda user: user if user in ('alice', 'bob') else None))
    monkeypatch.setitem(sys.modules, 'database.account_mode_db', SimpleNamespace(get_account_analyze_mode=lambda user: user == 'alice'))


def test_run_mode_is_owner_snapshot(owner_context):
    read = function('_analyzer_mode', {})
    assert read(user_id='alice', api_key='a-key') == 'sandbox'
    assert read(user_id='bob', api_key='b-key') == 'live'
    with pytest.raises(ValueError):
        read(user_id='alice', api_key='b-key')


@pytest.mark.parametrize('owner,key', [(None, 'a-key'), ('alice', None), ('alice', 'invalid')])
def test_missing_identity_refuses_spawn(owner_context, owner, key):
    env = {'runner_program_path': lambda: 'synthetic-runner', '_api_key_for': lambda owner: key, '_analyzer_mode': function('_analyzer_mode', {})}
    spawn = function('_spawn_claimed', env)
    assert spawn('script', 'run', 'BHEL', 'NSE', '5m', 'MIS', owner, 1, 1)[0] is False


def test_disabled_migration_refuses_spawn(owner_context, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')
    env = {'runner_program_path': lambda: 'synthetic-runner', '_api_key_for': lambda owner: 'a-key', '_analyzer_mode': function('_analyzer_mode', {})}
    spawn = function('_spawn_claimed', env)
    assert spawn('script', 'run', 'BHEL', 'NSE', '5m', 'MIS', 'alice', 1, 1)[0] is False
