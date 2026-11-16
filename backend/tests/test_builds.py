"""Templates on demand (app/builds.py): recipes, deleting a template no machine uses, deploying it while
it isn't built (the build first, then the deploy), and builds that fail. Packer itself doesn't run
here: `builds.build` is replaced by one that makes the template in vcsim."""

import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pyVmomi import vim

from app import actions, builds, catalogue, jobs
from app.api import app
from app.config import settings
from app.db import session
from app.models import Job, Machine, TemplateBuild, utcnow
from app.vsphere import VCenter, connect, wait

from .conftest import TEMPLATE, run_queued

client = TestClient(app)
ISO = "ubuntu-22.04.5-live-server-amd64.iso"


def _packer_dir() -> Path:
    for candidate in (Path(__file__).resolve().parents[2] / "packer", Path("/packer")):
        if candidate.is_dir():
            return candidate
    pytest.skip("packer/ isn't reachable from here")


def test_every_recipe_points_at_a_real_build():
    """Each recipe's directory has a Packer template declaring every variable it sets, and its prepare
    scripts exist."""
    packer = _packer_dir()
    recipes = [t for t in catalogue.catalogue().values() if t.build]
    assert len(recipes) > 40
    for t in recipes:
        hcl = "".join(p.read_text() for p in (packer / t.build.packer).glob("*.pkr.hcl"))
        assert hcl, f"{t.template} {t.version}: no packer/{t.build.packer}"
        declared = set(re.findall(r'^variable "([a-z_0-9]+)"', hcl, re.M))
        assert not set(t.build.vars) - declared, f"{t.template} {t.version}: {set(t.build.vars) - declared} not declared"
        for script in t.build.prepare:
            assert (packer.parent / script).is_file(), script


@pytest.mark.parametrize(
    "recipe, problem",
    [
        ({"isos": ["a.iso"]}, "packer:"),
        ({"packer": "../x", "isos": ["a.iso"]}, "packer:"),
        ({"packer": "ubuntu", "isos": ["a.iso"], "vars": {"iso": "a.iso; rm -rf /"}}, "plain name and value"),
        ({"packer": "ubuntu"}, "isos"),
        ({"packer": "ubuntu", "isos": ["ISO/a.iso"]}, "isos"),
        ({"packer": "ubuntu", "isos": ["a.iso"], "prepare": ["/etc/x.sh"]}, "prepare"),
    ],
)
def test_bad_recipes_are_refused(recipe, problem):
    with pytest.raises(ValueError, match=problem):
        catalogue._recipe("x 1", recipe)


def test_packer_gets_the_panels_settings(monkeypatch):
    monkeypatch.setenv("BUILD_HTTP_IP", "192.0.2.10")
    settings.cache_clear()
    try:
        text = builds.pkrvars(settings())
    finally:
        settings.cache_clear()
    assert 'datacenter = "DC0"' in text and 'vcenter_insecure = true' in text and 'http_ip = "192.0.2.10"' in text
    assert "password" not in text  # it goes in the credentials file build.sh reads
    tpl = catalogue.find("ubuntu", "24.04")
    cmd = builds.command(tpl, 57)
    assert cmd[:7] == ["bash", "packer/build.sh", "ubuntu", "-var", "version=24.04", "-var", "iso=ubuntu-24.04.5-live-server-amd64.iso"]
    assert re.fullmatch(r"vm_name=tpl-ubuntu-24.04-\d{8}-j57", cmd[-1]) and builds.BUILD_VM.match(cmd[-1].split("=")[1])
    assert builds.vm_name(catalogue.find("windows-server", "2012 R2"), 3).startswith("tpl-windows-server-2012-r2-")


