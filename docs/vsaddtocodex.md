# VSCode Codex Chat Task Spec (Status: Completed 2026-03-06)

下面给你一份 专门针对 Codex Chat 的完整任务说明（Task Spec）。
重点会说明：

Codex 的聚焦命令

如何发送消息

如何接收 AI 回复

VSCode 插件实现

Python 调用

因为你使用的是 Visual Studio Code + Codex IDE 插件。
Codex 是一个在 IDE 内运行的 AI coding agent，可以在 VSCode、Cursor 等 IDE 中直接进行对话与代码生成。

一、任务目标
由已經安裝的rest control vscode 插件做輔助
插件運行在 127.0.0.1:49818


codex 的sidebar 聚焦命令：
@command:chatgpt.sidebarView.focus
for example: 
curl http://localhost:49818/?command=chatgpt.sidebarView.focus
然後(判斷是否要把codex調到前端還是可以直接輸入)模擬鍵盤輸入 或者模擬輸入 ctrl+v 把已經拷貝到剪貼版的數據貼上去，然後模擬enter


具體：
实现一个最小化測試系统：

三、发送消息到 Codex

> **[DEPRECATED 警告]**
> 基于 `type` 的模拟输入、全局监听 `vscode.chat.onDidReceiveChatResponse`、同步死等 `setTimeout(5000)` 以及全局变量 `lastResponse` 均已被废弃。
> 原因：`type` 无法向 Webview iframe 内的元素稳定发送文本；隐式等待与全局变量会导致并发冲突和状态泄露。
>
> **[NEW 架构]**
> 现在改为**命令驱动**：优先使用 `custom.getCommands` 探测可用的发送命令（例如 `chatgpt.addToThread`），直接调用插件暴露的带参 Command，彻底剥离开对 UI 强焦点的依赖。
> 接收回复改为：定期轮询 `custom.eval("vscode.env.clipboard.readText()")` 并通过 `output:openai.chatgpt.Codex.log` 提取流式反馈。
> 失败策略：如果找不到支持的输入命令，或者 Codex 失去响应，不再盲目死等，而是直接标记 StepFailed，走系统默认的三次重试并在失败后触发 System Alert。

VSCode 插件需要模拟输入（旧版设计）：

发送流程：

focus Codex
↓
输入 prompt
↓
Enter

Python
 ↓
VSCode Extension
 ↓
Codex Chat
 ↓
VSCode Extension
 ↓
Python

功能要求：

1 发送消息

Python 可以发送 prompt 到 Codex Chat 输入框。




//resrcontrol 插件説明：

REST Control

Visual Studio Marketplace Number of installs Buy me a coffee

This extension allows you to remotely control instances of Visual Studio Code by exposing a REST endpoint that you can use to invoke vscode commands. In the background it launches a HTTP server that listen on the localhost interface for requests of commands to execute.

The demo below shows how we can open a terminal, run some commands in it, then close all terminals, open a file with the cursor in a specified location and finally start a debug session on the same file that is orchestrating it all!

sample automation demo

DISCLAIMER: This extension was forked from Remote Control. The main motivation behind it was that while Remote Control uses websockets, for my use case I can only rely on HTTP REST calls. In addition, some commands I need to use require non-primitive JavaScript types which are not handled except for a couple of cases in the original extension (e.g. the Uri for vscode.open command).

Extension Settings
The extension has the following settings which you can use to configure it:

restRemoteControl.enable: enable/disable this extension
restRemoteControl.port: set the port number on which the HTTP server will listen, otherwise the extension will pick one available port for you based on the current workspace path.
restRemoteControl.fallbacks: an array of port numbers to fallback to if the port is already in use.
Usage
When you install this extension, it will automatically try to start a HTTP server. The port can be specified with VSCode setting restRemoteControl.port. When you are going to use multiple VSCode sessions at the same time, it is best to configure it at workspace level or use the restRemoteControl.fallbacks setting to specify fallback ports when the specified one is already in use. VSCode terminals opened will have environment variable REMOTE_CONTROL_PORT set with the port the server is currently listening on.

status bar listening message

Once installed, you can execute vscode commands by making HTTP requests. The HTTP verb is currently ignored. Here are few examples using curl, assuming VSCode is listening on port 49818:

