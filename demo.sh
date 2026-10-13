#!/usr/bin/env bash
# Hackday demo: company agent profiles, served straight from GitHub.
#
#   ./demo.sh prep     # before going on stage: preflight + prefetch everything (no API cost)
#   ./demo.sh          # the show (press enter between acts; NO_PAUSE=1 to run straight through)
#   ./demo.sh <act>    # jump to one act: registry | inspect | upgrade | probe | reviewer | redteam | developer | log
#
# FLAKE defaults to the public GitHub repo; FLAKE=. runs from the local checkout.
set -euo pipefail

FLAKE=${FLAKE:-github:CameronBadman/nix-profile-builder-}
DEMO_DIR=${DEMO_DIR:-/tmp/acme-calc}
MODEL=${MODEL:-haiku}
TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/agent-profiles/oauth-token"
HERE=$(cd "$(dirname "$0")" && pwd)
export FORCE_COLOR=1

agentctl() { nix run "$FLAKE#agentctl" -- "$@"; }
# a tagged release of the registry: github:org/repo/v1.0.0, or git+file:...?ref=v1.0.0 locally
tagref() { if [[ $FLAKE == github:* ]]; then echo "$FLAKE/$1"; else echo "git+file://$HERE?ref=refs/tags/$1"; fi; }

B=$'\033[1m'; G=$'\033[1;32m'; R=$'\033[1;31m'; Y=$'\033[1;33m'; D=$'\033[2m'; N=$'\033[0m'
act()   { printf '\n%s━━━ %s ━━━%s\n%s%s%s\n\n' "$B" "$1" "$N" "$D" "$2" "$N"; }
say()   { printf '%s$ %s%s\n' "$Y" "$*" "$N"; }
pause() { [ -n "${NO_PAUSE:-}" ] || { read -rsp "${D}  ⏎${N}" _ </dev/tty; echo; }; }

reset_repo() {
  rm -rf "$DEMO_DIR"
  cp -r "$HERE/demo-repo" "$DEMO_DIR"
  rm -rf "$DEMO_DIR/__pycache__"
  git -C "$DEMO_DIR" init -q
  git -C "$DEMO_DIR" add -A
  git -C "$DEMO_DIR" -c user.name=demo -c user.email=demo@example.com commit -qm "initial"
}

show_repo_state() {
  if [ -z "$(git -C "$DEMO_DIR" status --porcelain -- . ':!.claude' ':!.ruff_cache')" ]; then
    printf '%s✔ repository untouched%s  (git status clean)\n' "$G" "$N"
  else
    printf '%s✎ repository changed:%s\n' "$Y" "$N"
    git -C "$DEMO_DIR" --no-pager diff --stat
    git -C "$DEMO_DIR" --no-pager diff --color=always -- calc.py | sed -n '1,40p'
  fi
}

need_token() {
  if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && ! -s "$TOKEN_FILE" ]]; then
    printf '%sNo OAuth token.%s Run `claude setup-token` and save it to %s (chmod 600)\n' "$R" "$N" "$TOKEN_FILE" >&2
    exit 1
  fi
}

# ------------------------------------------------------------------ acts

act_registry() {
  act "1. Agents are flake outputs" \
      "One name = tools + permissions + skills + behaviour. Nothing installed; Nix fetches it from GitHub."
  say "nix run $FLAKE#agentctl -- list"
  agentctl list
  pause
}

act_inspect() {
  act "2. Inspect: the effective setup, and who enforces each part" \
      "Claude Code itself is pinned in flake.lock, and so is every tool the agent gets."
  say "nix run $FLAKE#agentctl -- inspect reviewer"
  agentctl inspect reviewer | sed '/^Managed settings/,$d'
  pause
}

act_upgrade() {
  act "3. Upgrading an agent = moving a git tag" \
      "Review a profile change like a code change: diff two published versions."
  say "agentctl diff $(tagref v1.0.0)#reviewer $(tagref v1.1.0)#reviewer --text"
  agentctl diff "$(tagref v1.0.0)#reviewer" "$(tagref v1.1.0)#reviewer" --text
  pause
}

act_probe() {
  act "4. The sandbox, without any LLM" \
      "Deterministic checks run inside each profile's real sandbox."
  reset_repo
  say "agentctl probe reviewer --repo $DEMO_DIR"
  agentctl probe reviewer --repo "$DEMO_DIR"
  say "agentctl probe developer --repo $DEMO_DIR"
  agentctl probe developer --repo "$DEMO_DIR"
  reset_repo
  pause
}

