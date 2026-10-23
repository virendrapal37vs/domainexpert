"""IST placement-date filtering stays account scoped and matches CSV."""
from datetime import datetime
import pytest
from test_paper_dashboard import dashboard_app, seed, signed_client, read_csv


def add_order(db, owner, orderid, placed):
    db.db_session.add(db.SandboxOrders(user_id=owner,orderid=orderid,symbol='DXBHEL',exchange='NSE',
        product='CNC',action='BUY',quantity=1,price_type='LIMIT',price=400,average_price=400,
        pending_quantity=0,order_status='complete',order_timestamp=placed))


def test_inclusive_ist_dates_and_csv_owner(dashboard_app):
    app,db,_=dashboard_app
    seed(db)
    db.SandboxOrders.query.update({'order_timestamp':datetime(2026,10,1,12)})
    for owner,oid,stamp in [('alice','before',datetime(2026,10,22,23,59,59)),
                            ('alice','start',datetime(2026,10,23)),
                            ('alice','end',datetime(2026,10,23,23,59,59,999999)),
                            ('alice','after',datetime(2026,10,24)),
                            ('bob','other-account',datetime(2026,10,23,12))]:
        add_order(db,owner,oid,stamp)
    db.db_session.commit()
    alice=signed_client(app,'alice')
    query='?start=2026-10-23&end=2026-10-23&username=bob'
    data=alice.get('/paper-preview/dashboard'+query+'&format=json').json
    assert {o['orderid'] for o in data['orders']} == {'start','end'}
    assert data['matching_orders'] == 2
    assert data['available_cash'] == 1000 and data['preview_realized_pnl'] == 40
    assert data['orders'][0]['placed_at_ist'] == '2026-10-23 23:59:59'
    csv=read_csv(alice.get('/paper-preview/dashboard/export/orders.csv'+query))
    assert {o['orderid'] for o in csv} == {'start','end'}
    assert csv[0]['placed_at_ist'] == data['orders'][0]['placed_at_ist']
    html=alice.get('/paper-preview/dashboard'+query)
    assert html.status_code == 200 and html.headers['Cache-Control'] == 'no-store'
    assert b'start=2026-10-23' in html.data and b'Showing 2 of 2 matching' in html.data
    assert b'other-account' not in html.data
    bob=signed_client(app,'bob').get('/paper-preview/dashboard'+query+'&format=json').json
    assert {o['orderid'] for o in bob['orders']} == {'other-account'}
    assert db.SandboxOrders.query.count() == 9


@pytest.mark.parametrize('query', ['start=2026-10-23', 'end=2026-10-23',
    'start=2026-02-30&end=2026-03-01', 'start=2026-10-24&end=2026-10-23',
    'start=2025-01-01&end=2026-10-23', 'start=2026-1-01&end=2026-01-02'])
def test_invalid_dates_fail_closed(dashboard_app, query):
    app,db,_=dashboard_app
    client=signed_client(app,'alice')
    for path in ('/paper-preview/dashboard','/paper-preview/dashboard/export/orders.csv'):
        assert client.get(path+'?'+query).status_code == 400
    assert db.SandboxFunds.query.count() == 0


def test_empty_dates_positions_and_latest_fifty(dashboard_app):
    app,db,_=dashboard_app
    seed(db)
    for index in range(55):
        add_order(db,'alice',f'date-{index}',datetime(2026,10,23,12))
    db.db_session.commit()
    client=signed_client(app,'alice')
    query='?start=2026-10-23&end=2026-10-23'
    data=client.get('/paper-preview/dashboard'+query+'&format=json').json
    # Seed records use today's timestamp, so use matching count rather than a date assumption.
    assert data['matching_orders'] >= 55 and len(data['orders']) == 50
    csv=read_csv(client.get('/paper-preview/dashboard/export/orders.csv'+query))
    assert len(csv) == 50 and csv[0]['orderid'] == 'date-54'
    empty='?start=2000-01-01&end=2000-01-01'
    assert read_csv(client.get('/paper-preview/dashboard/export/orders.csv'+empty)) == []
    assert b'No preview orders match these dates' in client.get('/paper-preview/dashboard'+empty).data
    assert len(read_csv(client.get('/paper-preview/dashboard/export/positions.csv'+empty))) == 2
