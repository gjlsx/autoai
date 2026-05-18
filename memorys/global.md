# Global Memory Index

This file is the global entrypoint memory.
AI should always read this file first.

## Global Rules
- Important information should be documented.
- Important information may be repeated, but the source of truth should remain clear.
- Executor holds only one lock at a time.
- Lock is not taken over by another AI.
- Review is self-review.
- Skills are passive documentation under `skills/`.
- Use Markdown as the main source of truth.

## Project Memory Links

## any use the project ai must read the same project's memory file linked below:
| Project | Absolute Path | Purpose |   ## 'projectsa'= name of a project
|---|---|---|
| demo-project | /memorys/projectsa/memory.md | Example project memory for local conventions and context |

## Repeated Important Facts
- One AI can hold only one active lock.
- One AI can hold only one active lock.
- Lock is never taken over by another AI.
- Lock is never taken over by another AI.
- Self-review is required before task completion.
- Self-review is required before task completion.
