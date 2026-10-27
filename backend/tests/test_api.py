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
        ({"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "web-", "hours": 2}, 422),
        ({"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "a" * 16, "hours": 2}, 422),
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
        job.state, job.queued_at = "running", utcnow() - timedelta(minutes=5)
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


def test_names_are_unique_in_the_database(queued):
    """Backs up the API's check, for two deploys of one name at the same moment."""
    from sqlalchemy.exc import IntegrityError

    deploy(queued, "same01")
    with pytest.raises(IntegrityError):
        with session() as s:
            s.add(Machine(id="m-dupe", name="same01", template="ubuntu", version="26.04", owner="jo", state="running",
                          vm_name="x", username="ubuntu", password="x"))


def test_machines_on_their_way_up_count_against_memory(queued, monkeypatch):
    """Deploys close together can't all fit into the same free memory, and starting a stopped
    machine checks there's room."""
    from app import api
    from app.vsphere import Capacity

    # 5 GB free; Ubuntu machines take 2 GB each.
    small = Capacity(cpu=8, memory_gb=5, disk_gb=500, used_cpu=0, used_memory_gb=0, used_disk_gb=0)
    monkeypatch.setattr(api, "vcenter_capacity", lambda fresh=False: small)

    def ask(name):
        return client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": name, "hours": 2})

    assert ask("cap01").status_code == 201
    assert ask("cap02").status_code == 201
    r = ask("cap03")  # the first two haven't powered on yet, but they will
    assert r.status_code == 409 and "Not enough memory" in r.json()["detail"]
    run_queued(queued)

    # Both running now (powered on, so in vCenter's own figure); one is stopped.
    with session() as s:
        names = {m.name: m.vm_name for m in s.query(Machine)}
        stopped = s.query(Machine).filter(Machine.name == "cap02").one()
        stopped.state = "stopped"
        stopped_id = stopped.id
    monkeypatch.setattr(
        api, "vcenter_capacity", lambda fresh=False: Capacity(8, 5, 500, 4, 4, 0, powered_on=frozenset([names["cap01"]]))
    )
    r = client.post(f"/api/machines/{stopped_id}/start")
    assert r.status_code == 409 and "Not enough memory" in r.json()["detail"]


def test_deploys_keep_the_datastore_reserve_free(queued, monkeypatch):
    """A deploy is refused if it would leave less than DATASTORE_RESERVE_GB free, counting what deploys
    still running will write."""
    from app import api
    from app.config import settings
    from app.vsphere import Capacity

    monkeypatch.setattr(settings(), "datastore_reserve_gb", 30)
    monkeypatch.setattr(settings(), "clone_disk_gb", 10)
    # 48 GB free: room for one 10 GB machine above the reserve, not two.
    monkeypatch.setattr(api, "vcenter_capacity", lambda fresh=False: Capacity(8, 64, 100, 0, 0, 52))

    def ask(name):
        return client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": name, "hours": 2})

    assert ask("disk01").status_code == 201
    r = ask("disk02")
    assert r.status_code == 409 and "Not enough disk" in r.json()["detail"] and "30 GB must stay free" in r.json()["detail"]
    assert client.get("/api/capacity").json()["reserveGB"] == 30
    queued.clear()


def test_expired_machines_dont_count_against_the_quota(queued, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "max_machines", 1)
    m = deploy(queued, "old01")
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "new01", "hours": 2})
    assert r.status_code == 409 and "1 machines at a time" in r.json()["detail"]
    with session() as s:
        s.get(Machine, m["id"]).state = "expired"
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "new01", "hours": 2})
    assert r.status_code == 201, r.text
    queued.clear()


def test_reconcile_leaves_a_failed_deploy_flagged(queued):
    """A deploy that failed after powering on (e.g. an extra didn't install) stays "error", though
    vCenter says the VM runs; other failures are cleared once the VM looks fine."""
    m = deploy(queued, "half01")
    with session() as s:
        s.get(Machine, m["id"]).state = "error"
        s.query(Job).one().state = "failed"
    actions.reconcile()
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "error"

    with session() as s:
        s.query(Job).one().kind = "stop"
    actions.reconcile()
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "running"


