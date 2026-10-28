"""The job queue (Procrastinate, inside PostgreSQL) and the worker's tasks.

Three queues, so long jobs can't hold up short ones: deploys, redeploys and resets (minutes to
hours) go on "default", the sweep and quick power actions on "quick", and template builds (app/builds.py)
on "build". Three workers (deploy/compose.yaml):

    procrastinate --app=app.jobs.app worker --queues=default,quick --concurrency=4  # deploys and quick
    procrastinate --app=app.jobs.app worker --queues=quick --concurrency=3          # quick only
    procrastinate --app=app.jobs.app worker --queues=build --concurrency=1          # the builder

so the sweep and a Stop still run while four deploys fill the first. A machine's lock holds across
queues: its jobs still run one at a time, in the order they were queued. Builds share one lock: one
at a time, whatever the builder's concurrency.
"""

import logging

import procrastinate

from . import actions, builds
from .config import settings
from .db import session
from .models import Job, Machine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=settings().database_url))


@app.task(name="machine_action")
def machine_action(job_id: int, machine_id: str, action: str) -> None:
    actions.run(job_id, machine_id, action, enqueue)


QUICK = "quick"
# Actions that take seconds (destroy: a minute or two at most), not a machine's whole setup.
QUICK_ACTIONS = {"start", "stop", "reboot", "expire", "destroy"}


@app.periodic(cron="* * * * *")
@app.task(name="sweep", queueing_lock="sweep", queue=QUICK)
def sweep(timestamp: int) -> None:
    actions.recover_lost_jobs()
    actions.advance_instances(enqueue)
    builds.ensure_builds(enqueue_build)
    actions.expiry_sweep(enqueue)
    actions.reconcile()
    if timestamp % 3600 < 60:  # once an hour is plenty
        actions.prune_history()


VERBS = {
    "deploy": "Deploy",
    "redeploy": "Redeploy",
    "start": "Start",
    "stop": "Stop",
    "reboot": "Reboot",
    "reset": "Reset",
    "expire": "Expire",
    "destroy": "Destroy",
}


def enqueue(machine_id: str, action: str, by: str) -> int:
    """Records a job and queues it. One job runs per machine at a time (the lock); others wait."""
    with session() as s:
        m = s.get(Machine, machine_id)
        job = Job(machine_id=machine_id, action=f"{VERBS[action]} {m.name if m else machine_id}", kind=action, by=by)
        s.add(job)
        s.flush()
        job_id = job.id
    queue = QUICK if action in QUICK_ACTIONS else "default"
    machine_action.configure(lock=machine_id, queue=queue).defer(job_id=job_id, machine_id=machine_id, action=action)
    return job_id


BUILD = "build"


@app.task(name="template_build", queue=BUILD)
def template_build(job_id: int, template: str, version: str) -> None:
    builds.run_build(job_id, template, version, enqueue)


def enqueue_build(template: str, version: str, by: str) -> int | None:
    """Records a template build and queues it, unless one is queued or running already (its id is
    returned then, None if it was only just queued by another caller)."""
    with session() as s:
        if job := builds.active_build(s, template, version):
            return job.id
        job = Job(machine_id=None, template=builds.key(template, version), action=f"Build {template} {version}", kind="build", by=by)
        s.add(job)
        s.flush()
        job_id = job.id
    try:
        template_build.configure(lock="template-build", queueing_lock=f"build:{builds.key(template, version)}").defer(
            job_id=job_id, template=template, version=version
        )
    except procrastinate.exceptions.AlreadyEnqueued:
        with session() as s:  # another caller queued it a moment ago: drop this record
            s.delete(s.get(Job, job_id))
        return None
    return job_id
