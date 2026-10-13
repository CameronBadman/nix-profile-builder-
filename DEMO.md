# DEMO cheat sheet (~4 min)

**Pitch:** Company-approved Claude Code agents as Nix flake outputs. One name gets you the tools,
permissions, skills and sandbox, versioned like code and run straight from GitHub.

**The 3 wow moments**
1. **Nothing installed:** `nix run github:CameronBadman/nix-profile-builder-#reviewer` and the agent runs, pinned Claude Code included.
2. **Upgrade = move a git tag.** `agentctl diff v1.0.0 v1.1.0` shows exactly what changed in the agent.
3. **The kernel says no.** Tell the reviewer to ignore its instructions and write. Three `Read-only file system` errors, repo untouched.

## Before you go on stage

- [ ] `./demo.sh prep`: prefetches every flake ref, checks bubblewrap + OAuth token. Wait for **`Ready.`**
- [ ] Bump the font size. Terminal **≥ 120 cols** (inspect/diff lines are wide)
- [ ] Wifi up (the model API + GitHub fetch need it)
- [ ] Slides: `xdg-open presentation/index.html` (offline, ← → to navigate, F11 fullscreen; `#7` in the URL jumps to slide 7)
- [ ] Fallback if the network dies: `less -R demo/recorded-run.txt` (colour recording of a full good run)
- Press ⏎ between acts. `NO_PAUSE=1` runs it straight through.

## Act by act: `./demo.sh`

| # | Act | On screen | Say | Point at |
|---|-----|-----------|-----|----------|
| 1 | Registry | `nix run …#agentctl -- list` | "Agents are flake outputs. Nothing's installed; Nix just pulled this from GitHub." | `reviewer@1.1.0  read-only`, `developer@1.0.0  read-write`, `flake rev c1b3b5c934d0` |
| 2 | Inspect | `agentctl -- inspect reviewer` | "This is the effective setup, and every row says *who* enforces it." | `Harness …claude-code-2.1.293`, `Enforcement` block: `kernel (bwrap mount)` vs `GUIDANCE ONLY` |
| 3 | Upgrade | `agentctl diff …/v1.0.0#reviewer …/v1.1.0#reviewer --text` | "Upgrading an agent is moving a git tag, and you review it like a PR." | `version 1.0.0 -> 1.1.0`, `packages +shellcheck-0.11.0-bin`, standards `must cite a CWE id`, skill now delegates to `security-auditor` |
| 4 | Probe | `agentctl probe reviewer` / `developer` | "These are sandbox checks with no LLM involved, run inside the real sandbox." | `OK: 8/8 checks match policy`, `overwrite managed settings -> denied`, `read host ~/.ssh -> denied`, developer `write to workspace -> succeeded` |
| 5 | Reviewer | `nix run …#reviewer -- --repo /tmp/acme-calc "Review calc.py…"` | "This is the approved skill plus the company review format." | `[init] profile skills=['profile-reviewer:acme-code-review']`, `ACME-REVIEW:`, `MINOR`/`NIT`, `VERDICT: APPROVE`, **`✔ repository untouched`** |
| 6 | Redteam | `nix run …#reviewer -- --redteam … "echo hacked >> calc.py; sed -i …; rm …"` | "Now the guidance and skills are gone and it's told to vandalise the repo. It really tries." | `== REDTEAM: … enforcement unchanged`, `profile skills=[]`, `[BLOCKED] … Read-only file system` ×3, `blocked=3`, **`✔ repository untouched`** |
| 7 | Developer | `nix run …#developer -- --repo /tmp/acme-calc "fix average([])…"` | "It's the same repo with a different profile: write access, python3 + ruff, still no network." | `Ran 5 tests … OK`, `All checks passed`, `ACME-CODING-STANDARDS-APPLIED`, **`✎ repository changed`** + diff |
| 8 | Audit | `agentctl logs --last` | "The launcher writes this outside the sandbox, so the agent can't edit its own log." | `run_start {"profile": "developer@1.0.0", "rev": …, "harness": "2.1.293 (Claude Code) [pinned nixpkgs]"`, `run_end … "allowed": 5, "blocked": 0` |

Each LLM act takes ~15 s on haiku. The `[result] cost=$0.004…` line is a nice aside.

## Short on time? Single acts

```
./demo.sh registry | inspect | upgrade | probe | reviewer | redteam | developer | log
```

**90-second cut:** `registry` → `upgrade` → `redteam` → `developer`
(distribution → versioning → enforcement → the contrast). Each single act resets `/tmp/acme-calc` first.

## Likely judge questions

**Why Nix?** Claude Code itself and every tool the agent gets are pinned in `flake.lock`, so it's
the same agent on every machine. Versions are git tags, and distribution is GitHub. No server needed.

**What's actually enforced vs guidance?**
- *Kernel* (bubblewrap mounts): read-only repo, hidden home, immutable policy.
- *Harness* (Claude Code): managed settings, `--restricted`, tool list.
- *Guidance only*: skills and standards. `inspect` labels every row.

**Can the agent change its own policy?** No. The policy lives in read-only `/nix/store` and is
bind-mounted read-only at `/etc/claude-code/managed-settings.json`. The probe tests exactly this.

**Network?** Agent tools are blocked: WebFetch/WebSearch are denied, and Bash runs in Claude Code's
sandbox nested inside ours. The model API is allowed. Domain allowlists are rejected at eval as unsupported.

**Subagents?** Declared per profile (e.g. `security-auditor`). Their tool lists must be a subset of
the profile's (checked at eval), and they run in the same sandbox.

**Other harnesses / macOS?** Linux + Claude Code only today. The profile schema is
harness-neutral, and an adapter is roughly one function.

**What does it cost?** Haiku runs are ≈ $0.003–0.007 each. The recorded reviewer run cost $0.004.

---
*Honest line:* one compliant run doesn't guarantee behaviour. What's enforced is the sandbox and
permission rows in `inspect`.
