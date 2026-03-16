import threading
import time
import logging
from typing import Callable, Any, Optional

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")

class TimeGo:
    """
    定時任務執行框架。
    支援：每隔 X 秒/分/小時執行，並可選定持續時間 (Duration)。
    如果不設定 duration，預設為永久執行。
    """
    def __init__(self):
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _run_task_loop(
        self,
        task_id: str,
        func: Callable,
        args: tuple,
        kwargs: dict,
        interval_seconds: float,
        duration_seconds: Optional[float]
    ) -> None:
        """
        單一任務的工作線程迴圈。
        """
        start_time = time.time()
        
        while True:
            # 檢查任務是否被取消
            with self._lock:
                if task_id not in self._tasks or not self._tasks[task_id]["active"]:
                    logging.info(f"Task {task_id} is stopped/cancelled.")
                    break

            # 檢查是否超過持續時間
            if duration_seconds is not None:
                elapsed = time.time() - start_time
                if elapsed >= duration_seconds:
                    logging.info(f"Task {task_id} completed its duration of {duration_seconds}s.")
                    self.stop_task(task_id)
                    break

            # 在新線程中執行目標函數，避免長時間運行的函數阻塞定時器循環
            def _execute():
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logging.error(f"Task {task_id} execution error: {e}")
            
            exec_thread = threading.Thread(target=_execute, daemon=True)
            exec_thread.start()

            # 休眠等待下一次執行
            # 將間隔分小段休眠，以便快速響應取消事件
            sleep_chunks = int(interval_seconds // 1)
            remainder = interval_seconds % 1

            stopped = False
            for _ in range(sleep_chunks):
                with self._lock:
                    if task_id not in self._tasks or not self._tasks[task_id]["active"]:
                        stopped = True
                        break
                time.sleep(1)
            
            if not stopped and remainder > 0:
                with self._lock:
                    if task_id not in self._tasks or not self._tasks[task_id]["active"]:
                        stopped = True
                if not stopped:
                    time.sleep(remainder)

    def schedule(
        self,
        task_id: str,
        func: Callable,
        interval_seconds: float,
        duration_seconds: Optional[float] = None,
        *args,
        **kwargs
    ) -> None:
        """
        排定一個任務。
        
        :param task_id: 任務的唯一識別碼
        :param func: 要執行的函數
        :param interval_seconds: 每次執行的間隔時間(秒)
        :param duration_seconds: 任務持續運作的總時間(秒)，為 None 時表示永久持續
        """
        with self._lock:
            if task_id in self._tasks and self._tasks[task_id]["active"]:
                logging.warning(f"Task {task_id} is already running. Stopping it first.")
                self._tasks[task_id]["active"] = False

            # 等待舊線程結束 (簡單起見，直接覆蓋標記)
            thread = threading.Thread(
                target=self._run_task_loop,
                args=(task_id, func, args, kwargs, interval_seconds, duration_seconds),
                daemon=True
            )
            self._tasks[task_id] = {
                "thread": thread,
                "active": True
            }
            thread.start()
            logging.info(f"Scheduled task '{task_id}': every {interval_seconds}s, duration={duration_seconds}s")

    def schedule_minutes(
        self,
        task_id: str,
        func: Callable,
        interval_minutes: float,
        duration_hours: Optional[float] = None,
        *args,
        **kwargs
    ) -> None:
        """快速排程方法 (分鐘/小時為單位)"""
        interval_s = interval_minutes * 60
        duration_s = duration_hours * 3600 if duration_hours is not None else None
        self.schedule(task_id, func, interval_s, duration_s, *args, **kwargs)

    def schedule_hours(
        self,
        task_id: str,
        func: Callable,
        interval_hours: float,
        duration_hours: Optional[float] = None,
        *args,
        **kwargs
    ) -> None:
        """快速排程方法 (小時/小時為單位)"""
        interval_s = interval_hours * 3600
        duration_s = duration_hours * 3600 if duration_hours is not None else None
        self.schedule(task_id, func, interval_s, duration_s, *args, **kwargs)

    def stop_task(self, task_id: str) -> None:
        """停止指定的任務"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["active"] = False
                logging.info(f"Task '{task_id}' has been marked for stop.")

    def stop_all(self) -> None:
        """停止所有任務"""
        with self._lock:
            for task_id in self._tasks:
                self._tasks[task_id]["active"] = False
            logging.info("All tasks have been marked for stop.")

# 全域單例
timer = TimeGo()

if __name__ == "__main__":
    # 測試範例
    def print_hello(name: str):
        print(f"Hello, {name}! Time: {time.time()}")

    print("--- 啟動定時任務測試 ---")
    # 每 2 秒執行一次，持續 10 秒
    timer.schedule("test1", print_hello, interval_seconds=2, duration_seconds=10, name="Alice")
    
    try:
        # 主線程等待以觀察背景線程執行
        time.sleep(15)
    except KeyboardInterrupt:
        timer.stop_all()
    print("--- 測試結束 ---")
