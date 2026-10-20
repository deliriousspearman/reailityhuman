"""The install's state (/srv/lab-deploy/install/state.json): what each run built, failed or skipped,
so a re-run picks up where the last one stopped."""

import json
from pathlib import Path


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(path)
