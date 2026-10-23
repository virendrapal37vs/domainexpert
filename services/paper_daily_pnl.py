"""Read-only daily gross realized P&L reconstructed from retained paper fills."""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from services.paper_dashboard import parse_order_dates

SYMBOLS = ('DXPAPER', 'DXBHEL')
CENT = Decimal('0.01')
MAX_FILLS = 10000


def daily_report(owner, start='', end=''):
    if not start and not end:
        today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        start, end = str(today-timedelta(days=29)), str(today)
    first, last = parse_order_dates(start, end)
    result = dict(username=owner, start=start, end=end, rows=[], total_realized_pnl=None,
                  status='unavailable', message='Retained paper fills do not reconcile with saved positions. Daily P&L is unavailable.')
    from database.sandbox_db import SandboxTrades, SandboxPositions
    trades = SandboxTrades.query.filter(SandboxTrades.user_id == owner,
        SandboxTrades.symbol.in_(SYMBOLS), SandboxTrades.exchange == 'NSE',
        SandboxTrades.product == 'CNC').populate_existing().order_by(SandboxTrades.id).limit(MAX_FILLS+1).all()
    if len(trades) > MAX_FILLS:
        result['message'] = 'More than 10,000 paper fills. Daily report is unavailable; no partial totals exported.'
        return result
    positions = SandboxPositions.query.filter(SandboxPositions.user_id == owner,
        SandboxPositions.symbol.in_(SYMBOLS), SandboxPositions.exchange == 'NSE',
        SandboxPositions.product == 'CNC').populate_existing().all()
    saved = {row.symbol: row for row in positions}
    state = {symbol: dict(qty=0, avg=Decimal('0'), pnl=Decimal('0')) for symbol in SYMBOLS}
    days = defaultdict(lambda: dict(buy_quantity=0, sell_quantity=0, fills=0, DXPAPER=Decimal('0'), DXBHEL=Decimal('0')))
    try:
        for trade in trades:
            item = state[trade.symbol]
            price, qty = Decimal(str(trade.price)), trade.quantity
            if not price.is_finite() or price <= 0 or not isinstance(qty,int) or qty <= 0 or trade.trade_timestamp is None:
                return result
            pnl = Decimal('0')
            if trade.action == 'BUY':
                item['avg'] = ((item['qty']*item['avg'] + qty*price)/(item['qty']+qty)).quantize(CENT)
                item['qty'] += qty
            elif trade.action == 'SELL' and qty <= item['qty']:
                pnl = (price-item['avg'])*qty
                item['pnl'] += pnl
                item['qty'] -= qty
                if item['qty'] == 0:
                    item['avg'] = Decimal('0')
            else:
                return result
            if first <= trade.trade_timestamp <= last:
                day = days[str(trade.trade_timestamp.date())]
                day['fills'] += 1
                day['buy_quantity' if trade.action == 'BUY' else 'sell_quantity'] += qty
                day[trade.symbol] += pnl
        for symbol,item in state.items():
            row = saved.get(symbol)
            if item['qty'] != (row.quantity if row else 0):
                return result
            if item['pnl'].quantize(CENT) != Decimal(str((row.accumulated_realized_pnl or 0) if row else 0)).quantize(CENT):
                return result
            if item['qty'] and item['avg'] != Decimal(str(row.average_price)).quantize(CENT):
                return result
    except (ValueError, TypeError, InvalidOperation):
        return result
    rows = [dict(date_ist=date, fills=day['fills'], buy_quantity=day['buy_quantity'], sell_quantity=day['sell_quantity'],
                 dxpaper_pnl=str(day['DXPAPER'].quantize(CENT)), dxbhel_pnl=str(day['DXBHEL'].quantize(CENT)),
                 realized_pnl=str((day['DXPAPER']+day['DXBHEL']).quantize(CENT)))
            for date,day in sorted(days.items(),reverse=True)]
    return dict(result, status='success', rows=rows,
                total_realized_pnl=str(sum((Decimal(row['realized_pnl']) for row in rows),Decimal('0')).quantize(CENT)),
                message='Gross realized P&L from retained paper fills, reconciled to saved preview positions. Fees, spread and slippage excluded.')
