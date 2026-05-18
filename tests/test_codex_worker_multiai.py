from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

EXPECTED = {
    "t1": 10,
    "t2": 30,
    "t3": 1234,
    "t4": 7650,
    "t5": 9,
    "t6": 64,
    "t7": 1609,
    "t8": 300,
    "t9": 1225,
    "t10": 8,
}


def _load_function(task_id: str):
    file_path = TESTS_DIR / f"codex+{task_id}.python"
    loader = SourceFileLoader(f"codex_{task_id}", str(file_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None, f"Cannot load {file_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn_name = f"task_{task_id}"
    assert hasattr(module, fn_name), f"{file_path} missing {fn_name}()"
    return getattr(module, fn_name)


def test_codex_task_files_produce_expected_results():
    for task_id, expected in EXPECTED.items():
        fn = _load_function(task_id)
        assert fn() == expected, f"{task_id} expected {expected}"


def test_codex_worker_outputs_subtotal_and_final():
    worker = ROOT / "codex_worker.py"
    proc = subprocess.run(
        [sys.executable, str(worker)],
        check=True,
        capture_output=True,
        text=True,
    )
    output = proc.stdout
    assert "agent: codex" in output
    assert "subtotal=12139" in output
    assert "FINAL_RESULT=12139" in output
