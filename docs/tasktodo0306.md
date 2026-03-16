

VSCode Codex Bridge 重构任务计划（基于 vsaddtocodex.md）
摘要
目标是把链路从“UI 模拟输入”改成“插件命令驱动”，并保留稳定回读与持续对话能力。
本计划只定义任务，不执行代码修改；你确认后再进入实施。

codex 的sidebar 聚焦命令：
@command:chatgpt.sidebarView.focus
for example: 
curl http://localhost:49818/?command=chatgpt.sidebarView.focus
然後(判斷是否要把codex調到前端還是可以直接輸入)模擬鍵盤輸入 或者模擬輸入 ctrl+v 把已經拷貝到剪貼版的數據貼上去，然後模擬enter


公共接口/行为变更（决策完成）
发送消息接口：
然後(判斷是否要把codex調到前端還是可以直接輸入)模擬鍵盤輸入 或者模擬輸入 ctrl+v 把已經拷貝到剪貼版的數據貼上去，然後模擬enter //03.06 已經測試通過，by wind

回复获取接口：//這裏可能會無法獲得，若嘗試無法獲得先跳過
不使用 vscode.chat.onDidReceiveChatResponse 全局监听。
继续使用现有“copy + clipboard delta + codex log stream fallback”机制。
会话策略：

sessionid 变化时默认执行 chatgpt.newChat，防止串话。
同 sessionid 复用当前线程，保持上下文。
任务拆分（最小可测试通过）
Task 0: 基线校验（只读/不改码）
检查本机运行时命令是否存在：
chatgpt.addToThread
chatgpt.newChat
chatgpt.sidebarView.focus
验收：命令探测结果落在日志输出中，可复现。
Task 1: 先补测试（TDD）
新增测试文件：
D:\work\aiwork\autoai\tests\test_vscode_codex_worker_command_resolution.py
修改测试文件：
D:\work\aiwork\autoai\tests\test_vscode_codex_worker_pipeline.py
D:\work\aiwork\autoai\tests\test_vscode_codex_worker_mock_rest.py
关键测试场景：
custom.getCommands 返回 chatgpt.addToThread 时，发送成功。
无可用发送命令时，worker 失败并触发 system alert。
正常发送路径不调用 type。
sessionid 切换会触发 newChat。
clipboard 无增量但 stream 存在时返回 fallback 文案。



task 2,task 3先不具體實現，只做後續計劃，by wind ,26.03.06
Task 2: Worker 实现重构
修改文件：
D:\work\aiwork\autoai\vscode_codex_worker.py
变更点：
增加命令探测：custom.getCommands + 缓存。
增加发送命令解析器：按候选列表解析（优先 chatgpt.addToThread）。
发送阶段移除 type 依赖（默认不走 type_submit）。
解析失败走 StepFailed，复用已有 failed/system-alert 流程。
会话默认隔离：sessionid 变化执行 newChat（保留可配置开关）。
Task 3: 配置与启动参数对齐
修改文件：
D:\work\aiwork\autoai\config\vscode_codex_command_profile.json
D:\work\aiwork\autoai\scripts\one_click.py
D:\work\aiwork\autoai\tests\test_one_click_vscode_rest_config.py
变更点：
profile 增加发送候选命令配置（如 input_command_candidates）。
默认行为与 worker 一致：命令缺失失败、session 变化新会话。




Task 4: 文档更新
修改文件：
D:\work\aiwork\autoai\docs\vsaddtocodex.md
D:\work\aiwork\autoai\docs\runbooks\vscode-rest-control-codex-commands.md
变更点：
标注弃用：type 模拟输入、setTimeout(5000)、lastResponse 全局变量、全局 chat 响应监听。
明确新主链路与失败策略。

测试用例与验收场景
单元/集成测试命令：
$env:PYTHONPATH='.'; python -m pytest -q tests/test_vscode_codex_worker_parse.py tests/test_vscode_codex_worker_profile.py tests/test_vscode_codex_worker_pipeline.py tests/test_vscode_codex_worker_mock_rest.py tests/test_vscode_codex_worker_command_resolution.py tests/test_one_click_vscode_rest_config.py
验收标准：
全部测试通过。
正常发送流程命令序列中不出现 type。
缺发送命令会失败并记录可诊断错误（step + last_error）。
sessionid 隔离行为正确（新旧会话不串话）。
假设与默认值
本机目标插件为 openai.chatgpt，REST 控制插件为 dpar39.vscode-rest-control。
REST 端点默认 http://127.0.0.1:49818。
不引入 PTY/CLI fallback，专注 VSCode REST 主链路。
并发策略沿用现有 turn_lock 串行处理，不在本次最小任务扩展并发会话执行。
