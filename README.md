# nix-claude-profiles

Company-managed, flake-native agent profiles for Claude Code (hackday MVP).

One name (`reviewer`, `developer`, ...) = **tools + permissions + skills + behaviour + tool
environment**, built into a read-only `/nix/store` bundle. A profile is versioned by its
declared `version`, the flake rev, and the bundle's store hash, so `reviewer@1.0.0` at a given
rev is the same thing on every machine. `agentctl` launches Claude Code (`--restricted`) inside
a bubblewrap sandbox derived from the profile and writes an audit log.

## Try it (nothing to clone)

```sh
G=github:CameronBadman/nix-profile-builder-
nix run $G#agentctl -- list                                  # the profile registry
nix run $G#agentctl -- inspect reviewer                      # effective setup + who enforces what
nix run $G#agentctl -- diff $G/v1.0.0#reviewer $G/v1.1.0#reviewer --text   # agent upgrade = git tag

# launching needs a token: `claude setup-token`, then save it (chmod 600) to
# ~/.config/agent-profiles/oauth-token  (or export CLAUDE_CODE_OAUTH_TOKEN)
nix run $G#reviewer  -- --repo . "Review calc.py"
nix run $G#reviewer  -- --redteam --repo . "echo hacked >> calc.py"   # guidance off, sandbox on
nix run $G/v1.0.0#reviewer -- --repo . "Review calc.py"               # pinned older version
nix run $G#agentctl -- logs --last
```

Claude Code itself (`claude-code` from nixpkgs, 2.1.293) is pinned in `flake.lock`, along with
every tool in each profile's environment. The launcher needs Claude Code >= 2.1.259
(`--restricted` arrived in 2.1.248, `--permission-prompts` in 2.1.259): the pinned version is
checked at build time and the actual binary at launch, and an older one is refused with a clear
error. Set `harness = "host"` in a profile to use the host
binary instead (unpinned; version still logged).

## Demo

`./demo.sh prep` before going on stage (prefetches everything, checks token + bubblewrap),
then `./demo.sh` — eight acts, Enter between each. Presenter notes: [DEMO.md](DEMO.md).
Offline fallback: `less -R demo/recorded-run.txt`. `tests/test_enforcement.sh` runs the no-cost
checks (validation + probes). Haiku runs cost ~$0.003–0.007 each.

## Profile schema

Each `profiles/<name>.nix` becomes `.#<name>`. Validation (`nix/validate.nix`) rejects
anything it cannot enforce instead of ignoring it.

```nix
{
  name = "reviewer";
  version = "1.0.0";
  description = "Read-only code reviewer applying ACME review standards";
  packages = [ "ripgrep" "git" ];               # nixpkgs attrs, plus the base env (below)
  filesystem.workspace = "read-only";           # or "read-write"; extraReadOnly = [ "/abs/path" ];
  network.tools = "deny";                       # or "open"; "allowlist" is rejected
  tools = [ "Read" "Grep" "Glob" "Bash" "Skill" "Agent" ];  # Read Grep Glob Edit Write Bash TodoWrite Skill Agent
  skills = [ "acme-code-review" ];              # skills/<name>/SKILL.md
  behaviour = {
    standards = [ "review" ];                   # standards/<name>.md, appended to system prompt
    reviewRequired = false;
    notes = "You are a reviewer. Never modify repository files; report findings only.";
  };
  subagents.security-auditor = {
    description = "Focused security pass over the files under review";
    prompt = "You audit code for security issues. ...";
    tools = [ "Read" "Grep" "Glob" ];           # must be a subset of the profile's tools (minus Agent)
  };
}
```

Rejected at eval time (see `tests/invalid-profiles.nix`): unknown tools, unknown fields,
`network.tools = "allowlist"`, WebFetch/WebSearch, write tools on a read-only workspace,
extra writable paths, missing skills/standards, subagent tools outside the profile's set.

**Tool environment.** `PATH` is the profile's packages plus a base of bash, coreutils, gnused,
gnugrep, findutils (and bubblewrap/socat/ripgrep when Bash is sandboxed). `PYTHONDONTWRITEBYTECODE=1`.
The reviewer has no python3; the developer has python3 + ruff.

**Skills** ship as a per-profile Claude Code plugin in the bundle (`$bundle/plugin`,
`.claude-plugin/plugin.json` name `profile-<name>`) loaded with `--plugin-dir`, so they appear
as e.g. `profile-reviewer:acme-code-review`. A plugin is used because `--restricted` ignores
skills from `$CLAUDE_CONFIG_DIR/skills` and from `--add-dir` directories (verified);
`--plugin-dir` skills still load.

**Working directory.** Read-write profiles start in the repo. Read-only profiles start in a
scratch dir (`/home/agent/scratch`) and get the repo via `--add-dir`, because Claude Code's
inner Bash sandbox creates `<cwd>/.claude` at startup, which fails on a read-only mount.

## Red-team mode

