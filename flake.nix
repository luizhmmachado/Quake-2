{
  description = "Quake 2 (id Software GPL release) - Linux build environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "i686-linux" "aarch64-linux" ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          name = "quake2-dev";

          nativeBuildInputs = with pkgs; [
            gcc
            gnumake
            gdb
            pkg-config
          ];

          # rw_x11.c / vid_so.c need the X11 headers and libs.
          buildInputs = with pkgs; [
            libx11
            libxext
            xorgproto
          ];

          shellHook = ''
            echo "quake2 dev shell. Build with:"
            echo "  make -f linux/Makefile.i386 build_debug"
            echo "  make -f linux/Makefile.i386 build_release"
          '';
        };
      });

      packages = forAllSystems (pkgs: rec {
        default = quake2;

        quake2 = pkgs.stdenv.mkDerivation {
          pname = "quake2";
          version = "3.21";
          src = self;

          nativeBuildInputs = with pkgs; [ gnumake ];
          buildInputs = with pkgs; [ libx11 libxext xorgproto ];

          buildPhase = ''
            runHook preBuild
            make -f linux/Makefile.i386 build_release MOUNT_DIR="$PWD"
            runHook postBuild
          '';

          installPhase = ''
            runHook preInstall
            mkdir -p $out/bin $out/lib/quake2
            arch=$(uname -m | sed 's/^x86_64$/i386/;s/^i.86$/i386/')
            cp release*/quake2 $out/bin/quake2
            cp release*/*.so $out/lib/quake2/
            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "id Software's Quake II, GPL source release";
            license = licenses.gpl2Plus;
            platforms = systems;
            mainProgram = "quake2";
          };
        };
      });
    };
}
