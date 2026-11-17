# Developer guide

How the lab panel works inside: its parts, data, jobs, templates, extras, Pro Labs and console, and
how to develop, test and ship it. For running the site (adding machines and Pro Labs, capacity,
backups), see the [Admin guide](admin-guide.md).

> **Note:** Paths are from the repository's root. Addresses in this guide use documentation ranges
> (192.0.2.0/24, 198.51.100.0/24) and `.example` names, as everything committed here must.

## 1. What the panel is

The panel deploys, resets and tears down virtual machines on VMware vSphere, for a LAN without
internet access. It offers two things:

- **Single machines.** One VM from a template (Ubuntu, Windows Server, Kali, OPNsense, …) with
    optional *extras* ticked at deploy (web servers, databases, Active Directory, Docker apps, …).
- **Pro Labs.** A set of machines deployed together as one *instance* (e.g. Brookfield: a domain
    controller, an Exchange server and a workstation), set up in boot order, with flags planted fresh
    in each instance.

There is **no sign-in**. Learners type a name when they deploy; the browser remembers it and sends it
as the `X-Lab-User` header, and the API uses it only to label jobs and log lines. Every machine is
everyone's, and `/admin` is open to anyone who can reach the panel.

## 2. Architecture

```text
 browser ── HTTPS ──▶ Caddy (deploy/Caddyfile)
                        ├── /            static SvelteKit build (frontend/build → /srv/site)
                        └── /api/*  ──▶  api: FastAPI + uvicorn (backend/app)
                                           │  writes rows, queues jobs
                                           ▼
                                     PostgreSQL 16  ◀── Procrastinate job queue lives here too
                                           ▲
                         ┌─────────────────┴─────────────────┐
                    worker (all queues,               sweeper (quick queue,
                    concurrency 4)                    concurrency 3)
                         └───────────── pyVmomi ─────────────┘
                                           ▼
                              vCenter ── ESXi host(s) ── datastore, port group (DHCP)
```

The browser never talks to vCenter. The API answers from the database and queues work; the workers
do everything that touches vSphere. The console is the one exception that streams. The API relays
the browser's WebSocket to ESXi (see [Console relay](#10-console-relay)).

The services in `deploy/compose.yaml`:

| Service | What it runs |
|---|---|
| `caddy` | Ports 80/443, TLS from Caddy's internal CA, serves the site and proxies `/api` |
| `postgres` | postgres:16-alpine, with a health check |
| `api` | `alembic upgrade head`, then uvicorn on :8000. Must stay **one process** (console tickets live in memory) |
| `worker` | `procrastinate worker --concurrency=4`: every queue (deploys, resets, power changes) |
| `sweeper` | `procrastinate worker --queues=quick --concurrency=3`: quick jobs and the per-minute sweep, so they never wait behind a long deploy |
| `backup` | `pg_dump` at start and daily into `/srv/lab-deploy/backups`, kept 14 days |

