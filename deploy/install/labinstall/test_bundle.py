"""The offline bundle's sections and GitHub releases (deploy/sections.sh, release.sh, join.sh,
check-bundle.sh): fingerprints, every file in one section, and a bundle cut into releases and put back
(the core alone, then an add-on later), checked as install.sh checks it. Run with:
pytest deploy/install/labinstall/test_bundle.py
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3]
DEPLOY = SRC / "deploy"


def sh(script: str, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """A bash snippet with deploy/sections.sh sourced; args are $1, $2, …"""
    return subprocess.run(["bash", "-c", f'set -euo pipefail; source "{DEPLOY}/sections.sh"; {script}', "bash", *args],
                          cwd=cwd, capture_output=True, text=True, check=check)


def media_inputs() -> list[str]:
    return sh('echo $MEDIA_INPUTS').stdout.split()


def test_media_inputs_cover_every_file_fetch_media_reads_its_pins_from():
    text = (SRC / "scripts/isos/fetch-media.sh").read_text()
    here = SRC / "scripts/isos"
    read = {"scripts/isos/fetch-media.sh"}
    for m in re.finditer(r'\$here/([A-Za-z0-9_./-]+)', text):
        read.add(str((here / m.group(1)).resolve().relative_to(SRC)))
    # The imported images' scripts ($packer_dir) are imported-images', not media's.
    read = {r for r in read if (SRC / r).is_file() and (not r.startswith("packer/") or r == "packer/windows-server/legacy.ps1")}
    assert read <= set(media_inputs()), read - set(media_inputs())
    for f in media_inputs():
        assert (SRC / f).is_file(), f


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of what the fingerprints are made from."""
    dst = tmp_path / "src"
    for d in ("scripts", "packer"):
        shutil.copytree(SRC / d, dst / d)
    (dst / "backend").mkdir()
    shutil.copy(SRC / "backend/extras.yaml", dst / "backend/extras.yaml")
    return dst


def fp(section: str, src: Path, *extra: str) -> str:
    return sh('fingerprint "$@"', section, str(src), *extra).stdout.strip()


def test_fingerprints_stay_the_same_until_what_decides_them_changes(project: Path):
    before = {s: fp(s, project) for s in ("media", "image-isos", "imported-images")}
    assert before == {s: fp(s, project) for s in before}
    for s, t in before.items():
        assert re.fullmatch(rf"{s}-[0-9a-f]{{6}}", t), t
    # Metasploitable 3 in it is another set of imported images.
    assert fp("imported-images", project, "1") != before["imported-images"]

    prepare = project / "scripts/template/prepare.sh"
    prepare.write_text(prepare.read_text() + "\n# a change\n")
    assert fp("media", project) != before["media"]
    assert fp("image-isos", project) == before["image-isos"]

    extras = project / "backend/extras.yaml"
    text = extras.read_text()
    tag = re.search(r"dockerImage: grafana/grafana:(\S+)", text).group(1)
    extras.write_text(text.replace(f"grafana/grafana:{tag}", "grafana/grafana:0.0.1"))
    assert fp("image-isos", project) != before["image-isos"]
    assert fp("imported-images", project) == before["imported-images"]


def test_office_is_named_by_its_version_and_language(tmp_path: Path):
    office = tmp_path / "office"
    (office / "Office/Data/16.0.17932.21140").mkdir(parents=True)
    (office / "download.xml").write_text('<Configuration><Add><Product><Language ID="en-GB" /></Product></Add></Configuration>')
    assert fp("office", tmp_path, str(office)) == "office-16.0.17932.21140-en-gb"


