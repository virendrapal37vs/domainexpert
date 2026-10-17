import importlib
import sys
from sqlalchemy import create_engine, text
import pytest


@pytest.fixture
def logs(main_app, monkeypatch):
    sys.modules.pop('database.apilog_db', None)
    module = importlib.import_module('database.apilog_db')
    module.Base.metadata.create_all(module.engine)
    monkeypatch.setattr(importlib.import_module('database.auth_db'), 'verify_api_key', lambda key: {'alice-key': 'alice', 'bob-key': 'bob'}.get(key))
    yield module
    module.db_session.remove()
    module.engine.dispose()
    module.executor.shutdown(wait=True)


def test_event_and_request_key_ownership(logs):
    logs.async_log_order('placeorder', {'symbol': 'ALICE'}, {}, api_key='alice-key')
    request = {'symbol': 'BOB', 'apikey': 'bob-key', 'username': 'alice'}
    logs.async_log_order('quotes', request, {})
    logs.async_log_order('old', {}, {})
    assert logs.account_order_log_query(username='alice').count() == 1
    bob = logs.account_order_log_query(api_key='bob-key').one()
    assert 'BOB' in bob.request_data
    assert 'bob-key' not in bob.request_data
    assert request['apikey'] == 'bob-key'


def test_invalid_key_is_unowned_and_cannot_query(logs):
    logs.async_log_order('quotes', {'apikey': 'invalid', 'username': 'alice'}, {})
    assert logs.account_order_log_query(username='alice').count() == 0
    with pytest.raises(ValueError):
        logs.account_order_log_query(api_key='invalid')


def test_migration_preserves_old_log(logs, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'old-api.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE order_logs (id INTEGER PRIMARY KEY, request_data TEXT)'))
        connection.execute(text("INSERT INTO order_logs VALUES (1, 'old')"))
    logs.ensure_order_log_owner_column(engine)
    logs.ensure_order_log_owner_column(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT request_data, username FROM order_logs')).one() == ('old', None)
    engine.dispose()


def test_legacy_visibility(logs, monkeypatch):
    logs.async_log_order('old', {}, {})
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert logs.account_order_log_query().count() == 1
