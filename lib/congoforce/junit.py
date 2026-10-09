"""JUnit XML: the one report format every preset produces.

pytest (`--junitxml`, xunit1 adds file paths), vitest (`--reporter=junit`) and
jest (`jest-junit`) all write it, so matching tests to files, collection
checks and failure signatures are written once.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


class Case:
    __slots__ = ("name", "classname", "file", "suite", "status", "message")

    def __init__(self, name, classname, file, suite, status, message):
        self.name = name
        self.classname = classname
        self.file = file
        self.suite = suite
        self.status = status  # passed | failed | error | skipped
        self.message = message

    @property
    def id(self) -> str:
        where = self.file or self.classname or self.suite
        return f"{where}::{self.name}"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "file": self.file, "classname": self.classname,
                "suite": self.suite, "status": self.status, "message": self.message}


def parse(path) -> list:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        tree = ET.parse(str(path))
    except ET.ParseError:
        return []
    cases = []
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    seen = set()
    for suite in suites:
        suite_name = suite.get("name", "") or ""
        suite_file = suite.get("file", "") or ""
        for tc in suite.findall("testcase"):
            if id(tc) in seen:
                continue
            seen.add(id(tc))
            status, message = "passed", ""
            for tag in ("failure", "error"):
                el = tc.find(tag)
                if el is not None:
                    status = "failed" if tag == "failure" else "error"
                    # First line = the short message (used for signatures);
                    # the rest = details (used to judge *why* a test is red).
                    head = (el.get("message") or "").strip()
                    body = (el.text or "").strip()
                    message = (head + ("\n" + body[:4000] if body else "")) if head else body[:4000]
                    break
            if status == "passed":
                sk = tc.find("skipped")
                if sk is not None:
                    status = "skipped"
                    message = (sk.get("message") or "").strip()
            cases.append(Case(
                name=tc.get("name", "") or "",
                classname=tc.get("classname", "") or "",
                file=(tc.get("file") or suite_file or "").replace("\\", "/"),
                suite=suite_name,
                status=status,
                message=message,
            ))
    return cases


def _parts(path: str) -> list:
    p = path.replace("\\", "/").strip("/")
    p = re.sub(r"\.(py|[cm]?[jt]sx?)$", "", p)
    return [x for x in p.split("/") if x and x != "."]


def _suffix_match(a: list, b: list) -> bool:
    if not a or not b:
        return False
    n = min(len(a), len(b))
    return a[-n:] == b[-n:]


def case_matches_file(case: Case, rel_file: str) -> bool:
    """Does this testcase come from the given repo-relative test file?"""
    target = _parts(rel_file)
    for cand in (case.file, case.suite if "/" in case.suite or "." in case.suite else "", case.classname if "/" in case.classname else ""):
        if cand and ("/" in cand or cand.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"))):
            if _suffix_match(_parts(cand), target):
                return True
    # pytest xunit2-style dotted classname: tests.acceptance.test_x[.TestClass]
    if case.classname and "/" not in case.classname:
        dotted = case.classname.split(".")
        module = target[-1] if target else ""
        if module in dotted:
            idx = dotted.index(module)
            if _suffix_match(dotted[: idx + 1], target):
                return True
    # pytest collection errors: name is the dotted module path, classname empty
    if not case.classname and case.name:
        dotted = case.name.split(".")
        if dotted and _suffix_match(dotted, target):
            return True
    return False


_NORMALISERS = [
    (re.compile(r"0x[0-9a-fA-F]+"), "0x?"),
    (re.compile(r"\b\d+(\.\d+)?\s?(ms|s|sec|seconds)\b"), "<t>"),
    (re.compile(r"(/private)?/(tmp|var/folders)/[^\s'\":]+"), "<tmp>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\":]+|/(Users|home)/[^\s'\":]+"), "<path>"),
    (re.compile(r":\d+(:\d+)?\b"), ":<n>"),
    (re.compile(r"\s+"), " "),
]


def normalise(message: str) -> str:
    msg = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    for rx, rep in _NORMALISERS:
        msg = rx.sub(rep, msg)
    return msg.strip()[:240]


def signature(case: Case) -> str:
    return f"test:{case.id}|{normalise(case.message)}"


def summarise(cases: list) -> dict:
    out = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for c in cases:
        out[c.status] = out.get(c.status, 0) + 1
    out["total"] = len(cases)
    return out
