# Roadmap

Where lab-deploy stands and what comes next. Last updated 2026-10-20. The original design is in
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
| Debian | 13, 12 |
| Enterprise Linux | Rocky 10, 9 and 8; AlmaLinux 10, 9 and 8; CentOS Stream 9; CentOS 7 |
| Windows Server | 2025 (desktop and Core), 2022, 2019 |
| Windows | 11 Enterprise (90-day evaluation; TPM checks skipped) |
| Security | Kali 2026.2, Parrot 7.4 |
| Firewalls and routers | OPNsense 26.7, VyOS (rolling) |
| Practice targets | Metasploitable 2 and 3 (Linux), as complete images |

**Extras:** web servers, WordPress, Nextcloud, databases with sample data, mail, FTP, desktop and
RDP, IIS, SQL Server, Outlook. Also Docker, with Juice Shop, DVWA, Uptime Kuma, Vaultwarden, Gitea
and Grafana baked into the templates so they work offline.

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

## Waiting on Jake

| Item | What's needed | Then |
|---|---|---|
| Windows 10 | The ISO in the datastore's `ISO/` folder (Enterprise LTSC 2021 or 22H2, x64, en-US), its file name, and a key if it isn't an evaluation | Build with `packer/windows` (as Windows 11, `version = "10"`), run the e2e tests, add it to `templates.yaml` |
| Firefox black screen | Testing on the one affected Firefox: without extensions, then with `privacy.resistFingerprinting` off. Canvas blockers stop the screen drawing | A fix if it isn't the browser's settings |
| Workstation snapshot | Delete the snapshot of the ESXi VM taken before the datastore was extended | — |
| `parrot-base-7.4` | Choose: convert it to a vSphere template (recommended; it stays, for Parrot rebuilds) or delete it (frees 12.7 GB; rebuilding then means re-importing the OVA) | One line in `packer/parrot/import-base.sh` so new bases are templates |
| Off-host backups | Somewhere to copy the daily database dump: a network share or another machine | A copy job in `deploy/compose.yaml` |

## Next, in order

### 1. Keep a vCenter session open in the API (small)

**Why.** The panel signs in to vCenter for each request, and on this vCenter that takes 14 to 20
seconds. Opening a console therefore takes about 25 seconds, and the health and capacity checks are
just as slow.

