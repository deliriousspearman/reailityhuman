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
class LabExtra:
    # An extra applied to a lab machine, with its options filled in. A machine option's value can be
    # "@<role>", meaning the instance's machine with that role (e.g. a member joining the instance's
    # "@dc"); the orchestration fills in that machine's id when the instance is deployed.
    id: str
    options: tuple[tuple[str, str], ...] = ()


# A machine option's value of this form names another machine in the same instance, by role.
MACHINE_REF = re.compile(r"^@([a-z][a-z0-9]{0,8})$")


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
    # Extras applied when the machine is deployed, with their options. A member's machine option can
    # point at an earlier machine in the instance with "@<role>".
    extras: tuple[LabExtra, ...] = ()


@dataclass(frozen=True)
class Flag:
    # Short id, e.g. "user" or "root".
    id: str
    # Where it's planted, for the checklist on the lab's page, e.g. "the workstation desktop (user.txt)".
    where: str
    # The machine (a lab machine's role name) this flag is planted on; empty for a flag that isn't
    # planted automatically (just listed).
    machine: str = ""
    # How it's planted on that machine, once it's running (actions.plant_flags), one of:
    #  - file: the flag's value is written to this path in the guest (e.g. r"C:\Users\...\user.txt");
    #  - run:  this program is run in the guest with the flag's value as its last argument (e.g. a
    #          script baked into the golden template that drops the flag into a mailbox).
    file: str = ""
    run: str = ""


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


def _lab_extra(slug: str, machine: str, entry) -> LabExtra:
    """One of a lab machine's extras: either "id" (no options) or {id: {option: value}}."""
    if isinstance(entry, str):
        return LabExtra(id=entry)
    if not isinstance(entry, dict) or len(entry) != 1:
        raise ValueError(f"labs.yaml: {slug}/{machine}: each extra is an id or a single {{id: {{options}}}} mapping")
    (extra_id, options), = entry.items()
    options = options or {}
    if not isinstance(options, dict):
        raise ValueError(f"labs.yaml: {slug}/{machine}: the options of '{extra_id}' must be a mapping")
    return LabExtra(id=extra_id, options=tuple((k, str(v)) for k, v in options.items()))


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
                extras=tuple(_lab_extra(slug, m["name"], x) for x in m.get("extras", [])),
            )
            for m in e.get("machines", [])
        )
        flags = tuple(
            Flag(id=f["id"], where=f["where"], machine=f.get("machine", ""), file=f.get("file", ""), run=f.get("run", ""))
            for f in e.get("flags", [])
        )
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
        names = {m.name for m in lab.machines}
        for f in lab.flags:
            if f.machine and f.machine not in names:
                raise ValueError(f"labs.yaml: {slug}: flag '{f.id}' is planted on '{f.machine}', which isn't one of its machines")
            if f.file and f.run:
                raise ValueError(f"labs.yaml: {slug}: flag '{f.id}' can be planted as a file or by running a program, not both")
            if (f.file or f.run) and not f.machine:
                raise ValueError(f"labs.yaml: {slug}: flag '{f.id}' says how to plant it but not on which machine")
        for m in lab.machines:
            if not NAME_RULE.match(m.name):
                raise ValueError(f"labs.yaml: {slug}: '{m.name}' isn't a valid machine name (1-9 lowercase letters or digits, starting with a letter)")
            if m.boot_order < 1:
                raise ValueError(f"labs.yaml: {slug}/{m.name}: bootOrder starts at 1")
            # A machine option in a lab names another machine by "@role"; it must be a machine in the
            # lab, carry the extra the option needs, and boot earlier (so it's up first).
            boot = {lm.name: lm.boot_order for lm in lab.machines}
            roles = {lm.name for lm in lab.machines}
            for lx in m.extras:
                x = extras.find(lx.id)
                if x is None:
                    raise ValueError(f"labs.yaml: {slug}/{m.name} lists extra '{lx.id}', which isn't in extras.yaml")
                opts = {o.id: o for o in x.options}
                for opt_id, value in lx.options:
                    o = opts.get(opt_id)
                    if o is None:
                        raise ValueError(f"labs.yaml: {slug}/{m.name}: extra '{lx.id}' has no option '{opt_id}'")
                    if ref := MACHINE_REF.match(value):
                        target = ref.group(1)
                        if o.type != "machine":
                            raise ValueError(f"labs.yaml: {slug}/{m.name}: '{lx.id}.{opt_id}' is set to a machine (@{target}) but isn't a machine option")
                        if target not in roles:
                            raise ValueError(f"labs.yaml: {slug}/{m.name}: '{lx.id}.{opt_id}' points at @{target}, which isn't one of the lab's machines")
                        if target == m.name:
                            raise ValueError(f"labs.yaml: {slug}/{m.name}: '{lx.id}.{opt_id}' points at itself")
                        if boot[target] >= m.boot_order:
                            raise ValueError(f"labs.yaml: {slug}/{m.name}: '{lx.id}.{opt_id}' points at @{target}, which must boot before it (give @{target} a lower bootOrder)")
                    elif o.type == "machine":
                        raise ValueError(f"labs.yaml: {slug}/{m.name}: machine option '{lx.id}.{opt_id}' must be set to another machine as '@role'")
        # Whether its machines' templates exist and offer its extras is checked in unavailable_reason,
        # not here: a lab that references a template not built yet (or retired) is listed as "coming
        # soon" rather than crashing the panel, the same as a template that's planned.
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


def unavailable_reason(lab: Lab) -> str:
    """Why this lab can't be deployed right now, or "" if it can: a machine's template isn't built (or
    was retired), or doesn't offer an extra the lab applies. Checked here rather than at load, so a lab
    waiting on a template is listed as "coming soon" instead of crashing the panel. A `planned` lab is
    always unavailable."""
    if lab.planned:
        return f"{lab.title} isn't built yet"
    for m in lab.machines:
        t = catalogue.find(m.template, m.version)
        if t is None:
            return f"{m.name} needs {m.template} {m.version}, which isn't a template that can be deployed"
        for lx in m.extras:
            if lx.id not in t.extras:
                return f"{m.template} {m.version} doesn't offer the '{lx.id}' extra {m.name} needs"
    return ""


def deployable() -> dict[str, Lab]:
    """Labs whose machines can all be deployed now (their templates are built and offer their extras)."""
    return {slug: lab for slug, lab in labs().items() if not unavailable_reason(lab)}


def total_memory_gb(lab: Lab) -> int:
    """How much memory an instance of this lab needs, for capacity checks."""
    total = 0
    for m in lab.machines:
        t = catalogue.find(m.template, m.version)
        if t is not None:
            total += extras.memory_gb(t.memory_gb, [{"id": lx.id} for lx in m.extras])
    return total
