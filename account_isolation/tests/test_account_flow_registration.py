"""Real scheduler registration with paused jobstore; monitor calls stubbed."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_flow_cleanup_integration import integrated


def test_owned_schedule_registers_without_global_key(integrated,owned):
    _,_,a,_,_=owned
    state=integrated
    from services.account_flow_activation import register_account_trigger
    row=state.db.get_workflow(a)
    register_account_trigger(row,{'type':'start','data':{'scheduleType':'once',
        'executeAt':(datetime.now(timezone.utc)+timedelta(days=365)).isoformat()}},'alice','a-key')
    job=state.scheduler.get_job(f'flow_workflow_{a}')
    assert job is not None
    assert 'a-key' not in repr(job.args)+repr(job.kwargs)
    assert state.db.get_workflow(a).schedule_job_id==job.id


@pytest.mark.parametrize('kind,method',[('priceAlert','add_alert'),('orderUpdateTrigger','add_watch')])
def test_monitor_registration_passes_exact_key_and_order_owner(owned,monkeypatch,kind,method):
    db,_,a,_,_=owned
    monitor=SimpleNamespace(**{method:Mock(return_value=True)})
    module='services.flow_price_monitor_service' if kind=='priceAlert' else 'services.flow_order_update_monitor_service'
    factory='get_flow_price_monitor' if kind=='priceAlert' else 'get_flow_order_update_monitor'
    monkeypatch.setitem(sys.modules,module,SimpleNamespace(**{factory:lambda:monitor}))
    from services.account_flow_activation import register_account_trigger
    register_account_trigger(db.get_workflow(a),{'type':kind,'data':{'symbol':'BHEL','price':100,'trigger':'every_time'}},'alice','a-key')
    kwargs=getattr(monitor,method).call_args.kwargs
    assert kwargs['workflow_id']==a and kwargs['api_key']=='a-key'
    if kind=='orderUpdateTrigger':
        assert kwargs['user_id']=='alice'
