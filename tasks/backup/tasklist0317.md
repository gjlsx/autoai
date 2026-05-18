# Multi-AI 任務發布 03172017（

## 1) 總體任務名字
Multi-AI Worker Function Loop Validation 0317

## 2) 總體任務描述
本 tasklist 用於驗證多 AI 協作任務循環是否正確執行。  
每個任務都必須實現在 AI 自己的 worker 檔案中，以 Python 函數完成並可執行輸出結果。

## 3) 生成時間
2026-03-17

## 4) tasklist 狀態 / 繼承
- 狀態：執行中
- 繼承自：無（新建）
- 全部task done之後 ，本文檔需要歸檔至：`tasks/backup/`

## 5) 參與角色
- claude
- cline
- codex

## 6) 執行與約束規則
- 任務總數：5（`t1`~`t5`）
- 每個 AI 同時只能持有 1 個任務 lock
- lock 文件格式：`tasks/locks/<agent>_<taskid>.lock`
- AI 只允許修改自己的 .py 文件：

- 每個任務必須在對應 .py 中實作為函數，命名自定：

- .py 函數中 必須輸出：
  - `agent: <ainame>`
  - `tasks: ...`
  - `results:`
  - `<taskid>=<value>`
  - `subtotal=<value>`

## 7) 任務列表

| Status | TaskID | Project | Title | Description | Type | Priority | Role | Owner | Depends | module | Claim | Finish | Report | Git | Review | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| done | t03172017.t1 | autoai-multi-ai-0317 | Sum digits of 5732 | 輸入 `5732`，計算所有數字之和，輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | startat:260317021215 cline tasks/cline/t03172017.t1.md | finishat:260317021314 | agent: cline, t1=17 |  | pass:no-refactor-needed | 100/100 |
| done | t03172017.t2 | autoai-multi-ai-0317 | Asc sort 8461 | 輸入 `8461`，按升序排序，輸出整數（`1468`） | feature | P0 | claude/cline/codex | cline |  | backend | startat:260317021332 cline tasks/cline/t03172017.t2.md | finishat:260317021418 | agent: cline, t2=1468 |  | pass:no-refactor-needed | 100/100 |
| done | t03172017.t3 | autoai-multi-ai-0317 | Sum even digits of 2907 | 輸入 `2907`，計算所有偶數數字之和（`2+0`） | feature | P0 | claude/cline/codex | claude |  | backend | startat:260317001500 claude tasks/claude/t3.md | finishat:260317001600 | t3=2 |  | pass:no-refactor-needed | 100/100 |
| done | t03172017.t4 | autoai-multi-ai-0317 | Reverse 6318 | 輸入 `6318`，反轉數字順序，輸出整數（`8136`） | feature | P0 | claude/cline/codex | claude |  | backend | startat:260317000000 claude tasks/claude/t4.md | finishat:260317000500 | t4=8136 |  | pass:no-refactor-needed | 100/100 |
| done | t03172017.t5 | autoai-multi-ai-0317 | Multiply t1 and t3 | 依賴任務：`t5 = t1_result * t3_result` | feature | P0 | claude/cline/codex | cline | t1,t3 | backend | startat:260317021541 cline tasks/cline/t03172017.t5.md | finishat:260317021622 | agent: cline, t5=34 |  | pass:no-refactor-needed | 100/100 |

## 8) 依賴規則
- `t5` 依賴 `t1,t3`
- 若 `t1` 或 `t3` 未完成（非 `done`），不可認領 `t5`

## 9) 任務結果預期值（驗證用）
- `t1=17`
- `t2=1468`
- `t3=2`
- `t4=8136`
- `t5=34`

## 10) 最終匯總規則
`FINAL = t1 + t2 + t3 + t4 + t5`

系統輸出必須包含：

`FINAL_RESULT=9657`

