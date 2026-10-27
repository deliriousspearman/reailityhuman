"""The job queue (Procrastinate, inside PostgreSQL) and the worker's tasks.

Two queues, so long jobs can't hold up short ones: deploys, redeploys and resets (minutes to hours)
go on "default", and the sweep and quick power actions on "quick". Two workers (deploy/compose.yaml):

    procrastinate --app=app.jobs.app worker --concurrency=4                 # every queue
    procrastinate --app=app.jobs.app worker --queues=quick --concurrency=3  # quick only

so the sweep and a Stop still run while four deploys fill the first. A machine's lock holds across
queues: its jobs still run one at a time, in the order they were queued.
"""

import logging

import procrastinate

from . import actions
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
