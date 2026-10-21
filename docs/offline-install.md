# Offline install

How to install the lab, the panel and its templates, on a network with no internet. It takes two
sessions: one on a machine with internet, to gather everything into a **bundle**, and one on the
offline network, where **`install.sh`** does the rest:
1. it checks everything;
2. it shows what it can build;
3. it installs the panel;
4. it builds, tests and lists the templates;
5. it writes a report.

Rehearsed on 2026-10-21: a fresh Ubuntu 24.04 server with no internet and no Docker installed the
panel, built Ubuntu 26.04 with every extra (through a mirror, from the media folder), and its tests and
the extras' tests passed. Every template's build was also checked against mirrors and the media folder.

## What you need

**On the internet side**, a Linux machine with:
- Docker;
- about 15 GB free, or 35 GB with the imported images;
- Node.js, or else bundle.sh uses Node's Docker image;
- for Office's files, a Windows PC.

**On the offline network:**
- **vCenter**, with a datacenter, a cluster (or a standalone host), a datastore and a port group whose
  network has a DHCP server, with plenty of addresses (at least twice the machines you'll run).
- **Two vCenter accounts**, created under Administration → Single Sign On → Users and Groups:
  - an administrator, for setting up and building;
  - the panel's own account, e.g. `svc-labdeploy@vsphere.local`.

  The install gives the panel's account its rights itself (`scripts/setup_vcenter.py`).
- **For Proxmox VE and XCP-ng,** ESXi with hardware virtualisation exposed to VMs: they run nested.
- **The panel's server:**
  - Ubuntu 22.04 or 24.04;
  - 4 vCPU, 8 GB of memory and 200 GB of disk;
  - an address on the network vCenter and the machines are on.
- **Package mirrors on the LAN**, for the Linux templates: see [Mirrors](#mirrors). Leave a template
  out if there's no mirror for it.

## On the internet side

### 1. The bundle

From the repository, at the commit to install:

```sh
deploy/bundle.sh /path/to/lab-bundle            # add --images for the templates imported whole
```

It gathers:

| Folder | What |
|---|---|
| `install.sh`, `lab-install.toml.example` | The install, and its config to fill in |
| `repo/` | The project, with the panel's website built, and each ISO's size and checksum |
| `images/` | Docker images: the panel's, and the tools image the builds run in (Packer, govc, …) |
| `debs/` | Docker itself, for Ubuntu 22.04 and 24.04 servers without it |
| `media/` | What the builds would download (below) |
| `SHA256SUMS` | Every file's checksum |

**What `media/` holds:**
- WordPress, Nextcloud and Chinook (the databases' sample data);
- the container apps' images: Juice Shop, DVWA, Uptime Kuma, Grafana, Vaultwarden and Gitea;
- Cloudbase-Init and Exchange's prerequisites;
- VMware Tools for OPNsense and pfSense;
- Packer;
- with `--images`, the images imported whole: MikroTik CHR, and Metasploitable 2 and 3 (Linux and
  Windows).

### 2. What the bundle doesn't hold

1. **The ISOs.** Run `scripts/isos/fetch.sh <name> --no-upload` for each template you'll build (`--list`
   names them); they land in `/var/tmp/lab-isos`, or `STAGING=<folder>`. Two templates need ISOs made
   from these:
   - **Proxmox VE 8 and 9:** `packer/proxmox/prepare-iso.sh --no-upload proxmox-ve-9.2` (and `proxmox-ve-8.4`)
     makes `proxmox-ve_9.2-1-auto.iso`.
   - **VyOS:** `packer/vyos/build-iso.sh` builds VyOS's ISO.
2. **Office's files,** for the Outlook extra: on a Windows PC, as `media/windows/office/README.txt` says,
   into `media/windows/office/`. Without them, Windows templates come without Outlook.
3. **Parrot's OVA**, from https://deb.parrot.sh/parrot/iso/, into `media/images/`. Check it against its
   signed hashes.

Copy the bundle and the ISOs across.

## On the offline network

### 3. The ISOs into the datastore

In the vSphere Client: Storage → the datastore → Files → `ISO` (create it) → Upload Files. Keep the
files' names: the install finds them by name.

### 4. The panel's server

Copy the bundle onto it. Then, as root:

```sh
install -d -m 700 /srv/lab-deploy/secrets
printf '%s\n%s\n' 'administrator@vsphere.local' 'its password' >/srv/lab-deploy/secrets/vcenter-admin
printf '%s\n%s\n' 'svc-labdeploy@vsphere.local' 'its password' >/srv/lab-deploy/secrets/vcenter-panel
chmod 600 /srv/lab-deploy/secrets/*
cp lab-bundle/lab-install.toml.example /srv/lab-deploy/lab-install.toml
```

Edit `/srv/lab-deploy/lab-install.toml`. Its comments explain each setting:

- **`[panel] address`:** what browsers will use, e.g. `labs.lab.example`.
- **`[vcenter]`:** its address, and the inventory names.
- **`[mirrors]`:** your mirrors. Leave out those you don't have.
- **`[templates]`:**
  - `build`: which templates. `["all"]`, or ids from `deploy/install/manifest.toml`, e.g.
    `["ubuntu-26.04", "windows-server-2025"]`.
  - `on_missing`: what to do when one isn't ready (ask, skip or cancel).
  - `test`: whether to test them, with `none`, `lifecycle` or `full`. `full` is hours.
  - `remove_isos`: whether to remove the ISOs afterwards.

Anything left out is asked for when it runs, and saved.

**Firewall:** the template builds' VMs fetch files from this server while they install, so the VM network
must reach it on TCP 8000–9000 (Packer's web servers) and 8690 (the media folder).

### 5. Check first

```sh
sudo lab-bundle/install.sh --check
```

It changes nothing. It checks the bundle and then lists each check as ok, warning or failed:
- **vCenter:** both accounts sign in; the panel's account has its rights; the inventory is there.
- **The hosts:** their clocks.
- **The media folder.**
- **Each mirror:** that it has each release.
- **The ISOs:** each one is there at the right size.
- **Room:** on the datastore, and memory.

Then it shows each template as one of:
- **ready**, with any extras left out and why;
- **built already**;
- **not ready**, and why: an ISO missing, no mirror, no media, or a template it needs isn't ready.

Fix what you want, and run it again.

### 6. Install

```sh
sudo lab-bundle/install.sh
```

**What it does:**
1. Installs Docker from the bundle if the server has none.
2. Checks again, shows the summary, and asks whether to build without what isn't ready.
3. Sets up vCenter if needed: the `Labs` folders, and the panel account's rights.
4. **Installs the panel** and starts it. The panel is at `https://<address>`. Browsers trust it once
   they trust `/srv/lab-deploy/lab-root.crt`, Caddy's own root certificate.
5. **Builds the templates** one at a time, each logged in `/srv/lab-deploy/install/logs/`. A failed
   build doesn't stop the rest.
6. **Writes the panel's catalogue** from what was built (`/srv/lab-deploy/templates.yaml`). Templates
   not built show as "coming soon".
7. **Tests the new templates** through the panel.
8. **Asks about the ISOs:**
   - keep them all;
   - remove them all;
   - keep only Windows' (the ones rebuilt when evaluations expire);
   - choose.

   It only removes the ISOs of templates that built and passed.
9. **Writes the report:** `/srv/lab-deploy/install/install-report.md`.

Builds take 5 minutes (MikroTik) to over an hour (Debian 8 from a slow archive); a whole catalogue is a
day.

**`install.sh` options:**

| Option | What it does |
|---|---|
| `--yes` | Asks nothing, and takes the config's answers |
| `--only ubuntu-26.04,kali` | Builds only these templates |
| `--rebuild` | Builds again templates that exist already |
| `--skip-panel`, `--skip-templates` | Leaves out that half |
| `--verify-isos` | Also checks each ISO's SHA-256 (reads each back: slow) |
| `--verbose` | Shows the builds' whole output, not just their steps |
| `clean-isos` | The ISO question on its own, later |

**Running it again** is safe. It carries on where it stopped (`/srv/lab-deploy/install/state.json`),
keeps what's built, and only brings the panel up to date.

### 7. Afterwards

- **The report lists each evaluation licence's expiry:** Windows Server's are 180 days and Windows 11's
  90. Rebuild those templates before then (`--only windows-server-2025 --rebuild`), with their ISOs, or
  license them. Machines from an expired template stop working too.
- **Updates:** a new bundle from a newer commit, then `install.sh` again. `--rebuild` rebuilds templates
  with newer packages.

## Mirrors

What each mirror must hold, by template. The install checks each one for the file named:

| Config | Mirror of | Templates | Checked for |
|---|---|---|---|
| `ubuntu` | archive.ubuntu.com/ubuntu | Ubuntu 16.04–26.04 | `dists/<codename>/Release` |
| `debian` | deb.debian.org/debian | Debian 11–13, Proxmox VE 7–9 | `dists/<codename>/Release` |
| `debian_security` | security.debian.org/debian-security | Proxmox VE 8, 9 (optional: without it, their security source is off) | — |
| `debian_archive` | archive.debian.org/debian | Debian 8–10 | `dists/<codename>/Release` |
| `kali` | http.kali.org/kali | Kali | `dists/kali-rolling/Release` |
| `parrot` | deb.parrot.sh/parrot | Parrot | `dists/echo/Release` |
| `rocky`, `alma` | dl.rockylinux.org/pub/rocky, repo.almalinux.org/almalinux | Rocky, AlmaLinux 8–10 | `<version>/BaseOS/x86_64/os/repodata/repomd.xml` |
| `centos_stream` | mirror.stream.centos.org | CentOS Stream 9 | `9-stream/BaseOS/…` |
| `centos_vault` | vault.centos.org | CentOS 6–8, XCP-ng (its VMware Tools) | `<release>/…/repodata/repomd.xml` |
| `epel_archive` | archives.fedoraproject.org/pub/archive/epel | CentOS 6 | `6/x86_64/repodata/repomd.xml` |
| `proxmox` | download.proxmox.com/debian | Proxmox VE 7–9 | `pve/dists/<codename>/Release` |

These need no mirror:
- **Windows, TrueNAS and VyOS:** their ISOs hold everything.
- **OPNsense and pfSense:** their VMware Tools come from the media folder.
- **MikroTik and Metasploitable:** imported from the media folder.

**One extra needs the internet** and is always left out offline: `nextcloud-snap`, from the Snap Store.

## When something fails

- **A template is "not ready":** the summary says why. Usually an ISO isn't in the ISO folder under
  its name, or a mirror isn't set or lacks the release.
- **A build fails:**
  - Its log is in `/srv/lab-deploy/install/logs/<template>.log`, and the report has its last lines.
  - [build-templates.md](build-templates.md), "When a build fails", covers the usual causes.
  - **"Waiting for IP" until a timeout:** usually the VM couldn't reach this server (the firewall
    above), or the ISO it booted wasn't there.
  - **Windows stuck at shutdown:** sysprep didn't run. `C:\Windows\Temp\lab-finish\clean.log` on the VM
    says why (build it alone with `--only` after fixing, or by hand with Packer's `-on-error=abort` to
    keep the VM).
- **A test fails:** `/srv/lab-deploy/install/logs/e2e-report.md` says which step. The template is in
  the catalogue anyway: fix it, then `--only <id> --rebuild`.

## How it's made

For maintainers:

- **`deploy/install.sh`** gets the server ready: the bundle's checksums, Docker, the images, and the
  project into `/srv/lab-deploy/src`. Then it runs the rest in the tools image (`deploy/install/Dockerfile`),
  on the host's network, with Docker's socket.
- **`deploy/install/labinstall/`** is the rest:
  - `config.py` reads the config and asks for what's missing;
  - `checks.py` runs the checks and the summary;
  - `builds.py` runs the builds and serves the media folder;
  - `catalogue.py` writes `templates.yaml` and `compose.override.yaml`;
  - `tests.py` runs `scripts/e2e/run.py`;
  - `isos.py` checks and removes ISOs;
  - `report.py` writes the report.
- **`deploy/install/manifest.toml`** says, for each template:
  - its build command, and the Packer variables for the mirrors and media;
  - its ISOs, its mirrors, its media;
  - its extras;
  - what it needs built first;
  - its evaluation's length.

  A new template needs an entry there, as well as in `backend/templates.yaml`.
