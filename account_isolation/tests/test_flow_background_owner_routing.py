"""Actual background trigger entry points; fake pool-free monitor objects."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_strategy_account_guard import function


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES','false')
    allowed=Mock(return_value=False)
    monkeypatch.setitem(sys.modules,'utils.flow_execution_owner',SimpleNamespace(account_flow_trigger_allowed=allowed))
    return allowed


def test_price_trigger_validates_exact_owner_key_before_pool(boundary):
    fn=function('services/flow_price_monitor_service.py','_trigger_workflow',{},cls='FlowPriceMonitor')
    alert=SimpleNamespace(workflow_id=42,api_key='alice-key',triggered=True)
    assert fn(object(),alert,100) is None
    boundary.assert_called_once_with(42,'alice-key')
    assert alert.triggered is False


def test_order_trigger_validates_exact_owner_key_before_pool(boundary):
    fn=function('services/flow_order_update_monitor_service.py','_fire',{},cls='FlowOrderUpdateMonitor')
    watch=SimpleNamespace(workflow_id=43,api_key='bob-key',triggered=True)
    assert fn(object(),watch,object()) is None
    boundary.assert_called_once_with(43,'bob-key')
    assert watch.triggered is False


def test_schedule_passes_job_key_to_owner_boundary(boundary):
    fn=function('services/flow_scheduler_service.py','execute_workflow_scheduled',{})
    assert fn(44,api_key='job-key') is None
    boundary.assert_called_once_with(44,'job-key')


@pytest.mark.parametrize('presented,expected',[('explicit-key','explicit-key'),(None,'stored-key')])
def test_account_trigger_resolves_only_own_stored_key_and_stays_blocked(monkeypatch,presented,expected):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    import importlib
    module=importlib.import_module('utils.flow_execution_owner')
    validate=Mock(return_value='alice')
    monkeypatch.setattr(module,'validate_flow_execution_owner',validate)
    db=SimpleNamespace(get_workflow=Mock(return_value=object()),get_workflow_api_key=Mock(return_value='stored-key'),db_session=SimpleNamespace(remove=Mock()))
    import database
    monkeypatch.setattr(database,'flow_db',db,raising=False)
    assert module.account_flow_trigger_allowed(42,presented) is False
    validate.assert_called_once_with(42,expected)
    if presented:
        db.get_workflow.assert_not_called()
    db.db_session.remove.assert_called_once()


def test_invalid_trigger_credentials_stay_blocked(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    import utils.flow_execution_owner as module
    monkeypatch.setattr(module,'validate_flow_execution_owner',Mock(side_effect=ValueError('revoked')))
    assert module.account_flow_trigger_allowed(42,'revoked-key') is False
