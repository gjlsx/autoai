#!/usr/bin/env bash
set -euo pipefail
cd ~/autoai
source .venv/bin/activate
python - <<'PY'
import pymysql
from cloud_orchestrator.config import load_settings
s = load_settings()
conn = pymysql.connect(host=s.mysql_host,port=s.mysql_port,user=s.mysql_user,password=s.mysql_password,database=s.mysql_db,autocommit=True,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
try:
    with conn.cursor() as cur:
        cur.execute("UPDATE ai_feedback SET delivered_tg=1, delivered_tg_at=NOW() WHERE source_ai IN ('deploy_probe','deploy_probe2')")
        print('marked_delivered=', cur.rowcount)
        cur.execute("DELETE FROM ai_feedback WHERE source_ai IN ('deploy_probe','deploy_probe2')")
        print('deleted_rows=', cur.rowcount)
finally:
    conn.close()
PY

curl -sS http://127.0.0.1:18080/healthz
python - <<'PY'
from cloud_orchestrator.config import load_settings
from cloud_orchestrator import db
s = load_settings()
rows = db.fetch_undelivered_feedback(s, limit=1)
print('fetch_undelivered_feedback_ok count=', len(rows))
PY