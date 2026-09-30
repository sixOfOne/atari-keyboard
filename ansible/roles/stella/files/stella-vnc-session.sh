#!/bin/bash
# Minimal X session for TigerVNC: metacity WM + an xterm for launching Stella.
set -euo pipefail
unset SESSION_MANAGER
export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-x11}"

if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  if command -v dbus-launch >/dev/null 2>&1; then
    eval "$(dbus-launch --sh-syntax)"
  fi
fi

if command -v xrdb >/dev/null 2>&1 && [ -r "$HOME/.Xresources" ]; then
  xrdb -merge "$HOME/.Xresources"
fi

if command -v xsetroot >/dev/null 2>&1; then
  xsetroot -solid '#2e3436' || true
fi

metacity --sm-disable &
sleep 0.5
exec xterm -geometry 100x30+40+40 -fa DejaVuSansMono -fs 11 -ls \
  -T "Stella VNC — stella-flatpak ~/roms/game.a26"