def write(path: Path, size: int = 3000, seed: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(((seed or path.name) * size).encode()[:size])


def fake_bundle(root: Path) -> Path:
    """A bundle as bundle.sh leaves it: files in every section, sums, SECTIONS, SHA256SUMS."""
    b = root / "bundle"
    for f in ("install.sh", "DOWNLOAD-LATER.md", "images/panel.tar", "debs/noble/a.deb", "repo/docs/a.md"):
        write(b / f)
    for f in ("media/linux/wazuh/w.tar.gz", "media/windows/cloudbase-init/c.msi", "media/windows/office/README.txt",
              "media/images/chr-7.vmdk.zip", "media/windows/office/setup.exe", "media/windows/office/Office/Data/v64.cab",
              "image-isos/lab-image-grafana-1.iso", "image-isos/lab-image-redis-2.iso"):
        write(b / f, 5000)
    (b / "repo/deploy").mkdir(parents=True)
    for f in ("sections.sh", "check-bundle.sh"):
        shutil.copy(DEPLOY / f, b / "repo/deploy" / f)
    tags = {"media": "media-aaaaaa", "imported-images": "imported-images-bbbbbb", "office": "office-16.0.1-en-us",
            "image-isos": "image-isos-cccccc"}
    (b / "SECTIONS").write_text("commit 0123456789abcdef0123456789abcdef01234567\ncore bundle-0123456\n"
                                + "".join(f"{s} {t}\n" for s, t in tags.items()) + "isos -\n")
    for s, t in tags.items():
        sh('write_section_sums "$@"', str(b), s, t)
    sh('write_core_sums "$1"', str(b))
    return b


def files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_every_file_is_in_exactly_one_section(tmp_path: Path):
    b = fake_bundle(tmp_path)
    listed: list[str] = []
    for s in sh('echo $SECTIONS_ALL').stdout.split():
        listed += sh('section_files "$@"', str(b), s).stdout.split()
    # The sums files aren't in a section's list: release.sh puts each in its section's release.
    every = sorted(f for f in files(b) if f != "SHA256SUMS" and not f.startswith("sums/"))
    assert sorted(listed) == every
    assert "media/windows/office/README.txt" in sh('section_files "$@"', str(b), "media").stdout.split()
    assert "media/windows/office/README.txt" not in sh('section_files "$@"', str(b), "office").stdout.split()


def check(bundle: Path, stamps: Path) -> tuple[int, list[str]]:
    r = subprocess.run(["bash", str(bundle / "repo/deploy/check-bundle.sh"), str(bundle), str(stamps)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.splitlines()


def release(bundle: Path, rel: Path) -> None:
    subprocess.run(["bash", str(DEPLOY / "release.sh"), str(bundle), str(rel), "--part-size", "2KB"],
                   check=True, capture_output=True, text=True)


def join(downloads: Path, dest: Path, check_: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(downloads / "join.sh"), str(dest)], cwd=downloads,
                          capture_output=True, text=True, check=check_)


def download(rel: Path, tag: str, into: Path) -> None:
    """A release's files, as GitHub serves them: flat, into one folder."""
    into.mkdir(exist_ok=True)
    for f in (rel / tag).iterdir():
        if f.name != "NOTES.md":
            shutil.copy(f, into / f.name)


def test_releases_put_back_the_bundle_core_first_then_an_add_on(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel)
    assert sorted(p.name for p in rel.iterdir()) == sorted(
        ["bundle-0123456", "media-aaaaaa", "imported-images-bbbbbb", "office-16.0.1-en-us", "image-isos-cccccc", "upload.sh"])
    for d in rel.iterdir():
        if d.is_dir():
            parts = sorted(d.glob(f"{d.name}.tar.*"))
            assert len(parts) > 1 and all(p.stat().st_size <= 2000 for p in parts), d.name
    core = rel / "bundle-0123456"
    assert {"join.sh", "JOIN.md", "NOTES.md", "bundle-0123456.sha256"} <= {p.name for p in core.iterdir()}
    assert "`media-aaaaaa`" in (core / "JOIN.md").read_text()

    # The core alone: what install.sh checks passes, and says what's not there.
    dl, dest, stamps = tmp_path / "dl", tmp_path / "lab-bundle", tmp_path / "stamps"
    download(rel, "bundle-0123456", dl)
    join(dl, dest)
    assert subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=dest).returncode == 0
    code, lines = check(dest, stamps)
    assert code == 0, lines
    assert "info media: not in the bundle (release media-aaaaaa, or DOWNLOAD-LATER.md says how to make it)" in lines
    assert not (dest / "media").exists()

    # An add-on later, into the same folder: then the core and it are as they were made.
    download(rel, "media-aaaaaa", dl)
    join(dl, dest)
    code, lines = check(dest, stamps)
    assert code == 0 and "ok media: media-aaaaaa (3 files)" in lines, lines
    want = {f: v for f, v in files(b).items()
            if not f.startswith(("image-isos/", "media/images/")) and not (f.startswith("media/windows/office/") and not f.endswith("README.txt"))
            and f not in ("sums/imported-images-bbbbbb.sha256", "sums/office-16.0.1-en-us.sha256", "sums/image-isos-cccccc.sha256")}
    assert files(dest) == want

    # Everything: the bundle again, file for file.
    for t in ("imported-images-bbbbbb", "office-16.0.1-en-us", "image-isos-cccccc"):
        download(rel, t, dl)
    join(dl, dest)
    assert files(dest) == files(b)
    code, lines = check(dest, stamps)
    assert code == 0 and all(line.startswith("ok ") for line in lines if not line.startswith("info isos")), lines


def test_a_missing_part_a_damaged_file_and_another_release_are_caught(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel)
    dl, dest, stamps = tmp_path / "dl", tmp_path / "lab-bundle", tmp_path / "stamps"
    download(rel, "bundle-0123456", dl)
    download(rel, "media-aaaaaa", dl)
    (dl / "media-aaaaaa.tar.001").unlink()
    r = join(dl, dest, check_=False)
    assert r.returncode == 1 and "media-aaaaaa: 1 part(s) not downloaded" in r.stderr
    assert (dest / "SHA256SUMS").is_file()  # the core was joined all the same

    download(rel, "media-aaaaaa", dl)
    join(dl, dest)
    (dest / "media/linux/wazuh/w.tar.gz").write_bytes(b"changed")
    code, lines = check(dest, stamps)
    assert code == 1 and any(line.startswith("fail media-aaaaaa: 1 file(s)") for line in lines), lines

    # A media release made from other versions: a warning, not a failure.
    join(dl, dest)
    (dest / "sums/media-aaaaaa.sha256").rename(dest / "sums/media-dddddd.sha256")
    code, lines = check(dest, stamps)
    assert code == 0 and any(line.startswith("warn media: media-dddddd, but this core was made with media-aaaaaa")
                             for line in lines), lines


def test_join_needs_the_core_first(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel)
    dl = tmp_path / "dl"
    download(rel, "media-aaaaaa", dl)
    shutil.copy(DEPLOY / "join.sh", dl / "join.sh")
    r = join(dl, tmp_path / "lab-bundle", check_=False)
    assert r.returncode == 1 and "no core release here" in r.stderr


def test_upload_script_marks_only_the_core_latest(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel)
    up = (rel / "upload.sh").read_text()
    assert subprocess.run(["bash", "-n", str(rel / "upload.sh")]).returncode == 0
    assert "for tag in media-aaaaaa imported-images-bbbbbb office-16.0.1-en-us image-isos-cccccc bundle-0123456" in up
    assert "--target 0123456789abcdef0123456789abcdef01234567" in up
    assert '[[ $tag == bundle-* ]] && latest=--latest' in up


@pytest.mark.skipif(not os.access("/bin/bash", os.X_OK), reason="needs bash")
def test_a_bundle_from_before_sections_isnt_released(tmp_path: Path):
    b = fake_bundle(tmp_path)
    (b / "SECTIONS").unlink()
    r = subprocess.run(["bash", str(DEPLOY / "release.sh"), str(b), str(tmp_path / "rel")], capture_output=True, text=True)
    assert r.returncode == 1 and "older bundle.sh" in r.stderr
