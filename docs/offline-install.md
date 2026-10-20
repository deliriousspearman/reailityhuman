# Offline install: design

One script installs the whole lab, the panel and its templates, on a network with no internet. This
is the design, agreed on 2026-10-20; the runbook will replace it.

**Status (2026-10-20):** built (`deploy/bundle.sh`, `deploy/install.sh`, `deploy/install/`) and
rehearsed once: a bundle without media, installed on a fresh Ubuntu 24.04 VM with no internet and no
Docker. Docker from the bundle, the panel, the checks against vCenter, a TrueNAS CORE build, the
catalogue, its lifecycle test through the new panel and the report all worked; a re-run resumed.
Still to do: a rehearsal with the media folder and LAN mirrors (a Linux build with extras, and
Windows); the builds marked "needs internet" in `manifest.toml` (OPNsense, pfSense, CentOS 6 to 8,
Proxmox, XCP-ng, Parrot) made to take mirrors; the runbook.

## The two halves

A network without internet can't download anything, so the work splits in two:

1. **Online, once per release: `deploy/bundle.sh <folder>`.** It runs on any Linux machine with
   internet and Docker, and gathers everything the install needs into one folder, which is then
   carried across (a disk, or a transfer to the offline network).
2. **Offline: `<bundle>/install.sh`.** It runs on the panel's server (Ubuntu 22.04 or 24.04). It
   installs the panel, checks everything the template builds need, builds the templates, tests them
   and reports.

The admin edits one config file, `lab-install.toml`, before running the install. Anything the file
leaves out, the install asks for; with `--yes` it asks nothing and stops on whatever is missing.

## What the bundle holds

| Folder | What | Made by |
|---|---|---|
| `install.sh`, `lab-install.toml.example` | The installer, and the config to copy | the repo |
| `repo/` | The project at the bundled commit, with the panel's website already built | `git archive`, `npm run build` |
| `images/` | Docker images, saved: the panel (`lab-deploy-backend`, `caddy`, `postgres`) and the tools image (below) | `docker save` |
| `debs/` | Docker Engine and the Compose plugin for Ubuntu 22.04 and 24.04, for a server without Docker | Docker's apt repository |
| `media/` | What the builds download otherwise: `fetch-media.sh`'s folder, plus the Exchange prerequisites and the images imported whole (Metasploitable, MikroTik CHR, Parrot's OVA) | `fetch-media.sh` |
| `SHA256SUMS` | Every file's checksum | `bundle.sh` |

