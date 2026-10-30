"""Active Directory: the domain controller extra, and machines joining its domain through a machine
option (the panel hands the joining machine's script the controller's details)."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import actions, catalogue, cloudinit, extras
from app.api import app
from app.db import session
from app.models import Machine

from .conftest import TEMPLATE, run_queued
from .test_windows import decoded

client = TestClient(app)
KEY = ("windows-server", "2025")


@pytest.fixture
def windows(monkeypatch):
    """A Windows Server 2025 template offering the domain extras."""
    ubuntu = catalogue.catalogue()[("ubuntu", "26.04")]
    tpl = replace(
        ubuntu, template=KEY[0], version=KEY[1], vsphere=TEMPLATE, username="labadmin", family="windows",
        admin_group="Administrators", extras=("iis", "domain-controller", "additional-dc", "join-domain"),
    )  # fmt: skip
    monkeypatch.setitem(catalogue.catalogue(), KEY, tpl)


@pytest.fixture
def ready(monkeypatch):
    """Every Windows machine reports its extras done."""
    from app.vsphere import VCenter

    def read(self, vm, username, password, path):
        return "ok domain-controller\nok join-domain\n" if path == extras.WINDOWS_STATUS_FILE else None

    monkeypatch.setattr(VCenter, "read_guest_file", read)


def deploy(name, chosen, **extra):
    body = {"template": KEY[0], "version": KEY[1], "owner": "jo", "name": name, "hours": 2, "extras": chosen, **extra}
    return client.post("/api/machines", json=body)


def deploy_dc(queued, name="dc01", ip="192.0.2.10"):
    r = deploy(name, [{"id": "domain-controller", "options": {"domain": "corp.lab.example", "netbios": "corp"}}], password="Dc-Passw0rd!")
    assert r.status_code == 201, r.text
    run_queued(queued)
    with session() as s:
        s.get(Machine, r.json()["id"]).ip = ip  # vcsim's VMs never report one
    return r.json()


def userdata(queued, monkeypatch) -> list[str]:
    """Runs the queued jobs, capturing the Windows first-boot scripts they write."""
    scripts = []
    real = cloudinit.windows_userdata

    def spy(*args, **kwargs):
        scripts.append(real(*args, **kwargs))
        return scripts[-1]

    monkeypatch.setattr(cloudinit, "windows_userdata", spy)
    run_queued(queued)
    return scripts


def test_the_extras_load():
    dc, join = extras.find("domain-controller"), extras.find("join-domain")
    assert [o.id for o in dc.options] == ["domain", "netbios"] and dc.password and dc.setup_minutes == 20
    (option,) = join.options
    assert option.type == "machine" and option.extra == "domain-controller"
    out = client.get("/api/config").json()
    service = next(x for x in out["services"] if x["id"] == "join-domain")
    assert service["options"][0]["extra"] == "domain-controller"


def test_a_machine_option_needs_a_machine():
    with pytest.raises(extras.ExtraError, match="choose a machine"):
        extras.resolve(("join-domain",), [{"id": "join-domain"}], "win01")
    with pytest.raises(extras.ExtraError, match="choose a machine"):
        extras.resolve(("join-domain",), [{"id": "join-domain", "options": {"dc": "dc01"}}], "win01")
    resolved = extras.resolve(("join-domain",), [{"id": "join-domain", "options": {"dc": "m-ab12"}}], "win01")
    assert resolved == [{"id": "join-domain", "options": {"dc": "m-ab12"}}]


def test_a_controller_cant_join_a_domain_too():
    both = [{"id": "domain-controller"}, {"id": "join-domain", "options": {"dc": "m-ab12"}}]
    with pytest.raises(extras.ExtraError, match="joins another machine's"):
        extras.resolve(("domain-controller", "join-domain"), both, "win01")


def test_controller_defaults():
    (c,) = extras.resolve(("domain-controller",), [{"id": "domain-controller"}], "dc01")
    assert c["options"] == {"domain": "lab.internal", "netbios": "LAB"}
    with pytest.raises(extras.ExtraError):
        extras.resolve(("domain-controller",), [{"id": "domain-controller", "options": {"netbios": "has space"}}], "dc01")


def test_joining_gets_the_controllers_details(queued, windows, ready, monkeypatch):
    dc = deploy_dc(queued)
    r = deploy("win01", [{"id": "join-domain", "options": {"dc": dc["id"]}}], password="Member-Passw0rd!")
    assert r.status_code == 201, r.text
    (script,) = userdata(queued, monkeypatch)
    # The extras' scripts are written by the first-boot script, encoded in it too.
    values = [v for outer in decoded(script) for v in [outer, *decoded(outer)]]
    # dc_ip, dc_name, dc_username, dc_password, then the controller's own options.
    for value in ("192.0.2.10", "dc01", "labadmin", "Dc-Passw0rd!", "corp.lab.example", "corp"):
        assert value in values
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    assert "With Join a domain (domain controller dc01)" in [line["text"] for line in m["log"]]
    # Only the controller's id is kept on the machine, not its password.
    assert m["extras"][0]["options"] == {"dc": dc["id"]}


def test_joining_needs_a_running_controller(queued, windows, ready):
    plain = deploy("web01", [{"id": "iis"}], password="Plain-Passw0rd!").json()
    run_queued(queued)
    r = deploy("win01", [{"id": "join-domain", "options": {"dc": plain["id"]}}])
    assert r.status_code == 422 and "web01 isn't a domain controller" in r.json()["detail"]
    r = deploy("win02", [{"id": "join-domain", "options": {"dc": "m-0000"}}])
    assert r.status_code == 422 and "no longer exists" in r.json()["detail"]
    dc = deploy("dc01", [{"id": "domain-controller"}], password="Dc-Passw0rd!").json()  # not run yet: deploying
    r = deploy("win03", [{"id": "join-domain", "options": {"dc": dc["id"]}}])
    assert r.status_code == 422 and "dc01 isn't running yet" in r.json()["detail"]


def test_the_additional_controller_extra():
    x = extras.find("additional-dc")
    (option,) = x.options
    assert option.type == "machine" and option.extra == "domain-controller" and x.account == "dc"
    # It serves the same ports as the first controller, so the two can't go on one machine.
    assert set(x.conflicts) >= {"domain-controller", "freeipa"}
    _, script = x.families["windows"]
    # Promotes, restarts and comes back (3011) to check replication.
    assert script.index("Install-ADDSDomainController") < script.index("exit 3011") < script.index("repadmin /showrepl")


def test_a_second_controller_signs_in_as_the_first(queued, windows, ready):
    dc = deploy_dc(queued)
    r = deploy("dc02", [{"id": "additional-dc", "options": {"dc": dc["id"]}}])
    assert r.status_code == 201, r.text
    first = client.get(f"/api/machines/{dc['id']}").json()
    second = client.get(f"/api/machines/{r.json()['id']}").json()
    assert (second["username"], second["password"]) == (first["username"], first["password"]) == ("labadmin", "Dc-Passw0rd!")
    # A password of its own would never be used.
    r = deploy("dc03", [{"id": "additional-dc", "options": {"dc": dc["id"]}}], password="Other-Passw0rd!")
    assert r.status_code == 422 and "domain controller's user and password" in r.json()["detail"]


def test_deploy_fails_if_the_controller_went_away(queued, windows, ready):
    dc = deploy_dc(queued)
    r = deploy("win01", [{"id": "join-domain", "options": {"dc": dc["id"]}}], password="Member-Passw0rd!")
    with session() as s:
        s.get(Machine, dc["id"]).state = "stopped"
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert "dc01 isn't running yet" in m["log"][-1]["text"]


def test_slow_extras_get_longer(queued, windows, monkeypatch):
    waited = []
    monkeypatch.setattr(actions, "_wait_for_status", lambda vc, vm, m, family, timeout: waited.append(timeout) or "ok domain-controller\n")
    deploy_dc(queued)
    assert waited == [actions.settings().windows_setup_timeout_seconds + 20 * 60]


def test_first_boot_script_handles_a_domain_controller():
    script = cloudinit.windows_userdata("labadmin", "Pass-word1", None, [], "dc01")
    assert "DomainRole -ge 4" in script
    # The user into Domain Admins by SID, and the local accounts only when it isn't a controller.
    assert "foreach ($rid in 512, 518, 519)" in script
    assert script.index("DomainRole -ge 4") < script.index("New-LocalUser")


def test_exchange_joins_then_installs():
    x = extras.find("exchange")
    assert [o.id for o in x.options] == ["dc", "organization"] and x.options[0].extra == "domain-controller"
    assert x.setup_minutes >= 120 and x.min_memory_gb >= 8
    _, script = x.families["windows"]
    # The join restarts and comes back to it (3011); setup runs as the domain controller's user.
    assert script.index("exit 3011") < script.index("/Mode:Install /Roles:Mailbox")
    assert "-User $admin -Password $dc_password" in script


def test_windows_runner_reruns_an_extra_after_3011():
    runner = extras.WINDOWS_RUNNER
    rerun = runner.index("$code -eq 3011")
    # Unlike 3010, it doesn't mark the extra done, so the next run carries on with it.
    assert '"ok $id"' not in runner[rerun : runner.index("exit 1003", rerun)]
