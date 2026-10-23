"""Offline Razorpay test gateway checks: no real API calls or money movement."""
import hashlib
import hmac
import importlib
import json
import sys
from pathlib import Path
import pytest
from test_paper_dashboard import signed_client


@pytest.fixture
def gateway_app(main_app, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', 'true')
    monkeypatch.setenv('DOMAINXPERT_STAGING_SAFE', 'true')
    monkeypatch.setenv('DOMAINXPERT_RAZORPAY_TEST', 'true')
    monkeypatch.setenv('RAZORPAY_KEY_ID', 'rzp_test_OfflineKey')
    monkeypatch.setenv('RAZORPAY_KEY_SECRET', 'offline-secret')
    monkeypatch.setenv('RAZORPAY_WEBHOOK_SECRET', 'offline-webhook-secret-' * 3)
    for name in ('services.manual_subscription','services.razorpay_subscription','blueprints.account_subscription'):
        sys.modules.pop(name, None)
    billing = importlib.import_module('services.manual_subscription')
    gateway = importlib.import_module('services.razorpay_subscription')
    billing.init_db()
    gateway.init_db()
    bp = importlib.import_module('blueprints.account_subscription')
    main_app.register_blueprint(bp.subscription_bp)
    main_app.extensions['csrf'].exempt(main_app.view_functions['account_subscription.razorpay_webhook'])
    bp.install_subscription_gate(main_app)
    main_app.template_folder = str(Path(__file__).resolve().parents[2] / 'templates')
    state = {'orders':{}, 'payment_changes':{}, 'calls':[]}
    def api(method, path, payload=None):
        state['calls'].append((method,path,payload))
        if method == 'POST':
            oid = 'order_Offline' + str(len(state['orders'])+1)
            result = dict(payload, id=oid, status='created')
            state['orders'][oid] = result
            return result
        if path.startswith('payments/'):
            return dict(id=path.split('/')[-1], order_id=state['current_order'], status='captured',
                captured=True, amount=236000, currency='INR', amount_refunded=0,
                refund_status=None, **state['payment_changes'])
        if path.endswith('/payments'):
            return {'items':[{'id':'pay_Offline1', 'status':state.get('payment_status','captured')}]}
        return dict(state['orders'][path.split('/')[-1]], status='paid', amount_paid=236000, amount_due=0)
    monkeypatch.setattr(gateway, 'api', api)
    return main_app, billing, gateway, state


def post(client, path, data):
    csrf=client.get('/csrf').json['csrf_token']
    return client.post(path, json=data, headers={'X-CSRFToken':csrf})


def make_order(client, state):
    result=post(client, '/subscription/razorpay/order', {'amount':1,'username':'alice'}).json
    state['current_order']=result['order_id']
    return result


def signed(oid,pid='pay_Offline1'):
    signature=hmac.new(b'offline-secret',f'{oid}|{pid}'.encode(),hashlib.sha256).hexdigest()
    return dict(razorpay_order_id=oid,razorpay_payment_id=pid,razorpay_signature=signature)


def test_verified_capture_owner_binding_and_replay(gateway_app):
    app,billing,gateway,state=gateway_app
    bob=signed_client(app,'bob');alice=signed_client(app,'alice')
    assert bob.get('/api/account/brokers/groww').status_code==402
    result=make_order(bob,state);oid=result['order_id']
    assert result['amount']==236000 and result['test_mode'] is True
    assert 'offline-secret' not in str(result)
    assert make_order(bob,state)['order_id']==oid
    assert sum(c[0]=='POST' for c in state['calls'])==1
    assert post(alice,'/subscription/razorpay/verify',signed(oid)).status_code==400
    assert post(bob,'/subscription/razorpay/verify',dict(signed(oid),razorpay_signature='0'*64)).status_code==400
    response=post(bob,'/subscription/razorpay/verify',signed(oid))
    assert response.status_code==200 and response.json['active']
    until=response.json['access_until']
    assert post(bob,'/subscription/razorpay/verify',signed(oid)).json['access_until']==until
    assert bob.get('/api/account/brokers/groww').status_code==200
    assert alice.get('/api/account/brokers/groww').status_code==402
    assert gateway.history('alice')==[]
    html=bob.get('/subscription')
    assert b'Razorpay Test Mode' in html.data and b'Pay the exact amount using this UPI QR' not in html.data
    assert b'offline-secret' not in html.data and html.headers['Cache-Control']=='no-store'
    assert post(bob,'/subscription/payment',{}).status_code==409


@pytest.mark.parametrize('changes',[{'status':'authorized'}, {'amount':1}, {'currency':'USD'},
    {'order_id':'order_Other'}, {'amount_refunded':100}, {'captured':False}, {'refund_status':'full'}])
def test_uncaptured_mismatched_refunded_payment_never_grants(gateway_app,changes):
    app,billing,gateway,state=gateway_app
    bob=signed_client(app,'bob');oid=make_order(bob,state)['order_id']
    # merge overrides safely instead of duplicate keyword arguments in the fixture API
    original=gateway.api
    def api(method,path,payload=None):
        value=original(method,path,payload)
        return dict(value,**changes) if path.startswith('payments/') else value
    gateway.api=api
    assert post(bob,'/subscription/razorpay/verify',signed(oid)).status_code==400
    assert bob.get('/api/account/brokers/groww').status_code==402


def test_webhook_and_status_recovery_only_once(gateway_app):
    app,billing,gateway,state=gateway_app
    bob=signed_client(app,'bob');oid=make_order(bob,state)['order_id']
    raw=json.dumps({'event':'payment.captured','payload':{'payment':{'entity':{'order_id':oid,'id':'pay_Offline1'}}}}).encode()
    url='/subscription/razorpay/webhook'
    assert app.test_client().post(url,data=raw).status_code==400
    sig=hmac.new(gateway.config()[2].encode(),raw,hashlib.sha256).hexdigest()
    response=app.test_client().post(url,data=raw,headers={'X-Razorpay-Signature':sig})
    assert response.status_code==200
    until=response.json['access_until']
    assert app.test_client().post(url,data=raw,headers={'X-Razorpay-Signature':sig}).json['access_until']==until
    assert post(bob,'/subscription/razorpay/status',{'order_id':oid}).json['access_until']==until
    # Callback missing: server-side reconciliation grants another account's own captured order.
    alice=signed_client(app,'alice');oid2=make_order(alice,state)['order_id']
    def other_payment(method,path,payload=None):
        if path.endswith('/payments'): return {'items':[{'id':'pay_Offline2','status':'captured'}]}
        if path.startswith('payments/'): return {'id':'pay_Offline2','order_id':oid2,'status':'captured','captured':True,'amount':236000,'currency':'INR'}
        return dict(state['orders'][oid2],status='paid',amount_paid=236000,amount_due=0)
    gateway.api=other_payment
    assert post(alice,'/subscription/razorpay/status',{'order_id':oid2}).json['active']


def test_csrf_disabled_live_key_rejected_and_owner_exempt(gateway_app,monkeypatch):
    app,billing,gateway,state=gateway_app
    bob=signed_client(app,'bob')
    assert bob.post('/subscription/razorpay/order',json={}).status_code==400
    assert app.test_client().get('/subscription/razorpay/client.js').status_code==401
    assert bob.get('/subscription/razorpay/client.js').status_code==200
    from database.user_db import add_user
    add_user(billing.OWNER,billing.OWNER,'test',is_admin=True)
    owner=signed_client(app,billing.OWNER)
    assert post(owner,'/subscription/razorpay/order',{}).status_code==400
    monkeypatch.setenv('RAZORPAY_KEY_ID','rzp_live_NotAllowed')
    with pytest.raises(ValueError):gateway.config()
    monkeypatch.setenv('DOMAINXPERT_RAZORPAY_TEST','false')
    assert post(bob,'/subscription/razorpay/order',{}).status_code==400


def test_gateway_exception_is_generic_and_not_secret(gateway_app,monkeypatch):
    app,billing,gateway,state=gateway_app
    # Exercise the real HTTP wrapper without reaching any network.
    gateway=importlib.reload(gateway)
    import requests
    def unavailable(*args,**kwargs):raise requests.ConnectionError('offline-secret provider error')
    monkeypatch.setattr(requests.Session,'request',unavailable)
    with pytest.raises(RuntimeError) as error:gateway.api('POST','orders',{})
    assert 'offline-secret' not in str(error.value)


def test_csp_checkout_scope_and_tampered_webhook(gateway_app,monkeypatch):
    app,billing,gateway,state=gateway_app
    monkeypatch.setenv('CSP_ENABLED','TRUE')
    from csp import get_csp_config
    with app.test_request_context('/subscription'):
        config=get_csp_config()
        assert 'https://checkout.razorpay.com' in config['script-src']
        assert 'https://api.razorpay.com' in config['frame-src']
    with app.test_request_context('/instance-setting'):
        assert 'razorpay' not in str(get_csp_config())
    bob=signed_client(app,'bob');oid=make_order(bob,state)['order_id']
    raw=json.dumps({'event':'payment.captured','payload':{'payment':{'entity':{'order_id':oid,'id':'pay_Offline1'}}}}).encode()
    sig=hmac.new(gateway.config()[2].encode(),raw,hashlib.sha256).hexdigest()
    response=app.test_client().post('/subscription/razorpay/webhook',data=raw+b' ',headers={'X-Razorpay-Signature':sig})
    assert response.status_code==400
    assert gateway.history('bob')[0]['status']=='created'


def test_concurrent_capture_grants_one_month_and_replay_does_not_reactivate_expiry(gateway_app,monkeypatch):
    app,billing,gateway,state=gateway_app
    from datetime import datetime, timezone
    from concurrent.futures import ThreadPoolExecutor
    bob=signed_client(app,'bob');oid=make_order(bob,state)['order_id']
    row=gateway.own_order(oid)
    monkeypatch.setattr(billing,'now',lambda:datetime(2026,1,31,12,tzinfo=timezone.utc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:gateway.confirm(row,'pay_Offline1'),range(2)))
    assert len({r['access_until'] for r in results})==1
    assert results[0]['access_until'].startswith('2026-02-28T12:00')
    monkeypatch.setattr(billing,'now',lambda:datetime(2026,3,1,12,tzinfo=timezone.utc))
    replay=post(bob,'/subscription/razorpay/verify',signed(oid))
    assert replay.status_code==200 and replay.json['active'] is False
    assert bob.get('/api/account/brokers/groww').status_code==402
