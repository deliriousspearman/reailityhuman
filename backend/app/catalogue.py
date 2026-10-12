"""Which template versions can be deployed, and where they are in vCenter (templates.yaml).

The frontend has the full catalogue (descriptions, categories, flags) in src/lib/templates.ts; only
the versions listed here can be deployed, and the rest show as "coming soon".
"""

from dataclasses import dataclass
from functools import lru_cache

import yaml

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


@lru_cache
def catalogue() -> dict[tuple[str, str], LiveTemplate]:
    with open(settings().catalogue_path) as f:
        entries = yaml.safe_load(f) or []
    return {
        (e["template"], str(e["version"])): LiveTemplate(
            template=e["template"],
            version=str(e["version"]),
            vsphere=e["vsphere"],
            cpu=int(e["cpu"]),
            memory_gb=int(e["memoryGB"]),
            disk_gb=int(e["diskGB"]),
            username=e["username"],
        )
        for e in entries
    }


def find(template: str, version: str) -> LiveTemplate | None:
    return catalogue().get((template, version))