**How.**
- The API keeps one signed-in session and shares it between requests.
- It signs in again when the session has expired (vCenter's default idle limit is 30 minutes) or
  vCenter has restarted.
- A lock keeps two requests from signing in at once.
- The job worker keeps signing in per job: jobs take minutes, so it matters less there.

**Tests.** With vcsim:
- the session is reused;
- an expired session is replaced;
- a vCenter restart is survived.

**Done when:** opening a console takes a few seconds, and `/api/health` answers in under a second.

**Separately:** find out why sign-in is slow on this vCenter. DNS lookups inside the appliance or
single sign-on are the usual causes. Production may not have the problem.

### 2. Console on the other systems (small)

Open the console on each of these and check the screen, the keyboard, and Ctrl+Alt+Del:

| System | What to check in particular |
|---|---|
| Windows 11 | The sign-in screen and Ctrl+Alt+Del |
| Windows Server 2025 desktop | As Windows 11 |
| Windows Server 2025 Core | The text console |
| OPNsense | Its console menu |
| VyOS | Its sign-in |
| Kali or Parrot | A desktop at a high resolution, to check scaling |
| Metasploitable 2 | An old VMware Tools version |

Fix what turns up. Add a note on the console page for any system that needs one, for example how to
sign in at the OPNsense menu.

### 3. Active Directory domain (large)

**Goal.** Deploy a working Windows domain from the panel: a domain controller, then members that
join it.

**Approach.**
- **Domain controller:**
  - Windows Server 2025 (desktop or Core) gets a "Domain controller" extra.
  - Options: the domain name (default `lab.example`), the NetBIOS name, and the Directory Services
    Restore Mode password (default: the machine's password).
  - At first boot it installs AD DS and DNS and creates the forest. The machine restarts, and the
    deploy waits until the domain answers.
- **Members:**
  - Other Windows machines get a "Join a domain" extra: choose a domain controller from your
    running machines.
  - The panel sets the member's DNS to the controller's address, joins it with the controller's
    credentials, and restarts it.
- **Linux members (later):** realmd/sssd join, as an option on the Linux templates.
- **Panel:** show the domain and how to sign in (`LAB\user`) on both machines' pages. Reset and
  redeploy of the controller must warn that members lose their trust.

**Open questions:**
- One domain per person, or shared domains?
- What happens to members when their controller expires or is destroyed: expire together, or warn?
- Are AD Certificate Services wanted as an option?

**Done when:** a controller and a Windows 11 member deploy from the panel, a domain user signs in on
the member, and the e2e tests cover it.

### 4. More templates (medium, each)

| Template | Approach | Notes |
|---|---|---|
| Proxmox VE 9 | Unattended install (Proxmox's answer file), nested virtualisation switched on in the VM | Needs "expose hardware virtualisation" on the VM, and more memory |
| MikroTik CHR 7 | Complete image (image family): import the official VMDK | Free licence is speed-limited to 1 Mbit/s, fine for labs |
| TrueNAS SCALE | Unattended install is limited: as Parrot, import once, then automate | Needs a second disk for a pool |
| TrueNAS CORE | As SCALE, on FreeBSD (like OPNsense's tooling) | End of life; only if wanted for practice |
| Debian 8 to 11 | The Debian builds with older preseeds; the legacy family for 8 and 9 | Archive mirrors for old releases |
| Windows 7 | Legacy Windows build: BIOS, older unattend, no Cloudbase-Init support for the newest versions | ISO from Jake |
| Windows 10 | See "Waiting on Jake" | — |

Each follows the usual path: `packer/<name>`, ISO in `scripts/isos/isos.txt`, entry in
`templates.yaml`, e2e tests, commit.

### 5. ProLabs: the first multi-machine lab (large)

**Goal.** A lab of several machines deployed together on a network of their own, as the LMS's Pro Lab
pages describe.

**First lab.** Kept simple: two Windows Servers (a domain controller and a member server) and one
Windows workstation, with deliberate Active Directory weaknesses. Draw these from the
`/home/user/coding/vuln-ad` project:
- Kerberoasting
- AS-REP roasting
- weak ACLs
- DNSAdmins
- passwords in descriptions
- default passwords and password spraying
- DCSync
- silver and golden tickets
- pass-the-hash and pass-the-ticket
- SMB signing off

**Builds on:**
- the AD domain feature (item 3);
- a lab definition format (machines, roles, network, which weaknesses);
- deploy and reset of the whole lab as one unit (snapshot revert per machine);
- a network per lab instance, which needs VLANs or port groups (see "Later").

**Open questions:** shared instance or one per person? How are learners reached: VPN, or the
browser console only, to start with?

### 6. Capacity warnings (small)

Alerts on the panel's Admin page, and refusal to deploy, when one of these runs low:
- the datastore;
- the disk of the PC hosting ESXi;
- the LAN's DHCP pool.

Those three caused most outages so far. The datastore is already checked before deploys. The other
two need a way to read them: an agent or a check on the PC, and the DHCP server's lease count.

## Later

- **Sign-in:**
  - accounts, owners and admins;
  - limit consoles and passwords to a machine's owner and admins;
  - replaces the name people type today.
- **Networks:** VLANs or a network per user or lab, then a VPN to reach them (the "Download VPN
  config" button on machine pages is a placeholder for this).
- **Health tasks:** a periodic check that templates still deploy, and evaluation licences
  (Windows 11 lasts 90 days) are rebuilt in time.
- **pfSense:** its installer now needs the internet and an account; revisit if that changes.
- **Nested ESXi:** the ISO needs a Broadcom login; Jake may supply it.
- **Exchange:** heavy, with licensing to work out.
- **Older releases:** CentOS 6 and 8, Windows Server 2008 R2 to 2016, Parrot 6, and the Windows
  variant of Metasploitable 3. Jake has offered ISOs.

## The lab today

- **Datastore:** datastore1, 583.5 GB over two extents, about 265 GB free on 2026-10-19. The PC's
  own free disk is the real limit.
- **Memory:** the panel counts 46 GB with overcommit; vCenter uses 14 GB of it.
- **Deploys:** at most 2 or 3 test machines at once.
- **Limits on what Claude may do in the lab:**
  - never power off, snapshot or change the vCenter VM;
  - delete VMs only in `Labs/`, and datastore files only in `ISO/` and `tpl-*` folders;
  - anything outside the lab is Jake's decision;
  - Office and SQL Server media never go in the repository.
