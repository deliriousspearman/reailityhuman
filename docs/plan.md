# Pro Lab Deployment Platform ("lab-deploy") — Plan

## Context

The LMS (`/home/user/coding/lms`) already advertises Pro Labs (`src/content/docs/labs/meridian.md`, `harbourside.md`). Each page lists machines, OS, roles and network segments, and tells learners to "submit flags on the lab platform" and that "the lab is reset regularly". That platform doesn't exist yet. `lab-deploy` is it: a web panel that deploys, resets and tears down Pro Lab environments on on-prem VMware vSphere and gives learners network access.

Constraints and decisions so far:
- **LAN-only / air-gapped runtime:** dependencies are downloaded online, then moved across as a bundle.
- **Tenancy:** both **shared** instances (one per lab, HTB-style) and **dedicated** instances (per user or team, on demand).
- **Scope:** deploy and control only. No flag scoring or leaderboard for now, but the data model should leave room to add them.
- **vSphere edition:** unknown. Plan for vCenter with Standard/Distributed vSwitch as the baseline, and keep networking behind an adapter so NSX can be added later.
- **Look and feel:** match the LMS "Hacklab" theme.
- **Greenfield:** `/home/user/coding/lab-deploy` is empty.

---

## 1. Software stack options

### Backend / orchestration (the key choice, because it drives the vSphere integration)