def test_redeploy_starts_over_with_the_same_settings(queued):
    m = deploy(queued, "again01")
    r = client.post(f"/api/machines/{m['id']}/redeploy")
    assert r.status_code == 200 and r.json()["state"] == "deploying"
    run_queued(queued)
    m2 = client.get(f"/api/machines/{m['id']}").json()
    assert m2["state"] == "running" and m2["password"] == m["password"]
    assert "Deleted the old VM" in [line["text"] for line in m2["log"]]

    # Also when the VM is gone altogether.
    with connect() as vc:
        vc.destroy(vc.require_vm(m["vmName"]))
    with session() as s:
        s.get(Machine, m["id"]).state = "error"
    assert client.post(f"/api/machines/{m['id']}/redeploy").status_code == 200
    run_queued(queued)
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "running"
    with connect() as vc:
        assert vc.vm(m["vmName"]) is not None
    assert client.get("/api/jobs").json()[0]["action"] == "Redeploy again01"


def test_leftover_vms_can_be_listed_and_deleted(queued):
    from app import cloudinit
    from .conftest import TEMPLATE

    m = deploy(queued, "kept01")
    with connect() as vc:
        vc.clone(TEMPLATE, "jo-half01-dead", 1, 1, cloudinit.guestinfo("m-dead", "half01", "ubuntu", "secret", None))
    assert client.get("/api/leftovers").json() == [{"name": "jo-half01-dead", "poweredOn": False}]
    assert client.delete(f"/api/leftovers/{m['vmName']}").status_code == 404  # a machine owns it
    assert client.delete("/api/leftovers/jo-half01-dead").status_code == 200
    assert client.get("/api/leftovers").json() == []
    with connect() as vc:
        assert vc.vm("jo-half01-dead") is None and vc.vm(m["vmName"]) is not None


def test_jobs_keep_queue_time_and_filter_by_machine(queued):
    a = deploy(queued, "jobs01")
    deploy(queued, "jobs02")
    client.post(f"/api/machines/{a['id']}/stop")
    waiting = client.get("/api/jobs").json()[0]
    assert waiting["state"] == "queued" and waiting["queuedAt"] and waiting["startedAt"] is None
    run_queued(queued)
    mine = client.get(f"/api/jobs?machine={a['id']}").json()
    assert [j["action"] for j in mine] == ["Stop jobs01", "Deploy jobs01"]
    assert all(j["startedAt"] >= j["queuedAt"] for j in mine)


def test_reboot_says_rebooting(queued):
    m = deploy(queued, "boot01")
    assert client.post(f"/api/machines/{m['id']}/reboot").json()["state"] == "rebooting"
    run_queued(queued)
    assert client.get(f"/api/machines/{m['id']}").json()["state"] == "running"


def test_set_expiry_on_busy_or_expired_machines(queued):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "exp02", "hours": 2})
    m = r.json()
    assert client.post(f"/api/machines/{m['id']}/expiry", json={"hours": 4}).status_code == 409  # still deploying
    run_queued(queued)
    with session() as s:
        s.get(Machine, m["id"]).state = "expired"
    r = client.post(f"/api/machines/{m['id']}/expiry", json={"hours": 4}, headers={"X-Lab-User": "sam"})
    assert r.json()["state"] == "deploying"  # started again, like extending
    run_queued(queued)
    m = client.get(f"/api/machines/{m['id']}").json()
    assert m["state"] == "running"
    assert "Expiry set: powered off in 4 h unless extended, asked by sam" in [line["text"] for line in m["log"]]


def test_config_sends_the_deploy_rules():
    rules = client.get("/api/config").json()["rules"]
    import re

    assert re.match(rules["name"]["pattern"], "ubuntu01") and re.match(rules["name"]["pattern"], "a")
    assert not re.match(rules["name"]["pattern"], "Bad_Name") and not re.match(rules["name"]["pattern"], "web-")
    assert re.match(rules["owner"]["pattern"], "jo") and rules["owner"]["problem"]
    assert rules["passwordMin"] == 8
    assert re.match(rules["hostname"], "intranet.lab.example")


