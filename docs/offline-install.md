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
What's been added since (the extras' image ISOs; Windows Server 2016 and 2012 R2, TrueNAS SCALE 25.04
and CORE 13.0, Ubuntu Desktop, Alpine and FreeBSD; the packet capture appliance) was built through the
installer in the lab on 2026-11-16, one piece at a time; a whole new rehearsal hasn't been run since.

## What you need

**On the internet side**, a Linux machine with:
- Docker;
- about 25 GB free, or 45 GB with the imported images;
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
deploy/bundle.sh /path/to/lab-bundle --images --office /path/to/office \
    --isos windows-server-2025,windows-11,exchange,kali --iso-cache /path/to/isos
```

- `--images` adds the templates imported whole.
- `--office` adds the folder Office's download made, for the Outlook extra (see step 2).
- `--isos` adds installer ISOs, which the install uploads to the datastore. It takes ISO names
  (`scripts/isos/fetch.sh --list`), template ids (their ISOs), or `all`. Proxmox VE's ISOs are made
  here (`prepare-iso.sh`); VyOS's is built separately.
- `--iso-cache` takes ISOs from a folder that has them already (such as a copy of a lab's datastore
  `ISO` folder) instead of downloading them.

**Sizes:** without `--isos`, about 11 GB, or about 15.5 GB with `--images` and `--office`. All 46 ISOs
add about 89 GB.

#### Recommended for the first transfer

```sh
deploy/bundle.sh /path/to/lab-bundle --images --office /path/to/office
```

About **15.5 GB**, and no ISOs in it. It has everything that's made rather than downloaded (the media
folder and the extras' image ISOs, which only `bundle.sh` or its scripts can make, at this commit), so
the first trip needs nothing rebuilt later:

| Part | Size |
|---|---|
| `image-isos/`: the Docker extras, k3s and Winlogbeat | 7.6 GB |
| `media/windows/office/`: Office's files, for Outlook | 3.5 GB |
| `media/`: Cloudbase-Init (every Windows template), Exchange's prerequisites, the Linux extras' files, Wazuh, Zimbra, FreeBSD's and Alpine's packages, Packer | 2.7 GB |
| `media/images/`: Metasploitable 2 and MikroTik CHR 7 and 6 | 1.0 GB |
| `images/`: the panel's and the tools' Docker images | 0.5 GB |
| `debs/`: Docker for Ubuntu 22.04 and 24.04 | 0.3 GB |
| `repo/`, the install, `DOWNLOAD-LATER.md`, checksums | 6 MB |

The installer ISOs are left out because each is a single download with a published checksum, which
anyone can fetch on an online machine and bring alongside: `DOWNLOAD-LATER.md` gives each one's link,
checksum and the templates that need it. For the Pro Labs (Meridian, Brookfield), bring these four
(about 24 GB), and put them in the bundle's `isos/` folder (create it) so the install uploads them:

| ISO | Size | For |
|---|---|---|
| `windows-11-enterprise-eval-26300.9457.iso` | 7.7 GB | windows-11 |
| `ExchangeServerSE-x64.iso` | 6.0 GB | exchange |
| `windows-server-2025-eval-26100.1742.iso` | 5.6 GB | windows-server-2025 (and -core), exchange |
| `kali-linux-2026.2-installer-amd64.iso` | 4.5 GB | kali |

That's about 39 GB to carry in all. Add `sql-server-2025`'s ISO for the SQL Server extra, and the
Linux templates' ISOs for whichever you have mirrors for. Leave out `--office` if the bundle will be
shared: Microsoft doesn't allow passing Office's files on (nor Windows' and Exchange's ISOs, one
more reason they're downloaded rather than bundled).

**The smallest bundle:** `deploy/bundle.sh /path/to/lab-bundle --minimize`, about 0.75 GB. It leaves
out the media folder and the extras' image ISOs; the install sets up the panel and builds only the
templates that need neither (no Windows: they all need the media folder). `--isos` and `--office`
still add to it. Good for trying the install, not for a first transfer.

#### On GitHub

A GitHub release takes files under 2 GiB each (any number, up to 1000, and no limit on the total).
`--release <folder>` cuts the bundle into parts of at most 700 MB there, after making it:

```sh
deploy/bundle.sh /path/to/lab-bundle --images --office /path/to/office --release /path/to/lab-release
gh release create bundle-<commit> /path/to/lab-release/*
```

`deploy/release.sh <bundle> <folder> [--part-size 700MB]` does the same for a bundle made already. The
bundle goes in sections, each a tar cut into numbered parts (`lab-bundle-<commit>-<section>.tar.000`, …),
so a download can take only what it wants:

| Section | What | Parts at 700 MB (about) |
|---|---|---|
| `core` | The install, the project, Docker's images and packages (always needed) | 2 |
| `media` | The media folder, less the two below | 5 |
| `imported-images` | `media/images` (`--images`) | 2 |
| `office` | `media/windows/office` (`--office`) | 6 |
| `image-isos` | The extras' image ISOs | 12 |
| `isos` | Installer ISOs (`--isos`) | — |

With them come `SHA256SUMS-parts` and `JOIN.md`, which says how to put it back: check the parts, then
`cat` each section's parts into `tar -x`. That gives the same bundle, file for file, which `install.sh`
checks as always. It needs room for the parts and the bundle at once; the parts can go after. Office's
files and Microsoft's ISOs aren't for sharing: keep a release with them private.

**`DOWNLOAD-LATER.md`:** everything the install can use that isn't in the bundle, each with its link,
checksum, what needs it and where it goes:
- every ISO not chosen with `--isos`;
- the imported images not fetched: Parrot's OVA always (a manual download), Metasploitable 3
  (Linux)'s box unless `--with-deferred`, and all of them without `--images`.

Download them on an online machine whenever you want them, and bring them across. The install
leaves out a template whose files aren't there yet, and running it again picks them up.

It gathers:

| Folder | What |
|---|---|
| `install.sh`, `lab-install.toml.example` | The install, and its config to fill in |
| `repo/` | The project, with the panel's website built, and each ISO's size and checksum |
| `images/` | Docker images: the panel's, and the tools image the builds run in (Packer, govc, …) |
| `debs/` | Docker itself, for Ubuntu 22.04 and 24.04 servers without it |
| `media/` | What the builds would download (below) |
| `image-isos/` | The Docker extras' images, and k3s's and Winlogbeat's files, an ISO each (about 7.6 GB). The install uploads them to the ISO folder, and the panel attaches them to machines at deploy. `--no-image-isos` leaves them all out, and those extras with them (they're offered once their ISOs are there, with no rebuild) |
| `isos/` | With `--isos`: the installer ISOs chosen. The install uploads them to the ISO folder |
| `DOWNLOAD-LATER.md` | What isn't in the bundle, and where to get it |
| `SHA256SUMS` | Every file's checksum |

**What `media/` holds:**
- WordPress, Nextcloud and Chinook (the databases' sample data);
- Python 2.7 to 3.15, iRedMail with what its installer fetches, Wazuh's server bundle (about 1 GB)
  and agent, Zimbra 8.8.15's tarball, and MinIO and `mc` (built from source: about 12 minutes and
  3 GB free);
- Cloudbase-Init and Exchange's prerequisites;
- VMware Tools for OPNsense and pfSense;
- for FreeBSD 15.1, its release's base and kernel sets and the packages it installs;
- for Alpine 3.24 and the packet capture appliance, the packages they install, as a signed repository;
- Packer;
- with `--images`, the images imported whole: MikroTik CHR and Metasploitable 2 (and Metasploitable 3
  (Linux) with `--with-deferred`).

### 2. What the bundle doesn't hold

1. **The ISOs not chosen with `--isos`.** Each is in `DOWNLOAD-LATER.md`. Bring any you want
   alongside, or later. `scripts/isos/fetch.sh <name> --no-upload` downloads one and checks it, into
   `/var/tmp/lab-isos` or `STAGING=<folder>`.
2. **Office's files,** for the Outlook extra, unless you used `--office`: on a Windows PC, as
   `media/windows/office/README.txt` says, into `media/windows/office/`. Without them, Windows
   templates come without Outlook.
3. **The imported images in `DOWNLOAD-LATER.md`** (Parrot's OVA at least): into `media/images/`.

Copy the bundle, and anything you brought alongside, across.

## On the offline network

### 3. The ISOs into the datastore

The install uploads the bundle's `isos/` folder itself. For the others, either put them in the
bundle's `isos/` folder too, or upload them in the vSphere Client: Storage → the datastore → Files →
`ISO` (create it) → Upload Files. Keep the files' names: the install finds them by name.

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
- **`[capture] build`:** whether to build the packet capture appliance (`true` by default). It's built
  when `[templates] build` is `["all"]` or includes `"capture"`; `--only capture` builds it alone.

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
- **The ISOs:** each one is there at the right size, on the datastore or in the bundle's `isos/` to upload.
- **The extras' image ISOs:** each is in the ISO folder already, or in the bundle to upload. An extra
  whose ISO is in neither is left out of the templates.
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
   they trust `/srv/lab-deploy/lab-root.crt`, Caddy's own root certificate. Then it **uploads the
   extras' image ISOs** the ISO folder doesn't have yet; one there already is kept.
5. **Builds the templates** one at a time, each logged in `/srv/lab-deploy/install/logs/`. A failed
   build doesn't stop the rest.
6. **Writes the panel's catalogue** from what was built (`/srv/lab-deploy/templates.yaml`). Templates
   not built show as "coming soon". It also **sets the panel's builder up to build here**: its copy
   of `packer/` and `scripts/`, the media folder (less the imported images) in `/srv/lab-deploy/media`,
   and each template's build command for this network (`offline-builds.json`, `BUILD_OFFLINE`). So
   a template deleted from the Admin page builds again from the mirrors and media, on its next deploy
   or with **Build**, as the install built it.
7. **Builds the packet capture appliance**, as the [admin guide](admin-guide.md#13-packet-capture) has
   people do by hand: the capture port group and `Labs/Capture` (`scripts/setup_capture.py`), the
   appliance with the panel's key, `CAPTURE_VM` in `lab-deploy.env`, and the appliance powered on. A
   distributed switch needs its capture port group made by hand first, as that guide says.
8. **Tests the new templates** through the panel.
9. **Asks about the ISOs:**
   - keep them all;
   - remove them all;
   - keep only Windows' (the ones rebuilt when evaluations expire);
   - choose.

   It only removes the ISOs of templates that built and passed.
10. **Writes the report:** `/srv/lab-deploy/install/install-report.md`.

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
| `fedora` | dl.fedoraproject.org/pub/fedora/linux (`releases/44` and `updates/44`) | Fedora Server and Workstation 44 | `releases/44/Everything/x86_64/os/repodata/repomd.xml` |
| `centos_vault` | vault.centos.org | CentOS 6–8, XCP-ng (its VMware Tools) | `<release>/…/repodata/repomd.xml` |
| `epel_archive` | archives.fedoraproject.org/pub/archive/epel | CentOS 6 | `6/x86_64/repodata/repomd.xml` |
| `proxmox` | download.proxmox.com/debian | Proxmox VE 7–9 | `pve/dists/<codename>/Release` |
| `zabbix` | repo.zabbix.com (`zabbix/7.0`, and its key `zabbix-official-repo-apr2024.gpg`) | Ubuntu, Debian, Kali, Parrot (the Zabbix extras; optional: without it, they're left out) | — |
| `php` | ppa.launchpadcontent.net/ondrej/php (`ubuntu/dists/jammy`, `noble`) | Ubuntu 22.04, 24.04 (the Apache extras' PHP versions; optional: without it, only Ubuntu's own PHP) | — |
| `zimbra` | repo.zimbra.com (`apt/87` and `apt/8815`, focal) | Zimbra 8.8.15 | `apt/8815/dists/focal/Release` |

These need no mirror:
- **Windows, TrueNAS and VyOS:** their ISOs hold everything (Windows Server 2016 and 2012 R2 add
  what they lack from the media folder).
- **OPNsense, pfSense and FreeBSD:** their packages (and FreeBSD's release sets) come from the media
  folder.
- **Alpine and the packet capture appliance:** their packages come from the media folder, on the
  build's CD.
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
