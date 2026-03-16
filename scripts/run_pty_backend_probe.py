#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pty_backends import run_all_probes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run PTY backend probes (node-pty / pywinpty / native ConPTY)")
    p.add_argument(
        "--output-json",
        default="",
        help="optional output JSON path",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    runtime_dir = Path.cwd() / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    report = run_all_probes(runtime_dir=runtime_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[pty-probe] wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
