"""Real sandbox OMS/SQLite through HTTP, with account-owned fake Groww quotes."""
import os
from pathlib import Path
import subprocess
import sys


def test_groww_paper_two_accounts(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = r'''
import os, sys, socket, logging
from pathlib import Path
from types import SimpleNamespace, ModuleType
from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf

def forbidden(*a, **k): raise AssertionError('Network or unrelated broker access forbidden')
socket.socket.connect=forbidden
socket.create_connection=forbidden

def stub(name, **attrs):
    module=ModuleType(name); module.__dict__.update(attrs); sys.modules[name]=module
stub('utils.logging', get_logger=logging.getLogger)
stub('database.token_db', get_symbol_info=forbidden)
stub('database.symbol', SymToken=object)
stub('database.auth_db', get_auth_token_broker=forbidden, get_api_key_for_tradingview=forbidden)
stub('database.user_db', find_user_by_exact_username=lambda name:SimpleNamespace(username=name) if name in ('alice','bob') else None)
stub('services.quotes_service', get_quotes=forbidden, get_multiquotes=forbidden)
stub('sandbox.websocket_execution_engine', peek_websocket_execution_engine=lambda:None, is_websocket_execution_engine_running=lambda:False)
events=[]
stub('utils.event_bus',bus=SimpleNamespace(publish=lambda e:events.append(e)))
credentials={'alice':('alice-key','alice-secret'),'bob':('bob-key','bob-secret')}
reads=[]
def own(name):
    reads.append(name)
    return credentials.get(name)
stub('database.account_broker_db', get_groww_credentials=own)
quotes=[]
state=dict(fail=False, price=400)
def quote(creds):
    quotes.append(creds)
    if state['fail']: return None,'Quote too old. No paper order placed.'
    return dict(ltp=state['price'],low=390,high=430,last_trade_time=1800000000,age_seconds=1),None
stub('services.groww_paper_quote', fetch_quote=quote)
from database import sandbox_db as db
db.Base.metadata.create_all(db.engine)
from blueprints import paper_preview as bp
bp.ROOT=Path.cwd()
from utils.staging_mode import install_staging_gate
from limiter import limiter
app=Flask(__name__,template_folder=str(Path(os.environ['PYTHONPATH'])/'templates'))
app.config.update(TESTING=True,SECRET_KEY='paper-test',RATELIMIT_ENABLED=False)
CSRFProtect(app); limiter.init_app(app); install_staging_gate(app)
app.register_blueprint(bp.paper_preview_bp)
app.add_url_rule('/csrf',endpoint='auth.get_csrf_token',view_func=lambda:jsonify(token=generate_csrf()))
clients={name:app.test_client() for name in ('alice','bob')}
headers={}
for name,client in clients.items():
    with client.session_transaction() as session: session['user']=name
    headers[name]={'X-CSRFToken':client.get('/csrf').json['token']}
url='/paper-preview/groww'
assert app.test_client().get(url).status_code==401
assert clients['alice'].get(url).status_code==200
assert quotes==[]
assert clients['alice'].post(url+'/order',json={'action':'BUY','quantity':1}).status_code==400
assert quotes==[] and db.SandboxOrders.query.count()==0
for name,qty in [('alice',3),('bob',7)]:
    response=clients[name].post(url+'/order',json=dict(action='BUY',quantity=qty,username='other',symbol='BHEL',price=1),headers=headers[name])
    assert response.status_code==200,response.json
    assert response.json['username']==name and response.json['quantity']==qty
    assert response.json['used_margin']==qty*400
    assert response.json['orders'][0]['status']=='complete'
    assert response.json['orders'][0]['price']==400
assert quotes==[credentials['alice'],credentials['bob']]
assert db.SandboxOrders.query.filter_by(symbol='BHEL').count()==0
bob=clients['bob'].get(url+'?format=json').json
state['price']=420
response=clients['alice'].post(url+'/order',json=dict(action='SELL',quantity=3),headers=headers['alice'])
assert response.status_code==200,response.json
assert response.json['quantity']==0 and response.json['realized_pnl']==60
assert clients['bob'].get(url+'?format=json').json==bob
# Quote failures must not initialize funds or create even a rejected order.
before=db.SandboxOrders.query.count()
state['fail']=True
response=clients['alice'].post(url+'/order',json=dict(action='BUY',quantity=1),headers=headers['alice'])
assert response.status_code==503,response.json
assert db.SandboxOrders.query.count()==before
state['fail']=False
assert clients['alice'].post(url+'/order',json=dict(action='SELL',quantity=1),headers=headers['alice']).status_code>=400
assert clients['bob'].get(url+'?format=json').json==bob
before=len(quotes)
for qty in [0,101,True,1.5,'1e2','9'*5000]:
    assert clients['alice'].post(url+'/order',json=dict(action='BUY',quantity=qty),headers=headers['alice']).status_code==400
assert len(quotes)==before
response=clients['alice'].post(url+'/quote',headers=headers['alice'])
assert response.status_code==200 and b'Groww BHEL/NSE last price' in response.data
assert clients['alice'].get(url).headers['Cache-Control']=='no-store'
assert not events,events
os.environ['DOMAINXPERT_GROWW_PAPER_PREVIEW']='false'
assert clients['alice'].get(url).status_code==403
assert clients['alice'].post(url+'/order',json=dict(action='BUY',quantity=1),headers=headers['alice']).status_code==403
assert clients['alice'].get('/paper-preview').status_code==200
print('PASS: owner quotes, real paper fills, fail-closed errors and default-off gate')
'''
    env=os.environ.copy()
    env.update(PYTHONPATH=str(root), DOMAINXPERT_STAGING_SAFE='true', DOMAINXPERT_PER_USER_GROWW='true',
               DOMAINXPERT_PAPER_PREVIEW='true', DOMAINXPERT_GROWW_PAPER_PREVIEW='true',
               FLASK_HOST_IP='127.0.0.1', FLASK_PORT='5001', WEBSOCKET_HOST='127.0.0.1', WEBSOCKET_PORT='8766',
               ZMQ_HOST='127.0.0.1', ZMQ_PORT='5556', SESSION_COOKIE_NAME='domainxpert_staging', CSRF_COOKIE_NAME='domainxpert_staging_csrf',
               HOST_SERVER='http://127.0.0.1:5001', BROKER_API_KEY='', BROKER_API_SECRET='', FLASK_DEBUG='False',
               NGROK_ALLOW='FALSE', ORDER_UPDATES_ENABLED='FALSE', MCP_HTTP_ENABLED='False', HISTORIFY_DATABASE_URL='db/staging-history.duckdb')
    (tmp_path/'db').mkdir()
    for name in ('DATABASE_URL','LATENCY_DATABASE_URL','LOGS_DATABASE_URL','HEALTH_DATABASE_URL','SANDBOX_DATABASE_URL'):
        env[name]='sqlite:///db/staging-'+name.lower()+'.db'
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
