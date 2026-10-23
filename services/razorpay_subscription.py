"""Opt-in Razorpay TEST checkout for restricted staging, never live payments."""
import calendar
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
import requests
from sqlalchemy import Table, MetaData, Column, String, Integer, select, insert, update, text
from services import manual_subscription as billing

metadata = MetaData()
orders = Table('account_razorpay_test_orders', metadata,
    Column('id', String(32), primary_key=True), Column('username', String(80), nullable=False),
    Column('order_id', String(80), unique=True), Column('key_id', String(80), nullable=False),
    Column('amount_paise', Integer, nullable=False), Column('currency', String(3), nullable=False),
    Column('status', String(16), nullable=False), Column('created_at', String(32), nullable=False),
    Column('payment_id', String(80), unique=True), Column('access_until', String(32)))


def enabled():
    return os.getenv('DOMAINXPERT_RAZORPAY_TEST', '').lower() == 'true'


def config():
    from utils.staging_mode import staging_safe
    key, secret = os.getenv('RAZORPAY_KEY_ID', ''), os.getenv('RAZORPAY_KEY_SECRET', '')
    webhook = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
    if not enabled() or not billing.enabled() or not staging_safe():
        raise ValueError('Razorpay test checkout is disabled.')
    if not re.fullmatch(r'rzp_test_[A-Za-z0-9]+', key) or not secret or len(webhook) < 32:
        raise ValueError('Configure Razorpay Test keys and a webhook secret of at least 32 characters.')
    return key, secret, webhook


def init_db():
    config()
    from database.user_db import engine
    orders.create(engine, checkfirst=True)


def api(method, path, payload=None):
    key, secret, _ = config()
    try:
        with requests.Session() as client:
            client.trust_env = False
            response = client.request(method, 'https://api.razorpay.com/v1/' + path,
                auth=(key, secret), json=payload, timeout=(5, 20), allow_redirects=False)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
    except (requests.RequestException, ValueError):
        raise RuntimeError('Razorpay could not confirm this request. Try checking the payment status later.') from None


def latest_access(owner, conn):
    return conn.execute(select(orders.c.access_until).where(orders.c.username == owner,
        orders.c.status == 'paid').order_by(orders.c.access_until.desc()).limit(1)).scalar()


def checkout_order(user):
    key, _, _ = config()
    if billing.exempt(user):
        raise ValueError('Owner access does not require payment.')
    from database.user_db import engine
    current = billing.now()
    with engine.connect() as conn:
        existing = conn.execute(select(orders).where(orders.c.username == user.username,
            orders.c.key_id == key, orders.c.status == 'created',
            orders.c.created_at > (current - timedelta(minutes=30)).isoformat()
        ).order_by(orders.c.created_at.desc()).limit(1)).mappings().first()
    if existing:
        return checkout_data(existing)
    local_id = secrets.token_hex(16)
    # Never retry a POST automatically after an ambiguous network timeout.
    remote = api('POST', 'orders', dict(amount=billing.AMOUNT_PAISE, currency='INR',
        receipt=local_id, partial_payment=False))
    oid = remote.get('id')
    if (not isinstance(oid, str) or not re.fullmatch(r'order_[A-Za-z0-9]+', oid)
            or remote.get('amount') != billing.AMOUNT_PAISE or remote.get('currency') != 'INR'
            or remote.get('status') != 'created' or remote.get('receipt') != local_id):
        raise RuntimeError('Unexpected Razorpay order response. Checkout was not started.')
    values = dict(id=local_id, username=user.username, order_id=oid, key_id=key,
        amount_paise=billing.AMOUNT_PAISE, currency='INR', status='created', created_at=current.isoformat())
    with engine.begin() as conn:
        conn.execute(insert(orders).values(**values))
    return checkout_data(values)


def checkout_data(row):
    return dict(key=row['key_id'], order_id=row['order_id'], amount=row['amount_paise'],
        currency=row['currency'], name='DomainXpert Trade', description='One month · Test payment',
        test_mode=True)


def own_order(order_id, user=None):
    key, _, _ = config()
    if not isinstance(order_id, str) or not re.fullmatch(r'order_[A-Za-z0-9]+', order_id):
        raise ValueError('Invalid order.')
    from database.user_db import engine
    with engine.connect() as conn:
        row = conn.execute(select(orders).where(orders.c.order_id == order_id,
            orders.c.key_id == key)).mappings().first()
    if row is None or (user is not None and row['username'] != user.username):
        raise ValueError('Order is not available for this account.')
    return dict(row)


