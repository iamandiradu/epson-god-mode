#!/usr/bin/env bash
# Double-click on a Mac to build "Epson God Mode.app" and a .dmg into the dist folder.
cd "$(dirname "$0")"
[ -f signing.env.sh ] && source signing.env.sh
./packaging/build_macos.sh && open dist
echo; read -r -p "Press Enter to close..."
