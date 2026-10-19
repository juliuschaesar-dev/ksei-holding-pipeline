"""Read a GitHub Actions workflow file as text: its jobs, its run steps, the actions it uses.

The tests of ci.yml use these. A real
YAML parser is not needed for them, and the project has none.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def header(name: str) -> str:
    """Everything before `jobs:`: the name, the triggers, the permissions."""
    return text(name).split("\njobs:\n", 1)[0]


def jobs(name: str) -> dict[str, str]:
    """Job name -> the text of that job (jobs are the two-space-indented keys under `jobs:`)."""
    body = text(name).split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][a-z0-9-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def run_lines(block: str) -> list[str]:
    """Every command line of every `run:` step of the given text."""
    lines = block.splitlines()
    commands: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"(\s*)(?:- )?run:\s*(.*)$", line)
        if not match:
            continue
        indent, inline = match.groups()
        if inline and inline not in ("|", ">"):
            commands.append(inline.strip())
            continue
        for follow in lines[index + 1 :]:
            if follow.strip() and len(follow) - len(follow.lstrip()) <= len(indent):
                break
            if follow.strip():
                commands.append(follow.strip())
    return commands


def actions_used(name: str) -> set[str]:
    return set(re.findall(r"(?m)uses:\s*(\S+)", text(name)))


def make_targets() -> set[str]:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^([a-z][a-z0-9-]*):", makefile))
