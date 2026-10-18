"""Run against restricted loopback staging only; creates two disposable accounts.

Uses HTTP signup/login/credentials plus read-only DB verification. Never calls
broker/order APIs. Test users and dummy credentials remain for inspection.
"""
import os
import secrets
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'http://127.0.0.1:5001'


def check(condition, label):
    if not condition:
        raise RuntimeError(label)
    print('PASS:', label)


def client():
    session = requests.Session()
    session.trust_env = False
    return session


def call(session, method, path, expected=200, csrf=False, **kwargs):
    headers = {}
    if csrf:
        response = session.get(BASE + '/auth/csrf-token', timeout=15, allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError('Unable to initialize staging CSRF session')
        headers['X-CSRFToken'] = response.json()['csrf_token']
    response = session.request(method, BASE + path, headers=headers, timeout=20,
                               allow_redirects=False, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f'{method} {path}: expected HTTP {expected}, received {response.status_code}')
    return response


def run():
    os.chdir(ROOT)
    load_dotenv(ROOT / '.env', override=True)
    from utils.staging_mode import staging_safe, validate_staging_config
    if not staging_safe():
        raise RuntimeError('Restricted staging must be enabled')
    validate_staging_config(ROOT)
    if os.getenv('DOMAINXPERT_PUBLIC_SIGNUP', '').lower() != 'true':
        raise RuntimeError('Staging signup must be enabled')
    from database.account_broker_db import get_groww_credentials
    from database.user_db import find_user_by_exact_username, db_session
    suffix = secrets.token_hex(5)
    users = [f'smoke_a_{suffix}', f'smoke_b_{suffix}']
    passwords = ['Aa1!' + secrets.token_urlsafe(24) for _ in users]
    credentials = [(f'demo-{user}', f'demo-secret-{user}') for user in users]
    sessions = [client(), client()]
    anonymous = client()
    try:
        # Confirm the running service is actually restricted, not just this env.
        call(anonymous, 'GET', '/positions', expected=403)
        call(anonymous, 'GET', '/socket.io/?EIO=4&transport=polling', expected=403)
        call(anonymous, 'GET', '/api/account/brokers/groww', expected=401)
        print('PASS: Restricted routes and anonymous credential access blocked')
        for session, user, password, (key, secret) in zip(sessions, users, passwords, credentials):
            body = dict(username=user, email=user + '@example.com', password=password,
                        confirm_password=password, is_admin=True)
            call(session, 'POST', '/auth/signup', expected=201, csrf=True, json=body)
            response = call(session, 'POST', '/auth/login', csrf=True,
                            data={'username': user, 'password': password})
            check(response.json().get('status') == 'success', 'New account can sign in')
            status = call(session, 'GET', '/auth/session-status').json()
            check(status.get('user') == user and status.get('authenticated'), 'Session has correct account')
            config = call(session, 'GET', '/auth/broker-config').json()
            check(config.get('staging_restricted') is True, 'Running server confirms restricted staging')
            call(session, 'PUT', '/api/account/brokers/groww', csrf=True,
                 json={'api_key': key, 'api_secret': secret})
            visible = call(session, 'GET', '/api/account/brokers/groww').json()
            check(visible.get('configured') is True and 'api_key' not in visible and 'api_secret' not in visible,
                  'Credentials saved without returning secrets')
            check(find_user_by_exact_username(user).is_admin is False, 'Signup ignored supplied admin role')
        # Owner fields in the payload must not redirect Alice's write to Bob.
        replacement = ('demo-attempt-key', 'demo-attempt-secret')
        call(sessions[0], 'PUT', '/api/account/brokers/groww', csrf=True,
             json={'username': users[1], 'user_id': users[1],
                   'api_key': replacement[0], 'api_secret': replacement[1]})
        db_session.remove()
        check(get_groww_credentials(users[0]) == replacement, 'Write stayed with authenticated account')
        check(get_groww_credentials(users[1]) == credentials[1], 'Other account credentials unchanged')
        call(sessions[0], 'PUT', '/api/account/brokers/groww', expected=400,
             json={'api_key': 'demo-no-csrf', 'api_secret': 'demo-no-csrf'})
        db_session.remove()
        check(get_groww_credentials(users[0]) == replacement, 'Missing-CSRF write rejected without mutation')
        print('HTTP staging smoke check completed. Dummy accounts retained:', ', '.join(users))
        print('This does not verify broker trading, order fills, log export or WebSocket tenant isolation.')
    finally:
        for session in sessions + [anonymous]:
            session.close()
        db_session.remove()


if __name__ == '__main__':
    try:
        run()
    except (RuntimeError, requests.RequestException, ValueError, KeyError) as error:
        # Never print response bodies, credentials or request objects.
        print('STOP:', str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1)
