from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ProbeResult:
    name: str
    success: bool
    latency_ms: Optional[int]
    detail: str
    error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "error": self.error,
        }


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def probe_pywinpty(timeout_sec: float = 4.0) -> ProbeResult:
    start = time.perf_counter()
    try:
        import winpty

        pty = winpty.PTY(120, 30)
        pty.spawn("cmd.exe")
        token = "PYWINPTY_OK"
        pty.write(f"echo {token}\r\n")

        deadline = time.time() + timeout_sec
        output = ""
        while time.time() < deadline:
            chunk = pty.read(1024, blocking=False)
            if chunk:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", errors="replace")
                output += chunk
                if token in output:
                    return ProbeResult(
                        name="pywinpty",
                        success=True,
                        latency_ms=_ms(start),
                        detail="spawn/write/read OK via winpty.PTY",
                    )
            time.sleep(0.05)
        return ProbeResult(
            name="pywinpty",
            success=False,
            latency_ms=_ms(start),
            detail="timeout waiting probe token",
            error=output[-300:],
        )
    except Exception as exc:
        return ProbeResult(
            name="pywinpty",
            success=False,
            latency_ms=_ms(start),
            detail="exception",
            error=str(exc),
        )


def _ensure_node_pty_installed(runtime_dir: Path) -> Path:
    pkg_dir = runtime_dir / "node_pty_probe"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    package_json = pkg_dir / "package.json"
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    if not package_json.exists():
        subprocess.run(
            [npm_bin, "init", "-y", "--prefix", str(pkg_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        [npm_bin, "install", "node-pty", "--silent", "--prefix", str(pkg_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return pkg_dir


def probe_node_pty(runtime_dir: Optional[Path] = None, timeout_sec: float = 6.0) -> ProbeResult:
    start = time.perf_counter()
    try:
        base = runtime_dir or (Path.cwd() / ".runtime")
        pkg_dir = _ensure_node_pty_installed(base)
    except Exception as exc:
        return ProbeResult(
            name="node-pty",
            success=False,
            latency_ms=_ms(start),
            detail="npm install failed",
            error=str(exc),
        )

    script = (
        "const pty = require('node-pty');"
        "const shell = process.env.COMSPEC || 'cmd.exe';"
        "const token='NODE_PTY_OK';"
        "const term=pty.spawn(shell,[],{name:'xterm-color',cols:120,rows:30,cwd:process.cwd(),env:process.env});"
        "let buf='';"
        "let done=false;"
        "const t=setTimeout(()=>{if(!done){console.log(JSON.stringify({ok:false,detail:'timeout',tail:buf.slice(-300)}));"
        "try{term.kill();}catch(e){} process.exit(1);}},5000);"
        "term.onData((d)=>{buf+=d; if(!done && buf.includes(token)){done=true; clearTimeout(t);"
        "console.log(JSON.stringify({ok:true,detail:'spawn/write/read OK via node-pty'}));"
        "try{term.kill();}catch(e){} process.exit(0);}});"
        "term.write('echo '+token+'\\r');"
    )
    try:
        res = subprocess.run(
            ["node", "-e", script],
            cwd=str(pkg_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except Exception as exc:
        return ProbeResult(
            name="node-pty",
            success=False,
            latency_ms=_ms(start),
            detail="probe run failed",
            error=str(exc),
        )

    stdout = (res.stdout or "").strip().splitlines()
    payload = {}
    if stdout:
        last = stdout[-1]
        try:
            payload = json.loads(last)
        except Exception:
            payload = {"ok": False, "detail": "invalid node output", "tail": last[-200:]}
    ok = bool(payload.get("ok")) and res.returncode == 0
    return ProbeResult(
        name="node-pty",
        success=ok,
        latency_ms=_ms(start),
        detail=str(payload.get("detail") or "probe finished"),
        error=str(payload.get("tail") or (res.stderr or "").strip()),
    )


def probe_native_conpty() -> ProbeResult:
    start = time.perf_counter()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class COORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

        h_in_r = wintypes.HANDLE()
        h_in_w = wintypes.HANDLE()
        h_out_r = wintypes.HANDLE()
        h_out_w = wintypes.HANDLE()

        create_pipe = kernel32.CreatePipe
        create_pipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        create_pipe.restype = wintypes.BOOL

        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        hpcon = wintypes.HANDLE()
        create_pc = kernel32.CreatePseudoConsole
        create_pc.argtypes = [
            COORD,
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        create_pc.restype = ctypes.HRESULT
        close_pc = kernel32.ClosePseudoConsole
        close_pc.argtypes = [wintypes.HANDLE]
        close_pc.restype = None

        if not create_pipe(ctypes.byref(h_in_r), ctypes.byref(h_in_w), None, 0):
            raise RuntimeError(f"CreatePipe input failed: {ctypes.get_last_error()}")
        if not create_pipe(ctypes.byref(h_out_r), ctypes.byref(h_out_w), None, 0):
            raise RuntimeError(f"CreatePipe output failed: {ctypes.get_last_error()}")

        hr = create_pc(COORD(120, 30), h_in_r, h_out_w, 0, ctypes.byref(hpcon))
        if hr != 0:
            raise RuntimeError(f"CreatePseudoConsole HRESULT={hr}")

        close_pc(hpcon)
        for h in [h_in_r, h_in_w, h_out_r, h_out_w]:
            if h:
                close_handle(h)
        return ProbeResult(
            name="native-conpty",
            success=True,
            latency_ms=_ms(start),
            detail="CreatePseudoConsole/ClosePseudoConsole OK",
        )
    except Exception as exc:
        return ProbeResult(
            name="native-conpty",
            success=False,
            latency_ms=_ms(start),
            detail="exception",
            error=str(exc),
        )


def recommend_backend(results: List[ProbeResult]) -> str:
    by_name = {r.name: r for r in results}
    # Prefer Python stack with maintained wrapper when available.
    if by_name.get("pywinpty") and by_name["pywinpty"].success:
        return "pywinpty"
    if by_name.get("node-pty") and by_name["node-pty"].success:
        return "node-pty"
    if by_name.get("native-conpty") and by_name["native-conpty"].success:
        return "native-conpty"
    return "none"


def run_all_probes(runtime_dir: Optional[Path] = None) -> Dict[str, object]:
    if os.name != "nt":
        return {
            "platform": os.name,
            "results": [],
            "recommended": "none",
            "note": "PTY backend probes are Windows-specific",
        }
    results = [
        probe_pywinpty(),
        probe_node_pty(runtime_dir=runtime_dir),
        probe_native_conpty(),
    ]
    return {
        "platform": os.name,
        "results": [r.to_dict() for r in results],
        "recommended": recommend_backend(results),
    }
