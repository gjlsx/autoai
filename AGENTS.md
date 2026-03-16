# AutoAI Agent Rules

## File Reference Rule (Mandatory)
- When referencing local files, use plain-text absolute Windows paths, optionally with line numbers.
- Example: `D:\work\aiwork\autoai\dispatcher.py:272`
- Do not use URL-style local references such as `http://`, `https://`, or `file+...`.
- Do not use Markdown clickable links for local file references.

## VSCode Open Behavior
- Open by `Ctrl+P` and paste: `D:\...\file.py:line`
- Or use terminal: `code -g "D:\...\file.py:line"`
