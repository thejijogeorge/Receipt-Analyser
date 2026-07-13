#!/bin/bash
set -e

echo "Waiting for database to accept connections..."
python3 - <<'EOF'
import os
import time
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])

for attempt in range(30):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Database is up.")
        break
    except Exception as e:
        print(f"DB not ready yet ({attempt+1}/30): {e}")
        time.sleep(2)
else:
    raise SystemExit("Database never became ready.")
EOF

echo "Running migrations..."
alembic upgrade head

echo "Starting app..."
exec python3 app.py
