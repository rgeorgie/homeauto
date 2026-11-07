#!/usr/bin/env python3
"""
Probes Tuya Cloud for SD-card recordings of a camera / doorbell: which playback endpoints answer, and with what.
The endpoint list below is a set of CANDIDATES (not confirmed): every one is tried and summarised in one line.

Usage (from the project folder):
    venv/bin/python diag_playback.py "Front door"
    venv/bin/python diag_playback.py "Front door" "GET /v1.0/devices/{id}/some/path" "POST /v1.0/devices/{id}/other {\"k\": 1}"

In extra probes {id}, {start} and {end} are replaced by the device id and the last 24 hours (unix seconds).
"""
import json
import re
import sys
import time

from backend.config import load_config

try:
    from tuya_connector import TuyaOpenAPI
except ImportError:
    sys.exit("tuya-connector-python is not installed (pip install -r requirements.txt)")

if len(sys.argv) < 2:
    sys.exit(__doc__)

config = load_config()
needle = sys.argv[1].lower()
devices = [d for d in config.tuya.devices if d.category == "sp" and (needle in d.name.lower() or needle == d.id.lower())]
if not devices:
    sys.exit(f"No configured camera matches '{sys.argv[1]}'")

cloud = config.tuya.cloud
if not (cloud.access_id and cloud.access_secret):
    sys.exit("No Tuya Cloud access_id / access_secret in config.yaml")

api = TuyaOpenAPI(endpoint=cloud.endpoint, access_id=cloud.access_id, access_secret=cloud.access_secret)
conn = api.connect()
print(f"connect(): success={conn.get('success') if isinstance(conn, dict) else conn}")

END = int(time.time())
START = END - 24 * 3600

CANDIDATES = [
    ("POST", "/v1.0/devices/{id}/stream/actions/allocate", {"type": "RTSP", "start_time": "{start}", "end_time": "{end}"}),
    ("POST", "/v1.0/devices/{id}/stream/actions/allocate", {"type": "HLS", "start_time": "{start}", "end_time": "{end}"}),
    ("POST", "/v1.0/devices/{id}/stream/actions/allocate", {"type": "PLAYBACK", "start_time": "{start}", "end_time": "{end}"}),
    ("GET", "/v1.0/devices/{id}/ipc/playback/dates", None),
    ("GET", "/v1.0/devices/{id}/sd-card/playback-days", None),
    ("GET", "/v1.0/devices/{id}/movement/records?start_time={start}&end_time={end}", None),
    ("GET", "/v1.0/devices/{id}/ipc/records?start_time={start}&end_time={end}", None),
    ("GET", "/v1.0/devices/{id}/storage/records?start_time={start}&end_time={end}", None),
]

extra = []
for spec in sys.argv[2:]:
    m = re.match(r"(GET|POST)\s+(\S+)\s*(.*)$", spec.strip(), re.S)
    if not m:
        sys.exit(f"Bad probe {spec!r}: expected 'GET /path' or 'POST /path {{json}}'")
    extra.append((m.group(1), m.group(2), json.loads(m.group(3)) if m.group(3).strip() else None))


def fill(value, dev):
    """Replaces {id}/{start}/{end} in a path or in a JSON body."""
    if isinstance(value, dict):
        return {k: fill(v, dev) for k, v in value.items()}
    if isinstance(value, str):
        return value.replace("{id}", dev.id).replace("{start}", str(START)).replace("{end}", str(END))
    return value


def hide_secrets(text):
    # Stream URLs carry credentials and signatures: keep only scheme and host
    return re.sub(r'(rtsps?|https?)://[^"\s]+', lambda m: m.group(1) + "://<hidden>", text)


for d in devices:
    print("=" * 70)
    print(f"{d.name}  id={d.id}")
    for method, path, body in CANDIDATES + extra:
        path = fill(path, d)
        body = fill(body, d)
        try:
            res = api.get(path) if method == "GET" else api.post(path, body)
        except Exception as e:
            res = f"EXCEPTION: {e}"
        if isinstance(res, dict):
            verdict = "OK " if res.get("success") else f"ERR code={res.get('code')} msg={res.get('msg')}"
            detail = json.dumps(res.get("result"), default=str) if res.get("success") else ""
        else:
            verdict, detail = str(res), ""
        shown = f"{method} {path}" + (f"  {json.dumps(body)}" if body else "")
        print(f"\n{verdict}  {shown}")
        if detail:
            print("   " + hide_secrets(detail)[:700])
    print()
