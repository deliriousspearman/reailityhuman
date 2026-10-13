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
