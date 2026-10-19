"""Execute actual queued callback bodies with an immediate fake pool."""
import sys
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_strategy_account_guard import function


@pytest.mark.parametrize('kind',['price','order'])
@pytest.mark.parametrize('result,retired',[
    ({'status':'error','code':'FLOW_NODE_NOT_ACCOUNT_READY'},False),
    ({'status':'error','code':'FLOW_OWNER_AUTH_FAILED'},False),
    ({'status':'success','execution_id':123},True)])
def test_only_real_execution_record_consumes_account_oneshot(monkeypatch,kind,result,retired):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    monkeypatch.setitem(sys.modules,'utils.flow_execution_owner',SimpleNamespace(account_flow_trigger_allowed=lambda *a:True))
    execute=Mock(return_value=result)
    monkeypatch.setitem(sys.modules,'services.flow_executor_service',SimpleNamespace(execute_workflow=execute))
    monkeypatch.setitem(sys.modules,'utils.db_sessions',SimpleNamespace(remove_all_scoped_sessions=Mock()))
    item=SimpleNamespace(workflow_id=42,api_key='fake-key',trigger='once',triggered=True)
    self=SimpleNamespace(_retire_one_shot=Mock(),_workflow_is_active=lambda wid:True)
    env={'logger':Mock(),'datetime':datetime,'_WORKFLOW_POOL':SimpleNamespace(submit=lambda fn:fn())}
    if kind=='price':
        self._pending_lock=threading.Lock()
        self._pending=set()
        self._alerts={42:item}
        fn=function('services/flow_price_monitor_service.py','_trigger_workflow',env,cls='FlowPriceMonitor')
        fn(self,item,100)
        assert self._pending==set()
    else:
        self.get_watch=lambda wid:item
        event=SimpleNamespace(orderid='fake',order_status='complete',symbol='BHEL',exchange='NSE',filled_quantity=1,average_price=100)
        fn=function('services/flow_order_update_monitor_service.py','_fire',env,cls='FlowOrderUpdateMonitor')
        fn(self,item,event)
    execute.assert_called_once()
    assert self._retire_one_shot.called is retired
    if not retired:
        assert item.triggered is False
