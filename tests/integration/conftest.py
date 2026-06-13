"""Shared fixtures for integration tests (real Flask app + in-memory DB)."""
import importlib
import pkgutil

import pytest

import app.models as _models
from app import create_app
from app.extensions import db as _db
from app.models.user import User

# Import every model module so the full table set (incl. cross-FK targets like
# `job`/`customer`, which app.models.__init__ doesn't import) is registered in
# db.metadata before create_all() runs. Without this, create_all() fails with
# NoReferencedTableError on invoice's FKs.
for _mod in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f'app.models.{_mod.name}')


@pytest.fixture
def app():
    """App bound to the in-memory sqlite TestingConfig, with a fresh schema."""
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def user(db):
    """A minimal sync-mode user (sync mode skips catalogue sync side effects)."""
    u = User(email='tester@example.com', password_hash='x', platform_mode='sync')
    db.session.add(u)
    db.session.commit()
    return u
