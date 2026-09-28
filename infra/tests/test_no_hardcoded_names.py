"""The project name lives in project.toml only; everything else derives it."""

import subprocess
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = ("project.toml", "docs/")
# ponytail: substring match; a name that is a common word ("api") would false-positive.
# Meaningful for the template's placeholder name; tighten to word boundaries if it bites.


def test_project_name_not_hardcoded():
    c = config.load()
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()

    offenders = []
    for rel in tracked:
        if rel.startswith(EXCLUDED):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if c.name in text or c.agentcore_project in text:
            offenders.append(rel)

    assert not offenders, f"'{c.name}' written literally in: {offenders}"
