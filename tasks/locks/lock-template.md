# Lock File Template

Filename format:
`<agent>+<taskid>.lock`

Examples:
- `codex+t0316.p10.lock`
- `claude+t0316.p11.lock`

Content template:

```yaml
agent: codex
task: t0316.p10
owner: Codex
project: demo-project
created_at: 260316185749
updated_at: 260316185749
status: doing
log: tasks/codex/t0316.p10.md
```

Rules:
- each agent may have only one active lock
- scan your own lock before claiming a new task
- if task is already done/cancelled, remove your lock
- if task is unfinished, resume it directly
- no takeover by other AI
