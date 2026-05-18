# AutoAI README


1.若是直接要完成任務就先read: `.agent-rules.md` ,others先讀需求文檔  :
- `docs/需求説明.md`


2. 私密配置  
- Redis / MySQL / Telegram token 等放在根目錄 `.env`

3. 連接遠端服務器  
   ## 1) 一鍵直連服務器（固定命令）
   在本機 PowerShell 直接執行：
  ```powershell
  ssh -i "D:\temp\aws\keygool_anpingli" -p 22 lianping1230@34.101.230.107
  ```
  important:  than press a enter key for default:  enter /

- 參考：`docs/遠端服務器標準連接流程.md`

```powershell
ssh -i "D:\temp\aws\keygool_anpingli" -p 22 lianping1230@34.101.230.107
若 SSH 偶發卡住，按一次 Enter。
```
本機vscode remote rest control 啓動在 127.0.0.1:49818 端口//後續可能有更改


4. 雲端 FastAPI 管理器入口  
- `cloud_orchestrator/main.py`

5. 雲端部署與驗證文檔  
- `docs/plans/2026-03-02-fastapi-cloud-orchestrator-implementation-plan.md`
- `docs/runbooks/fastapi-orchestrator-e2e.md`

6. 本地一鍵啟停  
- 啟動（預設 VSCode Codex Worker）：`python .\scripts\one_click.py start`
- 啟動（含 Claude）：`python .\scripts\one_click.py start --start-claude`
- 啟動（含 Claude + Gemini）：`python .\scripts\one_click.py start --start-claude --start-gemini`
- 啟動（啟用 Codex Agent Worker）：`python .\scripts\one_click.py start --start-codex-agent`
- 啟動（舊 window_bridge 模式）：`python .\scripts\one_click.py start --bridge-mode window`
- 狀態：`python .\scripts\one_click.py status`
- 停止：`python .\scripts\one_click.py stop`
- 回寫：`python .\scripts\one_click.py feedback --task-id <id> --message "done" --source-ai codex`
- 演練（不實際啟動）：`python .\scripts\one_click.py start --dry-run`

`matrix_ui.py` 頂部也已接入一鍵 `start/stop/status` 按鈕，按鈕會直接調用 `scripts/one_click.py`。

7. 本地一鍵操作手冊  
- `docs/runbooks/local-one-click-operation.md`

8. Feedback 走通測試（雲 MySQL + Telegram）
- `python .\scripts\feedback_flow_test.py --inject --chat-id 1261596828 --payload "feedback smoke from script"`
- `python .\scripts\feedback_loop_e2e_test.py --chat-id 1261596828 --timeout-sec 40`

9. PTY Worker（Windows）
- 探測三方案並選型：`python .\scripts\run_pty_backend_probe.py --output-json .\.runtime\pty_backend_report.json`
- 任務說明與 Task1-4 狀態：`docs/tasktodo0302.md`
- Worker 入口：`pty_worker.py`
- VSCode Codex Worker 入口：`vscode_codex_worker.py`
- VSCode/REST 命令字典：`docs/runbooks/vscode-rest-control-codex-commands.md`
- 全鏈路煙霧測試：`python .\scripts\e2e_pty_pipeline_smoke.py --timeout-sec 120 --port 9913`
- Codex Agent（task0203_b）煙霧測試：`python .\scripts\e2e_codex_agent_pipeline_smoke.py --timeout-sec 120 --port 9923`
- 集成記錄（問題與解法）：`docs/runbooks/pty-worker-integration.md`

10. 基本規則（文件定位）
- 文件引用一律使用「純文本絕對路徑」，可附行號；示例：`D:\work\aiwork\autoai\dispatcher.py:272`
- 不使用任何網址形式（如 `http://`、`https://`、`file+...`）來表示本地文件
- 不使用 Markdown 可點擊鏈接來表示本地文件路徑
- 在 VSCode 中打開方式：
  - `Ctrl+P` 粘貼 `D:\...\file.py:line`
  - 或終端執行：`code -g "D:\...\file.py:line"`

