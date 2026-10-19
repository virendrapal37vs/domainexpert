"""Enabled internal account path, full graph engine and SQLite/auth, fake broker only."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_flow_engine_offline_integration import NODES,EDGES

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def runnable(owned,monkeypatch):
    db,auth,a,b,_=owned
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES','true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE','false')
    for wid in (a,b):
        db.update_workflow(wid,nodes=NODES,edges=EDGES)
    name='services.flow_executor_service'
    spec=importlib.util.spec_from_file_location(name,ROOT/'services/flow_executor_service.py')
    engine=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,name,engine)
    spec.loader.exec_module(engine)
    clients={key:SimpleNamespace(place_order=Mock(return_value={'status':'success','orderid':f'fake-{owner}'}))
        for key,owner in [('a-key','alice'),('b-key','bob')]}
    factory=Mock(side_effect=lambda key:clients[key])
    import services.flow_openalgo_client as transport
    monkeypatch.setattr(transport,'get_flow_client',factory)
    return SimpleNamespace(db=db,auth=auth,a=a,b=b,engine=engine,clients=clients,factory=factory)


def test_actual_account_entry_routes_two_keys_without_guard_bypass(runnable):
    s=runnable
    for wid,key in [(s.a,'a-key'),(s.b,'b-key')]:
        result=s.engine.execute_workflow(wid,api_key=key)
        assert result['status']=='success'
        assert s.db.get_execution(result['execution_id']).workflow_id==wid
        s.clients[key].place_order.assert_called_once()


def test_other_account_key_rejected_before_broker_or_execution_row(runnable):
    s=runnable
    assert s.engine.execute_workflow(s.a,api_key='b-key')['code']=='FLOW_OWNER_AUTH_FAILED'
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]


@pytest.mark.parametrize('flag,value',[('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','false'),
    ('DOMAINXPERT_ACCOUNT_MODES','false'),('DOMAINXPERT_STAGING_SAFE','true')])
def test_policy_default_off_modes_and_staging_all_block(runnable,monkeypatch,flag,value):
    s=runnable
    monkeypatch.setenv(flag,value)
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_ACCOUNT_ISOLATION_PENDING'
    s.factory.assert_not_called()


def test_unsupported_node_rejected_before_history_or_broker(runnable):
    s=runnable
    s.db.update_workflow(s.a,nodes=[{'id':'start','type':'start'},{'id':'x','type':'delay'}])
    assert s.engine.execute_workflow(s.a,api_key='a-key')['code']=='FLOW_NODE_NOT_ACCOUNT_READY'
    s.factory.assert_not_called()
    assert s.db.get_workflow_executions(s.a)==[]


def test_revocation_between_order_nodes_blocks_second_order(runnable):
    s=runnable
    nodes=[*NODES,{'id':'second','type':'placeOrder','position':{'x':200,'y':0},'data':dict(NODES[1]['data'])}]
    edges=[*EDGES,{'id':'second-edge','source':'order','target':'second'}]
    s.db.update_workflow(s.a,nodes=nodes,edges=edges)
    def first(**kwargs):
        s.auth.Auth.query.filter_by(name='alice').update({'is_revoked':True})
        s.auth.db_session.commit()
        return {'status':'success','orderid':'fake-first'}
    s.clients['a-key'].place_order.side_effect=first
    result=s.engine.execute_workflow(s.a,api_key='a-key')
    assert result['status']=='error'
    assert s.clients['a-key'].place_order.call_count==1
    assert s.db.get_execution(result['execution_id']).status=='failed'
    assert s.engine.execute_workflow(s.b,api_key='b-key')['status']=='success'


def test_policy_disabled_between_nodes_blocks_second_call(runnable,monkeypatch):
    s=runnable
    nodes=[*NODES,{'id':'second','type':'placeOrder','position':{'x':200,'y':0},'data':dict(NODES[1]['data'])}]
    s.db.update_workflow(s.a,nodes=nodes,edges=[*EDGES,{'id':'second-edge','source':'order','target':'second'}])
    def first(**kwargs):
        monkeypatch.setenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','false')
        return {'status':'success','orderid':'fake-first'}
    s.clients['a-key'].place_order.side_effect=first
    assert s.engine.execute_workflow(s.a,api_key='a-key')['status']=='error'
    assert s.clients['a-key'].place_order.call_count==1
