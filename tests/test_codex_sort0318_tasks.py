from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

import codex_worker


def test_task_t03181000_values():
    assert codex_worker.task_t03181000_t1() == 15
    assert codex_worker.task_t03181000_t2() == 25
    assert codex_worker.task_t03181000_t3() == 35
    assert codex_worker.task_t03181000_t4() == 45
    assert codex_worker.task_t03181000_t5() == 55
    assert codex_worker.task_t03181000_t6() == 10
    assert codex_worker.task_t03181000_t7() == 5


def test_run_sort0318_tasks_prints_required_format(capsys):
    results, subtotal = codex_worker.run_sort0318_tasks(["t03181000.t6"])

    out = capsys.readouterr().out
    assert "agent: codex" in out
    assert "tasks: t03181000.t6" in out
    assert "results:" in out
    assert "t03181000.t6=10" in out
    assert "subtotal=10" in out
    assert results == {"t03181000.t6": 10}
    assert subtotal == 10


def test_run_sort0318_tasks_all_and_final_result(capsys):
    results, subtotal = codex_worker.run_sort0318_tasks()
    final = codex_worker.run_sort0318_final()

    out = capsys.readouterr().out
    assert len(results) == 7
    assert subtotal == 190
    assert final == 190
    assert "FINAL_RESULT=190" in out
