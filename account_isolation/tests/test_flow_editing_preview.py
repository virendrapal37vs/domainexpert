"""Real stacked staging/Flow gates, session wrapper, CSRF and SQLite CRUD."""
from types import SimpleNamespace
from flask import Flask,Blueprint,jsonify,request
from flask_wtf.csrf import CSRFProtect,generate_csrf
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function
from utils.staging_mode import install_staging_gate,install_staging_socket_gate
from utils.flow_editing_preview import editing_preview_enabled,flow_session_required


@pytest.fixture
def preview(flows,monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE','true')
    monkeypatch.setenv('DOMAINXPERT_FLOW_EDITING_PREVIEW','true')
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW','true')
    # Even accidental execution flags must not bypass restricted staging.
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES','true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_FLOW_EXECUTION','true')
    app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='synthetic-preview')
    CSRFProtect(app)
    install_staging_gate(app);install_staging_socket_gate(app)
    app.add_url_rule('/csrf',endpoint='auth.get_csrf_token',view_func=lambda:jsonify(token=generate_csrf()))
    bp=Blueprint('flow',__name__)
    env={'jsonify':jsonify,'request':request,'logger':SimpleNamespace(warning=lambda *a:None)}
    env['_flow_account_owner']=function('blueprints/flow.py','_flow_account_owner',{})
    env['_existing_for_trigger_check']=function('blueprints/flow.py','_existing_for_trigger_check',{})
    bp.before_request(function('blueprints/flow.py','require_account_safe_flow',env))
    for name,path,method in [('list_workflows','/flows','GET'),('create_workflow','/flows','POST'),
        ('get_workflow','/flows/<int:workflow_id>','GET'),('update_workflow','/flows/<int:workflow_id>','PUT')]:
        view=flow_session_required(function('blueprints/flow.py',name,env))
        bp.add_url_rule(path,endpoint=name,view_func=view,methods=[method])
    for name in ['activate_workflow','deactivate_workflow','execute_workflow_now','trigger_webhook','enable_webhook','delete_workflow','get_monitor_status']:
        bp.add_url_rule('/blocked/'+name,endpoint=name,view_func=lambda:pytest.fail('Execution handler reached'),methods=['GET','POST'])
    app.register_blueprint(bp)
    app.add_url_rule('/flow',endpoint='react.react_flow_index',view_func=lambda:'shell')
    app.add_url_rule('/trade',endpoint='orders.place',view_func=lambda:pytest.fail('Trading handler reached'),methods=['POST'])
    client=app.test_client()
    with client.session_transaction() as session:
        session['user']='alice'  # Password account, deliberately no logged_in/broker flag.
    headers={'X-CSRFToken':client.get('/csrf').json['token']}
    return SimpleNamespace(client=client,headers=headers,db=flows)


def test_password_account_can_create_edit_only_its_workflows(preview):
    s=preview
    assert s.client.get('/flow').status_code==200
    response=s.client.post('/flows',json={'name':'Preview','owner_username':'bob'},headers=s.headers)
    assert response.status_code==201
    wid=response.json['id']
    assert s.db.get_workflow(wid).owner_username=='alice'
    assert s.client.put(f'/flows/{wid}',json={'name':'Edited'},headers=s.headers).status_code==200
    assert s.client.get(f'/flows/{wid}').json['name']=='Edited'
    b=s.db.create_workflow('Bob',owner_username='bob')
    assert s.client.get(f'/flows/{b.id}').status_code==404
    assert [row['id'] for row in s.client.get('/flows').json]==[wid]
    assert s.client.put(f'/flows/{b.id}',json={'name':'stolen'},headers=s.headers).status_code==404


@pytest.mark.parametrize('endpoint',['activate_workflow','deactivate_workflow','execute_workflow_now','trigger_webhook','enable_webhook','delete_workflow','get_monitor_status'])
def test_execution_and_unreviewed_paths_are_blocked_before_handlers(preview,endpoint):
    s=preview
    assert s.client.post('/blocked/'+endpoint,headers=s.headers).status_code==403
    from services.account_flow_execution import account_flow_execution_enabled
    assert not account_flow_execution_enabled()


def test_broker_transport_and_csrf_are_still_blocked(preview):
    s=preview
    assert s.client.post('/trade',headers=s.headers).status_code==403
    assert s.client.get('/socket.io/?transport=polling').status_code==403
    assert s.client.get('/ws').status_code==403
    assert s.client.post('/flows',json={'name':'No CSRF'}).status_code==400
    assert s.db.get_all_workflows()==[]


def test_anonymous_preview_rejected(preview):
    with preview.client.session_transaction() as session:session.clear()
    assert preview.client.get('/flow').status_code==401
    assert preview.client.get('/flows').status_code==401


@pytest.mark.parametrize('flag',['DOMAINXPERT_FLOW_EDITING_PREVIEW','DOMAINXPERT_STAGING_SAFE','DOMAINXPERT_PER_USER_GROWW'])
def test_preview_needs_all_three_flags(preview,monkeypatch,flag):
    monkeypatch.setenv(flag,'false')
    assert not editing_preview_enabled()
    # Staging off still leaves the general per-account Flow guard blocking APIs.
    assert preview.client.get('/flows').status_code in (403,503)
