#!/usr/bin/env python3
"""
On-screen "Exit mirroring" button shown above the AirPlay video (the kiosk browser is closed while mirroring,
so the touchscreen would otherwise have nothing to tap). Started by rpiplay.sh, stopped together with the service.

Needs the system python3 with GTK3 (python3-gi, gir1.2-gtk-3.0). On Wayland (labwc/Wayfire) it uses
gtk-layer-shell (gir1.2-gtklayershell-0.1) so the button floats above the fullscreen video; on X11 it keeps
itself on top. Without GTK it exits quietly and mirroring simply runs without the button.
"""
import ctypes.util
import os
import subprocess
import sys

SERVICE = "homeauto-rpiplay.service"

# gtk-layer-shell must be loaded before libwayland-client, so preload it and restart once
if os.environ.get("WAYLAND_DISPLAY") and "gtk-layer-shell" not in os.environ.get("LD_PRELOAD", ""):
    lib = ctypes.util.find_library("gtk-layer-shell")
    if lib:
        env = dict(os.environ, LD_PRELOAD=(os.environ.get("LD_PRELOAD", "") + " " + lib).strip())
        os.execve(sys.executable, [sys.executable] + sys.argv, env)

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
except Exception as e:  # GTK not installed
    print(f"mirroring_exit: GTK not available, no exit button ({e})", file=sys.stderr)
    sys.exit(0)

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except Exception:
    GtkLayerShell = None

CSS = b"""
window { background: transparent; }
button {
  background: rgba(185, 28, 28, 0.88);
  color: #fff;
  font-size: 22px;
  font-weight: bold;
  padding: 16px 28px;
  border-radius: 14px;
  border: 2px solid rgba(255, 255, 255, 0.6);
}
button:active { background: #7f1d1d; }
"""


def stop_mirroring(_btn):
    # Stopping the unit also starts the kiosk again (ExecStopPost)
    subprocess.Popen(["systemctl", "--user", "stop", SERVICE])


def main():
    win = Gtk.Window(title="Exit mirroring")
    win.set_decorated(False)
    win.set_resizable(False)
    win.set_accept_focus(False)
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    btn = Gtk.Button(label="✕  Exit mirroring")
    btn.connect("clicked", stop_mirroring)
    win.add(btn)

    use_layer = GtkLayerShell is not None and GtkLayerShell.is_supported()
    if use_layer:
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, 16)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.RIGHT, 16)
        win.show_all()
    else:
        # X11 (or Wayland without layer-shell): top-right corner, always on top, re-raised in case the video window appears later
        win.set_keep_above(True)
        win.set_type_hint(Gdk.WindowTypeHint.DOCK)
        win.set_skip_taskbar_hint(True)
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        win.show_all()
        width, _ = win.get_size()
        win.move(geo.x + geo.width - width - 16, geo.y + 16)

        def keep_on_top():
            gdk_win = win.get_window()
            if gdk_win:
                gdk_win.raise_()
            return True
        GLib.timeout_add(1000, keep_on_top)

    Gtk.main()


if __name__ == "__main__":
    main()
