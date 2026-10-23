"""Run as a FILE in the staging venv. Never paste secrets into chat or shell history."""
import getpass
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
import warnings

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
from dotenv import load_dotenv, set_key
from sqlalchemy.engine import make_url
import requests


def main():
    warnings.simplefilter('error', getpass.GetPassWarning)
    env = root / '.env'
    load_dotenv(env, override=True)
    from utils.staging_mode import staging_safe, validate_staging_config
    if not staging_safe():
        raise SystemExit('STOP: Restricted staging required.')
    validate_staging_config(root)
    if os.getenv('DOMAINXPERT_MANUAL_SUBSCRIPTIONS', '').lower() != 'true':
        raise SystemExit('STOP: Enable and verify the subscription gate first.')
    if os.getenv('DOMAINXPERT_RAZORPAY_TEST', '').lower() == 'true':
        raise SystemExit('STOP: Already enabled; do not rotate payment secrets casually.')
    key = input('Razorpay TEST Key ID (rzp_test_...): ').strip()
    secret = getpass.getpass('TEST Key Secret (hidden): ').strip()
    webhook = getpass.getpass('Webhook secret, at least 32 characters (hidden): ').strip()
    if not re.fullmatch(r'rzp_test_[A-Za-z0-9]+', key) or not secret or len(webhook) < 32:
        raise SystemExit('STOP: Invalid test keys or webhook secret.')
    try:
        with requests.Session() as client:
            client.trust_env = False
            response = client.get('https://api.razorpay.com/v1/orders', params={'count':1},
                auth=(key,secret), timeout=(5,20), allow_redirects=False)
            if response.status_code != 200:
                raise SystemExit('STOP: Test credentials were not accepted. Configuration unchanged.')
    except requests.RequestException:
        raise SystemExit('STOP: Cannot reach Razorpay. Configuration unchanged.') from None
    source = Path(make_url(os.environ['DATABASE_URL']).database).resolve()
    if not source.is_file() or source.parent != root / 'db' or not source.name.startswith('staging-'):
        raise SystemExit('STOP: Staging database not found.')
    os.umask(0o077)
    folder = Path.home() / 'domainxpert-staging-backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '-' + secrets.token_hex(3)
    backup = folder / f'staging-before-razorpay-{stamp}.db'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(backup) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('STOP: Backup failed integrity check.')
    config_backup = folder / f'staging-before-razorpay-{stamp}.env'
    shutil.copyfile(env, config_backup)
    config_backup.chmod(0o600)
    for name, value in [('RAZORPAY_KEY_ID',key),('RAZORPAY_KEY_SECRET',secret),
            ('RAZORPAY_WEBHOOK_SECRET',webhook),('DOMAINXPERT_RAZORPAY_TEST','true')]:
        if not set_key(str(env), name, value)[0]:
            shutil.copyfile(config_backup,env)
            env.chmod(0o600)
            raise SystemExit('STOP: Configuration restored after write failure.')
    env.chmod(0o600)
    print('PASS: Test credentials verified; no real payment created.')
    print('PASS: Database and configuration backups saved in', folder)
    print('PASS: Razorpay TEST checkout configured. Restart domainxpert-staging.')


if __name__ == '__main__':
    main()
