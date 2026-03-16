#!/usr/bin/env bash
set -euo pipefail
cd ~/autoai

python3 --version

sudo systemctl restart autoai-fastapi-orchestrator
sudo systemctl status autoai-fastapi-orchestrator --no-pager -l | sed -n '1,25p'

curl -sS http://127.0.0.1:18080/healthz || true

source .venv/bin/activate
python - <<'PY'
import time
from cloud_orchestrator.config import load_settings
from cloud_orchestrator import db
s = load_settings()

t0 = time.time()
for i in range(50):
    db.fetch_undelivered_feedback(s, limit=1)
print('fetch50_elapsed_sec=', round(time.time()-t0, 3))

t0 = time.time()
for i in range(50):
    db.insert_system_feedback(s, None, 'deploy_probe', f'deploy-probe-{i}')
print('insert50_elapsed_sec=', round(time.time()-t0, 3))
PY

sudo journalctl -u autoai-fastapi-orchestrator -n 80 --no-pager