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


def test_container_extras_run_their_image():
    """Each extra that runs a container (lab_docker <its id> ... <image>) declares that image as its
    `dockerImage`, by the same name: the panel attaches its ISO, and the clone can't pull (--pull never)."""
    run = {}
    for x in extras.extras().values():
        script = x.families.get("debian", ("", ""))[1]
        if "lab_docker" in script:
            # The extra's own container (lab_docker <its id> ..., continued over "\" lines).
            if command := re.search(rf"lab_docker {re.escape(x.id)} .*?(?<!\\)\n", script, re.S):
                run[x.id] = command.group(0).split()
    assert run, "no extra runs a container"
    # Every extra with images runs them (an extra with several, e.g. ELK, a container each, named for what it runs).
    for x in extras.extras().values():
        if x.images:
            words = x.families["debian"][1].split()
            assert "lab_docker" in words, x.id
            for image in x.images:
                assert image in words, f"{x.id} doesn't run its image {image}"
    for extra_id, words in run.items():
        assert extras.find(extra_id).image in words, f"{extra_id}'s lab_docker doesn't run its dockerImage"


def test_templates_no_longer_bake_images():
    text = _prepare_sh().read_text()
    assert "DOCKER_IMAGES" not in text and "docker pull" not in text


def test_image_isos_are_named_as_fetch_images_names_them(tmp_path):
    import os
    import subprocess

    script = _prepare_sh().parents[1] / "isos" / "fetch-images.sh"
    out = subprocess.run(
        ["bash", str(script), "--list"], capture_output=True, text=True, check=True, env={**os.environ, "EXTRAS_YAML": str(extras._path())}
    ).stdout
    listed = {line.split()[0]: line.split()[-1] for line in out.splitlines()}
    assert listed == {
        **{x.id: extras.image_iso(x) for x in extras.extras().values() if x.image},
        **{x.id: x.media_iso for x in extras.extras().values() if x.media_iso},
    }
    # Winlogbeat sends to ELK's Logstash: the same version.
    assert extras.find("winlogbeat").media_iso == f"lab-media-winlogbeat-{extras.find('elk').image.rsplit(':', 1)[1]}.iso"
    # Several images: the name has a hash of them all, so changing any one is a new ISO.
    elk = extras.find("elk")
    assert len(elk.images) == 3 and elk.image == elk.images[0]
    assert re.fullmatch(r"lab-image-elk-9\.5\.5-[0-9a-f]{6}\.iso", extras.image_iso(elk))
    assert extras.image_iso(replace(elk, images=(*elk.images[:2], "logstash:9.5.6"))) != extras.image_iso(elk)
    assert extras.image_iso(replace(extras.find("grafana"), image="registry.lab.example:5000/team/app")) == "lab-image-grafana-latest.iso"


