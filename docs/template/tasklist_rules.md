# Tasklist 構建規則以及參與 task 的ai執行規範
# this file is readonly !!!
# this file is readonly !!!


#> Scheduler creates and maintains the structure of this file.
> Executor may update only: Owner, Status, Claim, Finish, Report, Git, Review, Score.

# build a tasklist must doing this structure:
  1.總體任務名字  ex：# Likeshop 二开任务 0316（实施版）
  2.總體任務描述
  3.生成時間  2026-03-16
  4.該tasklist狀態(歸檔(歸檔file in /tasks/backup/ ),執行中 ?) ,該tasklist.md 
    繼承自哪一個 old  tasklist ,old tasklist帶全路徑,
  5. 參與角色name:(for example) claude ,codex ,gemini, ai4_name 

  6.分解任務，制定任務列表，這時候可以用合適skills/mcp 等輔助，核心標準是先框架后細節，模塊化開發，測試優先，執行任務需要先寫測試再寫實際内容來滿足測試的輸入輸出結果 


| TaskID | Project | Title | Description | Type | Priority | Role | Owner | Depends | Status |module| Claim | Finish | Report | Git | Review | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t0316.p10 | demo-project | Add schema sync command | Add idempotent schema sync entrypoint and tests | feature | P0 | codex ||| todo |front ||  |  |  |  |
| t0316.p11 | demo-project | Write migration docs | Document migration usage and rollback notes | docs | P1 | claude |  | t0316.p10 | todo | back |  |  |  |  | |




## Field Rules
- `TaskID`: global unique id, format `tYYMMDD.pXXX`
- `Project`: current project folder name under `memorys/projects/`
- `Role`: target executor role
  `module`: which module, like: front,backend.and....
- `Depends`: comma-separated task IDs or empty
- `Claim` example:
  - `startat:260316185749 codex tasks/codex/t0316.p10.md`
- `Finish` example:
  - `finishat:260316192301`
- `Review` examples:
  - `pass:no-refactor-needed`
  - `pass:minor-refactor-done`
  - `partial:needs-followup`
- `Score` example:
  - `91/100`
  `Git`: git hash like : 82b87dc1, 6b994148 


## Status Meanings
- `todo`: not claimed
- `doing`: claimed and being worked on
- `blocked`: cannot proceed because of dependency or environment issue
- `partial`: partially completed with next steps documented
- `pending`: paused for external reasons
- `done`: completed with tests passed and self-review finished
- `cancelled`: no longer needed
