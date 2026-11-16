# Roadmap

Where lab-deploy stands and what comes next. Last updated 2026-11-10. The original design is in
[plan.md](plan.md); building templates is in [build-templates.md](build-templates.md).

## Where things stand

The panel deploys single machines on vSphere. Each machine gets a name, a password or SSH key, an
expiry date, and optional extras (services installed at first boot). Machines can be stopped,
started, rebooted, reset to clean, redeployed and destroyed. Every push to `main` is tested and
deployed by CI.

**Templates built and passing the end-to-end tests:**

| Family | Templates |
|---|---|
| Ubuntu | 26.04, 24.04, 22.04, 20.04, 18.04, 16.04 |
| Ubuntu Desktop | 26.04, 24.04, 22.04 (GNOME over Remote Desktop) |
| Debian | 13, 12; 11, 10, 9, 8 (legacy) |
| Enterprise Linux | Rocky 10, 9 and 8; AlmaLinux 10, 9 and 8; CentOS Stream 9; CentOS 8, 7, 6 (legacy) |
| Fedora | Server 44 (with Cockpit), Workstation 44 (GNOME over Remote Desktop) |
| Arch-based | CachyOS (rolling; KDE Plasma on the console) |
| Small and BSD | Alpine Linux 3.24, FreeBSD 15.1 (added 2026-10-29; no extras) |
| Windows Server | 2025 (desktop and Core), 2022, 2019 (rebuilt 2026-10-28); 2016 and 2012 R2 (legacy; added 2026-10-28, no SQL Server or Outlook) |
| Windows | 11 Enterprise (90-day evaluation; TPM checks skipped) |
| Security | Kali 2026.2, Parrot 7.4 (both rebuilt 2026-10-29 with only web servers, FTP, Docker and Python) |
| Firewalls and routers | OPNsense 26.7, pfSense CE 2.7.2, VyOS (rolling), MikroTik CHR 7.24 and 6.49 |
| Hypervisors | Proxmox VE 9.2, 8.4, 7.4; XCP-ng 8.3 (all nested) |
| Mail | Exchange Server SE (its own template; joins a domain controller's domain), Zimbra 8.8.15 |
| Storage | TrueNAS SCALE 25.10 and 25.04, TrueNAS CORE 13.3 and 13.0 |
| Practice targets | Metasploitable 2 and 3 (Linux), as complete images; Metasploitable 3 (Windows) retired 2026-10-27 for space, to re-import |

**Extras:** web servers (Apache with a choice of PHP 5.6 to 8.5 on Ubuntu 22.04 and 24.04),
WordPress, Nextcloud, databases with sample data, mail (and iRedMail), FTP, desktop and RDP, IIS,
SQL Server, Outlook, MinIO, Python versions (2.7 and 3.8–3.15). Docker, with Juice Shop, DVWA,
Uptime Kuma, Vaultwarden, Gitea and Grafana baked into the templates so they work offline. Wazuh and
Zabbix, each as a server and an agent that picks its server machine and registers itself. VPN servers
(WireGuard and OpenVPN, 2026-11-10; see [3b](#3b-vpn-servers-wireguard-and-openvpn--built-2026-11-10)).

**Active Directory** (finished 2026-10-20). Two extras:
- **Domain controller** (Windows Server): installs AD DS and DNS and creates a new forest; the machine's
  user becomes a domain administrator.
- **Join a domain** (all Windows): pick a running domain controller from your machines; the panel
  passes its address and sign-in to the join, keeping only its id. This is a new kind of option,
  "machine", that other features can reuse.
- Tested live: a Server 2025 controller and a Server 2025 Core member, with the controller's user
  signing in to the member as a domain user.

**Browser console** (finished 2026-10-19, controls reworked 2026-10-27). Open console on a machine's
page shows its screen, keyboard and mouse in the browser.
- **How it works:** the panel gets a WebMKS ticket from vCenter and relays the stream from ESXi.
  noVNC shows it.
- **Controls:** a collapsible dock that stays on screen in full screen and fades when the mouse is
  still: Ctrl+Alt+Del, Paste (types the clipboard into the machine), Type password, Send keys (Esc,
  Tab, Alt+Tab, Ctrl+Alt+F2–F6), Fit/1:1, Screenshot, Full screen, Open in new tab. A dropped console
  reconnects by itself up to 4 times.
- **New tab:** `/machines/{id}/console?view=tab` shows just the screen, filling the tab; the machine
  page has a New tab button.
- **Clipboard out of the machine** is best effort only: WebMKS doesn't send it, and VMware Tools'
  clipboard sync needs a desktop session that guest operations don't have.
- **Access:** open to everyone for now; to be limited once there's sign-in (see below).
- **Tested:** in Chrome and Firefox with Ubuntu 26.04.
- **Known behaviour:**
  - ESXi closes a console when it gets a WebSocket ping, so the relay sends none.
  - ESXi presses the key a character is on without Shift, so Type password holds Shift itself
    (US layout).
  - The ticket path only works if the API runs as a single process.
  - **Ubuntu Desktop (GNOME on Wayland) sometimes shows a black screen** (ESXi itself has a 1×1
    framebuffer; Kali on Xorg never does). Possible fixes are noted but parked unless it comes back;
    those desktops are used over Remote Desktop anyway.

**Remote Desktop file** (2026-10-28). The machine page's `.rdp` download has a size picker (full
screen, or a window from 1024x768 to 2560x1440; the last pick is kept in the browser, 1280x720 by
default), with the clipboard shared, 32-bit colour, reconnecting and dynamic resolution. **Live
resizing doesn't work yet** from Windows' client to Kali's xrdp 0.10: mstsc sends no resizes. Parked;
the next step (an xrdp debug log while resizing) is agreed.

**Also done:**
- OS and distribution logos on the catalogue, the deploy page, the machines list and machine pages.
- The offline install: [offline-install.md](offline-install.md).
- **Long jobs can't hold up the sweep** (2026-10-27). Deploys, redeploys and resets run on the worker's
  `default` queue; the per-minute sweep and quick actions (start, stop, reboot, expire, destroy) on a
  `quick` queue, served by a second worker, `sweeper`. Before, four long deploys (Exchange takes about an
  hour) filled every slot, and expiry, lost-job recovery and a lab's next machines waited for them.
- **Lighter polling** (2026-10-27): each open page polls one `GET /api/state`; passwords only come
  with a single machine, and its log sends only new lines (two of the review's smaller items).
- **The review of 2026-11-11, batches 1 to 3** (2026-11-16):
  - **Secrets:** lab machines keep no passwords the attack path doesn't intend. The extras' scripts,
    cloud-init's copies of the first-boot data and Linux flag-planting scripts are deleted once used
    (checked live on Ubuntu 26.04, through a reboot, and on a Windows Server 2025 domain controller).
    A flag counts as planted only once its planting exits with 0.
  - **Correctness:** lab members can't be extended, kept, destroyed or reset on their own. A failed
    power-off at expiry is retried every 15 minutes. Activity logs keep 1000 lines per machine.
    Template builds can be cancelled. Deploys lock while they count. Changes are refused from other
    sites' pages. A cancelled setup powers its VM off.
  - **Polish:** the deploy form says why Deploy is disabled and asks for Name and Owner first. A
    banner shows when vCenter can't be reached. Stale "Soon" placeholders are gone.
  - Still open from that review (batches 4 and 5): letting deploys wait for long jobs, a sweep for
    stuck states, build progress, row and bulk actions, a per-person limit, flag submission, a
    lab's sign-in file, notifications, frontend tests, one folder per extra, one catalogue.
- The [project review of 2026-10-23](review-2026-10-23.md): its five top priorities (a datastore
  reserve, machines that depend on each other, cancelling a stuck job, expired machines out of the
  quota, capacity on the deploy form). The rest is kept for later.

## Waiting on Jake

| Item | What's needed | Then |
|---|---|---|
| Disk space for the next templates | None now: 89 GB free on 2026-10-29 after Jake deleted unused templates. ISOs stay; unused templates are deleted instead (templates on demand), and every ISO a recipe needs is back on the datastore | Windows 10 (~23 GB), Metasploitable 3 Windows (~14 GB), Parrot 6 (~19 GB, plus its import base while building) |
| Windows 7, Server 2008 R2, ESXi | Their ISOs (not downloadable without a licence or a Broadcom login) | A legacy Windows build; nested ESXi |
| vuln-ad fixes | A yes to push the fixes to `workstation/vuln-workstation.ps1`, committed locally in the vuln-ad repo | Push to `jake/vuln-ad` |
| Firefox black screen | Testing on the one affected Firefox: without extensions, then with `privacy.resistFingerprinting` off. Canvas blockers stop the screen drawing | A fix if it isn't the browser's settings |
| Workstation snapshot | Delete the snapshot of the ESXi VM taken before the datastore was extended | — |
| `parrot-base-7.4` | Choose: convert it to a vSphere template (recommended; it stays, for Parrot rebuilds) or delete it (frees 12.7 GB; rebuilding then means re-importing the OVA) | One line in `packer/parrot/import-base.sh` so new bases are templates |
| Off-host backups | Somewhere to copy the daily database dump: a network share or another machine | A copy job in `deploy/compose.yaml` |
| RDP live resize | A go-ahead to set xrdp's log to DEBUG on kali01 (restarting xrdp drops the RDP window; the session stays), then a connect and resize | Read whether resize messages arrive, and fix xrdp or the desktop side |
| Brookfield `i-9547` | Done looking at it? It was left running after the 2026-10-27 test | Destroy it (frees about 18 GB of memory) |
| Exercises | Answers to the open questions in [plan.md](plan.md#open-questions-for-jake) and a go-ahead | Phase 1: the engine and the iptables track |

## Next, in order

Items 1, 2 and 4 are finished or dropped and kept for the record. **Up next: item 3, the services
batch**, then 5 to 7.

### 1. ProLabs: the first multi-machine lab (large) — done 2026-10-27

**Goal.** A lab of several machines deployed together as one instance, as the LMS's Pro Lab pages
describe.

**First lab: Brookfield Logistics** (agreed 2026-10-23). A small company's Active Directory domain,
`brookfield.local`:
- a Windows Server domain controller;
- a Windows Server with Exchange SE, mailboxes and sample mail (Outlook on the web);
- a Windows 11 staff workstation.

Its weaknesses come from the `/home/user/coding/vuln-ad` scripts (`dc/vuln-ad.ps1`, `dc/emails.ps1`,
`workstation/vuln-workstation.ps1`): Kerberoasting, AS-REP roasting, weak ACLs, DNSAdmins, passwords
in descriptions, password spraying, DCSync, silver and golden tickets, pass-the-hash and
pass-the-ticket, SMB signing off. Plus file shares, users and sample emails.

**Decisions:**
- **Deploying:** one click on the lab's page makes all three machines, in boot order (the domain
  controller first). Reset and destroy act on the whole lab.
- **Build approach (changed 2026-10-26):** the machines **reuse the base templates** (`windows-server
  2025` + `exchange SE` + `windows 11`) with extras, rather than pre-built golden templates. This saves
  about 90 GB and keeps them current, at the cost of a long deploy (Exchange took about an hour in the
  2026-10-27 test). The
  members join the instance's own domain controller through `@dc` (cross-machine extra wiring).
- **Network:** the LAN with DHCP for now; members use the domain controller for DNS. A network per
  instance comes with "Networks" (see "Later").
- **Size:** about 18 GB of memory, so one instance at a time. **Disk:** about 75 GB while it deploys
  (Exchange's install growth); the `exchange` extra declares `diskGB: 45` so the capacity check counts it.
- **Flags:** random `LAB{...}` flags planted per instance (the workstation user's `user.txt`, a share,
  an email, the domain Administrator's `root.txt`), new on each deploy and reset, with a checklist on
  the lab's page.

**Steps:**

| Step | What | State |
|---|---|---|
| 1 | Lab definitions: `backend/labs.yaml` and `app/labs.py` | Done 2026-10-24 |
| 2 | Orchestration: `POST /api/instances` deploys a lab's machines in boot order; reset, destroy and cancel act on the whole instance | Done 2026-10-26 |
| 3 | The Pro Labs and Instances pages (machines in boot order, flags, Deploy, Reset, Destroy, Cancel, extend) | Done 2026-10-26 |
| 4 | Flags: random per instance, planted via VMware Tools once each machine is up, with the checklist | Done 2026-10-26 |
| 5 | Brookfield live by reusing the base templates: cross-machine extra wiring (`@dc`), the `brookfield-dc` and `brookfield-member` seeding extras, Brookfield redefined and marked live | Done 2026-10-26 |
| 6 | End-to-end test of a whole instance | Done 2026-10-27 |

**Step 6 result.** A Brookfield instance was deployed end to end through the panel (instance `i-9547`,
2026-10-27). All three machines came up clean (no warnings): the domain controller promoted
`brookfield.local`, the Exchange server joined and installed (about an hour), and the Windows 11
workstation joined. The `brookfield-dc` and `brookfield-member` seeding ran, and **all four flags
planted** (`user.txt`, the Finance share, the mailbox message, `root.txt`) once the two guest-operation
privileges were granted. The earlier run (2026-10-26) had filled the datastore; freeing ~46 GB (retiring
three templates) and declaring the `exchange` extra's `diskGB: 45` fixed that, and this run had room.

**Pro Labs is done.** Brookfield is live and deploys as one instance with flags. Follow-ons, if wanted:
a network per instance (VLAN/port group, with a VPN — see "Later"); a second lab; and rebuilding the
three templates retired to make room (Windows Server 2019/2022, Metasploitable 3 Windows).

### 1a. Meridian: the second Pro Lab, with two replicating domain controllers (large) — started 2026-10-30

**Goal.** The LMS's Meridian lab, cut from seven machines to five (four Windows, one Linux). Jake's main
requirement is **two domain controllers replicating with each other**. Domain `meridian.corp`:
- **dc1** (Windows Server 2025): the first domain controller, plus AD CS with web enrolment;
- **dc2** (Windows Server 2025): a second, writable domain controller in the same site, replicating both ways;
- **sql** (Windows Server 2025): SQL Server, running as a domain service account;
- **ws** (Windows 11): a staff workstation;
- **web** (Ubuntu 24.04): the customer portal and entry point, joined to the domain with realmd/sssd.

**Decisions (2026-10-30):** the flat LAN with DHCP like Brookfield (the DMZ and Internal networks wait for
"Networks"). About 18 GB of memory, so one instance at a time. The final chain uses both
controllers: coerce dc2 → relay to dc1's certificate web enrolment (ESC8) → a certificate for dc2 → DCSync.
Other routes: a backup account with replication rights, a GPP password in SYSVOL (replicated to dc2),
and an ESC1 template. 7 flags.

**Steps:**

| Step | What | State |
|---|---|---|
| 1 | `additional-dc` extra (a general one): a second controller of a deployed domain, signing in as the first one's user (`account: dc`) | Done 2026-10-30: the e2e test passes (promotes, replicates both ways, a user made on each controller reaches the other) |
| 2 | `adcs` and `join-domain-linux` extras | Done 2026-10-31, both e2e pass. `adcs`: Enterprise Root CA + HTTP web enrolment (ESC8), needing a Netlogon-locator wait, a domain-user credential, the software KSP, and sslFlags off on Server 2025. `join-domain-linux`: realmd join via Samba (adcli hits a Server 2025 "Message stream modified" bug); Ubuntu 24.04 rebuilt with its packages; the first-boot DC branch now fixes the locator so members can find a fresh controller |
| 3 | Meridian in `labs.yaml`, its seeding extras (`meridian-dc`, `meridian-dc2`, `meridian-member`, `meridian-web`), the frontend entry | Code done 2026-10-31 (loads, unit tests pass, frontend typechecks): 5 machines wired to `@dc1`, `planned: true`. Seeding covers Kerberoast `svc_sql`, `svc_backup` DCSync rights, a GPP cpassword in SYSVOL, a best-effort ESC1 template (ESC8 comes from `adcs`), the weak workstation/SQL, and a web portal (LFI + leaked `svc_portal` + sudo→root). Live attack-chain validation is step 5 |
| 4 | Flags on the Linux machine, if `plant_flags` needs it | Done 2026-10-31: `plant_flags` now plants Linux flags too — it writes a small script to /tmp and runs it with `/bin/sh`, writing the flag as root via the user's sudo (the paths include /root), with a unix newline. test_instances covers it |
| 5 | End-to-end instance test, walking the attack path | In progress. First instance deploy found a real bug: `meridian.example` can't be a domain — Windows DNS refuses a zone under the reserved `.example` TLD (WIN32 123), so dc1 had no forward zone and dc2 couldn't find the domain. Fixed by switching to `meridian.corp` (commit 157a112). Second deploy: dc1 came up and dc2 was promoting cleanly (DNS fix worked) when testing paused for the day. **Resume:** redeploy a Meridian instance (temp-flip `planned: false` in labs.yaml, redeploy panel, `POST /api/instances`), let it finish, validate dc2 replication + sql/ws/web seeding + flags + domain joins, then walk the chain from Kali; finally mark live (commit `planned: false`, update test_labs to assert deployable). Deploy by hand — CI still down. Read fresh-DC guest logs via the API container (app.vsphere guest ops); the DCs' sshd resets connections |

### 2. The install script: clear outcomes, colours and full errors — done 2026-10-26

Asked 2026-10-26, done the same day. The offline install (`deploy/install.sh` and
`deploy/install/labinstall`, see [offline-install.md](offline-install.md)) now marks every step and
check, in colour, with verbose failures. A shared `labinstall/out.py` holds the Python side; `install.sh`
mirrors it in bash (an `ERR` trap turns any stray failure into the same form). What was built:

**Outcomes.** Every step and check ends in one of three, marked the same way in both parts:
- **Success** (green `✔ OK`): what was done, e.g. "Docker 27.3 installed from the bundle".
- **Warning** (yellow `! WARN`): it carries on, but something is left out or needs a look, e.g. a template
  skipped because its ISO is missing, or no media folder.
- **Failed** (red `✘ FAIL`): it stops, or that item is left out, and the summary at the end lists it again.

Steps get a bold heading, and details and log paths are dimmed.

**Colours only where they work.** Only when the output is a terminal, and never with `NO_COLOR` set or
`--no-color` given. The text alone still says which outcome it is, so logs and the Markdown report stay
readable without them. `docker run` gets `-t` only at a terminal, as it does now.

**Verbose errors.** Every failure says:
- what it was doing;
- what went wrong: the command or call and its exit code or exception, not just "failed";
- the end of the relevant log, inline (the last 20 or so lines), and the log's full path;
- what to do next: the likely cause and the fix, where it's known.

For example: vCenter refusing sign-in names the user and host; a bundle checksum failure names each damaged
file; a Docker install failure shows dpkg's errors. Unexpected Python exceptions print a traceback to the
log and a readable summary on screen, never a bare traceback alone.

**Also:** the final summary gives a count of each outcome and lists every warning and failure with its fix.
`--verbose` keeps its meaning (every build's output as it runs).

**Tests.** Unit tests for the output helpers (`labinstall/test_out.py`: colours on and off, `NO_COLOR`,
not a terminal, a verbose failure, the summary); shellcheck passes on `install.sh`. Not yet exercised: a
full offline install run on a server — the changes are output only, so the install's behaviour is unchanged.

### 3. A batch of services (medium, each)

Asked 2026-10-23, each with an option for example data: GitLab CE, Jenkins, Prometheus, FreeBSD,
Alpine, FreeIPA (on Rocky), ELK, Graylog, k3s, Redis, MongoDB and Tomcat.

**Done 2026-10-28:** Prometheus (with Node Exporter as its own extra), GitLab CE and Jenkins, each with
example data, and example dashboards for Grafana.

**Done 2026-10-29:** Redis, MongoDB and Tomcat, each with example data and a deliberately insecure
setting, off by default, for practising attacks (Redis with no password, MongoDB with no sign-in,
Tomcat's tomcat / tomcat). Tomcat is on 8080, so it can't go with Jenkins. All the Docker extras are on
every template with Docker, and pass their end-to-end tests on Ubuntu 26.04.

**Done 2026-10-29, later:** the rest of the batch, each passing its end-to-end tests:
- **ELK** (Elasticsearch, Logstash and Kibana 9.5.5), with Kibana's example data and this machine's
  syslog; **Send event logs to ELK** for Windows Server 2016 to 2025 and Windows 11 (Winlogbeat into
  ELK's Logstash, in its own winlogbeat-* indexes and data view);
- **Graylog** 7.2 with OpenSearch 2.19 and MongoDB 7.0 (8.x won't start on Linux 6.19 and later);
- **k3s** v1.36.5, offline, with example workloads;
- **FreeIPA** on Rocky 9 and 10, with example users, groups, sudo and access rules;
- **Alpine Linux 3.24** and **FreeBSD 15.1** templates, set up per clone like the legacy ones.

The services batch asked for on 2026-10-23 is complete.

### 3a. Docker images on CDs, not in templates — done 2026-10-29

Templates have Docker but no images. Each Docker extra's image is an ISO in the datastore's ISO folder
(`lab-image-<extra>-<tag>.iso`, made by `scripts/isos/fetch-images.sh`; 13 of them, about 4 GB). The
panel attaches a machine's at deploy, after its clean snapshot; the machine loads them and the panel
takes them out once it's set up, and a reset attaches the same ones again. A new or updated service
needs no template rebuild, and the panel marks the services that run in Docker. Templates built
before this keep their old images until they're next rebuilt. Ubuntu 26.04 rebuilt without them:
7.5 GB, down from 23.2.

**Also 2026-10-29:**
- **Trim:** `clean.sh` runs `fstrim` before the template's snapshot. Debian 12: 12.3 GB, down from
  14.0, with Prometheus and Node Exporter added.
- **Kali and Parrot** offer only web servers, FTP, Docker and Python: Kali 16.8 GB (was 25.2),
  Parrot 15.5 GB (was 18.6).
- **Deploys no longer cut off a template build:** the builder is updated once the builds finish
  (`deploy/update-builder.sh`).
- **[External resources](external-resources.md):** everything downloaded from outside, besides the
  ISOs and the OSes' own packages.

### 3b. VPN servers: WireGuard and OpenVPN — built 2026-11-10

Asked 2026-11-10, after a review of the services (the other suggestions are under "Suggested" below).
Two Linux extras in a new **VPN** category, each with one client, optionally a gateway to the LAN
(IP forwarding and NAT):
- **WireGuard** (UDP 51820): `wg-quick@wg0`, a tunnel /24 (default 10.66.0.0/24), a preshared key;
- **OpenVPN** (UDP or TCP 1194): its own CA from easy-rsa (EC keys), `dh none`, tls-crypt, a tunnel /24
  (default 10.67.0.0/24), a `.ovpn` with everything inline.

**The client config downloads from the machine page.** A new `download` field on an extra names a
file in the user's home; once the extra is ready the worker reads it through VMware Tools (as it reads
the status file) and keeps a copy in `machines.downloads`, served by
`GET /api/machines/{id}/downloads/{extra}` and shown as a button by the extra's notes. It works while
the machine is off; a reset or redeploy clears it and reads the new one (new keys). One that can't be
read is a warning, with the path to copy over SSH. The configs hold private keys, so like passwords
they're open to anyone who reaches the panel until there's sign-in.

**Templates:** offered on Ubuntu 26.04 (rebuilt for them on 2026-11-10). In `plannedExtras` (shown as
Soon) on Ubuntu 24.04, 22.04, Debian 13, 12, Kali and Parrot until each is next rebuilt. Enterprise
Linux not yet (OpenVPN needs EPEL there).

**Tested:** the backend's tests (9 new: the field's checks, keeping, serving and replacing the file, a
failed read); both scripts run in Ubuntu 26.04 containers with a real client connecting (WireGuard
from a network namespace, OpenVPN on the same host). End to end on Ubuntu 26.04 (2026-11-10): the
lifecycle and all four cases pass (WireGuard with and without the gateway, OpenVPN on UDP, and on TCP
with the gateway), each with a real client from the downloaded config. E2E cases in
`scripts/e2e/checks.py`, with a new `download` check.

**Found on the way (2026-11-10):**
- **The rebuilt Ubuntu 26.04 gave machines a user with no password.** cloud-init blanks the password
  (`passwd -d`) when `passwd -u` prints anything on stderr, and SSSD's `sss_cache` (from the Join a
  domain (Linux) packages) complains on every user change while SSSD isn't set up. The panel now sets
  the password again with `usermod -p` first thing in `runcmd`, on every Linux machine. Ubuntu 26.04
  was withdrawn meanwhile with a new setting, `BLOCKED_TEMPLATES`, and is back.
- **Ubuntu 26.04's AppArmor profile for wg-quick** lets the `nft` it runs read no files, so the
  gateway's NAT is `nft` commands in `PostUp`; and wg-quick reads configs only from `/etc/wireguard`,
  which the machine page's note now says.
- **CI works again** (the runner can clone); its backend tests needed `openssh-client`.

### 4. Keep a vCenter session open in the API — not needed (checked 2026-10-27)

This was planned because signing in to vCenter took 14 to 20 seconds, which made opening a console
take about 25 seconds. Timed again on 2026-10-27 from the panel's API container, sign-in is fast now:

| Stage | Median of 5 |
|---|---|
| TCP and TLS to vCenter | 0.01 s |
| Service content (before signing in) | 0.02 s |
| Login | 0.04 s |
| Sign-in as the panel does it (`SmartConnect`) | 0.07 s |

`/api/health` and `/api/leftovers`, which sign in and query vCenter, answer in about 0.1 s. Nothing
was changed on vCenter for this, so whatever slowed sign-in earlier has since gone (DNS lookups inside
the appliance and single sign-on are the usual causes). Sharing a session would now save a few
hundredths of a second per call, at the cost of handling expired sessions and threads, so it's
dropped. If sign-in gets slow again (or production is slow), time it the same way first: stage by
stage, from inside the `api` container.

### 5. Console on the other systems (small)

Open the console on each of these and check the screen, the keyboard, and Ctrl+Alt+Del:

| System | What to check in particular |
|---|---|
| Windows 11 | The sign-in screen and Ctrl+Alt+Del |
| Windows Server 2025 desktop | As Windows 11 |
| Windows Server 2025 Core | The text console |
| OPNsense, pfSense | Their console menus |
| Proxmox VE, TrueNAS | Their console menus and sign-in |
| VyOS | Its sign-in |
| Kali or Parrot | A desktop at a high resolution, to check scaling |
| Metasploitable 2 | An old VMware Tools version |

Fix what turns up. Add a note on the console page for any system that needs one, for example how to
sign in at the OPNsense menu.

### 6. More templates (medium, each)

| Template | Approach | Notes |
|---|---|---|
| Windows 7 | Legacy Windows build: BIOS, older unattend, no Cloudbase-Init support for the newest versions | ISO from Jake |
| Windows 10 | Jake's ISO is in the datastore as `windows-10-22h2-19045.2965-consumer-x64.iso` (Home, Education, Pro; no Enterprise): build Pro with `packer/windows -var version=10`, set up with Microsoft's public setup key for Pro. Never delete that ISO: it can't be downloaded again | Waits for disk space |

Each follows the usual path: `packer/<name>`, ISO in `scripts/isos/isos.txt`, entry in
`templates.yaml`, e2e tests, commit.

### 7. Capacity warnings (small)

Alerts on the panel's Admin page, and refusal to deploy, when one of these runs low:
- the datastore (done: deploys keep `DATASTORE_RESERVE_GB` free);
- the disk of the PC hosting ESXi;
- the LAN's DHCP pool.

Those three caused most outages so far. The last two need a way to read them: an agent or a check on
the PC, and the DHCP server's lease count.

### 8. Templates on demand (medium) — step 1 built 2026-10-28

Delete a template nobody uses from the Admin page and keep its ISO; the next deploy builds it again
first. A template takes about five times its ISO's space. Design: [plan.md](plan.md#11-templates-on-demand).
Step 1 (deleting by hand, building on deploy or with Build) is built; step 2, flagging templates
unused for 30 days and deleting them after a week unless kept, comes once step 1 has proved itself.

### 9. Packet capture and the network diagram (medium-large) — done 2026-10-30

Asked 2026-10-30. Design: [plan.md section 12](plan.md#12-packet-capture-and-the-network-diagram);
setup: [admin guide section 13](admin-guide.md#13-packet-capture).

**Decisions (Jake, 2026-10-30):** a capture appliance (not `pktcap-uw` on ESXi over SSH), and a live
table in the browser plus a .pcap download.

**Built:**
- **The Network page** (`/network`): your machines on the LAN, grouped by lab instance, to select
  for a capture; the machines that talked are linked on it, thicker for more traffic. Machine and
  instance pages link to it.
- **Captures**: between the selected machines, across a subnet, or with your own BPF filter, with
  presets (DNS, HTTP, TLS, SSH, SMB, Kerberos, LDAP, RDP, ICMP, ARP). Always limited to the chosen
  machines' MAC addresses. A live table (find, pause), Stop, Download .pcap, and past captures kept for
  a day. Limits: 10 minutes, 50 MB, one per person, three at once.
- **The appliance**: `packer/capture` (Alpine, tcpdump; the second adapter listens on `LAN-capture`),
  `scripts/capture/lab-capture` (the only command the panel's key may run), and
  `scripts/setup_capture.py` for the port group and folder. Admin → Packet capture shows whether it
  answers and the panel's public key.

**In the lab:** `LAN-capture` on vSwitch0 (VLAN 0, promiscuous) and `Labs/Capture` from
`scripts/setup_capture.py`; `lab-capture` built (about 2.5 minutes) and running, with
`CAPTURE_VM=Labs/Capture/lab-capture` on the panel.

**Tested:** the backend's tests, with a stand-in appliance (16 new: parsing, scope, owners, a bad
filter, live and stop, the size limit, cleanup); `lab-capture` in an Alpine container with tcpdump. End
to end on the panel, between two Alpine machines (15 checks, all passing):
- a bad filter is refused with tcpdump's message;
- ICMP between the two: all 5 echo requests and replies arrive in the live view, and nothing else;
  Stop records it; the .pcap downloads whole and opens in tcpdump; the table is read back from the file;
- HTTP between them: the handshake and `GET /index.html` are seen;
- scope: a capture of the two with the filter `host <vCenter>` gets nothing while vCenter is busy;
- someone else's name is refused (403); a 10-second capture stops at its time limit;
- the diagram links the two machines for an opened capture.

**Not yet tried:** a Brookfield instance (Kerberos between the workstation and the domain controller
during sign-in), and Windows machines.

### Suggested, not yet scheduled

- **Exercises** (planned 2026-10-27, not started): guided tasks on one to three machines, checked by the
  panel, starting with an iptables track. The design and catalogue are in [plan.md](plan.md#10-exercises);
  its open questions wait on Jake.
- **Mail:** Mailpit (a mail catcher for apps) and GoPhish (phishing exercises), both small Docker
  extras; Mailcow for a realistic organisation mail server.
- **From the services review (2026-11-10)**, in rough order:
  - VPN and remote access: strongSwan IPsec site-to-site (two machines, each picking the other),
    FreeRADIUS (for OpenVPN and the firewalls), later Headscale;
  - network services: a DNS server (being planned next), Samba file shares, Squid, HAProxy, OpenLDAP,
    Keycloak. Not a DHCP server until per-user networks: on the flat LAN it would fight the lab's own;
  - blue team: Suricata and Zeek into ELK or Graylog, Velociraptor (server and client), OpenVAS only
    where there's internet for its feeds;
  - practice targets (small Docker extras): WebGoat, crAPI, DVGA, Mutillidae II, bWAPP.
- **More Docker services:** Jake to pick the ones that matter most to learners.
- **Wazuh and Zabbix agents on Windows;** Wazuh's vulnerability detection as an option where there's
  internet and disk.
- **The rest of the [project review](review-2026-10-23.md):** user snapshots, bulk actions, extras'
  scripts out of `extras.yaml`, a single template catalogue, and the smaller fixes it lists.

## Later

- **Other platforms:** how hard it would be to run the panel on a standalone ESXi host (no vCenter) or
  on Nutanix (AHV, through Prism's API) instead of vCenter.
- **Sign-in:**
  - accounts, owners and admins;
  - limit consoles and passwords to a machine's owner and admins;
  - replaces the name people type today.
- **Networks:** VLANs or a network per user or lab, then a WireGuard VPN to reach them (the "Download
  VPN config" button on machine pages is a placeholder for this). The gateway could be the small Debian
  VM in [plan.md](plan.md#2-lab-architecture-on-vsphere), or OPNsense as router and WireGuard server
  (Jake's suggestion; it already has a template). Exercises' routing and appliance tracks need this.
- **Health tasks:** a periodic check that templates still deploy, and evaluation licences
  (Windows 11 lasts 90 days) are rebuilt in time.
- **Nested ESXi:** the ISO needs a Broadcom login; Jake may supply it.
- **Older releases:** Windows Server 2008 R2 (Jake to supply the ISO) and Parrot 6 (from Parrot's archive). Windows Server 2016 and 2012 R2 are done (2026-10-28).

## The lab today

- **Datastore:** datastore1, 583.5 GB over two extents, 89 GB free on 2026-10-29, with every ISO a
  recipe needs and the 13 image ISOs, after Jake deleted unused templates. The PC's own free disk is the real limit.
- **Memory:** the panel counts 46 GB with overcommit; vCenter uses 14 GB of it.
- **Deploys:** at most 2 or 3 test machines at once.
- **Limits on what Claude may do in the lab:**
  - never power off, snapshot or change the vCenter VM;
  - delete VMs only in `Labs/`, and datastore files only in `ISO/` and `tpl-*` folders;
  - anything outside the lab is Jake's decision;
  - Office and SQL Server media never go in the repository.
