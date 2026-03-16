#!/usr/bin/env bash
set -euo pipefail
cd ~/autoai
source .venv/bin/activate
python - <<'PY'
import time
from cloud_orchestrator.config import load_settings
from cloud_orchestrator import db
s = load_settings()

t0 = time.time()
for i in range(100):
    db.fetch_undelivered_feedback(s, limit=1)
print('fetch100_elapsed_sec=', round(time.time()-t0, 3))

t0 = time.time()
for i in range(100):
    db.insert_system_feedback(s, None, 'deploy_probe2', f'deploy2-probe-{i}')
print('insert100_elapsed_sec=', round(time.time()-t0, 3))
PY

python - <<'PY'
import pymysql
from cloud_orchestrator.config import load_settings
s = load_settings()
conn = pymysql.connect(host=s.mysql_host,port=s.mysql_port,user=s.mysql_user,password=s.mysql_password,database=s.mysql_db,autocommit=True,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
try:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, payload, created_at
            FROM ai_feedback
            WHERE source_ai='cloud_orchestrator'
              AND payload LIKE 'outbound loop error:%'
            ORDER BY id DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        print('recent_outbound_errors_count=', len(rows))
        for r in rows:
            print(r['id'], r['created_at'], r['payload'][:160])
finally:
    conn.close()
PY

sudo journalctl -u autoai-fastapi-orchestrator -n 60 --no-pager | grep -i "outbound loop error" || true