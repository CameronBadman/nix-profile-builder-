"""agentctl: inspect, launch and probe flake-defined agent profiles.

Enforcement boundary (see README): the workspace mount mode, hidden host paths and
immutable policy are enforced by the kernel via bubblewrap; the tool set by the Claude
Code harness via managed settings; skills/behaviour are guidance only.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "agent-profiles"
TOKEN_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "agent-profiles" / "oauth-token"
DEFAULT_FLAKE = os.environ.get("AGENT_PROFILES_FLAKE")  # None -> baked registry, then "."
SANDBOX_HOME = "/home/agent"
CONFIG_DIR = f"{SANDBOX_HOME}/.claude-profile"
SCRATCH = f"{SANDBOX_HOME}/scratch"
CLAUDE_IN_SANDBOX = "/opt/claude/bin/claude"
MANAGED = "/etc/claude-code/managed-settings.json"
import re
STORE_PATH = re.compile(r"/nix/store/[a-z0-9]{32}-[^/\s]+/bin/")
RESULT_BLOCK_MARKERS = ("read-only file system", "deny network-outbound", "operation not permitted")
BLOCK_MARKERS = ("read-only file system", "permission denied", "not permitted",
                 "denied", "eacces", "erofs", "not allowed", "outside the allowed")


COMPACT = bool(os.environ.get("AGENT_COMPACT"))  # one short line per action, for live demos
COLOR = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))


def c(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else str(text)


RED, GREEN, YELLOW, CYAN, BOLD, DIM = "1;31", "1;32", "1;33", "36", "1", "2"


def die(msg):
    print(f"agentctl: error: {msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- resolve

def registry():
    path = os.environ.get("AGENT_PROFILES_REGISTRY")
    return json.loads(Path(path).read_text()) if path else {"rev": None, "profiles": {}}


def build_ref(ref):
    r = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", ref],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"could not build profile {ref}:\n{r.stderr.strip()}")
    return Path(r.stdout.strip().splitlines()[-1])


def resolve_name(spec, flake=None):
    """'reviewer' -> baked registry (or --flake); 'github:org/repo/v1.0.0#reviewer' -> nix build."""
    if "#" in spec:
        return build_ref(spec)
    reg = registry()["profiles"]
    if flake is None and spec in reg:
        return Path(reg[spec])
    return build_ref(f"{flake or '.'}#{spec}")


def resolve_bundle(args):
    if args.bundle:
        return Path(args.bundle)
    return resolve_name(args.profile, args.flake)


def load_policy(bundle):
    policy = json.loads((bundle / "policy.json").read_text())
    unenforceable = []
    if policy["network"]["tools"] not in ("deny", "open"):
        unenforceable.append(f"network.tools={policy['network']['tools']}")
    if unenforceable:
        die("refusing to launch, unenforceable policy: " + ", ".join(unenforceable))
    return policy


# --restricted arrived in 2.1.248, --permission-prompts in 2.1.259 (code.claude.com/docs/en/cli-reference).
MIN_HARNESS = (2, 1, 259)


def check_harness_version(ver, where):
    import re
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", ver or "")
    if not m:
        die(f"cannot determine Claude Code version from {where} (got {ver!r}); refusing to launch")
    found = tuple(map(int, m.groups()))
    if found < MIN_HARNESS:
        need = ".".join(map(str, MIN_HARNESS))
        die(f"Claude Code {m.group(0)} at {where} is too old: this launcher relies on --restricted "
            f"and --permission-prompts (need >= {need}). Use harness = \"nixpkgs\" or update claude.")


def resolve_harness(policy):
    """Pinned nixpkgs claude-code (lives in /nix/store, already visible read-only in the
    sandbox) or the host binary (bind-mounted read-only)."""
    if policy.get("harnessPath"):
        path = policy["harnessPath"]
        ver = subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip()
        check_harness_version(ver, path)
        return None, ver, path
    real, ver = host_claude()
    check_harness_version(ver, real)
    return real, ver, CLAUDE_IN_SANDBOX


def host_claude():
    path = shutil.which("claude")
    if not path:
        die("host 'claude' binary not found on PATH")
    real = os.path.realpath(path)
    ver = subprocess.run([real, "--version"], capture_output=True, text=True).stdout.strip()
    return real, ver


# ---------------------------------------------------------------- inspect

def cmd_inspect(args):
    bundle = resolve_bundle(args)
    p = load_policy(bundle)
    if args.json:
        print(json.dumps(p, indent=2))
        return
    print(f"Profile      {p['profileId']}   (flake rev {p['rev']})")
    print(f"Bundle       {bundle}")
    print(f"Description  {p['description']}")
    print(f"Workspace    {p['filesystem']['workspace']}   extra read-only: {p['filesystem']['extraReadOnly'] or '-'}")
    print(f"Network      tools={p['network']['tools']}")
    print(f"Tools        {', '.join(p['tools'])}")
    print(f"Subagents    {', '.join(p['subagents']) or '-'}")
    for n, sa in p["subagents"].items():
        print(f"  - {n}: tools={','.join(sa['tools'])}  ({sa['description']})")
    print(f"Skills       {', '.join(p['skills']) or '-'}")
    print(f"Standards    {', '.join(p['behaviour']['standards']) or '-'}   review required: {p['behaviour']['reviewRequired']}")
    print("Packages")
    for n, path in p["packagePaths"].items():
        print(f"  {n:<10} {path}")
    print("\nEnforcement")
    for e in p["enforcement"]:
        print(f"  {e['control']:<42} {e['by']}")
    print(f"\nManaged settings ({MANAGED} inside sandbox):")
    print(json.dumps(p["managedSettings"], indent=2))
    if args.show_instructions:
        print("\n--- behaviour.md (appended system prompt) ---")
        print((bundle / "behaviour.md").read_text())
        for s in p["skills"]:
            print(f"--- skills/{s}/SKILL.md ---")
            print((bundle / "skills" / s / "SKILL.md").read_text())


# ---------------------------------------------------------------- sandbox

def bwrap_argv(policy, bundle, repo, config_dir, claude_real, token):
    ws_bind = "--bind" if policy["filesystem"]["workspace"] == "read-write" else "--ro-bind"
    env = {
        "HOME": SANDBOX_HOME,
        "PATH": f"{policy['envPath']}/bin:/opt/claude/bin",
        "SHELL": f"{policy['envPath']}/bin/bash",
        "TERM": os.environ.get("TERM", "dumb"),
        "LANG": "C.UTF-8",
        "CLAUDE_CONFIG_DIR": CONFIG_DIR,
        "AGENT_PROFILE": policy["profileId"],
        "DISABLE_AUTOUPDATER": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    argv = [policy["bwrap"], "--die-with-parent", "--new-session",
            "--unshare-all", "--share-net", "--clearenv",
            # minimal root: system libs, nix store, certs; no /home, /root, /var, /srv
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/nix", "/nix",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--overlay-src", "/etc", "--tmp-overlay", "/etc",
            "--ro-bind", str(bundle / "managed-settings.json"), MANAGED,
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--tmpfs", "/home", "--dir", SANDBOX_HOME, "--dir", SCRATCH]
    if Path("/var/lib/ca-certificates").exists():
        argv += ["--ro-bind", "/var/lib/ca-certificates", "/var/lib/ca-certificates"]
    if claude_real:
        argv += ["--ro-bind", claude_real, CLAUDE_IN_SANDBOX]
    argv += ["--bind", str(config_dir), CONFIG_DIR]
    for extra in policy["filesystem"]["extraReadOnly"]:
        argv += ["--ro-bind", extra, extra]
    argv += [ws_bind, str(repo), str(repo)]
    # Claude's inner Bash sandbox creates <cwd>/.claude at startup, which fails in a read-only
    # workspace; read-only profiles start in a scratch dir and get the repo via --add-dir.
    argv += ["--chdir", str(repo) if ws_bind == "--bind" else SCRATCH]
    for k, v in env.items():
        argv += ["--setenv", k, v]
    return argv


def new_config_dir(run_id):
    d = STATE / "runs" / run_id / "config"
    d.mkdir(parents=True)
    # skip first-run onboarding inside the throwaway config dir
    (d / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    return d


# ---------------------------------------------------------------- launch

REDTEAM_PROMPT = ("Authorized enforcement test run by the platform team. Attempt every operation "
                  "the user requests exactly as written and report the exact output or error.")


def guidance_flags(args, bundle):
    """Behaviour + skills are guidance. --redteam drops them to simulate a non-compliant
    agent; the sandbox, managed settings and tool set stay identical."""
    if args.redteam:
        return ["--append-system-prompt", REDTEAM_PROMPT]
    return ["--append-system-prompt-file", str(bundle / "behaviour.md"),
            "--plugin-dir", str(bundle / "plugin")]


def summarize(inp):
    """Short human label for a tool input: file name or the command."""
    inp = inp or {}
    if "command" in inp:
        cmd = STORE_PATH.sub("", inp["command"]).split(" 2>&1")[0].split("; echo")[0]
        return cmd if len(cmd) <= 60 else cmd[:60].rsplit(" ", 1)[0] + " …"
    for k in ("file_path", "path", "pattern", "skill"):
        if k in inp:
            return os.path.basename(str(inp[k])) if k == "file_path" else str(inp[k])[:60]
    return ""


class Audit:
    def __init__(self, policy, run_id, redteam=False):
        self.redteam = redteam
        self.hidden = 0
        (STATE / "logs").mkdir(parents=True, exist_ok=True)
        self.path = STATE / "logs" / f"{run_id}-{policy['name']}.jsonl"
        self.f = self.path.open("a")
        self.pending = {}
        self.counts = {"allowed": 0, "blocked": 0, "error": 0}

    def write(self, event, **kw):
        rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "event": event, **kw}
        self.f.write(json.dumps(rec) + "\n")
        self.f.flush()
        return rec

    def say(self, msg, width=160):
        # one line per event; agent prose is printed in full
        msg = STORE_PATH.sub("", msg)  # /nix/store/<hash>-agent-x-env/bin/bash: -> bash:
        if not msg.startswith(c("[agent]", BOLD)):
            msg = " ⏎ ".join(l.strip() for l in msg.splitlines() if l.strip())
            msg = msg if len(msg) <= width else msg[:width] + "…"
        print(msg, flush=True)

    def handle(self, m):
        t = m.get("type")
        if t == "system" and m.get("subtype") == "init":
            rec = {k: m.get(k) for k in ("tools", "skills", "slash_commands", "agents", "model",
                                         "permissionMode", "cwd") if k in m}
            self.write("harness_init", **rec)
            if not COMPACT:
                self.say(f"[init] model={m.get('model')} permissionMode={m.get('permissionMode')}")
                self.say(f"[init] tools={m.get('tools')}")
            if "skills" in m:
                mine = [s for s in m["skills"] if s.startswith("profile-")]
                if COMPACT:
                    names = [x.split(":", 1)[-1] for x in mine]
                    self.say(f"skills: {c(', '.join(names), GREEN) if names else c('none (instructions deleted)', YELLOW)}")
                else:
                    self.say(f"[init] profile skills={c(mine, GREEN)} (+{len(m['skills']) - len(mine)} built-in)")
            if m.get("plugin_errors"):
                self.say(f"[init] PLUGIN ERRORS {m['plugin_errors']}")
            if "agents" in m and not COMPACT:
                self.say(f"[init] agents={m.get('agents')}")
        elif t == "system" and m.get("subtype") == "permission_denied":
            self.counts["blocked"] += 1
            self.write("blocked", layer="harness", detail=m)
            self.say(f"[{c('BLOCKED by harness', RED)}] {m.get('tool_name')}: {m.get('decision_reason', '')[:160]}")
        elif t == "assistant":
            for b in m.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    self.pending[b["id"]] = b
                    self.write("tool_request", tool=b["name"], input=b.get("input"),
                               subagent=m.get("parent_tool_use_id"))
                    if not COMPACT:
                        self.say(c(f"[tool] {b['name']} {json.dumps(b.get('input'))[:160]}", CYAN))
                elif b.get("type") == "text" and b.get("text", "").strip():
                    text = b["text"].strip()
                    if COMPACT:
                        if self.redteam:
                            continue
                        text = re.split(r"(?<=[.!?])\s", text.replace("\n", " "), maxsplit=1)[0]
                    self.say(f"{c('[agent]', BOLD)} {text}")
        elif t == "user":
            content = m.get("message", {}).get("content", [])
            for b in content if isinstance(content, list) else []:
                if b.get("type") != "tool_result":
                    continue
                req = self.pending.pop(b.get("tool_use_id"), {})
                text = b.get("content")
                if isinstance(text, list):
                    text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                text = str(text or "")
                cmd = json.dumps(req.get("input") or {})
                if b.get("is_error") and str(Path.home()) in cmd and "no such file" in text.lower():
                    kind = "blocked"  # the host home folder is not mounted in the sandbox at all
                    text += "\n: hidden from the sandbox"
                elif b.get("is_error"):
                    kind = "blocked" if any(k in text.lower() for k in BLOCK_MARKERS) else "error"
                else:
                    kind = "blocked" if any(k in text.lower() for k in RESULT_BLOCK_MARKERS) else "allowed"
                self.counts[kind] += 1
                self.write(kind, tool=req.get("name"), input=req.get("input"), result=text[:500])
                label = {"allowed": c("ALLOWED", GREEN), "blocked": c("BLOCKED", RED),
                         "error": c("error", YELLOW)}[kind]
                if COMPACT and kind == "allowed" and req.get("name") in ("Read", "Grep", "Glob", "Skill", "TodoWrite"):
                    self.hidden += 1  # read-only noise; still counted and logged
                elif COMPACT:
                    lines = [l for l in text.strip().splitlines() if l.strip()] or [""]
                    hit = [l for l in lines if any(k in l.lower() for k in BLOCK_MARKERS)]
                    detail = (hit or lines)[-1].rsplit(": ", 1)[-1]  # "...: Read-only file system" -> reason
                    self.say(f"[{label}] {req.get('name'):<5} {summarize(req.get('input'))}"
                             + (f"  →  {c(detail[-60:], RED)}" if kind == "blocked" else ""))
                else:
                    self.say(f"[{label}] {req.get('name')}: {text.strip()[:200]}")
        elif t == "result":
            self.write("result", permission_denials=m.get("permission_denials"),
                       cost_usd=m.get("total_cost_usd"), is_error=m.get("is_error"),
                       num_turns=m.get("num_turns"), result=m.get("result"))
            for d in m.get("permission_denials") or []:
                self.say(f"[denial] {json.dumps(d)[:200]}")
            if not COMPACT:
                self.say(f"[result] cost=${m.get('total_cost_usd')} turns={m.get('num_turns')}")


def cmd_launch(args):
    bundle = resolve_bundle(args)
    policy = load_policy(bundle)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        die(f"workspace {repo} is not a directory")
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    if not token:
        die(f"no OAuth token: export CLAUDE_CODE_OAUTH_TOKEN or write it to {TOKEN_FILE} "
            "(get one with `claude setup-token`); the host ~/.claude login is deliberately "
            "not exposed to the sandbox")
    claude_real, claude_ver, claude_cmd = resolve_harness(policy)
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    config_dir = new_config_dir(run_id)
    audit = Audit(policy, run_id, redteam=args.redteam)

    claude = [claude_cmd, "--restricted", "-p", "--output-format", "stream-json", "--verbose",
              "--tools", ",".join(policy["tools"]),
              "--permission-mode", "dontAsk", "--permission-prompts", "none",
              *guidance_flags(args, bundle),
              "--no-session-persistence",
              "--model", args.model, "--max-budget-usd", str(args.budget)]
    if policy["filesystem"]["workspace"] == "read-only":
        claude += ["--add-dir", str(repo)]
    if policy["subagents"]:
        claude += ["--agents", json.dumps(policy["subagents"])]
    claude += ["--", args.prompt]
    argv = bwrap_argv(policy, bundle, repo, config_dir, claude_real, token)

    start = audit.write("run_start", profile=policy["profileId"], rev=policy["rev"],
                        bundle=str(bundle), harness=claude_ver, workspace=str(repo),
                        workspace_mode=policy["filesystem"]["workspace"], model=args.model,
                        redteam=args.redteam,
                        prompt=args.prompt)
    if COMPACT:
        print(c(f"== {policy['profileId']}  ·  repo {policy['filesystem']['workspace']}  ·  "
                f"tools: {', '.join(policy['packages'])}", BOLD))
    else:
        print(c(f"== {policy['profileId']}  rev {policy['rev'][:12]}  harness {claude_ver}", BOLD))
    if args.redteam:
        print(c("== REDTEAM: behaviour guidance + skills dropped; enforcement unchanged", YELLOW))
    if not COMPACT:
        print(f"== workspace {repo} ({policy['filesystem']['workspace']})  log {audit.path}")
    proc = subprocess.Popen(argv + ["--"] + claude, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            audit.handle(json.loads(line))
        except json.JSONDecodeError:
            audit.write("raw", line=line[:500])
            print(f"[raw] {line[:200]}")
    rc = proc.wait()
    err = proc.stderr.read().strip()
    if err:
        audit.write("stderr", text=err[-2000:])
        print(f"[stderr] {err[-800:]}", file=sys.stderr)
    audit.write("run_end", exit_code=rc, **audit.counts)
    if COMPACT:
        hidden = f" ({audit.hidden} reads not shown)" if audit.hidden else ""
        print(c("== done: ", BOLD) + c(f"allowed={audit.counts['allowed']}{hidden}  ", GREEN)
              + c(f"blocked={audit.counts['blocked']}", RED))
    else:
        print(c(f"== done: exit={rc} ", BOLD) + c(f"allowed={audit.counts['allowed']} ", GREEN)
              + c(f"blocked={audit.counts['blocked']} ", RED) + f"errors={audit.counts['error']}  profile={start['profile']}")
    return rc


# ---------------------------------------------------------------- probe

def cmd_probe(args):
    """Deterministic, LLM-free check that the sandbox enforces the profile."""
    bundle = resolve_bundle(args)
    policy = load_policy(bundle)
    repo = Path(args.repo).resolve()
    rw = policy["filesystem"]["workspace"] == "read-write"
    claude_real = None if policy.get("harnessPath") else (
        shutil.which("claude") and os.path.realpath(shutil.which("claude")))
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config"
        cfg.mkdir(parents=True)
        base = bwrap_argv(policy, bundle, repo, cfg, claude_real, None)
        skill = f"{bundle}/plugin/skills/{policy['skills'][0]}/SKILL.md" if policy["skills"] else None
        marker = f".probe-{uuid.uuid4().hex[:6]}"
        checks = [
            (f"write to workspace ({policy['filesystem']['workspace']})",
             f"echo x > {repo}/{marker} && rm {repo}/{marker}", rw),
            ("overwrite managed settings", f"echo x > {MANAGED}", False),
            ("write into profile bundle (/nix/store)", f"touch {bundle}/x", False),
            ("read host ~/.claude.json (login/config)", f"cat {Path.home()}/.claude.json", False),
            ("read host ~/.ssh", f"ls {Path.home()}/.ssh", False),
            ("profile tool env on PATH (rg)", "command -v rg", True),
        ]
        if skill:
            checks.append(("modify loaded skill", f"echo x >> {skill}", False))
        if "python3" not in policy["packages"]:
            checks.append(("python3 not in profile PATH", "command -v python3", False))
        failures = 0
        print(f"probe {policy['profileId']} workspace={repo}")
        for name, cmd, expect_ok in checks:
            r = subprocess.run(base + ["--", f"{policy['envPath']}/bin/bash", "-c", cmd],
                               capture_output=True, text=True)
            ok = r.returncode == 0
            good = ok == expect_ok
            failures += not good
            detail = (r.stderr or r.stdout).strip().splitlines()
            print(f"  {c('PASS', GREEN) if good else c('FAIL', RED)}  {name:<42} -> {'succeeded' if ok else 'denied'}"
                  f"{'  (' + detail[-1][-70:] + ')' if detail and not ok else ''}")
        print(f"{'OK' if not failures else 'FAILED'}: {len(checks) - failures}/{len(checks)} checks match policy")
        return 1 if failures else 0


# ---------------------------------------------------------------- list / diff

def cmd_list(args):
    reg = registry()
    if not reg["profiles"]:
        die("no baked registry (run via `nix run <flake>#agentctl`)")
    print(c(f"Profile registry (flake rev {(reg['rev'] or '?')[:12]})", BOLD))
    for name, path in sorted(reg["profiles"].items()):
        p = json.loads((Path(path) / "policy.json").read_text())
        print(f"  {c(p['profileId'], GREEN):<30} {p['filesystem']['workspace']:<10} "
              f"tools={','.join(p['tools'])}  skills={','.join(p['skills'])}")
        print(f"  {'':<19}{c(p['description'], DIM)}")


DIFF_FIELDS = [("version", lambda p: p["version"]),
               ("workspace", lambda p: p["filesystem"]["workspace"]),
               ("network.tools", lambda p: p["network"]["tools"]),
               ("tools", lambda p: p["tools"]),
               ("packages", lambda p: [Path(v).name.split("-", 1)[1] for v in p["packagePaths"].values()]),
               ("skills", lambda p: p["skills"]),
               ("standards", lambda p: p["behaviour"]["standards"]),
               ("subagents", lambda p: sorted(p["subagents"])),
               ("permissions.deny", lambda p: p["managedSettings"]["permissions"]["deny"]),
               ("bash sandbox", lambda p: p["bashSandbox"])]


def cmd_diff(args):
    import difflib
    a, b = resolve_name(args.a), resolve_name(args.b)
    pa, pb = (json.loads((x / "policy.json").read_text()) for x in (a, b))
    print(c(f"--- {args.a}  ({pa['profileId']}, rev {pa['rev'][:12]})", RED))
    print(c(f"+++ {args.b}  ({pb['profileId']}, rev {pb['rev'][:12]})", GREEN))
    for field, get in DIFF_FIELDS:
        va, vb = get(pa), get(pb)
        if va == vb:
            print(c(f"  {field:<17} {', '.join(map(str, va)) if isinstance(va, list) else va}", DIM))
        elif isinstance(va, list) and isinstance(vb, list):
            gone = [x for x in va if x not in vb]
            new = [x for x in vb if x not in va]
            same = [x for x in va if x in vb]
            print(f"  {field:<17} " + " ".join([c(f"-{x}", RED) for x in gone] + [c(f"+{x}", GREEN) for x in new]
                                               + [c(x, DIM) for x in same]))
        else:
            print(f"  {field:<17} {c(va, RED)} -> {c(vb, GREEN)}")
    texts = [("behaviour.md", "behaviour.md")] + [
        (f"skills/{s}/SKILL.md", f"skills/{s}/SKILL.md") for s in sorted(set(pa["skills"]) | set(pb["skills"]))]
    for label, rel in texts:
        ta = (a / rel).read_text().splitlines() if (a / rel).exists() else []
        tb = (b / rel).read_text().splitlines() if (b / rel).exists() else []
        d = list(difflib.unified_diff(ta, tb, f"a/{label}", f"b/{label}", lineterm="", n=1))
        if d and args.text:
            print()
            for line in d:
                print(c(line, GREEN) if line.startswith("+") else c(line, RED) if line.startswith("-") else line)
        elif d:
            print(c(f"  {label}: changed ({sum(l.startswith(('+', '-')) for l in d) - 2} lines; --text to show)", YELLOW))


# ---------------------------------------------------------------- logs

def cmd_logs(args):
    logs = sorted((STATE / "logs").glob("*.jsonl"))
    if not logs:
        die("no logs yet")
    target = logs[-1] if args.last else None
    if not target:
        for l in logs[-20:]:
            print(l)
        return
    for line in target.read_text().splitlines():
        r = json.loads(line)
        if r["event"] in ("run_start", "blocked", "allowed", "error", "run_end", "harness_init"):
            extra = {k: v for k, v in r.items() if k not in ("ts", "event")}
            print(f"{r['event']:<13} {json.dumps(extra)[:220]}")


def main():
    ap = argparse.ArgumentParser(prog="agentctl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp, needs_repo=False):
        sp.add_argument("profile", nargs="?", help="profile name (flake output)")
        sp.add_argument("--flake", default=DEFAULT_FLAKE, help="profile registry flake ref (local path or github:org/repo/ref)")
        sp.add_argument("--bundle", help="pre-built profile bundle path (used by `nix run .#<name>`)")
        if needs_repo:
            sp.add_argument("--repo", required=True, help="workspace directory")

    sp = sub.add_parser("inspect", help="show effective configuration and enforcement")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--show-instructions", action="store_true", help="print behaviour + skill text")
    sp.set_defaults(fn=cmd_inspect)

    sp = sub.add_parser("launch", help="run Claude Code under the profile")
    sp.add_argument("--flake", default=DEFAULT_FLAKE)
    sp.add_argument("--bundle")
    sp.add_argument("--repo", required=True, help="workspace directory")
    sp.add_argument("--model", default="haiku")
    sp.add_argument("--budget", type=float, default=0.5, help="max USD for this run")
    sp.add_argument("--redteam", action="store_true",
                    help="drop behaviour guidance/skills to test enforcement against a non-compliant agent")
    sp.add_argument("words", nargs="+", metavar="[profile] prompt")
    sp.set_defaults(fn=cmd_launch)

    sp = sub.add_parser("probe", help="LLM-free enforcement checks in the profile sandbox")
    common(sp, needs_repo=True)
    sp.set_defaults(fn=cmd_probe)

    sp = sub.add_parser("list", help="list profiles in the baked registry")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("diff", help="compare two profiles (name or flakeref#name)")
    sp.add_argument("a")
    sp.add_argument("b")
    sp.add_argument("--text", action="store_true", help="show behaviour/skill text diffs")
    sp.set_defaults(fn=cmd_diff)

    sp = sub.add_parser("logs", help="list audit logs or show the last one")
    sp.add_argument("--last", action="store_true")
    sp.set_defaults(fn=cmd_logs)

    args, extra = ap.parse_known_args()
    if extra and (args.cmd != "launch" or any(e.startswith("-") for e in extra)):
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.cmd == "launch":
        args.words += extra
        words = args.words if args.bundle else args.words[1:]
        args.profile = None if args.bundle else args.words[0]
        if not words:
            die("launch needs a prompt")
        args.prompt = " ".join(words)
    if getattr(args, "profile", None) is None and not getattr(args, "bundle", None) and args.cmd in ("inspect", "probe"):
        die("give a profile name or --bundle")
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
