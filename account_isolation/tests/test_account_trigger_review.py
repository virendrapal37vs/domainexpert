"""Owner observations never release durable claims; HTTP body/CSRF/SQLite."""
from types import SimpleNamespace
from flask import Flask, jsonify, request
from flask_wtf.csrf import CSRFProtect, generate_csrf
import pytest
from test_flow_owner_storage import flows
from test_strategy_account_guard import function


@pytest.fixture
def reviews(flows):
    db=flows
    from database import account_flow_trigger_db as claims
    from database.account_flow_review_db import get_account_trigger_review
    nodes=[{'id':'root','type':'priceAlert','data':{'trigger':'once'}}]
    a=db.create_workflow('Alice',nodes=nodes,owner_username='alice').id
    b=db.create_workflow('Bob',nodes=nodes,owner_username='bob').id
    tokens={}
    for wid,owner in [(a,'alice'),(b,'bob')]:
        tokens[wid]=claims.create_account_trigger_arm(wid,owner)
        claims.claim_account_trigger(wid,owner,tokens[wid])
    app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='synthetic-review')
    CSRFProtect(app)
    @app.get('/csrf')
    def csrf(): return jsonify({'token':generate_csrf()})
    env={'jsonify':jsonify,'request':request,'_flow_account_owner':function('blueprints/flow.py','_flow_account_owner',{})}
    app.add_url_rule('/review/<int:workflow_id>',view_func=function('blueprints/flow.py','record_trigger_review',env),methods=['POST'])
    client=app.test_client()
    with client.session_transaction() as session: session['user']='alice'
    token=client.get('/csrf').json['token']
    def post(wid,body,csrf=True):
        return client.post(f'/review/{wid}',json=body,headers={'X-CSRFToken':token} if csrf else {})
    return SimpleNamespace(db=db,claims=claims,a=a,b=b,post=post,client=client,read=get_account_trigger_review,tokens=tokens)


@pytest.mark.parametrize('observation',['order_seen','no_order_seen','uncertain'])
def test_owner_review_never_changes_claim_or_exposes_arm(reviews,observation):
    s=reviews
    response=s.post(s.a,{'observation':observation,'owner_username':'bob','state':'armed'})
    assert response.status_code==200
    assert response.json['review']['observation']==observation
    assert s.claims.get_account_trigger_state(s.a,'alice')=='claimed'
    assert s.read(s.b,'bob') is None
    assert s.tokens[s.a] not in response.text and 'activation_id' not in response.text
    assert not s.claims.claim_account_trigger(s.a,'alice',s.tokens[s.a])


def test_review_is_immutable_and_other_owner_cannot_write(reviews):
    s=reviews
    assert s.post(s.a,{'observation':'uncertain'}).status_code==200
    assert s.post(s.a,{'observation':'order_seen'}).json['review']['observation']=='uncertain'
    assert s.post(s.b,{'observation':'order_seen'}).status_code==404
    assert s.read(s.b,'bob') is None
    assert s.read(s.a,'bob') is None


@pytest.mark.parametrize('case',['active','armed','invalid','no_csrf','anonymous'])
def test_invalid_or_unprotected_review_has_no_mutation(reviews,case):
    s=reviews
    body={'observation':'uncertain'}
    expected=400
    if case=='active':
        s.db.FlowWorkflow.query.filter_by(id=s.a).update({'is_active':True});s.db.db_session.commit()
    elif case=='armed':
        s.db.AccountFlowTriggerState.query.filter_by(workflow_id=s.a).update({'state':'armed'});s.db.db_session.commit()
    elif case=='invalid': body['observation']=['order_seen']
    elif case=='anonymous':
        with s.client.session_transaction() as session: session.pop('user')
        expected=401
    response=s.post(s.a,body,csrf=case!='no_csrf')
    assert response.status_code==expected
    assert s.read(s.a,'alice') is None


def test_review_is_projected_only_for_the_current_activation(reviews):
    s=reviews
    assert s.post(s.a,{'observation':'uncertain'}).status_code==200
    from services.account_flow_trigger_status import get_account_one_shot_status
    assert get_account_one_shot_status(s.a,'alice')['review']['observation']=='uncertain'
    s.db.AccountFlowTriggerState.query.filter_by(workflow_id=s.a).update({'activation_id':'different-identity'})
    s.db.db_session.commit()
    assert s.read(s.a,'alice') is None
