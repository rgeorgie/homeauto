#!/usr/bin/env bash
# ==========================================================
# AirPlay screen-mirroring receiver for the HomeAuto kiosk Pi.
# Started by homeauto-rpiplay.service (dashboard "Screen Mirroring" button); the service stops the kiosk browser
# while this runs and starts it again when it ends.
# Uses RPiPlay (built by install.sh); falls back to UxPlay (same AirPlay protocol) when RPiPlay isn't available.
# ==========================================================

NAME="${HOMEAUTO_AIRPLAY_NAME:-HomeAuto}"

export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XDG_RUNTIME_DIR" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [ -z "$WAYLAND_DISPLAY" ] && [ -e "$XDG_RUNTIME_DIR/wayland-0" ]; then
  export WAYLAND_DISPLAY="wayland-0"
fi

for dir in "" /usr/local/bin/; do
  if command -v "${dir}rpiplay" >/dev/null 2>&1; then
    exec "${dir}rpiplay" -n "$NAME"
  fi
done
for dir in "" /usr/local/bin/; do
  if command -v "${dir}uxplay" >/dev/null 2>&1; then
    exec "${dir}uxplay" -n "$NAME"
  fi
done

echo "Error: neither rpiplay nor uxplay is installed. Run ./install.sh --kiosk again." >&2
exit 1
