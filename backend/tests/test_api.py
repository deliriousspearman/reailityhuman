"""The API and the jobs it queues, run against vcsim and PostgreSQL."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import actions, jobs
from app.api import app
from app.db import session
from app.models import Job, Machine, utcnow
from app.vsphere import connect

from .conftest import run_queued

client = TestClient(app)


def deploy(queued, name="ubuntu01", hours=4):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "22.04", "name": name, "hours": hours})
    assert r.status_code == 201, r.text
    run_queued(queued)
    return client.get(f"/api/machines/{r.json()['id']}").json()


def test_config_lists_live_templates():
    r = client.get("/api/config").json()
    assert {"template": "ubuntu", "version": "22.04"}.items() <= r["templates"][0].items()
    assert r["vcenterConfigured"] is True


def test_health():
    assert client.get("/api/health").json() == {"database": "ok", "vcenter": "ok"}


def test_deploy_then_lifecycle(queued):
    m = deploy(queued)
    assert m["state"] == "running"
    assert m["username"] == "ubuntu" and len(m["password"]) == 16
    texts = [line["text"] for line in m["log"]]
    assert "Cloned from ubuntu/22.04" in texts
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
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "22.04", "name": "busy01", "hours": 2})
    assert client.post(f"/api/machines/{r.json()['id']}/stop").status_code == 409
    run_queued(queued)


@pytest.mark.parametrize(
    "body, status",
    [
        ({"template": "pfsense", "version": "2.8.0", "name": "fw01", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "22.04", "name": "Bad_Name", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "22.04", "name": "ok01", "hours": 0}, 422),
    ],
)
def test_deploy_validation(body, status):
    assert client.post("/api/machines", json=body).status_code == status


def test_duplicate_name_and_limits(queued, monkeypatch):
    deploy(queued, "dup01")
    assert client.post("/api/machines", json={"template": "ubuntu", "version": "22.04", "name": "dup01", "hours": 2}).status_code == 409
    from app.config import settings

    monkeypatch.setattr(settings(), "max_permanent", 0)
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "22.04", "name": "perm01", "hours": None})
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
