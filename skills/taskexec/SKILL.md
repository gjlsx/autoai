---
name: taskexec
description: Use when creating or executing any tasklist with strict compliance to .agent-rules.md and tasklist_rules.md, including lock, claim, test-first execution, self-review, tasklist field updates, and unlock.
---

# Tasklist Execution

Follow this workflow exactly when asked to build a tasklist or execute tasks from a tasklist.

## Required Inputs

Read in this order before any action:
1. `D:\work\aiwork\autoai\.agent-rules.md`
2. `D:\work\aiwork\autoai\tasklist_rules.md`
3. Target tasklist file (for example: `D:\work\aiwork\autoai\tasklist03182317.md`)
4. `D:\work\aiwork\autoai\memorys\global.md` (and only related project memory if needed)

## Mode A: Build Tasklist

Use this mode when the request is to create a new tasklist.

1. Use required tasklist structure:
   1) Overall task name
   2) Overall description
   3) Generation time
   4) Tasklist status and inheritance source
   5) Participant roles
   6) Decomposed task table
2. Keep table structure unchanged:
   `Status | TaskID | Project | Title | Description | Type | Priority | Role | Owner | Depends | module | Claim | Finish | Report | Git | Review | Score`
3. Enforce field rules:
   - `TaskID`: `tYYMMDD.pXXX`
   - `Claim`: `startat:YYMMDDHHMMSS <agent> tasks/<agent>/<taskid>.md`
   - `Finish`: `finishat:YYMMDDHHMMSS`
   - `Review`: one of `pass:no-refactor-needed`, `pass:minor-refactor-done`, `partial:needs-followup`
   - `Git`: commit hash
4. Enforce status vocabulary only:
   - `todo`, `doing`, `blocked`, `partial`, `pending`, `done`, `cancelled`
5. Plan tasks with test-first principle:
   - Define expected input/output and validation path before implementation details.

## Mode B: Execute Tasklist

Use this mode when the request is to run tasks in an existing tasklist.

### Startup Sequence

1. Read `.agent-rules.md`
2. Read `tasklist_rules.md`
3. Read target tasklist
4. Read memory files required by rule
5. Scan `tasks/locks/` for own lock: `<agent>_<taskid>.lock`
6. If own unfinished lock exists, resume that task first
7. If no own lock exists, pick first eligible `todo` task for own role
8. Check dependencies (`Depends` must be all `done`)
9. Confirm no lock exists for the same task from other agents (for example `claude_<taskid>.lock` or `cline_<taskid>.lock`)
10. Create own lock
11. Claim task
12. Execute task
13. Run required tests
14. Run self-review
15. If refactor needed, repeat execute -> test -> self-review
16. Update tasklist allowed fields
17. Remove lock

### Lock Rules

- One agent can have only one active lock.
- Never take over other agent lock.
- Lock file pattern: `<agent>_<taskid>.lock`

### Allowed Tasklist Updates (Executor)

Only update:
- `Owner`
- `Status`
- `Claim`
- `Finish`
- `Report`
- `Git`
- `Review`
- `Score`

Do not modify tasklist table structure.

### Allowed File Modifications

Only modify files required by rule and task:
- own task log: `tasks/<agent>/...`
- own lock: `tasks/locks/<agent>_<taskid>.lock`
- allowed tasklist fields in the target tasklist file
- code/tests/docs directly required by the claimed task

### Testing and Done Rules

- Never mark `done` unless required tests pass.
- If no tests exist, add minimal validation or record clear manual evidence.
- Self-review must explicitly check:
  - requirement satisfied
  - tests passed
  - no obvious duplicate logic left unhandled
  - naming consistent
  - no required refactor remains
  - task log complete
- Task is `done` only if all are true:
  - implementation complete
  - tests passed
  - self-review passed
  - task log written
  - tasklist updated
  - lock removed

## Forbidden Actions

- Do not create extra tasks unless asked to build tasklist.
- Do not modify other agent logs.
- Do not modify other agent locks.
- Do not change tasklist table schema.
- Do not mark `done` without passing verification.

## One-Line Invocation

Use this exact pattern:
- `Use taskexec to run D:\work\aiwork\autoai\tasklist03182327.md`
- `Use taskexec to build tasklist , "task info..."`
