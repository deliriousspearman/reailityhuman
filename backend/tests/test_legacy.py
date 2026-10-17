"""Legacy Linux machines (family "legacy"): the guestinfo keys lab-firstboot reads instead of
cloud-init's, and a deploy that waits for its status file (faked: vcsim VMs have no guest)."""

import base64
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import catalogue, cloudinit, extras
from app.api import app
from app.vsphere import connect

from .conftest import TEMPLATE, run_queued

client = TestClient(app)
KEY = ("centos", "7")


@pytest.fixture
def legacy(monkeypatch):
    """A CentOS 7 template: the legacy family, wheel for sudo, no extras."""
    ubuntu = catalogue.catalogue()[("ubuntu", "26.04")]
    tpl = replace(ubuntu, template=KEY[0], version=KEY[1], vsphere=TEMPLATE, username="labuser", family="legacy", admin_group="wheel", extras=())
    monkeypatch.setitem(catalogue.catalogue(), KEY, tpl)


def test_legacy_guestinfo_has_what_lab_firstboot_reads():
    keys = cloudinit.legacy_guestinfo("m-1234", "old01", "labuser", "Pass-word1", "ssh-ed25519 AAAA test", "wheel")
    assert keys["guestinfo.lab.instance"] == "m-1234"
    assert keys["guestinfo.lab.hostname"] == "old01"
    assert keys["guestinfo.lab.username"] == "labuser"
    assert keys["guestinfo.lab.group"] == "wheel"
    assert base64.b64decode(keys["guestinfo.lab.sshkey"]).decode() == "ssh-ed25519 AAAA test"
    # A SHA-512 crypt hash, never the password itself.
    assert keys["guestinfo.lab.password"].startswith("$6$") and "Pass-word1" not in "".join(keys.values())
    assert cloudinit.legacy_guestinfo("m-1", "a", "u", "pw", None, "sudo")["guestinfo.lab.sshkey"] == ""


def test_legacy_deploy_sets_its_keys_and_waits_for_first_boot(queued, legacy):
    r = client.post("/api/machines", json={"template": KEY[0], "version": KEY[1], "owner": "jo", "name": "old01", "hours": 2})
    assert r.status_code == 201, r.text
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    assert "Finishing setting up (its user and SSH)…" in [line["text"] for line in m["log"]]
    with connect() as vc:
        config = vc.props(vc.require_vm(m["vmName"]), "config.extraConfig")["config.extraConfig"]
    values = {o.key: o.value for o in config}
    assert values["guestinfo.lab.username"] == "labuser" and values["guestinfo.lab.group"] == "wheel"
    assert "guestinfo.userdata" not in values  # not cloud-init's


def test_legacy_templates_offer_no_extras():
    assert all("legacy" not in x.families for x in extras.extras().values())
