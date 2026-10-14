"""Extras: the catalogue, choosing and validating them, the cloud-init that applies them, and the
worker waiting for them (with the guest's status file faked: vcsim VMs have no guest)."""

import re
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalogue, cloudinit, extras
from app.api import app
from app.config import settings
from app.vsphere import VCenter

from .conftest import run_queued

client = TestClient(app)
ALL = ("nginx", "apache", "apache-https")


@pytest.fixture
def offered(monkeypatch):
    """The Ubuntu template, as if it had been built with every extra."""
    key = ("ubuntu", "26.04")
    monkeypatch.setitem(catalogue.catalogue(), key, replace(catalogue.catalogue()[key], extras=ALL))


@pytest.fixture
def guest(monkeypatch):
    """What the machine's status file says; None: not written yet."""
    state = {"status": None, "reads": []}

    def read(self, vm, username, password, path):
        state["reads"].append((username, path))
        return state["status"]

    monkeypatch.setattr(VCenter, "read_guest_file", read)
    return state


def deploy(name="web01", chosen=()):
    return client.post(
        "/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": name, "hours": 2, "extras": list(chosen)}
    )


# The catalogue ---------------------------------------------------------------------------------------


def test_catalogue_files_load():
    assert set(ALL) <= set(extras.extras())
    for x in extras.extras().values():
        assert x.families, f"{x.id} has steps for no family"
    catalogue.catalogue()  # checks each template's extras exist for its family


def _prepare_sh() -> Path:
    for candidate in (Path(__file__).resolve().parents[2] / "scripts", Path("/scripts")):
        if (candidate / "template" / "prepare.sh").exists():
            return candidate / "template" / "prepare.sh"
    pytest.skip("scripts/template/prepare.sh isn't mounted here")


def test_prepare_sh_installs_every_extras_packages():
    text = _prepare_sh().read_text()
    for family in ("debian", "rhel"):  # Windows extras install their features at deploy
        m = re.search(rf"^EXTRA_PACKAGES_{family.upper()}=\(([^)]*)\)", text, re.M)
        assert m, f"prepare.sh has no EXTRA_PACKAGES_{family.upper()}"
        in_script = set(m.group(1).split())
        for x in extras.extras().values():
            if family in x.families:
                missing = set(x.families[family][0]) - in_script
                assert not missing, f"prepare.sh doesn't install {missing} for {x.id} ({family})"


# Choosing ---------------------------------------------------------------------------------------------


def test_defaults_follow_the_name_and_machine_domain(monkeypatch):
    [c] = extras.resolve(ALL, [{"id": "apache-https", "options": {}}], "web01")
    assert c == {"id": "apache-https", "options": {"domain": "web01"}}
    monkeypatch.setattr(settings(), "machine_domain", "lab.example")
    [c] = extras.resolve(ALL, [{"id": "apache-https", "options": {"domain": "  "}}], "web01")
    assert c["options"]["domain"] == "web01.lab.example"
    [c] = extras.resolve(ALL, [{"id": "apache-https", "options": {"domain": "Intranet.Lab.Example."}}], "web01")
    assert c["options"]["domain"] == "intranet.lab.example"
    [c] = extras.resolve(ALL, [{"id": "apache-https", "options": {"domain": "*.lab.example"}}], "web01")
    assert c["options"]["domain"] == "*.lab.example"


@pytest.mark.parametrize(
    "chosen, problem",
    [
        ([{"id": "nginx"}, {"id": "apache"}], "can't be combined"),
        ([{"id": "nginx"}, {"id": "nginx"}], "only be chosen once"),
        ([{"id": "mysql"}], "isn't an extra"),
        ([{"id": "nginx", "options": {"domain": "x"}}], "has no option"),
        ([{"id": "apache-https", "options": {"domain": "a.example; rm -rf /"}}], "isn't a valid"),
        ([{"id": "apache-https", "options": {"domain": "$(reboot).example"}}], "isn't a valid"),
        ([{"id": "apache-https", "options": {"domain": "a b.example"}}], "isn't a valid"),
        ([{"id": "apache-https", "options": {"domain": "-bad.example"}}], "isn't a valid"),
        ([{"id": "apache-https", "options": {"domain": "a" * 64 + ".example"}}], "isn't a valid"),
    ],
)
def test_bad_choices_are_refused(chosen, problem):
    with pytest.raises(extras.ExtraError, match=re.escape(problem)):
        extras.resolve(ALL, chosen, "web01")


