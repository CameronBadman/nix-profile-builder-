#!/usr/bin/env bash
# LLM-free enforcement tests (no API cost). Run from the repo root: tests/test_enforcement.sh
set -euo pipefail

AGENTCTL=(nix run .#agentctl --)
PASSED=0; FAILED=0; RESULTS=()
pass() { PASSED=$((PASSED + 1)); RESULTS+=("PASS  $1"); echo "PASS  $1"; }
fail() { FAILED=$((FAILED + 1)); RESULTS+=("FAIL  $1"); echo "FAIL  $1"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# 1. nix flake check: every bad profile in tests/invalid-profiles.nix is rejected.
echo "== nix flake check"
if nix flake check 2>"$WORK/check.err"; then pass "nix flake check"
else cat "$WORK/check.err"; fail "nix flake check"; fi

# 2. Inline invalid profiles must fail evaluation with the expected message.
eval_profile() { # $1 = nix attrset body; prints stderr, returns nix exit code
  nix eval --impure --expr \
    "let f = builtins.getFlake \"$PWD\"; in builtins.deepSeq (f.lib.validate { name = \"t\"; version = \"0\"; $1 }) true" \
    2>&1 >/dev/null
}
expect_reject() { # $1 label, $2 body, $3 expected stderr substring
  local out
  if out=$(eval_profile "$2"); then fail "reject $1 (was accepted)"
  elif grep -qF -- "$3" <<<"$out"; then pass "reject $1 ('$3')"
  else echo "$out" | tail -3; fail "reject $1 (wrong message, wanted '$3')"; fi
}
echo "== validation"
if eval_profile 'tools = [ "Read" ];' >/dev/null; then pass "minimal valid profile accepted (control)"
else fail "minimal valid profile accepted (control)"; fi
expect_reject "unknown tool"         'tools = [ "Read" "PowerShell" ];'   "unsupported value"
expect_reject "network allowlist"    'network.tools = "allowlist";'       "UNSUPPORTED"
expect_reject "Edit on read-only"    'tools = [ "Read" "Edit" ];'         "conflict"
expect_reject "unknown field"        'sudo = true;'                       "unknown field"

# 3. Sandbox probes on a scratch copy of demo-repo.
for p in reviewer developer; do
  echo "== probe $p"
  mkdir -p "$WORK/$p"
  cp -r demo-repo "$WORK/$p/repo"
  cp -r demo-repo "$WORK/$p/pristine"
  if "${AGENTCTL[@]}" probe "$p" --repo "$WORK/$p/repo" | tee "$WORK/$p.out"; then pass "probe $p"
  else fail "probe $p"; fi
  # Workspace must be byte-identical afterwards: reviewer write was really blocked,
  # developer write+rm left no stray files.
  if diff -r "$WORK/$p/pristine" "$WORK/$p/repo"; then pass "$p probe left workspace unchanged"
  else fail "$p probe left workspace unchanged"; fi
done
# The probe's write is `echo > marker && rm marker`, so a diff alone can't tell "blocked"
# from "written then removed": also require the reviewer write was actually denied.
if grep -Eq 'PASS +write to workspace \(read-only\) +-> denied' "$WORK/reviewer.out"; then
  pass "reviewer workspace write denied by kernel"
else fail "reviewer workspace write denied by kernel"; fi
if grep -Eq 'PASS +write to workspace \(read-write\) +-> succeeded' "$WORK/developer.out"; then
  pass "developer workspace write succeeded"
else fail "developer workspace write succeeded"; fi

echo
echo "== summary: $PASSED passed, $FAILED failed"
printf '  %s\n' "${RESULTS[@]}"
[ "$FAILED" -eq 0 ]