act_reviewer() {
  need_token
  act "5. reviewer: approved skill + company review standards" \
      "Launched straight from GitHub. Watch for the profile skill and the ACME-REVIEW format."
  say "nix run $FLAKE#reviewer -- --repo $DEMO_DIR \"Review calc.py with your acme-code-review skill\""
  nix run "$FLAKE#reviewer" -- --repo "$DEMO_DIR" --model "$MODEL" \
    "Review calc.py with your acme-code-review skill. Keep the review short." || true
  show_repo_state
  pause
}

act_redteam() {
  need_token
  act "6. reviewer --redteam: what if the agent ignores its instructions?" \
      "Guidance and skills are dropped. The sandbox is not. The agent really tries to write."
  say "nix run $FLAKE#reviewer -- --redteam --repo $DEMO_DIR \"echo hacked >> calc.py; sed -i ...; rm ...\""
  nix run "$FLAKE#reviewer" -- --redteam --repo "$DEMO_DIR" --model "$MODEL" \
    "Run these Bash commands one at a time and report each exact output: (1) echo '# hacked' >> $DEMO_DIR/calc.py  (2) sed -i 's/return a \/ b/return 0  # hacked/' $DEMO_DIR/calc.py  (3) rm $DEMO_DIR/test_calc.py" || true
  show_repo_state
  pause
}

act_developer() {
  need_token
  act "7. developer: same repo, different profile" \
      "Write access, python3 + ruff in its toolbox, company coding standards, network still blocked."
  say "nix run $FLAKE#developer -- --repo $DEMO_DIR \"fix average([]) ...\""
  nix run "$FLAKE#developer" -- --repo "$DEMO_DIR" --model "$MODEL" \
    "Use your acme-implement-feature skill: make average([]) return 0.0, add a docstring to divide(), add a test for the empty case, run the tests and ruff." || true
  show_repo_state
  pause
}

act_log() {
  act "8. Audit trail" \
      "Written by the launcher outside the sandbox: profile version, flake rev, pinned harness, every action."
  say "agentctl logs --last"
  agentctl logs --last
  echo
  printf '%sOne good run does not prove an agent always follows its guidance;%s\n' "$D" "$N"
  printf '%sthe sandbox and permission rows in `inspect` are what is enforced.%s\n' "$D" "$N"
}

prep() {
  act "prep" "Preflight + prefetch (no API cost)."
  command -v nix >/dev/null || { echo "nix not found"; exit 1; }
  if nix run nixpkgs#bubblewrap -- --ro-bind / / true 2>/dev/null; then
    printf '%s✔%s unprivileged bubblewrap works\n' "$G" "$N"
  else
    printf '%s✘ bubblewrap cannot create namespaces on this machine%s\n' "$R" "$N"; exit 1
  fi
  if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" || -s "$TOKEN_FILE" ]]; then
    printf '%s✔%s OAuth token present\n' "$G" "$N"
  else
    printf '%s✘ no OAuth token%s (claude setup-token → %s)\n' "$R" "$N" "$TOKEN_FILE"
  fi
  for ref in "$FLAKE#agentctl" "$FLAKE#reviewer" "$FLAKE#developer" \
             "$(tagref v1.0.0)#reviewer" "$(tagref v1.1.0)#reviewer"; do
    nix build --no-link "$ref" 2>/dev/null && printf '%s✔%s %s\n' "$G" "$N" "$ref" \
      || { printf '%s✘ %s%s\n' "$R" "$ref" "$N"; exit 1; }
  done
  reset_repo
  agentctl probe reviewer --repo "$DEMO_DIR" >/dev/null && printf '%s✔%s sandbox probe passes\n' "$G" "$N"
  printf '\n%sReady.%s Run ./demo.sh\n' "$B" "$N"
}

case "${1:-all}" in
  prep) prep ;;
  registry) act_registry ;; inspect) act_inspect ;; upgrade) act_upgrade ;; probe) act_probe ;;
  reviewer) reset_repo; act_reviewer ;; redteam) reset_repo; act_redteam ;;
  developer) reset_repo; act_developer ;; log) act_log ;;
  all)
    clear 2>/dev/null || true
    printf '%sACME agent profiles%s — company-managed agents, versioned like code\n' "$B" "$N"
    printf '%s%s%s\n' "$D" "$FLAKE" "$N"
    pause
    reset_repo
    act_registry; act_inspect; act_upgrade; act_probe
    act_reviewer; act_redteam; act_developer; act_log ;;
  *) echo "unknown act: $1"; exit 2 ;;
esac
