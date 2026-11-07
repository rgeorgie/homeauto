"""
Camera / doorbell controls, driven by what each device's Tuya specification says it can do.
Only writable codes listed in CONTROLS are offered (never sd_format, device_restart, ...), values are checked against
the spec before anything is sent, and enum options / ranges come from the spec, so each camera model gets its own set.
"""
import json
from typing import Any, Dict, List, Optional, Tuple

# code -> label. Order here is the order in the UI.
CONTROLS: Dict[str, str] = {
    "basic_private": "Privacy mode (camera off)",
    "motion_switch": "Motion detection",
    "motion_sensitivity": "Motion sensitivity",
    "humanoid_filter": "Person filter",
    "motion_tracking": "Motion tracking",
    "record_switch": "Recording",
    "record_mode": "Recording mode",
    "basic_nightvision": "Night vision",
    "nightvision_mode": "Night vision",
    "floodlight_switch": "Floodlight",
    "siren_switch": "Siren",
    "basic_device_volume": "Volume",
    "basic_flip": "Flip image",
    "basic_osd": "Time watermark",
    "cruise_switch": "Auto cruise",
}

ENUM_LABELS: Dict[str, Dict[str, str]] = {
    "motion_sensitivity": {"0": "Low", "1": "Medium", "2": "High"},
    "record_mode": {"1": "Events only", "2": "Continuous"},
    "basic_nightvision": {"0": "Auto", "1": "Off", "2": "On"},
    "nightvision_mode": {"auto": "Auto", "ir_mode": "Infrared", "color_mode": "Colour"},
}

# Tuya ptz_control values: 0 up, 1 up-right, 2 right, 3 down-right, 4 down, 5 down-left, 6 left, 7 up-left
PTZ_DIRECTIONS: Dict[str, str] = {
    "up": "0", "up_right": "1", "right": "2", "down_right": "3",
    "down": "4", "down_left": "5", "left": "6", "up_left": "7",
}


def _parse_values(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else {}
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def writable_functions(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """code -> {"type": "Boolean" | "Enum" | "Integer" | ..., "values": {...}} for everything the device accepts commands for."""
    out = {}
    for f in (spec or {}).get("functions") or []:
        if isinstance(f, dict) and f.get("code"):
            out[f["code"]] = {"type": str(f.get("type", "")), "values": _parse_values(f.get("values"))}
    return out


def build_controls(spec: Dict[str, Any], codes: Dict[str, Any]) -> Dict[str, Any]:
    """The controls panel for one camera: {"controls": [...], "ptz": [direction names] }. `codes` holds the current values."""
    funcs = writable_functions(spec)
    controls: List[Dict[str, Any]] = []
    for code, label in CONTROLS.items():
        f = funcs.get(code)
        if not f:
            continue
        value = (codes or {}).get(code)
        kind = f["type"].lower()
        if kind == "boolean":
            controls.append({"code": code, "label": label, "kind": "bool", "value": value if isinstance(value, bool) else None})
        elif kind == "enum":
            options = [{"value": v, "label": ENUM_LABELS.get(code, {}).get(v, v)} for v in f["values"].get("range", [])]
            if options:
                controls.append({"code": code, "label": label, "kind": "enum", "value": value, "options": options})
        elif kind == "integer":
            v = f["values"]
            if "min" in v and "max" in v:
                controls.append({"code": code, "label": label, "kind": "range", "value": value if isinstance(value, int) else None,
                                 "min": v["min"], "max": v["max"], "step": v.get("step", 1) or 1, "unit": v.get("unit", "")})
    ptz = []
    if "ptz_control" in funcs and "ptz_stop" in funcs:
        allowed = set(funcs["ptz_control"]["values"].get("range", []))
        ptz = [name for name, v in PTZ_DIRECTIONS.items() if v in allowed]
    return {"controls": controls, "ptz": ptz}


def check_command(spec: Dict[str, Any], code: str, value: Any) -> Tuple[Optional[Any], Optional[str]]:
    """Validates a requested change. Returns (value to send, None) or (None, reason it was refused)."""
    f = writable_functions(spec).get(code)
    if code not in CONTROLS or not f:
        return None, "This camera has no such setting"
    kind = f["type"].lower()
    if kind == "boolean":
        return (value, None) if isinstance(value, bool) else (None, "Expected true or false")
    if kind == "enum":
        return (value, None) if isinstance(value, str) and value in f["values"].get("range", []) else (None, "Not an allowed option")
    if kind == "integer":
        v = f["values"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "Expected a whole number"
        if "min" in v and "max" in v and not (v["min"] <= value <= v["max"]):
            return None, f"Must be between {v['min']} and {v['max']}"
        return value, None
    return None, "Unsupported setting type"
