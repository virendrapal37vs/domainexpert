"""Synthetic preview gates and real OMS/SQLite through Flask session + CSRF."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from utils import paper_preview


def test_preview_requires_all_three_flags(monkeypatch):
    for name in ('DOMAINXPERT_STAGING_SAFE', 'DOMAINXPERT_PER_USER_GROWW', 'DOMAINXPERT_PAPER_PREVIEW'):
        monkeypatch.setenv(name, 'true')
    assert paper_preview.enabled()
    for name in ('DOMAINXPERT_STAGING_SAFE', 'DOMAINXPERT_PER_USER_GROWW', 'DOMAINXPERT_PAPER_PREVIEW'):
        monkeypatch.setenv(name, 'false')
        assert not paper_preview.enabled()
        monkeypatch.setenv(name, 'true')


def test_instrument_context_is_local_and_restored(monkeypatch):
    import sys
    from types import SimpleNamespace
    from concurrent.futures import ThreadPoolExecutor
    for name in ('DOMAINXPERT_STAGING_SAFE', 'DOMAINXPERT_PER_USER_GROWW', 'DOMAINXPERT_PAPER_PREVIEW'):
        monkeypatch.setenv(name, 'true')
    monkeypatch.setitem(sys.modules, 'database.token_db', SimpleNamespace(get_symbol_info=lambda *a: 'real-path'))
    assert paper_preview.get_symbol_info('DXPAPER', 'NSE') == 'real-path'
    with pytest.raises(RuntimeError):
        with paper_preview.instrument_context():
            assert paper_preview.get_symbol_info('DXPAPER', 'NSE').lotsize == 1
            assert paper_preview.get_symbol_info('BHEL', 'NSE') == 'real-path'
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(paper_preview.get_symbol_info, 'DXPAPER', 'NSE').result() == 'real-path'
            raise RuntimeError('restore')
    assert paper_preview.get_symbol_info('DXPAPER', 'NSE') == 'real-path'


def test_session_csrf_and_real_paper_round_trip(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = r'''
import os, sys, logging, socket
from types import ModuleType, SimpleNamespace
from pathlib import Path
from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf

def forbidden(*a, **k):
    raise AssertionError('External provider forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden

def stub(name, **attrs):
    module = ModuleType(name); module.__dict__.update(attrs); sys.modules[name] = module
stub('utils.logging', get_logger=logging.getLogger)
stub('database.token_db', get_symbol_info=forbidden)
stub('database.symbol', SymToken=object)
stub('database.auth_db', get_auth_token_broker=forbidden, get_api_key_for_tradingview=forbidden)
stub('database.user_db', find_user_by_exact_username=lambda name: SimpleNamespace(username=name) if name in ('alice','bob') else None)
stub('services.quotes_service', get_quotes=forbidden, get_multiquotes=forbidden)
stub('sandbox.websocket_execution_engine', peek_websocket_execution_engine=lambda:None,
     is_websocket_execution_engine_running=lambda:False)
event_calls = []
stub('utils.event_bus', bus=SimpleNamespace(publish=lambda event:event_calls.append(event)))
from database import sandbox_db as db
db.Base.metadata.create_all(db.engine)
from utils.staging_mode import install_staging_gate
from blueprints import paper_preview as bp
bp.ROOT = Path.cwd()
app=Flask(__name__, template_folder=str(Path(os.environ['PYTHONPATH'])/'templates'))
app.config.update(TESTING=True, SECRET_KEY='synthetic-paper')
CSRFProtect(app); install_staging_gate(app)
app.register_blueprint(bp.paper_preview_bp)
app.add_url_rule('/csrf',endpoint='auth.get_csrf_token',view_func=lambda:jsonify(token=generate_csrf()))
app.add_url_rule('/trade',endpoint='orders.place',view_func=forbidden,methods=['POST'])
clients={name:app.test_client() for name in ('alice','bob')}
for client in clients.values():
    original_post = client.post
    def guarded_post(url, *args, _client=client, _post=original_post, **kwargs):
        if url.endswith('/order') and 'json' in kwargs:
            page = url.rsplit('/order', 1)[0]
            kwargs['json'] = dict(kwargs['json'], request_token=_client.get(page+'?format=json').json.get('request_token'))
        if url.endswith('/order') and 'json' in kwargs:
            _client.last_order_payload = kwargs['json'].copy()
        return _post(url, *args, **kwargs)
    client.raw_post = original_post
    client.post = guarded_post
headers={}
for name,client in clients.items():
    with client.session_transaction() as session: session['user']=name
    headers[name]={'X-CSRFToken':client.get('/csrf').json['token']}
assert app.test_client().get('/paper-preview').status_code==401
assert clients['alice'].post('/trade',headers=headers['alice']).status_code==403
assert clients['alice'].post('/paper-preview/order',json={'action':'BUY','quantity':3}).status_code==400
assert db.SandboxOrders.query.count()==0
for name,qty in [('alice',3),('bob',7)]:
    response=clients[name].post('/paper-preview/order',json={'action':'BUY','quantity':qty,
        'username':'bob' if name=='alice' else 'alice','symbol':'RELIANCE','price':1},headers=headers[name])
    assert response.status_code==200,response.json
    assert response.json['order_status']=='complete'
    assert response.json['username']==name and response.json['quantity']==qty
    assert response.json['used_margin']==qty*100
    assert all(row['price']==100 for row in response.json['orders'])
    assert clients[name].get('/paper-preview').status_code==200
before_replay=db.SandboxOrders.query.count()
for name in ('alice','bob'):
    replay=clients[name].raw_post('/paper-preview/order',json=clients[name].last_order_payload,headers=headers[name])
    assert replay.status_code==409,replay.json
assert db.SandboxOrders.query.count()==before_replay
bob_before=clients['bob'].get('/paper-preview?format=json').json
bob_before.pop('request_token', None)
response=clients['alice'].post('/paper-preview/order',json={'action':'SELL','quantity':3},headers=headers['alice'])
assert response.status_code==200,response.json
assert response.json['quantity']==0 and response.json['realized_pnl']==30
assert response.json['used_margin']==0
assert {k:v for k,v in clients['bob'].get('/paper-preview?format=json').json.items() if k != 'request_token'}==bob_before
assert db.SandboxOrders.query.filter_by(symbol='DXPAPER').count()==3
assert db.SandboxTrades.query.count()==3
assert event_calls==[],event_calls
# Overselling cannot consume Bob's shares.
response=clients['alice'].post('/paper-preview/order',json={'action':'SELL','quantity':1},headers=headers['alice'])
assert response.status_code>=400,response.json
assert {k:v for k,v in clients['bob'].get('/paper-preview?format=json').json.items() if k != 'request_token'}==bob_before
for qty in [0,101,1.5,True,'1e2']:
    assert clients['alice'].post('/paper-preview/order',json={'action':'BUY','quantity':qty},headers=headers['alice']).status_code==400
os.environ['DOMAINXPERT_PAPER_PREVIEW']='false'
assert clients['alice'].get('/paper-preview').status_code==403
assert not event_calls
print('PASS: session paper round trip and guards')
'''
    env = os.environ.copy()
    env.update(PYTHONPATH=str(root), DOMAINXPERT_STAGING_SAFE='true', DOMAINXPERT_PER_USER_GROWW='true',
               DOMAINXPERT_PAPER_PREVIEW='true', FLASK_HOST_IP='127.0.0.1', FLASK_PORT='5001',
               WEBSOCKET_HOST='127.0.0.1', WEBSOCKET_PORT='8766', ZMQ_HOST='127.0.0.1', ZMQ_PORT='5556',
               SESSION_COOKIE_NAME='domainxpert_staging', CSRF_COOKIE_NAME='domainxpert_staging_csrf',
               HOST_SERVER='http://127.0.0.1:5001', BROKER_API_KEY='', BROKER_API_SECRET='',
               FLASK_DEBUG='False', NGROK_ALLOW='FALSE', ORDER_UPDATES_ENABLED='FALSE', MCP_HTTP_ENABLED='False',
               HISTORIFY_DATABASE_URL='db/staging-history.duckdb')
    (tmp_path/'db').mkdir()
    for name in ('DATABASE_URL','LATENCY_DATABASE_URL','LOGS_DATABASE_URL','HEALTH_DATABASE_URL','SANDBOX_DATABASE_URL'):
        env[name]='sqlite:///db/staging-'+name.lower()+'.db'
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
