"""Database tables. API responses mirror the shapes in frontend/src/lib/types.ts."""

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Machine states, as in the frontend's SingleMachineState. "error" means the last job failed and
# someone should look; the reconcile sweep moves it back to running/stopped if the VM is fine.
STABLE_STATES = {"running", "stopped", "expired", "error"}


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    # Hostname inside the VM, chosen by the person who deployed it.
    name: Mapped[str] = mapped_column(String(15), unique=True)
    template: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    # Its template's OS family when it was deployed (debian, rhel or windows), so resetting it works
    # the same even if templates.yaml has changed since.
    family: Mapped[str] = mapped_column(String(16), default="debian")
    owner: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # None: kept permanently.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    # Name of the VM in vCenter: "<owner>-<name>-<id>", unique within the folder.
    vm_name: Mapped[str] = mapped_column(String(80))
    username: Mapped[str] = mapped_column(String(32))
    # Shown on the machine page so people can sign in. The panel has no sign-in yet, so anyone who
    # can reach it can read these.
    password: Mapped[str] = mapped_column(String(128))
    ssh_key: Mapped[str | None] = mapped_column(Text)
    # Extras chosen at deploy, with every option filled in: [{"id": "apache-https", "options": {...}}].
    extras: Mapped[list] = mapped_column(JSON, default=list)
    # The image ISOs it was deployed with (extras.media), one CD each at first boot: a reset attaches
    # these same ones again, as its first-boot scripts expect those images. None before image CDs.
    media: Mapped[list | None] = mapped_column(JSON)
    # Files its extras made for people to download (extras.yaml `download`), read from the machine once
    # they're ready: {extra id: {"filename", "label", "content"}}. A VPN's client config holds its
    # private key, so like the password, anyone who can reach the panel can read these for now.
    downloads: Mapped[dict | None] = mapped_column(JSON)
    # Pro Labs: the instance it belongs to ("i-xxxx"), its lab's slug and its role name in the lab
    # (labs.yaml); None for a machine deployed on its own.
    instance_id: Mapped[str | None] = mapped_column(String(16), index=True)
    lab: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(16))
    # The action it waits to run (deploy or reset) until the machines before it in the lab's boot
    # order are ready; actions.advance_instance queues it then.
    pending: Mapped[str | None] = mapped_column(String(16))

    log: Mapped[list["LogLine"]] = relationship(
        back_populates="machine", cascade="all, delete-orphan", order_by="LogLine.id"
    )


class LogLine(Base):
    __tablename__ = "log_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    text: Mapped[str] = mapped_column(Text)
    # ok | warn | error | muted, or None for a plain line.
    tone: Mapped[str | None] = mapped_column(String(8))

    machine: Mapped[Machine] = relationship(back_populates="log")


class InstanceFlag(Base):
    """A Pro Lab instance's flags: a random value per flag, new each deploy or reset, planted into the
    lab's machines (actions.plant_flags). Learners find the values; the panel shows the checklist."""

    __tablename__ = "instance_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(16), index=True)
    # The flag's id in labs.yaml, e.g. "root".
    flag_id: Mapped[str] = mapped_column(String(32))
    # Its value this time round, e.g. "LAB{a1b2c3d4e5f6}".
    value: Mapped[str] = mapped_column(String(64))
    # Set once it's been planted on its machine; None while that's still to happen.
    planted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TemplateBuild(Base):
    """A template version the panel has deleted or built (docs/plan.md, section 11). No row: it's as
    templates.yaml says, built at its `vsphere` path."""

    __tablename__ = "template_builds"

    template: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    # built | deleted | building | failed (builds.STATES)
    state: Mapped[str] = mapped_column(String(16))
    # Where it is now, once the panel has built it (a rebuild's name has a new date); None: templates.yaml's.
    vsphere: Mapped[str | None] = mapped_column(String(255))
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set at every deploy of it, whether or not the panel ever built it.
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last build's job, and why it failed.
    job_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Kept after the machine is destroyed, so the job list still says what happened.
    machine_id: Mapped[str | None] = mapped_column(String(16), index=True)
    # e.g. "Deploy ubuntu01"
    action: Mapped[str] = mapped_column(String(128))
    # deploy | start | stop | reboot | reset | expire | destroy (actions.ACTIONS), or build (a template: builds.py)
    kind: Mapped[str] = mapped_column(String(16), default="")
    by: Mapped[str] = mapped_column(String(64))
    # queued | running | done | failed
    state: Mapped[str] = mapped_column(String(8), default="queued")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # None while it waits in the queue.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)
    # Who asked to cancel it, while it waits or runs: the worker stops it at its next check.
    cancelled_by: Mapped[str | None] = mapped_column(String(64))
    # A build job's template version, "<template>/<version>" (machine_id is None then).
    template: Mapped[str | None] = mapped_column(String(100))


class Capture(Base):
    """A packet capture on the capture appliance (app/capture.py), limited to some machines' traffic.
    The .pcap itself is a file in capture_dir; this row is what the panel lists."""

    __tablename__ = "captures"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    # The machines it's limited to, as they were when it started (kept after they're destroyed):
    # [{"id", "name", "ip", "macs"}].
    machines: Mapped[list] = mapped_column(JSON, default=list)
    # The filter as typed (may be empty), and what tcpdump ran: limited to those machines' MACs.
    user_filter: Mapped[str] = mapped_column(Text, default="")
    effective_filter: Mapped[str] = mapped_column(Text)
    seconds: Mapped[int] = mapped_column(Integer)
    # running | stopped | failed
    state: Mapped[str] = mapped_column(String(8), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    packets: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    # Who talked to whom, busiest first: [{"a", "b", "packets", "bytes"}] (addresses: IP, or MAC).
    conversations: Mapped[list] = mapped_column(JSON, default=list)
    # Why it stopped, e.g. "Time limit reached (10 minutes)".
    detail: Mapped[str | None] = mapped_column(Text)
