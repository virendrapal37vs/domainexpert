"""Full graph engine + real DB/auth, with fake broker and explicit test-only guard bypass.

This tests composition after admission, not an enabled production account path.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned

ROOT=Path(__file__).resolve().parents[2]
NODES=[{'id':'start','type':'start','position':{'x':0,'y':0},'data':{}},
       {'id':'order','type':'placeOrder','position':{'x':100,'y':0},'data':{'symbol':'BHEL','exchange':'NSE','action':'BUY',
           'quantity':1,'product':'MIS','priceType':'MARKET'}}]
EDGES=[{'id':'edge','source':'start','target':'order'}]


@pytest.fixture
def engine(owned,monkeypatch):
    db,auth,a,b,validate=owned
    for wid in (a,b):
        db.update_workflow(wid,nodes=NODES,edges=EDGES)
    name='services.flow_executor_service'
    spec=importlib.util.spec_from_file_location(name,ROOT/'services/flow_executor_service.py')
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,name,module)
    spec.loader.exec_module(module)
    clients={key:SimpleNamespace(api_key=key,place_order=Mock(return_value={'status':'success','orderid':f'fake-{owner}'}))
             for key,owner in [('a-key','alice'),('b-key','bob')]}
    factory=Mock(side_effect=lambda key:clients[key])
    monkeypatch.setattr(module,'get_flow_client',factory)
    def offline_run(wid,key):
        validate(wid,key)  # Real fresh DB owner/key admission before the bypass.
        # Production account execution stays disabled. This narrow test context
        # bypasses that policy only after admission, with all broker clients fake.
        with monkeypatch.context() as bypass:
            import utils.strategy_account_guard as guard
            bypass.setattr(guard,'shared_strategy_disabled',lambda:False)
            return module.execute_workflow(wid,api_key=key)
    return SimpleNamespace(db=db,auth=auth,a=a,b=b,validate=validate,module=module,
                           clients=clients,factory=factory,run=offline_run)


def test_two_owned_workflows_route_keys_to_distinct_fake_brokers(engine):
    s=engine
    a=s.run(s.a,'a-key')
    b=s.run(s.b,'b-key')
    assert a['status']==b['status']=='success'
    assert [call.args[0] for call in s.factory.call_args_list]==['a-key','b-key']
    for client in s.clients.values():
        client.place_order.assert_called_once()
        assert client.place_order.call_args.kwargs['symbol']=='BHEL'
    arow=s.db.get_execution(a['execution_id'])
    brow=s.db.get_execution(b['execution_id'])
    assert arow.workflow_id==s.a and brow.workflow_id==s.b
    assert arow.status==brow.status=='completed'


def test_wrong_key_rejected_before_client_or_history_creation(engine):
    s=engine
    with pytest.raises(ValueError):
        s.run(s.a,'b-key')
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]
    assert s.db.get_workflow_executions(s.b)==[]


def test_revoked_owner_cannot_enter_engine_bob_still_runs(engine):
    s=engine
    s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
    s.auth.db_session.commit()
    with pytest.raises(ValueError):
        s.run(s.a,'a-key')
    assert s.run(s.b,'b-key')['status']=='success'
    s.clients['a-key'].place_order.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]


def test_broker_failure_is_recorded_only_under_own_workflow(engine):
    s=engine
    s.clients['a-key'].place_order.return_value={'status':'error','message':'synthetic refusal'}
    result=s.run(s.a,'a-key')
    assert result['status']=='error'
    row=s.db.get_execution(result['execution_id'])
    assert row.workflow_id==s.a and row.status=='failed'
    assert s.db.get_workflow_executions(s.b)==[]
    s.clients['b-key'].place_order.assert_not_called()


def test_production_guard_remains_enabled_after_offline_run(engine):
    s=engine
    assert s.run(s.a,'a-key')['status']=='success'
    before=s.factory.call_count
    result=s.module.execute_workflow(s.a,api_key='a-key')
    assert result['code']=='FLOW_ACCOUNT_ISOLATION_PENDING'
    assert s.factory.call_count==before
