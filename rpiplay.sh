#!/usr/bin/env bash
# ==========================================================
# AirPlay screen-mirroring receiver for the HomeAuto kiosk Pi.
# Started by homeauto-rpiplay.service (dashboard "Screen Mirroring" button); the service stops the kiosk browser
# while this runs and starts it again when it ends.
# Prefers UxPlay (maintained, GStreamer based, works on current Pi OS); falls back to RPiPlay, which only runs on
# the old Pi graphics stack. Output goes to the journal: journalctl --user -u homeauto-rpiplay
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

if command -v uxplay >/dev/null 2>&1; then
  # Fullscreen video; the sink is picked by GStreamer (waylandsink / kmssink / ximagesink) unless HOMEAUTO_UXPLAY_ARGS is set
  # in ~/homeauto/.kiosk_env, e.g.  export HOMEAUTO_UXPLAY_ARGS="-vs kmssink -as alsasink"
  KIOSK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=/dev/null
  [ -f "$KIOSK_DIR/.kiosk_env" ] && . "$KIOSK_DIR/.kiosk_env"
  # shellcheck disable=SC2086
  echo "Starting: uxplay -n $NAME -fs ${HOMEAUTO_UXPLAY_ARGS:-}"
  # shellcheck disable=SC2086
  exec uxplay -n "$NAME" -fs ${HOMEAUTO_UXPLAY_ARGS:-}
fi

if command -v rpiplay >/dev/null 2>&1; then
  ARGS=(-n "$NAME")
  # RPiPlay's default video/audio output is OpenMAX (old Pi graphics stack). Without it use the GStreamer / ALSA
  # renderers, if this build has them.
  if [ ! -e /opt/vc/lib/libopenmaxil.so ]; then
    HELP="$(rpiplay -h 2>&1)"
    echo "$HELP" | grep -q -- "-vr" && ARGS+=(-vr gstreamer)
    echo "$HELP" | grep -q -- "-ar" && ARGS+=(-ar alsa)
  fi
  echo "Starting: rpiplay ${ARGS[*]}"
  exec rpiplay "${ARGS[@]}" 2>&1
fi

echo "Error: neither uxplay nor rpiplay is installed. Run: sudo apt install uxplay" >&2
exit 1
