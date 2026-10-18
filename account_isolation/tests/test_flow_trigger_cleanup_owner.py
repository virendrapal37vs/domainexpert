"""Real cleanup methods and real workflow owner lookup, fake registration stores."""
import sys
import threading
from types import SimpleNamespace, MethodType
from unittest.mock import Mock
import pytest
from test_strategy_account_guard import function
from test_flow_owner_storage import flows


@pytest.fixture
def stores(flows, monkeypatch):
    a = flows.create_workflow('Alice',owner_username='alice')
    b = flows.create_workflow('Bob',owner_username='bob')
    lookup = type('SyntheticJobLookupError',(Exception,),{})
    monkeypatch.setitem(sys.modules,'apscheduler.jobstores.base',SimpleNamespace(JobLookupError=lookup))
    env = {'logger':Mock()}
    scheduler = SimpleNamespace(scheduler=SimpleNamespace(remove_job=Mock()))
    for name in ('remove_job','remove_workflow_job'):
        setattr(scheduler,name,MethodType(function('services/flow_scheduler_service.py',name,env,cls='FlowScheduler'),scheduler))
    price = SimpleNamespace(_alerts_lock=threading.RLock(),_alerts={a.id:object(),b.id:object()},
                            _running=True,_stop_monitoring=Mock())
    price.remove = MethodType(function('services/flow_price_monitor_service.py','remove_alert',env,cls='FlowPriceMonitor'),price)
    order = SimpleNamespace(_watches_lock=threading.RLock(),_watches={a.id:object(),b.id:object()})
    order.remove = MethodType(function('services/flow_order_update_monitor_service.py','remove_watch',env,cls='FlowOrderUpdateMonitor'),order)
    return a.id,b.id,scheduler,price,order


@pytest.mark.parametrize('kind',['scheduler','price','order'])
def test_cross_account_cleanup_refused_and_other_records_preserved(stores,kind):
    a,b,s,p,o = stores
    fn = {'scheduler':s.remove_workflow_job,'price':p.remove,'order':o.remove}[kind]
    with pytest.raises(ValueError):
        fn(b,owner_username='alice')
    s.scheduler.remove_job.assert_not_called()
    assert set(p._alerts) == set(o._watches) == {a,b}


@pytest.mark.parametrize('kind',['scheduler','price','order'])
def test_missing_owner_refused(stores,kind):
    a,b,s,p,o = stores
    with pytest.raises(ValueError):
        {'scheduler':s.remove_workflow_job,'price':p.remove,'order':o.remove}[kind](a)


def test_verified_owner_removes_only_own_registration(stores):
    a,b,s,p,o = stores
    assert s.remove_workflow_job(a,owner_username='alice') is True
    s.scheduler.remove_job.assert_called_once_with(f'flow_workflow_{a}')
    assert p.remove(a,owner_username='alice') is True
    assert o.remove(a,owner_username='alice') is True
    assert set(p._alerts) == set(o._watches) == {b}
    p._stop_monitoring.assert_not_called()


@pytest.mark.parametrize('job',['other_job','flow_workflow_bad','flow_workflow_01','flow_workflow_-1'])
def test_raw_scheduler_remove_cannot_bypass_owner_gate(stores,job):
    _,_,s,_,_ = stores
    with pytest.raises(ValueError):
        s.remove_job(job,owner_username='alice')
    s.scheduler.remove_job.assert_not_called()


def test_scheduler_failure_propagates_in_strict_mode(stores):
    a,_,s,_,_ = stores
    s.scheduler.remove_job.side_effect = RuntimeError('synthetic jobstore failure')
    with pytest.raises(RuntimeError):
        s.remove_workflow_job(a,strict=True,owner_username='alice')