def test_docker_extras_get_their_image_and_iso():
    grafana = extras.find("grafana")
    text = extras.script(grafana, "debian", "web01", {"sample_data": "no"}, "jo", "pw")
    assert f"lab_image={grafana.image}" in text and f"lab_image_iso={extras.image_iso(grafana)}" in text
    assert "lab_image=" not in extras.script(extras.find("nginx"), "debian", "web01", {}, "jo")
    chosen = [{"id": "grafana", "options": {}}, {"id": "nginx", "options": {}}]
    assert extras.media(chosen, "debian") == [extras.image_iso(grafana)]
    assert extras.media(chosen, "legacy") == []
    assert extras.media([{"id": "winlogbeat", "options": {}}], "windows") == ["lab-media-winlogbeat-9.5.5.iso"]
    # Prometheus's example data runs Node Exporter: its CD goes in too, once.
    prometheus, exporter = (extras.image_iso(extras.find(i)) for i in ("prometheus", "node-exporter"))
    assert extras.media([{"id": "prometheus", "options": {}}], "debian") == [prometheus, exporter]
    assert extras.media([{"id": "prometheus", "options": {}}, {"id": "node-exporter", "options": {}}], "debian") == [prometheus, exporter]
    # k3s: files, not images.
    assert extras.media([{"id": "k3s", "options": {}}], "debian") == [extras.find("k3s").media_iso]


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
    """One web service per machine; FTP, the desktop and Docker itself go with anything. MariaDB and
    MySQL take port 3306, as do WordPress and Nextcloud's own MariaDB. Vaultwarden is HTTPS only, so
    it only clashes with what uses 443."""
    found = {i: set(x.conflicts) for i, x in extras.extras().items()}
    web = {"nginx", "apache", "apache-https", "wordpress", "nextcloud", "nextcloud-snap", "mail", "iredmail", "zimbra", "iis",
           "juice-shop", "dvwa", "uptime-kuma", "grafana", "gitea", "gitlab", "zabbix", "k3s", "freeipa", "adcs"}
    https = {"apache-https", "wordpress", "nextcloud", "nextcloud-snap", "mail", "iredmail", "zimbra", "vaultwarden", "wazuh", "k3s", "freeipa"}
    mysql_port = {"wordpress", "nextcloud", "mariadb", "mysql"}
    for i in web | mysql_port:
        expected = (web if i in web else set()) | (mysql_port if i in mysql_port else set()) | (https if i in https else set())
        if i == "freeipa":
            expected |= {"domain-controller", "additional-dc"}  # DNS, Kerberos and LDAP, as a domain controller's
        assert found[i] == expected - {i}, i
    assert found["vaultwarden"] == https - {"vaultwarden"}
    # The Wazuh server's indexer is on 9200, like Elasticsearch; its agents' port 1514 is Graylog's syslog.
    assert found["wazuh"] == (https - {"wazuh"}) | {"elk", "graylog"}
    # Remote Desktop's port: the desktop extra, and Ubuntu Desktop 26.04's own Remote Login (never both
    # on one template).
    assert found["desktop"] == {"gnome-remote-login"} and found["gnome-remote-login"] == {"desktop"}
    for i in ("ftp", "outlook", "postgresql", "sqlite", "mssql", "docker", "python", "wazuh-agent", "zabbix-agent",
              "prometheus", "node-exporter", "redis", "mongodb"):
        assert found[i] == set(), i
    # Port 9000: MinIO's and Graylog's.
    assert found["minio"] == {"graylog"}
    # Port 8080: Jenkins and Tomcat.
    assert found["jenkins"] == {"tomcat"} and found["tomcat"] == {"jenkins"}


DATABASES = ("postgresql", "mariadb", "mysql", "sqlite", "mssql")


def test_databases_can_be_filled_with_dummy_data():
    for i in DATABASES:
        x = extras.find(i)
        assert x.category == "Databases"
        [option] = x.options
        assert (option.id, option.type, option.default) == ("sample_data", "boolean", "no")
        [c] = extras.resolve((i,), [{"id": i}], "db01")
        assert c["options"] == {"sample_data": "no"}
        [c] = extras.resolve((i,), [{"id": i, "options": {"sample_data": "true"}}], "db01")
        assert c["options"] == {"sample_data": "yes"}
        assert any("chinook" in text.lower() for text, when in x.notes if when == {"sample_data": ("yes",)}), i
    assert extras.details({"id": "postgresql", "options": {"sample_data": "no"}}, "192.0.2.5", "ubuntu", "db01")["notes"] == [
        "Connect to 192.0.2.5 port 5432 as ubuntu, with the machine's password, e.g. psql -h 192.0.2.5 -U ubuntu."
    ]


