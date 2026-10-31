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
    assert [m.name for m in lab.machines] == ["dc", "mail", "ws"]
    assert [m.boot_order for m in lab.machines] == [1, 2, 2]
    assert {f.id for f in lab.flags} == {"user", "share", "mail", "root"}
    assert lab.domain == "brookfield.local"
    # Its members wire their extras to the instance's own domain controller.
    ws = next(m for m in lab.machines if m.name == "ws")
    assert dict(next(x for x in ws.extras if x.id == "join-domain").options) == {"dc": "@dc"}
    # Against the real catalogue it's deployable (its templates are built and offer its extras).
    assert labs.unavailable_reason(lab) == ""


def test_meridian_loads_and_wires_to_its_first_controller():
    labs.labs.cache_clear()
    lab = labs.labs()["meridian"]
    assert lab.domain == "meridian.example" and lab.planned is True
    assert [m.name for m in lab.machines] == ["dc1", "dc2", "sql", "ws", "web"]
    assert [m.boot_order for m in lab.machines] == [1, 2, 3, 3, 3]
    assert {f.id for f in lab.flags} == {"web-user", "web-root", "sql", "ws", "share", "sysvol", "root"}
    # Members (and the second controller) wire to the instance's own first controller through @dc1.
    for name, extra in (("dc2", "additional-dc"), ("sql", "join-domain"), ("ws", "join-domain"), ("web", "join-domain-linux")):
        m = next(x for x in lab.machines if x.name == name)
        assert dict(next(x for x in m.extras if x.id == extra).options)["dc"] == "@dc1"
    # dc1 offers AD CS and the first-controller seeding; it has no @ref of its own (it boots first).
    dc1 = next(m for m in lab.machines if m.name == "dc1")
    assert {x.id for x in dc1.extras} == {"domain-controller", "adcs", "meridian-dc"}
    # Planned, so it lists as coming soon until its end-to-end walk-through passes.
    assert labs.unavailable_reason(lab) == "Meridian Logistics isn't built yet"


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


def test_a_lab_on_an_unbuilt_template_is_unavailable_not_an_error(load):
    # It loads (no crash), but isn't deployable: its template isn't built.
    all_labs = load(PLANNED.replace("planned: true", "planned: false"))
    lab = all_labs["demo"]
    assert "isn't a template that can be deployed" in labs.unavailable_reason(lab)
    assert "demo" not in labs.deployable()


def test_total_memory_sums_the_machines(monkeypatch):
    from app import catalogue
    from app.catalogue import LiveTemplate

    lab = labs.Lab(
        slug="x", title="X", description="x",
        machines=(labs.LabMachine("dc", "t", "1"), labs.LabMachine("ws", "t", "1")),
    )
    monkeypatch.setattr(catalogue, "find", lambda t, v: LiveTemplate(template="t", version="1", vsphere="x", cpu=2, memory_gb=4, disk_gb=40, username="a", family="windows"))
    assert labs.total_memory_gb(lab) == 8


# Cross-machine extra wiring: a lab member's extra points at another machine by "@role".

WIRED = """
- slug: wired
  title: Wired
  description: A member joins the dc.
  planned: true
  machines:
    - {name: dc, template: not-built, version: "1", bootOrder: 1}
    - name: ws
      template: not-built
      version: "1"
      bootOrder: 2
      extras:
        - {join-domain: {dc: "@dc"}}
"""


def test_a_machine_extra_can_point_at_another_machine(load):
    lab = load(WIRED)["wired"]
    ws = next(m for m in lab.machines if m.name == "ws")
    assert ws.extras[0].id == "join-domain"
    assert dict(ws.extras[0].options) == {"dc": "@dc"}


def test_a_bare_extra_id_still_works(load):
    lab = load(WIRED.replace('- {join-domain: {dc: "@dc"}}', "- join-domain"))["wired"]
    ws = next(m for m in lab.machines if m.name == "ws")
    assert ws.extras[0].id == "join-domain" and ws.extras[0].options == ()


def test_machine_ref_must_name_a_real_machine(load):
    with pytest.raises(ValueError, match="isn't one of the lab's machines"):
        load(WIRED.replace("@dc", "@nope"))


def test_machine_ref_must_boot_earlier(load):
    with pytest.raises(ValueError, match="must boot before it"):
        load(WIRED.replace("bootOrder: 2", "bootOrder: 1"))


def test_a_machine_option_must_be_a_ref(load):
    with pytest.raises(ValueError, match="must be set to another machine"):
        load(WIRED.replace('{dc: "@dc"}', '{dc: "m-1234"}'))


def test_a_ref_on_a_non_machine_option_is_refused(load):
    with pytest.raises(ValueError, match="isn't a machine option"):
        load(WIRED.replace("{dc: \"@dc\"}", "{netbios: \"@dc\"}").replace("join-domain", "domain-controller"))


def test_an_unknown_option_is_refused(load):
    with pytest.raises(ValueError, match="has no option"):
        load(WIRED.replace('{dc: "@dc"}', '{nope: "@dc"}'))
