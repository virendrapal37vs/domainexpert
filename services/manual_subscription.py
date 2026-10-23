"""Staging manual payment ledger. Approval records a bank check, never proves payment."""
import calendar
import os
import re
from datetime import datetime, timezone
from sqlalchemy import MetaData, Table, Column, String, Integer, select, insert, update, text

AMOUNT_PAISE = 236000
OWNER = 'virendrapal37@gmail.com'
metadata = MetaData()
payments = Table('account_manual_payments', metadata,
    Column('id', Integer, primary_key=True), Column('username', String(80), nullable=False),
    Column('utr', String(32), unique=True, nullable=False),
    Column('amount_paise', Integer, nullable=False), Column('status', String(16), nullable=False),
    Column('submitted_at', String(32), nullable=False), Column('reviewed_at', String(32)),
    Column('reviewed_by', String(80)), Column('access_until', String(32)))


def enabled():
    return os.getenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', '').lower() == 'true'


def now():
    return datetime.now(timezone.utc)


def exempt(user):
    # Both persisted identity fields and administrator status must match.
    return bool(user and user.is_admin and user.username == OWNER and user.email == OWNER)


def init_db():
    from database.user_db import engine
    payments.create(engine, checkfirst=True)


def rows(owner=None):
    from database.user_db import engine
    query = select(payments).order_by(payments.c.id.desc()).limit(100)
    if owner is not None:
        query = query.where(payments.c.username == owner)
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(query).mappings()]


def access_until(owner, conn):
    manual = conn.execute(select(payments.c.access_until).where(
        payments.c.username == owner, payments.c.status == 'approved'
    ).order_by(payments.c.access_until.desc()).limit(1)).scalar()
    from services import razorpay_subscription as gateway
    online = gateway.latest_access(owner, conn) if gateway.enabled() else None
    return max(filter(None, (manual, online)), default=None)


def status(user):
    if exempt(user):
        return dict(active=True, exempt=True, access_until=None)
    from database.user_db import engine
    with engine.connect() as conn:
        until = access_until(user.username, conn)
    return dict(active=bool(until and datetime.fromisoformat(until) > now()),
                exempt=False, access_until=until)


def submit(user, utr):
    if not isinstance(utr, str) or not re.fullmatch(r'[0-9]{12}', utr.strip()):
        raise ValueError('Enter the 12-digit UPI reference number from your payment app.')
    from database.user_db import engine
    from sqlalchemy.exc import IntegrityError
    try:
        with engine.connect() as conn:
            conn.execute(text('BEGIN IMMEDIATE'))
            if conn.execute(select(payments.c.id).where(payments.c.username == user.username,
                    payments.c.status == 'pending')).first():
                raise ValueError('A payment is already awaiting verification.')
            conn.execute(insert(payments).values(username=user.username, utr=utr.strip(),
                amount_paise=AMOUNT_PAISE, status='pending', submitted_at=now().isoformat()))
            conn.commit()
    except IntegrityError:
        raise ValueError('This payment reference cannot be submitted. Contact the administrator.') from None


def review(payment_id, admin, decision):
    if decision not in {'approved', 'rejected'}:
        raise ValueError('Choose approve or reject.')
    from database.user_db import engine
    with engine.connect() as conn:
        conn.execute(text('BEGIN IMMEDIATE'))
        row = conn.execute(select(payments).where(payments.c.id == payment_id)).mappings().first()
        if row is None or row['status'] != 'pending':
            raise ValueError('Payment is missing or already reviewed.')
        current = now()
        until = None
        if decision == 'approved':
            previous = access_until(row['username'], conn)
            start = max(current, datetime.fromisoformat(previous)) if previous else current
            month = start.month % 12 + 1
            year = start.year + (start.month == 12)
            until = start.replace(year=year, month=month,
                day=min(start.day, calendar.monthrange(year, month)[1])).isoformat()
        conn.execute(update(payments).where(payments.c.id == payment_id).values(
            status=decision, reviewed_at=current.isoformat(), reviewed_by=admin.username,
            access_until=until))
        conn.commit()
