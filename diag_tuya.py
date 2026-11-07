#!/usr/bin/env python3
"""
Shows exactly what Tuya Cloud returns for a device, to find out why it never reports state.

Usage (from the project folder):
    venv/bin/python diag_tuya.py window          # every configured device whose name contains "window"
    venv/bin/python diag_tuya.py <device_id>
"""
import json
import re
import sys

from backend.config import load_config

try:
    from tuya_connector import TuyaOpenAPI
except ImportError:
    sys.exit("tuya-connector-python is not installed (pip install -r requirements.txt)")

if len(sys.argv) < 2:
    sys.exit(__doc__)

config = load_config()
needle = sys.argv[1].lower()
devices = [d for d in config.tuya.devices if needle in d.name.lower() or needle == d.id.lower()]
if not devices:
    sys.exit(f"No configured device matches '{sys.argv[1]}'")

cloud = config.tuya.cloud
if not (cloud.access_id and cloud.access_secret):
    sys.exit("No Tuya Cloud access_id / access_secret in config.yaml")

api = TuyaOpenAPI(endpoint=cloud.endpoint, access_id=cloud.access_id, access_secret=cloud.access_secret)
print(f"Cloud endpoint: {cloud.endpoint}")
conn = api.connect()
print(f"connect(): success={conn.get('success') if isinstance(conn, dict) else conn}\n")

for d in devices:
    print("=" * 70)
    print(f"{d.name}  id={d.id}  category={d.category!r}  type={d.type!r}  ip={d.ip!r}  key={'yes' if d.local_key else 'NO'}")
    for title, path in (
        ("device info", f"/v1.0/devices/{d.id}"),
        ("status", f"/v1.0/devices/{d.id}/status"),
        ("specifications", f"/v1.0/devices/{d.id}/specifications"),
        ("thing-model properties", f"/v2.0/cloud/thing/{d.id}/shadow/properties"),
        ("thing model", f"/v2.0/cloud/thing/{d.id}/model"),
    ):
        try:
            res = api.get(path)
        except Exception as e:
            res = f"EXCEPTION: {e}"
        text = json.dumps(res, default=str, indent=1) if not isinstance(res, str) else res
        text = re.sub(r'("local_key":\s*)"[^"]*"', r'\1"<hidden>"', text)  # never print the device key
        print(f"\n--- {title}  GET {path}\n{text[:1800]}")
    if d.category == "sp":
        # Live view needs Tuya to allocate a stream URL: show what each stream type answers
        path = f"/v1.0/devices/{d.id}/stream/actions/allocate"
        for kind in ("hls", "HLS", "rtsp", "RTSP"):
            try:
                res = api.post(path, {"type": kind})
            except Exception as e:
                res = f"EXCEPTION: {e}"
            text = json.dumps(res, default=str) if not isinstance(res, str) else res
            print(f"\n--- live stream  POST {path}  type={kind}\n{text[:600]}")
    print()
