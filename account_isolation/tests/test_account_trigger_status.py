"""Real detail route body and SQLite; outer Flow rollout guard stays enabled."""
import importlib
import sys
from types import SimpleNamespace
from flask import Flask, jsonify
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function


@pytest.fixture
def status_detail(flows):
    db=flows
    sys.modules.pop('database.account_flow_trigger_db',None)
    claims=importlib.import_module('database.account_flow_trigger_db')
    nodes=[{'id':'root','type':'priceAlert','data':{'trigger':'once'}}]
    a=db.create_workflow('Alice',nodes=nodes,owner_username='alice').id
    b=db.create_workflow('Bob',nodes=nodes,owner_username='bob').id
    legacy=db.FlowWorkflow(name='Legacy',nodes=nodes)
    db.db_session.add(legacy);db.db_session.commit()
    app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='synthetic-status')
    env={'jsonify':jsonify,'_flow_account_owner':function('blueprints/flow.py','_flow_account_owner',{})}
    app.add_url_rule('/detail/<int:workflow_id>',view_func=function('blueprints/flow.py','get_workflow',env))
    client=app.test_client()
    with client.session_transaction() as session:
        session['user']='alice'
    return SimpleNamespace(db=db,claims=claims,a=a,b=b,legacy=legacy.id,client=client)


@pytest.mark.parametrize('state',['unarmed','armed','claimed','consumed'])
def test_detail_status_is_read_only_and_hides_activation_identity(status_detail,state):
    s=status_detail;token=None
    if state!='unarmed':
        token=s.claims.create_account_trigger_arm(s.a,'alice')
    if state in ('claimed','consumed'):
        assert s.claims.claim_account_trigger(s.a,'alice',token)
    if state=='consumed':
        assert s.claims.consume_account_trigger(s.a,'alice',token)
    before=s.claims.get_account_trigger_state(s.a,'alice')
    response=s.client.get(f'/detail/{s.a}')
    assert response.status_code==200
    value=response.json['one_shot_status']
    assert value['state']==state
    assert set(value)=={'state','label','message','review'}
    assert value['review'] is None
    assert 'activation_id' not in response.text
    if token:
        assert token not in response.text
    assert s.claims.get_account_trigger_state(s.a,'alice')==before
    if state=='claimed':
        assert 'may still be running' in value['message'] and 'Automatic retry is blocked' in value['message']


@pytest.mark.parametrize('target',['b','legacy'])
def test_other_owner_status_is_not_disclosed(status_detail,target):
    s=status_detail
    s.claims.create_account_trigger_arm(s.b,'bob')
    response=s.client.get(f'/detail/{getattr(s,target)}?owner_username=bob')
    assert response.status_code==404
    assert 'one_shot_status' not in response.text


def test_anonymous_status_is_rejected(status_detail):
    s=status_detail
    with s.client.session_transaction() as session:
        session.clear()
    assert s.client.get(f'/detail/{s.a}').status_code==401


def test_every_time_workflow_has_no_one_shot_status(status_detail):
    s=status_detail
    s.db.update_workflow(s.a,nodes=[{'id':'root','type':'priceAlert','data':{'trigger':'every_time'}}])
    assert s.client.get(f'/detail/{s.a}').json['one_shot_status'] is None
