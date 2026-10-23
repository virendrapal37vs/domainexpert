"""Real SQLite page boundaries, account scoping and matching page CSV."""
from datetime import datetime
import pytest
from test_paper_dashboard import dashboard_app, signed_client, read_csv
from test_paper_order_dates import add_order


def test_three_pages_and_csv_preserve_owner_dates(dashboard_app):
    app,db,_=dashboard_app
    for index in range(120):
        add_order(db,'alice',f'alice-{index}',datetime(2026,10,23,12))
    for index in range(60):
        add_order(db,'bob',f'bob-{index}',datetime(2026,10,23,12))
    add_order(db,'alice','excluded-date',datetime(2026,10,22,12))
    db.db_session.commit()
    alice=signed_client(app,'alice')
    root='/paper-preview/dashboard'
    query='?start=2026-10-23&end=2026-10-23'
    pages=[]
    for number,size in [(1,50),(2,50),(3,20)]:
        data=alice.get(root+query+f'&page={number}&format=json&username=bob').json
        assert data['order_page'] == number and data['order_pages'] == 3
        assert data['matching_orders'] == 120 and len(data['orders']) == size
        assert data['has_previous'] == (number > 1)
        assert data['has_next'] == (number < 3)
        assert data['order_first'] == (number-1)*50+1
        assert data['order_last'] == (number-1)*50+size
        ids=[row['orderid'] for row in data['orders']]
        pages.extend(ids)
        response=alice.get(root+'/export/orders.csv'+query+f'&page={number}')
        assert [row['orderid'] for row in read_csv(response)] == ids
        assert f'paper-orders-page-{number}.csv' in response.headers['Content-Disposition']
    assert len(set(pages)) == 120 and all(oid.startswith('alice-') for oid in pages)
    assert pages[0] == 'alice-119' and pages[-1] == 'alice-0'
    html=alice.get(root+query+'&page=2')
    assert html.status_code == 200 and html.headers['Cache-Control'] == 'no-store'
    assert b'Previous orders</a>' in html.data and b'Next orders</a>' in html.data
    assert b'Export orders page 2 CSV' in html.data
    assert b'page=1' in html.data and b'page=3' in html.data
    assert b'start=2026-10-23' in html.data
    assert 'Showing 51–100 of 120 matching'.encode() in html.data
    assert b'bob-' not in html.data and b'excluded-date' not in html.data
    bob=signed_client(app,'bob').get(root+query+'&page=2&format=json').json
    assert len(bob['orders']) == 10 and bob['matching_orders'] == 60
    assert all(row['orderid'].startswith('bob-') for row in bob['orders'])
    last=alice.get(root+query+'&page=999999&format=json').json
    assert last['order_page'] == 3 and len(last['orders']) == 20
    assert db.SandboxOrders.query.count() == 181 and db.SandboxFunds.query.count() == 0


@pytest.mark.parametrize('page',['0','-1','1.5','abc','1000000',''])
def test_invalid_page(dashboard_app,page):
    app,db,_=dashboard_app
    client=signed_client(app,'alice')
    for route in ('/paper-preview/dashboard','/paper-preview/dashboard/export/orders.csv'):
        assert client.get(route+'?page='+page).status_code == 400
    assert db.SandboxOrders.query.count() == 0


def test_empty_page_and_positions_export(dashboard_app):
    app,db,_=dashboard_app
    client=signed_client(app,'alice')
    url='/paper-preview/dashboard'
    data=client.get(url+'?page=10&format=json').json
    assert data['order_page'] == data['order_pages'] == 1
    assert data['order_first'] == data['order_last'] == 0
    assert not data['has_previous'] and not data['has_next']
    assert read_csv(client.get(url+'/export/orders.csv?page=10')) == []
    assert len(read_csv(client.get(url+'/export/positions.csv?page=10'))) == 2
    assert b'Next orders</a>' not in client.get(url).data
