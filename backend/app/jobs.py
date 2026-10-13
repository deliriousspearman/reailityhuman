"""The job queue (Procrastinate, inside PostgreSQL) and the worker's tasks.

Run the worker with:  procrastinate --app=app.jobs.app worker --concurrency=4
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
    actions.run(job_id, machine_id, action)


@app.periodic(cron="* * * * *")
@app.task(name="sweep", queueing_lock="sweep")
def sweep(timestamp: int) -> None:
    actions.recover_lost_jobs()
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
    machine_action.configure(lock=machine_id).defer(job_id=job_id, machine_id=machine_id, action=action)
    return job_id
