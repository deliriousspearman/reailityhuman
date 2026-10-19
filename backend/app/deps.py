"""What the API's routes share: the database session, who's asking, and finding machines."""

import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_session
from .models import LogLine, Machine

# No sign-in yet: people type their name when they deploy, and the panel sends it with every
# request (X-Lab-User) so jobs record who did what. Without one, it's "anyone".
ANYONE = "anyone"
OWNER_RULE = re.compile(r"^[a-z][a-z0-9-]{0,19}$")

Db = Annotated[Session, Depends(get_session)]


def actor(x_lab_user: Annotated[str | None, Header()] = None) -> str:
    """Who's asking, as the panel says (no sign-in yet, so it's taken on trust)."""
    name = (x_lab_user or "").strip().lower()
    return name if OWNER_RULE.match(name) else ANYONE


Actor = Annotated[str, Depends(actor)]


def get_machine(db: Session, machine_id: str) -> Machine:
    m = db.get(Machine, machine_id)
    if m is None:
        raise HTTPException(404, "There's no machine with that id. It may have been destroyed.")
    return m


def add_log(db: Session, m: Machine, text_: str, tone: str | None = None) -> None:
    db.add(LogLine(machine_id=m.id, text=text_, tone=tone))