def test_only_what_the_template_offers():
    with pytest.raises(extras.ExtraError, match="isn't an extra this template offers"):
        extras.resolve(("nginx",), [{"id": "apache"}], "web01")


# Applying ---------------------------------------------------------------------------------------------


def test_cloud_config_quotes_values_and_runs_each_extra():
    chosen = [{"id": "apache-https", "options": {"domain": "*.lab.example"}}]
    config = extras.cloud_config(chosen, "debian", "web01")
    paths = [f["path"] for f in config["write_files"]]
    assert paths == [f"{extras.DIR}/extras/run.sh", f"{extras.DIR}/extras/apache-https.sh"]
    script = config["write_files"][1]["content"]
    assert "hostname=web01\n" in script
    assert "domain='*.lab.example'\n" in script  # quoted, so the * isn't expanded
    assert "openssl req" in script and "a2ensite" in script
    assert config["runcmd"] == [["bash", f"{extras.DIR}/extras/run.sh", "apache-https"]]
    assert extras.cloud_config([], "debian", "web01") == {}

    data = yaml.safe_load(cloudinit.userdata("web01", "ubuntu", "pw", None, extra=config).removeprefix("#cloud-config\n"))
    assert data["runcmd"] == config["runcmd"]
    assert data["users"][0]["name"] == "ubuntu"


def test_parse_status():
    assert extras.parse_status("ok nginx\nfailed apache-https Job for apache2.service failed.\n\n") == [
        ("nginx", True, ""),
        ("apache-https", False, "Job for apache2.service failed."),
    ]


# Through the API and the worker -------------------------------------------------------------------------


def test_config_lists_extras_for_templates_that_have_them(offered):
    t = client.get("/api/config").json()["templates"][0]
    https = next(x for x in t["extras"] if x["id"] == "apache-https")
    assert https["conflicts"] == ["nginx", "apache"]
    assert https["options"][0]["id"] == "domain" and https["options"][0]["default"] == "{fqdn}"


def test_deploy_rejects_bad_extras(offered):
    r = deploy(chosen=[{"id": "apache-https", "options": {"domain": "x.example && reboot"}}])
    assert r.status_code == 422 and "isn't a valid" in r.json()["detail"]
    assert deploy(chosen=[{"id": "nginx"}, {"id": "apache"}]).status_code == 422


def test_extras_offered_only_by_templates_listing_them():
    # The real templates.yaml's Ubuntu template predates extras, so it offers none.
    assert deploy(chosen=[{"id": "nginx"}]).status_code == 422


def test_deploy_waits_for_extras(queued, offered, guest):
    guest["status"] = "ok apache-https\n"
    r = deploy(chosen=[{"id": "apache-https", "options": {"domain": "intranet.lab.example"}}])
    assert r.status_code == 201, r.text
    assert r.json()["extras"] == [{"id": "apache-https", "name": "Apache + HTTPS", "options": {"domain": "intranet.lab.example"}}]
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running"
    texts = [line["text"] for line in m["log"]]
    assert "With Apache + HTTPS (domain name intranet.lab.example)" in texts
    assert "Installing extras: Apache + HTTPS…" in texts
    assert "Apache + HTTPS is ready" in texts
    assert guest["reads"] == [("ubuntu", extras.STATUS_FILE)]


def test_failed_extra_fails_the_deploy(queued, offered, guest):
    guest["status"] = "failed nginx Job for nginx.service failed.\n"
    r = deploy(chosen=[{"id": "nginx"}])
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert "nginx didn't install: Job for nginx.service failed." in m["log"][-1]["text"]


def test_extras_that_never_finish_time_out(queued, offered, guest, monkeypatch):
    monkeypatch.setattr(settings(), "extras_timeout_seconds", 0)
    r = deploy(chosen=[{"id": "nginx"}])
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert "didn't finish setting up within" in m["log"][-1]["text"]


def test_no_extras_no_waiting(queued, guest):
    r = deploy()
    run_queued(queued)
    assert client.get(f"/api/machines/{r.json()['id']}").json()["state"] == "running"
    assert guest["reads"] == []
