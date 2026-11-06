#!/usr/bin/env python3
"""
Listens to Tuya's message service and prints every pushed message (secrets redacted),
to see what a doorbell ring, a window opening or a motion alert really looks like.

Usage (from the project folder):
    venv/bin/python diag_pulsar.py            # listen for 120 seconds
    venv/bin/python diag_pulsar.py 300        # listen for 300 seconds

Then ring the doorbell, open a window, walk past the camera. Needs the "Message Service"
to be enabled for the project on iot.tuya.com; stop the HomeAuto service first if it already
listens (two consumers on one project compete for the messages).
"""
import json
import re
import sys
import time

from backend.config import load_config
from backend.tuya_manager import pulsar_ws_endpoint

try:
    from tuya_connector import TuyaCloudPulsarTopic, TuyaOpenPulsar
except ImportError:
    sys.exit("tuya-connector-python is not installed (pip install -r requirements.txt)")

seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 120
cloud = load_config().tuya.cloud
if not (cloud.access_id and cloud.access_secret):
    sys.exit("No Tuya Cloud access_id / access_secret in config.yaml")

names = {d.id: d.name for d in load_config().tuya.devices}
SECRET = re.compile(r'("(?:local_key|token|access_token|refresh_token)"\s*:\s*)"[^"]*"')


def on_message(text: str):
    try:
        data = json.loads(text)
    except ValueError:
        print(f"[{time.strftime('%H:%M:%S')}] (not JSON) {text[:300]}")
        return
    dev = data.get("devId") or (data.get("data") or {}).get("devId") or ""
    out = SECRET.sub(r'\1"<hidden>"', json.dumps(data, ensure_ascii=False))
    print(f"[{time.strftime('%H:%M:%S')}] {names.get(dev, dev)}: {out[:1500]}", flush=True)


endpoint = pulsar_ws_endpoint(cloud.endpoint)
print(f"Connecting to {endpoint} (topic {TuyaCloudPulsarTopic.PROD}) for {seconds}s ...")
client = TuyaOpenPulsar(cloud.access_id, cloud.access_secret, endpoint, TuyaCloudPulsarTopic.PROD)
client.add_message_listener(on_message)
client.start()
try:
    time.sleep(seconds)
except KeyboardInterrupt:
    pass
client.stop()
print("Done.")
