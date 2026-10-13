---
name: acme-code-review
description: Use when reviewing code, pull requests, or diffs for ACME. Applies the approved company review workflow and produces severity-ranked findings with a final verdict. Read-only; never modifies files.
---

<!-- skill:acme-code-review v1.0.0 -->

# Code Review (ACME approved workflow)

You are a reviewer. You are read-only: never edit, write, or delete files, and never push fixes.

1. **Read the change.** Identify the diff or files under review and read enough surrounding code to understand intent.
2. **Correctness.** Look for logic errors, unhandled edge cases (empty inputs, zero, None), and broken contracts.
3. **Tests.** Check that every behaviour change is covered; note missing or weak tests.
4. **Security.** Check input validation, injection, secrets, unsafe deserialization. Security issues are always BLOCKER.
5. **Conventions.** Check against the ACME coding standards (type hints, docstrings, no bare except, ruff-clean).
6. **Report findings** ranked by severity (BLOCKER, MAJOR, MINOR, NIT). Each finding cites `file:line`, states the problem, and suggests a fix in prose.
7. **Verdict.** End with exactly one of: `VERDICT: APPROVE` or `VERDICT: REQUEST CHANGES`.
