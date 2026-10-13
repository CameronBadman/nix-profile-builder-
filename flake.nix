{
  description = "Company-managed, versioned agent profiles for Claude Code";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      # Only claude-code is allowed through the unfree gate (it is the pinned harness).
      forAll = f: lib.genAttrs systems (s: f (import nixpkgs {
        system = s;
        config.allowUnfreePredicate = p: lib.getName p == "claude-code";
      }));

      skillsDir = ./skills;
      standardsDir = ./standards;
      validate = import ./nix/validate.nix { inherit lib skillsDir standardsDir; };
      rev = self.rev or self.dirtyRev or "unknown";

      # Local profile registry: every profiles/<name>.nix becomes a named agent.
      profileFiles = lib.filterAttrs (n: t: t == "regular" && lib.hasSuffix ".nix" n)
        (builtins.readDir ./profiles);
      profiles = lib.mapAttrs' (f: _:
        let v = validate (import (./profiles + "/${f}"));
        in lib.nameValuePair v.name v) profileFiles;
    in
    {
      lib = { inherit validate; };

      # `nix eval --json .#profiles.reviewer` — the declarative, validated profile.
      inherit profiles;

      packages = forAll (pkgs:
        let
          agentctl = pkgs.writeScriptBin "agentctl"
            ("#!${pkgs.python3}/bin/python3\n" + builtins.readFile ./agentctl/agentctl.py);
          mkAgent = profile: import ./nix/mkAgent.nix {
            inherit pkgs lib profile agentctl skillsDir standardsDir rev;
          };
        in
        lib.mapAttrs (_: mkAgent) profiles // { inherit agentctl; default = agentctl; });

      apps = forAll (pkgs: lib.mapAttrs (n: drv: {
        type = "app";
        program = if n == "agentctl" || n == "default"
          then "${drv}/bin/agentctl" else "${drv}/bin/${n}";
      }) self.packages.${pkgs.stdenv.hostPlatform.system});

      checks = forAll (pkgs: import ./tests/invalid-profiles.nix { inherit pkgs lib validate; });
    };
}
