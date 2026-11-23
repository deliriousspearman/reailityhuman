"""The offline bundle's sections and GitHub releases (deploy/sections.sh, release.sh, join.sh,
check-bundle.sh): fingerprints, every file in one section, and a bundle cut into releases and put back
(the core alone, then an add-on later), checked as install.sh checks it. Run with:
pytest deploy/install/labinstall/test_bundle.py
"""

import json
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


def release(bundle: Path, rel: Path, *more: str) -> None:
    subprocess.run(["bash", str(DEPLOY / "release.sh"), str(bundle), str(rel), "--part-size", "2KB", *more],
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
    assert "tags=(media-aaaaaa imported-images-bbbbbb office-16.0.1-en-us image-isos-cccccc bundle-0123456)" in up
    assert "commit=0123456789abcdef0123456789abcdef01234567" in up and "core=bundle-0123456" in up


@pytest.mark.skipif(not os.access("/bin/bash", os.X_OK), reason="needs bash")
def test_a_bundle_from_before_sections_isnt_released(tmp_path: Path):
    b = fake_bundle(tmp_path)
    (b / "SECTIONS").unlink()
    r = subprocess.run(["bash", str(DEPLOY / "release.sh"), str(b), str(tmp_path / "rel")], capture_output=True, text=True)
    assert r.returncode == 1 and "older bundle.sh" in r.stderr


def parts(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if re.search(r"\.tar\.\d{3}$", p.name))


def test_a_release_over_split_over_is_also_offered_split(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel, "--split-over", "5KB")  # so at most 2 parts of 2 KB in each piece
    for d in [d for d in rel.iterdir() if d.is_dir() and "-part" not in d.name]:
        whole = parts(d)
        total = sum((d / p).stat().st_size for p in whole)
        pieces = sorted(rel.glob(f"{d.name}-part*"), key=lambda p: int(p.name.rsplit("-part", 1)[1]))
        if total <= 5000:
            assert not pieces, d.name
            continue
        assert len(pieces) == -(-len(whole) // 2), d.name
        got = [p for piece in pieces for p in parts(piece)]
        assert got == whole, d.name  # every part once, in order
        for piece in pieces:
            assert 1 <= len(parts(piece)) <= 2
            assert sum((piece / p).stat().st_size for p in parts(piece)) <= 5000
            assert (piece / f"{d.name}.sha256").read_bytes() == (d / f"{d.name}.sha256").read_bytes()
            assert all((piece / p).samefile(d / p) for p in parts(piece))  # hard links, not copies
            assert "NOTES.md" in os.listdir(piece) and f"`{d.name}`" in (piece / "NOTES.md").read_text()
    media_pieces = sorted(p.name for p in rel.glob("media-aaaaaa-part*"))
    assert media_pieces, "media should be split at 5KB"
    assert f"`media-aaaaaa-part1` … `{media_pieces[-1]}`" in (rel / "bundle-0123456/JOIN.md").read_text()
    up = (rel / "upload.sh").read_text()
    assert "media-aaaaaa " + " ".join(media_pieces) + " " in up

    # The core and the media pieces (not the whole media release): joined and checked as before.
    dl, dest, stamps = tmp_path / "dl", tmp_path / "lab-bundle", tmp_path / "stamps"
    download(rel, "bundle-0123456", dl)
    download(rel, media_pieces[0], dl)
    r = join(dl, dest, check_=False)
    assert r.returncode == 1 and "media-aaaaaa:" in r.stderr and "not downloaded" in r.stderr
    for p in media_pieces[1:]:
        download(rel, p, dl)
    join(dl, dest)
    code, lines = check(dest, stamps)
    assert code == 0 and "ok media: media-aaaaaa (3 files)" in lines, lines


def test_split_over_zero_never_splits(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel, "--split-over", "0")
    assert not list(rel.glob("*-part*"))
    assert "Or, split" in (rel / "bundle-0123456/JOIN.md").read_text()
    r = subprocess.run(["bash", str(DEPLOY / "release.sh"), str(b), str(tmp_path / "r2"), "--part-size", "2KB",
                        "--split-over", "1KB"], capture_output=True, text=True)
    assert r.returncode == 1 and "can't be less than --part-size" in r.stderr


FAKE_GH = r"""#!/usr/bin/env python3
# gh, as far as upload.sh uses it: releases kept as folders under $FAKE_GH, each call logged.
import hashlib, json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["FAKE_GH"])
args = sys.argv[1:]
with open(root / "calls.log", "a") as log:
    log.write(" ".join(a.rsplit("/", 1)[-1] for a in args) + "\n")
opts, rest, i = {}, [], 2
while i < len(args):
    if args[i] in ("--repo", "--target", "--title", "--notes-file", "--json", "-q"):
        opts[args[i]] = args[i + 1]; i += 2
    else:
        rest.append(args[i]); i += 1
verb, tag = args[1], rest[0]
d = root / "releases" / tag
if verb == "view":
    if not d.is_dir():
        sys.exit(1)
    if opts["--json"] == "assets":
        for f in sorted((d / "assets").iterdir()):
            print(f.name, "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest())
    else:
        print((d / "body").read_text())
    sys.exit(0)
if verb == "create":
    (d / "assets").mkdir(parents=True)
    (d / "meta").write_text(json.dumps({"target": opts["--target"], "latest": "--latest" in rest}))
if verb in ("create", "edit"):
    (d / "body").write_text(Path(opts["--notes-file"]).read_text())
for f in rest[1:]:
    if not f.startswith("-"):
        shutil.copy(f, d / "assets" / Path(f).name)
"""


def test_upload_script_creates_then_mends_releases_with_a_fake_gh(tmp_path: Path):
    b = fake_bundle(tmp_path)
    rel = tmp_path / "rel"
    release(b, rel, "--split-over", "5KB")
    bin_, state = tmp_path / "bin", tmp_path / "gh"
    bin_.mkdir(); state.mkdir()
    (bin_ / "gh").write_text(FAKE_GH)
    (bin_ / "gh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_GH": str(state)}

    def upload() -> list[str]:
        (state / "calls.log").write_text("")
        out = subprocess.run(["bash", str(rel / "upload.sh"), "--repo", "me/it"], env=env, capture_output=True,
                             text=True, check=True).stdout
        return out.splitlines()

    out = upload()
    made = sorted(d.name for d in rel.iterdir() if d.is_dir())
    assert sorted(p.name for p in (state / "releases").iterdir()) == made
    for t in made:
        local = sorted(p.name for p in (rel / t).iterdir() if p.name != "NOTES.md")
        assert sorted(p.name for p in (state / "releases" / t / "assets").iterdir()) == local, t
        meta = json.loads((state / "releases" / t / "meta").read_text())
        assert meta == {"target": "0123456789abcdef0123456789abcdef01234567", "latest": t == "bundle-0123456"}, t
    assert out[-2] == "bundle-0123456: creating it, with " + str(len(os.listdir(rel / "bundle-0123456")) - 1) + " file(s)"

    # Again: nothing to do.
    out = upload()
    assert all(line.endswith(": on GitHub already, as it is here") for line in out[:-1]), out
    assert not any(" create " in c or " upload " in c or " edit " in c
                   for c in (state / "calls.log").read_text().splitlines())

    # A cut-short upload, a changed JOIN.md and new notes: just those are mended.
    (state / "releases/media-aaaaaa/assets/media-aaaaaa.tar.001").unlink()
    (rel / "bundle-0123456/JOIN.md").write_text("changed")
    (rel / "office-16.0.1-en-us/NOTES.md").write_text("new notes")
    out = upload()
    calls = [c for c in (state / "calls.log").read_text().splitlines() if " view " not in c]
    # (The core's pieces share its JOIN.md, hard linked, so theirs changed too. The log keeps paths' last part.)
    core_pieces = [p.name for p in rel.glob("bundle-0123456-part*")]
    assert core_pieces
    assert sorted(calls) == sorted([
        "release upload media-aaaaaa --repo it --clobber media-aaaaaa.tar.001",
        "release upload bundle-0123456 --repo it --clobber JOIN.md",
        "release edit office-16.0.1-en-us --repo it --notes-file NOTES.md --latest=false",
    ] + [f"release upload {p} --repo it --clobber JOIN.md" for p in core_pieces]), calls
    assert (state / "releases/bundle-0123456/assets/JOIN.md").read_text() == "changed"
    assert (state / "releases/office-16.0.1-en-us/body").read_text() == "new notes"