def verify_checkout(user, data):
    if not isinstance(data, dict):
        raise ValueError('Invalid payment response.')
    row = own_order(data.get('razorpay_order_id'), user)
    pid, signature = data.get('razorpay_payment_id'), data.get('razorpay_signature')
    if not isinstance(pid, str) or not re.fullmatch(r'pay_[A-Za-z0-9]+', pid):
        raise ValueError('Invalid payment.')
    if not isinstance(signature, str) or len(signature) != 64:
        raise ValueError('Invalid payment signature.')
    expected = hmac.new(config()[1].encode(), (row['order_id'] + '|' + pid).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError('Invalid payment signature.')
    return confirm(row, pid)


def reconcile(user, order_id):
    row = own_order(order_id, user)
    if row['status'] == 'paid':
        return dict(active=datetime.fromisoformat(row['access_until']) > billing.now(), access_until=row['access_until'], already_processed=True)
    result = api('GET', 'orders/' + row['order_id'] + '/payments')
    items = result.get('items', [])
    if not isinstance(items, list):
        raise RuntimeError('Unexpected payment status response.')
    for item in items:
        if isinstance(item, dict) and item.get('status') == 'captured':
            pid = item.get('id')
            if isinstance(pid, str) and re.fullmatch(r'pay_[A-Za-z0-9]+', pid):
                return confirm(row, pid)
    return dict(active=False, pending=True)


def confirm(row, pid):
    if not re.fullmatch(r'pay_[A-Za-z0-9]+', pid):
        raise ValueError('Invalid payment.')
    # Both objects fetched with this merchant's TEST credentials, not trusted client/webhook fields.
    remote = api('GET', 'payments/' + pid)
    order = api('GET', 'orders/' + row['order_id'])
    if (remote.get('id') != pid or remote.get('order_id') != row['order_id']
            or remote.get('status') != 'captured' or remote.get('captured') is not True
            or remote.get('amount') != row['amount_paise'] or remote.get('currency') != 'INR'
            or remote.get('amount_refunded', 0) != 0 or remote.get('refund_status') is not None
            or order.get('id') != row['order_id'] or order.get('status') != 'paid'
            or order.get('currency') != 'INR' or order.get('amount') != row['amount_paise']
            or order.get('amount_paid') != row['amount_paise'] or order.get('amount_due') != 0):
        raise ValueError('Payment is not fully captured for this subscription. Access was not activated.')
    from database.user_db import engine
    with engine.connect() as conn:
        conn.execute(text('BEGIN IMMEDIATE'))
        saved = conn.execute(select(orders).where(orders.c.id == row['id'])).mappings().one()
        if saved['status'] == 'paid':
            if saved['payment_id'] != pid:
                raise ValueError('Order has already been processed with a different payment.')
            return dict(active=datetime.fromisoformat(saved['access_until']) > billing.now(), access_until=saved['access_until'], already_processed=True)
        previous = billing.access_until(row['username'], conn)
        current = billing.now()
        start = max(current, datetime.fromisoformat(previous)) if previous else current
        month, year = start.month % 12 + 1, start.year + (start.month == 12)
        until = start.replace(year=year, month=month,
            day=min(start.day, calendar.monthrange(year, month)[1])).isoformat()
        conn.execute(update(orders).where(orders.c.id == row['id']).values(
            payment_id=pid, status='paid', access_until=until))
        conn.commit()
    return dict(active=True, access_until=until, already_processed=False)


def webhook(raw, signature):
    if not isinstance(signature, str) or len(signature) != 64:
        raise ValueError('Invalid webhook signature.')
    expected = hmac.new(config()[2].encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError('Invalid webhook signature.')
    import json
    try:
        event = json.loads(raw)
        if event.get('event') not in {'payment.captured', 'order.paid'}:
            return dict(ignored=True)
        payment = event['payload']['payment']['entity']
        row = own_order(payment['order_id'])
        return confirm(row, payment['id'])
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('Invalid webhook body.') from None


def history(owner):
    from database.user_db import engine
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(select(orders.c.order_id, orders.c.payment_id,
            orders.c.amount_paise, orders.c.status, orders.c.created_at, orders.c.access_until
        ).where(orders.c.username == owner).order_by(orders.c.created_at.desc()).limit(20)).mappings()]
