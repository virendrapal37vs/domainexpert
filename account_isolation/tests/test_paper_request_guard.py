"""Durable paper claims: concurrent requests, restart and owner binding."""
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from flask import Flask
from sqlalchemy import create_engine, select, func
from services import paper_request_guard as guard


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'claims.db'))
    monkeypatch.setitem(sys.modules, 'database.sandbox_db', SimpleNamespace(engine=engine))
    app = Flask(__name__)
    app.secret_key = 'test-request-claims'
    yield app, engine
    engine.dispose()


def test_claim_replay_survives_new_process(guarded):
    app, engine = guarded
    with app.app_context():
        token = guard.issue_token('alice', 'fixed')
        assert guard.claim_request(token, 'alice', 'fixed') is None
        engine.dispose()
        import subprocess
        code = '''
import sys
from types import SimpleNamespace
from flask import Flask
from sqlalchemy import create_engine
sys.modules['database.sandbox_db'] = SimpleNamespace(engine=create_engine(sys.argv[1]))
from services.paper_request_guard import claim_request
app=Flask(__name__);app.secret_key='test-request-claims'
with app.app_context():
    assert claim_request(sys.argv[2], 'alice', 'fixed')[1] == 409
'''
        result = subprocess.run([sys.executable, '-c', code, str(engine.url), token],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert guard.claim_request(token, 'alice', 'fixed')[1] == 409
        assert guard.claim_request(guard.issue_token('alice', 'fixed'), 'alice', 'fixed') is None


def test_claim_owner_kind_and_signature(guarded):
    app, engine = guarded
    with app.app_context():
        token = guard.issue_token('alice', 'fixed')
        for value, owner, kind in [(None,'alice','fixed'), (token,'bob','fixed'),
                                   (token,'alice','groww'), ('invalid','alice','fixed')]:
            assert guard.claim_request(value, owner, kind)[1] == 400
        assert guard.claim_request(token,'alice','fixed') is None
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(guard.claims)) == 1


def test_concurrent_duplicate_has_one_winner(guarded):
    app, engine = guarded
    guard.claims.create(engine, checkfirst=True)
    with app.app_context():
        token = guard.issue_token('alice','groww')
    def claim(_):
        with app.app_context():
            return guard.claim_request(token,'alice','groww')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert results.count(None) == 1
    assert sum(result is not None and result[1] == 409 for result in results) == 3


def test_expired_token_and_database_failure(guarded, monkeypatch):
    app, engine = guarded
    with app.app_context():
        monkeypatch.setattr('itsdangerous.timed.time.time', lambda: 1000)
        token = guard.issue_token('alice','fixed')
        monkeypatch.setattr('itsdangerous.timed.time.time', lambda: 5000)
        assert guard.claim_request(token,'alice','fixed')[1] == 400
        token = guard.issue_token('alice','fixed')
        from sqlalchemy.exc import OperationalError
        def failed(*args, **kwargs):
            raise OperationalError('unavailable', {}, None)
        monkeypatch.setattr(guard.claims, 'create', failed)
        assert guard.claim_request(token,'alice','fixed')[1] == 503
