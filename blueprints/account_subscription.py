"""Manual UPI subscription preview; CSRF applies to every mutation."""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for
from pathlib import Path
from limiter import limiter
from utils.account_access import current_account, require_account, require_instance_admin
from services import manual_subscription as billing
from services import razorpay_subscription as gateway

subscription_bp = Blueprint('account_subscription', __name__, url_prefix='/subscription')


@subscription_bp.before_request
def available():
    from utils.staging_mode import staging_safe
    if not billing.enabled() or not staging_safe():
        abort(404)


@subscription_bp.after_request
def private(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@subscription_bp.get('')
@require_account
def page():
    user = current_account()
    data = dict(user=user, subscription=billing.status(user), payments=billing.rows(user.username), razorpay_test=gateway.enabled(), online_payments=gateway.history(user.username) if gateway.enabled() else [])
    if request.args.get('format') == 'json':
        return jsonify(subscription=data['subscription'], payments=data['payments'], amount_paise=billing.AMOUNT_PAISE)
    return render_template('account_subscription.html', **data)


@subscription_bp.get('/qr')
@require_account
def qr():
    return send_file(Path(__file__).resolve().parents[1] / 'static/images/subscription-upi.png', mimetype='image/png')


@subscription_bp.post('/payment')
@require_account
@limiter.limit('5 per hour')
def payment():
    if gateway.enabled():
        return jsonify(error='Use Razorpay test checkout for new payments.'), 409
    try:
        billing.submit(current_account(), request.form.get('utr'))
    except ValueError as error:
        return jsonify(error=str(error)), 409
    return redirect(url_for('account_subscription.page'), 303)


@subscription_bp.get('/admin')
@require_account
def admin():
    denied = require_instance_admin()
    if denied:
        return denied
    return render_template('account_subscription_admin.html', payments=billing.rows())


@subscription_bp.post('/admin/<int:payment_id>')
@require_account
@limiter.limit('30 per minute')
def review(payment_id):
    denied = require_instance_admin()
    if denied:
        return denied
    if request.form.get('bank_verified') != 'yes':
        return jsonify(error='Confirm that you checked this payment in the receiving bank account.'), 400
    try:
        billing.review(payment_id, current_account(), request.form.get('decision'))
    except ValueError as error:
        return jsonify(error=str(error)), 409
    return redirect(url_for('account_subscription.admin'), 303)


def install_subscription_gate(app):
    @app.before_request
    def subscription_gate():
        if not billing.enabled():
            return None
        from utils.staging_mode import staging_safe
        if not staging_safe():
            return jsonify(error='Manual subscriptions require restricted staging.'), 503
        endpoint = request.endpoint or ''
        # Read-only saved paper reports remain accessible after expiry.
        protected = (endpoint.startswith('account_broker.') or
            endpoint in {'auth.get_broker_config', 'brlogin.broker_callback'} or
            (endpoint.startswith('paper_preview.') and request.method == 'POST') or
            (endpoint.startswith('flow.') and request.method != 'GET'))
        if not protected:
            return None
        user = current_account()
        if user is None:
            return jsonify(error='Sign in first'), 401
        if not billing.status(user)['active']:
            return jsonify(status='error', message='Activate your subscription before connecting a broker.',
                subscription_url='/subscription'), 402


@subscription_bp.post('/razorpay/order')
@require_account
@limiter.limit('5 per minute;20 per hour')
def razorpay_order():
    try:
        return jsonify(gateway.checkout_order(current_account()))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503


@subscription_bp.post('/razorpay/verify')
@require_account
@limiter.limit('10 per minute')
def razorpay_verify():
    if (request.content_length or 0) > 4096:
        abort(413)
    try:
        return jsonify(gateway.verify_checkout(current_account(), request.get_json(silent=True)))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503


@subscription_bp.post('/razorpay/status')
@require_account
@limiter.limit('5 per minute')
def razorpay_status():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Invalid status request.'), 400
    try:
        return jsonify(gateway.reconcile(current_account(), data.get('order_id')))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503


@subscription_bp.post('/razorpay/webhook')
def razorpay_webhook():
    # This is the only CSRF-exempt endpoint, authenticated by HMAC of the raw body.
    request.max_content_length = 65536
    if (request.content_length or 0) > 65536:
        abort(413)
    try:
        return jsonify(gateway.webhook(request.get_data(), request.headers.get('X-Razorpay-Signature')))
    except ValueError:
        return jsonify(error='Webhook validation failed.'), 400
    except RuntimeError:
        return jsonify(error='Payment confirmation temporarily unavailable.'), 503


@subscription_bp.get('/razorpay/client.js')
@require_account
def razorpay_client():
    if not gateway.enabled():
        abort(404)
    return send_file(Path(__file__).resolve().parents[1] / 'static/js/razorpay_subscription.js', mimetype='application/javascript')
