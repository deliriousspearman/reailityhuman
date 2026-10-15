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


def test_prepare_and_clean_know_the_same_oses():
    """An OS prepare.sh builds, clean.sh can finish (and the other way round)."""
    def oses(text: str) -> set[str]:
        found = re.findall(r"^\t?([a-z |]+)\) FAMILY=", text, re.M)
        return {os.strip() for line in found for os in line.split("|")}

    prepare = oses(_prepare_sh().read_text())
    assert prepare == oses(_prepare_sh().with_name("clean.sh").read_text())
    assert {"kali", "parrot"} <= prepare


def test_prepare_sh_installs_every_extras_packages():
    """Each extra's packages, per family, are in prepare.sh's list for that extra."""
    text = _prepare_sh().read_text()
    for family in ("debian", "rhel"):  # Windows extras install their features at deploy
        block = re.search(rf"^declare -A EXTRA_PACKAGES_{family.upper()}=\(\n(.*?)^\)", text, re.M | re.S)
        assert block, f"prepare.sh has no EXTRA_PACKAGES_{family.upper()}"
        listed = {i: set(p.split()) for i, p in re.findall(r'^\s*\[([\w-]+)\]="([^"]*)"', block.group(1), re.M)}
        for x in extras.extras().values():
            if family in x.families:
                assert x.id in listed, f"prepare.sh has no EXTRA_PACKAGES_{family.upper()}[{x.id}]"
                missing = set(x.families[family][0]) - listed[x.id]
                assert not missing, f"prepare.sh doesn't install {missing} for {x.id} ({family})"


# Choosing ---------------------------------------------------------------------------------------------


def test_clashes_come_from_shared_ports():
    from app.extras import Extra, clashes

    nginx = Extra("nginx", "nginx", "", ports=(80,))
    https = Extra("apache-https", "Apache + HTTPS", "", ports=(80, 443))
    wordpress = Extra("wordpress", "WordPress", "", ports=(80, 443))
    ftp = Extra("ftp", "FTP", "", ports=(21,))
    desktop = Extra("desktop", "Desktop", "", ports=(3389, 5901))
    assert clashes(nginx, https) and clashes(wordpress, nginx) and clashes(wordpress, https)
    assert not clashes(ftp, wordpress) and not clashes(desktop, https) and not clashes(ftp, desktop)
    assert not clashes(nginx, nginx)


def test_catalogue_conflicts_are_worked_out():
    """One web service per machine; FTP and the desktop go with anything."""
    found = {i: set(x.conflicts) for i, x in extras.extras().items()}
    web = {"nginx", "apache", "apache-https", "wordpress", "nextcloud", "nextcloud-snap", "mail", "iis"}
    for i in web:
        assert found[i] == web - {i}, i
    assert found["ftp"] == set() and found["desktop"] == set() and found["outlook"] == set()


def test_old_sharing_keys_are_refused(tmp_path, monkeypatch):
    (tmp_path / "extras.yaml").write_text("- id: x\n  name: X\n  description: ''\n  uses: apache\n")
    monkeypatch.setattr(extras, "_path", lambda: tmp_path / "extras.yaml")
    extras.extras.cache_clear()
    try:
        with pytest.raises(ValueError, match="no longer used"):
            extras.extras()
    finally:
        monkeypatch.undo()
        extras.extras.cache_clear()


def test_extras_run_in_catalogue_order(monkeypatch):
    """Always in the catalogue's order, whatever order they were ticked in."""
    from app.extras import Extra

    catalogue_ = {"apache": Extra("apache", "Apache", "", ports=(80,)), "ftp": Extra("ftp", "FTP", "", ports=(21,))}
    monkeypatch.setattr(extras, "extras", lambda: catalogue_)
    chosen = extras.resolve(("apache", "ftp"), [{"id": "ftp"}, {"id": "apache"}], "web01")
    assert [c["id"] for c in chosen] == ["apache", "ftp"]


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
        ([{"id": "apache"}, {"id": "nginx"}], "can't be combined"),
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
    assert paths == [f"{extras.DIR}/extras/run.sh", f"{extras.DIR}/extras/lib.sh", f"{extras.DIR}/extras/apache-https.sh"]
    assert "lab_cert()" in config["write_files"][1]["content"]
    script = config["write_files"][2]["content"]
    assert "hostname=web01\n" in script
    assert "domain='*.lab.example'\n" in script  # quoted, so the * isn't expanded
    # The helpers are loaded after the variables, and used.
    assert script.index("domain=") < script.index(f". {extras.DIR}/extras/lib.sh") < script.index('lab_cert "$domain"')
    assert "a2ensite" in script
    assert config["runcmd"] == [["bash", f"{extras.DIR}/extras/run.sh", "apache-https"]]
    assert extras.cloud_config([], "debian", "web01") == {}

    data = yaml.safe_load(cloudinit.userdata("web01", "ubuntu", "pw", None, extra=config).removeprefix("#cloud-config\n"))
    assert data["runcmd"] == config["runcmd"]
    assert data["users"][0]["name"] == "ubuntu"


