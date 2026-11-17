"""The offline install's manifest (manifest.toml) against the panel's catalogue (backend/templates.yaml):
it loads, and every template the panel can deploy can be built offline. Run with:
pytest deploy/install/labinstall/test_manifest.py
"""

import re
from pathlib import Path

import yaml

from .manifest import Manifest

SRC = Path(__file__).resolve().parents[3]
# Deployable, but not built by the offline install yet (each needs more than an entry). Empty: keep it so.
NOT_YET: set[str] = set()


def test_every_deployable_template_can_be_built_offline():
    m = Manifest(SRC)
    deployable = {f"{e['template']} {e['version']}" for e in yaml.safe_load((SRC / "backend/templates.yaml").read_text())
                  if not e.get("planned")}
    covered = {t.catalogue for t in m.templates.values() if t.catalogue}
    assert deployable - covered == NOT_YET, "templates.yaml has templates manifest.toml doesn't build (or NOT_YET is out of date)"
    assert not NOT_YET & covered


def test_an_iso_named_in_vars_is_the_one_its_isos_name():
    """A build told -var iso=<file> must get the file the install checks is in the ISO folder."""
    m = Manifest(SRC)
    for t in m.templates.values():
        named = [v.split("=", 1)[1] for v in t.vars if v.startswith("iso=")]
        if named:
            assert named == [m.iso_file(ref) for ref in t.isos], t.id


def test_media_files_are_ones_fetch_media_gathers():
    """Each media file a template needs is fetched by fetch-media.sh (by its name or its folder), apart
    from the images imported whole and Parrot's OVA, which come by hand."""
    script = (SRC / "scripts/isos/fetch-media.sh").read_text()
    legacy = (SRC / "packer/windows-server/legacy.ps1").read_text()
    for t in Manifest(SRC).templates.values():
        for f in t.media:
            name = f.rsplit("/", 1)[-1]
            if f.startswith("images/") or re.match(r"freebsd/|linux/zimbra/", f):
                continue  # imported whole, or made by its own step (checked by building)
            assert name in script or name in legacy or f.split("/")[1] in script, f"{t.id}: {f}"


def test_ubuntu_desktop_takes_its_extras_as_desktop_extras():
    """Its build reads the list from desktop_extras (packer/ubuntu); in extras it would be ignored."""
    from types import SimpleNamespace

    from . import checks

    m = Manifest(SRC)
    t = m.templates["ubuntu-desktop-24.04"]
    assert t.extras_var == "desktop_extras" and m.templates["ubuntu-24.04"].extras_var == "extras"
    hcl = (SRC / "packer/ubuntu/ubuntu.pkr.hcl").read_text()
    assert 'variable "desktop_extras"' in hcl
    ctx = SimpleNamespace(manifest=m, cfg=SimpleNamespace(internet=False, mirror=lambda name: ""), media_dir=Path("/nonexistent"),
                          iso_files={iso: 1 for isos in m.image_isos.values() for iso in isos}, bundled_images={})
    item = checks.Item(t)
    for e in t.entry["extras"]:
        (item.extras.append(e) if not checks.extra_missing(ctx, e) else item.left_out.__setitem__(e, "x"))
    item.extra_vars[t.extras_var] = ",".join(item.extras)
    assert "python" in item.left_out and "wazuh-agent" in item.left_out  # their files come from the media folder
    assert "zabbix-agent" in item.left_out  # no zabbix mirror in this config
    assert "docker" in item.extras and "grafana" in item.extras  # their images come on ISOs


def test_the_alpine_repository_has_what_the_alpine_builds_install():
    """Offline, the Alpine template and the capture appliance install only from fetch-media.sh's
    repository: every package their builds add must be in ALPINE_PACKAGES (dependencies come with it)."""
    script = (SRC / "scripts/isos/fetch-media.sh").read_text()
    listed = set(re.search(r'^ALPINE_PACKAGES="([^"]*)"', script, re.M | re.S).group(1).replace("\\\n", " ").split())
    files = [SRC / "packer/alpine/alpine.pkr.hcl", SRC / "packer/capture/capture.pkr.hcl",
             SRC / "scripts/template/alpine/prepare-alpine.sh", SRC / "scripts/capture/prepare-capture.sh"]
    wanted = set()
    for f in files:
        for line in re.findall(r"apk add (?:-q )?([a-z0-9 -]+)", f.read_text()):
            wanted |= set(line.split())
    assert {"open-vm-tools", "tcpdump", "sudo"} <= wanted  # the patterns still find them
    assert wanted <= listed, f"not in fetch-media.sh's ALPINE_PACKAGES: {sorted(wanted - listed)}"
    # The release it fetches is the one the builds install.
    version = re.search(r"^ALPINE_VERSION=(\S+)", script, re.M).group(1)
    for f in files[:2]:
        assert re.search(r'variable "version" \{\s*type\s*= string\s*default = "%s"' % re.escape(version), f.read_text()), f


