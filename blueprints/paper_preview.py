"""Explicit paper-only staging screen using the sandbox OMS and fixed prices."""
from pathlib import Path
from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request, url_for
from utils.account_access import current_account, require_account
from utils.paper_preview import SYMBOL, enabled, instrument_context
from utils.paper_preview import GROWW_PAPER_SYMBOL, GROWW_ENDPOINTS, groww_enabled
from limiter import limiter

ROOT = Path(__file__).resolve().parents[1]

paper_preview_bp = Blueprint('paper_preview', __name__, url_prefix='/paper-preview')


@paper_preview_bp.get('/dashboard')
@require_account
def dashboard():
    from services.paper_dashboard import dashboard_snapshot
    data = dashboard_snapshot(current_account().username)
    response = (jsonify(data) if request.args.get('format') == 'json'
                else make_response(render_template('paper_dashboard.html', **data)))
    response.headers['Cache-Control'] = 'no-store'
    return response


@paper_preview_bp.before_request
def require_preview():
    if not enabled():
        abort(404)
    if request.endpoint in GROWW_ENDPOINTS and not groww_enabled():
        abort(404)
    from utils.staging_mode import validate_staging_config
    validate_staging_config(ROOT)


def snapshot(owner, symbol=SYMBOL):
    from database.sandbox_db import SandboxOrders, SandboxPositions, SandboxFunds
    funds = SandboxFunds.query.filter_by(user_id=owner).populate_existing().first()
    position = SandboxPositions.query.filter_by(user_id=owner, symbol=symbol,
                                               exchange='NSE', product='CNC').populate_existing().first()
    orders = SandboxOrders.query.filter_by(user_id=owner, symbol=symbol, exchange='NSE',
                                          product='CNC').order_by(SandboxOrders.id.desc()).limit(25).all()
    return dict(username=owner, quantity=position.quantity if position else 0,
                realized_pnl=float(position.accumulated_realized_pnl or 0) if position else 0,
                available_cash=float(funds.available_balance) if funds else None,
                used_margin=float(funds.used_margin) if funds else None,
                orders=[dict(orderid=o.orderid, action=o.action, quantity=o.quantity,
                             status=o.order_status, price=float(o.average_price or 0)) for o in orders])


@paper_preview_bp.route('')
@require_account
def page():
    data = snapshot(current_account().username)
    if request.args.get('format') == 'json':
        return jsonify(data)
    return render_template('paper_preview.html', groww_paper_available=groww_enabled(), **data)


def groww_screen(quote=None, error=None, status=200):
    data = snapshot(current_account().username, GROWW_PAPER_SYMBOL)
    if request.is_json or request.args.get('format') == 'json':
        response = jsonify(**data, quote=quote, error=error, paper_only=True, symbol=GROWW_PAPER_SYMBOL)
    else:
        response = make_response(render_template('groww_paper_preview.html', quote=quote, error=error, **data))
    response.headers['Cache-Control'] = 'no-store'
    return response, status


def own_paper_quote():
    from database.account_broker_db import get_groww_credentials
    from services.groww_paper_quote import fetch_quote
    credentials = get_groww_credentials(current_account().username)
    if not credentials:
        return None, 'Save your own Groww credentials first.'
    return fetch_quote(credentials)


@paper_preview_bp.get('/groww')
@require_account
def groww_page():
    return groww_screen()


@paper_preview_bp.post('/groww/quote')
@require_account
@limiter.limit('3 per minute;10 per hour')
def groww_quote():
    quote, error = own_paper_quote()
    return groww_screen(quote, error, 503 if error else 200)


@paper_preview_bp.post('/groww/order')
@require_account
@limiter.limit('3 per minute;10 per hour')
def groww_order():
    payload = request.get_json(silent=True) if request.is_json else request.form
    if not payload or not hasattr(payload, 'get') or payload.get('action') not in ('BUY', 'SELL'):
        return groww_screen(error='Choose BUY or SELL', status=400)
    raw = str(payload.get('quantity', ''))
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 3 or not 1 <= int(raw) <= 100:
        return groww_screen(error='Quantity must be a whole number from 1 to 100', status=400)
    # Fetch anew for each order; caller price, timestamp, symbol and owner are ignored.
    quote, error = own_paper_quote()
    if error:
        return groww_screen(error=error, status=503)
    owner = current_account().username
    from sandbox.fund_manager import FundManager
    from sandbox.order_manager import OrderManager
    with instrument_context():
        if not FundManager(owner).initialize_funds()[0]:
            return groww_screen(error='Could not initialize paper funds', status=503)
        success, result, status = OrderManager(owner).place_order(dict(
            symbol=GROWW_PAPER_SYMBOL, exchange='NSE', product='CNC', price_type='LIMIT',
            action=payload['action'], quantity=int(raw), price=quote['ltp'],
            strategy='staging-groww-paper-preview'), prefetched_quote=quote)
    if not success:
        return groww_screen(error='Paper order rejected. Check your own shares and sandbox funds.', status=status)
    if request.is_json:
        return groww_screen(quote=quote)
    return redirect(url_for('paper_preview.groww_page'), code=303)


@paper_preview_bp.route('/order', methods=['POST'])
@require_account
def order():
    payload = request.get_json(silent=True) if request.is_json else request.form
    if (request.is_json and not isinstance(payload, dict)) or not payload or payload.get('action') not in ('BUY', 'SELL'):
        return jsonify(error='Choose BUY or SELL'), 400
    try:
        raw = str(payload.get('quantity', ''))
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError()
        quantity = int(raw)
        if not 1 <= quantity <= 100:
            raise ValueError()
    except ValueError:
        return jsonify(error='Quantity must be a whole number from 1 to 100'), 400
    owner = current_account().username
    # Body identity/symbol/price fields never control this paper-only path.
    action = payload['action']
    price = 100 if action == 'BUY' else 110
    from sandbox.fund_manager import FundManager
    from sandbox.order_manager import OrderManager
    from database.sandbox_db import SandboxOrders
    with instrument_context():
        if not FundManager(owner).initialize_funds()[0]:
            return jsonify(error='Could not initialize paper funds'), 503
        success, result, status = OrderManager(owner).place_order(dict(
            symbol=SYMBOL, exchange='NSE', product='CNC', price_type='LIMIT',
            action=action, quantity=quantity, price=price, strategy='staging-paper-preview'),
            prefetched_quote={'ltp': price, 'low': 90, 'high': 120})
    if not success:
        return jsonify(result), status
    # A successful placement need not be a fill; display the actual durable state.
    saved = SandboxOrders.query.filter_by(orderid=result['orderid'], user_id=owner).populate_existing().first()
    if request.is_json:
        return jsonify(orderid=result['orderid'], order_status=saved.order_status,
                       paper_only=True, **snapshot(owner)), 200
    return redirect(url_for('paper_preview.page'), code=303)
