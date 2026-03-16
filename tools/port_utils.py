import subprocess

def get_pid_map() -> dict[str, str]:
    """獲取當前系統進程的 PID 對應的名稱映射。"""
    pm = {}
    try:
        res = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            errors="replace"
        )
        for line in res.stdout.splitlines():
            if '","' in line:
                parts = line.split('","')
                if len(parts) >= 2:
                    name = parts[0].strip(' "')
                    pid = parts[1].strip(' "')
                    pm[pid] = name
    except Exception:
        pass
    return pm

def find_port(port_or_pid: str) -> list[str]:
    """根據端口或 PID 查找對應的佔用進程資訊。"""
    if not port_or_pid:
        return []

    pid_map = get_pid_map()
    matches = []
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
        for l in res.stdout.splitlines():
            parts = l.strip().split()
            if len(parts) >= 5:
                # 檢查本地地址(如 0.0.0.0:8080) 或 PID
                if f":{port_or_pid}" in parts[1] or parts[-1] == port_or_pid:
                    pid = parts[-1]
                    name = pid_map.get(pid, "Unknown")
                    matches.append(f"{l}  [{name}]")
    except Exception as e:
        matches.append(f"執行出錯: {e}")
        
    return matches

def list_listening_ports(limit: int = 20) -> tuple[list[str], int]:
    """列出當前系統中正在 LISTENING 的端口資訊，並回傳前 limit 筆及總數。"""
    pid_map = get_pid_map()
    listen_lines = []
    total_count = 0
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
        all_listen = [l for l in res.stdout.splitlines() if "LISTENING" in l]
        total_count = len(all_listen)
        
        for l in all_listen[:limit]:
            parts = l.strip().split()
            pid = parts[-1] if len(parts) >= 5 else ""
            name = pid_map.get(pid, "Unknown")
            listen_lines.append(f"{l}  [{name}]")
    except Exception as e:
        listen_lines.append(f"執行出錯: {e}")
        
    return listen_lines, total_count

def find_pids_by_port_or_pid(val: str) -> set[str]:
    """根據端口或 PID 獲取所有相關的 PID 集合。"""
    if not val:
        return set()
        
    pids_to_kill = set()
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
        for l in res.stdout.splitlines():
            parts = l.strip().split()
            if len(parts) >= 5:
                if f":{val}" in parts[1] or parts[-1] == val:
                    pids_to_kill.add(parts[-1])
    except Exception:
        pass
        
    if not pids_to_kill and val.isdigit():
        pids_to_kill.add(val)
        
    return pids_to_kill

def kill_process(pid: str) -> tuple[bool, str]:
    """強制刪除指定 PID 的進程。回傳 (是否成功, 訊息)。"""
    try:
        res = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True, errors="replace")
        if res.returncode == 0:
            return True, f"成功刪除 PID {pid}"
        else:
            return False, f"刪除失敗 PID {pid}: {res.stderr.strip()}"
    except Exception as e:
        return False, f"刪除發生錯誤: {e}"
