"""
Raspberry Pi controls for the Admin panel: Wi-Fi (NetworkManager / nmcli), Bluetooth power,
leaving the kiosk for the desktop, restarting services, reboot / shutdown.

Every function returns a plain dict and never raises: {"ok": bool, "message": str, ...}.
These run real system commands, so main.py only exposes them to requests coming from the Pi itself.
"""
import logging
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HomeAuto.PiControl")

KIOSK_SERVICE = "homeauto-kiosk.service"
APP_SERVICE = "homeauto.service"
RPIPLAY_SERVICE = "homeauto-rpiplay.service"  # installed by install.sh; Conflicts= with the kiosk, restarts it when it stops
RETURN_UNIT = "homeauto-kiosk-return"  # transient timer that brings the kiosk back after "open desktop"
MAX_DESKTOP_MINUTES = 240


def _run(cmd: List[str], timeout: float = 10, **kwargs) -> Tuple[int, str, str]:
    """Runs a command (no shell). Returns (returncode, stdout, stderr); 127 = not installed, 124 = timed out."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} timed out"
    except Exception as e:  # pragma: no cover - defensive
        return 1, "", str(e)


def _result(ok: bool, message: str, **extra) -> Dict[str, Any]:
    return {"ok": ok, "message": message, **extra}


def split_terse(line: str) -> List[str]:
    """Splits one line of `nmcli -t` output: ':' separates fields, '\\:' and '\\\\' are escaped characters."""
    fields, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
        elif c == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    fields.append("".join(cur))
    return fields


def parse_wifi_list(output: str) -> List[Dict[str, Any]]:
    """Parses `nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list`: one entry per SSID (strongest), connected first."""
    best: Dict[str, Dict[str, Any]] = {}
    for line in output.splitlines():
        parts = split_terse(line)
        if len(parts) < 4 or not parts[1].strip():
            continue  # hidden networks have no name to show
        in_use, ssid, signal, security = parts[0] == "*", parts[1], parts[2], parts[3]
        entry = {"ssid": ssid, "signal": int(signal) if signal.isdigit() else 0,
                 "secured": bool(security.strip()) and security.strip() != "--", "in_use": in_use}
        old = best.get(ssid)
        if old is None or entry["in_use"] or (not old["in_use"] and entry["signal"] > old["signal"]):
            best[ssid] = entry
    return sorted(best.values(), key=lambda e: (not e["in_use"], -e["signal"], e["ssid"].lower()))


# ----------------------------- Wi-Fi -----------------------------

def wifi_status() -> Dict[str, Any]:
    rc, out, err = _run(["nmcli", "radio", "wifi"])
    if rc != 0:
        return {"available": False, "message": err or "NetworkManager (nmcli) not available"}
    enabled = out.strip().lower() == "enabled"
    ssid, signal = None, None
    if enabled:
        rc, out, _ = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
        if rc == 0:
            current = next((n for n in parse_wifi_list(out) if n["in_use"]), None)
            if current:
                ssid, signal = current["ssid"], current["signal"]
    return {"available": True, "enabled": enabled, "ssid": ssid, "signal": signal}


def wifi_scan() -> Dict[str, Any]:
    rc, out, err = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], timeout=25)
    if rc != 0:
        return _result(False, err or "Wi-Fi scan failed", networks=[])
    return _result(True, "ok", networks=parse_wifi_list(out))


def wifi_set_power(on: bool) -> Dict[str, Any]:
    rc, _, err = _run(["nmcli", "radio", "wifi", "on" if on else "off"])
    return _result(rc == 0, f"Wi-Fi turned {'on' if on else 'off'}" if rc == 0 else (err or "Could not change Wi-Fi power"))


def wifi_connect(ssid: str, password: str = "") -> Dict[str, Any]:
    ssid = (ssid or "").strip()
    if not ssid or len(ssid.encode("utf-8")) > 32:
        return _result(False, "Enter a network name (up to 32 bytes)")
    if ssid.startswith("-"):
        return _result(False, "Network names starting with '-' are not supported here")  # would be read as an nmcli option
    cmd = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
    rc, out, err = _run(cmd, timeout=45)  # the password is never logged
    if rc == 0:
        return _result(True, f"Connected to {ssid}")
    logger.warning(f"Wi-Fi connect to '{ssid}' failed (code {rc})")
    return _result(False, (err or out or "Could not connect").replace(password, "***") if password else (err or out or "Could not connect"))


# ----------------------------- Bluetooth -----------------------------

def bluetooth_status() -> Dict[str, Any]:
    rc, out, err = _run(["bluetoothctl", "show"])
    if rc != 0 or "No default controller" in out:
        return {"available": False, "message": err or out or "No Bluetooth controller found"}
    m = re.search(r"Powered:\s*(yes|no)", out)
    return {"available": True, "powered": bool(m and m.group(1) == "yes")}


def bluetooth_set_power(on: bool) -> Dict[str, Any]:
    if on:
        _run(["rfkill", "unblock", "bluetooth"])  # a blocked radio can't be powered on; harmless if rfkill is missing
    rc, out, err = _run(["bluetoothctl", "power", "on" if on else "off"])
    ok = rc == 0 and "Failed" not in out
    return _result(ok, f"Bluetooth turned {'on' if on else 'off'}" if ok else (err or out or "Could not change Bluetooth power"))


# ----------------------------- Kiosk / desktop -----------------------------

def _systemctl_user(*args: str) -> Tuple[int, str, str]:
    return _run(["systemctl", "--user", *args])


def open_desktop(minutes: int) -> Dict[str, Any]:
    """Closes the kiosk browser to reveal the Raspberry Pi desktop, and schedules the kiosk to come back."""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 10
    minutes = max(1, min(MAX_DESKTOP_MINUTES, minutes))

    _systemctl_user("stop", f"{RETURN_UNIT}.timer")  # replace an earlier schedule
    rc, _, err = _run(["systemd-run", "--user", f"--unit={RETURN_UNIT}", f"--on-active={minutes * 60}s",
                       "systemctl", "--user", "start", KIOSK_SERVICE])
    if rc != 0:
        # Without the timer there would be no way back from the desktop, so don't leave the kiosk
        return _result(False, f"Could not schedule the return to the dashboard, so the kiosk was left running: {err}")
    _systemctl_user("stop", KIOSK_SERVICE)
    _run(["pkill", "-f", "chrom.*--kiosk"])  # a kiosk started by the desktop autostart instead of the service
    return _result(True, f"Desktop open. The dashboard returns automatically in {minutes} min.", minutes=minutes)


def return_to_dashboard() -> Dict[str, Any]:
    _systemctl_user("stop", f"{RETURN_UNIT}.timer")
    rc, _, err = _systemctl_user("start", KIOSK_SERVICE)
    return _result(rc == 0, "Dashboard restored" if rc == 0 else (err or "Could not start the kiosk"))


def restart_kiosk() -> Dict[str, Any]:
    rc, _, err = _systemctl_user("restart", KIOSK_SERVICE)
    return _result(rc == 0, "Kiosk restarted" if rc == 0 else (err or "Could not restart the kiosk"))


def restart_app() -> Dict[str, Any]:
    """Restarts HomeAuto itself. Done from a separate transient unit, otherwise the restart would kill its own command."""
    rc, _, err = _run(["systemd-run", "--user", "--on-active=2s", "systemctl", "--user", "restart", APP_SERVICE])
    return _result(rc == 0, "HomeAuto is restarting..." if rc == 0 else (err or "Could not schedule the restart"))


# ----------------------------- Screen mirroring (RPiPlay / AirPlay) -----------------------------

def rpiplay_status() -> Dict[str, Any]:
    # install.sh builds RPiPlay, or falls back to UxPlay (same AirPlay protocol) where RPiPlay can't run (Pi OS Bookworm)
    installed = any(shutil.which(b) or shutil.which(b, path="/usr/local/bin") for b in ("rpiplay", "uxplay"))
    rc, _, _ = _systemctl_user("cat", RPIPLAY_SERVICE)
    configured = rc == 0
    active = False
    if configured:
        _, out, _ = _systemctl_user("is-active", RPIPLAY_SERVICE)
        active = out.strip() == "active"
    return {"installed": installed, "configured": configured, "active": active}


def rpiplay_start() -> Dict[str, Any]:
    """Starts the RPiPlay service. The service Conflicts= with the kiosk, so systemd closes the browser to show the mirrored screen."""
    status = rpiplay_status()
    if not status["installed"] or not status["configured"]:
        return _result(False, "RPiPlay is not set up on this Pi. Run ./install.sh --kiosk again to install it.", **status)
    rc, _, err = _systemctl_user("start", RPIPLAY_SERVICE)
    if rc != 0:
        return _result(False, err or "Could not start RPiPlay", **status)
    _run(["pkill", "-f", "chrom.*--kiosk"])  # a kiosk started by the desktop autostart instead of the service
    return _result(True, "Screen mirroring is ready. On the iPhone/iPad/Mac pick 'HomeAuto' in Screen Mirroring.", **{**status, "active": True})


def rpiplay_stop() -> Dict[str, Any]:
    """Stops RPiPlay; its unit then starts the kiosk again (ExecStopPost)."""
    rc, _, err = _systemctl_user("stop", RPIPLAY_SERVICE)
    if rc == 0:
        _systemctl_user("start", "--no-block", KIOSK_SERVICE)  # in case the kiosk was started outside the service
    return _result(rc == 0, "Mirroring stopped" if rc == 0 else (err or "Could not stop RPiPlay"), **rpiplay_status())


# ----------------------------- Power -----------------------------

def power(action: str) -> Dict[str, Any]:
    verbs = {"reboot": "reboot", "shutdown": "poweroff"}
    verb = verbs.get(action)
    if not verb:
        return _result(False, "Unknown action")
    rc, _, err = _run(["systemctl", verb])
    if rc != 0:  # not allowed for this session: fall back to passwordless sudo (default on Raspberry Pi OS)
        rc, _, err = _run(["sudo", "-n", "systemctl", verb])
    label = "Rebooting..." if action == "reboot" else "Shutting down..."
    return _result(rc == 0, label if rc == 0 else (err or f"Could not {action}"))
