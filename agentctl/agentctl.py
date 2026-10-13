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
DEFAULT_FLAKE = os.environ.get("AGENT_PROFILES_FLAKE", ".")
SANDBOX_HOME = "/home/agent"
CONFIG_DIR = f"{SANDBOX_HOME}/.claude-profile"
CLAUDE_IN_SANDBOX = "/opt/claude/bin/claude"
MANAGED = "/etc/claude-code/managed-settings.json"
BLOCK_MARKERS = ("read-only file system", "permission denied", "not permitted",
                 "denied", "eacces", "erofs", "not allowed", "outside the allowed")


def die(msg):
    print(f"agentctl: error: {msg}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- resolve

def resolve_bundle(args):
    if args.bundle:
        return Path(args.bundle)
    ref = f"{args.flake}#{args.profile}"
    r = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", ref],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"could not build profile {ref}:\n{r.stderr.strip()}")
    return Path(r.stdout.strip().splitlines()[-1])


def load_policy(bundle):
    policy = json.loads((bundle / "policy.json").read_text())
    unenforceable = []
    if policy["network"]["tools"] not in ("deny", "open"):
        unenforceable.append(f"network.tools={policy['network']['tools']}")
    if unenforceable:
        die("refusing to launch, unenforceable policy: " + ", ".join(unenforceable))
    return policy


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
            "--tmpfs", "/home", "--dir", SANDBOX_HOME]
    if Path("/var/lib/ca-certificates").exists():
        argv += ["--ro-bind", "/var/lib/ca-certificates", "/var/lib/ca-certificates"]
    if claude_real:
        argv += ["--ro-bind", claude_real, CLAUDE_IN_SANDBOX]
    argv += ["--bind", str(config_dir), CONFIG_DIR,
             "--ro-bind", str(bundle / "skills"), f"{CONFIG_DIR}/skills"]
    for extra in policy["filesystem"]["extraReadOnly"]:
        argv += ["--ro-bind", extra, extra]
    argv += [ws_bind, str(repo), str(repo), "--chdir", str(repo)]
    for k, v in env.items():
        argv += ["--setenv", k, v]
    return argv