def test_a_cut_off_build_is_cleaned_up_by_the_next():
    with connect() as vc:
        src = vc.template(TEMPLATE)
        spec = vim.vm.CloneSpec(location=vim.vm.RelocateSpec(pool=vc.pool, datastore=vc.datastore), powerOn=True, template=False)
        wait(src.CloneVM_Task(folder=vc.template_folder, name="tpl-ubuntu-22.04-20261028-j5", spec=spec), "Clone")
        assert builds.clean_cut_off_builds(vc, 6) == ["tpl-ubuntu-22.04-20261028-j5"]
        assert builds.clean_cut_off_builds(vc, 6) == []
        assert TEMPLATE.rsplit("/", 1)[-1] in vc.templates()  # templates stay


# A throwaway template ---------------------------------------------------------------------------------

THROWAWAY = "Labs/Templates/tpl-throwaway"


def _make_template(vc: VCenter, name: str) -> None:
    """A template in Labs/Templates with a "clean" snapshot, cloned from the session's Ubuntu one."""
    src = vc.template(TEMPLATE)
    spec = vim.vm.CloneSpec(location=vim.vm.RelocateSpec(pool=vc.pool, datastore=vc.datastore), powerOn=False, template=False)
    vm = wait(src.CloneVM_Task(folder=vc.template_folder, name=name, spec=spec), "Clone")
    wait(vm.CreateSnapshot_Task(name="clean", description="", memory=False, quiesce=False), "Snapshot")
    vm.MarkAsTemplate()


@pytest.fixture
def throwaway(monkeypatch):
    """Ubuntu 22.04 in the catalogue points at tpl-throwaway, which is made in vcsim (and deleted after);
    its ISO is in the ISO folder."""
    with connect() as vc:
        if vc._path(f"DC0/vm/{THROWAWAY}") is None:
            _make_template(vc, THROWAWAY.rsplit("/", 1)[-1])
    live = dict(catalogue.catalogue())
    live[("ubuntu", "22.04")] = tpl = replace(live[("ubuntu", "22.04")], vsphere=THROWAWAY)
    monkeypatch.setattr(catalogue, "catalogue", lambda: live)
    monkeypatch.setattr(VCenter, "iso_files", lambda self: {ISO})
    yield tpl
    with connect() as vc:
        for name in vc.templates():
            if name.startswith("tpl-throwaway"):
                # As the panel does: a template destroyed as one leaves vcsim's hosts listing it.
                vc.delete_template(f"Labs/Templates/{name}")


@pytest.fixture
def builds_queued(monkeypatch):
    """Captures deferred builds; run them with run_builds()."""
    deferred: list[dict] = []

    class Deferrer:
        def defer(self, **kwargs):
            deferred.append(kwargs)

    class FakeTask:
        def configure(self, **_):
            return Deferrer()

    monkeypatch.setattr(jobs, "template_build", FakeTask())
    return deferred


def run_builds(deferred: list[dict]) -> None:
    while deferred:
        builds.run_build(**deferred.pop(0), enqueue=jobs.enqueue)


def fake_packer(monkeypatch, name="tpl-throwaway-rebuilt"):
    """builds.build as Packer would: a new template, at a new (date-stamped) name."""

    def build(job_id, tpl, log_path):
        with connect() as vc:
            _make_template(vc, name)
        return f"Labs/Templates/{name}"

    monkeypatch.setattr(builds, "build", build)


def deploy_2204(name="old01"):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "22.04", "owner": "jo", "name": name, "hours": 2})
    assert r.status_code == 201, r.text
    return r.json()


def test_templates_lists_what_can_be_deleted(throwaway):
    rows = {(t["template"], t["version"]): t for t in client.get("/api/templates").json()}
    t = rows[("ubuntu", "22.04")]
    assert t["state"] == "built" and t["deletable"] and t["build"]["isos"] == [{"name": ISO, "present": True}]
    assert t["sizeGB"] is not None
    # No recipe (an import): it stays.
    assert not rows[("metasploitable", "2")]["deletable"] and "no build recipe" in rows[("metasploitable", "2")]["cantDelete"]
    # Its ISO isn't there.
    assert "not in the datastore's ISO folder" in rows[("ubuntu", "24.04")]["cantDelete"]


