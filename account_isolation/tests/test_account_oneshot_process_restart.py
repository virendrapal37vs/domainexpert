"""Fresh OS processes, actual guarded graph and SQLite; fake broker only.

Abrupt os._exit calls intentionally skip Python cleanup. No app/server starts.
"""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_flow_owner_storage import flows
from test_flow_execution_owner import owned
from test_flow_engine_offline_integration import NODES, EDGES

ROOT=Path(__file__).resolve().parents[2]
CHILD=r'''
import json, os, socket, sys
from pathlib import Path
from types import SimpleNamespace

def forbidden(*args, **kwargs):
    raise AssertionError('Network transport is forbidden in restart tests')
socket.socket.connect=forbidden
wid=int(sys.argv[1]); key=sys.argv[2]; mode=sys.argv[3]; ledger=Path(sys.argv[4])
from database import flow_db
from database.account_flow_trigger_db import get_account_trigger_state
owner='alice' if key=='a-key' else 'bob'
if mode=='probe':
    print('RESULT:'+json.dumps({'state':get_account_trigger_state(wid,owner)}),flush=True)
    raise SystemExit(0)
import services.flow_openalgo_client as transport

def place_order(**kwargs):
    # A durable fake transport receipt lets the next process prove no second
    # attempt occurred, including a crash before the broker answer was saved.
    with ledger.open('a') as stream:
        stream.write(json.dumps({'owner':owner,'workflow_id':wid})+'\n')
        stream.flush(); os.fsync(stream.fileno())
    if mode=='in_transport':
        os._exit(74)
    return {'status':'success','orderid':'synthetic-order'}
transport.get_flow_client=lambda admitted: SimpleNamespace(place_order=place_order)
import services.flow_executor_service as executor
if mode=='before_graph':
    executor._execute_workflow_graph=lambda *a,**kw: os._exit(73)
result=executor.execute_workflow(wid,api_key=key,
    webhook_data={'trigger_type':'price_alert','trigger_price':150})
print('RESULT:'+json.dumps(result),flush=True)
'''


@pytest.fixture
def restart_state(owned,monkeypatch,tmp_path):
    db,auth,a,b,_=owned
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES','true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE','false')
    sys.modules.pop('database.account_flow_trigger_db',None)
    states=importlib.import_module('database.account_flow_trigger_db')
    for wid,key,owner in [(a,'a-key','alice'),(b,'b-key','bob')]:
        nodes=[{**NODES[0],'type':'priceAlert','data':{'symbol':'BHEL','exchange':'NSE',
            'condition':'greater_than','price':100,'trigger':'once'}},NODES[1]]
        db.update_workflow(wid,nodes=nodes,edges=EDGES)
        states.create_account_trigger_arm(wid,owner)
        db.activate_workflow(wid,api_key=key,owner_username=owner)
    ledger=tmp_path/'fake-receipts.jsonl'
    def child(wid,key,mode):
        result=subprocess.run([sys.executable,'-c',CHILD,str(wid),key,mode,str(ledger)],
            cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=30)
        parsed=None
        for line in result.stdout.splitlines():
            if line.startswith('RESULT:'):
                parsed=json.loads(line[len('RESULT:'):])
        return result,parsed
    def receipts():
        return [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    return db,auth,states,a,b,child,receipts


@pytest.mark.parametrize('mode,exit_code,expected_state,attempts',[
    ('before_graph',73,'claimed',0),
    ('in_transport',74,'claimed',1),
    ('complete',0,'consumed',1),
])
def test_new_process_never_replays_claimed_or_consumed_graph(restart_state,mode,exit_code,expected_state,attempts):
    db,_,states,a,b,child,receipts=restart_state
    first,result=child(a,'a-key',mode)
    assert first.returncode==exit_code, first.stderr
    if mode=='complete':
        assert result['status']=='success'
    # Fresh process observes the persisted state after abrupt or normal exit.
    probe,observed=child(a,'a-key','probe')
    assert probe.returncode==0,probe.stderr
    assert observed=={'state':expected_state}
    second,retry=child(a,'a-key','complete')
    assert second.returncode==0,second.stderr
    assert retry['code']=='FLOW_TRIGGER_NOT_ARMED'
    assert len([r for r in receipts() if r['owner']=='alice'])==attempts
    # Alice's claim cannot consume/block another account's first arm.
    other,success=child(b,'b-key','complete')
    assert other.returncode==0,other.stderr
    assert success['status']=='success'
    assert len([r for r in receipts() if r['owner']=='bob'])==1
    assert states.get_account_trigger_state(a,'alice')==expected_state


def test_unclaimed_arm_survives_process_exit_and_executes_once(restart_state):
    _,_,states,a,_,child,receipts=restart_state
    before,probe=child(a,'a-key','probe')
    assert before.returncode==0,before.stderr
    assert probe=={'state':'armed'}
    assert receipts()==[]
    run,result=child(a,'a-key','complete')
    assert run.returncode==0,run.stderr
    assert result['status']=='success'
    assert states.get_account_trigger_state(a,'alice')=='consumed'
    assert len(receipts())==1
