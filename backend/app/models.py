"""Database tables. API responses mirror the shapes in frontend/src/lib/types.ts."""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
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
    owner: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # None: kept permanently.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    # Name of the VM in vCenter: "<name>-<id>", unique within the folder.
    vm_name: Mapped[str] = mapped_column(String(80))
    username: Mapped[str] = mapped_column(String(32))
    # Shown on the machine page so people can sign in. The panel has no sign-in yet, so anyone who
    # can reach it can read these.
    password: Mapped[str] = mapped_column(String(128))
    ssh_key: Mapped[str | None] = mapped_column(Text)
    # Extras chosen at deploy, with every option filled in: [{"id": "apache-https", "options": {...}}].
    extras: Mapped[list] = mapped_column(JSON, default=list)

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


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Kept after the machine is destroyed, so the job list still says what happened.
    machine_id: Mapped[str | None] = mapped_column(String(16), index=True)
    # e.g. "Deploy ubuntu01"
    action: Mapped[str] = mapped_column(String(128))
    # deploy | start | stop | reboot | reset | expire | destroy (actions.ACTIONS)
    kind: Mapped[str] = mapped_column(String(16), default="")
    by: Mapped[str] = mapped_column(String(64))
    # queued | running | done | failed
    state: Mapped[str] = mapped_column(String(8), default="queued")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)
