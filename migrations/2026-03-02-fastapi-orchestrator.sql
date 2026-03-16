CREATE TABLE IF NOT EXISTS ai_tasks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    ai_target VARCHAR(64) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    dispatched_at DATETIME NULL,
    finished_at DATETIME NULL,
    last_error TEXT NULL
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_feedback (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id VARCHAR(128) NULL,
    source_ai VARCHAR(64) NULL,
    channel VARCHAR(32) NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) DEFAULT CHARSET=utf8mb4;

ALTER TABLE ai_tasks ADD COLUMN source_channel VARCHAR(32) NULL;
ALTER TABLE ai_tasks ADD COLUMN source_chat_id VARCHAR(64) NULL;
ALTER TABLE ai_tasks ADD COLUMN source_user_id VARCHAR(64) NULL;
ALTER TABLE ai_tasks ADD COLUMN idempotency_key VARCHAR(128) NULL;
ALTER TABLE ai_tasks ADD COLUMN sessionid VARCHAR(77) NULL;

ALTER TABLE ai_feedback ADD COLUMN delivered_tg TINYINT NOT NULL DEFAULT 0;
ALTER TABLE ai_feedback ADD COLUMN delivered_tg_at DATETIME NULL;
ALTER TABLE ai_feedback ADD COLUMN sessionid VARCHAR(77) NULL;

CREATE INDEX idx_tasks_status_priority ON ai_tasks(status, priority, id);
CREATE INDEX idx_feedback_delivered ON ai_feedback(delivered_tg, id);
CREATE INDEX idx_ai_tasks_sessionid ON ai_tasks(status, ai_target, sessionid, id);
CREATE INDEX idx_ai_feedback_sessionid ON ai_feedback(task_id, sessionid, id);
CREATE UNIQUE INDEX uq_tasks_idempotency_key ON ai_tasks(idempotency_key);
