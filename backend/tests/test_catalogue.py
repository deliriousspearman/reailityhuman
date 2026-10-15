"""templates.yaml against the frontend's catalogue (frontend/src/lib/templates.ts), which has each
template's name, description and category: every deployable version must be listed there too."""

import re
from pathlib import Path

import pytest

from app import catalogue


def _frontend_catalogue() -> str:
    for candidate in (Path(__file__).resolve().parents[2] / "frontend/src/lib", Path("/frontend-lib")):
        if (candidate / "templates.ts").is_file():
            return (candidate / "templates.ts").read_text()
    pytest.skip("frontend/src/lib/templates.ts isn't mounted here")


def test_every_deployable_version_is_in_the_frontend_catalogue():
    source = _frontend_catalogue()
    # Each template is an object starting "id: '<id>'", up to the next one.
    blocks = dict(re.findall(r"\bid: '([^']+)',(.*?)(?=\bid: '|\Z)", source, re.S))
    for t in catalogue.catalogue().values():
        assert t.template in blocks, f"{t.template} is in templates.yaml but not in templates.ts"
        assert f"version: '{t.version}'" in blocks[t.template], f"{t.template} {t.version} is in templates.yaml but not in templates.ts"


def test_commented_out_templates_are_ready_to_uncomment(tmp_path, monkeypatch):
    """Entries in templates.yaml waiting for their template to be built (e.g. Windows Server) load,
    with their extras, once uncommented, and are in the frontend's catalogue."""
    import shutil

    from app import extras
    from app.config import settings

    source = settings().catalogue_path.read_text()
    lines = source.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("# - template:"))
    entries = [line[2:] for line in lines[first:] if line.startswith(("# - ", "#   "))]
    (tmp_path / "templates.yaml").write_text("\n".join(lines[:first] + entries))
    shutil.copy(settings().catalogue_path.with_name("extras.yaml"), tmp_path / "extras.yaml")
    monkeypatch.setattr(settings(), "catalogue_path", tmp_path / "templates.yaml")
    catalogue.catalogue.cache_clear()
    extras.extras.cache_clear()
    try:
        windows = catalogue.find("windows-server", "2025 Core")
        assert windows is not None and windows.family == "windows" and windows.admin_group == "Administrators"
        assert windows.extras == ("iis",) and windows.access == ("rdp", "ssh", "console")
        assert catalogue.find("windows-server", "2025").extras == ("iis", "outlook")  # not on Core
        for key in (("kali", "2026.3"), ("parrot", "7")):
            box = catalogue.find(*key)
            assert box is not None and box.family == "debian" and "rdp" in box.access
            assert "desktop" not in box.extras  # they have their own, over RDP
        test_every_deployable_version_is_in_the_frontend_catalogue()
    finally:
        catalogue.catalogue.cache_clear()
        extras.extras.cache_clear()
