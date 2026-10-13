"""The API and the jobs it queues, run against vcsim and PostgreSQL."""

from datetime import timedelta

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import actions, jobs
from app.api import app
from app.db import session
from app.models import Job, Machine, utcnow
from app.vsphere import connect

from .conftest import run_queued

client = TestClient(app)


def deploy(queued, name="ubuntu01", hours=4):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": name, "hours": hours})
    assert r.status_code == 201, r.text
    run_queued(queued)
    return client.get(f"/api/machines/{r.json()['id']}").json()


def test_config_lists_live_templates():
    r = client.get("/api/config").json()
    assert {"template": "ubuntu", "version": "26.04"}.items() <= r["templates"][0].items()
    assert r["vcenterConfigured"] is True


def test_health():
    assert client.get("/api/health").json() == {"database": "ok", "vcenter": "ok"}


def test_memory_overcommit(monkeypatch):
    from app import api
    from app.config import settings

    monkeypatch.setattr(api, "_capacity_cache", None)
    physical = client.get("/api/capacity").json()["total"]["memoryGB"]
    monkeypatch.setattr(api, "_capacity_cache", None)
    monkeypatch.setattr(settings(), "memory_overcommit", 1.5)
    assert client.get("/api/capacity").json()["total"]["memoryGB"] == int(physical * 1.5)
    monkeypatch.setattr(api, "_capacity_cache", None)


def test_deploy_then_lifecycle(queued):
    m = deploy(queued)
    assert m["state"] == "running"
    assert m["username"] == "ubuntu" and len(m["password"]) == 16
    texts = [line["text"] for line in m["log"]]
    assert "Cloned from ubuntu/26.04" in texts
    assert texts[-1] == "Ready. Sign in as ubuntu."
    with connect() as vc:
        assert vc.powered_on(vc.require_vm(m["vmName"]))

    for action, after in [("stop", "stopped"), ("start", "running"), ("reboot", "running"), ("reset", "running")]:
        r = client.post(f"/api/machines/{m['id']}/{action}")
        assert r.status_code == 200, r.text
        assert r.json()["state"] not in ("running", "stopped")  # busy until the job runs
        run_queued(queued)
        assert client.get(f"/api/machines/{m['id']}").json()["state"] == after, action

    assert client.delete(f"/api/machines/{m['id']}").status_code == 200
    run_queued(queued)
    assert client.get(f"/api/machines/{m['id']}").status_code == 404
    with connect() as vc:
        assert vc.vm(m["vmName"]) is None
    jobs = client.get("/api/jobs").json()
    assert [j["action"] for j in jobs][:2] == ["Destroy ubuntu01", "Reset ubuntu01"]
    assert all(j["state"] == "done" for j in jobs)


def test_busy_machine_rejects_actions(queued):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "busy01", "hours": 2})
    assert client.post(f"/api/machines/{r.json()['id']}/stop").status_code == 409
    run_queued(queued)


@pytest.mark.parametrize(
    "body, status",
    [
        ({"template": "pfsense", "version": "2.8.0", "name": "fw01", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "Bad_Name", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "ok01", "hours": 0}, 422),
        ({"template": "ubuntu", "version": "26.04", "name": "ok01", "hours": 2}, 422),  # no owner
        ({"template": "ubuntu", "version": "26.04", "owner": "Jo Bloggs", "name": "ok01", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "26.04", "owner": "1jo", "name": "ok01", "hours": 2}, 422),
    ],
)
def test_deploy_validation(body, status):
    assert client.post("/api/machines", json=body).status_code == status


def test_duplicate_name_and_limits(queued, monkeypatch):
    deploy(queued, "dup01")
    assert client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "dup01", "hours": 2}).status_code == 409
    from app.config import settings

    monkeypatch.setattr(settings(), "max_permanent", 0)
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "perm01", "hours": None})
    assert r.status_code == 409 and "permanently" in r.json()["detail"]


def test_failed_job_marks_machine_error(queued):
    m = deploy(queued, "gone01")
    with connect() as vc:
        vc.destroy(vc.require_vm(m["vmName"]))
    client.post(f"/api/machines/{m['id']}/stop")
    run_queued(queued)
    m = client.get(f"/api/machines/{m['id']}").json()
    assert m["state"] == "error"
    assert "no longer exists" in m["log"][-1]["text"]
    assert client.get("/api/jobs").json()[0]["state"] == "failed"


