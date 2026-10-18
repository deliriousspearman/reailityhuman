"""VyOS machines (family "vyos"): cloud-config with only VyOS configuration commands, and a deploy
that's ready once the user can sign in (faked: vcsim VMs have no guest)."""

import base64
from dataclasses import replace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalogue, cloudinit, extras
from app.api import app
from app.vsphere import VCenter, connect

from .conftest import TEMPLATE, run_queued

client = TestClient(app)
KEY = ("vyos", "rolling")


@pytest.fixture
def vyos(monkeypatch):
    """A VyOS template: the vyos family, no extras."""
    ubuntu = catalogue.catalogue()[("ubuntu", "26.04")]
    tpl = replace(ubuntu, template=KEY[0], version=KEY[1], vsphere=TEMPLATE, username="labuser", family="vyos", extras=())
    monkeypatch.setitem(catalogue.catalogue(), KEY, tpl)


def test_vyos_userdata_is_configuration_commands():
    text = cloudinit.vyos_userdata("r1", "labuser", "Pass-word1", "ssh-ed25519 AAAAkey me@host")
    assert text.startswith("#cloud-config\n")
    commands = yaml.safe_load(text)["vyos_config_commands"]
    assert yaml.safe_load(text).keys() == {"vyos_config_commands"}
    assert "set system host-name 'r1'" in commands
    password = next(c for c in commands if "encrypted-password" in c)
    assert password.startswith("set system login user 'labuser' authentication encrypted-password '$6$")
    assert "Pass-word1" not in text
    assert "set system login user 'labuser' authentication public-keys panel type 'ssh-ed25519'" in commands
    assert "set system login user 'labuser' authentication public-keys panel key 'AAAAkey'" in commands
    assert "set service ssh port '22'" in commands
    assert {"set interfaces ethernet eth0 address 'dhcp'", "set interfaces ethernet eth1 address 'dhcp'"} <= set(commands)
    assert not any("public-keys" in c for c in yaml.safe_load(cloudinit.vyos_userdata("r1", "u", "pw", None))["vyos_config_commands"])


def test_vyos_metadata_has_no_network_config():
    keys = cloudinit.vyos_guestinfo("m-1", "r1", "labuser", "pw", None)
    metadata = yaml.safe_load(base64.b64decode(keys["guestinfo.metadata"]))
    assert metadata == {"instance-id": "m-1", "local-hostname": "r1"}


def test_vyos_deploy_waits_for_the_user(queued, vyos, monkeypatch):
    tries = []
    monkeypatch.setattr(VCenter, "guest_login_ok", lambda self, vm, u, p: tries.append(u) or len(tries) > 1)
    monkeypatch.setattr("app.actions.time.sleep", lambda s: None)
    r = client.post("/api/machines", json={"template": KEY[0], "version": KEY[1], "owner": "jo", "name": "r1", "hours": 2})
    assert r.status_code == 201, r.text
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    assert "Applying its configuration (its user and SSH)…" in [line["text"] for line in m["log"]]
    assert tries == ["labuser", "labuser"]
    with connect() as vc:
        config = vc.props(vc.require_vm(m["vmName"]), "config.extraConfig")["config.extraConfig"]
    values = {o.key: o.value for o in config}
    assert "vyos_config_commands" in base64.b64decode(values["guestinfo.userdata"]).decode()


def test_vyos_templates_offer_no_extras():
    assert all("vyos" not in x.families for x in extras.extras().values())
