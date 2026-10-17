import importlib
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


@pytest.fixture
def service(monkeypatch):
    modes = {'alice': True, 'bob': True}
    monkeypatch.setitem(sys.modules, 'database.account_mode_db', SimpleNamespace(get_account_analyze_mode=lambda owner: modes[owner], set_account_analyze_mode=lambda owner, value: modes.__setitem__(owner, value)))
    monkeypatch.setitem(sys.modules, 'utils.account_mode_context', SimpleNamespace(resolve_mode_owner=lambda **kwargs: kwargs.get('username') or 'alice'))
    monkeypatch.setitem(sys.modules, 'services.analyzer_service', SimpleNamespace(mode_transition=lambda: nullcontext()))
    monkeypatch.setitem(sys.modules, 'utils.staging_mode', SimpleNamespace(staging_safe=lambda: False))
    sys.modules.pop('services.account_mode_service', None)
    svc = importlib.import_module('services.account_mode_service')
    start = Mock()
    monkeypatch.setattr(svc, 'ensure_account_sandbox', start)
    return svc, modes, start


def test_live_switch_preserves_other_account(service):
    svc, modes, start = service
    assert svc.change_account_mode(False, username='alice') is False
    assert modes == {'alice': False, 'bob': True}
    start.assert_called_once()


def test_toggle_is_scoped(service):
    svc, modes, _ = service
    assert svc.change_account_mode(toggle=True, username='bob') is False
    assert modes['alice'] is True


def test_start_failure_does_not_persist_live(service):
    svc, modes, start = service
    start.side_effect = RuntimeError('worker start failed')
    with pytest.raises(RuntimeError):
        svc.change_account_mode(False, username='alice')
    assert modes['alice'] is True


def test_staging_blocks_transition_before_start(service, monkeypatch):
    svc, modes, start = service
    monkeypatch.setitem(sys.modules, 'utils.staging_mode', SimpleNamespace(staging_safe=lambda: True))
    with pytest.raises(RuntimeError):
        svc.change_account_mode(False, username='alice')
    start.assert_not_called()
    assert modes['alice'] is True


def test_workers_start_without_stop(service, monkeypatch):
    monkeypatch.setitem(sys.modules, 'utils.staging_mode', SimpleNamespace(staging_safe=lambda: False))
    engine, scheduler, stop = Mock(return_value=(True, 'ok')), Mock(return_value=(True, 'ok')), Mock()
    monkeypatch.setitem(sys.modules, 'sandbox.execution_thread', SimpleNamespace(start_execution_engine=engine, stop_execution_engine=stop))
    monkeypatch.setitem(sys.modules, 'sandbox.squareoff_thread', SimpleNamespace(start_squareoff_scheduler=scheduler, stop_squareoff_scheduler=stop))
    sys.modules.pop('services.account_mode_service', None)
    svc = importlib.import_module('services.account_mode_service')
    svc.ensure_account_sandbox()
    engine.assert_called_once()
    scheduler.assert_called_once()
    stop.assert_not_called()
