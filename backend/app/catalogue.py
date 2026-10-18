"""Which template versions can be deployed, and where they are in vCenter (templates.yaml); also
those still to be built ("planned"), so people can see what's coming.

The frontend has the full catalogue (descriptions, categories, flags) in src/lib/templates.ts; only
the versions listed here can be deployed, and the rest show as "coming soon".
"""

from dataclasses import dataclass
from functools import lru_cache

import yaml

from . import extras
from .config import settings


@dataclass(frozen=True)
class LiveTemplate:
    template: str
    version: str
    # Inventory path of the vSphere template, under the datacenter's VM folder.
    vsphere: str
    cpu: int
    memory_gb: int
    disk_gb: int
    username: str
    # OS family: "debian" (Debian, Ubuntu), "rhel" (CentOS Stream, Rocky, Alma), "windows", "legacy"
    # (old Linux and OPNsense, set up by lab-firstboot: give adminGroup), "vyos" (VyOS's own
    # cloud-init: configuration commands), or "image" (a complete image deployed as it is, e.g. a
    # practice target: nothing is set up on it, and its own sign-in is fixed_password).
    family: str = "debian"
    # The group that gives the user sudo. Default: "sudo" for the debian family, "wheel" for rhel.
    admin_group: str = "sudo"
    # Extras (extras.yaml) whose packages are in this template, so they can be chosen at deploy.
    extras: tuple[str, ...] = ()
    # How people reach it (ssh, rdp, web, console), and its web address with {ip}. Empty: the
    # frontend catalogue's (src/lib/templates.ts).
    access: tuple[str, ...] = ()
    web_url: str = ""
    # Not built yet: listed (e.g. under each service it will offer) but can't be deployed.
    planned: bool = False
    # Extras it will offer once rebuilt with today's prepare.sh: prepped, but not in it yet.
    planned_extras: tuple[str, ...] = ()
    # Family "image" only: its own, well-known password, which every machine from it has.
    fixed_password: str = ""


ACCESS = ("ssh", "rdp", "web", "console")


def _load() -> list[LiveTemplate]:
    with open(settings().catalogue_path) as f:
        entries = yaml.safe_load(f) or []
    out = []
    for e in entries:
        family = e.get("family", "debian")
        if family not in extras.FAMILIES:
            raise ValueError(f"templates.yaml: {e['template']} {e['version']}: unknown family '{family}'")
        planned = bool(e.get("planned", False))
        if not planned and not e.get("vsphere"):
            raise ValueError(f"templates.yaml: {e['template']} {e['version']}: no vsphere template (or mark it planned)")
        t = LiveTemplate(
            template=e["template"],
            version=str(e["version"]),
            vsphere=e.get("vsphere", ""),
            cpu=int(e["cpu"]),
            memory_gb=int(e["memoryGB"]),
            disk_gb=int(e["diskGB"]),
            username=e["username"],
            family=family,
            admin_group=e.get("adminGroup", {"rhel": "wheel", "windows": "Administrators"}.get(family, "sudo")),  # legacy: set it per entry
            extras=tuple(e.get("extras", [])),
            access=tuple(e.get("access", [])),
            web_url=e.get("webUrl", ""),
            planned=planned,
            planned_extras=tuple(e.get("plannedExtras", [])),
            fixed_password=str(e.get("password", "")),
        )
        if (family == "image") != bool(t.fixed_password):
            raise ValueError(f"templates.yaml: {t.template} {t.version}: give a password for family image (its own sign-in), and only then")
        if unknown := [a for a in t.access if a not in ACCESS]:
            raise ValueError(f"templates.yaml: {t.template} {t.version}: unknown access {', '.join(unknown)}")
        if both := set(t.extras) & set(t.planned_extras):
            raise ValueError(f"templates.yaml: {t.template} {t.version}: {', '.join(sorted(both))} in both extras and plannedExtras")
        for extra_id in t.extras + t.planned_extras:
            x = extras.find(extra_id)
            if x is None or family not in x.families:
                raise ValueError(f"templates.yaml: {t.template} {t.version} lists extra '{extra_id}', which extras.yaml has no {family} steps for")
        out.append(t)
    return out


@lru_cache
def catalogue() -> dict[tuple[str, str], LiveTemplate]:
    """The templates that can be deployed, by (template, version)."""
    return {(t.template, t.version): t for t in _load() if not t.planned}


@lru_cache
def planned() -> tuple[LiveTemplate, ...]:
    """Templates not built yet, listed so people can see what's coming."""
    return tuple(t for t in _load() if t.planned)


def offered_by(extra_id: str) -> list[dict]:
    """The templates offering an extra: ready (deployable and built with it), or not yet (planned, or
    waiting to be rebuilt with it)."""
    out = []
    for t in (*catalogue().values(), *planned()):
        if extra_id in t.extras or extra_id in t.planned_extras:
            ready = not t.planned and extra_id in t.extras
            out.append({"template": t.template, "version": t.version, "ready": ready})
    return out


def find(template: str, version: str) -> LiveTemplate | None:
    return catalogue().get((template, version))
