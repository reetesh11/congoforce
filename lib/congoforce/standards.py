"""standards.md: human-readable conventions plus one machine-readable TOML block."""

from __future__ import annotations

import re
from pathlib import Path

from . import tomlish
from .util import CFError, read_json, sha256_file, now, write_json

COMMAND_KEYS = ["install", "lint", "typecheck", "build", "test", "test_files", "e2e", "ci"]


def extract_block(text: str) -> str:
    for m in re.finditer(r"```toml\s*\n(.*?)```", text, re.S):
        if "[commands]" in m.group(1):
            return m.group(1)
    return ""


def parse(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise CFError(f"{path} not found; run `congoforce init` first")
    text = path.read_text()
    block = extract_block(text)
    if not block:
        raise CFError(f"{path}: no ```toml block with [commands] under 'Commands (machine-readable)'")
    try:
        data = tomlish.loads(block)
    except tomlish.TomlError as exc:
        raise CFError(f"{path}: commands block: {exc}")
    commands = {k: (data.get("commands", {}).get(k) or "").strip() for k in COMMAND_KEYS}
    freeze = data.get("freeze", {})
    return {
        "preset": data.get("preset", {}).get("name", ""),
        "commands": commands,
        "package_dir": (data.get("paths", {}).get("package_dir") or ".").strip() or ".",
        "freeze_globs": list(freeze.get("globs", [])),
        "freeze_keys": list(freeze.get("keys", [])),
        "docs": _docs_list(text),
        "text": text,
    }


def _docs_list(text: str) -> list:
    from .util import md_section

    section = md_section(text, "Docs agents should read")
    docs = []
    for line in section.splitlines():
        m = re.match(r"^\s*[-*]\s+`?([^`\s]+)`?", line)
        if m and not m.group(1).startswith("("):
            docs.append(m.group(1))
    return docs


def is_approved(paths) -> bool:
    data = read_json(paths.standards_approval, None)
    return bool(data and data.get("approved"))


def approve(paths) -> dict:
    parse(paths.standards)  # refuse to approve a file the helper cannot read
    data = {"approved": True, "at": now(), "sha256": sha256_file(paths.standards)}
    write_json(paths.standards_approval, data)
    return data
