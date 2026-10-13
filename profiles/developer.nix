{
  name = "developer";
  version = "1.0.0";
  description = "Implementation agent with workspace write access and ACME coding standards";
  packages = [ "ripgrep" "git" "python3" "ruff" ];
  filesystem.workspace = "read-write";
  network.tools = "deny";
  tools = [ "Read" "Grep" "Glob" "Edit" "Write" "Bash" "TodoWrite" "Skill" ];
  skills = [ "implement-feature" ];
  behaviour = {
    standards = [ "coding" ];
    reviewRequired = true;
  };
}