def test_parse_status():
    assert extras.parse_status("ok nginx\nfailed apache-https Job for apache2.service failed.\n\nwarn ssh no keys\nnoise\n") == [
        ("ok", "nginx", ""),
        ("failed", "apache-https", "Job for apache2.service failed."),
        ("warn", "ssh", "no keys"),
    ]


# Through the API and the worker -------------------------------------------------------------------------


def test_config_lists_extras_for_templates_that_have_them(offered):
    t = client.get("/api/config").json()["templates"][0]
    https = next(x for x in t["extras"] if x["id"] == "apache-https")
    assert https["conflicts"] == ["nginx", "apache", "wordpress", "nextcloud", "nextcloud-snap", "mail", "iis"]
    assert https["options"][0]["id"] == "domain" and https["options"][0]["default"] == "{fqdn}"


def test_deploy_rejects_bad_extras(offered):
    r = deploy(chosen=[{"id": "apache-https", "options": {"domain": "x.example && reboot"}}])
    assert r.status_code == 422 and "isn't a valid" in r.json()["detail"]
    assert deploy(chosen=[{"id": "nginx"}, {"id": "apache"}]).status_code == 422


def test_extras_offered_only_by_templates_listing_them():
    # The real templates.yaml's Ubuntu template offers the Linux web servers, not Windows' IIS.
    assert deploy(chosen=[{"id": "iis"}]).status_code == 422


def test_deploy_waits_for_extras(queued, offered, guest):
    guest["status"] = "ok apache-https\n"
    r = deploy(chosen=[{"id": "apache-https", "options": {"domain": "intranet.lab.example"}}])
    assert r.status_code == 201, r.text
    assert r.json()["extras"] == [
        {"id": "apache-https", "name": "Apache + HTTPS", "options": {"domain": "intranet.lab.example"}, "links": [], "notes": []}
    ]  # links once it has an address
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


def test_choice_and_boolean_options(monkeypatch):
    from app.extras import Extra, Option

    desktop = Extra(
        "desktop", "Desktop", "",
        options=(
            Option("protocol", "Connect with", "choice", default="rdp", choices=(("rdp", "RDP"), ("vnc", "VNC"), ("both", "Both"))),
            Option("tls", "Use TLS", "boolean", default="no"),
        ),
    )  # fmt: skip
    monkeypatch.setattr(extras, "extras", lambda: {"desktop": desktop})

    def resolve(options):
        return extras.resolve(("desktop",), [{"id": "desktop", "options": options}], "web01")[0]["options"]

    assert resolve({}) == {"protocol": "rdp", "tls": "no"}  # the defaults
    assert resolve({"protocol": "vnc", "tls": "on"}) == {"protocol": "vnc", "tls": "yes"}
    assert resolve({"tls": "False"})["tls"] == "no"
    with pytest.raises(extras.ExtraError, match="isn't one of the choices"):
        resolve({"protocol": "telnet"})
    with pytest.raises(extras.ExtraError, match="is yes or no"):
        resolve({"tls": "maybe"})


def test_choice_needs_a_valid_default(tmp_path, monkeypatch):
    (tmp_path / "extras.yaml").write_text(
        "- id: x\n  name: X\n  description: ''\n  options:\n"
        "    - {id: mode, label: Mode, type: choice, default: c, choices: [{value: a, label: A}, {value: b, label: B}]}\n"
    )
    monkeypatch.setattr(extras, "_path", lambda: tmp_path / "extras.yaml")
    extras.extras.cache_clear()
    try:
        with pytest.raises(ValueError, match="a choice needs choices"):
            extras.extras()
    finally:
        monkeypatch.undo()
        extras.extras.cache_clear()


