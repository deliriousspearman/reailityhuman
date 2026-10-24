"""Pro Labs: multi-machine labs deployed as one instance (labs.yaml).

A lab lists its machines, each a template from the catalogue (catalogue.py), in the order they boot
(the domain controller before the members that join it). Deploying a lab makes all its machines at
once as one instance; resetting or destroying acts on the whole instance. Flags are planted per
instance for learners to find.

The frontend has each lab's display copy (picture, long description) in src/lib/labs.ts; only the
labs here can be deployed, and the rest show as "coming soon", the same split as templates.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from . import catalogue, extras
from .config import settings

SLUG_RULE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
# A machine's role name within a lab: part of its hostname (<instance>-<name>), kept short so the
# whole stays within Windows' 15-character limit.
NAME_RULE = re.compile(r"^[a-z][a-z0-9]{0,8}$")
LEVELS = ("Beginner", "Intermediate", "Advanced")


@dataclass(frozen=True)
class LabMachine:
    # Role name, e.g. "dc"; the machine's hostname is "<instance>-<name>".
    name: str
    template: str
    version: str
    # Shown to learners, e.g. "Domain controller".
    role: str = ""
    # Lower boots and sets up first: the domain controller (1) before members that join it (2+).
    boot_order: int = 1
    # Extras applied when the machine is deployed (usually none: a lab's machines come from golden
    # templates that are already set up).
    extras: tuple[str, ...] = ()


@dataclass(frozen=True)
class Flag:
    # Short id, e.g. "user" or "root".
    id: str
    # Where it's planted, for the checklist on the lab's page, e.g. "the workstation desktop (user.txt)".
    where: str


@dataclass(frozen=True)
class Lab:
    slug: str
    title: str
    description: str
    machines: tuple[LabMachine, ...]
    flags: tuple[Flag, ...] = ()
    # The AD domain, for a domain lab; empty for standalone labs.
    domain: str = ""
    level: str = "Intermediate"
    # "lab": the whole instance resets together (domain labs, so trusts and tickets stay valid).
    reset_scope: str = "lab"
    # Not deployable yet (its golden templates aren't built): listed as "coming soon".
    planned: bool = False


def _path():
    return settings().catalogue_path.with_name("labs.yaml")


def _load() -> list[Lab]:
    with open(_path()) as f:
        entries = yaml.safe_load(f) or []
    out = []
    for e in entries:
        slug = e["slug"]
        if not SLUG_RULE.match(slug):
            raise ValueError(f"labs.yaml: '{slug}' isn't a valid slug (lowercase letters, digits, hyphens)")
        if e.get("level", "Intermediate") not in LEVELS:
            raise ValueError(f"labs.yaml: {slug}: level must be one of {', '.join(LEVELS)}")
        planned = bool(e.get("planned", False))
        machines = tuple(
            LabMachine(
                name=m["name"],
                template=m["template"],
                version=str(m["version"]),
                role=m.get("role", ""),
                boot_order=int(m.get("bootOrder", 1)),
                extras=tuple(m.get("extras", [])),
            )
            for m in e.get("machines", [])
        )
        flags = tuple(Flag(id=f["id"], where=f["where"]) for f in e.get("flags", []))
        lab = Lab(
            slug=slug,
            title=e["title"],
            description=e["description"],
            machines=machines,
            flags=flags,
            domain=e.get("domain", ""),
            level=e.get("level", "Intermediate"),
            reset_scope=e.get("resetScope", "lab"),
            planned=planned,
        )
        if not lab.machines:
            raise ValueError(f"labs.yaml: {slug} has no machines")
        if len({m.name for m in lab.machines}) != len(lab.machines):
            raise ValueError(f"labs.yaml: {slug} has two machines with the same name")
        if len({f.id for f in lab.flags}) != len(lab.flags):
            raise ValueError(f"labs.yaml: {slug} has two flags with the same id")
        for m in lab.machines:
            if not NAME_RULE.match(m.name):
                raise ValueError(f"labs.yaml: {slug}: '{m.name}' isn't a valid machine name (1-9 lowercase letters or digits, starting with a letter)")
            if m.boot_order < 1:
                raise ValueError(f"labs.yaml: {slug}/{m.name}: bootOrder starts at 1")
            # The template a machine comes from must exist (unless the whole lab is still planned),
            # and any extras it applies must be offered by that template.
            if not planned:
                t = catalogue.find(m.template, m.version)
                if t is None:
                    raise ValueError(f"labs.yaml: {slug}/{m.name} uses {m.template} {m.version}, which isn't a template that can be deployed (mark the lab planned until it's built)")
                for extra_id in m.extras:
                    if extras.find(extra_id) is None:
                        raise ValueError(f"labs.yaml: {slug}/{m.name} lists extra '{extra_id}', which isn't in extras.yaml")
                    if extra_id not in t.extras:
                        raise ValueError(f"labs.yaml: {slug}/{m.name}: {m.template} {m.version} doesn't offer the extra '{extra_id}'")
        out.append(lab)
    if len({lab.slug for lab in out}) != len(out):
        raise ValueError("labs.yaml: two labs share a slug")
    return out


@lru_cache
def labs() -> dict[str, Lab]:
    """Every lab defined, by slug (deployable and planned)."""
    return {lab.slug: lab for lab in _load()}


def find(slug: str) -> Lab | None:
    return labs().get(slug)


def deployable() -> dict[str, Lab]:
    """Labs whose machines can be deployed now (their golden templates are built)."""
    return {slug: lab for slug, lab in labs().items() if not lab.planned}


def total_memory_gb(lab: Lab) -> int:
    """How much memory an instance of this lab needs, for capacity checks."""
    total = 0
    for m in lab.machines:
        t = catalogue.find(m.template, m.version)
        if t is not None:
            total += extras.memory_gb(t.memory_gb, [{"id": i} for i in m.extras])
    return total
