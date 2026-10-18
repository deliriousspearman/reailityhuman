"""Complete images (family "image", e.g. Metasploitable): deployed as they are, with their own fixed
sign-in, ready once they have an address."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import catalogue
from app.api import app
from app.vsphere import connect

from .conftest import TEMPLATE, run_queued

client = TestClient(app)
KEY = ("metasploitable", "2")


@pytest.fixture
def image(monkeypatch):
    ubuntu = catalogue.catalogue()[("ubuntu", "26.04")]
    tpl = replace(
        ubuntu, template=KEY[0], version=KEY[1], vsphere=TEMPLATE, username="msfadmin", family="image", extras=(), fixed_password="msfadmin"
    )
    monkeypatch.setitem(catalogue.catalogue(), KEY, tpl)


def deploy(**fields):
    return client.post("/api/machines", json={"template": KEY[0], "version": KEY[1], "owner": "jo", "name": "ms01", "hours": 2, **fields})


def test_config_shows_the_fixed_sign_in(image):
    t = next(t for t in client.get("/api/config").json()["templates"] if t["template"] == KEY[0])
    assert t["family"] == "image" and t["username"] == "msfadmin" and t["fixedPassword"] == "msfadmin"


def test_an_image_takes_no_password_or_key(image):
    for fields in ({"password": "something-else"}, {"sshKey": "ssh-ed25519 AAAA me"}):
        r = deploy(**fields)
        assert r.status_code == 422 and "msfadmin / msfadmin" in r.json()["detail"]


def test_an_image_is_deployed_as_it_is(queued, image):
    r = deploy()
    assert r.status_code == 201, r.text
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    assert m["password"] == "msfadmin"
    assert "A complete image, as it is: nothing to set up." in [line["text"] for line in m["log"]]
    with connect() as vc:
        config = vc.props(vc.require_vm(m["vmName"]), "config.extraConfig")["config.extraConfig"]
    assert not [o.key for o in config if o.key.startswith("guestinfo.")]


def test_a_password_is_for_images_only(tmp_path, monkeypatch):
    from app.config import settings

    def load(text: str):
        (tmp_path / "templates.yaml").write_text(text)
        monkeypatch.setattr(settings(), "catalogue_path", tmp_path / "templates.yaml")
        catalogue.catalogue.cache_clear()
        try:
            return catalogue.catalogue()
        finally:
            catalogue.catalogue.cache_clear()

    base = "- {template: ubuntu, version: '26.04', vsphere: x, cpu: 1, memoryGB: 1, diskGB: 1, username: u"
    with pytest.raises(ValueError, match="password for family image"):
        load(base + ", family: image}\n")
    with pytest.raises(ValueError, match="password for family image"):
        load(base + ", password: pw}\n")
