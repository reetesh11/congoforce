"""Architecture diagrams: Mermaid blocks in tech.md's `## Architecture` section.

Mermaid (https://mermaid.js.org, MIT) is plain text, so agents write it and
reviewers read it in the gate packets; GitHub and GitLab render it in the PR
body. When mermaid-cli (`mmdc`) is available the helper renders each block to
SVG, which is also the syntax check: a parse error rejects tech.md and the
tech-spec agent fixes it. Without mmdc only the header is checked.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import runner
from .util import md_section

SIZE_RANK = {"small": 0, "medium": 1, "large": 2}
BLOCK_RX = re.compile(r"^```mermaid[ \t]*\n(.*?)^```", re.M | re.S)
# First keyword of every Mermaid diagram type that suits an architecture view.
TYPES = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2",
    "erDiagram", "C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment",
    "architecture-beta", "block-beta",
)
ANSI_RX = re.compile(r"\x1b\[[0-9;]*m")
SYNTAX_RX = re.compile(r"(Parse error|Syntax error|Lexical error|No diagram type detected|UnknownDiagramError)", re.I)


def required(cfg: dict, s: dict) -> bool:
    """Whether tech.md must hold a diagram for this task, from `architecture_diagram`."""
    mode = cfg.get("architecture_diagram", "large")
    if mode == "off":
        return False
    if mode == "always":
        return True
    size = max(SIZE_RANK.get(s.get("size") or "", 0), SIZE_RANK.get(s.get("size_requested") or "", 0))
    return size >= SIZE_RANK[mode]


def blocks(tech_text: str) -> list:
    """Mermaid sources inside `## Architecture`, in order."""
    section = md_section(tech_text, "Architecture")
    return [b.strip() + "\n" for b in BLOCK_RX.findall(section + "\n")] if section else []


def header_error(src: str) -> str:
    """'' when the block starts with a known diagram type, else why not."""
    lines = src.splitlines()
    i = 0
    if lines and lines[0].strip() == "---":  # front matter (title, config)
        i = next((j + 1 for j in range(1, len(lines)) if lines[j].strip() == "---"), len(lines))
    for line in lines[i:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        word = stripped.split()[0]
        if word in TYPES:
            return ""
        return f"starts with {word!r}; use one of: {', '.join(TYPES)}"
    return "is empty"


def _syntax_excerpt(output: str) -> str:
    """The parser's message without colour codes, warnings or the stack trace."""
    text = ANSI_RX.sub("", output)
    m = SYNTAX_RX.search(text)
    lines = text[text.rfind("\n", 0, m.start()) + 1:].splitlines() if m else text.splitlines()
    return "\n".join(l for l in lines[:5] if not l.lstrip().startswith("at ")).strip()


def render_command(cfg: dict) -> str:
    """Command template with {in} and {out}, or '' when rendering is off or unavailable."""
    mode = (cfg.get("diagram_render") or "auto").strip()
    if mode == "off":
        return ""
    if mode == "auto":
        return "mmdc -q -i {in} -o {out}" if shutil.which("mmdc") else ""
    return mode


def process(cfg: dict, s: dict, tech_text: str, out_dir: Path) -> dict:
    """Validate and render the diagrams. Returns {required, files, rendered, note, error}.

    `error` is set when the agent must fix tech.md; environment problems
    (no Chromium for mmdc, a timeout) only become a note.
    """
    need = required(cfg, s)
    srcs = blocks(tech_text)
    out = {"required": need, "files": [], "rendered": [], "note": "", "error": ""}
    if not srcs:
        if need:
            mode = cfg.get("architecture_diagram")
            out["error"] = (f"tech.md needs a `## Architecture` section with a ```mermaid diagram "
                            f"(architecture_diagram = {mode}, size {s.get('size_requested') or s.get('size')})")
        return out
    for n, src in enumerate(srcs, 1):
        bad = header_error(src)
        if bad:
            out["error"] = f"Architecture diagram {n} {bad}"
            return out
    cmd_tpl = render_command(cfg)
    for n, src in enumerate(srcs, 1):
        stem = "architecture" if n == 1 else f"architecture-{n}"
        mmd = Path(out_dir) / f"{stem}.mmd"
        mmd.write_text(src)
        out["files"].append(mmd.name)
        if not cmd_tpl:
            continue
        svg = mmd.with_suffix(".svg")
        res = runner.run(cmd_tpl.replace("{in}", str(mmd)).replace("{out}", str(svg)), Path(out_dir),
                         int(cfg.get("command_timeout", 600)), log_path=Path(out_dir) / "logs" / f"{stem}-render.log")
        if res["ok"] and svg.exists():
            out["rendered"].append(svg.name)
        elif not res["timed_out"] and SYNTAX_RX.search(res["output"]):
            out["error"] = f"Architecture diagram {n} does not parse:\n{_syntax_excerpt(res['output'])}"
            return out
        else:
            out["note"] = f"diagram {n} not rendered ({'timed out' if res['timed_out'] else 'renderer failed'}); see logs/{stem}-render.log"
    if not cmd_tpl:
        out["note"] = "rendering off or mmdc not installed; header checked only"
    return out
