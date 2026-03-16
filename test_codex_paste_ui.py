import urllib.request
import json
import time
import subprocess

def send_vscode_command(command, args=None):
    url = "http://127.0.0.1:49818"
    payload = {"command": command}
    if args:
        payload["args"] = args
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        response = urllib.request.urlopen(req, timeout=5)
        print(f"[{command}] Response: {response.status}")
    except Exception as e:
        print(f"[{command}] Error: {e}")

def set_clipboard_and_paste(text):
    # Set clipboard using powershell
    print("Setting clipboard...")
    ps_clip = f"Set-Clipboard -Value '{text}'"
    subprocess.run(["powershell", "-Command", ps_clip], check=True)
    
    # Send keys using powershell System.Windows.Forms.SendKeys
    print("Simulating Ctrl+V and Enter...")
    ps_keys = """
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
"""
    subprocess.run(["powershell", "-Command", ps_keys], check=True)

def send_message_to_codex_ui(message: str, rest_url: str = "http://127.0.0.1:49818"):
    """
    Sends a message to the VSCode Codex sidebar using a hybrid approach:
    1. Uses REST Control to focus the sidebar and input box.
    2. Uses PowerShell to force the VSCode window to the foreground.
    3. Uses PowerShell to set the clipboard and simulate Ctrl+V + Enter.
    """
    def _send_cmd(cmd):
        payload = {"command": cmd}
        req = urllib.request.Request(
            rest_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[{cmd}] Error: {e}")

    print("STEP 1: Focusing Codex sidebar...")
    _send_cmd("chatgpt.openSidebar")
    time.sleep(0.5)
    _send_cmd("chatgpt.sidebarView.focus")
    time.sleep(1.0)
    
    print("Activating VSCode Window...")
    ps_focus = """
$wshell = New-Object -ComObject wscript.shell
$wshell.AppActivate('Visual Studio Code')
Start-Sleep -Milliseconds 500
$wshell.AppActivate('Code')
"""
    subprocess.run(["powershell", "-Command", ps_focus])
    time.sleep(1.0)
    
    _send_cmd("workbench.action.chat.focusInput")
    time.sleep(0.5)

    print(f"STEP 2: Pasting text: {message}")
    ps_clip = f"Set-Clipboard -Value '{message}'"
    subprocess.run(["powershell", "-Command", ps_clip], check=True)
    
    ps_keys = """
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
"""
    subprocess.run(["powershell", "-Command", ps_keys], check=True)

if __name__ == "__main__":
    test_msg = "hello 260306 02:44 zheyang"
    print(f"Running test with message: {test_msg}")
    send_message_to_codex_ui(test_msg)
    print("Test finished.")
