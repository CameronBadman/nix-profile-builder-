# `nix flake check`: each bad profile must FAIL validation with the expected message.
{ pkgs, lib, validate }:
let
  base = { name = "t"; version = "0"; skills = [ ]; };
  cases = {
    unknown-tool = { p = base // { tools = [ "Read" "PowerShell" ]; }; msg = "unsupported value"; };
    allowlist-network = { p = base // { network.tools = "allowlist"; }; msg = "UNSUPPORTED"; };
    write-on-readonly = { p = base // { tools = [ "Read" "Edit" ]; }; msg = "conflict"; };
    webfetch = { p = base // { tools = [ "WebFetch" ]; filesystem.workspace = "read-write"; }; msg = "WebFetch"; };
    unknown-field = { p = base // { sudo = true; }; msg = "unknown field"; };
    extra-writable = { p = base // { filesystem.extraReadWrite = [ "/srv" ]; }; msg = "unsupported"; };
    missing-skill = { p = base // { skills = [ "nope" ]; }; msg = "not found"; };
    subagent-escalation = { p = base // { tools = [ "Read" "Agent" ]; subagents.x = { description = "d"; prompt = "p"; tools = [ "Bash" ]; }; }; msg = "subagents.x.tools"; };
  };
  run = n: c:
    let r = builtins.tryEval (builtins.deepSeq (validate c.p) true);
    in assert lib.assertMsg (!r.success) "bad profile '${n}' was accepted"; pkgs.runCommand "rejects-${n}" { } "touch $out";
in lib.mapAttrs run cases
