#!/bin/bash
set -e

echo "Checking database migration state..."

# Check if alembic_version table exists in the database
python3 << 'PYEOF'
from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        result = db.session.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar()
        print(f"Alembic version table exists with {result} rows")
        if result == 0:
            print("Stamping database at head...")
            import subprocess
            subprocess.run(["python", "-m", "flask", "db", "stamp", "head"], check=True)
            print("Stamped at head")
    except Exception as e:
        print(f"No alembic_version table found - stamping database at head: {e}")
        import subprocess
        subprocess.run(["python", "-m", "flask", "db", "stamp", "head"], check=True)
        print("Stamped at head")
PYEOF

echo "Running migrations..."
python -m flask db upgrade
echo "Migrations complete - starting gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 --access-logfile - --error-logfile - --log-level debug wsgi:app
