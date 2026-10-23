"""Daily paper fill reconstruction against real per-account SQLite records."""
from datetime import datetime
from decimal import Decimal
import importlib
import pytest
from test_paper_dashboard import dashboard_app, signed_client, read_csv

URL='/paper-preview/daily-pnl'


def fill(db, owner, tid, symbol, action, qty, price, day):
    db.db_session.add(db.SandboxTrades(user_id=owner,tradeid=tid,orderid=tid,symbol=symbol,
        exchange='NSE',product='CNC',action=action,quantity=qty,price=price,
        trade_timestamp=datetime(2026,10,day,12)))


def position(db,owner,symbol,qty,avg,pnl):
    db.db_session.add(db.SandboxPositions(user_id=owner,symbol=symbol,exchange='NSE',product='CNC',
        quantity=qty,average_price=avg,accumulated_realized_pnl=pnl))


def history(db):
    fill(db,'alice','a1','DXPAPER','BUY',3,100,22)
    fill(db,'alice','a2','DXPAPER','SELL',1,110,23)
    fill(db,'alice','a3','DXPAPER','SELL',2,90,24)
    fill(db,'alice','a4','DXBHEL','BUY',1,400,23)
    fill(db,'alice','a5','DXBHEL','SELL',1,398.6,24)
    position(db,'alice','DXPAPER',0,0,-10)
    position(db,'alice','DXBHEL',0,0,-1.4)
    fill(db,'bob','b1','DXPAPER','BUY',2,10,23)
    fill(db,'bob','b2','DXPAPER','SELL',2,30,23)
    position(db,'bob','DXPAPER',0,0,40)
    # Real symbols and other accounts do not participate in reconciliation.
    fill(db,'alice','ignored','BHEL','SELL',999,999,23)
    db.db_session.commit()


def test_daily_carry_basis_owner_and_csv(dashboard_app):
    app,db,_=dashboard_app
    history(db)
    alice=signed_client(app,'alice')
    query='?start=2026-10-23&end=2026-10-24&username=bob'
    response=alice.get(URL+query+'&format=json')
    assert response.status_code == 200
    data=response.json
    assert data['username'] == 'alice' and data['total_realized_pnl'] == '-11.40'
    assert [(r['date_ist'],r['realized_pnl']) for r in data['rows']] == [('2026-10-24','-21.40'),('2026-10-23','10.00')]
    assert data['rows'][0]['dxbhel_pnl'] == '-1.40'
    assert data['rows'][1]['buy_quantity'] == 1 and data['rows'][1]['sell_quantity'] == 1
    csv=alice.get(URL+query+'&format=csv')
    assert csv.headers['Cache-Control'] == 'no-store'
    rows=read_csv(csv)
    assert rows[0]['realized_pnl'] == '-21.40'
    assert sum(Decimal(r['realized_pnl']) for r in rows) == Decimal('-11.40')
    html=alice.get(URL+query)
    assert html.status_code == 200 and b'Export daily P&amp;L CSV' in html.data
    assert b'bob' not in html.data
    bob=signed_client(app,'bob').get(URL+query+'&format=json').json
    assert bob['total_realized_pnl'] == '40.00'
    assert db.SandboxTrades.query.count() == 8 and db.SandboxFunds.query.count() == 0


def test_average_cost_and_open_position(dashboard_app):
    app,db,_=dashboard_app
    fill(db,'alice','1','DXBHEL','BUY',1,100,22)
    fill(db,'alice','2','DXBHEL','BUY',1,102,22)
    fill(db,'alice','3','DXBHEL','SELL',1,105,23)
    position(db,'alice','DXBHEL',1,101,4)
    db.db_session.commit()
    data=signed_client(app,'alice').get(URL+'?start=2026-10-23&end=2026-10-23&format=json').json
    assert data['total_realized_pnl'] == '4.00'
    assert data['rows'][0]['fills'] == 1
    assert db.SandboxPositions.query.first().quantity == 1


@pytest.mark.parametrize('problem',['missing_fill','position_mismatch'])
def test_unreconciled_report_no_partial_csv(dashboard_app,problem):
    app,db,_=dashboard_app
    history(db)
    if problem == 'missing_fill':
        db.SandboxTrades.query.filter_by(tradeid='a1').delete()
    else:
        db.SandboxPositions.query.filter_by(user_id='alice',symbol='DXPAPER').update({'accumulated_realized_pnl':999})
    db.db_session.commit()
    client=signed_client(app,'alice')
    result=client.get(URL+'?format=json')
    assert result.status_code == 409
    assert result.json['rows'] == [] and result.json['total_realized_pnl'] is None
    csv=client.get(URL+'?format=csv')
    assert csv.status_code == 409 and csv.mimetype == 'application/json'
    assert 'Content-Disposition' not in csv.headers


def test_history_limit_no_partial_results(dashboard_app,monkeypatch):
    app,db,_=dashboard_app
    history(db)
    service=importlib.import_module('services.paper_daily_pnl')
    monkeypatch.setattr(service,'MAX_FILLS',1)
    result=signed_client(app,'alice').get(URL+'?format=json')
    assert result.status_code == 409 and result.json['rows'] == []


def test_empty_report_dates_and_access(dashboard_app,monkeypatch):
    app,db,_=dashboard_app
    assert app.test_client().get(URL).status_code == 401
    client=signed_client(app,'alice')
    data=client.get(URL+'?format=json').json
    assert data['status'] == 'success' and data['total_realized_pnl'] == '0.00' and data['rows'] == []
    assert read_csv(client.get(URL+'?format=csv')) == []
    assert client.get(URL+'?start=2026-10-24&end=2026-10-23').status_code == 400
    assert client.get(URL+'?start=2026-10-23').status_code == 400
    assert db.SandboxFunds.query.count() == 0
    monkeypatch.setenv('DOMAINXPERT_PAPER_PREVIEW','false')
    assert client.get(URL).status_code == 403
