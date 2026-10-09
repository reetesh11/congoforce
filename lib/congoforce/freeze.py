"""The frozen set: acceptance tests plus the test config that could fake them.

Frozen at Gate 2. The PreToolUse hook blocks edits; this module stores hashes
so the helper can still catch a change made through Bash or while a hook
failed, before it accepts any pass.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .util import sha256_bytes

_SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__", ".congoforce"}


def glob_to_regex(pattern: str):
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    i, out = 0, ""
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


def matches_any(rel: str, globs) -> bool:
    rel = rel.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    return any(glob_to_regex(g).match(rel) for g in globs if g)


def _walk_files(wt: Path):
    for dirpath, dirnames, filenames in os.walk(wt):
        dirnames[:] = [d for d in dirnames if d not in _SKIP]
        for f in filenames:
            yield Path(dirpath, f).relative_to(wt).as_posix()


def extract_key(wt: Path, spec: str):
    """Text or JSON for a `file#key.path` spec; None when the file or key is absent."""
    rel, key = spec.split("#", 1)
    path = Path(wt) / rel
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    if rel.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        for part in key.split("."):
            if not isinstance(data, dict) or part not in data:
                return None
            data = data[part]
        return json.dumps(data, sort_keys=True)
    # TOML/INI: the text of the [section] up to the next header.
    m = re.search(r"^\[" + re.escape(key) + r"\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def compute(wt: Path, acceptance_files, globs, keys) -> dict:
    wt = Path(wt)
    files = {}
    for rel in acceptance_files:
        p = wt / rel
        files[rel] = sha256_bytes(p.read_bytes()) if p.exists() else "MISSING"
    for rel in _walk_files(wt):
        if rel not in files and matches_any(rel, globs):
            files[rel] = sha256_bytes((wt / rel).read_bytes())
    key_hashes = {}
    for spec in keys:
        val = extract_key(wt, spec)
        key_hashes[spec] = sha256_bytes(val.encode()) if val is not None else "ABSENT"
    return {"files": files, "keys": key_hashes, "globs": list(globs), "acceptance": list(acceptance_files)}


def check(wt: Path, frozen: dict) -> list:
    """Describe every change to the frozen set; empty list means intact."""
    wt = Path(wt)
    problems = []
    for rel, digest in frozen.get("files", {}).items():
        p = wt / rel
        now = sha256_bytes(p.read_bytes()) if p.exists() else "MISSING"
        if now != digest:
            problems.append(f"{rel}: {'deleted' if now == 'MISSING' else 'modified'}")
    known = set(frozen.get("files", {}))
    for rel in _walk_files(wt):
        if rel not in known and matches_any(rel, frozen.get("globs", [])):
            problems.append(f"{rel}: added (matches a frozen glob)")
    for spec, digest in frozen.get("keys", {}).items():
        val = extract_key(wt, spec)
        now = sha256_bytes(val.encode()) if val is not None else "ABSENT"
        if now != digest:
            problems.append(f"{spec}: changed")
    return problems


def is_frozen_path(rel: str, frozen: dict) -> bool:
    rel = rel.replace("\\", "/")
    if rel in frozen.get("files", {}):
        return True
    # Files that only have frozen *keys* (package.json, pyproject.toml) stay
    # editable: the implementer may add dependencies. The hash check guards the keys.
    return matches_any(rel, frozen.get("globs", []))