def test_capture_in_the_build_list_is_the_appliance_not_a_template():
    m = Manifest(SRC)
    assert [t.id for t in m.selected(["capture", "alpine-3.24"])] == ["alpine-3.24"]
    assert "capture" not in m.templates  # it's capture.py's, not a manifest entry


def test_capture_is_built_with_all_or_when_named():
    from types import SimpleNamespace

    from . import capture

    def ctx(build, on=True):
        return SimpleNamespace(cfg=SimpleNamespace(get=lambda t, k: {("templates", "build"): build, ("capture", "build"): on}[(t, k)]))

    assert capture.wanted(ctx(["all"])) and capture.wanted(ctx(["capture"]))
    assert not capture.wanted(ctx(["ubuntu-26.04"])) and not capture.wanted(ctx(["all"], on=False))
    assert capture.ISO in Manifest(SRC).isos


def test_update_env_replaces_or_adds(tmp_path):
    from .envfile import update

    env = tmp_path / "lab-deploy.env"
    env.write_text("# CAPTURE_VM=\nVCENTER_HOST=v\nCAPTURE_VM=old\n")
    update(env, {"CAPTURE_VM": "Labs/Capture/lab-capture", "BUILD_HTTP_IP": "192.0.2.10"})
    assert env.read_text() == "# CAPTURE_VM=\nVCENTER_HOST=v\nCAPTURE_VM=Labs/Capture/lab-capture\nBUILD_HTTP_IP=192.0.2.10\n"


def test_the_freebsd_media_has_what_its_build_installs():
    script = (SRC / "scripts/isos/fetch-media.sh").read_text()
    listed = set(re.search(r"^FREEBSD_PACKAGES=(\S+)", script, re.M).group(1).split(","))
    wanted = set()
    for f in (SRC / "packer/freebsd/installerconfig.pkrtpl", SRC / "scripts/template/freebsd/prepare-freebsd.sh"):
        for line in re.findall(r"pkg install (?:-[a-z]+ )*([a-z0-9 -]+)", f.read_text()):
            wanted |= set(line.split())
    assert {"open-vm-tools-nox11", "sudo", "bash", "curl"} <= wanted
    assert wanted | {"pkg"} == listed
    version = re.search(r"^FREEBSD_VERSION=(\S+)", script, re.M).group(1)
    assert re.search(r'variable "version" \{\s*type\s*= string\s*default = "%s"' % re.escape(version),
                     (SRC / "packer/freebsd/freebsd.pkr.hcl").read_text())
    assert f'"freebsd/{version}-RELEASE/base.txz"' in (SRC / "deploy/install/manifest.toml").read_text()


def test_zabbix_extras_need_their_mirror_offline():
    from types import SimpleNamespace

    from . import checks

    m = Manifest(SRC)
    assert set(m.extras_mirrors) == {"zabbix", "zabbix-agent"}

    def missing(extra, mirrors=None, internet=False):
        cfg = SimpleNamespace(internet=internet, mirror=lambda name: (mirrors or {}).get(name, ""))
        return checks.extra_missing(SimpleNamespace(manifest=m, cfg=cfg, media_dir=Path("/nonexistent"), iso_files={},
                                                    bundled_images={}), extra)

    assert missing("zabbix-agent") == "no zabbix mirror in the config"
    assert missing("zabbix-agent", {"zabbix": "http://mirror.lab.example/zabbix"}) == ""
    assert missing("zabbix", internet=True) == ""


def test_php_versions_are_offered_only_with_their_mirror(tmp_path):
    """Ubuntu 22.04 and 24.04 take PHP 5.6-8.5 from Ondřej Surý's PPA: without its mirror their builds
    leave them out, so the panel's catalogue mustn't offer them. 26.04's PHP is Ubuntu's own."""
    from . import catalogue

    m = Manifest(SRC)
    assert m.choices_mirrors == {"php": "php"}
    with_ppa = [t.id for t in m.templates.values() if "{mirror.php}" in " ".join(t.vars)]
    assert set(with_ppa) == {"ubuntu-22.04", "ubuntu-24.04"}
    state = {"templates": {
        "ubuntu-24.04": {"status": "built", "name": "tpl-ubuntu-24.04-x", "extras": ["apache"], "choices_left_out": ["php"]},
        "ubuntu-22.04": {"status": "built", "name": "tpl-ubuntu-22.04-x", "extras": ["apache"], "choices_left_out": []},
    }}
    catalogue.write(m, state, "Labs/Templates", tmp_path)
    written = {f"{e['template']} {e['version']}": e for e in yaml.safe_load((tmp_path / "templates.yaml").read_text())}
    assert "php" not in (written["ubuntu 24.04"].get("choices") or {})
    assert written["ubuntu 22.04"]["choices"]["php"]  # built with the mirror: kept


