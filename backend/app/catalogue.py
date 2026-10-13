"""Which template versions can be deployed, and where they are in vCenter (templates.yaml).

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
    # OS family: "debian" (Debian, Ubuntu) or "rhel" (CentOS Stream, Rocky, Alma).
    family: str = "debian"
    # The group that gives the user sudo. Default: "sudo" for the debian family, "wheel" for rhel.
    admin_group: str = "sudo"
    # Extras (extras.yaml) whose packages are in this template, so they can be chosen at deploy.
    extras: tuple[str, ...] = ()
    # How people reach it (ssh, rdp, web, console), and its web address with {ip}. Empty: the
    # frontend catalogue's (src/lib/templates.ts).
    access: tuple[str, ...] = ()
    web_url: str = ""


ACCESS = ("ssh", "rdp", "web", "console")


@lru_cache
def catalogue() -> dict[tuple[str, str], LiveTemplate]:
    with open(settings().catalogue_path) as f:
        entries = yaml.safe_load(f) or []
    out = {}
    for e in entries:
        family = e.get("family", "debian")
        if family not in extras.FAMILIES:
            raise ValueError(f"templates.yaml: {e['template']} {e['version']}: unknown family '{family}'")
        t = LiveTemplate(
            template=e["template"],
            version=str(e["version"]),
            vsphere=e["vsphere"],
            cpu=int(e["cpu"]),
            memory_gb=int(e["memoryGB"]),
            disk_gb=int(e["diskGB"]),
            username=e["username"],
            family=family,
            admin_group=e.get("adminGroup", "wheel" if family == "rhel" else "sudo"),
            extras=tuple(e.get("extras", [])),
            access=tuple(e.get("access", [])),
            web_url=e.get("webUrl", ""),
        )
        if unknown := [a for a in t.access if a not in ACCESS]:
            raise ValueError(f"templates.yaml: {t.template} {t.version}: unknown access {', '.join(unknown)}")
        for extra_id in t.extras:
            x = extras.find(extra_id)
            if x is None or family not in x.families:
                raise ValueError(f"templates.yaml: {t.template} {t.version} lists extra '{extra_id}', which extras.yaml has no {family} steps for")
        out[(t.template, t.version)] = t
    return out


def find(template: str, version: str) -> LiveTemplate | None:
    return catalogue().get((template, version))
