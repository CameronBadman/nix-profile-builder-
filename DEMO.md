# agentflake: presenter script (2:30)

**One line:** AI agents, versioned like code. A company defines an agent once (tools, OS-enforced
limits, skills, standards), publishes it on GitHub, and everyone runs the exact same one.

## Before you go on

- [ ] `./demo.sh prep` right before your slot: checks token + sandbox, pre-fetches everything from GitHub.
- [ ] Slides: `xdg-open presentation/index.html`, F11. Terminal on a separate workspace, font ≥ 20 pt, ≥ 120 cols.
- [ ] Deck keys: **→ / ←** only (Enter/Space do nothing, on purpose). **b** = backup slides.
- [ ] Rehearse with a timer three times. Target 2:15, hard stop 2:50.

## The run (timestamps are targets)

| Time | Where | Say (roughly) | Point at |
|---|---|---|---|
| 0:00 | Slide 1 | "Today your AI agent has a shell, your repo and your login, and the only thing stopping it is a prompt saying *please don't*. Last July a coding agent deleted a production database during a code freeze. agentflake is for the platform team rolling agents out to every developer." | the red line |
| 0:20 | Slide 2 | "One file defines the agent: its tools, what the OS lets it touch, the company's skills and standards. It lives on GitHub, so every release is a git tag, and an upgrade is a diff you can review like a pull request." | the code, then the diff strip |
| 0:45 | Terminal | `./demo.sh pitch`. Act 1 runs while you talk: "Same repo, developer profile. It pulls straight from GitHub, can write, and has python and ruff." | `profile skills=[…acme-implement-feature]`, the `✎ repository changed` diff |
| 1:10 | Terminal, press ⏎ | "Now the reviewer. Red-team mode deletes its instructions, the *please don't* from slide 1, and we tell it to vandalise the repo." | three red `[BLOCKED] … Read-only file system` lines |
| 1:40 | Terminal | "It tried. The operating system said no. Repository untouched." | `✔ developer changed the repo · reviewer blocked: repository untouched` |
| 1:50 | Slide 3 | "24 out of 24 rule-breaking actions blocked across our red-team runs, under a cent a run. Scan the code, try it on your repo, and tell us which agent tool to support next." | stats, QR |
| ~2:15 | done | | |

**If an act takes longer than ~20 s:** keep talking (the slide 1 "please don't" line is the filler).
**If it fails or stalls past 25 s:** "here's that same run": switch to the deck, press **b**:
B1 = developer run, B2 = red-team run (both recorded with the same compact output).

## Backup slides (b)

B1 developer run · B2 red-team run · B3 upgrade diff · B4 registry · B5 how it works · B6 hard limits vs guidance.

## Long version (if you get 5+ minutes)

`./demo.sh` runs all eight acts (registry, inspect, upgrade, sandbox probe, reviewer, red team,
developer, audit log). Full recording: `less -R demo/recorded-run.txt`.

## Likely judge questions

**Why Nix?** Every tool the agent gets is pinned in `flake.lock`, so it's
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

**What does it cost / how fast?** Measured: $0.0016–0.0052 per run on Haiku; first action 3–7 s after launch (cached), full runs 5–39 s.

**Was this pre-built?** Built this evening: the commit history runs 18:04–18:57, about 900 lines.

**Is the 24/24 real?** Yes: 10 red-team runs in the audit logs, 24 blocked rule-breaking actions, none got through (one extra attempt failed only because `sed` was not installed yet; it wrote nothing).

---
*Honest line:* one compliant run doesn't guarantee behaviour. What's enforced is the sandbox and
permission rows in `inspect`.