def test_dummy_data_is_what_the_templates_bake_in():
    """Each Linux database loads a Chinook file prepare.sh fetches; SQL Server, the one prepare.ps1 does."""
    prepare = _prepare_sh().read_text()
    fetched = set(re.findall(r"^\tfetch_chinook (\S+) [0-9a-f]{64}$", prepare, re.M))
    for i in ("postgresql", "mariadb", "mysql", "sqlite"):
        _, body = extras.find(i).families["debian"]
        used = set(re.findall(r"/opt/lab-deploy/chinook/(\S+?)(?=[\s\"]|$)", body))
        assert used and used <= fetched, (i, used)
        bake = re.search(rf"^bake_{i}\(\) {{\n(.*?)^}}", prepare, re.M | re.S)
        assert bake and any(f in bake.group(1) for f in used), f"bake_{i} doesn't fetch {used}"
    assert "Dir::Cache::archives=/opt/lab-deploy/mysql" in prepare
    assert "Dir::Cache::archives=/opt/lab-deploy/mysql" in extras.find("mysql").families["debian"][1]
    _, body = extras.find("mssql").families["windows"]
    prepare_ps1 = _prepare_sh().with_name("prepare.ps1").read_text()
    source = re.search(r"\$src = '([^']+)'", body).group(1)
    assert f"$SqlServerDir = '{source}'" in prepare_ps1
    chinook_dir = re.search(r"\$ChinookDir = '([^']+)'", prepare_ps1).group(1)
    assert f"'{chinook_dir}\\Chinook_SqlServer.sql'" in body and "Chinook_SqlServer.sql" in prepare_ps1


def test_sql_strings_are_quoted_for_each_database():
    import subprocess

    def quoted(value: str, *mode: str) -> str:
        run = subprocess.run(["bash", "-c", extras.LIB + '\nlab_sql_string "$@"', "lib", value, *mode], capture_output=True, text=True, check=True)
        return run.stdout

    assert quoted("plain") == "'plain'"
    assert quoted("it's a\\b") == "'it''s a\\b'"  # PostgreSQL: backslashes as they are
    assert quoted("it's a\\b", "mysql") == "'it''s a\\\\b'"
    assert quoted("$(reboot) `x`") == "'$(reboot) `x`'"


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
    assert c == {"id": "apache-https", "options": {"domain": "web01", "php": "none"}}
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
    # None chosen: the runner alone, which writes an empty status file (the sign first boot is done).
    none = extras.cloud_config([], "debian", "web01")
    assert none["runcmd"] == [["bash", f"{extras.DIR}/extras/run.sh"]]
    assert [f["path"] for f in none["write_files"]] == [f"{extras.DIR}/extras/run.sh"]

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
    assert https["conflicts"] == ["nginx", "apache", "wordpress", "nextcloud", "nextcloud-snap", "mail", "iredmail", "zimbra", "juice-shop", "dvwa", "uptime-kuma", "grafana", "vaultwarden", "gitea", "k3s", "gitlab", "wazuh", "zabbix", "iis", "adcs", "freeipa"]
    assert https["options"][0]["id"] == "domain" and https["options"][0]["default"] == "{fqdn}"


def test_a_template_sets_up_its_always_extras_on_every_machine(queued, monkeypatch):
    """Ubuntu Desktop 26.04's Remote Login: added to every machine, never chosen, and its password
    cleared from vCenter afterwards like any extra that gets it."""
    from dataclasses import replace

    tpl = catalogue.catalogue()[("ubuntu", "26.04")]
    monkeypatch.setitem(catalogue.catalogue(), ("ubuntu", "26.04"), replace(tpl, always=("gnome-remote-login",)))
    r = deploy("desk01", [{"id": "python", "options": {}}])
    assert r.status_code == 201, r.text
    assert [x["id"] for x in r.json()["extras"]] == ["gnome-remote-login", "python"]
    from app.db import session
    from app.models import Machine

    with session() as s:
        assert extras.needs_password(s.query(Machine).filter(Machine.name == "desk01").one().extras)
    r = deploy("desk02", [{"id": "gnome-remote-login", "options": {}}])
    assert r.status_code == 422 and "isn't an extra this template offers" in r.json()["detail"]
    queued.clear()


def test_config_lists_every_service_and_where_it_runs(offered):
    services = {s["id"]: s for s in client.get("/api/config").json()["services"]}
    # Not those templates set up themselves (hidden).
    assert set(services) == {i for i, x in extras.extras().items() if not x.hidden} and "gnome-remote-login" in extras.extras()
    assert services["nginx"]["category"] == "Web servers" and services["nginx"]["ports"] == [80]
    assert {"template": "ubuntu", "version": "26.04", "ready": True} in services["nginx"]["offeredBy"]
    iis = services["iis"]["offeredBy"]
    assert {"template": "windows-server", "version": "2025", "ready": True} in iis
    assert {"template": "windows-server", "version": "2025 Core", "ready": True} in iis


