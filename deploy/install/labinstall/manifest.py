"""The templates the install can build (deploy/install/manifest.toml), with what each needs, and the
ISO names they use (scripts/isos/isos.txt)."""

import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import images

PLACEHOLDER = re.compile(r"\{([a-z_]+(?:\.[a-z_]+)*)\}")


@dataclass
class Template:
    id: str
    build: str
    catalogue: str = ""          # "<template> <version>" in templates.yaml; "" for a base VM
    vars: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    isos: list[str] = field(default_factory=list)
    mirrors: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    extras: bool | str = False
    # The Packer variable the extras built in go to (extras = true): "extras", or "desktop_extras" for
    # Ubuntu Desktop, whose build takes its list there.
    extras_var: str = "extras"
    needs: list[str] = field(default_factory=list)
    internet: str = ""
    eval_days: int = 0
    base: bool = False
    # From templates.yaml.
    entry: dict = field(default_factory=dict)

    @property
    def windows(self) -> bool:
        return self.entry.get("family") == "windows"

    @property
    def disk_gb(self) -> int:
        return int(self.entry.get("diskGB", 40))

    @property
    def memory_gb(self) -> int:
        return int(self.entry.get("memoryGB", 2))

    @property
    def import_script(self) -> bool:
        return not self.build.startswith("packer/build.sh")


@dataclass
class Iso:
    name: str
    file: str
    sha256: str = ""
    size: int = 0


class Manifest:
    def __init__(self, src: Path):
        self.src = src
        data = tomllib.loads((src / "deploy/install/manifest.toml").read_text())
        self.extras_media: dict[str, list[str]] = data.get("extras", {})
        self.extras_online_only: dict[str, str] = data.get("extras_online_only", {})
        self.extras_mirrors: dict[str, str] = data.get("extras_mirrors", {})
        self.choices_mirrors: dict[str, str] = data.get("choices_mirrors", {})
        # The ISOs each extra needs attached at deploy (images.py): the Docker extras' and k3s's.
        self.image_isos: dict[str, list[str]] = images.needed(src)
        catalogue = yaml.safe_load((src / "backend/templates.yaml").read_text())
        self.catalogue = {f"{e['template']} {e['version']}": e for e in catalogue}
        self.templates: dict[str, Template] = {}
        for t in data["template"]:
            tpl = Template(**t)
            if tpl.catalogue:
                if tpl.catalogue not in self.catalogue:
                    raise ValueError(f"manifest.toml: {tpl.id}: no '{tpl.catalogue}' in templates.yaml")
                tpl.entry = self.catalogue[tpl.catalogue]
            self.templates[tpl.id] = tpl
        for t in self.templates.values():
            for n in t.needs:
                if n not in self.templates:
                    raise ValueError(f"manifest.toml: {t.id} needs {n}, which isn't a template")
        self.isos = read_isos(src / "scripts/isos/isos.txt", src / "deploy/install/isos.sha256")

    def iso_file(self, ref: str) -> str:
        """An ISO reference (a name in isos.txt, or file:<name>) as its file name on the datastore."""
        if ref.startswith("file:"):
            return ref[5:]
        if ref not in self.isos:
            raise ValueError(f"manifest.toml: no ISO '{ref}' in scripts/isos/isos.txt")
        return self.isos[ref].file

    def selected(self, build: list[str]) -> list[Template]:
        """The templates a [templates] build list names, with what they need, in build order."""
        # "capture" is the packet capture appliance (capture.py), not a template.
        ids = list(self.templates) if "all" in build else [i for i in build if i != "capture"]
        unknown = [i for i in ids if i not in self.templates]
        if unknown:
            raise ValueError(f"unknown template {', '.join(unknown)}; known: {', '.join(self.templates)}")
        order: list[str] = []

        def add(i: str) -> None:
            for n in self.templates[i].needs:
                add(n)
            if i not in order:
                order.append(i)

        for i in ids:
            add(i)
        return [self.templates[i] for i in order]


def read_isos(path: Path, sums: Path) -> dict[str, Iso]:
    """isos.txt: <name> <url> <checksum> [file]. The file is fetch.sh's: the given name or the URL's
    last part, without .bz2, .xz or .gz (fetch.sh unpacks those). isos.sha256, written by bundle.sh: <name> <file> <size> <sha256>."""
    isos = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts or line.lstrip().startswith("#"):
            continue
        name, url = parts[0], parts[1]
        file = re.sub(r"\.(bz2|xz|gz)$", "", parts[3] if len(parts) > 3 else url.rsplit("/", 1)[-1])
        isos[name] = Iso(name, file)
    if sums.exists():
        for line in sums.read_text().splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] in isos:
                isos[parts[0]].size, isos[parts[0]].sha256 = int(parts[2]), parts[3]
    return isos


def resolve(text: str, values: dict[str, str]) -> str | None:
    """Fills a value's {placeholders}; None if one of them has no value (then it isn't passed)."""
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        v = values.get(m.group(1), "")
        if not v:
            missing = True
        return v

    out = PLACEHOLDER.sub(sub, text)
    return None if missing else out


def placeholder_values(mirrors: dict[str, str], media: str, media_dir: str, http_ip: str) -> dict[str, str]:
    values = {"media": media, "media_dir": media_dir, "http_ip": http_ip}
    for name, url in mirrors.items():
        if not isinstance(url, str) or not url:
            continue
        url = url.rstrip("/")
        parts = urlsplit(url)
        values[f"mirror.{name}"] = url
        values[f"mirror.{name}.host"] = parts.netloc
        values[f"mirror.{name}.path"] = parts.path or "/"
    return values


def command(t: Template, values: dict[str, str], extra_vars: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """The build's command line and environment, its placeholders filled."""
    argv = [resolve(a, values) or a for a in shlex.split(t.build)]
    env = {}
    for e in t.env:
        k, _, v = e.partition("=")
        r = resolve(v, values)
        if r is not None:
            env[k] = r
    if not t.import_script:
        for v in t.vars:
            k, _, val = v.partition("=")
            r = resolve(val, values)
            if r is not None:
                argv += ["-var", f"{k}={r}"]
        for k, val in extra_vars.items():
            argv += ["-var", f"{k}={val}"]
    return argv, env
