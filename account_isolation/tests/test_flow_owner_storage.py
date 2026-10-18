"""Real SQLite workflow ownership storage. No workflows activated or executed."""
import importlib
import sys
import pytest
from sqlalchemy import inspect, text


@pytest.fixture
def flows(main_app):
    old = sys.modules.pop('database.flow_db', None)
    if old:
        old.db_session.remove()
    module = importlib.import_module('database.flow_db')
    module.Base.metadata.create_all(module.engine)
    module.migrate_workflow_owner_column()
    yield module
    module.db_session.remove()
    module.engine.dispose()


def test_account_lists_and_id_lookup_exclude_other_owner(flows):
    a = flows.create_workflow('Alice flow', owner_username='alice')
    b = flows.create_workflow('Bob flow', owner_username='bob')
    assert a and b
    assert [w.id for w in flows.get_account_workflows('alice')] == [a.id]
    assert flows.get_account_workflow(b.id, 'alice') is None
    assert flows.get_account_workflow(a.id, 'bob') is None
    assert flows.get_account_workflow(a.id, 'alice').name == 'Alice flow'


@pytest.mark.parametrize('owner', [None, '', 'missing'])
def test_account_creation_requires_existing_owner(flows, owner):
    with pytest.raises(ValueError):
        flows.create_workflow('Unowned', owner_username=owner)
    assert flows.get_all_workflows() == []


def test_unknown_read_owner_rejected(flows):
    with pytest.raises(ValueError):
        flows.get_account_workflows('missing')
    with pytest.raises(ValueError):
        flows.get_account_workflow(1, None)


def test_legacy_ownerless_workflow_not_auto_assigned(flows, monkeypatch):
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'false')
    monkeypatch.setenv('DOMAINXPERT_ACCOUNT_MODES', 'false')
    legacy = flows.create_workflow('Legacy')
    assert legacy.owner_username is None
    monkeypatch.setenv('DOMAINXPERT_PER_USER_GROWW', 'true')
    assert flows.get_account_workflow(legacy.id, 'alice') is None
    assert flows.get_account_workflows('bob') == []


def test_old_schema_migration_preserves_rows_and_is_repeatable(flows):
    flows.db_session.remove()
    flows.Base.metadata.drop_all(flows.engine)
    with flows.engine.begin() as conn:
        conn.execute(text('CREATE TABLE flow_workflows (id INTEGER PRIMARY KEY, name VARCHAR(255))'))
        conn.execute(text("INSERT INTO flow_workflows(id,name) VALUES (1,'Legacy')"))
    flows.migrate_workflow_owner_column()
    flows.migrate_workflow_owner_column()
    assert 'owner_username' in {c['name'] for c in inspect(flows.engine).get_columns('flow_workflows')}
    with flows.engine.connect() as conn:
        assert conn.execute(text('SELECT name,owner_username FROM flow_workflows')).all() == [('Legacy', None)]
