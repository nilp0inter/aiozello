{
  description = "A Zello async library for Python";
  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    flake-utils,
    nixpkgs,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      lib = nixpkgs.lib;
    in {
      formatter = pkgs.alejandra;

      devShells.default = pkgs.mkShell {
        packages = [
          pkgs.poetry
          pkgs.ffmpeg
        ];
        LD_LIBRARY_PATH = lib.makeLibraryPath (with pkgs; [
          libopus
        ]);
      };
    });
}
