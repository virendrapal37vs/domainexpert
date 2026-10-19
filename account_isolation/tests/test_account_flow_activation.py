"""Activation service + real owner/auth DB; registration mocked, no triggers run."""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_flow_engine_offline_integration import NODES, EDGES


@pytest.fixture
def activation(owned,monkeypatch):
    db,auth,a,b,_=owned
    for wid in (a,b):
        db.update_workflow(wid,nodes=NODES,edges=EDGES)
    lock=threading.Lock()
    monkeypatch.setitem(sys.modules,'services.flow_executor_service',SimpleNamespace(get_workflow_lock=lambda wid:lock))
    import services.account_flow_activation as module
    cleanup=Mock()
    register=Mock()
    monkeypatch.setattr(module,'remove_account_triggers',cleanup)
    monkeypatch.setattr(module,'register_account_trigger',register)
    return SimpleNamespace(db=db,auth=auth,a=a,b=b,lock=lock,cleanup=cleanup,register=register,module=module)


def test_success_persists_before_registering_exact_owner(activation):
    s=activation
    def registered(wf,trigger,owner,key):
        assert s.db.get_workflow(s.a).is_active
        assert owner=='alice' and key=='a-key'
    s.register.side_effect=registered
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==200
    assert s.db.get_workflow(s.a).is_active
    assert not s.db.get_workflow(s.b).is_active
    s.cleanup.assert_called_once_with(s.a,'alice')
    assert not s.lock.locked()


@pytest.mark.parametrize('owner,key,status',[('alice','b-key',403),('bob','b-key',404)])
def test_cross_owner_activation_has_no_mutation(activation,owner,key,status):
    s=activation
    assert s.module.activate_account_workflow(s.a,owner,key)[1]==status
    assert not s.db.get_workflow(s.a).is_active
    s.cleanup.assert_not_called()
    s.register.assert_not_called()


def test_registration_failure_rolls_back_only_owner(activation):
    s=activation
    s.register.side_effect=RuntimeError('synthetic failure')
    result,status=s.module.activate_account_workflow(s.a,'alice','a-key')
    assert status==503 and result['cleanup_pending'] is False
    assert not s.db.get_workflow(s.a).is_active
    assert not s.db.get_workflow(s.b).is_active
    assert s.cleanup.call_count==2
    assert not s.lock.locked()


def test_rollback_cleanup_failure_retains_credentials_for_retry(activation):
    s=activation
    s.register.side_effect=RuntimeError('registration failed')
    s.cleanup.side_effect=[None,RuntimeError('cleanup failed')]
    result,status=s.module.activate_account_workflow(s.a,'alice','a-key')
    assert status==503 and result['cleanup_pending'] is True
    row=s.db.get_workflow(s.a)
    assert not row.is_active
    assert s.db.get_workflow_api_key(row)=='a-key'


def test_stale_cleanup_failure_does_not_activate(activation):
    s=activation
    s.cleanup.side_effect=RuntimeError('stale jobstore failed')
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==503
    assert not s.db.get_workflow(s.a).is_active
    s.register.assert_not_called()


def test_busy_workflow_lock_blocks_activation(activation):
    s=activation
    s.lock.acquire()
    assert s.module.activate_account_workflow(s.a,'alice','a-key')[1]==409
    s.lock.release()
    s.register.assert_not_called()


def test_rollback_persistence_failure_reports_repair_needed(activation,monkeypatch):
    s=activation
    s.register.side_effect=RuntimeError('registration failed')
    monkeypatch.setattr(s.db,'deactivate_workflow',Mock(return_value=None))
    result,status=s.module.activate_account_workflow(s.a,'alice','a-key')
    assert status==503 and result['cleanup_pending'] is True
    assert not s.lock.locked()
