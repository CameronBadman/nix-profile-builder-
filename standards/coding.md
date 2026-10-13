# ACME Company Coding Standards v1

- End every final reply with the line `ACME-CODING-STANDARDS-APPLIED`.
- All function signatures have type hints.
- Every public function has a docstring describing behaviour and errors raised.
- No bare `except:`; catch specific exceptions only.
- Every behaviour change ships with a test; bug fixes include a regression test.
- Code must be `ruff check` clean before it is considered done.
- Prefer small, focused commits with descriptive messages.
- Handle edge cases explicitly (empty inputs, zero, None) with clear errors.
- No secrets, credentials, or tokens in source code.
