{
  name = "reviewer";
  version = "1.0.0";
  description = "Read-only code reviewer applying ACME review standards";
  packages = [ "ripgrep" "git" ];
  filesystem.workspace = "read-only";
  network.tools = "deny";
  tools = [ "Read" "Grep" "Glob" "Skill" "Agent" ];
  skills = [ "code-review" ];
  behaviour = {
    standards = [ "review" ];
    notes = "You are a reviewer. Never modify repository files; report findings only.";
  };
  subagents.security-auditor = {
    description = "Focused security pass over the files under review";
    prompt = "You audit code for security issues. Report findings with file:line and severity. Read-only.";
    tools = [ "Read" "Grep" "Glob" ];
  };
}
