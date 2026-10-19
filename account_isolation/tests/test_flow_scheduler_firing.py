"""Real APScheduler worker/timer and SQLite jobstore -> guarded engine, fake broker."""
import importlib.util
import sys
import threading
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from apscheduler.events import EVENT_JOB_EXECUTED,EVENT_JOB_ERROR
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_account_flow_execution import runnable

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def timer(runnable,tmp_path,monkeypatch):
    state=runnable
    name='services.flow_scheduler_service'
    spec=importlib.util.spec_from_file_location(name,ROOT/'services/flow_scheduler_service.py')
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,name,module)
    spec.loader.exec_module(module)
    scheduler=BackgroundScheduler(jobstores={'default':SQLAlchemyJobStore(
        url='sqlite:///'+str(tmp_path/'firing-jobs.db'))},timezone='UTC')
    events=[]
    finished=threading.Event()
    event_lock=threading.Lock()
    def listener(event):
        with event_lock:
            events.append(event)
            if len(events)==2:
                finished.set()
    scheduler.add_listener(listener,EVENT_JOB_EXECUTED|EVENT_JOB_ERROR)
    scheduler.start(paused=True)
    for wid,key,owner in [(state.a,'a-key','alice'),(state.b,'b-key','bob')]:
        state.db.activate_workflow(wid,api_key=key,owner_username=owner)
        job=scheduler.add_job(module.execute_workflow_scheduled,'date',
            run_date=datetime.now(timezone.utc)+timedelta(milliseconds=200),
            id=f'flow_workflow_{wid}',kwargs={'workflow_id':wid,'api_key':None,
                                            'market_hours_only':False},misfire_grace_time=30)
        assert job.kwargs['api_key'] is None
    try:
        yield SimpleNamespace(state=state,scheduler=scheduler,events=events,finished=finished)
    finally:
        scheduler.shutdown(wait=True)


def fire_and_wait(timer):
    timer.scheduler.resume()
    assert timer.finished.wait(timeout=15),'Real scheduled callbacks did not finish in time'
    assert all(event.exception is None for event in timer.events)
    assert len(timer.events)==2


def test_real_timer_fires_two_owners_through_guarded_engine(timer):
    s=timer.state
    fire_and_wait(timer)
    for wid,key in [(s.a,'a-key'),(s.b,'b-key')]:
        s.clients[key].place_order.assert_called_once()
        rows=s.db.get_workflow_executions(wid)
        assert len(rows)==1 and rows[0].workflow_id==wid and rows[0].status=='completed'


def test_revoked_account_skipped_by_real_timer_other_account_runs(timer):
    s=timer.state
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    s.auth.db_session.commit()
    fire_and_wait(timer)
    s.clients['a-key'].place_order.assert_not_called()
    s.clients['b-key'].place_order.assert_called_once()
    assert s.db.get_workflow_executions(s.a)==[]
    assert s.db.get_workflow_executions(s.b)[0].status=='completed'


def test_staging_policy_blocks_real_firing_jobs(timer,monkeypatch):
    s=timer.state
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE','true')
    fire_and_wait(timer)
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]
    assert s.db.get_workflow_executions(s.b)==[]
