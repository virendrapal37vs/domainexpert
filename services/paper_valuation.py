"""Manual, read-only DXBHEL valuation using only the signed-in owner's quote."""
import math
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


def own_position(owner):
    from database.sandbox_db import SandboxPositions
    return SandboxPositions.query.filter_by(user_id=owner, symbol='DXBHEL', exchange='NSE',
                                            product='CNC').populate_existing().first()


def estimate(owner):
    row = own_position(owner)
    if row is None or row.quantity == 0:
        return dict(status='closed', unrealized_pnl=0, message='No open DXBHEL position. No Groww quote requested.')
    from database.account_broker_db import get_groww_credentials
    from services.groww_paper_quote import fetch_quote
    credentials = get_groww_credentials(owner)
    if not credentials:
        return dict(status='unavailable', unrealized_pnl=None, message='Save your own Groww credentials first.')
    quote, error = fetch_quote(credentials)
    if error or not quote:
        return dict(status='unavailable', unrealized_pnl=None,
                    message='No fresh Groww quote available. Check approval, credentials and market freshness, then retry manually.')
    try:
        price, stamp = quote['ltp'], quote['last_trade_time']
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (price, stamp)):
            raise ValueError()
        age = time.time() - stamp
        if not -5 <= age <= 120:
            raise ValueError()
        # Re-read after the network call: orders may have changed the position.
        row = own_position(owner)
        quantity = row.quantity if row else 0
        entry = Decimal(str(row.average_price)) if quantity else Decimal('0')
        if not entry.is_finite() or (quantity and entry <= 0):
            raise ValueError()
        pnl = ((Decimal(str(price)) - entry) * quantity).quantize(Decimal('0.01'))
        return dict(status='fresh', symbol='DXBHEL', quantity=quantity,
                    average_price=float(entry) if quantity else None, quote_price=price,
                    unrealized_pnl=float(pnl), last_trade_time=stamp, valid_until=stamp+120,
                    traded_at_ist=datetime.fromtimestamp(stamp, ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y %H:%M:%S IST'),
                    message='Estimated at this quote only; fees, spread and slippage excluded. Cash and realized P&L unchanged.')
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return dict(status='unavailable', unrealized_pnl=None, message='Quote or position is stale or invalid. Refresh manually for a new estimate.')
