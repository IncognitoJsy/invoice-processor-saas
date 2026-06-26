"""Build the schema from MIGRATIONS ONLY on the DB at $DATABASE_URL.

Neutralises db.create_all() (set to a no-op) BEFORE create_app() so the app's boot-time
create_all + inline ALTERs do NOT run (on an empty DB the inline ALTERs fail-and-pass since
their tables don't exist yet). Then runs `flask db upgrade head` — so the resulting schema is
purely what Alembic migrations produce. Read-only w.r.t. prod (operates only on the scratch DB).
"""
import os

from app.extensions import db

# Neutralise create_all before the factory runs it.
db.create_all = lambda *a, **k: None

from app import create_app  # noqa: E402
from flask_migrate import upgrade  # noqa: E402

app = create_app(os.environ.get('APP_CONFIG', 'default'))
with app.app_context():
    upgrade()  # base -> head, migrations only
    print("MIGRATIONS-ONLY UPGRADE COMPLETE")
