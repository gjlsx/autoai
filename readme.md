# AutoAI README

1. 先讀需求文檔  
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
  - 
