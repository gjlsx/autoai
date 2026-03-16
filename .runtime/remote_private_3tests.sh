#!/usr/bin/env bash
set -euo pipefail
cd ~/autoai
source .venv/bin/activate

# Test 1: service health
curl -sS http://127.0.0.1:18080/healthz

# Test 2 + 3: DB singleton reuse + reconnect
python - <<'PY'
from cloud_orchestrator.config import load_settings
from cloud_orchestrator import db

s = load_settings()

# Test 2: same process should reuse same connection object
c1 = db.connect(s)
c2 = db.connect(s)
print('test2_same_conn=', c1 is c2)

# Test 3: close current conn, next call should reconnect and still work
c1.close()
rows = db.fetch_undelivered_feedback(s, limit=1)
print('test3_reconnect_ok=', isinstance(rows, list), 'rows=', len(rows))
PY