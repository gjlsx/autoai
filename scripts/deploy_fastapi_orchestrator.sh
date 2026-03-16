#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f ".env" ]]; then
  echo ".env not found in current directory"
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Applying migration..."
.venv/bin/python scripts/run_sql_migration.py migrations/2026-03-02-fastapi-orchestrator.sql

sudo cp deploy/systemd/autoai-fastapi-orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autoai-fastapi-orchestrator
sudo systemctl restart autoai-fastapi-orchestrator
sudo systemctl status autoai-fastapi-orchestrator --no-pager
