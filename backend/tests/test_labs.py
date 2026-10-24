"""Pro Labs: the labs.yaml format and its loader (app/labs.py)."""

from pathlib import Path

import pytest

from app import labs


@pytest.fixture
def load(tmp_path, monkeypatch):
    """Loads labs from YAML text written to a temp file, past the lru_cache."""
    def _load(text: str):
        p = tmp_path / "labs.yaml"
        p.write_text(text)
        monkeypatch.setattr(labs, "_path", lambda: p)
        labs.labs.cache_clear()
        return labs.labs()
    yield _load
    labs.labs.cache_clear()


PLANNED = """
- slug: demo
  title: Demo
  description: A demo lab.
  planned: true
  machines:
    - {name: dc, template: not-built, version: "1", bootOrder: 1}
    - {name: ws, template: not-built, version: "1", bootOrder: 2}
  flags:
    - {id: root, where: the DC desktop}
"""


def test_the_real_labs_yaml_loads():
    labs.labs.cache_clear()
    all_labs = labs.labs()
    assert "brookfield" in all_labs
    lab = all_labs["brookfield"]
    assert lab.planned is True
    assert [m.name for m in lab.machines] == ["dc", "mail", "ws"]
    assert [m.boot_order for m in lab.machines] == [1, 2, 3]
    assert {f.id for f in lab.flags} == {"user", "share", "mail", "root"}
    assert lab.domain == "brookfield.local"


def test_a_planned_lab_doesnt_need_built_templates(load):
    all_labs = load(PLANNED)
    assert all_labs["demo"].planned is True
    assert labs.deployable() == {}


def test_slug_must_be_valid(load):
    with pytest.raises(ValueError, match="valid slug"):
        load(PLANNED.replace("slug: demo", "slug: Demo_Lab"))


def test_machine_names_are_unique(load):
    with pytest.raises(ValueError, match="same name"):
        load(PLANNED.replace("name: ws", "name: dc"))


def test_flag_ids_are_unique(load):
    doubled = PLANNED + "    - {id: root, where: somewhere else}\n"
    with pytest.raises(ValueError, match="same id"):
        load(doubled)


def test_machine_name_must_be_short_and_simple(load):
    with pytest.raises(ValueError, match="valid machine name"):
        load(PLANNED.replace("name: ws", "name: workstation-01"))


def test_a_lab_needs_machines(load):
    with pytest.raises(ValueError, match="no machines"):
        load("- {slug: empty, title: Empty, description: x, planned: true, machines: []}\n")


def test_a_deployable_lab_needs_real_templates(load):
    with pytest.raises(ValueError, match="isn't a template that can be deployed"):
        load(PLANNED.replace("planned: true", "planned: false"))


def test_total_memory_sums_the_machines(monkeypatch):
    from app import catalogue
    from app.catalogue import LiveTemplate

    lab = labs.Lab(
        slug="x", title="X", description="x",
        machines=(labs.LabMachine("dc", "t", "1"), labs.LabMachine("ws", "t", "1")),
    )
    monkeypatch.setattr(catalogue, "find", lambda t, v: LiveTemplate(template="t", version="1", vsphere="x", cpu=2, memory_gb=4, disk_gb=40, username="a", family="windows"))
    assert labs.total_memory_gb(lab) == 8
