#!/usr/bin/env bash
set -euo pipefail
cd ~/autoai
source .venv/bin/activate
curl -sS http://127.0.0.1:18080/healthz; echo
python - <<'PY'
from cloud_orchestrator.config import load_settings
from cloud_orchestrator import db
s = load_settings()
c1 = db.connect(s)
c2 = db.connect(s)
print('test2_same_conn=', c1 is c2)
c1.close()
rows = db.fetch_undelivered_feedback(s, limit=1)
print('test3_reconnect_ok=', isinstance(rows, list), 'rows=', len(rows))
PY