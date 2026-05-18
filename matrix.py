import datetime as dt
import re
import shlex
import subprocess
import sys
import json
import threading
import tkinter as tk
import tkinter.ttk as ttk
import urllib.request
import urllib.error
from pathlib import Path
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText

import pymysql

from tools.port_utils import find_port, list_listening_ports, find_pids_by_port_or_pid, kill_process
from tools.vscode_utils import get_vscode_instances
from tools.timego import timer
from test_codex_paste_ui import send_message_to_codex_ui


DEFAULT_AI_TARGET = "codex"
AUTO_REFRESH_MS = 60_000
MATRIX_SOURCE_CHANNEL = "matrix_ui"
MATRIX_SOURCE_ID = "matrix_ui_local"


def _strip_wrapping_quotes(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
        return value[1:-1]
    return value


def _parse_mysql_from_env(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        raise RuntimeError(f".env not found: {env_path}")
    text = env_path.read_text(encoding="utf-8")

    def pick(name: str) -> str:
        m = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", text)
        if not m:
            return ""
        return _strip_wrapping_quotes(m.group(1))

    mysql_host = pick("MYSQL_HOST")
    mysql_port = pick("MYSQL_PORT")
    mysql_user = pick("MYSQL_USER")
    mysql_password = pick("MYSQL_PASSWORD")
    mysql_db = pick("MYSQL_DB")

    if not mysql_host or not mysql_port:
        m_host = re.search(r"(?m)^\s*([A-Za-z0-9\.-]+)\s+(\d{2,5})\s*$", text)
        if m_host:
            mysql_host = mysql_host or m_host.group(1).strip()
            mysql_port = mysql_port or m_host.group(2).strip()

    if not mysql_user or not mysql_password:
        m_user = re.search(r"(?mi)^\s*([A-Za-z0-9_]+)\s+[^\r\n]*?pwd:\s*([^\s]+)\s*$", text)
        if m_user:
            mysql_user = mysql_user or m_user.group(1).strip()
            mysql_password = mysql_password or m_user.group(2).strip()

    if not mysql_db and mysql_user:
        m_db = re.match(r"^(.*)wr$", mysql_user)
        if m_db and m_db.group(1):
            mysql_db = m_db.group(1)

    if not all([mysql_host, mysql_port, mysql_user, mysql_password, mysql_db]):
        raise RuntimeError(
            "cannot parse mysql config from .env, "
            "please set MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DB"
        )

    return {
        "MYSQL_HOST": mysql_host,
        "MYSQL_PORT": mysql_port,
        "MYSQL_USER": mysql_user,
        "MYSQL_PASSWORD": mysql_password,
        "MYSQL_DB": mysql_db,
    }


class MatrixUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AI Matrix 控制台")
        self.root.geometry("960x640")

        env_path = Path(__file__).resolve().parent / ".env"
        self.mysql_cfg = _parse_mysql_from_env(env_path)

        self._build_layout()
        self._ensure_tables()
        self.refresh_recent_both_10()
        self.root.after(AUTO_REFRESH_MS, self._auto_refresh_tick)

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.tab_wind = tk.Frame(self.notebook)
        self.notebook.add(self.tab_wind, text="風")
        self._build_tab1_layout(self.tab_wind)

        self.tab_flower = tk.Frame(self.notebook)
        self.notebook.add(self.tab_flower, text="花")
        self._build_tab2_layout(self.tab_flower)

        self.tab_snow = tk.Frame(self.notebook)
        self.notebook.add(self.tab_snow, text="雪")
        self._build_tab3_layout(self.tab_snow)

        self.tab_moon = tk.Frame(self.notebook)
        self.notebook.add(self.tab_moon, text="月")
        self._build_dummy_tab_layout(self.tab_moon, 4)

    def _build_tab1_layout(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=1)

        top_bar = tk.Frame(parent, padx=8, pady=8)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)

        buttons_row1 = tk.Frame(top_bar)
        buttons_row1.pack(anchor="w", pady=(0, 4))
        buttons_row2 = tk.Frame(top_bar)
        buttons_row2.pack(anchor="w", pady=(0, 4))
        buttons_row3 = tk.Frame(top_bar)
        buttons_row3.pack(anchor="w")

        tk.Button(buttons_row1, text="一鍵啟動(Codex)", width=15, command=lambda: self.run_one_click(["start"])).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="啟動+Claude", width=12, command=lambda: self.run_one_click(["start", "--start-claude"])).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="停止Worker", width=11, command=lambda: self.run_one_click(["stop"])).pack(side=tk.LEFT, padx=4)
        
        tk.Button(buttons_row2, text="查看狀態", width=11, command=lambda: self.run_one_click(["status"])).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸入", width=14, command=self.refresh_recent_input_10).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸出", width=14, command=self.refresh_recent_output_10).pack(side=tk.LEFT, padx=4)
        
        tk.Button(buttons_row3, text="清除輸出框", width=14, command=self.clear_output).pack(side=tk.LEFT, padx=4)

        input_row = tk.Frame(parent, padx=8, pady=6)
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(input_row, textvariable=self.input_var, font=("Microsoft YaHei UI", 11))
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_entry.bind("<Return>", lambda _e: self.send_task())

        send_btn = tk.Button(input_row, text="發送", width=12, command=self.send_task)
        send_btn.grid(row=0, column=1, sticky="e")

        hint = tk.Label(
            input_row,
            text="輸入格式: ai:消息（例: codex:檢查日誌）; 若未填 ai，預設 codex",
            anchor="w",
            fg="#555555",
        )
        hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        output_wrap = tk.Frame(parent, padx=8, pady=8)
        output_wrap.grid(row=2, column=0, sticky="nsew")
        output_wrap.grid_rowconfigure(0, weight=1)
        output_wrap.grid_columnconfigure(0, weight=1)

        self.output_box = ScrolledText(output_wrap, font=("Consolas", 10), wrap=tk.WORD)
        self.output_box.grid(row=0, column=0, sticky="nsew")
        self.output_box.configure(state="disabled")

    def _build_tab2_layout(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=1)

        top_bar = tk.Frame(parent, padx=8, pady=8)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)

        buttons_row1 = tk.Frame(top_bar)
        buttons_row1.pack(anchor="w", pady=(0, 4))
        buttons_row2 = tk.Frame(top_bar)
        buttons_row2.pack(anchor="w")

        input_row = tk.Frame(parent, padx=8, pady=6)
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        input_var = tk.StringVar()
        input_entry = tk.Entry(input_row, textvariable=input_var, font=("Microsoft YaHei UI", 11))
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        output_wrap = tk.Frame(parent, padx=8, pady=8)
        output_wrap.grid(row=2, column=0, sticky="nsew")
        output_wrap.grid_rowconfigure(0, weight=1)
        output_wrap.grid_columnconfigure(0, weight=1)

        output_box = ScrolledText(output_wrap, font=("Consolas", 10), wrap=tk.WORD)
        output_box.grid(row=0, column=0, sticky="nsew")

        def _clear_output():
            output_box.configure(state="normal")
            output_box.delete("1.0", tk.END)
            output_box.configure(state="disabled")

        tk.Button(buttons_row2, text="清除輸出框", width=14, command=_clear_output).pack(side=tk.LEFT, padx=4)

        def _log(msg: str, color: str = None):
            def _do():
                output_box.configure(state="normal")
                if color:
                    tag_name = f"color_{color.replace('#', '')}"
                    output_box.tag_configure(tag_name, foreground=color)
                    output_box.insert(tk.END, msg + "\n", tag_name)
                else:
                    if msg.startswith("===") or msg.startswith("---"):
                        output_box.tag_configure("header", foreground="#0055D4", font=("Consolas", 10, "bold"))
                        output_box.insert(tk.END, msg + "\n", "header")
                    elif "出錯" in msg or "失敗" in msg or "找不到" in msg or "未找到" in msg:
                        output_box.tag_configure("error", foreground="#D32F2F")
                        output_box.insert(tk.END, msg + "\n", "error")
                    elif "成功" in msg:
                        output_box.tag_configure("success", foreground="#2E7D32")
                        output_box.insert(tk.END, msg + "\n", "success")
                    else:
                        output_box.insert(tk.END, msg + "\n")
                output_box.see(tk.END)
                output_box.configure(state="disabled")
            self.root.after(0, _do)
            
        _log("=== 端口查找與刪除工具 ===")
        _log("請在上方輸入端口號 (如 8080) 或 PID。\n", color="#555555")

        def _find_port():
            port_or_pid = input_var.get().strip()
            _log(f"=== 查找端口 / PID: {port_or_pid} ===")
            if not port_or_pid:
                _log("請輸入端口或PID。")
                return

            matches = find_port(port_or_pid)
            if matches:
                _log("找到的佔用：")
                for m in matches:
                    _log(m)
            else:
                _log(f"未找到佔用 {port_or_pid} 的端口/PID。")
            
            _log("\n--- 主要監聽中的端口 ---")
            listen_lines, total_count = list_listening_ports(20)
            for m in listen_lines:
                _log(m)
            if total_count > 20:
                _log(f"...(共 {total_count} 筆，僅顯示前 20 筆)")

        def _kill_port():
            val = input_var.get().strip()
            if not val:
                self.root.after(0, lambda: messagebox.showwarning("輸入錯誤", "請輸入要刪除的PID或端口。"))
                return
            
            pids_to_kill = find_pids_by_port_or_pid(val)
            if not pids_to_kill:
                _log(f"找不到對應的 PID: {val}")
                return
            
            pids_str = ", ".join(pids_to_kill)
            
            def _ask_and_kill():
                if messagebox.askyesno("確認刪除", f"確定要刪除以下 PID 的進程嗎？\nPID: {pids_str}"):
                    def _do_kill():
                        for pid in pids_to_kill:
                            _log(f"嘗試刪除 PID {pid} ...")
                            success, msg = kill_process(pid)
                            _log(msg)
                    self.run_in_thread(_do_kill)

            self.root.after(0, _ask_and_kill)

        btn_find = tk.Button(buttons_row1, text="查找端口", width=12, command=lambda: self.run_in_thread(_find_port))
        btn_find.pack(side=tk.LEFT, padx=4)
        
        btn_kill = tk.Button(buttons_row1, text="刪除端口", width=12, command=lambda: self.run_in_thread(_kill_port))
        btn_kill.pack(side=tk.LEFT, padx=4)

        def _test_rest_job():
            _log("=== 測試發送 REST 消息到 VSCode ===")
            cfg_path = Path(__file__).resolve().parent / "config" / "vscode_rest_targets.json"
            if not cfg_path.exists():
                _log(f"[錯誤] 找不到設定檔: {cfg_path}", color="#D32F2F")
                return
                
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                workers = cfg.get("workers", [])
                if not workers:
                    _log("[錯誤] vscode_rest_targets.json 中沒有 workers 設定", color="#D32F2F")
                    return
            except Exception as e:
                _log(f"[錯誤] 讀取設定檔失敗: {e}", color="#D32F2F")
                return

            msg = "hello, 1+2=?"
            _log(f"準備發送測試消息: {msg}")
            
            for worker in workers:
                target = worker.get("target", "unknown")
                rest_url = worker.get("rest_url")
                
                if not rest_url:
                    _log(f"[跳過] 目標 {target} 沒有設定 rest_url", color="#555555")
                    continue
                    
                _log(f"-> 正在發送到 {target} ({rest_url}) ...")
                
                try:
                    # 使用已經寫好驗證過的方法發送
                    send_message_to_codex_ui(msg, rest_url=rest_url)
                    _log(f"[成功] 目標 {target} 發送完成", color="#2E7D32")
                except Exception as e:
                    _log(f"[錯誤] 目標 {target} 發送時發生異常: {e}", color="#D32F2F")

        def _start_test_task():
            self.run_in_thread(_test_rest_job)

        btn_test = tk.Button(buttons_row1, text="測試發送", width=12, command=_start_test_task)
        btn_test.pack(side=tk.LEFT, padx=4)

        send_btn = tk.Button(input_row, text="發送", width=12, command=lambda: self.run_in_thread(_find_port))
        send_btn.grid(row=0, column=1, sticky="e")
        
        input_entry.bind("<Return>", lambda _e: self.run_in_thread(_find_port))

        hint = tk.Label(
            input_row,
            text="輸入端口 (如 8080) 或 PID，然後發送（查找）",
            anchor="w",
            fg="#555555",
        )
        hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_tab3_layout(self, parent: tk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=1)

        top_bar = tk.Frame(parent, padx=8, pady=8)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)

        buttons_row1 = tk.Frame(top_bar)
        buttons_row1.pack(anchor="w", pady=(0, 4))
        buttons_row2 = tk.Frame(top_bar)
        buttons_row2.pack(anchor="w", pady=(0, 4))
        buttons_row3 = tk.Frame(top_bar)
        buttons_row3.pack(anchor="w")

        tk.Button(buttons_row1, text="一鍵啟動(Codex)", width=15, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="啟動+Claude", width=12, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="停止Worker", width=11, state="disabled").pack(side=tk.LEFT, padx=4)
        
        tk.Button(buttons_row2, text="查看狀態", width=11, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸入", width=14, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸出", width=14, state="disabled").pack(side=tk.LEFT, padx=4)

        input_row = tk.Frame(parent, padx=8, pady=6)
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        input_var = tk.StringVar()
        input_entry = tk.Entry(input_row, textvariable=input_var, font=("Microsoft YaHei UI", 11))
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        output_wrap = tk.Frame(parent, padx=8, pady=8)
        output_wrap.grid(row=2, column=0, sticky="nsew")
        output_wrap.grid_rowconfigure(0, weight=1)
        output_wrap.grid_columnconfigure(0, weight=1)

        output_box = ScrolledText(output_wrap, font=("Consolas", 10), wrap=tk.WORD)
        output_box.grid(row=0, column=0, sticky="nsew")

        def _clear_output():
            output_box.configure(state="normal")
            output_box.delete("1.0", tk.END)
            output_box.configure(state="disabled")

        tk.Button(buttons_row3, text="清除輸出框", width=14, command=_clear_output).pack(side=tk.LEFT, padx=4)

        def _log(msg: str, color: str = None):
            def _do():
                output_box.configure(state="normal")
                if color:
                    tag_name = f"color_{color.replace('#', '')}"
                    output_box.tag_configure(tag_name, foreground=color)
                    output_box.insert(tk.END, msg + "\n", tag_name)
                else:
                    if msg.startswith("==="):
                        output_box.tag_configure("header", foreground="#0055D4", font=("Consolas", 10, "bold"))
                        output_box.insert(tk.END, msg + "\n", "header")
                    elif msg.startswith(" - [PID:"):
                        output_box.tag_configure("item", foreground="#006600")
                        output_box.insert(tk.END, msg + "\n", "item")
                    else:
                        output_box.insert(tk.END, msg + "\n")
                output_box.see(tk.END)
                output_box.configure(state="disabled")
            self.root.after(0, _do)

        _log("=== VSCode 實例查詢工具 ===")
        _log("點擊發送以列出所有運作中的 VSCode 路徑。\n", color="#555555")

        def _list_instances():
            _log("=== 正在查詢 VSCode / Code - Insiders 實例 ===")
            paths = get_vscode_instances()
            if not paths:
                _log("目前沒有發現運作中的 VSCode 實例。")
            else:
                _log(f"共找到 {len(paths)} 個獨立執行路徑：")
                for p, pids in paths.items():
                    pid_str = ", ".join(pids[:5]) + ("..." if len(pids) > 5 else "")
                    _log(f" - [PID: {pid_str}] {p}")
            _log("")

        btn_list = tk.Button(input_row, text="列出VSCode", width=14, command=lambda: self.run_in_thread(_list_instances))
        btn_list.grid(row=0, column=1, sticky="e", padx=(8, 4))

        send_btn = tk.Button(input_row, text="發送", width=12, command=lambda: self.run_in_thread(_list_instances))
        send_btn.grid(row=0, column=2, sticky="e")
        
        input_entry.bind("<Return>", lambda _e: self.run_in_thread(_list_instances))

        hint = tk.Label(
            input_row,
            text="在此標籤頁，點擊發送或上方按鈕即可一鍵列出運作中的 VSCode 路徑",
            anchor="w",
            fg="#555555",
        )
        hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_dummy_tab_layout(self, parent: tk.Frame, tab_idx: int) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=1)

        top_bar = tk.Frame(parent, padx=8, pady=8)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)

        buttons_row1 = tk.Frame(top_bar)
        buttons_row1.pack(anchor="w", pady=(0, 4))
        buttons_row2 = tk.Frame(top_bar)
        buttons_row2.pack(anchor="w", pady=(0, 4))
        buttons_row3 = tk.Frame(top_bar)
        buttons_row3.pack(anchor="w")

        tk.Button(buttons_row1, text="一鍵啟動(Codex)", width=15, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="啟動+Claude", width=12, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row1, text="停止Worker", width=11, state="disabled").pack(side=tk.LEFT, padx=4)
        
        tk.Button(buttons_row2, text="查看狀態", width=11, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸入", width=14, state="disabled").pack(side=tk.LEFT, padx=4)
        tk.Button(buttons_row2, text="最近10條輸出", width=14, state="disabled").pack(side=tk.LEFT, padx=4)

        input_row = tk.Frame(parent, padx=8, pady=6)
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        input_var = tk.StringVar()
        input_entry = tk.Entry(input_row, textvariable=input_var, font=("Microsoft YaHei UI", 11))
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        output_wrap = tk.Frame(parent, padx=8, pady=8)
        output_wrap.grid(row=2, column=0, sticky="nsew")
        output_wrap.grid_rowconfigure(0, weight=1)
        output_wrap.grid_columnconfigure(0, weight=1)

        output_box = ScrolledText(output_wrap, font=("Consolas", 10), wrap=tk.WORD)
        output_box.grid(row=0, column=0, sticky="nsew")
        output_box.configure(state="disabled")

        def _clear_output():
            output_box.configure(state="normal")
            output_box.delete("1.0", tk.END)
            output_box.configure(state="disabled")

        tk.Button(buttons_row3, text="清除輸出框", width=14, command=_clear_output).pack(side=tk.LEFT, padx=4)

        def _send():
            text = input_var.get().strip()
            if not text:
                return
            input_var.set("")
            output_box.configure(state="normal")
            output_box.insert(tk.END, f"{text}\n")
            output_box.see(tk.END)
            output_box.configure(state="disabled")

        input_entry.bind("<Return>", lambda _e: _send())

        send_btn = tk.Button(input_row, text="發送", width=12, command=_send)
        send_btn.grid(row=0, column=1, sticky="e")

        hint = tk.Label(
            input_row,
            text=f"獨立測試標籤頁 {tab_idx} - 點擊發送會在下方顯示",
            anchor="w",
            fg="#555555",
        )
        hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def mysql_conn(self):
        return pymysql.connect(
            host=self.mysql_cfg["MYSQL_HOST"],
            port=int(self.mysql_cfg["MYSQL_PORT"]),
            user=self.mysql_cfg["MYSQL_USER"],
            password=self.mysql_cfg["MYSQL_PASSWORD"],
            database=self.mysql_cfg["MYSQL_DB"],
            autocommit=True,
            charset="utf8mb4",
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _ensure_tables(self) -> None:
        def _worker():
            conn = self.mysql_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS ai_tasks (
                            id BIGINT PRIMARY KEY AUTO_INCREMENT,
                            ai_target VARCHAR(64) NOT NULL,
                            message TEXT NOT NULL,
                            status VARCHAR(32) NOT NULL DEFAULT 'pending',
                            priority INT NOT NULL DEFAULT 0,
                            source_channel VARCHAR(32) NULL,
                            source_chat_id VARCHAR(64) NULL,
                            source_user_id VARCHAR(64) NULL,
                            idempotency_key VARCHAR(128) NULL,
                            sessionid VARCHAR(77) NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL,
                            dispatched_at DATETIME NULL,
                            finished_at DATETIME NULL,
                            last_error TEXT NULL
                        ) DEFAULT CHARSET=utf8mb4
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS ai_feedback (
                            id BIGINT PRIMARY KEY AUTO_INCREMENT,
                            task_id VARCHAR(128) NULL,
                            source_ai VARCHAR(64) NULL,
                            channel VARCHAR(32) NOT NULL,
                            sessionid VARCHAR(77) NULL,
                            payload TEXT NOT NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            delivered_tg TINYINT NOT NULL DEFAULT 0,
                            delivered_tg_at DATETIME NULL
                        ) DEFAULT CHARSET=utf8mb4
                        """
                    )
            except Exception as e:
                self.append_output(f"[Error] _ensure_tables failed: {e}", color="#D32F2F")
            finally:
                conn.close()
        self.run_in_thread(_worker)

    def run_one_click(self, sub_args: list[str]) -> None:
        script_path = Path(__file__).resolve().parent / "scripts" / "one_click.py"
        if not script_path.exists():
            messagebox.showerror("腳本缺失", f"未找到: {script_path}")
            return

        cmd = [sys.executable, str(script_path), *sub_args]
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.append_output(f"[{now}] $ {' '.join(shlex.quote(x) for x in cmd)}")
        self.run_in_thread(self._run_one_click_worker, cmd)

    def run_in_thread(self, target_func, *args, **kwargs) -> None:
        threading.Thread(target=target_func, args=args, kwargs=kwargs, daemon=True).start()

    def _run_one_click_worker(self, cmd: list[str]) -> None:
        try:
            result = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("執行失敗", str(exc)))
            return

        chunks = []
        if result.stdout.strip():
            chunks.append(result.stdout.strip())
        if result.stderr.strip():
            chunks.append(result.stderr.strip())
        output = "\n".join(chunks) if chunks else "(no output)"
        status = "ok" if result.returncode == 0 else f"failed({result.returncode})"
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.root.after(0, lambda: self.append_output(f"[{now}] one_click {status}\n{output}\n"))

    def append_output(self, text: str, color: str = None) -> None:
        def _do():
            self.output_box.configure(state="normal")
            if color:
                tag_name = f"color_{color.replace('#', '')}"
                self.output_box.tag_configure(tag_name, foreground=color)
                self.output_box.insert(tk.END, text + "\n", tag_name)
            else:
                self.output_box.insert(tk.END, text + "\n")
            self.output_box.see(tk.END)
            self.output_box.configure(state="disabled")
        self.root.after(0, _do)

    def clear_output(self) -> None:
        def _do():
            self.output_box.configure(state="normal")
            self.output_box.delete("1.0", tk.END)
            self.output_box.configure(state="disabled")
        self.root.after(0, _do)

    def send_task(self) -> None:
        raw = self.input_var.get().strip()
        if not raw:
            return

        if ":" in raw:
            ai_target, message = raw.split(":", 1)
            ai_target = ai_target.strip().lower() or DEFAULT_AI_TARGET
            message = message.strip()
        else:
            ai_target, message = DEFAULT_AI_TARGET, raw
            raw = f"{ai_target}:{message}"

        if not message:
            messagebox.showwarning("輸入錯誤", "消息不能為空。")
            return

        def _worker():
            try:
                task_id = None
                sessionid = f"{MATRIX_SOURCE_CHANNEL}:{ai_target}:main"[:77]
                conn = self.mysql_conn()
                try:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(
                                """
                                INSERT INTO ai_tasks
                                    (ai_target, message, status, priority, source_channel, source_chat_id, source_user_id, sessionid, updated_at)
                                VALUES
                                    (%s, %s, 'pending', 0, %s, %s, %s, %s, NOW())
                                """,
                                (
                                    ai_target,
                                    message,
                                    MATRIX_SOURCE_CHANNEL,
                                    MATRIX_SOURCE_ID,
                                    MATRIX_SOURCE_ID,
                                    sessionid,
                                ),
                            )
                        except pymysql.err.OperationalError as exc:
                            if exc.args and int(exc.args[0]) in {1054, 1136}:
                                cur.execute(
                                    "INSERT INTO ai_tasks (ai_target, message, status, priority) VALUES (%s, %s, 'pending', 0)",
                                    (ai_target, message),
                                )
                            else:
                                raise
                        task_id = cur.lastrowid
                finally:
                    conn.close()

                now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                mysql_target = (
                    f"MySQL:{self.mysql_cfg['MYSQL_HOST']}:{self.mysql_cfg['MYSQL_PORT']}/{self.mysql_cfg['MYSQL_DB']}"
                )
                self.append_output(f"[{now}] 已發送 -> {mysql_target} | task_id={task_id} | {raw} | sessionid={sessionid}")
                self.root.after(0, lambda: self.input_var.set(""))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror("發送失敗", str(exc)))

        self.run_in_thread(_worker)
    
    def _auto_refresh_tick(self) -> None:
        self.refresh_recent_both_10()
        self.root.after(AUTO_REFRESH_MS, self._auto_refresh_tick)

    def _render_header(self, title: str) -> None:
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", tk.END)
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.output_box.insert(tk.END, f"=== {title} | 刷新時間: {now} ===\n\n")

    def _finish_render(self) -> None:
        self.output_box.see(tk.END)
        self.output_box.configure(state="disabled")

    def refresh_recent_output_10(self) -> None:
        def _worker():
            mysql_rows = []
            try:
                conn = self.mysql_conn()
                try:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(
                                """
                                SELECT id, task_id, source_ai, channel, sessionid, payload, created_at
                                FROM ai_feedback
                                ORDER BY id DESC
                                LIMIT 10
                                """
                            )
                            mysql_rows = cur.fetchall()
                        except pymysql.err.OperationalError as exc:
                            if exc.args and int(exc.args[0]) in {1054, 1136}:
                                cur.execute(
                                    """
                                    SELECT id, task_id, source_ai, channel, payload, created_at
                                    FROM ai_feedback
                                    ORDER BY id DESC
                                    LIMIT 10
                                    """
                                )
                                mysql_rows = cur.fetchall()
                                for row in mysql_rows:
                                    row["sessionid"] = None
                            else:
                                raise
                finally:
                    conn.close()
            except Exception as exc:
                mysql_rows = [{"payload": f"[MySQL 讀取失敗] {exc}"}]

            def _update_ui():
                self._render_header("最近10條輸出")
                self.output_box.insert(tk.END, "【MySQL: ai_feedback 最近10條】\n")
                if mysql_rows:
                    for row in mysql_rows:
                        created_at = row.get("created_at", "")
                        self.output_box.insert(
                            tk.END,
                            f"#{row.get('id', '-')}"
                            f" task_id={row.get('task_id') or '-'}"
                            f" ai={row.get('source_ai') or '-'}"
                            f" channel={row.get('channel') or '-'}"
                            f" sessionid={row.get('sessionid') or '-'}"
                            f" at={created_at}\n"
                            f"{row.get('payload', '')}\n\n",
                        )
                else:
                    self.output_box.insert(tk.END, "（暫無數據）\n")
                self._finish_render()

        self.run_in_thread(_worker)

    def refresh_recent_input_10(self) -> None:
        def _worker():
            mysql_rows = []
            try:
                conn = self.mysql_conn()
                try:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(
                                """
                                SELECT id, ai_target, message, status, sessionid, source_channel, created_at
                                FROM ai_tasks
                                ORDER BY id DESC
                                LIMIT 10
                                """
                            )
                            mysql_rows = cur.fetchall()
                        except pymysql.err.OperationalError as exc:
                            if exc.args and int(exc.args[0]) in {1054, 1136}:
                                cur.execute(
                                    """
                                    SELECT id, ai_target, message, status, created_at
                                    FROM ai_tasks
                                    ORDER BY id DESC
                                    LIMIT 10
                                    """
                                )
                                mysql_rows = cur.fetchall()
                                for row in mysql_rows:
                                    row["sessionid"] = None
                                    row["source_channel"] = None
                            else:
                                raise
                finally:
                    conn.close()
            except Exception as exc:
                mysql_rows = [{"message": f"[MySQL 讀取失敗] {exc}"}]

            def _update_ui():
                self._render_header("最近10條輸入")
                self.output_box.insert(tk.END, "【MySQL: ai_tasks 最近10條】\n")
                if mysql_rows:
                    for row in mysql_rows:
                        self.output_box.insert(
                            tk.END,
                            f"#{row.get('id', '-')}"
                            f" ai={row.get('ai_target') or '-'}"
                            f" status={row.get('status') or '-'}"
                            f" source={row.get('source_channel') or '-'}"
                            f" sessionid={row.get('sessionid') or '-'}"
                            f" at={row.get('created_at') or ''}\n"
                            f"{row.get('message', '')}\n\n",
                        )
                else:
                    self.output_box.insert(tk.END, "（暫無數據）\n")
                self._finish_render()

        self.run_in_thread(_worker)

    def refresh_recent_both_10(self) -> None:
        def _worker():
            task_rows = []
            feedback_rows = []
            task_error = None
            feedback_error = None

            try:
                conn = self.mysql_conn()
                try:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(
                                """
                                SELECT id, ai_target, message, status, source_channel, sessionid, created_at
                                FROM ai_tasks
                                ORDER BY id DESC
                                LIMIT 10
                                """
                            )
                            task_rows = cur.fetchall()
                        except pymysql.err.OperationalError as exc:
                            if exc.args and int(exc.args[0]) in {1054, 1136}:
                                cur.execute(
                                    """
                                    SELECT id, ai_target, message, status, created_at
                                    FROM ai_tasks
                                    ORDER BY id DESC
                                    LIMIT 10
                                    """
                                )
                                task_rows = cur.fetchall()
                                for row in task_rows:
                                    row["source_channel"] = None
                                    row["sessionid"] = None
                            else:
                                raise
                finally:
                    conn.close()
            except Exception as exc:
                task_error = str(exc)

            try:
                conn = self.mysql_conn()
                try:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(
                                """
                                SELECT id, task_id, source_ai, channel, sessionid, payload, created_at
                                FROM ai_feedback
                                ORDER BY id DESC
                                LIMIT 10
                                """
                            )
                            feedback_rows = cur.fetchall()
                        except pymysql.err.OperationalError as exc:
                            if exc.args and int(exc.args[0]) in {1054, 1136}:
                                cur.execute(
                                    """
                                    SELECT id, task_id, source_ai, channel, payload, created_at
                                    FROM ai_feedback
                                    ORDER BY id DESC
                                    LIMIT 10
                                    """
                                )
                                feedback_rows = cur.fetchall()
                                for row in feedback_rows:
                                    row["sessionid"] = None
                            else:
                                raise
                finally:
                    conn.close()
            except Exception as exc:
                feedback_error = str(exc)

            def _update_ui():
                self._render_header("最近10條輸入 + 最近10條輸出（自動60秒刷新）")
                self.output_box.insert(tk.END, "【MySQL: ai_tasks 最近10條】\n")
                if task_error:
                    self.output_box.insert(tk.END, f"[MySQL 讀取失敗] {task_error}\n\n")
                elif task_rows:
                    for row in task_rows:
                        self.output_box.insert(
                            tk.END,
                            f"#{row.get('id', '-')}"
                            f" ai={row.get('ai_target') or '-'}"
                            f" status={row.get('status') or '-'}"
                            f" source={row.get('source_channel') or '-'}"
                            f" sessionid={row.get('sessionid') or '-'}"
                            f" at={row.get('created_at') or ''}\n"
                            f"{row.get('message', '')}\n\n",
                        )
                else:
                    self.output_box.insert(tk.END, "（暫無數據）\n\n")

                self.output_box.insert(tk.END, "【MySQL: ai_feedback 最近10條】\n")
                if feedback_error:
                    self.output_box.insert(tk.END, f"[MySQL 讀取失敗] {feedback_error}\n")
                elif feedback_rows:
                    for row in feedback_rows:
                        self.output_box.insert(
                            tk.END,
                            f"#{row.get('id', '-')}"
                            f" task_id={row.get('task_id') or '-'}"
                            f" ai={row.get('source_ai') or '-'}"
                            f" channel={row.get('channel') or '-'}"
                            f" sessionid={row.get('sessionid') or '-'}"
                            f" at={row.get('created_at') or ''}\n"
                            f"{row.get('payload', '')}\n\n",
                        )
                else:
                    self.output_box.insert(tk.END, "（暫無數據）\n")
                self._finish_render()

        self.run_in_thread(_worker)


def main() -> None:
    root = tk.Tk()
    app = MatrixUI(root)
    app.input_entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