def new_config_dir(run_id):
    d = STATE / "runs" / run_id / "config"
    d.mkdir(parents=True)
    (d / "skills").mkdir()  # mount point for read-only skills
    # skip first-run onboarding inside the throwaway config dir
    (d / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    return d


# ---------------------------------------------------------------- launch

class Audit:
    def __init__(self, policy, run_id):
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

    def say(self, msg):
        print(msg, flush=True)

    def handle(self, m):
        t = m.get("type")
        if t == "system" and m.get("subtype") == "init":
            rec = {k: m.get(k) for k in ("tools", "skills", "slash_commands", "agents", "model",
                                         "permissionMode", "cwd") if k in m}
            self.write("harness_init", **rec)
            self.say(f"[init] model={m.get('model')} permissionMode={m.get('permissionMode')}")
            self.say(f"[init] tools={m.get('tools')}")
            if "skills" in m:
                self.say(f"[init] skills={m.get('skills')}")
            if "agents" in m:
                self.say(f"[init] agents={m.get('agents')}")
        elif t == "system" and m.get("subtype") == "permission_denied":
            self.counts["blocked"] += 1
            self.write("blocked", layer="harness", detail=m)
            self.say(f"[BLOCKED by harness] {json.dumps(m)[:200]}")
        elif t == "assistant":
            for b in m.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    self.pending[b["id"]] = b
                    self.write("tool_request", tool=b["name"], input=b.get("input"),
                               subagent=m.get("parent_tool_use_id"))
                    self.say(f"[tool] {b['name']} {json.dumps(b.get('input'))[:160]}")
                elif b.get("type") == "text" and b.get("text", "").strip():
                    self.say(f"[agent] {b['text'].strip()}")
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
                if b.get("is_error"):
                    kind = "blocked" if any(k in text.lower() for k in BLOCK_MARKERS) else "error"
                else:
                    kind = "blocked" if "read-only file system" in text.lower() else "allowed"
                self.counts[kind] += 1
                self.write(kind, tool=req.get("name"), input=req.get("input"), result=text[:500])
                label = {"allowed": "ALLOWED", "blocked": "BLOCKED", "error": "error"}[kind]
                self.say(f"[{label}] {req.get('name')}: {text.strip()[:200]}")
        elif t == "result":
            self.write("result", permission_denials=m.get("permission_denials"),
                       cost_usd=m.get("total_cost_usd"), is_error=m.get("is_error"),
                       num_turns=m.get("num_turns"), result=m.get("result"))
            for d in m.get("permission_denials") or []:
                self.say(f"[denial] {json.dumps(d)[:200]}")
            self.say(f"[result] cost=${m.get('total_cost_usd')} turns={m.get('num_turns')}")


def cmd_launch(args):
    bundle = resolve_bundle(args)
    policy = load_policy(bundle)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        die(f"workspace {repo} is not a directory")
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        die("CLAUDE_CODE_OAUTH_TOKEN is not set (run `claude setup-token` once and export it); "
            "the host ~/.claude login is deliberately not exposed to the sandbox")
    claude_real, claude_ver = host_claude()
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    config_dir = new_config_dir(run_id)
    audit = Audit(policy, run_id)

    claude = [CLAUDE_IN_SANDBOX, "--restricted", "-p", "--output-format", "stream-json", "--verbose",
              "--tools", ",".join(policy["tools"]),
              "--permission-mode", "dontAsk", "--permission-prompts", "none",
              "--append-system-prompt-file", str(bundle / "behaviour.md"),
              "--no-session-persistence",
              "--model", args.model, "--max-budget-usd", str(args.budget)]
    if policy["subagents"]:
        claude += ["--agents", json.dumps(policy["subagents"])]
    claude += ["--", args.prompt]
    argv = bwrap_argv(policy, bundle, repo, config_dir, claude_real, token)

    start = audit.write("run_start", profile=policy["profileId"], rev=policy["rev"],
                        bundle=str(bundle), harness=claude_ver, workspace=str(repo),
                        workspace_mode=policy["filesystem"]["workspace"], model=args.model,
                        prompt=args.prompt)
    print(f"== {policy['profileId']}  rev {policy['rev'][:12]}  harness {claude_ver}")
    print(f"== workspace {repo} ({policy['filesystem']['workspace']})  log {audit.path}")
    proc = subprocess.Popen(argv + ["--"] + claude, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    print(f"== done: exit={rc} allowed={audit.counts['allowed']} blocked={audit.counts['blocked']} "
          f"errors={audit.counts['error']}  profile={start['profile']}")
    return rc


# ---------------------------------------------------------------- probe

def cmd_probe(args):
    """Deterministic, LLM-free check that the sandbox enforces the profile."""
    bundle = resolve_bundle(args)
    policy = load_policy(bundle)
    repo = Path(args.repo).resolve()
    rw = policy["filesystem"]["workspace"] == "read-write"
    claude_real = shutil.which("claude") and os.path.realpath(shutil.which("claude"))
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config"
        (cfg / "skills").mkdir(parents=True)
        base = bwrap_argv(policy, bundle, repo, cfg, claude_real, None)
        skill = f"{CONFIG_DIR}/skills/{policy['skills'][0]}/SKILL.md" if policy["skills"] else None
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
            print(f"  {'PASS' if good else 'FAIL'}  {name:<42} -> {'succeeded' if ok else 'denied'}"
                  f"{'  (' + detail[-1][-70:] + ')' if detail and not ok else ''}")
        print(f"{'OK' if not failures else 'FAILED'}: {len(checks) - failures}/{len(checks)} checks match policy")
        return 1 if failures else 0


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
    common(sp, needs_repo=True)
    sp.add_argument("--model", default="haiku")
    sp.add_argument("--budget", type=float, default=0.5, help="max USD for this run")
    sp.add_argument("prompt")
    sp.set_defaults(fn=cmd_launch)

    sp = sub.add_parser("probe", help="LLM-free enforcement checks in the profile sandbox")
    common(sp, needs_repo=True)
    sp.set_defaults(fn=cmd_probe)

    sp = sub.add_parser("logs", help="list audit logs or show the last one")
    sp.add_argument("--last", action="store_true")
    sp.set_defaults(fn=cmd_logs)

    args = ap.parse_args()
    if getattr(args, "profile", None) is None and not getattr(args, "bundle", None) and args.cmd != "logs":
        die("give a profile name or --bundle")
    sys.exit(args.fn(args) or 0)


if __name__ == "__main__":
    main()