All backend services read `lab-deploy.env` (see [Configuration reference](#14-configuration-reference)).

## 3. Repository tour

| Path | What's there |
|---|---|
| `backend/app/` | The API and the worker's code (below) |
| `backend/templates.yaml` | The catalogue: which template versions can be deployed, and where they are in vCenter |
| `backend/extras.yaml` | Every extra, with its options and per-family install scripts |
| `backend/labs.yaml` | Pro Lab definitions |
| `backend/alembic/` | Database migrations |
| `backend/tests/` | pytest suite, run against PostgreSQL and vcsim |
| `frontend/` | The SvelteKit panel (static build) |
| `deploy/` | Compose file, Caddyfile, `deploy.sh`, `setup-server.sh`, offline bundle and installer |
| `packer/` | One folder per template build, plus `build.sh`; import scripts for complete images |
| `scripts/template/` | `prepare.sh`/`clean.sh` (Linux), `prepare.ps1`/`clean.ps1` (Windows), appliance first-boot scripts |
| `scripts/isos/` | `isos.txt` and `fetch.sh`: download, verify and upload ISOs; `fetch-images.sh`: an ISO of each Docker extra's image. Everything else downloaded from outside: [external-resources.md](external-resources.md) |
| `scripts/e2e/` | `run.py`: deploys real machines through the panel and checks them |
| `scripts/setup_vcenter.py` | Creates the vCenter folders, roles and permissions |
| `docs/` | These guides, the runbooks, the plan and the roadmap |

### The backend modules (`backend/app/`)

| Module | Purpose |
|---|---|
| `config.py` | `Settings` (pydantic-settings), read only from the environment; `settings()` is cached |
| `db.py` | The engine and `session()` (commits on success, rolls back on error) |
| `deps.py` | FastAPI dependencies: `actor()` reads `X-Lab-User` (anything not matching `^[a-z][a-z0-9-]{0,19}$` becomes `anyone`), `get_machine()`, `add_log()` |
| `models.py` | SQLAlchemy tables: `Machine`, `LogLine`, `Job`, `InstanceFlag` |
| `api.py` | The `/api` router: request models, output shapers, the capacity check, and `create_app()` |
| `jobs.py` | The Procrastinate app, the `machine_action` and `sweep` tasks, and `enqueue()` |
| `actions.py` | What the worker does for each action, setup waits, flags, and the sweep's parts |
| `vsphere.py` | The pyVmomi adapter, `VCenter`: clone, power, snapshots, guest operations, capacity, console tickets |
| `catalogue.py` | Loads and validates `templates.yaml` |
| `extras.py` | Loads `extras.yaml`; resolves options; builds the Linux cloud-config and the Windows runner |
| `cloudinit.py` | First-boot data per family, password rules and generation, a pure-Python `sha512_crypt` |
| `labs.py` | Loads and validates `labs.yaml` |
| `console.py` | The WebMKS console relay |
| `capture.py` | Packet captures: the capture appliance over SSH, the filter's scope, running captures, their routes and WebSocket |
| `pcap.py` | Reads a pcap stream as it arrives: whole packets, a line each for the live table, and conversations |

## 4. Data model

| Table | Columns that matter |
|---|---|
| `machines` | `id` (`m-xxxx`), `name` (unique, ≤15 chars, a hostname), `template`, `version`, `family`, `owner`, `vm_name` (`<owner>-<name>-<hex>` in vCenter), `state`, `created_at`, `expires_at` (null = kept permanently), `ip`, `username`, `password` (plaintext, shown to learners), `ssh_key`, `extras` (JSON `[{id, options}]`), and for Pro Labs `instance_id`, `lab`, `role`, `pending` |
| `log_lines` | The activity log per machine: `machine_id` (cascade delete), `at`, `text`, `tone` (`ok`, `warn`, `error`, `muted`) |
| `jobs` | `id`, `machine_id` (**no** foreign key, so jobs outlive destroyed machines), `action` (a label such as "Deploy ubuntu01"), `kind`, `by`, `state` (`queued`, `running`, `done`, `failed`), `queued_at`, `started_at`, `finished_at`, `detail`, `cancelled_by` |
| `instance_flags` | One row per planted flag: `instance_id`, `flag_id`, `value` (`LAB{…}`), `planted_at` |
| `template_builds` | Templates the panel deleted or built: `template`, `version`, `state`, `vsphere`, `built_at`, `last_deployed_at`, `job_id`, `detail` |
| `captures` | Packet captures: `id` (`c-xxxxxx`), `owner`, `machines` (JSON, as they were: id, name, ip, macs), `user_filter`, `effective_filter`, `seconds`, `state` (`running`, `stopped`, `failed`), `started_at`, `stopped_at`, `packets`, `bytes`, `conversations` (JSON), `detail`. The .pcap is `/capture/files/<id>.pcap` |

A Pro Lab instance has no table of its own. It is the set of machines sharing an `instance_id`
(`i-xxxx`).

Migrations (`backend/alembic/versions/`): `0001` initial tables and Procrastinate's schema · `0002`
machine extras · `0003` unique machine names · `0004` `jobs.kind` · `0005` `jobs.queued_at` ·
`0006` `machines.family` · `0007` `jobs.cancelled_by` · `0008` instance columns on machines · `0009`
`instance_flags` · `0010` `template_builds` · `0011` `machines.media` · `0012` `captures`. Add a new one with `alembic revision -m "…"` in `backend/`. The `api` container
runs `alembic upgrade head` on every start.

### Machine states

```text
                ┌──────────── API sets a busy state, queues a job ───────────┐
 stable:  running · stopped · error · expired                busy:  deploying · stopping · rebooting
                ▲                                                   resetting · destroying
                └──────── worker sets the result (or error) ─────────────────┘
```

- **Which actions are allowed.** The API accepts an action only from a stable state (`require_idle`).
    An `expired` machine accepts only destroy, extend, keep or a new expiry. Giving it time queues a
    `start`. There is no `starting` state: start uses `deploying`.
- **What the worker sets.** On success it sets `running` (`stopped` after a stop); destroy deletes
    the row. Any exception sets `error`, and the job's `detail` holds the message (with the end of the
    machine's setup log, for setup failures).
- **What the sweep sets.** Expiry turns a machine `expired` (powered off); after `GRACE_MINUTES` it
    turns `destroying`. Reconcile makes `running`/`stopped` follow the VM's real power state. An
    `error` left by a failed deploy, redeploy or reset stays `error`, and a VM that has vanished
    becomes `error`.
- **An instance's state** is derived from its machines (`api.py`, near `instance_out`): the first
    busy machine's state, otherwise `error`, `expired`, all-`stopped`, or `running`.

## 5. API reference

Everything is under `/api`. The schema is at `/api/openapi.json`; the interactive docs pages are
switched off.

**Requests that change something** (POST, PUT, PATCH, DELETE) are refused with 403 when a browser
sends them from another site's page: their `Origin` isn't the panel's own host (`Host`, or
`X-Forwarded-Host`), or `Sec-Fetch-Site` says `cross-site` (`same_site_only` in `api.py`). There's no
sign-in yet, so a plain form elsewhere could otherwise post them. Clients other than browsers send
neither header, and pass.

**Config and status**

| Method | Path | Purpose |
|---|---|---|
| GET | `/config` | Templates, services (extras with `offeredBy`), labs, limits and validation rules: everything the frontend needs to draw forms |
| GET | `/health` | Database and vCenter reachability |
| GET | `/capacity` | Memory, CPU and datastore (read from vCenter, cached 30 s) |
| GET | `/state?jobs=1` | Machines and instances (and jobs): what the panel polls |

**Machines**

| Method | Path | Purpose |
|---|---|---|
| GET | `/machines` | All machines, without passwords or logs |
| GET | `/machines/{id}?after=` | One machine, with password and log lines (after a line id, if given) |
| POST | `/machines` | Deploy (201). Body: `template`, `version`, `name`, `hours` (null = permanent), `owner`, optional `password`, `sshKey`, `extras` |
| POST | `/machines/{id}/start` · `stop` · `reboot` · `reset` · `redeploy` | Power and rebuild actions |
| POST | `/machines/{id}/cancel` | Cancel its queued or running jobs; a cancelled deploy, redeploy or reset powers its VM off |
| POST | `/machines/{id}/extend` | `{hours}`: add time |
| POST | `/machines/{id}/keep` | Keep permanently (within `MAX_PERMANENT`) |
| POST | `/machines/{id}/expiry` | `{hours}`: a new expiry, counted from now |
| DELETE | `/machines/{id}` | Destroy |
| GET | `/machines/{id}/downloads/{extra}` | A file the extra made for people to download (a VPN's client config) |
| POST | `/machines/{id}/console` | A one-off console path (see [Console relay](#10-console-relay)) |
| WS | `/console/{token}` | The console stream |

`hours` is 1–720 (`MAX_HOURS`). Names must match `^[a-z](?:[a-z0-9-]{0,13}[a-z0-9])?$`.

A Pro Lab's machine refuses `extend`, `keep`, `expiry`, destroy, and (in a lab that resets together)
`reset` on its own, with 409 (`require_on_its_own`): those go with the whole instance. Deploys, and
keeping a machine, take a PostgreSQL advisory lock while they count machines and free capacity
(`lock_deploys`), so two at once can't both take the last place.

**Pro Lab instances**

| Method | Path | Purpose |
|---|---|---|
| GET | `/instances`, `/instances/{id}` | List, or one |
| POST | `/instances` | Deploy a lab: `{lab, owner, hours}` |
| POST | `/instances/{id}/reset` · `extend` · `cancel` | Applied to every machine (reset in boot order) |
| DELETE | `/instances/{id}` | Destroy every machine |

**Admin**

| Method | Path | Purpose |
|---|---|---|
| GET | `/leftovers` | VMs in the machines folder that no machine row owns |
| DELETE | `/leftovers/{name}` | Delete one (re-checked first) |
| GET | `/jobs?limit=&machine=` | Jobs, newest first (`limit` 1–500); `cancelledBy` while one is stopping |
| GET | `/templates` | Every template version: built or not, size, machines using it, whether it can be deleted |
| DELETE | `/templates/{template}/{version}` | Delete it, keeping its ISOs (the next deploy builds it again) |
| POST | `/templates/{template}/{version}/build` | Build it now (202) |
| POST | `/templates/{template}/{version}/cancel` | Cancel its queued or running build |

**Packet captures** (`capture.py`; requests carry `X-Lab-User`, and only your own machines can be
captured)

| Method | Path | Purpose |
|---|---|---|
| POST | `/captures/check` | `{machineIds or instanceId, filter}`: the filter tcpdump would run, or 400 with tcpdump's complaint |
| POST | `/captures` | Start (201): `{machineIds or instanceId, filter, seconds}` |
| GET | `/captures`, `/captures/{id}` | List (newest first), or one; a running one's counts are live |
| POST | `/captures/{id}/stop` | Stop it; answers once it's recorded |
| GET | `/captures/{id}/pcap` | The .pcap (a running one's so far) |
| GET | `/captures/{id}/packets?after=&limit=` | A finished capture's lines for the table, from its file |
| DELETE | `/captures/{id}` | Delete a finished one and its file |
| WS | `/captures/{id}/live` | A running one's new lines, counts and conversations every 0.5 s; `done: true` last |
| GET | `/capture-appliance` | The appliance's address, whether it answers, and the panel's public key |

Errors are JSON `{"detail": "…"}` with a sentence meant for people; the frontend shows it as is.

## 6. Jobs and the worker

### Queueing

`jobs.enqueue()` inserts a `jobs` row, then defers the Procrastinate task `machine_action` with
`lock=<machine id>`. Each machine therefore runs one job at a time, in order.

- **Queues.** `quick` takes start, stop, reboot, expire and destroy; `default` takes deploy,
    redeploy and reset. The `sweeper` only takes `quick`, so a long Windows deploy never holds up a
    stop.
- **The API.** `api.queue()` commits the database change before it enqueues, so the worker always
    sees the new state.

### What each action does (`actions.py`)

Each job opens its own vCenter session (`vsphere.connect()`).

- **deploy:**
    1. Resolve the extras and fill in `machine`-type options with the other machine's details.
    2. Build the family's first-boot data (`cloudinit.py`).
    3. **Linked-clone** the template's `clean` snapshot, then reconfigure it (CPU, memory,
       `guestinfo.*`, NIC), and take the clone's own `clean` snapshot before first boot.
    4. Power on and wait for an address (`_record_ip`). A machine that gets an ESXi or vCenter address
       from DHCP is powered off at once.
    5. Wait for setup (`_await_setup`): read the status file through VMware Tools until it says done.
       The wait is `EXTRAS_TIMEOUT_SECONDS`, or `WINDOWS_SETUP_TIMEOUT_SECONDS` for Windows, plus each
       extra's `setupMinutes`.
    6. Clear `guestinfo.userdata` if it carried a plaintext password, re-read the address, plant any
       Pro Lab flags, and set `running`.

- **reset:** power off, revert to the clone's `clean` snapshot, power on, then wait for the
    address and setup again. Because the snapshot predates first boot, cloud-init runs again: a reset
    machine is as new.
- **redeploy:** delete the VM and deploy again with the same settings; machines that depend on it
    are told if its address changed.
- **start / stop / reboot:** stop tries a clean shutdown, falling back to power-off after 90 s.
    Address waits are capped at 120 s.
- **expire:** power off. **destroy:** delete the VM and the row.
- **extend, keep and expiry** are API-only database updates. They queue a `start` only if the
    machine had expired.

### Cancellation

`POST …/cancel` sets `jobs.cancelled_by`. Long waits call `vsphere.check_cancelled()`, which polls
that column at most every 2 s and raises `Cancelled`. A job cancelled while still queued marks its
machine `error`. A deploy, redeploy or reset cancelled while running also powers its VM off
(`_power_off_after_cancel`), so a half-set-up machine stops using memory. A template build's loop
checks the same column every 10 s and stops Packer with an interrupt, which deletes its VM.

### The sweep

`sweep` runs every minute (`cron="* * * * *"`, `queueing_lock="sweep"` so runs never stack), on
the quick queue:

1. `recover_lost_jobs`: fail jobs whose worker's heartbeat is older than 60 s (a worker that was
    killed mid-deploy), and panel jobs the queue no longer holds.
2. `advance_instances`: move Pro Lab instances on to their next boot-order tier.
3. `ensure_builds`: queue a template build for every template machines are waiting for, if none is
    queued or running.
4. `expiry_sweep`: expire machines whose time is up; destroy those past the grace period. A machine
    whose power-off at expiry failed (vCenter down) is tried again every 15 minutes, not every minute.
5. `reconcile`: one bulk vCenter read to sync power states and addresses.
6. Once an hour, `prune_history`: finished `jobs` older than 90 days, finished Procrastinate jobs
    older than 7 days, and each machine's activity beyond its latest 1000 lines.

## 7. Templates, families and first boot

A **template** is a vSphere template VM with a snapshot named exactly `clean`. Every machine is a
linked clone of that snapshot, so a deploy writes only its own changes (`CLONE_DISK_GB`, 10 GB by
default, for the capacity check). For the same reason, a template can't be deleted while machines
still use it.

Templates carry no per-machine settings. On first boot, the machine reads them from vCenter's
`guestinfo` variables, set by the clone's reconfigure. How that works depends on the template's
**family** (`templates.yaml`'s `family`):

| Family | Used for | First-boot data (`cloudinit.py`) | Ready when |
|---|---|---|---|
| `debian` | Ubuntu, Debian, Kali, Parrot | `guestinfo.metadata` (hostname, netplan DHCP) + `guestinfo.userdata` (`#cloud-config`: user, SHA-512 password hash, admin group, SSH key, extras' `write_files`/`runcmd`) | `/var/lib/lab-deploy/extras.status` says done |
| `rhel` | Rocky, Alma, CentOS Stream, Fedora | As debian, `wheel` group | As debian |
| `arch` | CachyOS | As debian, `wheel` group | As debian |
| `windows` | Windows Server, Windows 11, Exchange | A Cloudbase-Init `#ps1_sysnative` script: creates the user (a domain admin on a domain controller), disables the built-in Administrator, sets up OpenSSH, then runs the extras' runner | `C:\ProgramData\lab-deploy\extras.status` says done |
| `legacy` | Old Linux, OPNsense, pfSense, Proxmox, TrueNAS, XCP-ng | Plain `guestinfo.lab.*` keys, read by the template's own `lab-firstboot` script (`scripts/template/legacy/`, `opnsense/`, …) | The status file |
| `vyos` | VyOS | cloud-config `users` + `vyos_config_commands` | A guest login succeeds |
| `image` | Metasploitable, MikroTik CHR | None: deployed as is, with the fixed `password` from `templates.yaml` | An address |

The worker reads status files through VMware Tools guest operations (`read_guest_file`). That needs
the guest-operation privileges `setup_vcenter.py` grants, and the panel's server must reach the ESXi
host on port 443.

## 8. Extras framework

An **extra** is an optional service installed at deploy: a web server, a database, a domain
controller, a Docker app. Extras are defined in `backend/extras.yaml`, whose header documents every
key; `extras.py` loads them.

**No downloads at deploy.** An extra's packages are **baked into the template**, installed but
switched off, by `scripts/template/prepare.sh`: `EXTRA_PACKAGES_<FAMILY>[<id>]`, `EXTRA_SERVICES`,
and `bake_<id>()` for anything more. At deploy, only the extra's `script` runs.
`test_extras.py` checks that every Linux extra's packages and bake functions are in `prepare.sh`.

**Container images come on CDs.** A Docker extra names its image as `dockerImage:`. The image isn't in
the template: `scripts/isos/fetch-images.sh` puts it on the datastore as an ISO
(`lab-image-<id>-<tag>.iso`, named by `extras.image_iso`). At deploy, `actions.deploy` checks the ISOs
the machine needs are there (`extras.media`), and `VCenter.attach_media` adds a CD drive for each,
after the clone's "clean" snapshot, so the snapshot never refers to an ISO. On first boot,
`lab_docker` loads the images from the CDs (`lab_images` in `extras.py`'s LIB), and once the machine
is set up `VCenter.remove_media` takes the drives out. The machine records its ISOs (`media`), and a
reset attaches the same ones again.

**How a template offers an extra.** It lists the extra under `extras:` in `templates.yaml`. Extras
prepped in `prepare.sh` but not yet in that build go under `plannedExtras:`, and show as "Soon".

**Clashes come from ports alone.** Two extras that list the same port can't be ticked together. The
old `uses`/`provides`/`conflicts` keys are refused by the loader.

**Options** (`options:`) are typed: `hostname`, `text` (with `pattern`), `choice`, `boolean` (`yes`/
`no`) and `machine`. A `machine` option takes another machine's id; the script receives
`<opt>_ip`, `<opt>_name`, `<opt>_username`, `<opt>_password` and that machine's own option values.
This is how `join-domain` finds its domain controller. Every value reaches the script as a
validated, quoted shell or PowerShell variable; scripts never see raw input.

**Linux scripts** run as root with `bash -e` from cloud-init's `runcmd`, through a runner that
records each extra's result in the status file. Helpers from `extras.py`'s `LIB` are loaded:
`lab_ip`, `lab_cert`, `lab_php`, `lab_apache`, `lab_apache_site`, `lab_sql_string`, `lab_docker`,
`lab_wait_http` and `lab_open`.

**Both runners delete the extras' scripts** once the status file is written (on Linux, cloud-init's
copies of the first-boot data too: `user-data.txt`, `cloud-config.txt`, `obj.pkl`, and
`/run/cloud-init/combined-cloud-config.json`). The scripts can hold the machine's password or another
machine's (a domain controller's administrator), which in a Pro Lab would be a shortcut nobody meant.
A reset goes back to the snapshot from before first boot, so they're written again.

**Windows scripts** run as SYSTEM under a PowerShell runner (`extras.windows_setup()`). Exit codes
manage restarts:

- **3010** means restart, then go on to the next extra.
- **3011** means restart, then run this extra again.
- The runner tells Cloudbase-Init **1003** to get the restart, and allows at most 3 restarts.

**After setup**, `extras.details()` builds the links and notes shown on the machine's page, from
each extra's `links`/`notes` with `{ip}`, `{username}`, `{hostname}` and option placeholders.

## 9. Pro Labs internals

Pro Labs are defined in `backend/labs.yaml` (schema in its header) and loaded by `labs.py`. A lab is
a list of machines, each a catalogue template and version with a `role`, a `bootOrder` and extras,
plus the flags to plant.

**When a lab is "Soon".** `labs.unavailable_reason()` checks two things: every machine's template
must be deployable, and every extra a lab machine uses must be in that template's `extras:`.
Otherwise the lab is listed as "Soon" instead of failing to load.

**Machine references.** A `machine`-type option in a lab is written `"@<role name>"`, e.g.
`{join-domain: {dc: "@dc"}}`. It must point at another machine in the lab with a lower `bootOrder`.
At deploy, the API allocates every machine id first and swaps each `@dc` for the real `m-xxxx` id.

**Deploying an instance** (`POST /instances`):

1. Check the lab is available, the quotas, and the combined memory and disk.
2. Create every machine row with `pending="deploy"`.
3. `actions.generate_flags` stores a random `LAB{…}` value per flag.
4. `actions.advance_instance` queues the lowest boot-order tier. Once every machine in it is
    `running`, it queues the next tier; if one fails, the waiting machines fail too.

`advance_instance` runs after every lab job and from the sweep, under a row lock, so it is safe to
call from both.

**Flags** are planted by `actions.plant_flags` once a machine is set up, through VMware Tools guest
operations:

- `file:` writes the value to that path (Linux: as root, by a script in `/tmp` that only the user may
    read and that deletes itself as it starts).
- `run:` runs the program with the value as its last argument. Brookfield's mail flag is planted
    this way, by a script its seeding extra left on the mail server.

A flag counts as planted (`planted_at`) only once that's confirmed: the write went through, or the
program exited with 0 (`VCenter.wait_guest_program`, up to 2 minutes for a file and 20 for a `run`).
Otherwise its machine's log has a warning and the checklist shows it missing.

**Reset** reverts every machine to its own `clean` snapshot, in boot order, and plants new flag
values.

## 10. Console relay

The browser console is noVNC talking to ESXi's WebMKS, relayed through the API (`console.py`):

1. `POST /api/machines/{id}/console`. The API asks vCenter for a WebMKS ticket
    (`vm.AcquireTicket("webmks")`) and stores it in memory under a random token for 30 s, single
    use. It returns `/api/console/<token>`.
2. The browser opens that WebSocket (subprotocol `binary`). A cross-origin `Origin` is refused
    (close code 4403).
3. The API connects to `wss://<esxi>/ticket/<ticket>`. It pins ESXi's certificate to the thumbprint
    vCenter reported before sending the ticket, then relays bytes both ways.

**Gotchas:**

- **Single API process.** Tokens live in process memory, so the API must run as a single process.
- **No pings.** ESXi closes the console on a WebSocket ping, so upstream pings are off.
- **Shifted characters.** ESXi maps keysyms to keys without Shift. "Type password" and "Paste"
    therefore send Shift around capitals and shifted symbols, assuming a US layout.
- **Privilege.** It needs `VirtualMachine.Interact.ConsoleInteract`.

### Packet captures

`capture.py` runs captures on the capture appliance ([plan.md section 12](plan.md#12-packet-capture-and-the-network-diagram)):

1. **Scope.** `POST /captures` reads the chosen machines' MAC addresses from vCenter
    (`VCenter.machine_macs`) and builds `(ether host <mac> or …) and (<filter>)` (`scoped()`), then has
    the appliance check it (`validate`).
2. **The appliance.** `ssh` (OpenSSH, from the image) with the panel's key in `/capture/ssh/`, made by
    `public_key()` on first use, and `StrictHostKeyChecking=accept-new` under `HostKeyAlias=lab-capture`.
    The key may only run `scripts/capture/lab-capture`, which reads its request from stdin: `validate`
    and the filter, or `run`, seconds, snap length and the filter. `run` streams tcpdump's pcap until
    stdin closes or the seconds are up. Its address is `CAPTURE_HOST`, or `CAPTURE_VM`'s from VMware
    Tools (`appliance_address()`, cached a minute).
3. **Running.** `_run()` is an asyncio task in the API process: it feeds stdout to `pcap.Reader`, writes
    only whole packets to the file (so a capture cut off by a limit is still a valid file), keeps the last
    2000 lines and the conversations in a `Live`, and records the result in `captures` when it ends.
    The WebSocket reads the `Live`.
4. **Restarts.** The lifespan stops running captures on shutdown (`stop_all()`), marks leftovers
    `stopped` on start (`recover()`), and deletes old captures every 10 minutes (`clean_up()`).

**Gotchas:** like consoles, captures live in the single API process. Tests run `tests/fake_capture.py`
in place of `ssh` (the `appliance` fixture), and need `with TestClient(app)` so the event loop, and the
capture, outlives one request.

## 11. Frontend

`frontend/` is SvelteKit 2 with Svelte 5, built to static files by `adapter-static` (`ssr = false`;
`200.html` is the fallback, served by Caddy's `try_files`).

| Path | Purpose |
|---|---|
| `src/routes/machines/…` | Machine list (By OS / By service), deploy form (`new/[template]`), machine page (`[id]`), console (`[id]/console`) |
| `src/routes/labs/…`, `instances/…` | Pro Lab catalogue and lab pages; deployed instances |
| `src/routes/admin/` | Capacity, all machines, leftover VMs, jobs, templates, the capture appliance |
| `src/routes/network/` | The network diagram and packet captures (`NetworkDiagram`, `CaptureForm` and `CaptureView` in `src/lib/components/`; filters in `src/lib/captures.ts`) |
| `src/lib/api.ts` | `fetch` wrapper: sends `X-Lab-User`, turns error bodies into `ApiError` |
| `src/lib/store.svelte.ts` | `PanelStore`: polls `/api/state` every 3 s while the tab is visible (15 s hidden); every action the UI takes |
| `src/lib/types.ts` | Types shared with the API's JSON. Build backend work against these |
| `src/lib/templates.ts` | The catalogue's display side: names, categories, versions, end-of-life marks, access, flags |
| `src/lib/services.ts` | Services planned but not yet extras ("Soon" under By service) |
| `src/lib/labs.ts` | Pro Lab designs (cards, pictures, network sketches), matched to `labs.yaml` by slug |
| `src/lib/os-logos.ts` | Inline logos (Simple Icons) or lettered badges |
| `src/lib/styles/` | `tokens.css` (Hardline Classic theme), `palettes.css` (other themes), `app.css` (shared classes) |

**The catalogue lives in two places.** `templates.yaml` decides what can be deployed and where it
is in vCenter; `templates.ts` holds how it looks. `backend/tests/test_catalogue.py` parses
`templates.ts` and fails if a YAML template/version is missing from it. Templates in `templates.ts`
with no YAML entry show as "Soon".

**Theme.** The look copies the course site's Hardline Classic: dark by default, square corners, 2px
outlines, and a lime accent. Keep `tokens.css` in step with the course site. The theme menu sets
`data-theme` and `data-palette` on `<html>` and stores the choice in localStorage (`labs-theme`).

**Content Security Policy.** Caddy sends a strict CSP: `default-src 'self'`, with fonts and images
self-hosted. Nothing may load from a CDN. noVNC is bundled and imported dynamically, and fonts stay
separate files (`assetsInlineLimit: 0`).

## 12. Local development and tests

```sh
# Backend tests: PostgreSQL + vcsim (VMware's vCenter simulator), in Docker
docker compose -f backend/compose.test.yaml run --rm --build tests

# Frontend: dev server on :5173, /api proxied to localhost:8000
cd frontend && npm install && npm run dev

# Frontend type and Svelte checks (CI runs this)
cd frontend && npm run check

# Shell scripts: use the same shellcheck version as CI. Newer ones miss some warnings it raises.
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck-alpine:v0.10.0 shellcheck scripts/template/*.sh
```

**Test fixtures** (`backend/tests/conftest.py`):

- It points `VCENTER_*` at vcsim and builds a `Labs/Templates` inventory with `clean` snapshots.
- It resets the schema with Alembic and truncates the tables after each test.
- It fakes guest-file reads; mark a test `real_guest_files` to opt out.
- The `queued` fixture captures deferred jobs, and `run_queued()` runs them in the test.

**What vcsim can't tell you:**

- It **doesn't enforce privileges**, so a missing vCenter privilege only shows on a real vCenter.
- Read VM properties by path (the PropertyCollector).
- Apply clone configuration in a separate `ReconfigVM`.

**End-to-end tests** run against a real panel and vCenter:

```sh
scripts/e2e/run.py --panel https://panel.example --only ubuntu:26.04 --report e2e-report.md
```

It deploys `e2e-*` machines owned by `e2e`, runs the whole lifecycle (deploy, sign-in over SSH or
RDP, stop, start, reboot, reset, redeploy, destroy), then one deploy per extra with the checks in
`scripts/e2e/checks.py`. Exit 0 is the sign-off for a new template.

> **Warning:** Don't run heavy tests on the panel's own server. It also runs the panel, and CI
> deploys to it.

## 13. CI and deployment

`.gitlab-ci.yml` runs on every push. The **build** stage has five jobs:

- `build`: `npm run check` and `npm run build`.
- `scripts-check`: shellcheck v0.10.0.
- `scripts-check-windows`: parses the `.ps1` files with PowerShell's parser.
- `backend-test`: pytest with Postgres and vcsim services.
- `install-test`: the offline install's tests (`deploy/install/labinstall/test_*.py`), above all that
    every template the panel can deploy has an offline build in `manifest.toml`.

On the default branch, the **deploy** stage (which waits for all but `scripts-check-windows`) then runs `deploy/deploy.sh` with the frontend that
`build` already built. It needs the CI/CD variables `DEPLOY_HOST`, `SITE_ADDRESS`, `SSH_PRIVATE_KEY`
and `SSH_KNOWN_HOSTS`, plus `DEPLOY_USER` if it isn't the default.

**What `deploy/deploy.sh` does:**

1. Rsyncs the built site, the backend, `compose.yaml`, the env example and the Caddyfile to
    `/srv/lab-deploy`.
2. Writes `.env`. On the first deploy only, it creates `lab-deploy.env` with a generated database
    password.
3. Builds `api` and starts everything except the worker and the builder.
4. Restarts the worker, letting running jobs finish for up to 15 minutes.
5. Updates the builder (`deploy/update-builder.sh`) only between template builds: with one queued
    or running, a waiter in the background updates it once they've finished
    (`build-logs/update-builder.log`), so a deploy never cuts a build off.
6. Reloads Caddy.

Overlapping deploys can leave the API down, so batch your pushes.

**Offline installs** use `deploy/bundle.sh` (online side) and `deploy/install.sh` with the
`labinstall` package (offline side). These build the panel and every template from a carried-in
bundle; see [offline-install.md](offline-install.md). Its template list is
`deploy/install/manifest.toml`: each entry's `catalogue` must exist in `templates.yaml`, and every
deployable template needs an entry (`install-test` checks both). Besides the fields its header
describes, an entry's `extras_var` names the Packer variable its extras go to (Ubuntu Desktop's
`desktop_extras`), and the manifest's `[extras_mirrors]` names extras that need a mirror of their
own (Zabbix's).

`labinstall`'s modules: `config.py` (the config and its questions), `checks.py` (the checks, and each
template's verdict), `manifest.py`, `builds.py` (the builds and the media server), `images.py` (the
extras' image ISOs: which each needs, from `fetch-images.sh --list`, and uploading the bundle's; an extra
whose ISO is missing is still built in, and `catalogue.write` offers it only once the ISO is on the
datastore),
`capture.py` (the packet capture appliance's setup and build), `catalogue.py` (the panel's catalogue
from what was built, and the builder's offline setup: `offline-builds.json`, its copy of `packer/`,
`scripts/` and the media folder), `tests.py` (the end-to-end tests), `isos.py` (the bundle's installer ISOs, uploaded; checking and removing
them), `isolist.py` (every ISO the install can use and what needs it, for `bundle.sh --isos` and
`DOWNLOAD-LATER.md`), `report.py`, `out.py` and
`vcenter.py` and `envfile.py`. The manifest's `[choices_mirrors]` names per-template choices that need
a mirror (PHP's versions, from Ondřej Surý's PPA): a build without it leaves them out, and the
catalogue doesn't offer them.

## 14. Configuration reference

All settings come from the environment (`lab-deploy.env` on the server; an example is in
`deploy/lab-deploy.env.example`). `config.py` is the source of truth.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql://labdeploy:labdeploy@localhost/labdeploy` | Database |
| `VCENTER_HOST` | — | vCenter, `host[:port]` |
| `VCENTER_USER`, `VCENTER_PASSWORD` | — | The panel's vCenter account (`svc-labdeploy`) |
| `VCENTER_INSECURE` | `false` | Accept a self-signed vCenter certificate |
| `VCENTER_DATACENTER`, `VCENTER_CLUSTER` | — | Where machines run. Without these four, deploys fail with "vCenter isn't configured" |
| `VCENTER_RESOURCE_POOL` | cluster root | Optional resource pool |
| `VCENTER_DATASTORE` | — | Datastore for clones |
| `VCENTER_FOLDER` | `Labs/Machines` | VM folder for machines |
| `VCENTER_NETWORK` | — | Port group machines join (needs DHCP) |
| `MAX_MACHINES` | `10` | Machines at once (expired ones don't count) |
| `MAX_PERMANENT` | `3` | Of those, kept permanently |
| `MEMORY_OVERCOMMIT` | `1.0` | Memory the capacity check may hand out, as a multiple of physical memory (≥1) |
| `DATASTORE_RESERVE_GB` | `30` | Datastore space deploys never use |
| `CLONE_DISK_GB` | `10` | What a new linked clone is expected to write |
| `GRACE_MINUTES` | `1440` | How long expired machines are kept before deletion |
| `IP_TIMEOUT_SECONDS` | `300` | Wait for an address |
| `EXTRAS_TIMEOUT_SECONDS` | `600` | Wait for Linux setup and extras |
| `WINDOWS_SETUP_TIMEOUT_SECONDS` | `1200` | Wait for Windows setup |
| `MACHINE_DOMAIN` | — | Fills `{fqdn}` in extras' defaults, e.g. `lab.example` |
| `PASSWORD_LENGTH` | `16` | Generated passwords |
| `VCENTER_TEMPLATE_FOLDER` | `Labs/Templates` | Where templates are, and builds put them |
| `VCENTER_ISO_FOLDER` | `ISO` | The datastore folder builds read their ISOs from |
| `BUILD_DIR` | `/build` | The builder's copy of `packer/` and `scripts/` (deploy.sh copies them to `build-next/`; `deploy/update-builder.sh` moves them here between builds) |
| `BUILD_LOGS_DIR` | `/build-logs` | Each build's whole output |
| `BUILD_HTTP_IP` | — | The address build VMs fetch answer files from (Packer's web server) |
| `BUILD_MEDIA_DIR` | — | Offline: `fetch-media.sh`'s media folder, as the builder sees it |
| `BUILD_OFFLINE` | — | Offline: a JSON file the offline install writes (`catalogue.offline_builds`): for each template it built, `{"argv", "env", "media"}`. The builder runs that command instead of the recipe and its prepare scripts, and serves `BUILD_MEDIA_DIR` on `BUILD_MEDIA_PORT` while a `media` build runs |
| `BUILD_MEDIA_PORT` | `8690` | Where the builder serves the media folder during an offline build |
| `BUILD_TIMEOUT_MINUTES` | `180` | A longer build is stopped |
| `BLOCKED_TEMPLATES` | — | Template versions withdrawn for now, e.g. `ubuntu/26.04,debian/13`: not deployed or built, whatever `templates.yaml` says |
| `CAPTURE_VM`, `CAPTURE_HOST` | — | The capture appliance, by its VM in vCenter (address from VMware Tools) or its address. Both empty: captures are off |
| `CAPTURE_DIR` | `/capture` | The panel's SSH key for the appliance, the appliance's pinned host key, and the .pcap files |
| `CAPTURE_MAX_SECONDS`, `CAPTURE_MAX_MB` | `600`, `50` | The longest and largest a capture may be |
| `CAPTURE_PER_OWNER`, `CAPTURE_TOTAL` | `1`, `3` | Captures running at once, per person and in all |
| `CAPTURE_KEEP_DAYS` | `1` | How long finished captures are kept |
| `CATALOGUE_PATH` | `backend/templates.yaml` | The catalogue. `extras.yaml` and `labs.yaml` are read from the same folder |

## 15. Conventions and gotchas

**Conventions:**

- **Example data.** Committed files use documentation addresses and `.example` domains; real
    hostnames, IPs and keys stay out of the repository.
- **Commits.** Every change is committed as `Lab Deploy Admin` and pushed to `main`, which deploys
    it.
- **Repeatable steps.** These are scripts in `scripts/`, not commands pasted into a doc.

**Gotchas:**

- **New privileges need `setup_vcenter.py`.** When a feature needs a new vCenter privilege, add it to
    `scripts/setup_vcenter.py` and say so in the commit. `NoPermission` errors name the missing
    privilege.
- **DHCP churn.** Every clone is a new MAC, so test runs eat DHCP leases. Keep fixed addresses
    outside the pool; the panel powers off a machine that gets a host's or vCenter's address.
- **A paused ESXi.** If ESXi runs nested in VMware Workstation, it pauses when the PC's disk fills.
    When both ESXi and vCenter stop answering, check that first.
- **Deleting a template.** vCenter refuses to delete a template outright ("Invalid virtual machine
    state"). Convert it to a virtual machine first.
- **Stale comments to know about.** `models.py` says `family` is "debian, rhel or windows" (there are
    seven), and `labs.yaml`'s header still speaks of "golden templates". Brookfield uses the base
    templates plus seeding extras.
