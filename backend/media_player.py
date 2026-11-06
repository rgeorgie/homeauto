import os
import json
import logging
import asyncio
import subprocess
import shutil
import socket
from typing import Dict, Any, Optional, List
import yt_dlp
from backend.config import YouTubeAudioConfig

logger = logging.getLogger("HomeAuto.MediaPlayer")

MPV_IPC_SOCK = "/tmp/mpv-homeauto.sock"

class MediaPlayer:
    def __init__(self, config: YouTubeAudioConfig):
        self.config = config
        self.current_title: str = ""
        self.current_url: str = ""
        self.current_direct: bool = False
        self.is_playing: bool = False
        self.volume: int = self.config.volume
        self._mpv_process: Optional[subprocess.Popen] = None
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False
        }

    def _get_audio_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        uid = os.getuid()
        home = os.path.expanduser("~")
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
        env["PULSE_SERVER"] = f"unix:/run/user/{uid}/pulse/native"
        env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{uid}"
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
        cookie = os.path.join(home, ".config", "pulse", "cookie")
        if os.path.exists(cookie):
            env["PULSE_COOKIE"] = cookie
        
        # Ensure virtualenv bin (with yt-dlp) is at head of PATH
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        venv_bin = os.path.join(project_root, "venv", "bin")
        if os.path.exists(venv_bin):
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        return env

    def _send_ipc_command(self, command: List[Any]) -> bool:
        """Sends a JSON IPC command to the running MPV instance via unix socket."""
        if not os.path.exists(MPV_IPC_SOCK):
            return False
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(0.3)
            client.connect(MPV_IPC_SOCK)
            msg = json.dumps({"command": command}) + "\n"
            client.sendall(msg.encode("utf-8"))
            client.close()
            return True
        except Exception as e:
            logger.debug(f"MPV IPC send error: {e}")
            return False

    def reload_config(self, config: YouTubeAudioConfig):
        self.config = config
        self.volume = self.config.volume

    async def get_stream_url(self, youtube_url: str) -> Optional[Dict[str, str]]:
        """Resolves a YouTube URL to a direct audio stream URL and title."""
        def _extract():
            try:
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    info = ydl.extract_info(youtube_url, download=False)
                    if 'entries' in info: # Playlist
                        info = info['entries'][0]
                    stream_url = info.get('url')
                    title = info.get('title', 'YouTube Audio Stream')
                    return {"stream_url": stream_url, "title": title}
            except Exception as e:
                logger.error(f"Error extracting stream info from {youtube_url}: {e}")
                return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _extract)

    async def play(self, url_or_preset: str, title: Optional[str] = None, direct: bool = False) -> bool:
        """Plays a YouTube stream (or, with direct=True, a plain radio stream URL) via mpv with Pulse/PipeWire audio routing."""
        self.stop()
        
        # Check matching preset title if not provided
        stream_title = title
        if not stream_title:
            for p in self.config.preset_streams:
                if p.url == url_or_preset:
                    stream_title = p.title
                    break
        self.current_title = stream_title or "Ambient Audio Stream"
        self.current_url = url_or_preset
        self.current_direct = direct
        self.is_playing = True

        if shutil.which("mpv"):
            def _start_mpv():
                try:
                    env = self._get_audio_env()
                    if os.path.exists(MPV_IPC_SOCK):
                        try:
                            os.remove(MPV_IPC_SOCK)
                        except Exception:
                            pass

                    # Unmute sinks in pactl before playing
                    if shutil.which("pactl"):
                        try:
                            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True, env=env)
                            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{self.volume}%"], capture_output=True, env=env)
                            sinks_out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=2, env=env)
                            for line in sinks_out.stdout.splitlines():
                                if "bluez" in line:
                                    parts = line.split()
                                    if len(parts) >= 2:
                                        bt_sink = parts[1]
                                        subprocess.run(["pactl", "set-sink-mute", bt_sink, "0"], capture_output=True, env=env)
                                        subprocess.run(["pactl", "set-sink-volume", bt_sink, f"{self.volume}%"], capture_output=True, env=env)
                        except Exception:
                            pass

                    log_file = open("/tmp/mpv.log", "w")
                    play_url = url_or_preset.strip()
                    if not play_url.startswith("http://") and not play_url.startswith("https://") and not play_url.startswith("ytdl://") and not os.path.exists(play_url):
                        play_url = f"ytdl://ytsearch:{play_url}"

                    # Locate yt-dlp binary
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    venv_ytdl = os.path.join(project_root, "venv", "bin", "yt-dlp")
                    ytdl_bin = venv_ytdl if os.path.exists(venv_ytdl) else (shutil.which("yt-dlp") or shutil.which("youtube-dl"))

                    cmd = [
                        "mpv",
                        "--no-video",
                        "--ao=pulse,pipewire,alsa",
                        "--audio-client-name=HomeAuto",
                        f"--input-ipc-server={MPV_IPC_SOCK}",
                        f"--volume={self.volume}",
                        "--network-timeout=15",
                        "--ytdl=no" if direct else "--ytdl=yes",
                        "--ytdl-format=bestaudio/best"
                    ]
                    if ytdl_bin and not direct:
                        cmd.append(f"--script-opts=ytdl_hook-ytdl_path={ytdl_bin}")
                    cmd.append(play_url)
                    self._mpv_process = subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=log_file,
                        stderr=log_file
                    )
                    logger.info(f"Started mpv background audio playback for: {self.current_title}")
                except Exception as e:
                    logger.error(f"Failed to start mpv: {e}")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _start_mpv)
        
        return True

    def pause(self):
        """Toggles pause on active MPV playback."""
        if self._send_ipc_command(["cycle", "pause"]):
            self.is_playing = not self.is_playing
        else:
            self.stop()

    def stop(self):
        """Stops active MPV playback process."""
        self._send_ipc_command(["quit"])
        if self._mpv_process:
            try:
                self._mpv_process.terminate()
                self._mpv_process.wait(timeout=0.3)
            except Exception:
                try:
                    self._mpv_process.kill()
                except Exception:
                    pass
            self._mpv_process = None
        
        if os.path.exists(MPV_IPC_SOCK):
            try:
                os.remove(MPV_IPC_SOCK)
            except Exception:
                pass
        self.is_playing = False

    def set_volume(self, volume: int):
        """Updates volume on the fly via MPV IPC socket."""
        self.volume = max(0, min(100, volume))
        self._send_ipc_command(["set_property", "volume", self.volume])

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_playing": self.is_playing,
            "title": self.current_title,
            "url": self.current_url,
            "direct": self.current_direct,
            "volume": self.volume,
            "presets": [p.model_dump() for p in self.config.preset_streams]
        }
