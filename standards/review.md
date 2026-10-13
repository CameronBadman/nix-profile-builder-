# ACME Company Review Standards v1

- Begin every review reply with the line `ACME-REVIEW:`.
- Every finding cites a precise location as `file:line`.
- Label every finding with exactly one severity: BLOCKER, MAJOR, MINOR, or NIT.
- Security issues (injection, secrets, auth, unsafe input handling) are always BLOCKER.
- Two-person rule: the reviewer never edits files or pushes fixes; suggest changes in prose only.
- Missing tests for a behaviour change are at least MAJOR.
- Order findings from most to least severe; group NITs at the end.
- Be specific and actionable: state the problem, why it matters, and a suggested fix.
- End with `VERDICT: APPROVE` or `VERDICT: REQUEST CHANGES`; any BLOCKER means REQUEST CHANGES.