def test_expiry_sweep_powers_off_then_deletes(queued):
    m = deploy(queued, "exp01", hours=2)
    with session() as s:
        s.get(Machine, m["id"]).expires_at = utcnow() - timedelta(minutes=1)
    actions.expiry_sweep(jobs.enqueue)
    run_queued(queued)
    m2 = client.get(f"/api/machines/{m['id']}").json()
    assert m2["state"] == "expired"
    with connect() as vc:
        assert not vc.powered_on(vc.require_vm(m["vmName"]))

    # Extending brings it back.
    r = client.post(f"/api/machines/{m['id']}/extend", json={"hours": 2})
    assert r.json()["state"] == "deploying"
    run_queued(queued)
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "running"

    # Past the grace period it's deleted.
    with session() as s:
        row = s.get(Machine, m["id"])
        row.state = "expired"
        row.expires_at = utcnow() - timedelta(days=2)
    actions.expiry_sweep(jobs.enqueue)
    run_queued(queued)
    assert client.get(f"/api/machines/{m['id']}").status_code == 404
    with session() as s:
        assert s.query(Job).filter(Job.by == "system").count() == 2


def test_keep_and_set_expiry(queued):
    m = deploy(queued, "keep01")
    m = client.post(f"/api/machines/{m['id']}/keep").json()
    assert m["expiresAt"] is None
    assert client.post(f"/api/machines/{m['id']}/extend", json={"hours": 2}).status_code == 409
    m = client.post(f"/api/machines/{m['id']}/expiry", json={"hours": 4}).json()
    assert m["expiresAt"] is not None


def test_reconcile_picks_up_changes_made_in_vcenter(queued):
    m = deploy(queued, "rec01")
    with connect() as vc:
        vc.power_off(vc.require_vm(m["vmName"]))
    actions.reconcile()
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "stopped"


def test_owner_names_the_vm_and_the_jobs(queued):
    r = client.post(
        "/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": " John ", "name": "ubuntu02", "hours": 2}
    )
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["owner"] == "john"
    assert m["name"] == "ubuntu02"  # the hostname stays as chosen
    assert m["vmName"] == f"john-ubuntu02-{m['id'].removeprefix('m-')}"
    run_queued(queued)
    with connect() as vc:
        assert vc.vm(m["vmName"]) is not None

    # Actions record who asked (X-Lab-User), or "anyone" without it.
    assert client.post(f"/api/machines/{m['id']}/stop", headers={"X-Lab-User": "sam"}).status_code == 200
    run_queued(queued)
    assert client.post(f"/api/machines/{m['id']}/start").status_code == 200
    run_queued(queued)
    by = {j["action"]: j["by"] for j in client.get("/api/jobs").json()}
    assert by == {"Deploy ubuntu02": "john", "Stop ubuntu02": "sam", "Start ubuntu02": "anyone"}
    texts = [line["text"] for line in client.get(f"/api/machines/{m['id']}").json()["log"]]
    assert "Deploy requested by john (2 h)" in texts
    assert "Stopping, asked by sam" in texts


def test_chosen_password_or_a_generated_one(queued):
    def make(name, **extra):
        body = {"template": "ubuntu", "version": "26.04", "owner": "jo", "name": name, "hours": 2, **extra}
        return client.post("/api/machines", json=body)

    r = make("pw01", password="correct horse 9")
    assert r.status_code == 201 and r.json()["password"] == "correct horse 9"
    r = make("pw02", password="")
    assert r.status_code == 201 and len(r.json()["password"]) == 16  # generated
    assert make("pw03", password="short").status_code == 422
    assert make("pw04", password="has\nnewline").status_code == 422


def test_jobs_the_worker_lost_are_failed(queued):
    """A job cut off by the worker stopping (e.g. killed in a redeploy) fails, freeing its machine."""
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "lost01", "hours": 2})
    m = r.json()
    queued.clear()  # the worker took it, then died
    with session() as s:
        job = s.query(Job).one()
        job.state, job.started_at = "running", utcnow() - timedelta(minutes=5)
        s.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args, status) "
                "VALUES ('default', 'machine_action', :lock, CAST(:args AS jsonb), 'doing')"
            ),
            {"lock": m["id"], "args": json.dumps({"job_id": job.id, "machine_id": m["id"], "action": "deploy"})},
        )
    try:
        actions.recover_lost_jobs()
        m = client.get(f"/api/machines/{m['id']}").json()
        assert m["state"] == "error"
        assert "the job worker stopped" in m["log"][-1]["text"]
        assert client.get("/api/jobs").json()[0]["state"] == "failed"
        with session() as s:
            assert s.scalar(text("SELECT status FROM procrastinate_jobs WHERE lock = :lock"), {"lock": m["id"]}) == "failed"

        # It can be destroyed now, and a job that's only just been queued is left alone.
        assert client.delete(f"/api/machines/{m['id']}").status_code == 200
        actions.recover_lost_jobs()
        assert client.get("/api/jobs").json()[0]["state"] == "queued"
        run_queued(queued)
        assert client.get(f"/api/machines/{m['id']}").status_code == 404
    finally:
        with session() as s:
            s.execute(text("DELETE FROM procrastinate_jobs"))
