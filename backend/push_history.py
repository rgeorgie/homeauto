"""
Push history: a log of what Tuya's message service pushed (doorbell rings, SOS presses, doors opening, devices going
online / offline, ...). Continuous readings (temperature, power draw, ...) are left out, and so are repeats of an
unchanged value, so the list stays readable. The newest KEEP entries are stored in data/push_history.json.
"""
import asyncio
import base64
import itertools
import json
import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.config import PROJECT_ROOT

logger = logging.getLogger("HomeAuto.PushHistory")

HISTORY_FILE = os.path.join(PROJECT_ROOT, "data", "push_history.json")
KEEP = 200

# Codes that are events: each message counts, even when the value equals the previous one (an SOS press always says "sos")
EVENT_CODES = {"doorbell_active", "doorbell_pic", "alarm_message", "sos_mode"}

# Continuous readings and housekeeping codes: not interesting as history
NOISY_CODES = {
    "temp_current", "va_temperature", "temp_indoor", "humidity_value", "va_humidity", "humidity_current",
    "cur_power", "cur_current", "cur_voltage", "add_ele", "sd_storge", "sd_format_state", "movement_detect_pic",
    "initiative_message", "decibel_upload", "ptz_control", "ptz_stop", "bright_value", "bright_value_v2",
    "temp_value", "temp_value_v2", "colour_data", "colour_data_v2",
}

BATTERY_CODES = {"battery_percentage", "battery", "wireless_electricity", "va_battery", "residual_electricity", "battery_value"}
ALARM_LABELS = {"ipc_human": "Person detected", "ipc_motion": "Motion detected", "ipc_low_battery": "Low battery"}
BATTERY_STATE_LABELS = {"low": "low", "middle": "medium", "high": "high"}


def describe(code: str, value: Any) -> Optional[str]:
    """One readable line for a pushed code / value, or None when it is not worth logging."""
    if value is None or code in NOISY_CODES:
        return None
    if code in EVENT_CODES and value in ("", "$", False):  # "nothing happened"
        return None
    if code in ("doorbell_active", "doorbell_pic"):
        return "Doorbell ring"
    if code == "sos_mode":
        return "SOS button pressed"
    if code == "alarm_message":
        cmd = ""
        if isinstance(value, str):
            try:
                cmd = json.loads(base64.b64decode(value + "=" * (-len(value) % 4))).get("cmd", "")
            except Exception:
                cmd = ""
        return ALARM_LABELS.get(cmd) or (f"Alert ({cmd})" if cmd else "Alert")
    if code in ("doorcontact_state", "contact_state") and isinstance(value, bool):
        return "Opened" if value else "Closed"
    if code in ("pir", "presence_state") and isinstance(value, str):
        return "Motion cleared" if value.lower() in ("none", "clear", "off") else "Motion detected"
    if code in BATTERY_CODES and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"Battery {int(value)}%"
    if code == "battery_state" and isinstance(value, str):
        return f"Battery {BATTERY_STATE_LABELS.get(value.lower(), value)}"
    if (code == "switch" or code.startswith("switch_")) and isinstance(value, bool):
        return "Switched on" if value else "Switched off"
    return f"{code}: {str(value)[:40]}"


class PushHistory:
    def __init__(self,
                 device_name: Callable[[str], str],
                 broadcast: Callable[[Dict[str, Any]], Awaitable[None]],
                 path: str = HISTORY_FILE):
        self._device_name = device_name
        self._broadcast = broadcast
        self._path = path
        self._lock = threading.Lock()
        self._last: Dict[str, Any] = {}  # "dev_id/code" -> last value seen (to drop repeats of non-event codes)
        self._last_biz: Dict[str, str] = {}
        self._seq = itertools.count()  # makes ids unique even for two messages in the same millisecond
        self._entries: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return [e for e in json.load(f) if isinstance(e, dict) and e.get("id")]
        except (OSError, ValueError):
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._entries, f)
        os.replace(tmp, self._path)

    def _store(self, new: List[Dict[str, Any]]):
        with self._lock:
            self._entries = (new[::-1] + self._entries)[:KEEP]  # newest first
            self._save()

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries = []
            self._save()

    def _lines(self, dev_id: str, biz: Optional[str], codes: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        if biz in ("online", "offline"):
            if self._last_biz.get(dev_id) != biz:  # Tuya sometimes repeats these
                lines.append("Came online" if biz == "online" else "Went offline")
            self._last_biz[dev_id] = biz
        for code, value in codes.items():
            key = f"{dev_id}/{code}"
            if code not in EVENT_CODES:
                if self._last.get(key) == value and key in self._last:
                    continue
                self._last[key] = value
            line = describe(code, value)
            if line and line not in lines:  # e.g. doorbell_active and doorbell_pic arrive together for one ring
                lines.append(line)
        return lines

    async def record(self, dev_id: str, biz: Optional[str], codes: Dict[str, Any]):
        """Logs one pushed message (called on the event loop)."""
        try:
            lines = self._lines(dev_id, biz, codes)
            if not lines:
                return
            name = self._device_name(dev_id)
            now = time.time()
            entries = [{"id": f"{int(now * 1000)}-{next(self._seq)}-{dev_id[:6]}", "dev_id": dev_id, "dev_name": name, "text": text, "ts": now}
                       for text in lines]
            await asyncio.get_event_loop().run_in_executor(None, self._store, entries)
            for entry in entries:
                await self._broadcast(entry)
        except Exception as e:
            logger.error(f"Could not log push message: {e}")
