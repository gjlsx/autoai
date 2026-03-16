# AI 矩陣自動化控制系統 - 任務文檔與優化方案

日期: 2026-03-01  
目標: 建立可運行的「中控分發器 + 窗口橋接器 + AI 反饋工具」，支援 Redis、MySQL、用戶輸入三路任務來源，以及多個 AI CLI 管道化協作。

## 1. 系統目標

- 統一接入任務來源: Redis、MySQL、終端人工輸入。
- 精準投遞: 根據 `ai_target` 將消息路由到指定 AI 管理員窗口。
- 可追蹤: 任務狀態可在 MySQL 中追蹤（`pending -> dispatching -> dispatched`）。
- 可回寫: AI 能透過命令行工具把中間結果、最終結果與提問寫回 Redis/MySQL/終端。

## 2. 核心組件

- `dispatcher.py` (中控分發器)
- `window_bridge.py` (窗口橋接器，按窗口各啟一個進程)
- `ai_feedback.py` (AI 反饋工具)

## 3. 通訊與資料約定

### 3.1 Dispatcher -> Bridge (TCP)

- 本地回環地址 `127.0.0.1`
- 端口路由（預設）:
  - `claude -> 9001`
  - `gemini -> 9002`
  - `codex -> 9003`
- 傳輸內容:
  - 兼容純文本 `ai:message`
  - 支援 JSON payload，例如:
    ```json
    {"target":"claude","message":"檢查錯誤日誌","task_id":"t-1001","source":"redis"}
    ```

### 3.2 任務來源

- Redis:
  - 佇列鍵: `ai_task_queue`（可參數覆蓋）
  - 消費方式: `BRPOP`
- MySQL:
  - 表: `ai_tasks`
  - 狀態流轉: `pending -> dispatching -> dispatched/failed`
- User:
  - 交互輸入格式: `ai:message`

### 3.3 AI 反饋寫回

- Redis:
  - 結果鍵: `ai_results`
  - 問題鍵: `ai_questions`
- MySQL:
  - 表: `ai_feedback`
  - 欄位: `task_id`, `source_ai`, `channel`, `payload`, `created_at`

## 4. 優化方案

- 統一消息封包: 分發時將消息統一為 JSON，保留 `task_id/source/target/message`，降低多來源格式差異。
- 容錯投遞: Dispatcher 對 socket 連線做短重試，避免橋接器短暫重啟導致任務丟失。
- 任務鎖定: MySQL 使用 `dispatching` 中間狀態，避免並行 Dispatcher 重覆投遞同一筆 `pending` 任務。
- 自動建表: 啟動時可選 `--init-schema`，快速初始化 `ai_tasks`、`ai_feedback`。
- 版本兼容: 建表不綁定 InnoDB，且避免多 `TIMESTAMP CURRENT_TIMESTAMP` 寫法，兼容老版本 MySQL/MariaDB。
- 視窗隔離: 每個窗口橋接器獨立進程，單窗口故障不影響其他 AI 管線。

## 5. 執行步驟

1. 安裝依賴
   - `pip install redis pymysql`
2. 啟動橋接器（每個管理員窗口各一）
   - Claude: `python window_bridge.py --port 9001 --ai claude --cli "claude"`
   - Gemini: `python window_bridge.py --port 9002 --ai gemini --cli "gemini"`
   - Codex: `python window_bridge.py --port 9003 --ai codex --cli "codex"`
3. 初始化資料表（可選，建議首跑）
   - `python dispatcher.py --init-schema --mysql-user root --mysql-password gj`
4. 啟動分發器
   - `python dispatcher.py --mysql-user root --mysql-password gj`
5. 發送任務
   - Redis: 向 `ai_task_queue` 推入 `claude:幫我分析今天錯誤日誌`
   - User: 在 dispatcher 終端輸入 `gemini:整理本週報告摘要`
   - MySQL: 插入 `ai_tasks` 的 `pending` 任務
6. AI 回寫（由 AI CLI 調用）
   - `python ai_feedback.py --source-ai claude --task-id t-1001 --redis "已完成摘要"`
   - `python ai_feedback.py --source-ai claude --task-id t-1001 --db "結果已入庫"`
   - `python ai_feedback.py --source-ai claude --task-id t-1001 --ask "請確認是否繼續下一步？"`

## 6. 安全與運維建議

- 生產環境用環境變數注入 MySQL 密碼，不要寫死在腳本。
- Redis/MySQL 建議最小權限帳號，不用 root 直連。
- 可新增 `dispatcher.log` 與 `bridge.log` 輪轉日誌，便於審計與追蹤。
- 若需跨機部署，將 `127.0.0.1` 改為內網地址並加 ACL/TLS。

## 7. 後續可擴展項

- 任務優先級佇列（Redis Sorted Set 或 MySQL priority 調度）。
- 回執機制（Bridge ACK -> Dispatcher）以提高可觀測性。
- 任務超時與重試策略（failed 後回退為 pending N 次）。
- 結果聚合器（按 `task_id` 統一收斂多 AI 的輸出）。
