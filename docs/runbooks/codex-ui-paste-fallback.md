# Codex UI Paste Fallback 模块使用说明

## 简介
`test_codex_paste_ui.py` 现在被重构为一个可引入的模块。由于部分极其早期的 Codex 插件并没有开放 `chatgpt.addToThread` 之类的 API 命令，我们保留了这种“硬核”的模拟操作作为通用备用脱困手段。

这种方法不依赖任何内部插件接口代码，纯粹通过：
1. `VSCode REST Control` 的系统命令聚焦聊天框。
2. `PowerShell` 强制将 VSCode 进程窗口拉到最前台激活。
3. `PowerShell` 修改系统剪贴板。
4. `PowerShell` 发送全局键盘事件 (`Ctrl+V` 和 `Enter`) 将文本发送出去。

## 使用方法

### 1. 作为 Python 模块导入
你可以将其作为一个普通的 Python 函数引入并调用：

```python
from test_codex_paste_ui import send_message_to_codex_ui

message = "帮我生成一个 Python 的 HTTP 服务器代码"
rest_url = "http://127.0.0.1:49818" # 默认值

# 执行调用
send_message_to_codex_ui(message, rest_url)
```

### 2. 命令行直接测试
你也可以直接运行脚本来发送内置的测试消息（`"hello 260306 02:44 zheyang"`）：

```bash
python test_codex_paste_ui.py
```

## 注意事项与建议

1. **强行抢夺焦点**：因为该脚本在运行时会使用 Windows COM API 强制夺取系统级别的窗口第一焦点（使得当前用户的鼠标和键盘输入被打断），**仅推荐用作最后的 Fallback，不可作为高并发或后台静默链路使用。**
2. **兼容性**：该脚本目前依赖 Windows 系统的 PowerShell (`Set-Clipboard` 和 `System.Windows.Forms.SendKeys`)，无法在 Linux/macOS 上执行。
3. **延迟控制**：如果你发现粘贴经常失败（只聚焦了但没有粘贴），请适当增加 `test_codex_paste_ui.py` 中 `time.sleep` 的秒数，给 VSCode 前端界面一点渲染的时间。
