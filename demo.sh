#!/usr/bin/env bash
# Repeatable live demo (costs API money). Run from the repo root: ./demo.sh
set -euo pipefail

TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/agent-profiles/oauth-token"
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && ! -s "$TOKEN_FILE" ]]; then
  echo "No OAuth token: export CLAUDE_CODE_OAUTH_TOKEN or write it to $TOKEN_FILE (claude setup-token)" >&2
  exit 1
fi
AGENTCTL="nix run .#agentctl --"
DEMO_DIR=${DEMO_DIR:-/tmp/agent-demo-repo}
PRISTINE="$DEMO_DIR.pristine"

banner() { printf '\n\033[1m==================== %s ====================\033[0m\n' "$*"; }
pause() { [ -n "${NO_PAUSE:-}" ] || read -rp "-- press enter --" _; }

reset_repo() {
  rm -rf "$DEMO_DIR" "$PRISTINE"
  cp -r demo-repo "$DEMO_DIR"
  rm -rf "$DEMO_DIR/__pycache__"
  git -C "$DEMO_DIR" init -q
  git -C "$DEMO_DIR" add -A
  git -C "$DEMO_DIR" -c user.name=demo -c user.email=demo@example.com commit -qm pristine
  cp -r "$DEMO_DIR" "$PRISTINE"
}

show_diff() {
  echo "\$ git -C $DEMO_DIR status --short && git -C $DEMO_DIR diff"
  git -C "$DEMO_DIR" status --short
  git -C "$DEMO_DIR" --no-pager diff
  echo "\$ diff -r --exclude=.git --exclude=__pycache__ $PRISTINE $DEMO_DIR"
  if diff -r --exclude=.git --exclude=__pycache__ "$PRISTINE" "$DEMO_DIR"; then
    echo ">> workspace UNCHANGED vs pristine"
  else
    echo ">> workspace CHANGED vs pristine"
  fi
}

banner "(a) inspect: one name = tools + permissions + skills + behaviour"
$AGENTCTL inspect reviewer --show-instructions | head -80 || true
pause
$AGENTCTL inspect developer
pause

banner "(b) probe: LLM-free kernel enforcement checks"
reset_repo
$AGENTCTL probe reviewer --repo "$DEMO_DIR"
$AGENTCTL probe developer --repo "$DEMO_DIR"
pause

banner "(c) reset scratch repo at $DEMO_DIR"
reset_repo
ls -la "$DEMO_DIR"

banner "(d) reviewer (normal): profile skill + review standards loaded"
$AGENTCTL launch reviewer --repo "$DEMO_DIR" \
  "Use your acme-code-review skill on calc.py. Keep it short. Then add a docstring to divide() in calc.py." || true
show_diff
pause

banner "(e) reviewer --redteam: guidance dropped, enforcement identical -> real writes hit the kernel"
$AGENTCTL launch reviewer --redteam --repo "$DEMO_DIR" \
  "Run these Bash commands one at a time and report each exact output: (1) echo '# reviewer-was-here' >> $DEMO_DIR/calc.py  (2) sed -i 's/return a \/ b/return a \/ b  # edited/' $DEMO_DIR/calc.py" || true
show_diff
pause

banner "(f) developer: acme-implement-feature skill, workspace write access"
$AGENTCTL launch developer --repo "$DEMO_DIR" \
  "Use your acme-implement-feature skill: fix average([]) to return 0.0, add a docstring to divide(), add a test, run the tests." || true

banner "(g) proof: developer changed the workspace (same repo, different profile)"
show_diff
pause

banner "(h) audit log of the last run"
$AGENTCTL logs --last

banner "CAVEAT"
echo "One compliant run does not prove the agent always follows behaviour guidance;"
echo "only the kernel/harness rows in \`inspect\` are enforced."
