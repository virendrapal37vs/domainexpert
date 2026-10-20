"""Real route bodies/DB/CSRF, with outer account rollout guard still unchanged."""
from datetime import datetime
from types import SimpleNamespace
from flask import Flask,jsonify,request
from flask_wtf.csrf import CSRFProtect,generate_csrf
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function
from test_flow_engine_offline_integration import NODES,EDGES

ROUTES=[('get_webhook_info','webhook','GET'),('enable_webhook','enable','POST'),
 ('disable_webhook','disable','POST'),('regenerate_webhook','rotate','POST'),
 ('regenerate_webhook_secret_route','secret','POST'),('set_webhook_auth','auth','POST'),
 ('export_workflow','export','GET'),('replace_workflow','replace','POST')]


@pytest.fixture
def aux(flows):
    db=flows
    a=db.create_workflow('Alice',nodes=NODES,edges=EDGES,owner_username='alice').id
    b=db.create_workflow('Bob',nodes=NODES,edges=EDGES,owner_username='bob').id
    app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='synthetic-aux')
    CSRFProtect(app)
    @app.get('/csrf')
    def csrf():return {'token':generate_csrf()}
    env={'jsonify':jsonify,'request':request,'datetime':datetime,
        'logger':SimpleNamespace(warning=lambda *a:None,info=lambda *a:None),
        'get_webhook_base_url':lambda:'https://synthetic.invalid'}
    env['_flow_account_owner']=function('blueprints/flow.py','_flow_account_owner',{})
    for name,path,method in ROUTES:
        app.add_url_rule('/<int:workflow_id>/'+path,endpoint=name,
            view_func=function('blueprints/flow.py',name,env),methods=[method])
    app.add_url_rule('/import',view_func=function('blueprints/flow.py','import_workflow',env),methods=['POST'])
    app.add_url_rule('/monitor',view_func=function('blueprints/flow.py','get_monitor_status',env))
    client=app.test_client()
    with client.session_transaction() as session:session['user']='alice'
    headers={'X-CSRFToken':client.get('/csrf').json['token']}
    return SimpleNamespace(db=db,a=a,b=b,client=client,headers=headers)


@pytest.mark.parametrize('name,path,method',ROUTES)
def test_other_owner_auxiliary_routes_cannot_read_or_mutate(aux,name,path,method):
    s=aux;before=s.db.get_workflow(s.b)
    snapshot=(before.webhook_token,before.webhook_secret,before.webhook_enabled,before.webhook_auth_type,before.name)
    response=s.client.open(f'/{s.b}/{path}',method=method,headers=s.headers,
        json={'auth_type':'url','name':'stolen','nodes':NODES,'edges':EDGES,'owner_username':'bob'})
    assert response.status_code==404
    assert snapshot[0] not in response.text and snapshot[1] not in response.text
    after=s.db.get_workflow(s.b)
    assert (after.webhook_token,after.webhook_secret,after.webhook_enabled,after.webhook_auth_type,after.name)==snapshot


def test_owner_webhook_writes_and_exports_stay_scoped(aux):
    s=aux
    bob=s.db.get_workflow(s.b).webhook_secret
    assert s.client.get(f'/{s.a}/webhook').status_code==200
    assert s.client.post(f'/{s.a}/enable',headers=s.headers).status_code==200
    assert s.db.get_workflow(s.a).webhook_enabled
    original=s.db.get_workflow(s.a).webhook_secret
    assert s.client.post(f'/{s.a}/rotate',headers=s.headers).status_code==200
    assert s.db.get_workflow(s.a).webhook_secret!=original
    assert s.db.get_workflow(s.b).webhook_secret==bob
    assert s.client.post(f'/{s.a}/auth',headers=s.headers,json={'auth_type':'url'}).status_code==200
    assert s.client.post(f'/{s.a}/disable',headers=s.headers).status_code==200
    exported=s.client.get(f'/{s.a}/export').json
    assert exported['name']=='Alice'
    assert not {'api_key','webhook_secret','webhook_token','owner_username'} & exported.keys()


def test_import_ignores_body_owner_and_replace_cannot_mutate_lifecycle(aux):
    s=aux
    payload={'name':'Imported','nodes':NODES,'edges':EDGES,'owner_username':'bob',
        'is_active':True,'api_key':'untrusted','webhook_secret':'untrusted'}
    response=s.client.post('/import',headers=s.headers,json=payload)
    assert response.status_code==201
    row=s.db.get_workflow(response.json['workflow_id'])
    assert row.owner_username=='alice' and not row.is_active and row.api_key is None
    assert row.webhook_secret!='untrusted'
    response=s.client.post(f'/{s.a}/replace',headers=s.headers,json=payload)
    assert response.status_code==200
    row=s.db.get_workflow(s.a)
    assert row.owner_username=='alice' and not row.is_active and row.api_key is None
    s.db.FlowWorkflow.query.filter_by(id=s.a).update({'is_active':True});s.db.db_session.commit()
    assert s.client.post(f'/{s.a}/replace',headers=s.headers,json=payload).status_code==409


def test_get_webhook_info_does_not_initialize_missing_credentials(aux):
    s=aux
    s.db.FlowWorkflow.query.filter_by(id=s.a).update({'webhook_secret':None});s.db.db_session.commit()
    assert s.client.get(f'/{s.a}/webhook').status_code==409
    assert s.db.get_workflow(s.a).webhook_secret is None


def test_csrf_and_anonymous_requests_are_rejected(aux):
    s=aux
    assert s.client.post(f'/{s.a}/enable').status_code==400
    assert not s.db.get_workflow(s.a).webhook_enabled
    with s.client.session_transaction() as session:session.pop('user')
    assert s.client.get(f'/{s.a}/export').status_code==401
    assert s.client.post('/import',headers=s.headers,json={'name':'x'}).status_code==401


def test_database_webhook_helpers_require_explicit_owner(aux):
    s=aux
    for helper in [s.db.ensure_webhook_credentials,s.db.regenerate_webhook_token,s.db.regenerate_webhook_secret]:
        assert not helper(s.b,owner_username='alice')
        assert not helper(s.a)
    for helper in [s.db.enable_webhook,s.db.disable_webhook]:
        assert helper(s.b,owner_username='alice') is None
        with pytest.raises(ValueError):helper(s.a)


def test_shared_monitor_summary_remains_blocked(aux):
    assert aux.client.get('/monitor').status_code==503
