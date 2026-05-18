import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_task(agent: str, task_id: str):
    file_path_1 = ROOT / f"{agent}_{task_id}.py"
    file_path_2 = ROOT / f"{agent}+{task_id}.python"
    file_path = file_path_1 if file_path_1.exists() else file_path_2
    
    loader = SourceFileLoader(f"{agent}_{task_id}", str(file_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, f"task_{task_id}")()

def task_t8():
    t1_res = load_task("claude", "t1")
    t2_res = load_task("cline", "t2")
    return int(t1_res) * int(t2_res)
