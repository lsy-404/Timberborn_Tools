"""
version: 1.0.0
This module recognises mods that carry no strings of their own to translate
"""
import csv
import os
import re
from typing import Iterable, Optional, Set

import toml

LOCALE_PREFIX = re.compile(r"^([a-z]{2}[A-Z]{2})")
BUILTIN_SHARE = 0.5
FOREIGN_ROW_RATIO = 5


def load_protected_ids(repo_path: str) -> Set[str]:
    """Built-in game string IDs listed by the data repository; empty when it is unavailable."""
    try:
        build = toml.load(os.path.join(repo_path, ".github", "config", "config.toml")).get("build", {})
        ids = set(build.get("extra_protect_string_ids", []))
        raw = os.path.join(repo_path, ".github", "data", "raw", build["protect_string_ids_file"])
        with open(raw, "r", encoding="utf-8-sig", newline="") as f:
            ids.update(row[0] for row in csv.reader(f) if row)
        return ids
    except (OSError, KeyError, toml.TomlDecodeError):
        return set()


def _ids(path: str) -> Set[str]:
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = csv.reader(f)
        next(rows, None)
        return {row[0] for row in rows if row}


def _rows_by_locale(mod_path: str) -> dict:
    rows = {}
    for root, _, files in os.walk(mod_path):
        for name in files:
            match = LOCALE_PREFIX.match(name)
            if match and name.endswith((".csv", ".txt")):
                rows[match.group(1)] = rows.get(match.group(1), 0) + len(_ids(os.path.join(root, name)))
    return rows


def translation_pack_reason(mod_path: str, source_files: Iterable[str],
                            protected_ids: Set[str]) -> Optional[str]:
    """Explain why the mod has no strings of its own to translate, or return None."""
    source_ids = set()
    for path in source_files:
        source_ids |= _ids(path)
    if source_ids and len(source_ids & protected_ids) >= BUILTIN_SHARE * len(source_ids):
        return "its strings are built-in game IDs"
    rows = _rows_by_locale(mod_path)
    english = rows.pop("enUS", 0)
    if english and rows and max(rows.values()) >= FOREIGN_ROW_RATIO * english:
        return "it mostly carries another language"
    return None
