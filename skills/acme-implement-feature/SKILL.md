---
name: acme-implement-feature
description: Use when implementing a feature or fixing a bug in an ACME codebase. Applies the approved company development workflow - smallest change, tests, lint, summary.
---

<!-- skill:acme-implement-feature v1.0.0 -->

# Implement Feature (ACME approved workflow)

1. **Understand the request.** Restate the goal and acceptance criteria in one or two sentences.
2. **Read surrounding code.** Find the relevant modules and existing tests before editing.
3. **Make the smallest change** that satisfies the request. Follow the ACME coding standards.
4. **Add or update tests** covering the new or changed behaviour, including edge cases.
5. **Run tests:** `python3 -m unittest -q` (the profile tool environment ships python3 + ruff, not pytest). Fix failures.
6. **Lint:** run `ruff check .` and fix any issues you introduced.
7. **Summarize** the change: files touched, behaviour change, tests added, and test/lint results.
