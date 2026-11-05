import os
import yaml
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class CloudConfig(BaseModel):
    access_id: str = ""
    access_secret: str = ""
    endpoint: str = "https://openapi.tuyaeu.com"
    user_id: str = ""

class TuyaDeviceConfig(BaseModel):
    id: str
    name: str
    ip: Optional[str] = None
    local_key: Optional[str] = None
    version: float = 3.3
    type: str = "switch" # switch, light, socket, sensor, climate
    category: str = "cz"
    room: str = "Default"
    home: str = "" # Tuya home name (filled by cloud sync)

class TuyaConfig(BaseModel):
    mode: str = "local" # local, cloud, both
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    devices: List[TuyaDeviceConfig] = Field(default_factory=list)

class BluetoothAudioConfig(BaseModel):
    enabled: bool = True
    target_mac: str = ""
    device_name: str = "Surround Sound"
    auto_reconnect: bool = True
    reconnect_interval_seconds: int = 15
    default_volume: int = 70

class KodiConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8088
    user: str = "kodi"
    password: str = ""
    launch_command: str = "kodi-standalone"
    auto_switch_display: bool = True

class YouTubeAudioPreset(BaseModel):
    title: str
    url: str

class YouTubeAudioConfig(BaseModel):
    enabled: bool = True
    auto_play_on_screensaver: bool = False
    volume: int = 50
    preset_streams: List[YouTubeAudioPreset] = Field(default_factory=list)

class ScreensaverWidgetsConfig(BaseModel):
    show_clock: bool = True
    show_weather: bool = True
    show_device_summaries: bool = True
    show_system_telemetry: bool = True

class ScreensaverConfig(BaseModel):
    enabled: bool = True
    idle_timeout_seconds: int = 120
    photo_transition_seconds: int = 15
    photo_directory: str = "./frontend/assets/photos"
    use_unsplash_random: bool = True
    youtube_audio: YouTubeAudioConfig = Field(default_factory=YouTubeAudioConfig)
    widgets: ScreensaverWidgetsConfig = Field(default_factory=ScreensaverWidgetsConfig)

class WeatherConfig(BaseModel):
    latitude: float = 51.5074
    longitude: float = -0.1278
    units: str = "celsius"

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 80
    debug: bool = False

class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tuya: TuyaConfig = Field(default_factory=TuyaConfig)
    bluetooth_audio: BluetoothAudioConfig = Field(default_factory=BluetoothAudioConfig)
    kodi: KodiConfig = Field(default_factory=KodiConfig)
    screensaver: ScreensaverConfig = Field(default_factory=ScreensaverConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")
EXAMPLE_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.example.yaml")

def load_config(config_path: Optional[str] = None) -> AppConfig:
    target_path = config_path or DEFAULT_CONFIG_PATH
    if not os.path.exists(target_path):
        if os.path.exists(EXAMPLE_CONFIG_PATH):
            target_path = EXAMPLE_CONFIG_PATH
        else:
            return AppConfig()
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return AppConfig(**data)
    except Exception:
        return AppConfig()

def save_config(config: AppConfig, config_path: Optional[str] = None):
    target_path = config_path or DEFAULT_CONFIG_PATH
    data = config.model_dump()
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
