import logging
import asyncio
import subprocess
import shutil
from typing import Dict, Any, Optional, List
import yt_dlp
from backend.config import YouTubeAudioConfig

logger = logging.getLogger("HomeAuto.MediaPlayer")

class MediaPlayer:
    def __init__(self, config: YouTubeAudioConfig):
        self.config = config
        self.current_title: str = ""
        self.current_url: str = ""
        self.is_playing: bool = False
        self.volume: int = self.config.volume
        self._mpv_process: Optional[subprocess.Popen] = None
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False
        }

    async def get_stream_url(self, youtube_url: str) -> Optional[Dict[str, str]]:
        """Resolves a YouTube URL to a direct audio stream URL and title."""
        def _extract():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=False)
                    if 'entries' in info: # Playlist
                        info = info['entries'][0]
                    stream_url = info.get('url')
                    title = info.get('title', 'Unknown Stream')
                    return {"stream_url": stream_url, "title": title}
            except Exception as e:
                logger.error(f"Error extracting stream info from {youtube_url}: {e}")
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract)

    async def play(self, url_or_preset: str, title: Optional[str] = None) -> bool:
        """Plays YouTube stream via backend mpv player (if available) or prepares stream."""
        self.stop()
        
        info = await self.get_stream_url(url_or_preset)
        direct_url = info.get("stream_url") if info else url_or_preset
        self.current_title = title or (info.get("title") if info else url_or_preset)
        self.current_url = url_or_preset
        self.is_playing = True

        # Check if mpv is available on the Pi/system
        if shutil.which("mpv") and direct_url:
            def _start_mpv():
                try:
                    cmd = [
                        "mpv",
                        "--no-video",
                        f"--volume={self.volume}",
                        "--really-quiet",
                        direct_url
                    ]
                    self._mpv_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logger.info(f"Started mpv playback for: {self.current_title}")
                except Exception as e:
                    logger.error(f"Failed to start mpv: {e}")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _start_mpv)
        
        return True

    def pause(self):
        # Stop process or mark paused
        self.stop()
        self.is_playing = False

    def stop(self):
        if self._mpv_process:
            try:
                self._mpv_process.terminate()
                self._mpv_process.wait(timeout=2)
            except Exception:
                try:
                    self._mpv_process.kill()
                except Exception:
                    pass
            self._mpv_process = None
        self.is_playing = False

    def set_volume(self, volume: int):
        self.volume = max(0, min(100, volume))
        # Volume change will apply to next play or via pulse/alsa

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_playing": self.is_playing,
            "title": self.current_title,
            "url": self.current_url,
            "volume": self.volume,
            "presets": [p.model_dump() for p in self.config.preset_streams]
        }
