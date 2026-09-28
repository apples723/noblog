import importlib
import os
import sys

import pytest

# Ensure the repo root is importable so `import app` works when pytest runs from
# the tests/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_app(tmp_path, token=None):
    """Reload the app module with a fresh temp DB (and optional write token).

    app.py reads DB_PATH and NOBLOG_WRITE_TOKEN at import time, so env vars must
    be set before importlib.reload runs to get clean module state per test."""
    os.environ['NOBLOG_DB_PATH'] = str(tmp_path / 'blog.db')
    if token is None:
        os.environ.pop('NOBLOG_WRITE_TOKEN', None)
    else:
        os.environ['NOBLOG_WRITE_TOKEN'] = token

    import app as app_module
    importlib.reload(app_module)
    app_module.init_db()
    return app_module


@pytest.fixture
def app_module(tmp_path):
    """App with auth disabled (no NOBLOG_WRITE_TOKEN)."""
    module = _load_app(tmp_path, token=None)
    yield module


@pytest.fixture
def client(app_module):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


TEST_TOKEN = 'secret-write-token'


@pytest.fixture
def app_module_token(tmp_path):
    """App with NOBLOG_WRITE_TOKEN configured."""
    module = _load_app(tmp_path, token=TEST_TOKEN)
    yield module


@pytest.fixture
def client_token(app_module_token):
    app_module_token.app.config['TESTING'] = True
    with app_module_token.app.test_client() as c:
        yield c
