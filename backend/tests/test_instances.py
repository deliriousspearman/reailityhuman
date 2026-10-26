"""Pro Labs: deploying, resetting, cancelling and destroying a lab as one instance, in its boot order."""

import pytest
from fastapi.testclient import TestClient

from app import actions, jobs, labs
from app.api import app
from app.vsphere import connect

from .conftest import run_queued

client = TestClient(app)

# A lab of the test template (vcsim has Ubuntu 26.04): one machine first, then two together.
LAB = """
- slug: demo
  title: Demo
  description: A demo lab.
  machines:
    - {name: dc, template: ubuntu, version: "26.04", role: Domain controller, bootOrder: 1}
    - {name: web, template: ubuntu, version: "26.04", bootOrder: 2}
    - {name: ws, template: ubuntu, version: "26.04", bootOrder: 2}
- slug: later
  title: Later
  description: Not built yet.
  planned: true
  machines:
    - {name: dc, template: not-built, version: "1"}
"""


@pytest.fixture(autouse=True)
def demo_lab(tmp_path, monkeypatch):
    p = tmp_path / "labs.yaml"
    p.write_text(LAB)
    monkeypatch.setattr(labs, "_path", lambda: p)
    labs.labs.cache_clear()
    yield
    labs.labs.cache_clear()


def deploy(lab="demo"):
    r = client.post("/api/instances", json={"lab": lab, "owner": "jo", "hours": 4})
    assert r.status_code == 201, r.text
    return r.json()


def roles(instance) -> dict[str, dict]:
    return {m["role"]: m for m in instance["machines"]}


def test_deploys_in_boot_order(queued):
    i = deploy()
    assert i["lab"] == "demo" and i["state"] == "deploying"
    ms = roles(i)
    assert [m["role"] for m in i["machines"]] == ["dc", "web", "ws"]
    assert ms["dc"]["name"] == f"{i['id'].replace('-', '')}-dc"
    # Only the first in the boot order is queued; the rest wait their turn.
    assert [q["machine_id"] for q in queued] == [ms["dc"]["id"]]
    assert "pending" not in ms["dc"] and ms["web"]["pending"] == ms["ws"]["pending"] == "deploy"

    actions.run(**queued.pop(0), enqueue=jobs.enqueue)
    assert sorted(q["machine_id"] for q in queued) == sorted([ms["web"]["id"], ms["ws"]["id"]])
    run_queued(queued)

    i = client.get(f"/api/instances/{i['id']}").json()
    assert i["state"] == "running"
    assert all(m["state"] == "running" and "pending" not in m for m in i["machines"])
    assert [j["action"] for j in client.get("/api/jobs").json()][-1] == f"Deploy {ms['dc']['name']}"
    assert [x["id"] for x in client.get("/api/instances").json()] == [i["id"]]


def test_reset_and_destroy_the_whole_instance(queued):
    i = deploy()
    run_queued(queued)
    ms = roles(i)

    r = client.post(f"/api/instances/{i['id']}/reset")
    assert r.status_code == 200 and r.json()["state"] == "resetting"
    assert [q["machine_id"] for q in queued] == [ms["dc"]["id"]]
    run_queued(queued)
    i = client.get(f"/api/instances/{i['id']}").json()
    assert i["state"] == "running"
    assert "Reverted to snapshot 'clean'" in [line["text"] for line in client.get(f"/api/machines/{ms['ws']['id']}").json()["log"]]

    assert client.delete(f"/api/instances/{i['id']}").json()["state"] == "destroying"
    assert len(queued) == 3  # all at once
    run_queued(queued)
    assert client.get(f"/api/instances/{i['id']}").status_code == 404
    with connect() as vc:
        assert all(vc.vm(m["vmName"]) is None for m in i["machines"])


