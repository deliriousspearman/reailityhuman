"""templates.yaml against the frontend's catalogue (frontend/src/lib/templates.ts), which has each
template's name, description and category: every deployable version must be listed there too."""

import re
from dataclasses import replace
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


@pytest.fixture
def a_planned_template(monkeypatch):
    """A template still to be built, whatever templates.yaml has planned today: Kali as a future
    release, marked planned."""
    kali = catalogue.find("kali", "2026.2")
    planned = replace(kali, version="2027.1", vsphere="", planned=True)
    monkeypatch.setattr(catalogue, "planned", lambda: (planned,))
    return planned


def test_the_attack_boxes_and_windows_load_as_built():
    windows = catalogue.find("windows-server", "2025 Core")
    assert windows.family == "windows" and windows.admin_group == "Administrators"
    assert windows.extras == ("iis", "mssql", "domain-controller", "join-domain") and windows.access == ("rdp", "ssh", "console")
    assert "outlook" in catalogue.find("windows-server", "2025").extras  # not on Core: it needs the desktop
    for box in (catalogue.find("kali", "2026.2"), catalogue.find("parrot", "7")):
        assert box.family == "debian" and "rdp" in box.access
        assert "desktop" not in box.extras  # they have their own, over RDP
        assert "mysql" not in box.extras and "mariadb" in box.extras  # Debian has only MariaDB


def test_planned_templates_are_listed_but_not_deployable():
    """Entries waiting for their template to be built (in templates.yaml now: none, or a few) can't be
    deployed, and are in the frontend's catalogue."""
    planned = {(t.template, t.version): t for t in catalogue.planned()}
    for key in planned:
        assert catalogue.find(*key) is None
    source = _frontend_catalogue()
    blocks = dict(re.findall(r"\bid: '([^']+)',(.*?)(?=\bid: '|\Z)", source, re.S))
    for t in planned.values():
        assert f"version: '{t.version}'" in blocks.get(t.template, ""), f"{t.template} {t.version} isn't in templates.ts"


def test_offered_by_says_what_is_ready(monkeypatch, a_planned_template):
    """Ready: deployable and built with the extra. Not yet: planned extras, and planned templates."""
    ubuntu = catalogue.find("ubuntu", "26.04")
    monkeypatch.setitem(catalogue.catalogue(), ("ubuntu", "26.04"), replace(ubuntu, extras=("nginx",), planned_extras=("ftp",)))
    nginx = catalogue.offered_by("nginx")
    assert {"template": "ubuntu", "version": "26.04", "ready": True} in nginx
    assert {"template": "kali", "version": "2027.1", "ready": False} in nginx
    assert {"template": "ubuntu", "version": "26.04", "ready": False} in catalogue.offered_by("ftp")
    # `a_planned_template` stubs planned() with one fake template, so only the deployable iis
    # templates show here (planned() is stubbed).
    assert catalogue.offered_by("iis") == [
        {"template": "windows-server", "version": "2025", "ready": True},
        {"template": "windows-server", "version": "2022", "ready": True},
        {"template": "windows-server", "version": "2019", "ready": True},
        {"template": "windows-server", "version": "2016", "ready": True},
        {"template": "windows-server", "version": "2025 Core", "ready": True},
        {"template": "windows", "version": "11", "ready": True},
    ]


def test_bad_planned_entries_are_refused(tmp_path, monkeypatch):
    from app.config import settings

    def load(text: str):
        (tmp_path / "templates.yaml").write_text(text)
        monkeypatch.setattr(settings(), "catalogue_path", tmp_path / "templates.yaml")
        catalogue.catalogue.cache_clear()
        catalogue.planned.cache_clear()
        try:
            return catalogue.planned()
        finally:
            catalogue.catalogue.cache_clear()
            catalogue.planned.cache_clear()

    import shutil

    shutil.copy(settings().catalogue_path.with_name("extras.yaml"), tmp_path / "extras.yaml")
    entry = "- {template: x, version: '1', cpu: 1, memoryGB: 1, diskGB: 1, username: u"
    assert load(entry + ", planned: true}\n")[0].vsphere == ""
    with pytest.raises(ValueError, match="no vsphere template"):
        load(entry + "}\n")
    with pytest.raises(ValueError, match="both extras and plannedExtras"):
        load(entry + ", vsphere: a/b, extras: [nginx], plannedExtras: [nginx]}\n")
    with pytest.raises(ValueError, match="no debian steps"):
        load(entry + ", vsphere: a/b, plannedExtras: [iis]}\n")
