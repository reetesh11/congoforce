"""TOML loading that works on Python 3.9.

Uses tomllib when present (3.11+). Otherwise a small parser that covers what
CongoForce's own files use: tables, dotted table headers, strings, ints,
floats, booleans and (multi-line) arrays of those. It is not a general TOML
parser and does not need to be.
"""

from __future__ import annotations

import re
from typing import Any

try:  # pragma: no cover - depends on interpreter
    import tomllib as _tomllib  # type: ignore
except Exception:  # pragma: no cover
    _tomllib = None


class TomlError(ValueError):
    pass


def loads(text: str) -> dict:
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except Exception as exc:  # normalise the error type
            raise TomlError(str(exc)) from exc
    return _fallback_loads(text)


def _strip_comment(line: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


def _parse_value(raw: str, lineno: int) -> Any:
    raw = raw.strip()
    if raw.startswith('"'):
        if not raw.endswith('"') or len(raw) < 2:
            raise TomlError(f"line {lineno}: unterminated string")
        body = raw[1:-1]
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}
        return re.sub(r"\\(.)", lambda m: escapes.get(m.group(1), m.group(0)), body)
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise TomlError(f"line {lineno}: unterminated string")
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith("["):
        inner = raw[1:-1].strip() if raw.endswith("]") else None
        if inner is None:
            raise TomlError(f"line {lineno}: unterminated array")
        if not inner:
            return []
        return [_parse_value(item, lineno) for item in _split_array(inner)]
    if re.fullmatch(r"[+-]?\d[\d_]*", raw):
        return int(raw.replace("_", ""))
    if re.fullmatch(r"[+-]?\d[\d_]*\.\d+([eE][+-]?\d+)?", raw):
        return float(raw.replace("_", ""))
    raise TomlError(f"line {lineno}: unsupported value {raw!r}")


def _split_array(inner: str) -> list:
    items, cur, quote, depth = [], [], None, 0
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            if "".join(cur).strip():
                items.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        items.append("".join(cur).strip())
    return items


def _fallback_loads(text: str) -> dict:
    root: dict = {}
    table = root
    pending_key = None
    pending_buf: list = []
    pending_line = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        line = _strip_comment(line)
        if pending_key is not None:
            pending_buf.append(line)
            joined = " ".join(pending_buf)
            if joined.count("[") <= joined.count("]"):
                table[pending_key] = _parse_value(joined, pending_line)
                pending_key = None
            continue
        if not line:
            continue
        m = re.fullmatch(r"\[\s*([A-Za-z0-9_.\-\"]+)\s*\]", line)
        if m:
            table = root
            for part in m.group(1).split("."):
                part = part.strip('"')
                table = table.setdefault(part, {})
            continue
        m = re.fullmatch(r"([A-Za-z0-9_\-\"]+)\s*=\s*(.+)", line)
        if not m:
            raise TomlError(f"line {lineno}: cannot parse {line!r}")
        key, value = m.group(1).strip('"'), m.group(2).strip()
        if value.startswith("[") and value.count("[") > value.count("]"):
            pending_key, pending_buf, pending_line = key, [value], lineno
            continue
        table[key] = _parse_value(value, lineno)
    if pending_key is not None:
        raise TomlError(f"line {pending_line}: unterminated array")
    return root


def dumps_value(value: Any) -> str:
    """Render one value as TOML (used when writing config files)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(dumps_value(v) for v in value) + "]"
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'
