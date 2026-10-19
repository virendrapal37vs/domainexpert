"""Real SQLite jobstore + actual scheduler/monitor removals, broker transport stubbed."""
import atexit
import importlib.util
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text
from test_flow_owner_storage import flows

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def integrated(flows,tmp_path,monkeypatch):
    # Load full production modules, not extracted function bodies. Replace only
    # the event bus so importing the order monitor registers no real subscriber.
    monkeypatch.setitem(sys.modules,'utils.event_bus',SimpleNamespace(bus=SimpleNamespace(subscribe=Mock())))
    modules=[]
    def load(short):
        name='services.'+short
        spec=importlib.util.spec_from_file_location(name,ROOT/'services'/f'{short}.py')
        module=importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules,name,module)
        spec.loader.exec_module(module)
        modules.append(module)
        return module
    sched_mod=load('flow_scheduler_service')
    price_mod=load('flow_price_monitor_service')
    order_mod=load('flow_order_update_monitor_service')
    a=flows.create_workflow('Alice',owner_username='alice')
    b=flows.create_workflow('Bob',owner_username='bob')
    engine=create_engine('sqlite:///'+str(tmp_path/'real-jobs.db'))
    scheduler=BackgroundScheduler(jobstores={'default':SQLAlchemyJobStore(engine=engine)})
    scheduler.start(paused=True)  # Never execute a callback, even if time moves.
    for wid in (a.id,b.id):
        scheduler.add_job('builtins:print','date',run_date=datetime.now(timezone.utc)+timedelta(days=365),
                          id=f'flow_workflow_{wid}',args=['synthetic-never-executed'])
    wrapper=object.__new__(sched_mod.FlowScheduler)
    wrapper._scheduler=scheduler
    monkeypatch.setattr(sched_mod,'get_flow_scheduler',lambda:wrapper)
    price=price_mod.flow_price_monitor
    order=order_mod.flow_order_update_monitor
    price._alerts={wid:price_mod.PriceAlert(wid,'BHEL','NSE','above',1,api_key=key)
                   for wid,key in [(a.id,'alice-fake-key'),(b.id,'bob-fake-key')]}
    order._watches={wid:order_mod.OrderUpdateWatch(wid,key,user_id=owner)
                    for wid,key,owner in [(a.id,'alice-fake-key','alice'),(b.id,'bob-fake-key','bob')]}
    # No price polling or inbound event delivery is started. Broker unsubscribe
    # is a stub here; its ownership behavior has separate registry-body tests.
    release=Mock()
    lock=threading.Lock()
    monkeypatch.setitem(sys.modules,'services.flow_executor_service',SimpleNamespace(
        get_workflow_lock=lambda wid:lock,release_workflow_subscriptions=release,
        has_workflow_subscriptions=lambda wid:False))
    from services.account_flow_cleanup import delete_account_workflow
    state=SimpleNamespace(db=flows,a=a.id,b=b.id,scheduler=scheduler,engine=engine,
        price=price,order=order,release=release,delete=delete_account_workflow)
    try:
        yield state
    finally:
        scheduler.shutdown(wait=True)
        engine.dispose()
        for module in modules:
            if hasattr(module,'_shutdown_at_exit'):
                atexit.unregister(module._shutdown_at_exit)
            if hasattr(module,'_WORKFLOW_POOL'):
                module._WORKFLOW_POOL.shutdown(wait=True)


def persisted_jobs(state):
    with state.engine.connect() as conn:
        return set(conn.execute(text('SELECT id FROM apscheduler_jobs')).scalars())


def test_owner_delete_removes_real_job_and_monitors_only_for_alice(integrated):
    s=integrated
    assert s.delete(s.a,'alice')[1]==200
    assert persisted_jobs(s)=={f'flow_workflow_{s.b}'}
    assert s.scheduler.get_job(f'flow_workflow_{s.a}') is None
    assert s.scheduler.get_job(f'flow_workflow_{s.b}') is not None
    assert set(s.price._alerts)==set(s.order._watches)=={s.b}
    assert s.db.get_workflow(s.a) is None
    assert s.db.get_workflow(s.b) is not None
    s.release.assert_called_once_with(s.a,owner_username='alice')


def test_wrong_account_does_not_change_persisted_jobs_or_monitors(integrated):
    s=integrated
    assert s.delete(s.b,'alice')[1]==404
    assert persisted_jobs(s)=={f'flow_workflow_{s.a}',f'flow_workflow_{s.b}'}
    assert set(s.price._alerts)==set(s.order._watches)=={s.a,s.b}
    s.release.assert_not_called()


def test_partial_failure_keeps_workflow_and_retry_completes(integrated):
    s=integrated
    s.release.side_effect=RuntimeError('synthetic unsubscribe failure')
    assert s.delete(s.a,'alice')[1]==503
    assert s.db.get_workflow(s.a) is not None
    # Actual acknowledged job/monitor removals are retained, not rolled back.
    assert persisted_jobs(s)=={f'flow_workflow_{s.b}'}
    assert set(s.price._alerts)==set(s.order._watches)=={s.b}
    s.release.side_effect=None
    assert s.delete(s.a,'alice')[1]==200
    assert s.db.get_workflow(s.b) is not None
