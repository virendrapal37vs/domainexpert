"""Guard extracted messaging entry points without starting bots or sending messages."""
from flask import Flask, jsonify
import pytest
from test_strategy_account_guard import function


@pytest.fixture(autouse=True)
def scoped(monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')


@pytest.mark.parametrize('file', ['blueprints/telegram.py', 'blueprints/whatsapp.py'])
def test_bot_http_routes_blocked(file):
    app = Flask(__name__)
    app.before_request(function(file, 'require_account_safe_bot', {'jsonify': jsonify}))
    app.add_url_rule('/config', view_func=lambda: {'read_shared_config': True}, methods=['GET', 'POST'])
    for verb in ('get', 'post'):
        response = getattr(app.test_client(), verb)('/config')
        assert response.status_code == 503
        assert response.json['code'] == 'BOT_ACCOUNT_ISOLATION_PENDING'


@pytest.mark.parametrize('file,cls,name,args', [
    ('services/telegram_bot_service.py','TelegramBotService','initialize_bot_sync',('fake-token',)),
    ('services/telegram_bot_service.py','TelegramBotService','start_bot',()),
    ('services/whatsapp_bot_service.py','WhatsAppBotService','start_bot',()),
    ('services/whatsapp_bot_service.py','WhatsAppBotService','start_pair',()),
])
def test_bot_start_stops_before_state_or_network(file, cls, name, args):
    fn = function(file, name, {}, cls=cls)
    ok, message = fn(object(), *args)
    assert ok is False
    assert 'Account-owned' in message


@pytest.mark.parametrize('file,cls', [
    ('services/telegram_alert_service.py','TelegramAlertService'),
    ('services/whatsapp_alert_service.py','WhatsAppAlertService')])
def test_order_alerts_stop_before_session_fallback_or_recipient_lookup(file, cls):
    fn = function(file, 'send_order_alert', {}, cls=cls)
    assert fn(object(), 'placeorder', {}, {}, api_key='fake-key') is None
    send = function(file, 'send_alert_sync', {}, cls=cls)
    assert send(object(), 'fake-recipient', 'synthetic message') is False
    broadcast = function(file, 'send_broadcast_alert', {}, cls=cls)
    assert broadcast(object(), 'synthetic message') is None


def test_whatsapp_direct_send_reports_no_delivery():
    fn = function('services/whatsapp_bot_service.py', 'send_sync', {}, cls='WhatsAppBotService')
    report = fn(object(), text='synthetic message')
    assert report['sent'] == []
    assert report['failed']


@pytest.mark.parametrize('file', ['blueprints/telegram.py', 'blueprints/whatsapp.py'])
def test_legacy_bot_http_behavior_preserved(file, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert function(file, 'require_account_safe_bot', {})() is None
