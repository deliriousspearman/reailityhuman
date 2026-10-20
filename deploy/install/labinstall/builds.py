"""Building the templates (docs/offline-install.md, step 7): one at a time, each logged, the results in
the install's state so a re-run picks up where the last one stopped."""

import functools
import http.server
import os
import re
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

from .checks import Context, Item
from .manifest import command
from .state import save

# Packer colours its output; the log and the console get it plain.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def pkrvars(ctx: Context) -> Path:
    """packer/lab.pkrvars.hcl from the config (build.sh reads it)."""
    v = ctx.cfg.data["vcenter"]
    path = ctx.manifest.src / "packer/lab.pkrvars.hcl"
    path.write_text("".join(f'{k:<16} = {hcl(val)}\n' for k, val in (
        ("vcenter_server", v["host"]), ("vcenter_insecure", v["insecure"]), ("datacenter", v["datacenter"]),
        ("cluster", v["cluster"]), ("datastore", v["datastore"]), ("network", v["network"]),
        ("template_folder", v["template_folder"]), ("iso_folder", v["iso_folder"]))))
    return path


def hcl(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else '"' + str(v).replace('"', '\\"') + '"'


class MediaServer:
    """Serves the media folder to the builds' VMs (their media_url)."""

    def __init__(self, folder: Path, port: int):
        handler = functools.partial(Quiet, directory=str(folder))
        self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def name_for(ctx: Context, item: Item, taken: set[str]) -> str:
    """tpl-<id>-<date>, with a letter after it if that's taken (a second build the same day)."""
    base = f"tpl-{item.t.id}-{date.today():%Y%m%d}"
    name, n = base, 0
    while name in taken:
        n += 1
        name = f"{base}{chr(ord('a') + n)}"
    return name


def build_all(ctx: Context, state: dict, state_path: Path, logs: Path, verbose: bool) -> None:
    items = [i for i in ctx.items if i.status == "ready"]
    if not items:
        print("Nothing to build.")
        return
    logs.mkdir(parents=True, exist_ok=True)
    pkrvars(ctx)
    admin = ctx.cfg.admin()
    v = ctx.cfg.data["vcenter"]
    base_env = dict(os.environ, VCENTER_CREDENTIALS=str(admin.file), GOVC_URL=v["host"],
                    GOVC_USERNAME=admin.user, GOVC_PASSWORD=admin.password,
                    GOVC_INSECURE="1" if v["insecure"] else "0", GOVC_DATACENTER=v["datacenter"],
                    GOVC_DATASTORE=v["datastore"], NETWORK=v["network"], FOLDER=v["template_folder"])
    taken = ctx.vc.vm_names(ctx.inv.template_folder)
    records = state.setdefault("templates", {})
    media = MediaServer(ctx.media_dir, int(ctx.cfg.get("media", "port"))) if ctx.media_url else None
    if media:
        media.__enter__()
    try:
        for n, item in enumerate(items, 1):
            t = item.t
            failed_need = [x for x in t.needs if records.get(x, {}).get("status") != "built"]
            if failed_need:
                records[t.id] = {"status": "skipped", "reason": f"{', '.join(failed_need)} didn't build"}
                save(state_path, state)
                print(f"[{n}/{len(items)}] {t.id}: skipped ({', '.join(failed_need)} didn't build)")
                continue
            name = "" if t.base else name_for(ctx, item, taken)
            extra_vars = dict(item.extra_vars)
            if name and not t.import_script:
                extra_vars["vm_name"] = name
            argv, env = command(t, ctx.values(), extra_vars)
            if name and t.import_script:
                env["NAME"] = name
            log = logs / f"{t.id}.log"
            print(f"[{n}/{len(items)}] {t.id}: building{f' {name}' if name else ''} (log: {log})", flush=True)
            started = time.time()
            ok = run(argv, dict(base_env, **env), ctx.manifest.src, log, verbose)
            minutes = (time.time() - started) / 60
            if ok:
                if t.base:
                    name = next((x for x in ctx.vc.vm_names(ctx.inv.template_folder) if x.startswith(f"{t.id}-")), "")
                records[t.id] = {"status": "built", "name": name, "extras": item.extras,
                                 "left_out": item.left_out, "minutes": round(minutes, 1),
                                 "date": f"{date.today():%Y-%m-%d}", "log": str(log)}
                taken.add(name)
                print(f"    built in {minutes:.0f} min")
            else:
                records[t.id] = {"status": "failed", "minutes": round(minutes, 1), "log": str(log),
                                 "tail": tail(log)}
                print(f"    FAILED after {minutes:.0f} min; the end of its log:")
                print("      " + "\n      ".join(tail(log, 12).splitlines()))
            save(state_path, state)
    finally:
        if media:
            media.__exit__()


def run(argv: list[str], env: dict, cwd: Path, log: Path, verbose: bool) -> bool:
    with open(log, "w") as out:
        out.write("$ " + " ".join(argv) + "\n")
        out.flush()
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             bufsize=1, stdin=subprocess.DEVNULL)
        for line in p.stdout:
            line = ANSI.sub("", line)
            out.write(line)
            # Packer's steps ("==> vsphere-iso.x: …") and the import scripts' "==> " lines.
            if verbose or line.startswith("==> "):
                print("    " + line.rstrip(), flush=True)
        return p.wait() == 0


def tail(log: Path, lines: int = 25) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""
