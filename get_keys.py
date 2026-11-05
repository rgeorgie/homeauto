#!/usr/bin/env python3
"""
Direct Tuya Key Extractor & Config Generator
Queries Tuya Cloud with your credentials and writes all 38 devices + local keys to config.yaml
"""

import sys
import yaml
import tinytuya

def fetch_and_save_keys():
    # Load config
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        with open("config.example.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    tuya_cfg = cfg.get("tuya", {})
    cloud_cfg = tuya_cfg.get("cloud", {})

    access_id = cloud_cfg.get("access_id", "").strip()
    access_secret = cloud_cfg.get("access_secret", "").strip()
    endpoint = cloud_cfg.get("endpoint", "https://openapi.tuyaeu.com").strip()
    uid = cloud_cfg.get("user_id", "").strip()

    print(f"Connecting to Tuya Cloud with Access ID: {access_id[:6]}... Region: {endpoint}")

    region = "eu"
    if "tuyaus" in endpoint or "us" in endpoint:
        region = "us"
    elif "tuyacn" in endpoint or "cn" in endpoint:
        region = "cn"
    elif "tuyain" in endpoint or "in" in endpoint:
        region = "in"

    c = tinytuya.Cloud(
        apiRegion=region,
        apiKey=access_id,
        apiSecret=access_secret
    )

    devices_list = []

    # 1. Try UID query if provided
    if uid:
        print(f"Querying devices for UID: {uid}...")
        try:
            res = c.cloudrequest(f"/v1.0/users/{uid}/devices")
            if res and res.get("success"):
                r = res.get("result")
                if isinstance(r, list):
                    devices_list = r
                elif isinstance(r, dict):
                    devices_list = r.get("devices", r.get("list", []))
                print(f"Found {len(devices_list)} devices via UID endpoint!")
            else:
                print(f"UID query returned: {res}")
        except Exception as e:
            print(f"UID query exception: {e}")

    # 2. Try c.getdevices()
    if not devices_list:
        print("Querying via tinytuya.Cloud.getdevices()...")
        try:
            c_devs = c.getdevices()
            if isinstance(c_devs, list) and len(c_devs) > 0:
                devices_list = c_devs
                print(f"Found {len(devices_list)} devices via getdevices()!")
            else:
                print(f"getdevices returned: {c_devs}")
        except Exception as e:
            print(f"getdevices exception: {e}")

    # 3. Format and update config.yaml
    if devices_list:
        print(f"\nSuccessfully retrieved {len(devices_list)} devices with local keys from Tuya Cloud:")
        saved_devices = []
        for d in devices_list:
            if not isinstance(d, dict):
                continue
            dev_id = d.get("id")
            name = d.get("name") or f"Device {dev_id[-4:]}"
            key = d.get("key") or d.get("local_key") or ""
            ip = d.get("ip") or ""
            category = d.get("category", "")
            
            dev_type = "switch"
            if category in ["dj", "dd", "dc", "xdd"]:
                dev_type = "light"
            elif category in ["cz", "pc"]:
                dev_type = "socket"
            elif category in ["wk"]:
                dev_type = "climate"

            print(f"  • {name} | ID: {dev_id} | Key: {'*' * 12 + key[-4:] if key else 'NO KEY'} | Type: {dev_type}")

            saved_devices.append({
                "id": dev_id,
                "name": name,
                "ip": ip,
                "local_key": key,
                "version": 3.4 if d.get("version") == "3.4" else 3.3,
                "type": dev_type,
                "category": category or "cz",
                "room": "Living Room"
            })

        cfg["tuya"]["devices"] = saved_devices
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
        print("\n🎉 Saved all devices and local keys to config.yaml successfully!")
    else:
        print("\n⚠️ No devices could be fetched. Please verify your Access ID, Secret, and ensure Smart Home Device System API is authorized.")

if __name__ == "__main__":
    fetch_and_save_keys()
