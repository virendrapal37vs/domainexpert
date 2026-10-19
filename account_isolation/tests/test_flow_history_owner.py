"""History/log query ownership with real SQLite and real HTTP route bodies."""
from types import SimpleNamespace
from flask import Flask,jsonify,request
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function


@pytest.fixture
def history(flows):
    db=flows
    a=db.create_workflow('Alice',owner_username='alice')
    b=db.create_workflow('Bob',owner_username='bob')
    legacy=db.FlowWorkflow(name='Legacy')
    db.db_session.add(legacy)
    db.db_session.commit()
    rows=[]
    for wf,marker in [(a,'alice-only-log'),(b,'bob-only-log'),(legacy,'legacy-private-log')]:
        row=db.create_execution(wf.id,status='completed')
        db.update_execution_status(row.id,'completed',logs=[{'message':marker}])
        rows.append(row.id)
    app=Flask(__name__)
    app.config.update(TESTING=True,SECRET_KEY='history-tests-only')
    env={'jsonify':jsonify,'request':request,'EXECUTIONS_DEFAULT_LIMIT':20,'EXECUTIONS_MAX_LIMIT':200}
    env['_flow_account_owner']=function('blueprints/flow.py','_flow_account_owner',{})
    app.add_url_rule('/history/<int:workflow_id>',view_func=function('blueprints/flow.py','get_workflow_executions',env))
    client=app.test_client()
    with client.session_transaction() as session:
        session['user']='alice'
    return SimpleNamespace(db=db,a=a.id,b=b.id,legacy=legacy.id,rows=rows,client=client)


def test_http_returns_only_own_history_and_logs(history):
    s=history
    response=s.client.get(f'/history/{s.a}')
    assert response.status_code==200
    assert [row['workflow_id'] for row in response.json]==[s.a]
    assert 'alice-only-log' in response.text
    assert 'bob-only-log' not in response.text


@pytest.mark.parametrize('target',['b','legacy'])
def test_other_and_ownerless_workflow_history_hidden(history,target):
    s=history
    response=s.client.get(f'/history/{getattr(s,target)}?username=bob&owner_username=bob')
    assert response.status_code==404
    assert 'only-log' not in response.text and 'private-log' not in response.text


def test_execution_id_lookup_is_owner_filtered(history):
    s=history
    assert s.db.get_account_execution(s.rows[0],'alice').workflow_id==s.a
    assert s.db.get_account_execution(s.rows[1],'alice') is None
    assert s.db.get_account_execution(s.rows[2],'alice') is None
    assert s.db.get_account_workflow_executions(s.b,'alice')==[]


def test_anonymous_history_rejected(history):
    s=history
    with s.client.session_transaction() as session:
        session.pop('user')
    assert s.client.get(f'/history/{s.a}').status_code==401


def test_limit_and_unknown_owner_cannot_escape_filter(history):
    s=history
    for _ in range(3):
        s.db.create_execution(s.a,status='completed')
    assert len(s.client.get(f'/history/{s.a}?limit=1').json)==1
    assert len(s.db.get_account_workflow_executions(s.a,'alice',limit=-1))==1
    with pytest.raises(ValueError):
        s.db.get_account_execution(s.rows[0],'missing')
