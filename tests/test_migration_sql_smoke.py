from pathlib import Path


def test_migration_contains_delivery_columns():
    sql = Path("migrations/2026-03-02-fastapi-orchestrator.sql").read_text(encoding="utf-8")
    assert "delivered_tg" in sql
    assert "idempotency_key" in sql
    assert "sessionid" in sql.lower()
    assert "idx_ai_tasks_sessionid" in sql
    assert "idx_ai_feedback_sessionid" in sql
