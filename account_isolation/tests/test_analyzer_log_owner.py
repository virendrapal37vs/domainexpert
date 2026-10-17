import importlib
import sys
from sqlalchemy import create_engine, text, inspect
import pytest


@pytest.fixture
def logs(main_app, monkeypatch):
    sys.modules.pop('database.analyzer_db', None)
    module = importlib.import_module('database.analyzer_db')
    module.Base.metadata.create_all(module.engine)
    monkeypatch.setattr(importlib.import_module('database.auth_db'), 'verify_api_key', lambda key: {'alice-key': 'alice', 'bob-key': 'bob'}.get(key))
    module.async_log_analyzer({'symbol': 'ALICE'}, {}, api_key='alice-key')
    module.async_log_analyzer({'symbol': 'BOB'}, {}, api_key='bob-key')
    module.async_log_analyzer({'symbol': 'OLD'}, {})
    yield module
    module.db_session.remove()
    module.engine.dispose()
    module.executor.shutdown(wait=True)


def test_list_counts_and_export_query_scoped(logs):
    assert logs.account_analyzer_query(api_key='alice-key').count() == 1
    assert logs.account_analyzer_query(api_key='bob-key').count() == 1
    assert 'ALICE' in logs.account_analyzer_query(username='alice').first().request_data
    assert 'BOB' in logs.account_analyzer_query(username='bob').first().request_data


def test_clear_cannot_delete_other_user(logs):
    logs.account_analyzer_query(username='alice').delete()
    logs.db_session.commit()
    assert logs.account_analyzer_query(username='alice').count() == 0
    assert logs.account_analyzer_query(username='bob').count() == 1
    assert logs.db_session.query(logs.AnalyzerLog).count() == 2


def test_unknown_key_rejected(logs):
    with pytest.raises(ValueError):
        logs.account_analyzer_query(api_key='invalid')


def test_additive_migration_preserves_old_logs(logs, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE analyzer_logs (id INTEGER PRIMARY KEY, request_data TEXT)'))
        connection.execute(text("INSERT INTO analyzer_logs VALUES (1, 'old')"))
    logs.ensure_log_owner_column(engine)
    logs.ensure_log_owner_column(engine)
    assert 'username' in {c['name'] for c in inspect(engine).get_columns('analyzer_logs')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT request_data, username FROM analyzer_logs')).one() == ('old', None)
    engine.dispose()


def test_legacy_query_keeps_old_visibility(logs, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    assert logs.account_analyzer_query().count() == 3