def test_planned_templates_cant_be_deployed(monkeypatch):
    from dataclasses import replace

    from app import catalogue

    future = replace(catalogue.find("kali", "2026.2"), version="2027.1", vsphere="", planned=True)
    monkeypatch.setattr(catalogue, "planned", lambda: (future,))
    r = client.post(
        "/api/machines", json={"template": "kali", "version": "2027.1", "owner": "jo", "name": "kali01", "hours": 2}
    )
    assert r.status_code in (400, 404, 422), r.text


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
        {"id": "apache-https", "name": "Apache + HTTPS", "options": {"domain": "intranet.lab.example", "php": "none"}, "docker": False, "links": [], "notes": []}
    ]  # links once it has an address
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running"
    texts = [line["text"] for line in m["log"]]
    assert "With Apache + HTTPS (domain name intranet.lab.example)" in texts
    assert "Installing extras: Apache + HTTPS…" in texts
    assert "Apache + HTTPS is ready" in texts
    assert guest["reads"] == [("ubuntu", extras.STATUS_FILE)]


@pytest.fixture
def media(monkeypatch):
    """The ISO folder's files, and the image CDs attached and taken out, by VM."""
    state = {"isos": set(), "attached": [], "removed": 0}
    monkeypatch.setattr(VCenter, "iso_files", lambda self: state["isos"])
    monkeypatch.setattr(VCenter, "attach_media", lambda self, vm, isos: state["attached"].append(list(isos)) if isos else None)

    def remove(self, vm):
        state["removed"] += 1
        return 1

    monkeypatch.setattr(VCenter, "remove_media", remove)
    key = ("ubuntu", "26.04")
    monkeypatch.setitem(catalogue.catalogue(), key, replace(catalogue.catalogue()[key], extras=(*ALL, "grafana")))
    return state


def test_docker_extras_get_their_image_cd(queued, guest, media):
    iso = extras.image_iso(extras.find("grafana"))
    media["isos"] = {iso}
    guest["status"] = "ok grafana\n"
    r = deploy(chosen=[{"id": "grafana"}])
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running", m["log"]
    assert media["attached"] == [[iso]] and media["removed"] == 1
    assert f"Attached 1 image CD: {iso}" in [line["text"] for line in m["log"]]

    # A reset attaches the same ones again: the snapshot is from before they went in.
    assert client.post(f"/api/machines/{m['id']}/reset").status_code < 300
    run_queued(queued)
    assert media["attached"] == [[iso], [iso]] and media["removed"] == 2


def test_a_missing_image_iso_fails_the_deploy_before_cloning(queued, guest, media):
    r = deploy(chosen=[{"id": "grafana"}])
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert f"{extras.image_iso(extras.find('grafana'))} is not in the datastore's ISO folder" in m["log"][-1]["text"]
    assert media["attached"] == []


def test_no_image_cds_without_docker_extras(queued, guest, media):
    guest["status"] = "ok nginx\n"
    r = deploy(chosen=[{"id": "nginx"}])
    run_queued(queued)
    assert client.get(f"/api/machines/{r.json()['id']}").json()["state"] == "running"
    assert media["attached"] == [] and media["removed"] == 0


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


def test_no_extras_still_waits_for_first_boot(queued, guest):
    """Without extras too: ready means its user and SSH are set up, not just that it has an address
    (Parrot's desktop gets one a few minutes before)."""
    guest["status"] = ""
    r = deploy()
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "running"
    assert guest["reads"] == [("ubuntu", extras.STATUS_FILE)]
    assert "Finishing setting up (its user and SSH)…" in [line["text"] for line in m["log"]]


def test_first_boot_that_never_finishes_times_out(queued, guest, monkeypatch):
    monkeypatch.setattr(settings(), "extras_timeout_seconds", 0)
    r = deploy()
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert m["log"][-1]["text"].startswith("Deploy failed: It didn't finish setting up within")


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


