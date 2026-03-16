# AutoAI Redis Feedback Skill

## Purpose
When the AI finishes a turn (or has a mid-step update), push a structured event to Redis.
`redis_to_mysql_feedback_bridge.py` then writes it into MySQL `ai_feedback`.

## Command Template
Use this command from the project root:

```powershell
python scripts/skill_emit_to_redis.py --source-ai codex --task-id "<task_id>" --sessionid "<sessionid>" --event output --text "<final_or_delta_text>"
```

## Event Types
- `output`: normal AI answer or delta
- `ask`: question back to user
- `system`: error/alert

## Notes
- This skill does not write MySQL directly.
- MySQL insert is handled by `scripts/redis_to_mysql_feedback_bridge.py`.
- Keep payload plain text; bridge keeps original text in `ai_feedback.payload`.

