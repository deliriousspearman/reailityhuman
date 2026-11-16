"""The extras' image ISOs in the offline install (images.py): which each extra needs, how a missing one
leaves its extra out, and uploading those the datastore lacks. Run with:
pytest deploy/install/labinstall/test_images.py
"""

from pathlib import Path
from types import SimpleNamespace

import yaml

from . import checks, images
from .manifest import Manifest

SRC = Path(__file__).resolve().parents[3]


def docker_extras() -> dict[str, dict]:
    entries = yaml.safe_load((SRC / "backend/extras.yaml").read_text())
    return {e["id"]: e for e in entries if e.get("dockerImage") or e.get("dockerImages") or e.get("mediaIso")}


def test_every_docker_and_media_extra_needs_its_iso():
    need = images.needed(SRC)
    assert set(need) == set(docker_extras())
    for extra, isos in need.items():
        assert isos[0].startswith((f"lab-image-{extra}-", f"lab-media-{extra}-")) and isos[0].endswith(".iso"), extra
    # Prometheus starts Node Exporter: both CDs go in.
    assert need["prometheus"][1:] == need["node-exporter"]
    assert need["k3s"] == [docker_extras()["k3s"]["mediaIso"]]


def test_the_manifest_has_them_and_no_image_files_in_the_media_folder():
    m = Manifest(SRC)
    assert m.image_isos == images.needed(SRC)
    assert not [need for needs in m.extras_media.values() for need in needs if need.startswith("linux/docker/")]


def ctx(iso_files=None, bundled=None, need=None):
    return SimpleNamespace(
        manifest=SimpleNamespace(image_isos=need or {"grafana": ["g.iso"], "prometheus": ["p.iso", "n.iso"]}, extras_media={},
                                 extras_online_only={}, extras_mirrors={}),
        cfg=SimpleNamespace(internet=False, get=lambda *a: "ISO", mirror=lambda name: ""),
        media_dir=Path("/nonexistent"),
        iso_files=dict(iso_files or {}),
        bundled_images=dict(bundled or {}),
    )


def test_an_extra_is_left_out_only_when_an_iso_is_nowhere():
    c = ctx(iso_files={"g.iso": 5}, bundled={"p.iso": 7})
    assert checks.extra_missing(c, "grafana") == ""  # on the datastore
    assert "no n.iso in the ISO folder or the bundle" in checks.extra_missing(c, "prometheus")  # its second CD
    c.bundled_images["n.iso"] = 3
    assert checks.extra_missing(c, "prometheus") == ""  # in the bundle: uploaded before deploys
    assert checks.extra_missing(c, "wordpress") == ""  # no ISO: only its media and mirror matter


def test_uploads_what_the_datastore_lacks(tmp_path, monkeypatch):
    for name in ("g.iso", "p.iso", "n.iso", "stray.iso"):
        (tmp_path / name).write_bytes(b"x" * 4)
    monkeypatch.setattr(images, "BUNDLE", tmp_path)
    # p.iso is there with another size: made at another time, whole all the same (uploads are renamed
    # into place once complete), so it stays.
    c = ctx(iso_files={"g.iso": 4, "p.iso": 2}, bundled=images.bundled(tmp_path))
    assert images.to_upload(c) == ["n.iso"]  # not stray.iso either: no extra needs it
    sent = []
    c.inv = "inv"
    c.vc = SimpleNamespace(upload_file=lambda inv, local, path: sent.append((local.name, path)))
    assert images.upload(c) == []
    assert sent == [("n.iso", "ISO/n.iso")]
    assert images.to_upload(c) == []  # recorded as there now