def test_links_and_notes_are_filled_in(monkeypatch):
    from app.extras import Extra

    wp = Extra(
        "wordpress", "WordPress", "",
        links=(("http://{ip}/", {"https": ("no",)}), ("https://{ip}/", {"https": ("yes",)})),
        notes=(("Admin: /wp-admin/ as {username}, for {domain} on {hostname}. Keep {braces}.", {}),),
    )  # fmt: skip
    monkeypatch.setattr(extras, "find", lambda i: wp)
    plain = {"id": "wordpress", "options": {"domain": "blog.lab.example", "https": "no"}}
    assert extras.details(plain, "192.0.2.7", "ubuntu", "web01") == {
        "links": ["http://192.0.2.7/"],
        "notes": ["Admin: /wp-admin/ as ubuntu, for blog.lab.example on web01. Keep {braces}."],
    }
    secure = {"id": "wordpress", "options": {"domain": "blog.lab.example", "https": "yes"}}
    assert extras.details(secure, "192.0.2.7", "ubuntu", "web01")["links"] == ["https://192.0.2.7/"]
    assert extras.details(plain, "", "ubuntu", "web01") == {"links": [], "notes": []}  # no address yet


def test_web_apps_are_the_whole_site():
    for i in ("wordpress", "nextcloud", "mail"):
        _, script = extras.find(i).families["debian"]
        assert 'lab_apache_site ' in script and '"$https" "$domain"' in script, i
        assert "Alias /" not in script, i


def test_extras_too_big_for_the_machine_are_refused(monkeypatch):
    from app.extras import Extra

    desktop = Extra("desktop", "Desktop", "", min_memory_gb=4)
    monkeypatch.setattr(extras, "extras", lambda: {"desktop": desktop})
    with pytest.raises(extras.ExtraError, match="needs at least 4 GB of memory, and this machine has 2 GB"):
        extras.resolve(("desktop",), [{"id": "desktop"}], "web01", memory_gb=2)
    assert extras.resolve(("desktop",), [{"id": "desktop"}], "web01", memory_gb=4)


def test_config_sends_category_memory_and_ports(offered):
    t = client.get("/api/config").json()["templates"][0]
    https = next(x for x in t["extras"] if x["id"] == "apache-https")
    assert https["category"] == "Web servers" and https["minMemoryGB"] == 0 and https["ports"] == [80, 443]


def test_scripts_get_the_user_and_only_some_the_password(monkeypatch):
    from app.extras import Extra

    plain = Extra("plain", "Plain", "", families={"debian": ((), "true")})
    secret = Extra("secret", "Secret", "", password=True, families={"debian": ((), "true")})
    monkeypatch.setattr(extras, "extras", lambda: {"plain": plain, "secret": secret})
    monkeypatch.setattr(extras, "find", lambda i: {"plain": plain, "secret": secret}.get(i))
    assert "username=ubuntu\n" in extras.script(plain, "debian", "web01", {}, "ubuntu", "s3cret pw")
    assert "s3cret" not in extras.script(plain, "debian", "web01", {}, "ubuntu", "s3cret pw")
    assert "password='s3cret pw'\n" in extras.script(secret, "debian", "web01", {}, "ubuntu", "s3cret pw")
    assert not extras.needs_password([{"id": "plain"}]) and extras.needs_password([{"id": "plain"}, {"id": "secret"}])


def test_linux_first_boot_data_is_cleared_when_an_extra_used_the_password(queued, offered, guest, monkeypatch):
    from app.vsphere import connect

    monkeypatch.setattr(extras, "needs_password", lambda chosen: True)
    guest["status"] = "ok nginx\n"
    r = deploy(chosen=[{"id": "nginx"}])
    run_queued(queued)
    with connect() as vc:
        config = vc.props(vc.require_vm(r.json()["vmName"]), "config.extraConfig")["config.extraConfig"]
    assert {o.key: o.value for o in config}.get("guestinfo.userdata", "") == ""


def test_notes_can_depend_on_options():
    desktop = extras.find("desktop")
    rdp = extras.details({"id": "desktop", "options": {"protocol": "rdp"}}, "192.0.2.7", "ubuntu", "web01")["notes"]
    both = extras.details({"id": "desktop", "options": {"protocol": "both"}}, "192.0.2.7", "ubuntu", "web01")["notes"]
    assert desktop and len(rdp) == 1 and rdp[0].startswith("RDP: connect to 192.0.2.7 as ubuntu")
    assert len(both) == 2 and both[1].startswith("VNC: connect to 192.0.2.7:5901")


def test_domain_shows_only_with_https():
    """The web apps' domain name only matters for their certificate."""
    for i in ("wordpress", "nextcloud"):
        domain = next(o for o in extras.find(i).options if o.id == "domain")
        assert domain.when == {"https": ("yes",)}, i
    assert next(o for o in extras.find("mail").options if o.id == "domain").when == {}  # mail uses it anyway
