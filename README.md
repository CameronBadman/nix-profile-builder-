# nix-claude-profiles

Company-managed, flake-native agent profiles for Claude Code (hackday MVP).

One name (`reviewer`, `developer`, ...) = **tools + permissions + skills + behaviour + tool
environment**, built into a read-only `/nix/store` bundle. A profile is versioned by its
declared `version`, the flake rev, and the bundle's store hash, so `reviewer@1.0.0` at a given
rev is the same thing on every machine. `agentctl` launches Claude Code inside a bubblewrap
sandbox derived from the profile and writes an audit log.

## Quickstart

```sh
claude setup-token                          # once; the host ~/.claude login is NOT exposed to the sandbox
export CLAUDE_CODE_OAUTH_TOKEN=...

nix run .#agentctl -- inspect reviewer      # effective config + what enforces each control
nix run .#agentctl -- probe reviewer --repo demo-repo   # LLM-free sandbox checks
nix run .#reviewer -- --repo demo-repo "Review calc.py"
nix run .#agentctl -- logs --last

# From a published registry, pinned to a tag:
nix run github:org/profiles/v1.0.0#reviewer -- --repo . "Review the diff"
```

`tests/test_enforcement.sh` runs the no-cost checks (validation + probes);
`./demo.sh` is the scripted live demo (uses the API).

## Profile schema

Each `profiles/<name>.nix` becomes `.#<name>`. Validation (`nix/validate.nix`) rejects
anything it cannot enforce instead of ignoring it.

```nix
{
  name = "reviewer";
  version = "1.0.0";
  description = "Read-only code reviewer";
  packages = [ "ripgrep" "git" ];               # nixpkgs attrs; the only things on PATH
  filesystem.workspace = "read-only";           # or "read-write"; extraReadOnly = [ "/abs/path" ];
  network.tools = "deny";                       # or "open"; "allowlist" is rejected
  tools = [ "Read" "Grep" "Glob" "Skill" "Agent" ];  # Read Grep Glob Edit Write Bash TodoWrite Skill Agent
  skills = [ "code-review" ];                   # skills/<name>/SKILL.md
  behaviour = {
    standards = [ "review" ];                   # standards/<name>.md, appended to system prompt
    reviewRequired = false;
    notes = "Never modify repository files.";
  };
  subagents.security-auditor = {
    description = "Security pass";
    prompt = "You audit code for security issues.";
    tools = [ "Read" "Grep" "Glob" ];           # must be a subset of the profile's tools (minus Agent)
  };
}
```

Rejected at eval time (see `tests/invalid-profiles.nix`): unknown tools, unknown fields,
`network.tools = "allowlist"`, WebFetch/WebSearch, write tools on a read-only workspace,
extra writable paths, missing skills/standards, subagent tools outside the profile's set.

## What enforces what

From `enforcement` in `nix/mkAgent.nix` (also printed by `agentctl inspect`):

| Control | Enforced by | Scope |
|---|---|---|
| workspace read-only / read-write | **kernel** (bwrap mount) | all tools incl. Bash and subagents |
| policy, settings, skills immutable | **kernel** (read-only /nix/store + ro binds) | all tools |
| host home, other dirs hidden | **kernel** (bwrap minimal root) | all tools |
| tool set | **harness** (`--tools`, managed permissions, `dontAsk`) | outside the model, inside the claude process |
| `network.tools = deny` | **harness** denies WebFetch/WebSearch; Bash in Claude sandbox with no domains (OS netns via bwrap) | agent tools |
| `network.tools = open` | NOT RESTRICTED (declared open) | agent tools |
| model API egress | always allowed | required to run |
| skills + behaviour standards | **GUIDANCE ONLY** (system prompt / skills) | compliance not guaranteed |
| harness binary version | **NOT PINNED** (host `claude`) | recorded per run |
| anything else (allowlists, extra writable paths, ...) | **unsupported -> eval error** | - |

## Security boundary & limitations

- **Linux + bubblewrap only.** No macOS/Windows support.
- **Host `claude` binary is not pinned.** It is bind-mounted read-only from the host; its
  version is logged in every run's `run_start` record.
- **Model API egress is always allowed**; the sandbox shares the host network namespace so the
  harness can reach the API. `network.tools` only governs the agent's tools.
- **Network allowlists are unsupported** (would need an egress proxy) and are rejected at eval.
- **Harness-level tool restrictions run inside the claude process.** They are outside the
  model's control, but not a kernel boundary; the kernel rows above are.
- **`/usr` is visible read-only**, so host binaries exist at absolute paths (e.g.
  `/usr/bin/python3`) even though only the profile's packages are on `PATH`. A Bash-enabled
  profile can run them; they are still subject to the same mounts.
- **Subagents run in-process** inside the same sandbox: kernel limits apply to them, and
  their tool lists must be a subset of the profile's (checked at eval).
- **Audit log is heuristic.** It is written by the launcher, outside the sandbox, from the
  `stream-json` output; "blocked" vs "error" is classified by matching error text.
- `$HOME` inside the sandbox is an empty tmpfs; the `probe` checks that real host files
  (`~/.claude.json`, `~/.ssh`) are not visible.

Docs used: code.claude.com/docs/en/ —
[settings](https://code.claude.com/docs/en/settings),
[permissions](https://code.claude.com/docs/en/permissions),
[managed-settings](https://code.claude.com/docs/en/managed-settings),
[cli-reference](https://code.claude.com/docs/en/cli-reference),
[headless](https://code.claude.com/docs/en/headless),
[sandboxing](https://code.claude.com/docs/en/sandboxing).

## Layout

```
flake.nix                  profile registry, packages/apps per profile, checks
nix/validate.nix           schema + validation (throws on anything unenforceable)
nix/mkAgent.nix            builds the bundle: policy.json, managed-settings.json, behaviour.md, skills, env
agentctl/agentctl.py       inspect / launch / probe / logs; bwrap sandbox + audit log
profiles/*.nix             reviewer, developer
skills/<name>/SKILL.md     skill registry
standards/<name>.md        behaviour standards (guidance)
tests/invalid-profiles.nix nix flake check: bad profiles must be rejected
tests/test_enforcement.sh  no-cost validation + probe tests
demo.sh                    live demo (needs CLAUDE_CODE_OAUTH_TOKEN)
demo-repo/                 toy Python repo used by demo and tests
```

Audit logs: `${XDG_STATE_HOME:-~/.local/state}/agent-profiles/logs/<run>-<profile>.jsonl`.