def test_delete_then_deploy_builds_it_first(throwaway, queued, builds_queued, monkeypatch):
    r = client.delete("/api/templates/ubuntu/22.04")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "deleted"
    with connect() as vc:
        assert "tpl-throwaway" not in vc.templates()
    assert client.delete("/api/templates/ubuntu/22.04").status_code == 409  # isn't built
    cfg = {(t["template"], t["version"]): t for t in client.get("/api/config").json()["templates"]}
    assert cfg[("ubuntu", "22.04")]["built"] is False and cfg[("ubuntu", "22.04")]["buildMinutes"] == throwaway.build.minutes

    # Deploying it: the machine waits, and one build is queued, however many deploys ask.
    m = deploy_2204()
    deploy_2204("old02")
    assert m["state"] == "deploying" and not queued
    assert len(builds_queued) == 1
    assert "Building it first" in client.get(f"/api/machines/{m['id']}").json()["log"][-1]["text"]

    fake_packer(monkeypatch)
    run_builds(builds_queued)
    with session() as s:
        row = s.get(TemplateBuild, ("ubuntu", "22.04"))
        assert row.state == "built" and row.vsphere == "Labs/Templates/tpl-throwaway-rebuilt"
        assert s.query(Job).filter_by(kind="build").one().state == "done"
    assert len(queued) == 2  # both deploys
    run_queued(queued)
    m = client.get(f"/api/machines/{m['id']}").json()
    assert m["state"] == "running"
    assert any("Cloned from ubuntu/22.04" in line["text"] for line in m["log"])

    # Machines use it now: it can't be deleted.
    r = client.delete("/api/templates/ubuntu/22.04")
    assert r.status_code == 409 and "2 machines use it" in r.json()["detail"]


def test_a_failed_build_fails_the_waiting_machines(throwaway, queued, builds_queued, monkeypatch):
    assert client.delete("/api/templates/ubuntu/22.04").status_code == 200
    m = deploy_2204()

    def broken(job_id, tpl, log_path):
        raise builds.BuildError("Packer failed (exit code 1).", "the end of its output")

    monkeypatch.setattr(builds, "build", broken)
    run_builds(builds_queued)
    m = client.get(f"/api/machines/{m['id']}").json()
    assert m["state"] == "error" and "building ubuntu 22.04 failed" in m["log"][-1]["text"]
    job = client.get("/api/jobs").json()[0]
    assert job["state"] == "failed" and job["template"] == "ubuntu/22.04" and "the end of its output" in job["detail"]
    t = {(t["template"], t["version"]): t for t in client.get("/api/templates").json()}[("ubuntu", "22.04")]
    assert t["state"] == "failed" and "exit code 1" in t["detail"]

    # Building it from the admin page.
    queued.clear()
    assert client.post("/api/templates/ubuntu/22.04/build").status_code == 202
    fake_packer(monkeypatch)
    run_builds(builds_queued)
    assert {(t["template"], t["version"]): t for t in client.get("/api/templates").json()}[("ubuntu", "22.04")]["state"] == "built"
    assert not queued  # nothing was waiting
    assert client.post("/api/templates/ubuntu/22.04/build").status_code == 409  # built already


def test_a_build_waits_for_space_and_its_isos(throwaway, builds_queued, monkeypatch):
    assert client.delete("/api/templates/ubuntu/22.04").status_code == 200
    m = deploy_2204()
    monkeypatch.setattr(VCenter, "iso_files", lambda self: set())
    run_builds(builds_queued)
    assert "Missing from the datastore's ISO folder" in client.get("/api/jobs").json()[0]["detail"]
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "error"


def test_delete_refuses_linked_clones_and_machines(throwaway, queued, monkeypatch):
    monkeypatch.setattr(VCenter, "clones_of", lambda self, path: ["jo-left-1234"])
    r = client.delete("/api/templates/ubuntu/22.04")
    assert r.status_code == 409 and "jo-left-1234" in r.json()["detail"]
    with connect() as vc:
        assert "tpl-throwaway" in vc.templates()


