# tasktodo0203_C - 任務1（獨立文件）

## 目標
參考 `vscode-chonky-remote-pilot`，驗證是否可作為目前 `codex` 本機 I/O 主鏈路。

## 輸出物
- 腳本：`scripts/chonky_remote_pilot_probe.py`
- 測試：`tests/test_chonky_remote_pilot_probe.py`
- 第三方源碼快照：`.runtime/third_party/vscode-chonky-remote-pilot`

## 驗證維度
1. 靜態能力（讀源碼）  
   - 是否有 `registerTool('chonky_remotepilot', ...)`
   - 是否有 `waitForMessage`（入站）
   - 是否有 `sendMessage`（出站）
2. 當前 VSCode 運行態  
   - REST `custom.getCommands` 是否出現 `chonky.*` 命令
3. 決策  
   - 可直接納入主鏈路 / 不可（轉任務2）

## 執行命令
```powershell
python scripts/chonky_remote_pilot_probe.py --output-json .runtime/chonky_probe_report.json
```

## 當前結論（本機）
- 靜態：具備雙向橋能力（工具式循環）
- 運行態：當前 VSCode 未檢出 `chonky.*` 命令
- 決策：暫不作為當前主鏈路，保留方案與腳本；按任務2落地可控通道

## 本機實測輸出
- 報告文件：`.runtime/chonky_probe_report.json`
- 關鍵字段：
  - `decision.usable_for_current_pipeline = false`
  - `decision.reasons` 包含：
    - `chonky_extension_not_active_in_current_vscode`
    - `fallback_to_task2_recommended`
