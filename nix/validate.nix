# Profile schema + validation. Pure data in, normalised data out, or a clear `throw`.
# Anything we cannot enforce is rejected here rather than silently accepted.
{ lib, skillsDir, standardsDir }:

let
  # Built-in Claude Code tools this MVP knows how to govern.
  supportedTools = [ "Read" "Grep" "Glob" "Edit" "Write" "Bash" "TodoWrite" "Skill" "Agent" ];
  writeTools = [ "Edit" "Write" "NotebookEdit" ];
  networkTools = [ "WebFetch" "WebSearch" ];

  fail = name: msg: throw "profile '${name}': ${msg}";
  checkList = name: field: allowed: xs:
    let bad = lib.filter (x: !(lib.elem x allowed)) xs;
    in if bad == [ ] then xs
       else fail name "${field}: unsupported value(s) ${builtins.toJSON bad}; supported: ${builtins.toJSON allowed}";
  isAbs = p: lib.hasPrefix "/" p;
in
p:
let
  name = p.name or (throw "profile: missing 'name'");
  known = [ "name" "version" "description" "harness" "packages" "filesystem" "network" "tools" "skills" "behaviour" "subagents" ];
  unknownKeys = lib.subtractLists known (builtins.attrNames p);

  fs = { workspace = "read-only"; extraReadOnly = [ ]; } // (p.filesystem or { });
  net = { tools = "deny"; } // (p.network or { });
  tools = p.tools or [ "Read" "Grep" "Glob" ];
  subagents = p.subagents or { };
  behaviour = { standards = [ ]; reviewRequired = false; notes = ""; } // (p.behaviour or { });
in
assert unknownKeys == [ ] || fail name "unknown field(s) ${builtins.toJSON unknownKeys} (refusing to ignore them)";
assert lib.isString (p.version or null) || fail name "missing string 'version'";
assert lib.elem (p.harness or "nixpkgs") [ "nixpkgs" "host" ]
  || fail name "harness must be \"nixpkgs\" (pinned claude-code) or \"host\"";
assert lib.elem fs.workspace [ "read-only" "read-write" ]
  || fail name "filesystem.workspace must be \"read-only\" or \"read-write\"";
assert lib.subtractLists [ "workspace" "extraReadOnly" ] (builtins.attrNames fs) == [ ]
  || fail name "filesystem: only 'workspace' and 'extraReadOnly' are enforceable; extra writable paths are unsupported in this MVP";
assert lib.all isAbs fs.extraReadOnly || fail name "filesystem.extraReadOnly entries must be absolute paths";
assert net.tools != "allowlist"
  || fail name "network.tools = \"allowlist\" is UNSUPPORTED (needs an egress proxy); use \"deny\" or \"open\"";
assert lib.elem net.tools [ "deny" "open" ] || fail name "network.tools must be \"deny\" or \"open\"";
assert (lib.intersectLists networkTools tools == [ ])
  || fail name "WebFetch/WebSearch are not supported tools in this MVP";
assert (fs.workspace == "read-write" || lib.intersectLists writeTools tools == [ ])
  || fail name "write tools ${builtins.toJSON (lib.intersectLists writeTools tools)} conflict with filesystem.workspace = \"read-only\"";
assert (subagents == { } || lib.elem "Agent" tools)
  || fail name "subagents are declared but the 'Agent' tool is not in tools";
let
  checkedTools = checkList name "tools" supportedTools tools;
  checkedSubagents = lib.mapAttrs (sn: sa:
    assert lib.isString (sa.description or null) || fail name "subagent '${sn}' needs a description";
    assert lib.isString (sa.prompt or null) || fail name "subagent '${sn}' needs a prompt";
    {
      inherit (sa) description prompt;
      tools = checkList name "subagents.${sn}.tools" (lib.remove "Agent" checkedTools) (sa.tools or [ "Read" "Grep" "Glob" ]);
    }) subagents;
  checkSkill = s:
    if builtins.pathExists (skillsDir + "/${s}/SKILL.md") then s
    else fail name "skill '${s}' not found in local skill registry (skills/${s}/SKILL.md)";
  checkStandard = s:
    if builtins.pathExists (standardsDir + "/${s}.md") then s
    else fail name "behaviour standard '${s}' not found (standards/${s}.md)";
in
{
  inherit name;
  inherit (p) version;
  description = p.description or "";
  harness = p.harness or "nixpkgs";
  packages = p.packages or [ ];
  filesystem = fs;
  network = net;
  tools = checkedTools;
  skills = map checkSkill (p.skills or [ ]);
  behaviour = behaviour // { standards = map checkStandard behaviour.standards; };
  subagents = checkedSubagents;
}
