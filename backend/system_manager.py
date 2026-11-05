import os
import psutil
import subprocess
import socket
import logging
from typing import Dict, Any

logger = logging.getLogger("HomeAuto.System")

class SystemManager:
    @staticmethod
    def get_cpu_temp() -> float:
        """Reads CPU temperature on Raspberry Pi OS."""
        # Method 1: /sys/class/thermal/thermal_zone0/temp
        try:
            thermal_path = "/sys/class/thermal/thermal_zone0/temp"
            if os.path.exists(thermal_path):
                with open(thermal_path, "r") as f:
                    temp_millideg = int(f.read().strip())
                    return round(temp_millideg / 1000.0, 1)
        except Exception:
            pass

        # Method 2: vcgencmd measure_temp (Raspberry Pi specific)
        try:
            res = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                # Output format: temp=48.2'C
                parts = res.stdout.strip().replace("temp=", "").replace("'C", "")
                return float(parts)
        except Exception:
            pass

        # Method 3: psutil sensors
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return round(entries[0].current, 1)
        except Exception:
            pass

        return 42.0 # Default mock/safe fallback if non-pi or simulated

    @staticmethod
    def get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    @classmethod
    def get_telemetry(cls) -> Dict[str, Any]:
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        return {
            "cpu_percent": round(cpu_pct, 1),
            "cpu_temp": cls.get_cpu_temp(),
            "memory_percent": round(mem.percent, 1),
            "memory_used_mb": round(mem.used / (1024 * 1024), 1),
            "memory_total_mb": round(mem.total / (1024 * 1024), 1),
            "disk_percent": round(disk.percent, 1),
            "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 1),
            "local_ip": cls.get_local_ip()
        }

    @staticmethod
    def set_display_power(turn_on: bool) -> bool:
        """Controls HDMI / DSI Touchscreen power state."""
        val = "1" if turn_on else "0"
        try:
            # Try vcgencmd display_power (Raspberry Pi HDMI/Touchscreen)
            subprocess.run(["vcgencmd", "display_power", val], capture_output=True, timeout=2)
            # Try xset dpms
            dpms_arg = "on" if turn_on else "off"
            subprocess.run(["xset", "dpms", "force", dpms_arg], capture_output=True, timeout=2)
            return True
        except Exception as e:
            logger.error(f"Error toggling display power: {e}")
            return False