def test_old_finished_jobs_are_pruned(queued):
    deploy(queued, "old01")
    deploy(queued, "new01")
    with session() as s:
        old = s.query(Job).filter(Job.action == "Deploy old01").one()
        old.finished_at = utcnow() - timedelta(days=91)
    actions.prune_history()
    assert [j["action"] for j in client.get("/api/jobs").json()] == ["Deploy new01"]


def test_the_list_leaves_logs_out(queued):
    m = deploy(queued, "list01")
    assert "log" not in client.get("/api/machines").json()[0]
    assert client.get(f"/api/machines/{m['id']}").json()["log"]


def test_a_machine_given_the_hosts_address_is_powered_off(queued, monkeypatch):
    """A DHCP pool overlapping the lab's fixed addresses can hand a machine the ESXi host's (or
    vCenter's): then both drop off the network. The machine is powered off at once instead."""
    from app.vsphere import VCenter

    with connect() as vc:
        taken = sorted(vc.infrastructure_addresses())[0]
    monkeypatch.setattr(VCenter, "wait_for_ip", lambda self, vm, timeout: taken)
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "clash01", "hours": 2})
    run_queued(queued)
    m = client.get(f"/api/machines/{r.json()['id']}").json()
    assert m["state"] == "error"
    assert f"It got {taken} from DHCP" in m["log"][-1]["text"]
    with connect() as vc:
        assert not vc.powered_on(vc.require_vm(m["vmName"]))


def test_infrastructure_addresses_include_vcenter_and_the_hosts():
    from app.config import settings

    with connect() as vc:
        addresses = vc.infrastructure_addresses()
    assert settings().vcenter_host.partition(":")[0] in addresses
    assert len(addresses) >= 2, addresses  # vCenter, and at least one host


def _machine(s, machine_id, name, extras, ip):
    s.add(Machine(id=machine_id, name=name, template="ubuntu", version="26.04", owner="jo", state="running",
                  vm_name=f"jo-{name}", username="ubuntu", password="x", ip=ip, extras=extras))


def test_machines_list_who_depends_on_them_and_hear_when_it_moves():
    """An agent points at its server's address, given when it was deployed: the server lists it, and
    the agent is told when the server's address changes."""
    with session() as s:
        _machine(s, "m-serv", "server1", [{"id": "wazuh", "options": {}}], "192.0.2.10")
        _machine(s, "m-agnt", "agent1", [{"id": "wazuh-agent", "options": {"wazuh": "m-serv"}}], "192.0.2.11")
    server = client.get("/api/machines/m-serv").json()
    assert server["usedBy"] == [{"id": "m-agnt", "name": "agent1"}]
    assert next(m for m in client.get("/api/machines").json() if m["id"] == "m-serv")["usedBy"] == [{"id": "m-agnt", "name": "agent1"}]
    assert client.get("/api/machines/m-agnt").json()["usedBy"] == []

    actions.set_ip("m-serv", "192.0.2.20")
    log = client.get("/api/machines/m-agnt").json()["log"]
    assert log[-1]["tone"] == "warn" and "server1 moved from 192.0.2.10 to 192.0.2.20" in log[-1]["text"]
    actions.set_ip("m-serv", "192.0.2.20")  # the same address: nothing more said
    assert len(client.get("/api/machines/m-agnt").json()["log"]) == len(log)


def test_a_waiting_job_can_be_cancelled(queued):
    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "wait01", "hours": 2})
    machine_id = r.json()["id"]
    r = client.post(f"/api/machines/{machine_id}/cancel", headers={"X-Lab-User": "sam"})
    assert r.status_code == 200
    run_queued(queued)
    m = client.get(f"/api/machines/{machine_id}").json()
    assert m["state"] == "error" and "cancelled by sam before it started" in m["log"][-1]["text"]
    job = client.get(f"/api/jobs?machine={machine_id}").json()[0]
    assert job["state"] == "failed" and job["detail"] == "Cancelled by sam before it started."
    with connect() as vc:
        assert vc.vm(m["vmName"]) is None
    # Nothing left to cancel.
    assert client.post(f"/api/machines/{machine_id}/cancel").status_code == 409


