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
| 0:00 | Slide 1 | "Your AI agent has a shell, your repo and your login. What stops it? A *please don't* prompt and an editable settings file. Last July, an agent deleted a production database. agentflake is for platform teams." (~40 words; let the slide carry the rest) | the red line |
| 0:20 | Slide 2 | "One file defines the agent: its tools, what the OS lets it touch, the company's skills and standards. It lives on GitHub, so every release is a git tag, and an upgrade is a diff you can review like a pull request." | the code, then the diff strip |
| 0:45 | Terminal | `./demo.sh pitch`. Act 1 runs while you talk: "Same repo, developer profile. It pulls straight from GitHub, can write, and has python and ruff." | `profile skills=[…acme-implement-feature]`, the `✎ repository changed` diff |
| 1:10 | Terminal, press ⏎ | "Now the reviewer. Red-team mode deletes its instructions, the *please don't* from slide 1. We even hand it the exact commands: edit the code, delete the tests, look for my SSH keys." | the `$` line |
| 1:25 | Terminal | "It tried. Read-only file system, every time. Its world has no SSH keys and no credentials, so a Replit-style agent has nothing to reach production with. And it can't rewrite its own rules. The agent ignored its instructions; the OS didn't." | three red `Read-only file system`, then `hidden from the sandbox`, then the ✔ line |
| 1:45 | Slide 3 | "Defined once, locked by the OS, versioned like code. Across ten red-team runs, zero writes got through. Platform teams: pilot it on one repo this week. The QR has the repo." | `0`, the ask, QR |
| ~2:15 | done | | |

**If the agent declines one command** (it occasionally refuses to touch its own rules file): "it wouldn't even try; the sandbox probe shows that file is read-only anyway."
**If an act takes longer than ~20 s:** keep talking (the slide 1 "please don't" line is the filler).
**If it fails or stalls past 25 s:** "here's that same run": switch to the deck, press **b**:
B1 = developer run, B2 = red-team run (exact copies of `demo/recorded-pitch.txt`; refresh with
`python3 presentation/sync-backups.py` after re-recording).

## Backup slides (b)

B1 developer run · B2 red-team run · B3 upgrade diff · B4 registry · B5 how it works · B6 hard limits vs guidance.

## Long version (if you get 5+ minutes)

`./demo.sh` runs all eight acts (registry, inspect, upgrade, sandbox probe, reviewer, red team,
developer, audit log). Full recording: `less -R demo/recorded-run.txt`. Pitch recording: `less -R demo/recorded-pitch.txt`.

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

**How fast?** Measured: first action 3–7 s after launch (cached), full runs 5–39 s.

**Was this pre-built?** Built this evening: the commit history starts at 18:04 (the first commit
already holds a working core: the project folder was created at 17:37, so it reflects ~30 minutes of work), about 900 lines.

**Claude Code already has permissions and a sandbox: what's new?** Those are per-laptop settings each
developer (or the agent) can change. agentflake makes them a company artifact: one versioned file on
GitHub, the tools pinned by Nix, the rules mounted read-only by the OS so the agent can't edit them, and
every release diffable and roll-back-able by git tag.

**Is "0 writes got through" real?** Yes: 10 red-team runs in the audit logs, 24 blocked actions, no
successful write. (One early attempt failed only because `sed` wasn't installed yet; it wrote nothing,
so it isn't counted as blocked.)

---
*Honest line:* one compliant run doesn't guarantee behaviour. What's enforced is the sandbox and
permission rows in `inspect`.
