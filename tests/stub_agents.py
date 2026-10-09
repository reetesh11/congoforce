"""Stand-ins for the six agents: they write exactly what each stage must produce."""

import json
import subprocess
from pathlib import Path

REQ = """---
class: task
size: small
title: Add word_count to textkit
---
# Requirements — Add word_count to textkit

## Problem
Callers need a word count for short texts.

## Requirements
- R1. When given text, the system shall return the number of whitespace-separated words.

## Acceptance criteria
- AC-1: `word_count("hello big world")` returns 3.
- AC-2: tokens made only of punctuation ("-", "...") are not counted.
- AC-3: empty or whitespace-only text returns 0.
- AC-4: `title_case` keeps working as before.

## Out of scope
- Unicode word segmentation.

## Open questions
- none
"""

TECH = """# Tech spec

## Interface contract
- `textkit.word_count(text: str) -> int`, exported from the `textkit` package.

## Tasks
1. Add `textkit/words.py` with `word_count`.
2. Export `word_count` from `textkit/__init__.py`.

## Implementation tests
- Unit tests in tests/test_words.py.

## Open questions
- none
"""

TEST_FILE = '''from textkit import word_count


def test_counts_words():
    assert word_count("hello big world") == 3


def test_ignores_punctuation_tokens():
    assert word_count("wait - what ...") == 2


def test_empty_is_zero():
    assert word_count("   ") == 0
'''

UNCHANGED_FILE = '''from textkit import title_case


def test_title_case_unchanged():
    assert title_case("hello world") == "Hello World"
'''

IMPL = '''"""Word helpers."""

import re


def word_count(text: str) -> int:
    """Number of whitespace-separated words that contain a letter or digit."""
    return sum(1 for tok in text.split() if re.search(r"\\w", tok))
'''


def requirements(task_dir: Path, wt: Path):
    (task_dir / "req.md").write_text(REQ)


def tech_spec(task_dir: Path, wt: Path):
    (task_dir / "tech.md").write_text(TECH)


def test_author(task_dir: Path, wt: Path, early_pass=False):
    acc = wt / "tests" / "acceptance"
    acc.mkdir(parents=True, exist_ok=True)
    body = TEST_FILE
    if early_pass:
        body = "def test_counts_words():\n    assert True\n\ndef test_ignores_punctuation_tokens():\n    assert True\n\ndef test_empty_is_zero():\n    assert True\n"
    (acc / "test_word_count.py").write_text(body)
    (acc / "test_unchanged.py").write_text(UNCHANGED_FILE)
    tests = {"acceptance": [
        {"criterion": "AC-1", "file": "tests/acceptance/test_word_count.py", "tests": 3, "description": "counts"},
        {"criterion": "AC-2", "file": "tests/acceptance/test_word_count.py", "tests": 3, "description": "punctuation"},
        {"criterion": "AC-3", "file": "tests/acceptance/test_word_count.py", "tests": 3, "description": "empty"},
        {"criterion": "AC-4", "file": "tests/acceptance/test_unchanged.py", "tests": 1, "expect_red": False, "description": "unchanged"},
    ]}
    (task_dir / "tests.json").write_text(json.dumps(tests, indent=2))
    (task_dir / "test.md").write_text("# Test plan\n\n- AC-1..3 in test_word_count.py\n- AC-4 in test_unchanged.py\n\n## Open questions\n- none\n")


def implement(task_dir: Path, wt: Path, broken=False):
    (wt / "textkit" / "words.py").write_text(IMPL if not broken else IMPL.replace('re.search(r"\\w", tok)', "True"))
    init = wt / "textkit" / "__init__.py"
    text = init.read_text()
    if "word_count" not in text:
        init.write_text(text.replace("from .strings import title_case", "from .strings import title_case\nfrom .words import word_count")
                        .replace('__all__ = ["title_case"]', '__all__ = ["title_case", "word_count"]'))
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add word_count"], cwd=wt, check=True)


def review(task_dir: Path, wt: Path, result="PASS"):
    data = {"result": result, "unmet": [] if result == "PASS" else [{"criterion": "AC-2", "why": "punctuation counted"}],
            "findings": [{"severity": "note", "file": "textkit/words.py", "summary": "regex could be precompiled"}]}
    (task_dir / "verify-review.json").write_text(json.dumps(data))
    (task_dir / "verify-report.md").write_text(f"# Verify report\n\n## Result\n{result}\n")
