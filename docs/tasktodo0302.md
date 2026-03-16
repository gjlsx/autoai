# tasktodo0302 - PTY Worker（Windows 10）
##重要，pty方案略過，但是已經完成代碼保留，目前設計改變只需要實現下方 tasktodo0203_C 方案即可  by wind/26.03.02


    ## 目標
    實現一個 PTY Worker：在 Windows 10 上維持單一 AI CLI session（`codex` 或 `claude`），接收上游文本、寫入 CLI、流式讀取輸出、並把標準化輸出事件交給 `ai_feedback.py`（或等價分派）。

    邊界（不在本 task）：
    - MySQL / Redis 任務來源與狀態流轉
    - 上層重試策略、任務路由
    - prompt 拼裝/上下文記憶/工具策略

    ---

    ## Task 1：三方案測試與選型（已完成）
    測試對象：
    1. `node-pty`
    2. `pywinpty`
    3. 原生 `ConPTY API`

    已新增：
    - `pty_backends.py`
    - `scripts/run_pty_backend_probe.py`

    執行：

    ```powershell
    python .\scripts\run_pty_backend_probe.py --output-json .\.runtime\pty_backend_report.json
    ```

    本機實測結果（2026-03-02）：
    - `pywinpty`: success
    - `node-pty`: success
    - `native-conpty`: success
    - 推薦：`pywinpty`（與現有 Python 架構整合成本最低，維護最簡）

    ---

    ## Task 2：PTY Session 管理（已完成）
    已新增 `pty_worker.py`：
    - 建立/維持單 session PTY
    - 若 session 已存活，後續任務直接復用同一 AI CLI
    - 支持 `pywinpty backend` 切換：`auto|conpty|winpty`

    ---

    ## Task 3：CLI IO（已完成）
    `pty_worker.py` 已實現：
    - `write(stdin)`：接收 socket payload，寫入 CLI
    - `read(stdout/stderr)`：非阻塞輪詢 + 緩衝聚合
    - 對外 socket 協議：接受純文本或 JSON（含 `task_id` / `message`）

    ---

    ## Task 4：標準化事件分派（已完成）
    `pty_worker.py` 已實現輸出事件分派：
    - `--feedback-mode ai_feedback|file|stdout`
    - `ai_feedback` 模式下，調用 `ai_feedback.py`，支持 `db|redis|ask`
    - 事件格式：`event/source/ai/task_id/seq/ts/text`

    已新增測試：
    - `tests/test_pty_backends.py`
    - `tests/test_pty_worker_parse.py`
    - `tests/test_pty_worker_file_mode.py`

    測試結果：
    - `pytest` 全量：`18 passed`

    ---

    ## 快速啟動（示例）

    ### 1) 啟動 Worker（接 codex，走 ai_feedback -> MySQL）
    ```powershell
    python .\pty_worker.py --ai codex --cli "codex" --port 9103 --feedback-mode ai_feedback --feedback-channel db
    ```

    ### 2) 啟動 Worker（本地文件觀察事件）
    ```powershell
    python .\pty_worker.py --ai codex --cli "python scripts/mock_ai_cli.py" --port 9103 --feedback-mode file --feedback-file .\.runtime\pty_events.jsonl --emit-input-events
    ```

    ### 3) 發送一條上游消息（socket）
    ```powershell
    @'
    import socket
    s=socket.create_connection(("127.0.0.1",9103),timeout=5)
    s.sendall(b'{"task_id":"t-1","message":"hello"}')
    s.shutdown(socket.SHUT_WR)
    print(s.recv(1024).decode())
    s.close()
    '@ | python -
    ```




## tasktodo0203_b: (to be coninue 03-02 16:04)  //by wind :此需求略過，作爲後備計劃，目前只需要實施## tasktodo0203_C: 

    如果你要真正「長駐一個 agent，外部事件來就餵一條訊息到同一個codex thread,保持上下文」，官方更對位的是：

    codex app-server：thread/start / thread/resume / turn/start，在同一 thread 持續送入新訊息
    或 @openai/codex-sdk：startThread() 後反覆 thread.run(...)，也可 resumeThread(threadId)
    Codex App Server (thread/resume, turn/start):
    https://developers.openai.com/codex/app-server

    Codex SDK (run() again / resumeThread):
    https://developers.openai.com/codex/sdk
    這個場景可以理解成「同一個客服對話，只是每次訊息都由後端再餵給同一個 thread」。

    ----
    如上，使用codex app-server /或者codex sdk  調用同一個codex 實體， 作爲ptty調用cli的另一個選擇，一并實現，具體調用誰由 ai_target 決定， 閲讀鏈接中的官方文檔，先寫測試通過后再實現之，要保證測試，並通過


## tasktodo0203_C:
   經過檢查我發現下發到本機ai codex 這裏實在是問題比較大，現在更新需求，我們使用 vscode 裏的codex 插件，和
   rest control 插件，info見：https://github.com/dpar39/vscode-rest-control
   該插件啓動后偵聽在 http://127.0.0.1:49818   ,
   要求吧vscode 裏的 codex輸出按原來流程轉發到，并且調用相應vscode command 把返回下發西信息輸入在codex插件文本輸入框，並enter后，等待處理，循環，分解任務，建立文檔逐個完成，注意每完成一步要測試通過，

