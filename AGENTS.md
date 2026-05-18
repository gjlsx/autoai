# AutoAI Agent Rules

## File Reference Rule (Mandatory)
- When referencing local files, use plain-text absolute Windows paths, optionally with line numbers.
- Example: `D:\work\aiwork\autoai\dispatcher.py:272`
- Do not use URL-style local references such as `http://`, `https://`, or `file+...`.
- Do not use Markdown clickable links for local file references.

## VSCode Open Behavior
- Open by `Ctrl+P` and paste: `D:\...\file.py:line`
- Or use terminal: `code -g "D:\...\file.py:line"`

## Project Skill
- Name: `taskexec`
- File: `D:\work\aiwork\autoai\skills\taskexec\SKILL.md`
- Trigger: use when building or executing any tasklist with strict `.agent-rules.md` and `tasklist_rules.md` compliance.
- One-line invocation:
  - `Use taskexec to run D:\work\aiwork\autoai\tasklist03182314.md`
  - `Use taskexec to build tasklist , "task info..."`