def test_clones_of_finds_a_machines_disk(queued):
    """vcsim's clones are full copies, so this checks the lookup's shape: the template itself isn't
    counted, and VMs in other folders aren't either."""
    with connect() as vc:
        assert vc.clones_of(TEMPLATE) == []


def test_lab_machines_wait_for_their_build_without_losing_their_turn(queued):
    with session() as s:
        for role, pending in (("dc", "build"), ("ws", "deploy")):
            s.add(
                Machine(
                    id=f"m-{role}00", name=f"i1-{role}", template="ubuntu", version="26.04", owner="jo", state="deploying",
                    vm_name=f"jo-i1-{role}", username="u", password="p", instance_id="i-0001", lab=None, role=role, pending=pending,
                )
            )
    actions.advance_instance("i-0001", jobs.enqueue)
    # The member waiting for its own turn is queued (no boot order without a lab); the one waiting for a build isn't.
    assert [d["machine_id"] for d in queued] == ["m-ws00"]
    with session() as s:
        assert s.get(Machine, "m-dc00").pending == "build"
    queued.clear()
    builds.release_waiting("ubuntu", "26.04", jobs.enqueue)
    assert [d["machine_id"] for d in queued] == ["m-dc00"]


def test_the_sweep_queues_a_lost_build_again(builds_queued):
    with session() as s:
        s.add(
            Machine(
                id="m-wait", name="wait01", template="ubuntu", version="26.04", owner="jo", state="deploying",
                vm_name="jo-wait01", username="u", password="p", pending="build",
            )
        )
        s.add(TemplateBuild(template="ubuntu", version="26.04", state="building"))
        s.add(Job(kind="build", template="ubuntu/26.04", action="Build ubuntu 26.04", by="system", state="running", queued_at=utcnow() - timedelta(minutes=5)))
    actions.recover_lost_jobs()
    with session() as s:
        assert s.get(TemplateBuild, ("ubuntu", "26.04")).state == "failed"
    builds.ensure_builds(jobs.enqueue_build)
    assert len(builds_queued) == 1
    builds.ensure_builds(jobs.enqueue_build)  # queued now: not again
    assert len(builds_queued) == 1


def test_a_running_build_isnt_taken_for_lost(builds_queued):
    """The queue still has it (doing): the sweep leaves it alone."""
    import json

    from sqlalchemy import text

    with session() as s:
        job = Job(kind="build", template="ubuntu/26.04", action="Build ubuntu 26.04", by="system", state="running", queued_at=utcnow() - timedelta(minutes=5))
        s.add(job)
        s.flush()
        worker = s.scalar(text("INSERT INTO procrastinate_workers DEFAULT VALUES RETURNING id"))  # alive: a fresh heartbeat
        s.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args, status, worker_id) "
                "VALUES ('build', 'template_build', 'template-build', CAST(:args AS jsonb), 'doing', :worker)"
            ),
            {"args": json.dumps({"job_id": job.id, "template": "ubuntu", "version": "26.04"}), "worker": worker},
        )
        job_id = job.id
    try:
        actions.recover_lost_jobs()
        with session() as s:
            assert s.get(Job, job_id).state == "running"
    finally:
        with session() as s:
            s.execute(text("DELETE FROM procrastinate_jobs"))
            s.execute(text("DELETE FROM procrastinate_workers"))


def test_a_build_of_a_built_template_just_lets_machines_go(queued, builds_queued):
    with session() as s:
        s.add(
            Machine(
                id="m-wait", name="wait01", template="ubuntu", version="26.04", owner="jo", state="deploying",
                vm_name="jo-wait01", username="u", password="p", pending="build",
            )
        )
        job = Job(kind="build", template="ubuntu/26.04", action="Build ubuntu 26.04", by="system")
        s.add(job)
        s.flush()
        job_id = job.id
    builds.run_build(job_id, "ubuntu", "26.04", jobs.enqueue)
    with session() as s:
        assert s.get(Job, job_id).state == "done"
    assert [d["machine_id"] for d in queued] == ["m-wait"]


