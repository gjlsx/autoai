# Multi-AI 任務發布 03181000（排序數列求和驗證）

## 1) 總體任務名字
Multi-AI Sort & Arithmetic Sequence Validation 0318

## 2) 總體任務描述
本 tasklist 用於驗證多 AI 協作任務循環是否正確執行。  
輸入未排序數字列表 `[55, 15, 45, 25, 35]`，拆解為 7 個獨立子任務，每個 AI 各自負責其中一個任務，最終將所有任務結果加總，比對是否等於 **190**。  
每個任務必須實現在 AI 自己的 worker 檔案中，以 Python 函數完成並可執行輸出結果。

## 3) 生成時間
2026-03-18-10:00

## 4) tasklist 狀態 / 繼承
- 狀態：執行中
- 繼承自：無（新建）
- 全部 task done 之後，本文檔需要歸檔至：`tasks/backup/`

## 5) 參與角色
- claude
- cline
- codex

## 6) 執行與約束規則
- 輸入數列：`[55, 15, 45, 25, 35]`，排序後：`[15, 25, 35, 45, 55]`
- 任務總數：7（`t1`~`t7`）
- 每個 AI 同時只能持有 1 個任務 lock
- lock 文件格式：`tasks/locks/<agent>_<taskid>.lock`
- AI 只允許修改自己的 .py 文件
- 每個任務必須在對應 .py 中實作為函數，命名自定。
- .py 函數中必須輸出：
  - `agent: <ainame>`
  - `tasks: ...`
  - `results:`
  - `<taskid>=<value>`
  - `subtotal=<value>`

## 7) 任務列表

| Status | TaskID | Project | Title | Description | Type | Priority | Role | Owner | Depends | module | Claim | Finish | Report | Git | Review | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| done | t03181000.t1 | autoai-sort-0318 | Find 1st sorted number | 輸入 `[55,15,45,25,35]`，排序後取第一個數字（最小值），輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:12 | 03:13 | 15 | done |  |  |
| done | t03181000.t2 | autoai-sort-0318 | Find 2nd sorted number | 輸入 `[55,15,45,25,35]`，排序後取第二個數字，輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:13 | 03:14 | 25 | done |  |  |
| done | t03181000.t3 | autoai-sort-0318 | Find 3rd sorted number | 輸入 `[55,15,45,25,35]`，排序後取第三個數字，輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:14 | 03:14 | 35 | done |  |  |
| done | t03181000.t4 | autoai-sort-0318 | Infer 4th from arithmetic diff | 依賴 t1、t2、t3，計算等差數列的共同差值，推算第四個數字，輸出整數 | feature | P0 | claude/cline/codex | cline | t03181000.t1,t03181000.t2,t03181000.t3 | backend | 03:15 | 03:15 | 45 | done |  |  |
| done | t03181000.t5 | autoai-sort-0318 | Find 5th sorted number | 輸入 `[55,15,45,25,35]`，排序後取第五個數字（最大值），輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:15 | 03:16 | 55 | done |  |  |
| done | t03181000.t6 | autoai-sort-0318 | Compute common difference | 獨立計算 `[55,15,45,25,35]` 排序後等差數列的共同差值，輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:16 | 03:17 | 10 | done |  |  |
| done | t03181000.t7 | autoai-sort-0318 | Count elements | 計算 `[55,15,45,25,35]` 共有幾個元素，輸出整數 | feature | P0 | claude/cline/codex | cline |  | backend | 03:17 | 03:18 | 5 | done |  |  |

## 8) 依賴規則
- `t03181000.t4` 依賴 `t03181000.t1`、`t03181000.t2`、`t03181000.t3`
- 若 `t1`、`t2`、`t3` 任一未完成（非 `done`），不可認領 `t4`

## 9) 任務結果預期值（驗證用）
- `t1 = 15`（排序後第 1 個：最小值）
- `t2 = 25`（排序後第 2 個）
- `t3 = 35`（排序後第 3 個）
- `t4 = 45`（由 t1~t3 等差推算：差值=10，35+10=45）
- `t5 = 55`（排序後第 5 個：最大值）
- `t6 = 10`（獨立計算等差值）
- `t7 = 5`（元素總數）

## 10) 最終匯總規則
```text
FINAL = t1 + t2 + t3 + t4 + t5 + t6 + t7
```

系統輸出必須包含：

`FINAL_RESULT=190`

驗證條件：`FINAL_RESULT == 190` → 全部任務正確完成。
