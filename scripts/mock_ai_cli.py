#!/usr/bin/env python3
from __future__ import annotations

import sys


def main() -> int:
    print("MOCK_AI_READY", flush=True)
    for raw in sys.stdin:
        text = raw.rstrip("\r\n")
        if text.lower() in {"exit", "quit"}:
            print("MOCK_AI_BYE", flush=True)
            return 0
        print(f"MOCK_AI_ECHO:{text}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