def test_a_queued_build_can_be_cancelled(throwaway, queued, builds_queued):
    assert client.delete("/api/templates/ubuntu/22.04").status_code == 200
    m = deploy_2204()
    r = client.post("/api/templates/ubuntu/22.04/cancel", headers={"X-Lab-User": "sam"})
    assert r.status_code == 200 and r.json()["state"] == "queued"
    assert client.post("/api/templates/ubuntu/22.04/cancel").status_code == 409  # cancelled already
    run_builds(builds_queued)
    job = client.get("/api/jobs").json()[0]
    assert job["state"] == "failed" and job["detail"].startswith("Cancelled by")
    m = client.get(f"/api/machines/{m['id']}").json()
    assert m["state"] == "error" and "Cancelled by" in m["log"][-1]["text"]
    assert not queued
    # Nothing left to cancel.
    assert client.post("/api/templates/ubuntu/22.04/cancel").status_code == 409


def test_a_running_build_stops_when_cancelled(throwaway, builds_queued, monkeypatch):
    """The build loop checks for a cancel while Packer runs, and stops it."""
    assert client.delete("/api/templates/ubuntu/22.04").status_code == 200
    assert client.post("/api/templates/ubuntu/22.04/build").status_code == 202

    def packer(job_id, tpl, log_path):
        assert client.post("/api/templates/ubuntu/22.04/cancel", headers={"X-Lab-User": "sam"}).status_code == 200
        with session() as s:  # as _run_process finds at its next check
            who = s.get(Job, job_id).cancelled_by
        raise builds.BuildError(f"Stopped: cancelled by {who}.")

    monkeypatch.setattr(builds, "build", packer)
    run_builds(builds_queued)
    t = {(t["template"], t["version"]): t for t in client.get("/api/templates").json()}[("ubuntu", "22.04")]
    assert t["state"] == "failed" and t["detail"] == "Stopped: cancelled by sam."


def test_offline_builds_use_the_install_command(tmp_path, monkeypatch):
    """BUILD_OFFLINE (written by the offline install): a template it lists builds with the install's
    command (this network's mirrors and media), the rest with templates.yaml's recipe."""
    import json

    offline = tmp_path / "offline-builds.json"
    offline.write_text(json.dumps({"ubuntu/24.04": {"argv": ["bash", "packer/build.sh", "ubuntu", "-var", "apt_mirror=http://mirror.lab.example/ubuntu"],
                                                    "env": {}, "media": True}}))
    monkeypatch.setenv("BUILD_OFFLINE", str(offline))
    settings.cache_clear()
    try:
        cmd = builds.command(catalogue.find("ubuntu", "24.04"), 9)
        assert cmd[:5] == ["bash", "packer/build.sh", "ubuntu", "-var", "apt_mirror=http://mirror.lab.example/ubuntu"]
        assert re.fullmatch(r"vm_name=tpl-ubuntu-24.04-\d{8}-j9", cmd[-1])
        assert builds.command(catalogue.find("ubuntu", "22.04"), 9)[3:5] == ["-var", "version=22.04"]  # not listed: its recipe
        assert builds.offline_build(settings(), catalogue.find("ubuntu", "24.04"))["media"] is True
    finally:
        settings.cache_clear()


def test_the_media_server_serves_the_folder(tmp_path):
    import socket
    import urllib.request

    (tmp_path / "linux").mkdir()
    (tmp_path / "linux" / "file.txt").write_text("media")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = builds.MediaServer(tmp_path, port)
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/linux/file.txt", timeout=5).read() == b"media"
    finally:
        server.close()