def test_a_running_job_stops_when_cancelled(queued, monkeypatch):
    """A deploy waiting for the machine to set itself up stops at its next check once cancelled."""
    from app.vsphere import VCenter

    r = client.post("/api/machines", json={"template": "ubuntu", "version": "26.04", "owner": "jo", "name": "slow01", "hours": 2})
    machine_id = r.json()["id"]

    def never_ready(self, vm, username, password, path):
        # Someone presses Cancel while it waits.
        client.post(f"/api/machines/{machine_id}/cancel", headers={"X-Lab-User": "sam"})
        return None

    monkeypatch.setattr(VCenter, "read_guest_file", never_ready)
    run_queued(queued)
    m = client.get(f"/api/machines/{machine_id}").json()
    assert m["state"] == "error" and m["log"][-1]["text"] == "Deploy failed: cancelled by sam"
    assert client.get(f"/api/jobs?machine={machine_id}").json()[0]["detail"] == "cancelled by sam"
    # Destroying it works as for any failed deploy.
    assert client.delete(f"/api/machines/{machine_id}").status_code == 200
    run_queued(queued)
    assert client.get(f"/api/machines/{machine_id}").status_code == 404


def test_quick_jobs_and_the_sweep_have_their_own_queue(monkeypatch):
    """Long jobs (deploys, resets) can fill the worker for hours; the sweep and quick power actions go
    on the "quick" queue, which a second worker serves, so they still run meanwhile."""
    configured = []

    class Deferrer:
        def defer(self, **_):
            pass

    class RecordingTask:
        def configure(self, **kwargs):
            configured.append(kwargs)
            return Deferrer()

    monkeypatch.setattr(jobs, "machine_action", RecordingTask())
    for action in ("deploy", "redeploy", "reset", "start", "stop", "reboot", "expire", "destroy"):
        jobs.enqueue("m-none", action, "jo")
    assert [c["queue"] for c in configured] == ["default"] * 3 + ["quick"] * 5
    # Still one job at a time per machine, across both queues.
    assert {c["lock"] for c in configured} == {"m-none"}
    assert jobs.sweep.queue == "quick"
    with session() as s:
        s.execute(Job.__table__.delete().where(Job.machine_id == "m-none"))


def test_polls_leave_out_passwords_and_send_only_new_log_lines(queued):
    """Every open page polls the lists every few seconds: no passwords there, only on the machine's own
    page, and its log comes in full once, then only the lines since."""
    m = deploy(queued, name="poll01")
    listed = next(x for x in client.get("/api/machines").json() if x["id"] == m["id"])
    assert "password" not in listed and "log" not in listed
    assert len(m["password"]) == 16 and "logAfter" not in m
    ids = [line["id"] for line in m["log"]]
    assert ids == sorted(ids)
    # Nothing new since the last line; then one more.
    assert client.get(f"/api/machines/{m['id']}?after={ids[-1]}").json()["log"] == []
    client.post(f"/api/machines/{m['id']}/extend", json={"hours": 2})
    later = client.get(f"/api/machines/{m['id']}?after={ids[-1]}").json()
    assert later["logAfter"] == ids[-1] and [line["text"] for line in later["log"]] == ["Extended by 2 h"]
    assert later["password"] == m["password"]
    # The panel's one poll: the lists as their own endpoints give them, and jobs only when asked for.
    state = client.get("/api/state").json()
    assert state["machines"] == client.get("/api/machines").json()
    assert state["instances"] == client.get("/api/instances").json()
    assert "jobs" not in state
    assert client.get("/api/state?jobs=1").json()["jobs"] == client.get("/api/jobs").json()
