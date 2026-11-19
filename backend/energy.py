"""
Energy history: power readings of metering plugs / sockets, kept in a small SQLite file (data/energy.db).

One row per device per 5-minute bucket: the average watts of that bucket and the plug's own lifetime kWh counter at
the end of it. Usage over a period is taken from the counter when the device has one (accurate, survives restarts of
this app) and from the watts otherwise.
"""
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from backend.config import PROJECT_ROOT

logger = logging.getLogger("HomeAuto.Energy")

DB_FILE = os.path.join(PROJECT_ROOT, "data", "energy.db")
BUCKET_SECONDS = 300
KEEP_DAYS = 400

# range name -> (seconds covered, bucket size in seconds for the chart)
RANGES = {
    "day": (24 * 3600, 3600),
    "week": (7 * 24 * 3600, 6 * 3600),
    "month": (30 * 24 * 3600, 24 * 3600),
    "year": (365 * 24 * 3600, 30 * 24 * 3600),
}


class EnergyLog:
    def __init__(self, path: str = DB_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._pending: Dict[str, Dict[str, Any]] = {}  # dev_id -> running average of the current bucket
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS samples (
                ts INTEGER NOT NULL, dev_id TEXT NOT NULL, name TEXT, room TEXT,
                avg_w REAL NOT NULL, kwh_total REAL,
                PRIMARY KEY (ts, dev_id))""")
        self._last_prune = 0.0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    # ---------------- recording ----------------

    def record(self, states: Iterable[Dict[str, Any]], now: Optional[float] = None):
        """Called every few seconds with all device states. Averages per bucket, writes a row when a bucket ends."""
        now = now if now is not None else time.time()
        bucket = int(now // BUCKET_SECONDS) * BUCKET_SECONDS
        finished: List[tuple] = []
        with self._lock:
            for st in states:
                dev_id = st.get("id")
                watts = st.get("power_w")
                if not dev_id or watts is None or not st.get("online", True):
                    continue
                pend = self._pending.get(dev_id)
                if pend and pend["bucket"] != bucket:
                    finished.append(self._row(dev_id, pend))
                    pend = None
                if pend is None:
                    pend = self._pending[dev_id] = {"bucket": bucket, "sum": 0.0, "n": 0}
                pend["sum"] += float(watts)
                pend["n"] += 1
                pend["name"] = st.get("name")
                pend["room"] = st.get("room")
                if st.get("energy_kwh") is not None:
                    pend["kwh"] = float(st["energy_kwh"])
        if finished:
            self._write(finished)

    @staticmethod
    def _row(dev_id: str, pend: Dict[str, Any]) -> tuple:
        return (pend["bucket"], dev_id, pend.get("name"), pend.get("room"), pend["sum"] / max(1, pend["n"]), pend.get("kwh"))

    def flush(self):
        """Writes the unfinished buckets (shutdown)."""
        with self._lock:
            rows = [self._row(d, p) for d, p in self._pending.items() if p["n"]]
            self._pending.clear()
        if rows:
            self._write(rows)

    def _write(self, rows: List[tuple]):
        try:
            with self._connect() as db:
                db.executemany("INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?)", rows)
                if time.time() - self._last_prune > 86400:
                    db.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - KEEP_DAYS * 86400,))
                    self._last_prune = time.time()
        except Exception as e:
            logger.warning(f"Could not write energy history: {e}")

    # ---------------- reading ----------------

    def summary(self, range_name: str, now: Optional[float] = None) -> Dict[str, Any]:
        """Usage per chart bucket and per device for a range ('day', 'week', 'month', 'year')."""
        span, step = RANGES.get(range_name, RANGES["day"])
        now = now if now is not None else time.time()
        start = int((now - span) // step) * step
        with self._connect() as db:
            rows = db.execute(
                "SELECT ts, dev_id, name, room, avg_w, kwh_total FROM samples WHERE ts >= ? ORDER BY dev_id, ts",
                (start - BUCKET_SECONDS,)).fetchall()

        per_device: Dict[str, Dict[str, Any]] = {}
        buckets: Dict[int, float] = {}
        prev: Dict[str, tuple] = {}  # dev_id -> (ts, kwh_total) of the previous row
        for ts, dev_id, name, room, avg_w, kwh_total in rows:
            dev = per_device.setdefault(dev_id, {"id": dev_id, "name": name or dev_id, "room": room or "", "kwh": 0.0})
            dev["name"], dev["room"] = name or dev["name"], room or dev["room"]
            used = avg_w * BUCKET_SECONDS / 3600000.0  # watts over one bucket -> kWh
            p = prev.get(dev_id)
            if kwh_total is not None and p and p[1] is not None and 0 <= kwh_total - p[1] < 50:
                # the plug's own counter between two rows is exact (a reset makes it go down: then the watts are used)
                used = kwh_total - p[1]
            prev[dev_id] = (ts, kwh_total)
            if ts < start:
                continue
            dev["kwh"] += used
            b = int(ts // step) * step
            buckets[b] = buckets.get(b, 0.0) + used

        series = []
        t = start
        while t <= now:
            series.append({"ts": t, "kwh": round(buckets.get(t, 0.0), 4)})
            t += step
        devices = sorted(({**d, "kwh": round(d["kwh"], 3)} for d in per_device.values() if d["kwh"] > 0),
                         key=lambda d: -d["kwh"])
        return {"range": range_name, "step": step, "series": series, "devices": devices,
                "total_kwh": round(sum(d["kwh"] for d in devices), 3)}