def test_extras_needing_more_memory_get_it(monkeypatch):
    """A machine gets its template's memory, or an extra's minimum where that's more."""
    from app.extras import Extra

    desktop = Extra("desktop", "Desktop", "", min_memory_gb=4)
    monkeypatch.setattr(extras, "extras", lambda: {"desktop": desktop})
    assert extras.memory_gb(2, [{"id": "desktop"}]) == 4
    assert extras.memory_gb(8, [{"id": "desktop"}]) == 8
    assert extras.memory_gb(2, []) == 2


def test_disk_is_a_clones_own_plus_its_extras(monkeypatch):
    from app.config import settings
    from app.extras import Extra

    monkeypatch.setattr(settings(), "clone_disk_gb", 10)
    big = Extra("big", "Big", "", disk_gb=20)
    monkeypatch.setattr(extras, "extras", lambda: {"big": big})
    assert extras.disk_gb([]) == 10
    assert extras.disk_gb([{"id": "big"}]) == 30


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


def test_machines_show_the_memory_their_extras_gave_them():
    """A machine's record has its real memory: a Wazuh server on 2 GB Ubuntu got 4 GB."""
    from app.api import machine_out
    from app.models import Machine

    m = Machine(id="m-0001", name="siem", template="ubuntu", version="24.04", owner="e2e", state="running",
                vm_name="e2e-siem-0001", username="ubuntu", password="x", extras=[{"id": "wazuh", "options": {}}])
    assert machine_out(m, log=False)["memoryGB"] == 4
    assert machine_out(m, log=False)["cpu"] == 4
    m.extras = []
    assert machine_out(m, log=False)["memoryGB"] == 2
    assert machine_out(m, log=False)["cpu"] == 2


# PHP versions (a per-template choice) -----------------------------------------------------------------


def test_php_versions_are_those_prepare_sh_bakes():
    versions = re.search(r'^PHP_VERSIONS="([^"]*)"', _prepare_sh().read_text(), re.M).group(1).split()
    php = next(o for o in extras.find("apache").options if o.id == "php")
    assert php.per_template and php.default == "none"
    assert [v for v, _ in php.choices if v != "none"] == versions
    assert php.choices == next(o for o in extras.find("apache-https").options if o.id == "php").choices


def test_a_template_offers_only_its_own_php_versions(queued, monkeypatch):
    """The PHP option shows the versions the template lists (its choices), refuses others, and isn't
    shown at all where a template lists none."""
    key = ("ubuntu", "26.04")
    monkeypatch.setitem(catalogue.catalogue(), key, replace(catalogue.catalogue()[key], choices={"php": ("7.4", "8.5")}))
    t = next(t for t in client.get("/api/config").json()["templates"] if (t["template"], t["version"]) == key)
    php = next(o for o in next(x for x in t["extras"] if x["id"] == "apache")["options"] if o["id"] == "php")
    assert [c["value"] for c in php["choices"]] == ["none", "7.4", "8.5"]

    r = deploy("php01", [{"id": "apache", "options": {"php": "5.6"}}])
    assert r.status_code == 422 and "isn't one of the choices for php on this template" in r.json()["detail"]
    r = deploy("php02", [{"id": "apache", "options": {"php": "7.4"}}])
    assert r.status_code == 201, r.text
    assert next(x for x in r.json()["extras"] if x["id"] == "apache")["options"]["php"] == "7.4"
    queued.clear()

    monkeypatch.setitem(catalogue.catalogue(), key, replace(catalogue.catalogue()[key], choices={}))
    t = next(t for t in client.get("/api/config").json()["templates"] if (t["template"], t["version"]) == key)
    assert "php" not in {o["id"] for o in next(x for x in t["extras"] if x["id"] == "apache")["options"]}


def test_apache_switches_on_the_php_chosen():
    config = extras.cloud_config(extras.resolve(("apache",), [{"id": "apache", "options": {"php": "8.5"}}], "web01", {"php": ("8.5",)}), "debian", "web01")
    script = next(f["content"] for f in config["write_files"] if f["path"].endswith("/apache.sh"))
    assert "php=8.5" in script.replace("'", "") and 'lab_php "$php"' in script
    lib = next(f["content"] for f in config["write_files"] if f["path"].endswith("/lib.sh"))
    assert "lab_php()" in lib and "a2enmod -q mpm_prefork" in lib