def test_extras_waiting_for_their_image_iso_are_offered_once_it_is_there(tmp_path):
    """ELK's, Graylog's and GitLab's image ISOs can come later (DOWNLOAD-LATER.md): their templates are
    built with the extras anyway, and the catalogue offers them only while their ISOs are there."""
    from . import catalogue

    m = Manifest(SRC)
    assert {"elk", "graylog", "gitlab"} <= set(m.image_isos)
    state = {"templates": {"ubuntu-24.04": {"status": "built", "name": "tpl-ubuntu-24.04-x",
                                            "extras": ["apache", "elk", "grafana"]}}}

    def offered(no_image):
        catalogue.write(m, state, "Labs/Templates", tmp_path, no_image)
        rows = yaml.safe_load((tmp_path / "templates.yaml").read_text())
        return next(e for e in rows if f"{e['template']} {e['version']}" == "ubuntu 24.04")["extras"]

    assert offered({"elk", "graylog", "gitlab"}) == ["apache", "grafana"]
    assert offered(set()) == ["apache", "elk", "grafana"]


def test_the_panels_builder_gets_the_install_commands(tmp_path):
    """After an offline install, the panel's own builds (Admin → Templates) run the install's command:
    this network's mirrors and media, the extras it built, and no online prepare scripts."""
    import json
    from types import SimpleNamespace

    from . import catalogue

    m = Manifest(SRC)
    media = tmp_path / "media"
    (media / "images").mkdir(parents=True)
    (media / "images" / "big.ova").write_text("x")
    (media / "windows" / "legacy").mkdir(parents=True)
    (media / "windows" / "legacy" / "OpenSSH.msi").write_text("x")
    cfg = SimpleNamespace(get=lambda t, k: {("media", "port"): 8690}[(t, k)],
                          mirrors=lambda: {"ubuntu": "http://mirror.lab.example/ubuntu", "internet": False})
    ctx = SimpleNamespace(manifest=m, cfg=cfg, media_dir=media, http_ip="192.0.2.10")
    state = {"templates": {
        "ubuntu-24.04": {"status": "built", "name": "x", "extra_vars": {"extras": "nginx,docker"}},
        "windows-server-2016": {"status": "built", "name": "y", "extra_vars": {}},
        "mikrotik": {"status": "built", "name": "z", "extra_vars": {}},  # imported: never rebuilt by the panel
        "ubuntu-22.04": {"status": "failed"},
    }}
    root = tmp_path / "root"
    root.mkdir()
    (root / "lab-deploy.env").write_text("VCENTER_HOST=v\n")
    catalogue.prepare_builder(ctx, state, root)
    builds = json.loads((root / "offline-builds.json").read_text())
    assert set(builds) == {"ubuntu/24.04", "windows-server/2016"}
    ubuntu = builds["ubuntu/24.04"]
    assert ubuntu["argv"][:3] == ["bash", "packer/build.sh", "ubuntu"] and ubuntu["media"] is True
    assert "apt_mirror=http://mirror.lab.example/ubuntu" in ubuntu["argv"] and "media_url=http://192.0.2.10:8690" in ubuntu["argv"]
    assert "extras=nginx,docker" in ubuntu["argv"]
    assert "media_dir=/media" in builds["windows-server/2016"]["argv"] and not builds["windows-server/2016"]["media"]
    assert (root / "build" / "packer" / "build.sh").is_file() and (root / "build" / "scripts").is_dir()
    assert (root / "media" / "windows" / "legacy" / "OpenSSH.msi").is_file() and not (root / "media" / "images").exists()
    env = (root / "lab-deploy.env").read_text()
    assert "BUILD_OFFLINE=/app/offline-builds.json" in env and "BUILD_MEDIA_DIR=/media" in env and "BUILD_HTTP_IP=192.0.2.10" in env
    assert "./offline-builds.json:/app/offline-builds.json:ro" in catalogue.OVERRIDE and "./media:/media:ro" in catalogue.OVERRIDE
