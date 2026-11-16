"""
version: 1.0.0
This module keeps per-mod source metadata (Steam time_updated, cache released flag)
and decides which mods to download and which cached directories to release
"""
import json
import logging
import os
import shutil
from typing import Dict, Iterable, List, Set, Tuple

logger = logging.getLogger("mod_state")

State = Dict[str, Dict]


def load_state(path: str) -> State:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: State) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)  # atomic so an interrupted run never leaves a truncated file


def local_file(mod_path: str):
    """Return the file whose mtime marks the cached content, or None if the cache is absent."""
    for parts in (("workshop_data.json",), ("Localizations", "enUS.csv")):
        p = os.path.join(mod_path, *parts)
        if os.path.exists(p):
            return p
    return None


def bootstrap_state(state: State, mod_path_of, mod_ids: Iterable[str]) -> None:
    """Seed missing entries from the local file mtime; mods without local files stay unseeded."""
    for mod_id in mod_ids:
        if mod_id in state:
            continue
        f = local_file(mod_path_of(mod_id))
        if f:
            state[mod_id] = {"time_updated": int(os.path.getmtime(f)), "released": False}


def select_downloads(tracked: Iterable[str], local_ids: Set[str], state: State,
                     steam_times: Dict[str, int], now: float, days: int) -> List[Tuple[str, str]]:
    """Return (mod_id, reason) for every tracked mod that must be downloaded."""
    result = []
    for mod_id in tracked:
        entry = state.get(mod_id)
        if mod_id not in local_ids and not (entry and entry["released"]):
            result.append((mod_id, "missing"))
            continue
        steam_time = steam_times.get(mod_id)
        if steam_time is None or entry is None:
            continue
        within_window = days <= 0 or (now - steam_time) < days * 86400
        if steam_time > entry["time_updated"] and within_window:
            result.append((mod_id, "updated"))
    return result


def select_releases(cache_ids: Iterable[str], state: State, steam_times: Dict[str, int],
                    tracked: Set[str], data_ok: Set[str], downloaded: Set[str],
                    now: float, release_days: int) -> List[str]:
    """Return cached mod ids whose directory can be removed."""
    if release_days <= 0:
        return []
    result = []
    for mod_id in cache_ids:
        entry = state.get(mod_id)
        if entry is None or mod_id in downloaded:
            continue
        last_update = steam_times.get(mod_id, entry["time_updated"])
        if now - last_update <= release_days * 86400:
            continue
        if mod_id in tracked and mod_id not in data_ok:
            continue
        result.append(mod_id)
    return result


def _dir_size(path: str) -> int:
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)


def release_mods(cache_root: str, mod_ids: Iterable[str], state: State) -> Tuple[int, int]:
    """Remove the cached directories and mark them released. Returns (count, freed bytes)."""
    count = freed = 0
    for mod_id in mod_ids:
        path = os.path.join(cache_root, mod_id)
        try:
            size = _dir_size(path)
            shutil.rmtree(path)
        except OSError as e:
            logger.warning(f"Mod {mod_id}: cache release failed: {e}")
            continue
        state[mod_id]["released"] = True
        count += 1
        freed += size
        logger.info(f"Mod {mod_id}: cache released ({size} bytes)")
    return count, freed
