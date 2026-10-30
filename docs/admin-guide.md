# Admin guide

How to run the lab panel: watch it, tune it, add machines and Pro Labs to it, keep it backed up, and
fix it when something goes wrong. For how it works inside, see the [Developer guide](developer-guide.md).

> **Note:** Addresses here use documentation ranges (192.0.2.0/24) and `.example` names. Put in your
> own. Paths are from the repository's root unless they start with `/srv`.

## 1. Overview

**What learners do.** They open the panel and pick a machine under **Machines** (By OS or By service)
or a lab under **Pro Labs**. They choose extras, a name, their own name and how long to keep it, and
deploy. The machine's page then shows its address, sign-in, SSH and Remote Desktop details, and a
browser console. Machines expire unless they're given more time.

**What admins look after:**

| Area | Where |
|---|---|
| Capacity, all machines, stray VMs, the job queue | The panel's **Admin** page |
| Limits, timeouts, vCenter connection | `/srv/lab-deploy/lab-deploy.env` on the server |
| Which machines can be deployed | `backend/templates.yaml` + `frontend/src/lib/templates.ts`, and the templates in vCenter |
| Optional services on machines | `backend/extras.yaml` (and the templates that bake them in) |
| Pro Labs | `backend/labs.yaml` (+ `frontend/src/lib/labs.ts` for the card) |
| vCenter permissions | `scripts/setup_vcenter.py` |
| Packet captures | The capture appliance and `CAPTURE_*` ([section 13](#13-packet-capture)) |
| Database backups | `/srv/lab-deploy/backups` |

**Changes go live by push.** Every change to the repository is committed and pushed to `main`, and
the pipeline deploys it to the panel's server. Catalogue and lab changes need no server login: edit
the YAML, run the tests, commit and push.

> **Warning:** There is no sign-in. Anyone who can reach the panel can deploy and destroy machines,
> read their passwords, and use the Admin page. Keep the panel on a trusted network.

**On the server**, everything is under `/srv/lab-deploy`:

| Path | What |
|---|---|
| `compose.yaml` | The services: `caddy`, `postgres`, `api`, `worker`, `sweeper`, `backup` |
| `lab-deploy.env` | Settings (mode 600). Created by the first deploy, never overwritten |
| `backend/`, `site/` | What the pipeline deployed |
| `backups/` | Daily database dumps |

The API's named volume `capture` holds the panel's SSH key for the capture appliance and the
captures' .pcap files.

## 2. The Admin page

`/admin` has six sections: Capacity, Machines, Leftover VMs, Jobs, Templates and Packet capture.

### Capacity

Three meters, read from vCenter every 30 s:

- **Memory.** Configured memory against physical memory × `MEMORY_OVERCOMMIT`, with "room for N
    more machines" of a typical size.
- **CPU.** For information; deploys aren't blocked on CPU.
- **Storage.** Datastore free space, less `DATASTORE_RESERVE_GB`.

A deploy is refused, with a reason, when it doesn't fit in memory or disk. Deploys already in flight
count too.

### Machines

Every machine, whoever owns it, and how many are kept permanently, against `MAX_PERMANENT`.

### Templates

Every template the panel can deploy, with:

- **its state:** Built, Not built (deleted to save space), Build queued, Building, or Build failed
  (hover to see why);
- **its size on the datastore,** and how many machines use it;
- **when it was last deployed,** and roughly how long a rebuild takes.

The heading says how much space deleting every deletable template would free.

**Delete** removes a template from vCenter and keeps its ISO. It's offered only when:

- the template has a build recipe (`build:` in `templates.yaml`);
- no machine uses it;
- no VM in vCenter is a linked clone of it;
- every ISO it's built from is in the datastore's ISO folder.

Otherwise the row says why it can't be deleted: **In use**, **Can't delete** (hover for the reason),
or **Kept** for imported templates, which can't be rebuilt from the panel.

**Deploying a deleted template builds it first.** The deploy page warns how much longer it takes. The
machine waits, its log says it's waiting for the build, and it deploys once the build is done. If the
build fails, the machine goes to error with the reason. **Build** builds a deleted or failed template
straight away instead of waiting for a deploy.

Builds run on the `builder` service, one at a time, as the panel's own vCenter account. Each build's
full output is in `/srv/lab-deploy/build-logs/`; a failed build's job shows its last lines. A deploy
of the panel doesn't interrupt a build: it updates the builder once no build is queued or running
(`build-logs/update-builder.log` says when). A build first checks:

- that its ISOs are there;
- that the datastore has room for it on top of `DATASTORE_RESERVE_GB`.

> **Note:** Redeploying the panel stops a running build. The sweep queues it again within a minute,
> and that build deletes what the first left behind.

### Leftover VMs

These are VMs in vCenter's `Labs/Machines` folder that the panel has no record of. Typical causes:

- a deploy cut off at the wrong moment;
- a database restored from an older backup;
- a VM someone made there by hand.

Before deleting one, check it isn't someone's work. **Delete** removes it from disk, after checking
again that no machine owns it. Templates are never listed here.

> **Warning:** Keep VMs that aren't the panel's out of `Labs/Machines`. The panel treats everything
> in that folder as its own.

### Jobs

Every deploy, power change, reset, destroy and template build: who asked, when, how long it took, and its result.
Click a failed job to see its full error, which for a failed setup includes the end of the machine's
own log.

## 3. Day-to-day machine management

On a machine's page:

| Action | What it does | When to use it |
|---|---|---|
| **+2 h / +1 day** | Adds time (up to 720 h in all) | A learner needs longer |
| **Keep permanently** | No expiry; limited to `MAX_PERMANENT` machines | Long-lived servers, demos |
| **Expire in 1 day instead** | Turns a permanent machine back into a timed one | Freeing a permanent slot |
| **Stop / Start / Reboot** | Power, with a clean shutdown first | Saving memory |
| **Reset to clean** | Reverts to the machine's first-boot snapshot. Setup and extras run again; the name and password stay | A learner broke it, or a lab must start again |
| **Redeploy** | Deletes the VM and deploys it again with the same settings | A failed deploy, or a reset that won't take |
| **Cancel job** | Stops the queued or running job | A deploy stuck waiting |
| **Destroy** | Deletes the VM and the record | Done with it |

**Expiry.** When time runs out, the machine is powered off and shown as **expired**. Giving it more
time starts it again. After `GRACE_MINUTES` (a day by default) an expired machine is deleted.

**Getting in:**

- The page shows the username and password, an SSH command, and for RDP machines a `.rdp` file in a
    size you choose.
- **Open console** works for any running machine, even without a network address. Its dock has
    Ctrl+Alt+Del, Paste (types your clipboard, US layout), Type password, function keys, a screenshot
    and full screen.

**Pro Lab instances** are managed from **Instances** → the instance:

- **Reset lab** resets every machine in boot order, with new flags.
- **+2 h / +1 day** extends every machine.
- **Destroy lab** removes them all.
- **Show flags** lists the instance's flag values, for checking a learner's answers.

## 4. Settings (`lab-deploy.env`)

Edit `/srv/lab-deploy/lab-deploy.env` on the server, then apply and check:

```sh
cd /srv/lab-deploy
docker compose up -d                       # recreates the services whose settings changed
curl -sk https://localhost/api/health      # database and vCenter both "ok"
```

The settings you're most likely to change:

| Setting | Default | Change it when |
|---|---|---|
| `MAX_MACHINES` | 10 | More (or fewer) machines may exist at once. Expired machines don't count |
| `MAX_PERMANENT` | 3 | More machines may be kept permanently |
| `MEMORY_OVERCOMMIT` | 1.0 | The host is small and machines idle. 1.5 lets VMs be given 1.5× physical memory, and ESXi reclaims what they don't use. Above ~1.5, machines slow down |
| `DATASTORE_RESERVE_GB` | 30 | Raise it if the datastore also holds builds or ISOs. A full datastore pauses every VM |
| `CLONE_DISK_GB` | 10 | What each new machine is expected to write, for the disk check |
| `GRACE_MINUTES` | 1440 | How long expired machines wait before deletion |
| `IP_TIMEOUT_SECONDS` | 300 | DHCP is slow |
| `EXTRAS_TIMEOUT_SECONDS` | 600 | Linux deploys with heavy extras time out |
| `WINDOWS_SETUP_TIMEOUT_SECONDS` | 1200 | Windows deploys with several extras time out |
| `MACHINE_DOMAIN` | empty | Machines should get names like `web01.lab.example` in certificates and defaults |
| `VCENTER_*` | — | vCenter moved, or its password changed (see [section 8](#8-vcenter-setup-and-privileges)) |
| `BUILD_HTTP_IP` | empty | Template builds' VMs can't reach the server: set it to the server's LAN address |
| `BUILD_MEDIA_DIR` | empty | Offline: the media folder `fetch-media.sh` made, for the Windows builds |
| `BUILD_TIMEOUT_MINUTES` | 180 | A build that takes longer is stopped |
| `CAPTURE_VM` | empty | The capture appliance is set up: its VM, e.g. `Labs/Capture/lab-capture` ([section 13](#13-packet-capture)) |
| `CAPTURE_MAX_SECONDS`, `CAPTURE_MAX_MB` | 600, 50 | Captures should be allowed to run longer or grow larger |
| `CAPTURE_PER_OWNER`, `CAPTURE_TOTAL` | 1, 3 | More captures should run at once |
| `CAPTURE_KEEP_DAYS` | 1 | Finished captures should be kept longer |

The [Developer guide's configuration reference](developer-guide.md#14-configuration-reference)
lists every setting.

## 5. Adding a machine (template) by hand

A machine on the panel is a **template** in vCenter plus an **entry** in the catalogue. Adding one
takes five steps:

1. Build the template.
2. Add it to `backend/templates.yaml`.
3. Add it to `frontend/src/lib/templates.ts`, if it's a new OS or version.
4. Run the tests, commit and push.
5. Run the end-to-end test.

> **Note:** Adding a new *version* of an OS the panel already has (say, Debian 14) follows the same
> steps. Usually the existing Packer build takes it with `-var version=… -var iso=…`.

### 5.1 Choose how to build it

| Path | Use it for | Guide |
|---|---|---|
| **Packer** (recommended) | Anything with a build in `packer/`: Ubuntu, Debian, Rocky/Alma, Fedora, Kali, Windows, OPNsense, pfSense, Proxmox, TrueNAS, VyOS, … | [build-templates.md](build-templates.md) |
| **By hand** | A one-off, or an OS with no Packer build yet | [setup-vsphere.md](setup-vsphere.md) parts 2, 5, 6 |
| **Import a complete image** | A ready-made VM that you don't install (Metasploitable, MikroTik CHR) | The import scripts in `packer/metasploitable/`, `packer/mikrotik/` |

Whichever path you take, the result must be:

- a **template** in `Labs/Templates`;
- named `tpl-<os>-<version>-<YYYYMMDD>`, for example `tpl-debian-13-20261028`;
- with a snapshot named exactly **`clean`**, taken with the VM powered off and without memory.

**Check the datastore's free space before a build.** A build needs about as much again as the
finished template; Windows builds need about 30 GB while they run.

### 5.2 Build it with Packer

The build machine needs Packer and its vSphere plugin, plus `packer/lab.pkrvars.hcl` (copy
`lab.pkrvars.hcl.example`) and an administrator's credentials in
`~/.config/lab-deploy/vcenter-build`. The details are in
[build-templates.md, part 1](build-templates.md).

1. **Put the ISO on the datastore.** The ISO's line in `scripts/isos/isos.txt` gives its name, URL
    and checksum. For a new release, add or update that line.

    ```sh
    export GOVC_URL=vcenter.lab.example GOVC_INSECURE=1
    scripts/isos/fetch.sh --list
    scripts/isos/fetch.sh debian-13 --credentials ~/.config/lab-deploy/vcenter-build
    ```

2. **Build.**

    ```sh
    packer/build.sh debian                         # the folder under packer/
    packer/build.sh ubuntu -var version=24.04 -var iso=ubuntu-24.04.5-live-server-amd64.iso
    packer/build.sh windows-server -var edition=core
    ```

    Useful options:

    - `-var extras=a,b` bakes in only those extras; `-var extras=none` bakes in none.
    - `-on-error=abort` keeps a failed build's VM so you can look at it.

    The build installs the OS unattended, runs `prepare.sh` (or `prepare.ps1`), cleans up, takes the
    `clean` snapshot and converts the VM to a template. Its name is recorded in
    `packer/output/<name>.json`.

### 5.3 Build it by hand (Linux)

When there's no Packer build for the OS:

1. **Create the VM** in `Labs/Templates`, named `tpl-<os>-<version>-<date>`:
    - thin-provisioned disk;
    - a **VMXNET3** adapter on the machines' port group;
    - the ISO, from the datastore's `ISO` folder, set to connect at power on.
2. **Install the OS.** Include OpenSSH, and create a temporary user named `builder`.
3. **Disconnect the ISO properly.** Set the CD/DVD to **Client Device**. Just disconnecting it
    leaves every clone pointing at the ISO.
4. **Let `builder` use sudo without a password.** Run this on the VM; the clean-up step removes it:

    ```sh
    echo 'builder ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/builder
    ```

5. **Prepare it** from a machine with this repository:

    ```sh
    ssh builder@192.0.2.50 'sudo bash -s -- --dry-run' < scripts/template/prepare.sh   # what it found and plans
    ssh builder@192.0.2.50 'sudo bash -s' < scripts/template/prepare.sh
    ```

    This installs cloud-init and VMware Tools, grows the disk, and bakes in the extras' packages.
    `--extras=a,b` bakes in only those; `--no-extras` bakes in none.

6. **Clean it.** This resets the VM's identity, deletes `builder` and powers it off:

    ```sh
    ssh builder@192.0.2.50 'sudo bash -s -- --yes' < scripts/template/clean.sh
    ```

7. **Snapshot and convert.** In vCenter, take a snapshot named **`clean`** (no memory), then
    right-click → **Template → Convert to Template**.

> **Note:** `prepare.sh` and `clean.sh` recognise Ubuntu, Debian, Kali, Parrot, CentOS Stream, Rocky,
> Alma, Fedora and CachyOS. A new distribution needs its `/etc/os-release` `ID` added to both scripts.
> See [scripts/template/README.md](../scripts/template/README.md).

**Windows by hand** follows [setup-vsphere.md part 5](setup-vsphere.md): EFI with Secure Boot, then
`prepare.ps1 -Msi <CloudbaseInit.msi>` (add `-Office`/`-SqlServer` media for those extras). Then
`clean.ps1 -Yes`, which syspreps and shuts down, followed by the same `clean` snapshot and conversion.

### 5.4 Import a complete image

Some machines are images you deploy as they are, not install. Each has an import script that builds
the template, takes the `clean` snapshot and converts it:

```sh
export GOVC_URL=vcenter.lab.example GOVC_INSECURE=1
packer/metasploitable/import-ms2.sh --credentials ~/.config/lab-deploy/vcenter-build
VERSION=7 packer/mikrotik/import-chr.sh --credentials ~/.config/lab-deploy/vcenter-build
```

The panel can't set a password on these, so their catalogue entry uses `family: image` with the
image's fixed `password` (see below).

### 5.5 Add it to the catalogue

**Step 1: `backend/templates.yaml`.** Add an entry; the file's header explains every key.

```yaml
- template: debian              # the catalogue id (same as in templates.ts)
  version: "13"                 # always a string
  # Built by Packer (packer/build.sh debian) on 2026-10-28.
  vsphere: Labs/Templates/tpl-debian-13-20261028
  cpu: 2
  memoryGB: 2
  diskGB: 40
  username: labuser             # the user created on each machine, with a generated password
  family: debian
  extras: [nginx, apache, apache-https, wordpress, postgresql, mariadb, sqlite, ftp]
```

| Key | Required | Meaning |
|---|---|---|
| `template`, `version` | yes | Which catalogue entry and version this is |
| `vsphere` | yes, unless `planned` | The template's path under the datacenter's VM folder |
| `cpu`, `memoryGB`, `diskGB` | yes | The machine's size. `diskGB` is the template's disk |
| `username` | yes | The account each machine gets |
| `family` | default `debian` | How first boot works: `debian`, `rhel` (Rocky, Alma, CentOS, Fedora), `arch` (CachyOS), `windows`, `legacy` (old Linux and appliances with their own first-boot script), `vyos`, `image` (deployed as is) |
| `adminGroup` | no | The group that gives sudo. Defaults: `sudo`, `wheel` for rhel/arch, Administrators for Windows |
| `extras` | no | Extras learners can tick. List only those **baked into this build** |
| `plannedExtras` | no | Extras prepped but not in this build yet; shown as "Soon" |
| `always` | no | Hidden extras every machine gets (e.g. `gnome-remote-login` on Ubuntu Desktop) |
| `choices` | no | Extra values for template-specific options, e.g. `{php: ["8.5"]}` |
| `access` | no | Any of `ssh`, `rdp`, `web`, `console`. Defaults to what `templates.ts` says |
| `webUrl` | no | Its web interface, with `{ip}`, e.g. `https://{ip}:8006/` |
| `password` | `image` only | The image's fixed password, e.g. `msfadmin` |
| `planned` | no | `true`: listed as "Soon", can't be deployed (no `vsphere` needed) |

**Step 2: `frontend/src/lib/templates.ts`.**

- **A new version of an existing OS:** add it to that entry's `versions` (newest first; mark old
    ones `eol: true`).
- **A new OS:** add a whole entry. The test fails if a `templates.yaml` template or version is
    missing here.

```ts
{
	id: 'debian',
	name: 'Debian',
	category: 'Linux',
	os: 'Linux',
	description: 'Debian stable releases, minimal install with OpenSSH.',
	versions: [{ version: '13' }, { version: '12' }],
	resources: { cpu: 1, memoryGB: 2, diskGB: 20 },
	access: ['ssh', 'console'],
	credentials: 'labuser / set on first deploy',
},
```

**Step 3: optional files.**

- `frontend/src/lib/os-logos.ts`: a logo for a new OS. Without one, it gets a lettered badge.
- `deploy/install/manifest.toml`: a `[[template]]` entry, if the offline installer should build it.

### 5.6 Test, ship, and check

```sh
docker compose -f backend/compose.test.yaml run --rm --build tests
(cd frontend && npm run check)
git add -A && git commit -m "Debian 13 template" && git push    # the pipeline deploys the panel
scripts/e2e/run.py --panel https://panel.example --only debian:13
```

The new version appears on the panel once the pipeline has finished. The end-to-end run deploys real
machines and checks every extra; exit 0 means the template is good.

### 5.7 Updating and retiring a template

**Updating.** Build a new one; its date makes it a new name. Then point `vsphere:` at it and push.
Existing machines keep using the old template, so delete the old one only once **no machine uses
it**: every machine's disk is built on its template's `clean` snapshot.

**Deleting from vCenter.** vCenter may refuse with "Invalid virtual machine state". Right-click →
**Template → Convert to Virtual Machine**, then **Delete from Disk**.

**Retiring a version** without removing it from the catalogue: mark the entry `planned: true` and
comment out `vsphere:`, with a note saying how to rebuild it. Learners then see it as "Soon".

```yaml
- template: windows-server
    version: "2022"
    # Retired 2026-10-27 to free space; rebuild with packer/build.sh windows-server -var version=2022.
    planned: true
    # vsphere: Labs/Templates/tpl-windows-server-2022-20261018
    cpu: 2                        # the other keys stay as they were
    memoryGB: 4
    diskGB: 60
    username: labadmin
    family: windows
```

## 6. Adding an extra (service)

Extras are services learners tick at deploy. To add one:

1. **Define it** in `backend/extras.yaml`. The header lists every key; copy a similar extra.

    ```yaml

    - id: redis
      name: Redis
      category: Databases
      description: Redis, listening on the network with a password.
      ports: [6379]                    # extras sharing a port can't be ticked together
      password: true                   # the script gets $password
      notes:
        - "Connect with redis-cli -h {ip} -a <the machine's password>."
      debian:
        packages: [redis-server]
        script: |
          sed -i 's/^bind .*/bind 0.0.0.0/' /etc/redis/redis.conf
          echo "requirepass $password" >> /etc/redis/redis.conf
          systemctl enable --now redis-server
    ```

2. **Bake its packages** into templates in `scripts/template/prepare.sh`:
    - packages go in `EXTRA_PACKAGES_DEBIAN[redis]` (and the RHEL or Arch arrays for those families);
    - services go in `EXTRA_SERVICES`;
    - anything more goes in a `bake_redis()` function.

    The backend tests check this.

    **An extra that runs in Docker** needs no baking beyond `docker.io`: give it `dockerImage:` (e.g.
    `redis:8.2`), start it with `lab_docker`, and put its image on the datastore with
    `scripts/isos/fetch-images.sh redis`. Any template with Docker can then offer it, without a
    rebuild. The panel marks it "Docker" for learners.

3. **Rebuild the templates** that should offer it, then list `redis` under their `extras:`. Until
    then, put it under `plannedExtras:`; it shows as "Soon".
4. **Tidy the "Soon" list.** If it was listed as a planned service in
    `frontend/src/lib/services.ts`, remove it from there.
5. **Add an end-to-end check** in `scripts/e2e/checks.py`.

**Windows extras** have only a `windows: script:` (PowerShell, run as SYSTEM). Nothing needs baking
unless the script uses installation media.

### The Docker extras' image ISOs

Each Docker extra's image is an ISO in the datastore's ISO folder, `lab-image-<extra>-<tag>.iso`. A
deploy with that extra attaches it as a CD, the machine loads the image, and the CD comes out once
the machine is set up. A deploy fails straight away, before cloning, if one it needs is missing.

```bash
export GOVC_URL=<vCenter address> GOVC_INSECURE=1
scripts/isos/fetch-images.sh --list                                   # each extra, its image and its ISO
scripts/isos/fetch-images.sh --missing --credentials <file>           # make and upload any not there
scripts/isos/fetch-images.sh grafana --credentials <file>             # one, after changing its image
```

**Several images, or files rather than images:** an extra can list `dockerImages:` (ELK's three, on
one ISO named with a hash of the list) or name a `mediaIso:` of files (k3s's binary and offline
images, Winlogbeat for Windows), which `fetch-images.sh` makes from its own pinned downloads. Media
CDs work on Windows too.

**To update an image,** change its `dockerImage:` in `extras.yaml`, run `fetch-images.sh` for that
extra, and deploy the panel. The new version is a new ISO. Machines deployed with the old one keep
using it: a reset attaches the same ISO again. Delete the old ISO once none of those machines is
left; a reset of one fails, saying so, if its ISO is gone, and a redeploy then uses the current one.

## 7. Adding a Pro Lab by hand

A Pro Lab is several machines deployed together as one instance. They come up in boot order, are
wired to each other, and have flags planted in each instance. Labs are defined in
`backend/labs.yaml`; Brookfield there is the working example.

### 7.1 Before you start

- **Every machine's template must be built** and deployable in `templates.yaml`.
- **Seeding extras.** Most labs need one or two: an extra per role that adds the users, weaknesses,
    files and flag locations, in `category: Pro Labs`. Brookfield's are `brookfield-dc` and
    `brookfield-member` in `extras.yaml`; copy them. Seeding extras that only run a script need no
    rebuild.
- **List every extra a lab machine uses** (seeding or otherwise) in that template's `extras:`
    in `templates.yaml`. Otherwise the lab is shown as **Soon**, with the reason.
- **Size it.** Add up the machines' memory and disk. Brookfield needs about 18 GB of memory and
    75 GB of disk while deploying. The panel refuses an instance that doesn't fit.

### 7.2 Define it in `labs.yaml`

A small two-machine example: a web server with a WordPress site, and a file server it backs up to.

```yaml
- slug: lakeside                 # lowercase id; the card in labs.ts uses the same slug
  title: Lakeside Studio
  description: A design studio's website and file server, to break into and pivot between.
  level: Beginner                # Beginner, Intermediate or Advanced
  domain: ""                     # an AD domain for domain labs
  resetScope: lab
  machines:
    - name: files                # role name: [a-z][a-z0-9]{0,8}, unique in the lab
      template: ubuntu
      version: "26.04"
      role: File server
      bootOrder: 1               # lower comes up first
      extras:
        - {ftp: {tls: "no"}}
        - lakeside-files         # a seeding extra you wrote
    - name: web
      template: ubuntu
      version: "26.04"
      role: Public website
      bootOrder: 2
      extras:
        - wordpress
        - {lakeside-web: {files: "@files"}}   # a machine option: the instance's own "files"
  flags:
    - id: user
      where: the web server, in the site user's home folder (user.txt)
      machine: web
      file: /home/ubuntu/user.txt
```

The two seeding extras go in `backend/extras.yaml`. The `files` option is a **machine** option: its
`extra` says which extra the other machine must have, and the script gets that machine's details as
`$files_ip`, `$files_username` and so on.

```yaml
- id: lakeside-web
  name: Lakeside lab (web)
  category: Pro Labs
  description: Seeds the Lakeside Pro Lab's web server. For the Lakeside lab, not for a machine on its own.
  options:
    - id: files
      label: File server
      type: machine
      extra: lakeside-files
  debian:
    script: |
      # A backup script with the file server's FTP password in it: the way in to the next machine.
      install -d -m 755 /var/www/html/backup
      printf 'ftp://%s:%s@%s/\n' "$files_username" "$files_password" "$files_ip" > /var/www/html/backup/notes.txt
```

Then list `lakeside-web` and `lakeside-files` under Ubuntu 26.04's `extras:` in `templates.yaml`.
Script-only extras need no template rebuild.

The keys:

- **`machines`.** Each has a `name` (its role; the hostname becomes `<instance>-<name>`), a
    `template` and `version` from the catalogue, the `role` text shown to learners, a `bootOrder`, and
    `extras`. Each extra is an id, or `{id: {option: value}}`.
- **`"@<name>"`.** The value for a machine-type option, such as `join-domain`'s `dc`. The panel
    replaces it with that machine in the same instance. It must point at a machine with a **lower**
    `bootOrder`.
- **`flags`.** Each has an `id`, a `where` (shown on the checklist) and the `machine` it's planted
    on, plus one of:

    - `file:` the flag's value is written to that path;
    - `run:` a PowerShell script is run with the value as its last argument. This is for Windows only,
      e.g. Brookfield's mail flag.

> **Note:** Flags are written through VMware Tools as the machine's own user (`ubuntu`, `labadmin`, …),
> so a `file:` path must be one that user can write. For a flag in a protected place, have the seeding
> extra create the folder or file first with the right owner. So far flags have only been planted on
> Windows (Brookfield), so check a Linux lab's flags after its first deploy.

### 7.3 The catalogue card (optional)

The Pro Labs page lists every lab from `labs.yaml` and works without a card. For a picture and a
network sketch:

- add an entry with the same `slug` to `frontend/src/lib/labs.ts`;
- add an SVG at `frontend/static/images/labs/<slug>.svg`.

Designs in `labs.ts` with no `labs.yaml` entry show as planned.

### 7.4 Ship and test it

1. Run the backend tests. `labs.yaml` is validated on load: unknown templates, extras, options and
    bad `@` references are errors.
2. Commit and push.
3. On the panel, open **Pro Labs** → the lab. If it says **Soon**, the reason names the missing
    template or extra.
4. Deploy an instance, and watch each machine's activity log as the tiers come up in boot order.
5. On the instance page, click **Show flags**, and check each flag is where `where:` says. A flag
    that couldn't be planted is a warning in that machine's log; the machine still counts as ready.
6. Test **Reset lab**: the flags should change.

## 8. vCenter setup and privileges

The panel signs in to vCenter as its own account (`svc-labdeploy`), with two roles that
`scripts/setup_vcenter.py` creates:

- **Lab Deploy**, on the `Labs` folders, the datastore and the port group;
- **Lab Deploy (placement)**, on the cluster.

Lab Deploy includes what Packer needs to build templates (the Admin page's Templates list), so the
server never holds an administrator's sign-in. Re-run the script after updating to a version that
added this (2026-10-28).

The script also creates the folders `Labs/Templates` and `Labs/Machines`. The account itself is
created by hand in vCenter (Administration → Single Sign On → Users and Groups).

```sh
python3 -m venv ~/labdeploy-setup && ~/labdeploy-setup/bin/pip install pyvmomi
~/labdeploy-setup/bin/python scripts/setup_vcenter.py
```

It is safe to re-run. **Re-run it** when:

- an update needs a new privilege (the commit says so);
- a job fails with `NoPermission`, whose message names the missing privilege;
- vCenter has been rebuilt.

It prints the `VCENTER_*` lines for `lab-deploy.env`. Full walk-through:
[setup-vsphere.md part 1](setup-vsphere.md).

## 9. Capacity and datastore space

**Memory** is usually the first limit. Lower it by stopping idle machines, or raise
`MEMORY_OVERCOMMIT` a little.

**Disk** is where trouble comes from. A full datastore **pauses every VM** writing to it, and vCenter
asks a "no more space" question for each. To keep room:

- Delete templates nobody uses from the Admin page's Templates list: a template takes about five
  times its ISO's space, and the next deploy builds it again from the ISO. Keep the ISOs.
- Delete replaced templates promptly ([section 5.7](#57-updating-and-retiring-a-template)).
- Run builds, Windows especially, one at a time, and check free space first.
- Keep `DATASTORE_RESERVE_GB` above what one build needs.

**What's safe to delete:**

| Safe | Not safe |
|---|---|
| VMs in `Labs/` that the panel lists as leftovers | The vCenter VM, ever |
| Templates the Admin page offers to delete | A template while any machine uses it |
| ISOs listed in `scripts/isos/isos.txt` whose templates can't be rebuilt from the panel | An ISO a rebuildable template needs, or one that can't be downloaded again |
| Retired `tpl-*` templates no machine uses | A template's `clean` snapshot |

> **Warning:** If ESXi runs nested inside VMware Workstation, its virtual disk grows on the PC and
> doesn't shrink when VMs are deleted. When ESXi and vCenter both stop answering, first check the
> PC's free disk. A full disk pauses the ESXi VM.

## 10. Backups and restore

The `backup` service dumps the database when it starts and then daily, to
`/srv/lab-deploy/backups/labdeploy-<date>-<time>.sql.gz`, and keeps 14 days.

The database holds every machine's password and settings. Without it, the panel no longer knows its
VMs: they would all show up as leftovers.

To restore (this replaces the database), stop the workers first:

```sh
cd /srv/lab-deploy
docker compose stop worker sweeper
gunzip -c backups/labdeploy-<date>-<time>.sql.gz | docker compose exec -T postgres psql -q -U labdeploy labdeploy
docker compose start worker sweeper
```

After a restore:

- machines created since the dump appear under **Leftover VMs**;
- machines deleted since the dump show as errors, and can be destroyed.

> **Warning:** The dumps stay on the panel's server. Copy `backups/` to another machine or share
> regularly. There is no off-host copy yet.

## 11. Deploying and updating the panel

- **Normally:** push to `main`. The pipeline checks the code, tests it, and runs `deploy/deploy.sh`
    against the server. A deploy waits up to 15 minutes for running jobs to finish. Batch your
    changes into one push, because overlapping deploys can leave the API down.
- **By hand**, from a development machine:

    ```sh
    DEPLOY_HOST=192.0.2.10 SSH_KEY=~/.ssh/lab-deploy deploy/deploy.sh
    ```

- **A new server** (Ubuntu 22.04/24.04): run `sudo bash deploy/setup-server.sh` once. Then deploy,
    fill in `lab-deploy.env`'s vCenter settings, and run `docker compose up -d`.
- **The browser warning.** The panel uses Caddy's internal CA. To stop browsers warning, export
    its root certificate and trust it:

    ```sh
    docker compose -f /srv/lab-deploy/compose.yaml exec caddy cat /data/caddy/pki/authorities/local/root.crt
    ```

- **Without internet**, the offline bundle installs the panel and builds every template:
    [offline-install.md](offline-install.md).

## 12. Troubleshooting

Start with the machine's **activity log** and its failed job (**Admin → Jobs**). For more detail,
the worker's own log:

```sh
cd /srv/lab-deploy
docker compose logs --since 1h worker sweeper
docker compose ps                         # every service up and healthy?
```

| Symptom | Likely cause | What to do |
|---|---|---|
| Banner "vCenter isn't set up yet" | `VCENTER_*` empty or wrong | Fill in `lab-deploy.env`, `docker compose up -d`, check `/api/health` |
| Deploy fails "has no snapshot named 'clean'" | The template was converted without its snapshot | Convert it back to a VM, take the `clean` snapshot powered off, convert again |
| `NoPermission … <privilege>` | The panel's role is missing a privilege | Re-run `scripts/setup_vcenter.py` |
| Deploy fails "no address" | DHCP pool exhausted (every clone is a new MAC) | Shorten lease times (an hour is good) or enlarge the pool. Keep fixed addresses outside it |
| A machine powered itself off right after deploy | DHCP gave it an ESXi or vCenter address | Move those hosts' addresses out of the DHCP pool |
| Setup timed out | Heavy extras or a slow host | Look at the log tail in the job; raise `EXTRAS_TIMEOUT_SECONDS` or `WINDOWS_SETUP_TIMEOUT_SECONDS`; redeploy |
| Windows user can't sign in | Password doesn't meet Windows' rules, or setup still running | Use a generated password; wait for "running" |
| A job sits "running" for ever | Its worker was killed | The sweep marks it failed within a minute or two; else **Cancel job**, then Redeploy |
| Everything paused, VMs show "no more space" | Datastore full | Free space ([section 9](#9-capacity-and-datastore-space)), then answer vCenter's question on each VM (Retry) |
| ESXi and vCenter both stop answering | The nested host's PC disk is full | Free space on the PC |
| Console won't open | Machine stopped, or console privilege missing | Start it; re-run `setup_vcenter.py` |
| Console opens black | A guest display quirk (seen on Ubuntu Desktop) | Reconnect; use RDP meanwhile |
| A lab shows "Soon" | A template isn't built, or doesn't list an extra the lab uses | The reason on the lab's page names it; see [7.1](#71-before-you-start) |

## 13. Packet capture

The **Network** page draws each person's machines on the LAN and captures the traffic between them,
with a BPF filter. Traffic between machines stays inside ESXi's virtual switch, so a small VM, the
**capture appliance**, listens on a promiscuous port group with the LAN's VLAN. The panel signs in to it
over SSH, runs tcpdump there and streams the packets back. Design: [plan.md section 12](plan.md#12-packet-capture-and-the-network-diagram).

> **Warning:** A VM on the capture port group sees **all** the LAN's traffic on that switch: vCenter,
> ESXi, the panel and everyone's machines. Put nothing else on it. The panel limits every capture to the
> chosen machines' MAC addresses, and its key on the appliance may only run `lab-capture`.

**Setting it up** (once; about 15 minutes):

1. **The port group and folder.** From a machine with pyVmomi (as for `setup_vcenter.py`):

    ```sh
    ~/labdeploy-setup/bin/python scripts/setup_capture.py
    ```

    It adds `LAN-capture` to every host's vSwitch that carries the LAN's port group (same VLAN,
    promiscuous mode on, forged transmits and MAC changes refused), and the folder `Labs/Capture`. On a
    **distributed switch** it stops: add a distributed port group `LAN-capture` by hand, with the LAN's
    VLAN and Security → Promiscuous mode set to Accept.
2. **The panel's key.** Admin → Packet capture shows the panel's public key (made on the API's first
    start). Copy it.
3. **Build the appliance** (from the build machine, as for templates;
    [build-templates.md](build-templates.md)). It needs Alpine's ISO, the same as `packer/alpine`:

    ```sh
    packer/build.sh capture -var panel_key="ssh-ed25519 AAAA… lab-deploy-capture"
    ```

    This leaves the VM `lab-capture`, powered off, in `Labs/Capture`.
4. **Power it on**, and set it in `/srv/lab-deploy/lab-deploy.env`:

    ```sh
    CAPTURE_VM=Labs/Capture/lab-capture
    ```

    Then `docker compose up -d api`. The panel reads the appliance's address from VMware Tools, so DHCP
    can give it any address. Set `CAPTURE_HOST` instead to use a fixed address.
5. **Check it.** Admin → Packet capture should say **Answering**. On the Network page, select two
    machines, pick ICMP, start a capture, and ping one from the other.

**The appliance's host key** is accepted on the first connection, then pinned (under the name
`lab-capture`, whatever its address). After rebuilding the appliance, remove the old key:

```sh
docker compose exec api ssh-keygen -f /capture/ssh/known_hosts -R lab-capture
```

**A new panel key** (a new server, or the `capture` volume was lost): build the appliance again with
the new key, or put it in `/root/.ssh/authorized_keys.panel` on the appliance (from its console) and
run `finish-capture.sh` there, which also powers it off.

**Limits.** A capture runs at most `CAPTURE_MAX_SECONDS` (10 minutes) and `CAPTURE_MAX_MB` (50 MB), one
per person and three at once. Finished captures are kept `CAPTURE_KEEP_DAYS` (1 day), or until all their
machines are destroyed. A deploy restarts the API, which stops running captures; what they captured is
kept. Each start is written to the machines' activity logs.

**When it doesn't answer**, Admin → Packet capture says why:

| It says | Do this |
|---|---|
| "has no address: is it running, with VMware Tools?" | Power the appliance on; wait a minute for Tools |
| "Couldn't reach the capture appliance … Permission denied" | The appliance doesn't have the panel's current key: see "A new panel key" |
| "… REMOTE HOST IDENTIFICATION HAS CHANGED" | The appliance was rebuilt: remove its old host key (above) |
| A capture with no packets | The machines are on another host or switch than the appliance, or the port group isn't promiscuous |