def test_a_failure_stops_the_machines_after_it(queued, monkeypatch):
    def fail(vc, m):
        raise actions.VSphereError("it broke")

    monkeypatch.setitem(actions.ACTIONS, "deploy", fail)
    i = deploy()
    run_queued(queued)
    i = client.get(f"/api/instances/{i['id']}").json()
    assert i["state"] == "error"
    ws = client.get(f"/api/machines/{roles(i)['ws']['id']}").json()
    assert ws["state"] == "error" and "pending" not in ws
    assert ws["log"][-1]["text"] == "Not deployed: dc isn't running, and this machine needs it first."
    # Nothing ran for the machines after it.
    assert len(client.get("/api/jobs").json()) == 1


def test_cancel_drops_the_turns_waiting(queued):
    i = deploy()
    r = client.post(f"/api/instances/{i['id']}/cancel")
    assert r.status_code == 200
    assert all(m["state"] == "error" for m in r.json()["machines"] if m["role"] != "dc")
    run_queued(queued)  # the controller's job, cancelled before it started
    i = client.get(f"/api/instances/{i['id']}").json()
    assert all(m["state"] == "error" for m in i["machines"])
    assert client.post(f"/api/instances/{i['id']}/cancel").status_code == 409
    # Destroyable now that nothing's busy.
    assert client.delete(f"/api/instances/{i['id']}").status_code == 200
    run_queued(queued)


def test_the_sweep_queues_turns_a_job_didnt(queued):
    """The worker stopped between a job and queuing the next: the sweep picks it up."""
    i = deploy()
    actions.run(**queued.pop(0))  # no enqueue: as if the worker stopped there
    assert queued == []
    actions.advance_instances(jobs.enqueue)
    assert len(queued) == 2
    actions.advance_instances(jobs.enqueue)  # already queued: not again
    assert len(queued) == 2
    run_queued(queued)
    assert client.get(f"/api/instances/{i['id']}").json()["state"] == "running"


def test_busy_instance_refuses_reset_and_destroy(queued):
    i = deploy()
    assert client.post(f"/api/instances/{i['id']}/reset").status_code == 409
    assert client.delete(f"/api/instances/{i['id']}").status_code == 409
    run_queued(queued)


@pytest.mark.parametrize("lab", ["later", "nope"])
def test_planned_or_unknown_labs_cant_deploy(lab):
    r = client.post("/api/instances", json={"lab": lab, "owner": "jo", "hours": 4})
    assert r.status_code == 422


def test_the_machine_limit_counts_the_whole_lab(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "max_machines", 2)
    r = client.post("/api/instances", json={"lab": "demo", "owner": "jo", "hours": 4})
    assert r.status_code == 409 and "has 3 machines" in r.json()["detail"]


def test_unknown_instance_is_404():
    assert client.get("/api/instances/i-0000").status_code == 404


def test_config_lists_the_labs():
    got = {lab["slug"]: lab for lab in client.get("/api/config").json()["labs"]}
    assert got["demo"]["planned"] is False and got["later"]["planned"] is True
    assert [m["name"] for m in got["demo"]["machines"]] == ["dc", "web", "ws"]
    assert got["demo"]["memoryGB"] > 0


def test_extend_restarts_an_expired_lab_in_boot_order(queued):
    from datetime import timedelta

    from app.db import session
    from app.models import Machine, utcnow

    i = deploy()
    run_queued(queued)
    with session() as s:
        for m in s.query(Machine).filter(Machine.instance_id == i["id"]):
            m.expires_at = utcnow() - timedelta(minutes=1)
    actions.expiry_sweep(jobs.enqueue)
    run_queued(queued)
    assert client.get(f"/api/instances/{i['id']}").json()["state"] == "expired"

    r = client.post(f"/api/instances/{i['id']}/extend", json={"hours": 2})
    assert r.status_code == 200, r.text
    assert [q["machine_id"] for q in queued] == [roles(i)["dc"]["id"]]
    run_queued(queued)
    i = client.get(f"/api/instances/{i['id']}").json()
    assert i["state"] == "running" and i["expiresAt"] > utcnow().timestamp() * 1000