11. **自動化與工具目錄 (`tools/`)**
- 為了避免 `matrix.py` 累積過多代碼影響後續的 PR 重構，所有的底層具體操作均抽離到 `tools/` 資料夾下：
  - `tools/port_utils.py`：包含端口與 PID 查詢、強刪執行緒操作。
  - `tools/vscode_utils.py`：包含依路徑找出當前運作的 VSCode/Code - Insiders 相關邏輯。
  - `tools/timego.py`：**定時任務框架**。提供全域 `timer` 單例，使用方式如下：
    ```python
    from tools.timego import timer
    
    # 每 600 秒 (10分鐘) 執行 my_func，持續 86400 秒 (24小時)
    timer.schedule("my_task_1", my_func, interval_seconds=600, duration_seconds=86400)
    
    # 或是透過快速方法，每 12 小時執行一次，永久持續 (duration_hours=None)
    timer.schedule_hours("my_task_2", my_func, interval_hours=12)
    ```

12. 
  -
  CLIProxyAPI 免檢測快速安裝/啟動：`docs/runbooks/2026-03-08-cliproxyapi-quick-install.md`


  I have initialized the Git repository, committed all the current files, and successfully pushed them to your remote repository at [](https://github.com/gjlsx/autoai.git)<https://github.com/gjlsx/autoai.git>.

針對您先前提到的**「任務流程與函數調用」**，我為您梳理了 AutoAI 專案目前的整體運作架構與核心流轉過程：

### 1. 任務創建與雲端接收 (Cloud Entry)

- __流程__：使用者在 Telegram 發送指令給 Bot。

- __核心模組__：`cloud_orchestrator/telegram_inbound.py` / `main.py`

- __函數/動作__：

  - 接收 Telegram Webhook 或 Polling 消息。
  - 將解析後的指令存入雲端 MySQL 資料庫的 `ai_tasks` 表，初始狀態設為 `pending`，並產生唯一 `idempotency_key` 避免重複。

### 2. 本地拉取與任務派發 (Local Dispatcher)

- __流程__：本地機器上的分發中心定期輪詢雲端 MySQL，取得待處理的任務並決定送到哪個 AI 工具。

- __核心模組__：`dispatcher.py`

- __函數/動作__：

  - `fetch_pending_tasks()`：從 MySQL 拉取狀態為 `pending` 的任務。
  - `mark_task_dispatching()`：將任務狀態更新為 `dispatching` 並鎖定。
  - `route_task(ai_target)`：根據 `ai_target`（如 claude, codex）將任務透過 Socket/HTTP 分發到對應的本機 Port（例如 Codex 預設 9003）。

### 3. AI 橋接與終端執行 (Worker & Bridge)

- __流程__：對應的 Worker 接收到任務後，透過模擬或 API 控制實際的 AI 工具（VSCode Codex, PTY Terminal 等）。

- __核心模組__：`vscode_codex_worker.py` / `pty_worker.py` / `window_bridge.py`

- __函數/動作__：

  - `window_bridge.py` 中的 Socket Listener 接收到 `dispatcher` 發來的任務。
  - 呼叫 worker (例如 `vscode_codex_worker.py` 中的 `send_to_codex()`) 透過 API 或是模擬輸入，將 prompt 送入已經開啟的 VSCode/CLI AI 會話中。
  - 任務狀態流轉為 `running`。

### 4. 過程回饋與狀態回寫 (AI Feedback)

- __流程__：AI 工具在執行任務期間，或是在完成後，需要將結果或遭遇的問題回報給系統。

- __核心模組__：`ai_feedback.py` / `scripts/skill_emit_to_redis.py`

- __函數/動作__：

  - `report_progress(task_id, payload)` / `report_result(task_id, payload)`。
  - 將執行過程 (progress) 或是最終產出 (result) 寫回 MySQL 的 `ai_feedback` 資料表。
  - 若有需要人工介入，可能會觸發狀態轉為 `waiting_human`。

### 5. 雲端推播與使用者通知 (Cloud Outbound)

- __流程__：雲端服務監測到有新的 Feedback 或任務完成，主動推送回使用者的 Telegram。

- __核心模組__：`cloud_orchestrator/telegram_outbound.py`

- __函數/動作__：

  - 輪詢或監聽 `ai_feedback` 表的變更。
  - 調用 Telegram Bot API `send_message()` 將最終結果或是 AI 的追問發送給使用者，形成完整閉環。

這套架構實現了「雲端接收任務 -> 本地主動拉取 -> 本地派發與執行 -> 結果回寫雲端 -> 推送給人類」的解耦設計。您現在可以直接在 GitHub 上查閱與管理這些更新了！

  - 
