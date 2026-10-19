"""Full production monitors/worker pool -> guarded graph, synthetic data/broker."""
import atexit
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_account_flow_execution import runnable
from test_flow_engine_offline_integration import NODES,EDGES

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def monitors(runnable,monkeypatch):
    s=runnable
    monkeypatch.setitem(sys.modules,'utils.event_bus',SimpleNamespace(bus=SimpleNamespace(subscribe=Mock())))
    modules=[]
    for short in ('flow_price_monitor_service','flow_order_update_monitor_service'):
        name='services.'+short
        spec=importlib.util.spec_from_file_location(name,ROOT/'services'/f'{short}.py')
        module=importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules,name,module)
        spec.loader.exec_module(module)
        module._WORKFLOW_POOL.shutdown(wait=True)
        module._WORKFLOW_POOL=ThreadPoolExecutor(max_workers=1)
        modules.append(module)
    price,order=modules
    for key in ('a-key','b-key'):
        s.clients[key].get_quotes=Mock(return_value={'status':'success','data':{'ltp':150}})
    def arm(kind):
        for wid,key,owner in [(s.a,'a-key','alice'),(s.b,'b-key','bob')]:
            data={'symbol':'BHEL','exchange':'NSE','condition':'greater_than','price':100,
                  'status':'complete','trigger':'every_time'}
            nodes=[{**NODES[0],'type':kind,'data':data},NODES[1]]
            s.db.update_workflow(wid,nodes=nodes,edges=EDGES)
            s.db.activate_workflow(wid,api_key=key,owner_username=owner)
        if kind=='priceAlert':
            price.flow_price_monitor._alerts={wid:price.PriceAlert(wid,'BHEL','NSE','greater_than',100,
                api_key=key,trigger='every_time') for wid,key in [(s.a,'a-key'),(s.b,'b-key')]}
        else:
            order.flow_order_update_monitor._watches={wid:order.OrderUpdateWatch(wid,key,symbol='BHEL',exchange='NSE',
                user_id=owner,trigger='every_time') for wid,key,owner in [(s.a,'a-key','alice'),(s.b,'b-key','bob')]}
    def drain(module):
        module._WORKFLOW_POOL.submit(lambda:None).result(timeout=15)
    try:
        yield SimpleNamespace(s=s,price=price,order=order,arm=arm,drain=drain)
    finally:
        for module in modules:
            atexit.unregister(module._shutdown_at_exit)
            module._WORKFLOW_POOL.shutdown(wait=True)


def event(owner):
    return SimpleNamespace(orderid='synthetic-fill',order_status='complete',symbol='BHEL',exchange='NSE',
        filled_quantity=1,average_price=150,request_data={'user_id':owner} if owner else {})


def test_price_poll_uses_owner_key_and_actual_pool_executes_own_graph(monitors):
    m=monitors;s=m.s
    m.arm('priceAlert')
    m.price.flow_price_monitor._check_alert(m.price.flow_price_monitor._alerts[s.a])
    m.drain(m.price)
    s.clients['a-key'].get_quotes.assert_called_once_with(symbol='BHEL',exchange='NSE')
    s.clients['a-key'].place_order.assert_called_once()
    s.clients['b-key'].get_quotes.assert_not_called()
    s.clients['b-key'].place_order.assert_not_called()
    assert s.db.get_workflow_executions(s.a)[0].status=='completed'
    assert not m.price.flow_price_monitor._alerts[s.a].triggered


def test_revoked_price_owner_is_blocked_before_quote_transport(monitors):
    m=monitors;s=m.s
    m.arm('priceAlert')
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    s.auth.db_session.commit()
    m.price.flow_price_monitor._check_alert(m.price.flow_price_monitor._alerts[s.a])
    s.clients['a-key'].get_quotes.assert_not_called()
    s.clients['a-key'].place_order.assert_not_called()


def test_order_event_only_fires_matching_verified_account(monitors):
    m=monitors;s=m.s
    m.arm('orderUpdateTrigger')
    m.order.flow_order_update_monitor._on_order_update(event('alice'))
    m.drain(m.order)
    s.clients['a-key'].place_order.assert_called_once()
    s.clients['b-key'].place_order.assert_not_called()
    assert s.db.get_workflow_executions(s.a)[0].status=='completed'
    assert not m.order.flow_order_update_monitor._watches[s.a].triggered


@pytest.mark.parametrize('case',['missing_event_owner','wrong_watch_owner'])
def test_unverified_order_identity_cannot_fire(monitors,case):
    m=monitors;s=m.s
    m.arm('orderUpdateTrigger')
    monitor=m.order.flow_order_update_monitor
    if case=='wrong_watch_owner':
        monitor._watches={s.a:monitor._watches[s.a]}
        monitor._watches[s.a].user_id='bob'
    monitor._on_order_update(event(None if case=='missing_event_owner' else 'bob'))
    m.drain(m.order)
    s.clients['a-key'].place_order.assert_not_called()
    s.clients['b-key'].place_order.assert_not_called()


def test_oneshot_account_trigger_remains_explicitly_unsupported(monitors):
    m=monitors;s=m.s
    m.arm('priceAlert')
    wf=s.db.get_workflow(s.a)
    nodes=[{**wf.nodes[0],'data':{**wf.nodes[0]['data'],'trigger':'once'}},wf.nodes[1]]
    s.db.update_workflow(s.a,nodes=nodes)
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_NODE_NOT_ACCOUNT_READY'
    s.clients['a-key'].place_order.assert_not_called()
