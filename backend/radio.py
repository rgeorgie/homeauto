"""Online radio station directory (radio-browser.info), used by the Radio card on the media page."""
import os
import json
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List

import requests

logger = logging.getLogger("HomeAuto.Radio")

# radio-browser.info API hosts, tried in order ("all" is their round-robin name for every live server)
SERVERS = ["de1.api.radio-browser.info", "all.api.radio-browser.info"]
CACHE_SECONDS = 3600
_cache: Dict[tuple, tuple] = {}
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="radio")


def search_stations(country: str = "BG", query: str = "", limit: int = 150) -> List[Dict[str, Any]]:
    """Working stations of a country (most popular first), optionally filtered by name. Cached for an hour."""
    key = (country.upper(), query.strip().lower(), limit)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    params = {"countrycode": country.upper(), "hidebroken": "true", "order": "votes", "reverse": "true", "limit": limit}
    if query.strip():
        params["name"] = query.strip()

    last_error = None
    for host in SERVERS:
        try:
            res = requests.get(f"https://{host}/json/stations/search", params=params, timeout=(4, 8),
                               headers={"User-Agent": "HomeAuto/1.0"})
            res.raise_for_status()
            stations = []
            seen = set()
            for s in res.json():
                url = s.get("url_resolved") or s.get("url")
                name = (s.get("name") or "").strip()
                if not url or not name or url in seen:
                    continue
                seen.add(url)
                stations.append({"name": name, "url": url, "codec": s.get("codec", ""), "bitrate": s.get("bitrate", 0)})
            _cache[key] = (time.time(), stations)
            return stations
        except Exception as e:
            last_error = e
            logger.warning(f"Radio directory {host} failed: {e}")
    if hit:  # directory unreachable: an old list is better than none
        return hit[1]
    raise RuntimeError(f"Radio directory unavailable: {last_error}")


# ----- Favourites (kept in their own file so admin config saves never overwrite them) -----

FAVORITES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "radio_favorites.json")
_fav_lock = threading.Lock()


def get_favorites() -> List[Dict[str, str]]:
    try:
        with open(FAVORITES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [{"name": s["name"], "url": s["url"]} for s in data if isinstance(s, dict) and s.get("name") and s.get("url")]
    except (OSError, ValueError, TypeError):
        return []


def _save_favorites(favs: List[Dict[str, str]]):
    tmp = FAVORITES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(favs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FAVORITES_PATH)


def add_favorite(name: str, url: str) -> List[Dict[str, str]]:
    with _fav_lock:
        favs = get_favorites()
        if not any(f["url"] == url for f in favs):
            favs.append({"name": name, "url": url})
            _save_favorites(favs)
        return favs


def remove_favorite(url: str) -> List[Dict[str, str]]:
    with _fav_lock:
        favs = [f for f in get_favorites() if f["url"] != url]
        _save_favorites(favs)
        return favs
