# tasktodo0203_C - 任務2（獨立文件）

## 目標
當 UI 抓取輸出不穩定時，改走「AI 顯式調用 skill -> Redis -> MySQL」通道，形成可觀測、可追蹤的回傳鏈路。

## 設計
1. AI 在回覆末尾執行 skill 命令：
   - `scripts/skill_emit_to_redis.py`
2. 橋接服務常駐：
   - `scripts/redis_to_mysql_feedback_bridge.py`
3. 橋接把 Redis 事件寫入 MySQL `ai_feedback`（保留 `task_id/sessionid/source_ai`）。
4. 若寫庫失敗，事件進 `ai_skill_feedback_retry` 便於人工追查。

## 輸出物
- Skill 規範：`skills/autoai_redis_feedback/SKILL.md`
- 發送腳本：`scripts/skill_emit_to_redis.py`
- 橋接腳本：`scripts/redis_to_mysql_feedback_bridge.py`
- 測試：
  - `tests/test_skill_emit_to_redis.py`
  - `tests/test_redis_to_mysql_feedback_bridge.py`

## 運行方式
### 1) 啟動橋接器（常駐）
```powershell
python scripts/redis_to_mysql_feedback_bridge.py
```

### 2) 由 AI/人工推一條事件到 Redis
```powershell
python scripts/skill_emit_to_redis.py --source-ai codex --task-id 123 --sessionid "matrix_ui:codex:main" --event output --text "done"
```

### 3) 單次驗證模式
```powershell
python scripts/redis_to_mysql_feedback_bridge.py --once
```

## 測試命令
```powershell
pytest -q tests/test_skill_emit_to_redis.py tests/test_redis_to_mysql_feedback_bridge.py
```

## 成功標準
- Redis 有事件入隊
- 橋接成功落 MySQL `ai_feedback`
- 異常事件進 retry 隊列，不丟失

## 本機 E2E 實測（已完成）
1. 下發：
```powershell
python scripts/skill_emit_to_redis.py --source-ai codex --task-id task2-e2e --sessionid task2:e2e --event output --text "task2-e2e-<ts>"
```
2. 橋接：
```powershell
python scripts/redis_to_mysql_feedback_bridge.py --once
```
3. 觀察結果：
- 橋接輸出：`once processed=True`
- MySQL `ai_feedback` 查到新行（`channel=skill`, `sessionid=task2:e2e`）

## 注意
- 橋接器已加 `.env` 自動回填（含舊格式備援），避免默認連到 `root@localhost`。
