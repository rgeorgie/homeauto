import os
import glob
import logging
from typing import List, Dict, Any
from backend.config import ScreensaverConfig

logger = logging.getLogger("HomeAuto.Screensaver")

# Curated high-res ambient backgrounds (Nature, Architecture, Minimal, SciFi)
DEFAULT_AMBIENT_WALLPAPERS = [
    "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1511447333015-45b65e60f6d5?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1518495973542-4542c06a5843?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1920&q=80",
    "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=1920&q=80"
]

class ScreensaverManager:
    def __init__(self, config: ScreensaverConfig):
        self.config = config

    def reload_config(self, config: ScreensaverConfig):
        self.config = config

    def get_photos(self) -> List[str]:
        """Returns list of photo paths / URLs for the slideshow."""
        photos = []
        photo_dir = self.config.photo_directory
        if os.path.exists(photo_dir):
            valid_exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif")
            for ext in valid_exts:
                found = glob.glob(os.path.join(photo_dir, ext))
                # Convert to web-accessible URLs
                for p in found:
                    rel_path = os.path.relpath(p, start="frontend")
                    photos.append(f"/{rel_path}")

        if not photos and self.config.use_unsplash_random:
            photos = DEFAULT_AMBIENT_WALLPAPERS

        return photos

    def get_settings(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "idle_timeout_seconds": self.config.idle_timeout_seconds,
            "photo_transition_seconds": self.config.photo_transition_seconds,
            "widgets": self.config.widgets.model_dump(),
            "youtube_audio": self.config.youtube_audio.model_dump(),
            "photos": self.get_photos()
        }
