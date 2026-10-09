"""Small shared helpers: time, JSON files, slugs, errors."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class CFError(Exception):
    """An error the helper reports to the orchestrator as a one-line message."""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomic write so a crash never leaves half a state file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "task"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def parse_frontmatter(text: str) -> tuple:
    """Return (dict, body) for a `---` YAML-ish frontmatter of simple key: value lines."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    meta = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1 :])
        m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if m:
            value = re.sub(r"\s+#.*$", "", m.group(2))  # allow `class: bug  # comment`
            meta[m.group(1).lower()] = value.strip().strip('"').strip("'")
    return {}, text


def md_section(text: str, heading: str) -> str:
    """Body of the first `## heading` section (case-insensitive prefix match), '' if absent."""
    lines = text.splitlines()
    out = []
    inside = False
    level = 0
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if inside and len(m.group(1)) <= level:
                break
            if not inside and m.group(2).strip().lower().startswith(heading.lower()):
                inside = True
                level = len(m.group(1))
                continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def tail(text: str, lines: int = 60) -> str:
    parts = text.splitlines()
    return "\n".join(parts[-lines:])
