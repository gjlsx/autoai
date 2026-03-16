#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pymysql

from cloud_orchestrator.config import load_settings


def _normalize_sql(stmt: str) -> str:
    text = stmt
    text = text.replace("ADD COLUMN IF NOT EXISTS ", "ADD COLUMN ")
    text = text.replace("CREATE INDEX IF NOT EXISTS ", "CREATE INDEX ")
    text = text.replace("CREATE UNIQUE INDEX IF NOT EXISTS ", "CREATE UNIQUE INDEX ")
    return text


def _is_safe_duplicate_error(exc: Exception) -> bool:
    if not isinstance(exc, (pymysql.err.ProgrammingError, pymysql.err.OperationalError)):
        return False
    code = exc.args[0] if exc.args else None
    # duplicate column / duplicate key name / duplicate index name
    return code in {1060, 1061, 1831}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_sql_migration.py <sql_file>")

    sql_file = Path(sys.argv[1])
    if not sql_file.exists():
        raise SystemExit(f"sql file not found: {sql_file}")

    settings = load_settings()
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        autocommit=True,
        charset="utf8mb4",
    )
    try:
        sql_text = sql_file.read_text(encoding="utf-8")
        statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
        with conn.cursor() as cur:
            for stmt in statements:
                normalized = _normalize_sql(stmt)
                try:
                    cur.execute(normalized)
                except Exception as exc:
                    if _is_safe_duplicate_error(exc):
                        continue
                    raise
        print(f"migration applied: {sql_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