| Option | Pros | Cons |
|---|---|---|
| **A. Python 3.12 + FastAPI + pyVmomi** (recommended) | pyVmomi is VMware's official SDK with full vim API coverage (linked clones, snapshots, dvPortgroups, guest operations). Large ecosystem and easy to read. Shares the language of the tooling used to build templates (Packer + Ansible). Can be tested against **vcsim**, the vCenter simulator. | Deploying offline means shipping a wheelhouse or container image. Slower than Go (irrelevant here, since vCenter is the bottleneck). |
| **B. Go + govmomi** | govmomi is the best vSphere library there is (Terraform's provider uses it, and vcsim comes from the same project). Builds to a **single static binary**, which is ideal for offline transfer. Strong concurrency for parallel clones. | Building the web/API layer takes longer. Fewer people can maintain it, and it's a different language from the LMS (TypeScript). |
| **C. TypeScript (Node) + vSphere REST API** | Same language as the LMS, so theme code can be shared directly. | **No good vSphere SDK for Node.** The REST (Automation) API doesn't cover everything a lab platform needs (e.g. linked clones and some snapshot and network operations), so you'd end up writing SOAP calls by hand. Not recommended. |
| **D. OpenTofu/Terraform (vsphere provider) driven by an app** | Topologies are declared in code, and plan/apply shows what will change. | Each instance needs its own state file. Slow for "reset" (reset becomes destroy and recreate instead of a snapshot revert, taking minutes instead of seconds). Air-gapped setups need a provider mirror. Useful for **building the platform itself**, a poor fit for resetting instances repeatedly. |
| **E. Existing products** | — | **Ludus** is Proxmox-only. **KYPO/CyberRange** needs OpenStack. **VMware Cloud Director** (vApps with fenced networks do exactly this) is now effectively licensed only to cloud providers under Broadcom. None fit vSphere on-prem, so building our own is justified. |

**Recommendation: A (Python/FastAPI/pyVmomi).** Go (B) is a close second if you want a single-binary deployment.

### Supporting pieces (recommended)
- **Database: PostgreSQL 16.** Holds instances, jobs, users and the audit log. (SQLite is fine for a proof of concept, but the job worker and API write at the same time.)
- **Job queue: Procrastinate**, a queue that runs inside Postgres. It avoids adding Redis, so there's one component fewer to ship offline. Deploy and reset operations take minutes and must run as background jobs with progress reporting.
- **ORM and migrations:** SQLAlchemy 2 + Alembic.
- **Frontend: SvelteKit with `adapter-static`, in TypeScript.** It builds to static files served by Caddy, with live status via Server-Sent Events. Styling reuses the LMS Hacklab tokens (see §5).
  - *Alternatives:* Jinja + htmx (no Node build, fewer moving parts, less polished interactive dashboards), or Astro SSR (same framework as the LMS, but Starlight is built for docs sites, not apps).
- **Reverse proxy: Caddy with `tls internal`,** the same as the LMS (`lms/deploy/Caddyfile`).
- **Packaging: Docker Compose** (caddy, api, worker, postgres). Images are built online, exported with `docker save`, and imported offline with `docker load`.
  - *Alternative:* systemd services plus a setup script, in the style of the LMS's `deploy/setup-server.sh`. Offline, that means shipping wheels and apt packages by hand, which is more painful.
- **Lab gateway VM:** a minimal Debian template with WireGuard, nftables and dnsmasq, built with **Packer** and exported as an OVA.
  - *Alternatives:* OPNsense (has a GUI and REST API, but is heavier and harder to template) or VyOS (its LTS images need a subscription).

## 2. Lab architecture on vSphere

```
Learner PC ──LAN──► [lab-access port group (routable on the LAN)]
                             │ WAN (IP assigned by the panel)
                     ┌───────┴────────┐
                     │ Gateway VM      │  WireGuard, nftables, per-peer rules
                     │ (one per        │  (infrastructure, out of scope for attacks)
                     │  instance)      │
                     └──┬────────┬─────┘
          VLAN seg A ───┘        └─── VLAN seg B      ← isolated port groups for this instance
          (e.g. Perimeter)            (e.g. Office)
          SHOP  GATE                  DEV  NAS  POS01  NVR   ← linked clones of template snapshots
```

- **Each instance is a vCenter folder plus a resource pool,** e.g. `ProLabs/Instances/harbourside-shared/`, holding **linked clones** of versioned templates (e.g. `ProLabs/Templates/harbourside/v3`). Clones take seconds and use little disk.
- **The IPs inside a lab are the same in every copy.** Each instance sits behind its own gateway, so clones are byte-identical and don't need re-IPing or sysprep, and AD keeps working.
- **Network pool (baseline, no NSX):**
  - v1 uses a set of **pre-created "slot" port groups** (e.g. `lab-slot-01-seg-a`, …), each on its own VLAN, which the panel assigns and recycles. The vCenter service account then needs fewer privileges, and behaviour is predictable.
  - v2 adds creating dvPortgroups on the fly from a VLAN range.
  - Multi-host clusters need a **Distributed vSwitch** (a higher vSphere licence) or identical standard port groups on every host, and the physical uplinks must trunk the lab VLANs. A single host can use internal-only vSwitches with no uplink.
- **NSX adapter (later):** implements the same `NetworkProvider` interface by creating segments and Tier-1 gateways for each instance.
- **Management isolation:** lab segments must have no route to vCenter, ESXi management or the panel. The panel's vCenter account uses a custom role limited to the `ProLabs` folder, resource pool, datastore and port groups.

### Should learners use a VPN or a DHCP address on the LAN?
Use **WireGuard**, even on a LAN-only network. A flat DHCP network where learners get a lab IP has four problems:
1. **Dedicated copies stop working,** because identical lab IP ranges can't coexist without a gateway in front of each copy.
2. **The real LAN is exposed:** AD lab techniques such as LLMNR/NBT-NS poisoning (Responder), ARP spoofing and rogue DHCP would spill onto it, and intentionally vulnerable hosts would be reachable from it.
3. **There's no identity or expiry.** WireGuard peers belong to a user and an instance, and the panel can revoke them the moment access ends.
4. **Learners can't be kept apart.** The gateway blocks traffic between learners on shared instances.

For learners the cost is small: download a `.conf` from the panel and import it into the WireGuard client. For people who can't install a client, add an **in-browser attack box (Apache Guacamole to a Kali VM)** later.

## 3. Web panel features

### MVP
- **Lab catalogue:** labs from manifest files, shown with the same card, difficulty and machine-list style as the LMS.
- **Instance lifecycle:** **Deploy** (clone, attach networks, power on in boot order, then take a baseline snapshot), **Start/Stop**, **Destroy**. Each runs as a job with a live progress log.
- **Restart and reset. Yes, this is fully possible from the panel:**
  - **Reset lab:** revert every VM to its baseline snapshot and power on in boot order. This takes seconds to a couple of minutes.
  - **Reset machine:** revert one VM (HTB's "reset box").
  - **Reboot / power cycle** a machine that has hung.
  - **Rebuild:** destroy and re-clone, for when an instance is corrupted or a template has changed.
  - **Shared instances:** only admins and instructors can reset. The reset is announced first (e.g. "reset in 5 min" banner) and **scheduled resets** can be set up (e.g. nightly cron).
  - **Dedicated instances:** the owner can reset whenever they like.
- **Access:** per-user WireGuard config for each instance (QR code and download), which is revoked automatically when the instance is destroyed or expires.
- **Dedicated instances:** quotas (maximum per user, maximum concurrent across the platform), a **TTL with auto-expiry** and an "extend" button, and a capacity check against the resource pool before deploying.
- **Users and roles:** local accounts with Admin, Instructor and Learner roles (OIDC via the LMS's GitLab is an optional later addition).
- **Admin dashboard:** every instance with its state and uptime, capacity (CPU, RAM, datastore), the job queue, and failed jobs with retry.
- **Audit log:** who deployed, reset or destroyed what, and when.
- **Health checks:** VMware Tools heartbeat and a ping sweep from the gateway, shown as machine status dots.

### Later
- Learners vote for a reset on shared labs (HTB-style).
- Admin-only in-browser VM console through vSphere WebMKS tickets or Guacamole.
- Guacamole attack box.
- NSX adapter.
- GitLab OIDC.
- Flag submission, progress and leaderboards.
- A template manager: import an OVA, snapshot it as `clean`, bump its version.
- Deep links from LMS lab pages.

## 4. Limitations and risks to plan around
- **vCenter is required.** Standalone ESXi (free or unmanaged) exposes a read-only or limited API, so it can't be automated properly. **Confirm the vCenter version and licence edition first.** The edition decides whether dvSwitch and DRS are available.
- **Capacity:** a lab like Harbourside (six VMs, mixed OS) needs roughly 16–32 GB RAM for each copy. Shared plus dedicated copies multiply that, so quotas, TTLs and capacity checks are essential.
- **Linked clones pin their template snapshot.** You can't change a template while instances depend on it, so templates are versioned (v1, v2…) and old versions retire once no instances use them.
- **Resetting part of an AD lab:** reverting one domain member without the DC can break the machine account secure channel, and reverting the DC alone rolls back AD state.
  - Mitigations: reset domain labs as a whole by default; set the "disable machine account password changes" GPO in templates; and make the DC the time source to avoid Kerberos clock-skew problems after a revert.
- **Windows licensing offline:** evaluation ISOs expire after 180 days, and there's no internet activation. You'll need KMS or volume licensing, or to rebuild templates before they expire.
- **Shared-instance resets disrupt everyone** connected at the time, so resets need announcements and schedules.
- **One WireGuard lab connection at a time per learner:** every copy of a lab uses the same IP ranges.
- **Browser VM consoles** need the browser to reach ESXi hosts directly (WebMKS), which is awkward on segregated networks. That's why they're deferred and admin-only.
- **Keeping the air-gapped server updated:** each release is a new offline bundle (images, OVAs, checksums). No automatic updates.
- **LMS CSP:** LMS pages can only **link** to the panel, not fetch from or embed it (`lms/scripts/csp.mjs`, and `X-Frame-Options DENY` in the Caddyfile). Plain links are enough.

## 5. Design consistency with the LMS
- **Port the "Hacklab" tokens** from `lms/src/styles/custom.css:12-74` (dark by default; light with `:root[data-theme='light']`):
  - Dark backgrounds `#111927`, `#141d2b`, `#1a2332`, `#202c3f`.
  - Lime accent `#9fef00`, with `#c5f467` for the high variant and `#2a3d12` for the low variant.
  - Difficulty colours: easy `#9fef00`, medium `#ffaf00`, hard `#ff3e3e`.
  - Put them in `frontend/src/lib/styles/tokens.css` with the same `--lms-*` names, so they can move into a shared package later.
- **Same self-hosted fonts through @fontsource:** Chakra Petch 500/700 for headings, Figtree Variable for body text, JetBrains Mono Variable for code and logs. No CDN.
- **Reuse the LMS patterns:**
  - Top header with a light/dark toggle.
  - Collapsible left sidebar (`lms/src/components/CourseToolbar.astro`, `lms/src/scripts/sidebar-toggle.ts`).
  - Cards with square pictures and pill chips (`custom.css:~790-850`).
  - The fake-terminal hero, reused for job logs.
  - The lab machine table from `LabDetails.astro`.
  - Corners rounded 6–10px, and inline SVG icons (no icon library, which keeps it offline).
- **Reuse lab identity:** the manifest slug matches the LMS page slug (`labs/<slug>.md`), and pictures are copied from `lms/public/images/labs/`. LMS lab pages can link to `https://<panel>/labs/<slug>`.
- **Follow the LMS conventions:** documentation IP ranges and `.example` domains in committed examples, and no personal information.

## 6. Proposed repo layout (`/home/user/coding/lab-deploy`)
```
backend/app/{api,models,jobs,vsphere,network,access,auth}/   FastAPI + worker
backend/tests/                                               pytest, runs against vcsim
frontend/                                                    SvelteKit (static), Hacklab theme
labs/<slug>/lab.yaml                                         deployment manifests
gateway/                                                     Packer + scripts for the gateway VM
deploy/{compose.yaml,Caddyfile,bundle.sh,install.sh}        offline bundle and install
docs/                                                        admin runbook, template authoring guide
```

**Example lab manifest (`labs/harbourside/lab.yaml`):**
```yaml
slug: harbourside            # matches lms/src/content/docs/labs/harbourside.md
templateVersion: v3
resetScope: lab              # lab | machine (domain labs → lab)
networks:
  - { name: Perimeter, cidr: 10.10.110.0/24, gateway: 10.10.110.1 }
  - { name: Office,    cidr: 10.10.120.0/24, gateway: 10.10.120.1 }
entry: Perimeter
machines:
  - { name: GATE, template: harbourside-gate, nics: [Perimeter, Office], bootOrder: 1 }
  - { name: SHOP, template: harbourside-shop, nics: [Perimeter], bootOrder: 2 }
  # ...
resources: { cpu: 12, memoryGB: 24 }   # used by the capacity check
```

## 7. Delivery phases
0. **Discovery and dev environment:**
   - Confirm the vCenter version and licence, the switch type, a free VLAN range, datastore and capacity, and whether NSX is present.
   - Stand up a `vmware/vcsim` container for local development.
   - Build a tiny two-VM Alpine test lab plus the gateway template on the real cluster.
1. **Core engine:**
   - Manifest schema and validation (optionally checked against the LMS frontmatter).
   - `vsphere` adapter: clone, reconfigure NIC, power, snapshot, revert, destroy, capacity queries.
   - `NetworkProvider` using slot port groups.
   - Job worker and instance state machine.
2. **Access:** gateway VM configuration (pushed through vSphere Guest Operations or cloud-init `guestinfo`), WireGuard peer issuing and revoking, nftables isolation.
3. **Panel UI:** catalogue, instance page (machines, status, reset, reboot, config download), admin dashboard, job logs over SSE, Hacklab theme.
4. **Multi-tenancy and operations:** dedicated instances, quotas, TTL expiry, scheduled resets with announcements, audit log, local auth and roles.
5. **Offline packaging:** a `bundle.sh` that produces image tarballs, the gateway OVA, a Python wheelhouse, a checksum manifest and an install runbook.

## 8. Verification
- **Unit and integration tests (pytest)** run the vSphere adapter and job flows against **vcsim**: deploy, reset, destroy, and slot allocation and recycling.
- **End-to-end test on the real vCenter** with the two-VM test lab:
  - Deploy from the UI and connect with the WireGuard config.
  - Ping lab hosts; confirm there's no route to the management network or other instances.
  - Reset one machine and the whole lab; confirm the snapshot state comes back.
  - Let a dedicated instance expire and confirm it's cleaned up and its peer revoked.
- **UI:** Playwright smoke test (same approach as `lms/tests/browser/smoke.mjs`) on the catalogue and instance pages, in light and dark.
- **Offline rehearsal:** install from the bundle on a VM with no internet access.

## 9. Single machines

Added after the first design pass. Alongside Pro Labs, people can deploy **one machine from a template**: an OS or appliance (pfSense, Ubuntu, Windows Server, ESXi…) to build and break things on. The prototype has the pages: `/machines`, `/machines/new/<template>` and `/machines/<id>`.

### Lifecycle
- **Duration:** chosen at deploy time (2 h, 4 h, 8 h, 1 d, 3 d or 7 d), or **permanently**.
- **Expiry:** when time runs out, the machine is powered off and marked *expired*. It's deleted after a grace period (`GRACE_MINUTES`, a day by default) unless it's extended.
  - This gives a grace period for anyone who missed the warning. Extending an expired machine starts it again.
  - A banner on every page warns when one of your machines has less than an hour left.
- **Extending:** +2 h or +1 day, as often as wanted. Or keep it permanently, and put it back on a timer later.
- **Quotas (configurable):**
  - Learners: up to 3 machines, 1 of them permanent.
  - Admins: up to 10, 5 of them permanent.
  - Permanent machines count against capacity indefinitely, so the limit matters.
- **Other actions:** start, stop, reboot, reset to the clean snapshot, redeploy (a new VM with the same settings, e.g. after a failed deploy), "deploy another like this", and destroy.

### Personal network
- **Layout:** each person gets one network (a VLAN slot plus a small gateway VM, like a lab instance). It's created with their first machine and removed with their last.
- **Access:** all their machines join it, so a pfSense, a Windows server and a Kali box can reach each other. One WireGuard file reaches everything.
- **Isolation:** kept apart from other people's networks and from the labs.
- **Later:** let people add extra private segments, so a pfSense can sit *between* networks rather than beside them.

### Templates
- **Catalogue:** 39 templates in 11 categories: firewalls and routers, Linux, Windows, Windows Server (including a ready-made Active Directory domain), hypervisors, mail, storage, self-hosted apps (such as Vaultwarden, MinIO, WordPress and Keycloak), developer tools, security tools and practice targets.
  - The catalogue (names, descriptions, categories, versions) is `frontend/src/lib/templates.ts`. What can actually be deployed, and how, is `backend/templates.yaml`, which the API serves; a test checks every entry there is in the catalogue too.
  - Practice targets (Metasploitable, Juice Shop, DVWA) are vulnerable on purpose. Like everything else, they're only reachable inside their owner's personal network.
- **Apps:** app templates are Ubuntu with the app installed. The machine page separates the app's own sign-in from the SSH user, and knows each app's web address (e.g. MinIO's console on port 9001).
- **How they're stored:** each version is a vSphere template with a `clean` snapshot, deployed as a linked clone.
- **Name and first sign-in:**
  - Linux: set by cloud-init.
  - Windows: set by Cloudbase-Init (cloud-init's Windows counterpart, reading the same VMware guestinfo data) in templates generalized with sysprep. Chosen over a vSphere customisation spec so Windows and Linux share one way of passing data, and one way of waiting for setup and extras.
  - Appliances (pfSense, OPNsense, ESXi, TrueNAS, VyOS) can't be customised, so they keep documented defaults, shown on the machine page.
- **Flags** on a template tell people, and the deploy job, what it needs:
  - **Nested** (Proxmox, ESXi): expose hardware virtualisation to the guest (`vhv.enable`). The port group must let nested VMs talk: MAC learning on a vSphere 8 distributed switch, or promiscuous mode plus forged transmits. Nested VMs are slower.
  - **Licence** (Windows, Windows Server, ESXi, Exchange): an offline network can't activate online.
    - Windows needs a KMS host or volume keys in the lab network.
    - ESXi runs on its 60-day evaluation.
  - **vTPM** (Windows 11): needs a key provider in vCenter (the Native Key Provider is enough). Cloning then has to handle the TPM.
  - **Two machines** (Exchange): Exchange needs Active Directory, so it's deployed as a pair with a domain controller.
- **Old versions:** end-of-life versions (CentOS 6–8, Ubuntu 16.04–20.04, Windows 7, Server 2012 R2, ESXi 6.5–7.0, Exchange 2016/2019) are offered on purpose, for practising on old systems. They're clearly labelled and only reachable inside personal networks.

### What this changes elsewhere
- **Browser console becomes necessary rather than "later".** Appliances are set up from their console on first boot (pfSense interface assignment, ESXi's DCUI), and a firewall misconfiguration can lock out SSH and the web UI.
  - Plan a WebMKS console proxied through the panel, so browsers never need to reach ESXi hosts directly.
- **The expiry sweep is a scheduled worker job.** It powers off expired machines, deletes those past the grace period, and warns owners. Browser notifications are an option; email only if the offline network has a mail relay.
- **Capacity:** machines share the ProLabs resource pool with lab instances and appear in the admin meters.

## Open items to confirm with the infra owner
- vCenter version and licence edition (dvSwitch?), and whether NSX is present.
- Number of hosts, total RAM, and datastore type and size.
- A reserved VLAN range and the LAN subnet for the `lab-access` port group.
- Windows licensing approach (KMS or volume keys).
- For single machines: whether nested virtualisation is allowed on the cluster, and whether a key provider can be set up for vTPM (Windows 11).
