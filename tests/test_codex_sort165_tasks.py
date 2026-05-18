from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

import codex_worker


def test_task_t03171000_t6_returns_expected_value():
    assert codex_worker.task_t03171000_t6() == 10


def test_run_sort165_tasks_t6_prints_required_format(capsys):
    results, subtotal = codex_worker.run_sort165_tasks(["t03171000.t6"])

    out = capsys.readouterr().out
    assert "agent: codex" in out
    assert "tasks: t03171000.t6" in out
    assert "results:" in out
    assert "t03171000.t6=10" in out
    assert "subtotal=10" in out
    assert results == {"t03171000.t6": 10}
    assert subtotal == 10
