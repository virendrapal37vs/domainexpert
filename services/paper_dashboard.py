"""Read-only, account-scoped staging paper dashboard data."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


def dashboard_snapshot(owner):
    from database.sandbox_db import SandboxFunds, SandboxOrders, SandboxPositions
    from database.account_broker_db import has_groww_credentials
    from utils.paper_preview import SYMBOL, GROWW_PAPER_SYMBOL, groww_enabled
    symbols = (SYMBOL, GROWW_PAPER_SYMBOL)
    funds = SandboxFunds.query.filter_by(user_id=owner).populate_existing().first()
    rows = SandboxPositions.query.filter(
        SandboxPositions.user_id == owner, SandboxPositions.symbol.in_(symbols),
        SandboxPositions.exchange == 'NSE', SandboxPositions.product == 'CNC'
    ).populate_existing().all()
    by_symbol = {row.symbol: row for row in rows}
    positions = []
    for symbol in symbols:
        row = by_symbol.get(symbol)
        positions.append(dict(symbol=symbol, quantity=row.quantity if row else 0,
            average_price=float(row.average_price) if row and row.quantity else None,
            realized_pnl=float(row.accumulated_realized_pnl or 0) if row else 0,
            source='Groww BHEL quote simulation' if symbol == GROWW_PAPER_SYMBOL else 'Fixed-price demonstration'))
    orders = SandboxOrders.query.filter(
        SandboxOrders.user_id == owner, SandboxOrders.symbol.in_(symbols),
        SandboxOrders.exchange == 'NSE', SandboxOrders.product == 'CNC'
    ).populate_existing().order_by(SandboxOrders.id.desc()).limit(50).all()
    return dict(username=owner, paper_only=True, groww_credentials_saved=has_groww_credentials(owner),
        groww_paper_available=groww_enabled(),
        refreshed_at=datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %H:%M:%S IST'),
        available_cash=float(funds.available_balance) if funds else None,
        used_margin=float(funds.used_margin) if funds else None,
        preview_realized_pnl=float(sum((row.accumulated_realized_pnl or Decimal('0') for row in rows), Decimal('0'))),
        open_positions=sum(1 for row in rows if row.quantity), positions=positions,
        orders=[dict(orderid=row.orderid, symbol=row.symbol, action=row.action, quantity=row.quantity,
                     status=row.order_status, price=float(row.average_price) if row.average_price is not None else None)
                for row in orders])