`agentctl launch --redteam` simulates a non-compliant agent: it drops `behaviour.md` and the
skills plugin and appends an "authorized enforcement test" prompt. Sandbox, managed settings
and tool set are unchanged; the audit log records `redteam: true`. Live results (reviewer):

| Attempt | Outcome |
|---|---|
| Bash `echo >> calc.py` | `Read-only file system` (kernel) |
| Bash `sed -i ... calc.py` | `couldn't open temporary file ... Read-only file system` (kernel) |
| Bash `echo > /etc/claude-code/managed-settings.json` | `Read-only file system` (kernel) |
| Read tool on managed-settings.json | harness denial: `--restricted` confines file tools to the working directory |

In normal mode the reviewer declined to write at all, citing the review standards; that is
behaviour guidance, not enforcement. Developer (normal mode): Edit/Write succeeded, tests and
ruff ran; Bash network was blocked by Claude Code's own sandbox nested inside our bwrap
(`deny network-outbound example.com:443`).

## What enforces what

From `enforcement` in `nix/mkAgent.nix` (also printed by `agentctl inspect`):

| Control | Enforced by | Scope |
|---|---|---|
| workspace read-only / read-write | **kernel** (bwrap mount) | all tools incl. Bash and subagents |
| policy, settings, skills immutable | **kernel** (read-only /nix/store + ro binds) | all tools |
| host home, other dirs hidden | **kernel** (bwrap minimal root) | all tools |
| tool set | **harness** (`--tools`, managed permissions, `dontAsk`) | outside the model, inside the claude process |
| `network.tools = deny` | **harness** denies WebFetch/WebSearch; Bash in Claude sandbox with no domains (`failIfUnavailable`: launch fails rather than run unsandboxed) | agent tools |
| `network.tools = open` | NOT RESTRICTED (declared open) | agent tools |
| model API egress | always allowed | required to run |
| skills + behaviour standards | **GUIDANCE ONLY** (system prompt / skills plugin) | compliance not guaranteed |
| harness binary version | **NOT PINNED** (host `claude`) | recorded per run |
| anything else (allowlists, extra writable paths, ...) | **unsupported -> eval error** | - |

## Security boundary & limitations

- **Linux + bubblewrap only.** No macOS/Windows support.
- **Host `claude` binary is not pinned.** It is bind-mounted read-only from the host; its
  version is logged in every run's `run_start` record.
- **Model API egress is always allowed**; the sandbox shares the host network namespace so the
  harness can reach the API. `network.tools` only governs the agent's tools.
- **The agent can read its own OAuth token** (it is in its environment). Bash has no network,
  but the model could echo it into the conversation. Use a revocable token.
- **Built-in skills remain.** Claude Code's ~19 bundled skills (e.g. its own `code-review`)
  stay available alongside the profile's; there is no documented way to remove only those
  without also disabling plugin skills.
- **Network allowlists are unsupported** (would need an egress proxy) and are rejected at eval.
- **Harness-level tool restrictions run inside the claude process.** They are outside the
  model's control, but not a kernel boundary; the kernel rows above are.
- **`/usr` is visible read-only**, so host binaries exist at absolute paths (e.g.
  `/usr/bin/python3`) even though only the profile's packages are on `PATH`. Bash can run
  them; they are still subject to the same mounts and network sandbox.
- **Subagents run in-process** inside the same sandbox: kernel limits apply to them, and
  their tool lists must be a subset of the profile's (checked at eval).
- **Audit log is heuristic.** It is written by the launcher, outside the sandbox, from the
  `stream-json` output. "Blocked" vs "error" is classified by matching error text; successful
  tool results containing `deny network-outbound` or `Read-only file system` also count as blocked.
- **Built-in subagents** (`general-purpose`, `Explore`, ...) also appear when `Agent` is
  enabled. They run in the same process and sandbox, so kernel limits apply; we have not
  verified their harness-level tool lists beyond the session's.
- **Writable workspaces get Claude sandbox artefacts**: Claude Code's inner Bash sandbox leaves
  a `.claude/` dir (and transient mount-point files) in the workspace.
- `$HOME` inside the sandbox is an empty tmpfs; the `probe` checks that real host files
  (`~/.claude.json`, `~/.ssh`) are not visible.

Docs used: code.claude.com/docs/en/ -
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
nix/mkAgent.nix            builds the bundle: policy.json, managed-settings.json, behaviour.md, plugin/, env
agentctl/agentctl.py       inspect / launch [--redteam] / probe / logs; bwrap sandbox + audit log
profiles/*.nix             reviewer, developer
skills/<name>/SKILL.md     skill registry (acme-code-review, acme-implement-feature)
standards/<name>.md        behaviour standards (guidance)
tests/invalid-profiles.nix nix flake check: bad profiles must be rejected
tests/test_enforcement.sh  no-cost validation + probe tests
demo.sh                    live demo (needs an OAuth token)
demo-repo/                 toy Python repo used by demo and tests
```

Audit logs: `${XDG_STATE_HOME:-~/.local/state}/agent-profiles/logs/<run>-<profile>.jsonl`.
# nix-profile-builder-
