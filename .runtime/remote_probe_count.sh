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
        cur.execute("SELECT COUNT(*) AS c FROM ai_feedback WHERE source_ai IN ('deploy_probe','deploy_probe2')")
        print('left_probe_rows=', cur.fetchone()['c'])
finally:
    conn.close()
PY