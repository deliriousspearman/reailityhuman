"""Test setup: PostgreSQL and vcsim from compose.test.yaml (or CI services), settings pointing at them,
and a vcsim inventory shaped like the real one (Labs folders and an Ubuntu template)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://labdeploy:labdeploy@localhost/labdeploy")
_vcsim = os.environ.get("VCSIM_URL", "localhost:8989")
os.environ.update(
    VCENTER_HOST=_vcsim,
    VCENTER_USER="user",
    VCENTER_PASSWORD="pass",
    VCENTER_INSECURE="1",
    VCENTER_DATACENTER="DC0",
    VCENTER_CLUSTER="DC0_C0",
    VCENTER_DATASTORE="LocalDS_0",
    VCENTER_NETWORK="VM Network",
    VCENTER_FOLDER="Labs/Machines",
    # vcsim VMs never report an IP; don't wait for one.
    IP_TIMEOUT_SECONDS="0",
)

import time  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from pyVmomi import vim  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import catalogue, jobs  # noqa: E402
from app.db import engine  # noqa: E402
from app.vsphere import connect, wait  # noqa: E402

# The Ubuntu template, as templates.yaml names it (builds are date-stamped: tpl-ubuntu-26.04-<date>).
TEMPLATE = catalogue.find("ubuntu", "26.04").vsphere


def _wait_for_vcsim(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with connect():
                return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


@pytest.fixture(scope="session", autouse=True)
def inventory():
    """The Ubuntu template in Labs/Templates (one of vcsim's VMs, with a "clean" snapshot) and
    Labs/Machines, as docs/setup-vsphere.md has people set up."""
    _wait_for_vcsim()
    with connect() as vc:
        if vc._path(f"DC0/vm/{TEMPLATE}"):
            return
        def folder(parent, name):
            """The folder, made if it isn't there (vcsim can outlive a test run)."""
            found = [f for f in parent.childEntity if isinstance(f, vim.Folder) and f.name == name]
            return found[0] if found else parent.CreateFolder(name)

        labs = folder(vc.datacenter.vmFolder, "Labs")
        templates = folder(labs, "Templates")
        folder(labs, "Machines")
        vm = vc._path("DC0/vm/DC0_C0_RP0_VM0")
        vc.power_off(vm)
        wait(vm.Rename_Task(TEMPLATE.rsplit("/", 1)[-1]), "Rename")
        wait(vm.CreateSnapshot_Task(name="clean", description="", memory=False, quiesce=False), "Snapshot")
        wait(templates.MoveIntoFolder_Task([vm]), "Move")
        vm.MarkAsTemplate()


@pytest.fixture(scope="session", autouse=True)
def database():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    with engine().begin() as c:
        c.execute(text("drop schema public cascade; create schema public"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine().begin() as c:
        c.execute(text("truncate machines, log_lines, jobs restart identity cascade"))
    with connect() as vc:
        for child in vc.folder.childEntity:
            if isinstance(child, vim.VirtualMachine):
                vc.destroy(child)


@pytest.fixture(autouse=True)
def first_boot_finished(request, monkeypatch):
    """vcsim has no guests to write a status file: by default, every machine has finished its first
    boot with nothing to report. Tests about the wait itself replace this (test_extras's `guest`);
    those of reading itself are marked real_guest_files."""
    from app.vsphere import VCenter

    if request.node.get_closest_marker("real_guest_files"):
        return
    monkeypatch.setattr(VCenter, "read_guest_file", lambda self, vm, username, password, path: "")


@pytest.fixture
def queued(monkeypatch):
    """Captures deferred jobs instead of sending them to the queue; run them with run_queued()."""
    deferred: list[dict] = []

    class Deferrer:
        def defer(self, **kwargs):
            deferred.append(kwargs)

    class FakeTask:
        def configure(self, **_):
            return Deferrer()

    monkeypatch.setattr(jobs, "machine_action", FakeTask())
    return deferred


def run_queued(deferred: list[dict]) -> None:
    from app import actions

    while deferred:
        actions.run(**deferred.pop(0), enqueue=jobs.enqueue)
