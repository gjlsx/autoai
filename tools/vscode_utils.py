import subprocess

def get_vscode_instances() -> dict[str, list[str]]:
    """獲取當前運行的 VSCode / Code - Insiders 的所有獨立執行路徑與對應的 PIDs。"""
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process -Name 'Code', 'Code - Insiders' -ErrorAction SilentlyContinue | Select-Object Id, Path | ConvertTo-Csv -NoTypeInformation"
    ]
    path_to_pids = {}
    try:
        CREATE_NO_WINDOW = 0x08000000
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=CREATE_NO_WINDOW)
        lines = res.stdout.splitlines()
        for line in lines:
            if not line.strip() or line.startswith('"Id"'):
                continue
            parts = line.split('","')
            if len(parts) >= 2:
                pid = parts[0].strip('"')
                path = parts[1].strip('"')
                if path:
                    if path not in path_to_pids:
                        path_to_pids[path] = []
                    path_to_pids[path].append(pid)
        return path_to_pids
    except Exception as e:
        return {"[Error]": [str(e)]}
