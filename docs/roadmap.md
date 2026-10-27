# Roadmap

Where lab-deploy stands and what comes next. Last updated 2026-10-27. The original design is in
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
| Windows Server | 2025 (desktop and Core), 2022, 2019 |
| Windows | 11 Enterprise (90-day evaluation; TPM checks skipped) |
| Security | Kali 2026.2, Parrot 7.4 |
| Firewalls and routers | OPNsense 26.7, pfSense CE 2.7.2, VyOS (rolling), MikroTik CHR 7.24 and 6.49 |
| Hypervisors | Proxmox VE 9.2, 8.4, 7.4; XCP-ng 8.3 (all nested) |
| Mail | Exchange Server SE (its own template; joins a domain controller's domain), Zimbra 8.8.15 |
| Storage | TrueNAS SCALE 25.10, TrueNAS CORE 13.3 |
| Practice targets | Metasploitable 2 and 3 (Linux), Metasploitable 3 (Windows; shuts down hourly), as complete images |

**Extras:** web servers (Apache with a choice of PHP 5.6 to 8.5 on Ubuntu 22.04 and 24.04),
WordPress, Nextcloud, databases with sample data, mail (and iRedMail), FTP, desktop and RDP, IIS,
SQL Server, Outlook, MinIO, Python versions (2.7 and 3.8–3.15). Docker, with Juice Shop, DVWA,
Uptime Kuma, Vaultwarden, Gitea and Grafana baked into the templates so they work offline. Wazuh and
Zabbix, each as a server and an agent that picks its server machine and registers itself.

**Active Directory** (finished 2026-10-20). Two extras:
- **Domain controller** (Windows Server): installs AD DS and DNS and creates a new forest; the machine's
  user becomes a domain administrator.
- **Join a domain** (all Windows): pick a running domain controller from your machines; the panel
  passes its address and sign-in to the join, keeping only its id. This is a new kind of option,
  "machine", that other features can reuse.
- Tested live: a Server 2025 controller and a Server 2025 Core member, with the controller's user
  signing in to the member as a domain user.

**Browser console** (finished 2026-10-19). Open console on a machine's page shows its screen, keyboard
and mouse in the browser.
- **How it works:** the panel gets a WebMKS ticket from vCenter and relays the stream from ESXi.
  noVNC shows it.
- **Buttons:** Ctrl+Alt+Del, Type password, full screen, reconnect.
- **Access:** open to everyone for now; to be limited once there's sign-in (see below).
- **Tested:** in Chrome and Firefox with Ubuntu 26.04.
- **Known behaviour:**
  - ESXi closes a console when it gets a WebSocket ping, so the relay sends none.
  - ESXi presses the key a character is on without Shift, so Type password holds Shift itself
    (US layout).
  - The ticket path only works if the API runs as a single process.

**Also done:**
- OS and distribution logos on the catalogue, the deploy page, the machines list and machine pages.
- The offline install: [offline-install.md](offline-install.md).
- **Long jobs can't hold up the sweep** (2026-10-27). Deploys, redeploys and resets run on the worker's
  `default` queue; the per-minute sweep and quick actions (start, stop, reboot, expire, destroy) on a
  `quick` queue, served by a second worker, `sweeper`. Before, four long deploys (Exchange takes about an
  hour) filled every slot, and expiry, lost-job recovery and a lab's next machines waited for them.
- The [project review of 2026-10-23](review-2026-10-23.md): its five top priorities (a datastore
  reserve, machines that depend on each other, cancelling a stuck job, expired machines out of the
  quota, capacity on the deploy form). The rest is kept for later.

## Waiting on Jake

| Item | What's needed | Then |
|---|---|---|
| Windows 10 | The ISO in the datastore's `ISO/` folder (Enterprise LTSC 2021 or 22H2, x64, en-US), its file name, and a key if it isn't an evaluation | Build with `packer/windows` (as Windows 11, `version = "10"`), run the e2e tests, add it to `templates.yaml` |
| Windows 7 | The ISO, as for Windows 10 | A legacy Windows build (see "More templates") |
| vuln-ad fixes | A yes to push the fixes to `workstation/vuln-workstation.ps1`, committed locally in the vuln-ad repo | Push to `jake/vuln-ad` |
| Firefox black screen | Testing on the one affected Firefox: without extensions, then with `privacy.resistFingerprinting` off. Canvas blockers stop the screen drawing | A fix if it isn't the browser's settings |
| Workstation snapshot | Delete the snapshot of the ESXi VM taken before the datastore was extended | — |
| `parrot-base-7.4` | Choose: convert it to a vSphere template (recommended; it stays, for Parrot rebuilds) or delete it (frees 12.7 GB; rebuilding then means re-importing the OVA) | One line in `packer/parrot/import-base.sh` so new bases are templates |
| Off-host backups | Somewhere to copy the daily database dump: a network share or another machine | A copy job in `deploy/compose.yaml` |

## Next, in order

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
  about 90 GB and keeps them current, at the cost of a long deploy (Exchange is about 2.5 hours). The
  members join the instance's own domain controller through `@dc` (cross-machine extra wiring).
- **Network:** the LAN with DHCP for now; members use the domain controller for DNS. A network per
  instance comes with "Networks" (see "Later").
- **Size:** about 18 GB of memory, so one instance at a time. **Disk:** about 75 GB while it deploys
  (Exchange's install growth), which is more than the lab's datastore has free — see the blocker below.
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
| Windows 10 | See "Waiting on Jake" | — |

Each follows the usual path: `packer/<name>`, ISO in `scripts/isos/isos.txt`, entry in
`templates.yaml`, e2e tests, commit.

### 7. Capacity warnings (small)

Alerts on the panel's Admin page, and refusal to deploy, when one of these runs low:
- the datastore (done: deploys keep `DATASTORE_RESERVE_GB` free);
- the disk of the PC hosting ESXi;
- the LAN's DHCP pool.

Those three caused most outages so far. The last two need a way to read them: an agent or a check on
the PC, and the DHCP server's lease count.

### Suggested, not yet scheduled

- **Exercises** (planned 2026-10-27): guided tasks on one to three machines, checked by the panel, starting
  with an iptables track. The design and catalogue are in [plan.md](plan.md#10-exercises).
- **Mail:** Mailpit (a mail catcher for apps) and GoPhish (phishing exercises), both small Docker
  extras; Mailcow for a realistic organisation mail server.
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
- **Networks:** VLANs or a network per user or lab, then a VPN to reach them (the "Download VPN
  config" button on machine pages is a placeholder for this).
- **Health tasks:** a periodic check that templates still deploy, and evaluation licences
  (Windows 11 lasts 90 days) are rebuilt in time.
- **Nested ESXi:** the ISO needs a Broadcom login; Jake may supply it.
- **Older releases:** Windows Server 2008 R2 to 2016 and Parrot 6. Jake has offered ISOs.

## The lab today

- **Datastore:** datastore1, 583.5 GB over two extents, about 73 GB free on 2026-10-24. The PC's
  own free disk is the real limit.
- **Memory:** the panel counts 46 GB with overcommit; vCenter uses 14 GB of it.
- **Deploys:** at most 2 or 3 test machines at once.
- **Limits on what Claude may do in the lab:**
  - never power off, snapshot or change the vCenter VM;
  - delete VMs only in `Labs/`, and datastore files only in `ISO/` and `tpl-*` folders;
  - anything outside the lab is Jake's decision;
  - Office and SQL Server media never go in the repository.
