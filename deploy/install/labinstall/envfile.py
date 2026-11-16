"""lab-deploy.env, the panel's settings on this server: lines set by the install."""

from pathlib import Path


def update(path: Path, values: dict[str, str]) -> None:
    """Sets these lines, replacing any already there (not commented ones) and adding the rest."""
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    for n, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in values and not line.startswith("#"):
            lines[n] = f"{key}={values[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
