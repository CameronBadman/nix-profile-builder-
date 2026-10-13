# Build one named agent: a read-only /nix/store bundle holding the generated policy,
# harness settings, skills, behaviour instructions and the profile's tool environment.
{ pkgs, lib, profile, agentctl, skillsDir, standardsDir, rev }:

let
  p = profile;
  # --restricted (2.1.248) and --permission-prompts (2.1.259) are required by the launcher.
  minHarness = "2.1.259";
  pinnedOk = lib.versionAtLeast pkgs.claude-code.version minHarness
    || throw "profile '${p.name}': pinned claude-code ${pkgs.claude-code.version} is older than ${minHarness} (needs --restricted and --permission-prompts); update the nixpkgs input";
  hasBash = lib.elem "Bash" p.tools;
  rw = p.filesystem.workspace == "read-write";
  bashSandbox = hasBash && p.network.tools == "deny";

  resolvePkg = n:
    lib.attrByPath (lib.splitString "." n)
      (throw "profile '${p.name}': package '${n}' not found in nixpkgs") pkgs;

  # Claude Code's own Bash sandbox needs bubblewrap + socat (+ ripgrep) on PATH.
  sandboxDeps = lib.optionals bashSandbox [ pkgs.bubblewrap pkgs.socat pkgs.ripgrep ];
  env = pkgs.buildEnv {
    name = "agent-${p.name}-env";
    paths = map resolvePkg p.packages ++ [ pkgs.bashInteractive pkgs.coreutils pkgs.gnused pkgs.gnugrep pkgs.findutils ] ++ sandboxDeps;
    ignoreCollisions = true;
  };

  # Highest-precedence settings layer (bind-mounted at /etc/claude-code/managed-settings.json).
  managedSettings = {
    permissions = {
      defaultMode = "dontAsk";
      allow = p.tools;
      deny = [ "WebFetch" "WebSearch" "NotebookEdit" ]
        ++ lib.optionals (!rw) [ "Edit" "Write" ]
        ++ lib.optional (!hasBash) "Bash";
    };
    disableAllHooks = true;
    allowManagedHooksOnly = true;
  } // lib.optionalAttrs bashSandbox {
    sandbox = {
      enabled = true;
      failIfUnavailable = true;
      allowUnsandboxedCommands = false;
      autoAllowBashIfSandboxed = true;
      network.allowedDomains = [ ];
    };
  };

  behaviourMd = lib.concatStringsSep "\n\n" (
    [ "# Company profile: ${p.name}@${p.version}\n\nThe following behaviour standards are company guidance for this session. Filesystem and tool restrictions are enforced separately by the launcher; do not attempt to work around them." ]
    ++ map (s: builtins.readFile (standardsDir + "/${s}.md")) p.behaviour.standards
    ++ lib.optional p.behaviour.reviewRequired "## Review requirement\nAll changes require review by a separate reviewer before merge. Say so in your final summary."
    ++ lib.optional (p.behaviour.notes != "") "## Notes\n${p.behaviour.notes}"
  );

  enforcement = [
    { control = "workspace ${p.filesystem.workspace}"; by = "kernel (bwrap mount)"; scope = "all tools incl. Bash and subagents"; }
    { control = "policy, settings, skills immutable"; by = "kernel (read-only /nix/store + ro binds)"; scope = "all tools"; }
    { control = "host home, other dirs hidden"; by = "kernel (bwrap minimal root)"; scope = "all tools"; }
    { control = "tool set ${builtins.toJSON p.tools}"; by = "harness (--tools, managed permissions, dontAsk)"; scope = "outside the model, inside the claude process"; }
    { control = "network.tools = ${p.network.tools}"; by =
        if p.network.tools == "open" then "NOT RESTRICTED (declared open)"
        else if bashSandbox then "WebFetch/WebSearch denied (harness); Bash in Claude sandbox, no domains (OS netns via bwrap)"
        else "WebFetch/WebSearch denied (harness); no Bash tool";
      scope = "agent tools"; }
    { control = "model API egress"; by = "always allowed"; scope = "required for the agent to run"; }
    { control = "skills + behaviour standards"; by = "GUIDANCE ONLY (system prompt / skills)"; scope = "compliance not guaranteed"; }
  ] ++ lib.optionals (p.harness == "host") [
    { control = "harness binary version"; by = "host claude (version recorded per run)"; scope = "recorded per run"; }
  ];

  policy = p // {
    inherit rev enforcement;
    profileId = "${p.name}@${p.version}";
    envPath = "${env}";
    bwrap = "${pkgs.bubblewrap}/bin/bwrap";
    bashSandbox = bashSandbox;
    harnessPath = if p.harness == "nixpkgs" then assert pinnedOk; "${pkgs.claude-code}/bin/claude" else null;
    minHarness = minHarness;
    managedSettings = managedSettings;
    packagePaths = lib.genAttrs p.packages (n: "${resolvePkg n}");
  };
in
pkgs.runCommand "agent-${p.name}-${p.version}" {
  passthru = { inherit policy; };
  policyJson = builtins.toJSON policy;
  settingsJson = builtins.toJSON managedSettings;
  agentsJson = builtins.toJSON p.subagents;
  inherit behaviourMd;
  passAsFile = [ "policyJson" "settingsJson" "agentsJson" "behaviourMd" ];
} ''
  mkdir -p $out/plugin/.claude-plugin $out/plugin/skills $out/bin
  ln -s plugin/skills $out/skills
  echo '{"name":"profile-${p.name}","version":"${p.version}","description":"Approved skills for agent profile ${p.name}"}' > $out/plugin/.claude-plugin/plugin.json
  cp $policyJsonPath $out/policy.json
  cp $settingsJsonPath $out/managed-settings.json
  cp $agentsJsonPath $out/agents.json
  cp $behaviourMdPath $out/behaviour.md
  ln -s ${env} $out/env
  ${lib.concatMapStrings (s: "cp -r ${skillsDir + "/${s}"} $out/plugin/skills/${s}\n") p.skills}
  cat > $out/bin/${p.name} <<EOF
  #!${pkgs.runtimeShell}
  exec ${agentctl}/bin/agentctl launch --bundle $out "\$@"
  EOF
  chmod +x $out/bin/${p.name}
''