# Create a new terminal
curl http://localhost:49818 -d '{"command":"workbench.action.terminal.new"}' 
# or curl http://localhost:49818/?command=chatgpt.sidebarView.focus

# Run `pwd` in the currently active terminal
curl http://localhost:49818 -d '{"command":"custom.runInTerminal", "args": ["pwd"]}'
# or curl http://localhost:49818/?command=custom.runInTerminal&args=%5B%22pwd%22%5D

# Kill all terminals
curl http://localhost:49818 -d '{"command":"workbench.action.terminal.killAll"}'
# or curl http://localhost:49818/?command=workbench.action.terminal.killAll

# Register an external formatter endpoint available at http://localhost:12345 that accepts POST requests and formats C++ and Python code
curl http://localhost:49818 -d '{"command":"custom.registerExternalFormatter", "args":["http://localhost:12345", ["cpp", "python"], "POST"]}'

All requests are expected to be in a JSON HTTP request body in the form:

{
  "command": "<command-id>",
  "args": ["<arg1>", "<arg2>", "...", "<argN>"]
}

or URL encoded as ?command=<command-id>&args=<url-encoded-of-json-string-of-args>.

Some VSCode commands expect VSCode's defined types such as Range, Uri, Position and Location. To accommodate for those, such arguments can be passed as a special types, see the example below which effectively invokes editor.action.goToLocations with Uri, Position and an array of Locations:

{
  "command": "editor.action.goToLocations",
  "args": [
    {
      "__type__": "Uri",
      "args": ["/path/to/file.py"]
    },
    {
      "__type__": "Position",
      "args": [4, 0]
    },
    [
      {
        "__type__": "Location",
        "args": [
          {
            "__type__": "Uri",
            "args": ["/path/to/file.py"]
          },
          {
            "__type__": "Position",
            "args": [11, 5]
          }
        ]
      }
    ]
  ]
}

Custom defined commands:
As the extension progresses, I plan to add more special commands (i.e. commands that require some use of the VSCode API). For now, we have defined the following commands:

custom.goToFileLineCharacter: allows you to navigate to a specific position in a file by passing the file path, line and column number as arguments
custom.startDebugSession: allows you to invoke vscode.debug.startDebugging() API by passing the workspace folder and a name or definition of a debug configuration as it would be set in launch.json
custom.runInTerminal: allows you to invoke commands the currently active integrated terminal
custom.showQuickPick: show quick pick dialog to collect selection from the user
custom.showInputBox: show input box dialog to collect a input string from the user
custom.showInformationMessage, custom.showWarningMessage and custom.showErrorMessage: show message dialogs to the user and let them click on a button
custom.listInstalledExtensions: get the list of installed extension IDs
custom.getExtensionInfo: get details of an installed extension by passing the extension ID
custom.registerExternalFormatter: registers an external formatter via a HTTP endpoint. The HTTP endpoint will receive a JSON body with the following properties{"file": "<document file path>", "snippet": "<content to be formatted>", "language": "<language id of the current file>"} and it should return in the body the formatted code snippet (or the original if the code can't be formatted).
custom.listOpenedFiles: gets the list of all files currently opened (string[])
custom.currentEditorContent: to get the content of the current (in-focus) editor as a string (string or null)
custom.registerEventHandler: so that an external HTTP server can handle events from VSCode API. Events supported right now are:
vscode.window.onDidChangeActiveTextEditor
vscode.window.onDidChangeTextEditorSelection
vscode.workspace.onDidSaveTextDocument
vscode.workspace.onDidOpenTextDocument
vscode.workspace.onDidCloseTextDocument
To implement in the near future:
Add the ability to set a breakpoint at the specified file/line combination
How do I get the command ID?
To get the command ID, open the Command Palette and type Show all commands. This will give you a list with all the available commands. VScode's built-in commands can be found here.

Behind each command, there is a gear button. When you click on it, it brings you to the shortcut configuration. Where you can right-click on the command and copy its ID.

how to get the command id

Feedback / issues / ideas
Please submit your feedback/issues/ideas by creating an issue in the project repository: issue list.
