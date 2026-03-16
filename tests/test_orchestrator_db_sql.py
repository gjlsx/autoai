from cloud_orchestrator.db import SQL


def test_insert_task_sql_targets_ai_tasks():
    assert "INSERT INTO ai_tasks" in SQL.INSERT_TASK
    assert "ai_target" in SQL.INSERT_TASK
    assert "message" in SQL.INSERT_TASK
    assert "sessionid" in SQL.INSERT_TASK


def test_select_feedback_sql_filters_undelivered():
    normalized = SQL.SELECT_UNDELIVERED_FEEDBACK.replace(" ", "")
    assert "FROMai_feedback" in normalized
    assert "WHEREf.delivered_tg=0" in normalized
    assert "f.sessionid" in SQL.SELECT_UNDELIVERED_FEEDBACK
