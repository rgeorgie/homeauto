#!/usr/bin/env bash
# ==========================================================
# AirPlay screen-mirroring receiver for the HomeAuto kiosk Pi.
# Started by homeauto-rpiplay.service (dashboard "Screen Mirroring" button); the service stops the kiosk browser
# while this runs and starts it again when it ends.
# Uses RPiPlay (built by install.sh); falls back to UxPlay (same AirPlay protocol) when RPiPlay isn't available
# or can't run. Output goes to the journal: journalctl --user -u homeauto-rpiplay
# ==========================================================

NAME="${HOMEAUTO_AIRPLAY_NAME:-HomeAuto}"

export DISPLAY="${DISPLAY:-:0}"
if [ -z "$XDG_RUNTIME_DIR" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [ -z "$WAYLAND_DISPLAY" ] && [ -e "$XDG_RUNTIME_DIR/wayland-0" ]; then
  export WAYLAND_DISPLAY="wayland-0"
fi
export PATH="/usr/local/bin:$PATH"

echo "Session: DISPLAY=$DISPLAY WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-none} XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

if command -v rpiplay >/dev/null 2>&1; then
  ARGS=(-n "$NAME")
  # RPiPlay's default video/audio output is OpenMAX (old Pi graphics stack). Without it (Pi OS Bookworm, Pi 4/5)
  # use the GStreamer / ALSA renderers, if this build has them.
  if [ ! -e /opt/vc/lib/libopenmaxil.so ]; then
    HELP="$(rpiplay -h 2>&1)"
    echo "$HELP" | grep -q -- "-vr" && ARGS+=(-vr gstreamer)
    echo "$HELP" | grep -q -- "-ar" && ARGS+=(-ar alsa)
  fi
  echo "Starting: rpiplay ${ARGS[*]}"
  rpiplay "${ARGS[@]}"
  rc=$?
  echo "rpiplay exited with code $rc"
  # Failed to run: try UxPlay instead
  if ! command -v uxplay >/dev/null 2>&1; then
    exit "$rc"
  fi
fi

if command -v uxplay >/dev/null 2>&1; then
  echo "Starting: uxplay -n $NAME"
  exec uxplay -n "$NAME"
fi

echo "Error: neither rpiplay nor uxplay is installed. Run ./install.sh --kiosk again." >&2
exit 1