Not in it: the **ISOs** (already on the datastore, see below), **Office's files** (made on a Windows
PC; they go in `media/windows/office`), and **package mirrors** (the offline network's own).

**The tools image** (`lab-deploy-tools`) holds everything the builds run with, so the server needs
nothing but Docker: Packer and its vSphere plugin, govc, xorriso (Packer's CDs), qemu-img (disk
conversion), OpenSSH, and Python with pyVmomi for the checks. The template stages run inside it, on
the host's network (the builds' VMs fetch answer files from Packer's web server, and media from the
installer's).

## The config file

```toml
[panel]
address = "labs.lab.example"        # what browsers use

[vcenter]
host = "vcenter.lab.example"
insecure = true                      # its own self-signed certificate
admin_credentials = "/root/vcenter-admin"   # user, then password: builds and setup
panel_credentials = "/root/vcenter-svc"     # svc-labdeploy's
datacenter = "Datacenter"
cluster = "Cluster"
datastore = "datastore1"
network = "VM Network"
iso_folder = "ISO"

[mirrors]                           # leave out any you don't have: their templates are skipped
ubuntu = "http://mirror.lab.example/ubuntu"
debian = "http://mirror.lab.example/debian"
debian_archive = "http://mirror.lab.example/debian-archive"   # Debian 8 to 10
kali = "http://mirror.lab.example/kali"
parrot = "http://mirror.lab.example/parrot"
rocky = "http://mirror.lab.example/rocky"
alma = "http://mirror.lab.example/almalinux"
centos_stream = "http://mirror.lab.example/centos-stream"
centos_vault = "http://mirror.lab.example/centos-vault"       # CentOS 6 to 8, XCP-ng's Tools
epel_archive = "http://mirror.lab.example/epel-archive"       # CentOS 6
proxmox = "http://mirror.lab.example/proxmox"                 # Proxmox VE 7

[templates]
build = ["all"]                      # or a list: ["ubuntu-26.04", "windows-server-2025", …]
on_missing = "ask"                   # ask | skip | cancel
rebuild = false                      # true: rebuild templates that already exist
test = "lifecycle"                   # none | lifecycle | full
remove_isos = "ask"                  # ask | none | all | keep-windows
```

Passwords are never in the config: it names files that hold them.

## The install, step by step

1. **The bundle:** checks `SHA256SUMS`.
2. **Docker:** installs it from `debs/` if the server has none; loads the images.
3. **The config:** reads it, and asks for what's missing.
4. **Checks, all before anything changes** (each one ok, a warning, or a failure):
   - **vCenter:** answers; both accounts sign in; the admin account has the rights the builds need;
     the datacenter, cluster, datastore, port group and `Labs/` folders exist (if not, it offers to
     run `setup_vcenter.py`).
   - **The ESXi host:** VMware Tools' `windows.iso` is there (Windows builds); nested virtualisation
     is allowed (Proxmox, XCP-ng); the clock is right (evaluation licences, certificates).
   - **ISOs:** each template's ISOs are in the datastore's ISO folder, at the size `isos.txt` gives.
     `--verify-isos` also reads each back and checks its SHA-256 (slow).
   - **Mirrors:** each answers, and has the release its templates need (e.g. Ubuntu's
     `dists/noble/Release`, the CentOS vault's `8.5.2111/BaseOS`).
   - **Media:** the bundle's media folder has what each template and extra needs. Office's files
     and SQL Server's ISO are optional: without them, their extras are left out, not their
     templates.
   - **Room:** the disk every chosen template needs, against the datastore's free space; one
     build VM's memory against the cluster's.
   - **This server's ports:** the builds' web servers (Packer's, and the installer's for media)
     listen here; a firewall must let the VM network in. Tested from here; the first build proves it
     from a VM.

   Mirrors and media are tested from the server, not the VM network. If the two differ, a build
   that can't reach one fails at its first download, and the report says which.
5. **The summary:** one table, each template ready or why not (missing ISO, missing mirror,
   depends on a skipped template, already built), with extras left out. Then **continue without
   the ones that aren't ready, or cancel** (`on_missing`).
6. **The panel:** writes `/srv/lab-deploy/lab-deploy.env` (vCenter settings, generated database
   password), starts it from the loaded images, and prints the address and Caddy's root
   certificate. Done before the builds, so the admin can look at it while they run.
7. **The builds,** one at a time, in dependency order (Windows Server 2025 before Exchange; Parrot's
   base before Parrot). Each one's log is kept. A failed build doesn't stop the rest. A template
   already in `Labs/Templates` is kept unless `rebuild` is on. A re-run picks up where the last one
   stopped.
8. **The catalogue:** writes `/srv/lab-deploy/templates.yaml` from what was built: each built
   template's vCenter name, the extras it was built with; templates not built show as "coming soon".
   The panel reads it from there (`CATALOGUE_PATH`) and restarts.
9. **Tests:** `scripts/e2e/run.py` on each new template: the lifecycle (`test = "lifecycle"`, the
   default) or every extra too (`full`, hours).
10. **ISOs:** asks whether to keep them (`remove_isos`): all, none, only Windows' (the ones rebuilt
    when evaluations expire), or a choice from a list with sizes. Only ISOs whose templates built and
    passed can go; the intermediate ISOs (Proxmox's `-auto`, VyOS's) always can.
11. **The report:** `/srv/lab-deploy/install-report.md`: what was built, skipped and failed (with each
    failure's log tail), the tests' results, ISOs removed (to carry in again before a rebuild), and
    each evaluation licence's expiry date.

Options: `--config FILE`, `--yes`, `--only <templates>`, `--rebuild`, `--skip-panel`,
`--skip-templates`, `--verify-isos`, `--check` (steps 1 to 5 only, changing nothing). `install.sh
clean-isos` is step 10 on its own, for later.

## What the builds need offline (audit, 2026-10-20)

Most builds already take a mirror or media variable; these don't yet, and get one:

- **Proxmox VE 7:** Proxmox's repository (`download.proxmox.com`) and its key.
- **Proxmox VE 8 and 9:** the first-boot script's packages (VMware Tools) from Debian's mirror.
- **XCP-ng:** VMware Tools from the CentOS 7 vault.
- **CentOS 6:** EPEL's key from `dl.fedoraproject.org`.
- **Exchange:** Visual C++ 2012 and 2013 and URL Rewrite, from Microsoft (into `media/windows`).
- **The imports** (Metasploitable 2 and 3, MikroTik CHR, Parrot): their downloads into `media/`,
  where most already look (`MEDIA=`).
- **VyOS:** its ISO is built online (`build-iso.sh`); the bundle carries the built ISO.

## Testing it

- `bundle.sh` here, then `install.sh` on a new Ubuntu VM whose firewall drops everything but the
  LAN, with this lab's vCenter and LAN mirrors served from the build machine (`apt-mirror`-style
  partial mirrors for one Ubuntu and one Rocky template are enough to prove the path).
- `--check` with an ISO removed, a mirror stopped and Office's files missing: the summary says so,
  and `skip` builds the rest.
- A re-run after a build is interrupted picks up where it stopped.
