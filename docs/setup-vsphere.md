# Setting up vSphere for the panel

What to do once, by hand, before the panel can deploy machines:

1. Prepare vCenter: an account, folders and permissions (mostly scripted).
2. Build the Ubuntu 26.04 template.
3. Give the panel the vCenter details.
4. Deploy a test machine.

Names below (`Labs/Templates`, `tpl-ubuntu-26.04`…) are the defaults the panel expects. If you use
others, change them in `lab-deploy.env` and `backend/templates.yaml` to match.

## 1. vCenter

vCenter needs a datacenter with your ESXi host in it. On a fresh vCenter, first create a datacenter
(right-click the vCenter → **New Datacenter**) and a cluster in it (**New Cluster**, with DRS, HA and
vSAN off, and "Manage all hosts in the cluster with a single image" unticked), then add the host
(right-click the cluster → **Add Hosts**).

The panel then needs:

- **Folders:** `Labs/Templates` for templates, and `Labs/Machines` for its machines. Keep other VMs
  out of `Labs/Machines`, because the panel treats everything there as its own.
- **An account of its own:** what it can do is then limited and easy to audit.

### Create the panel's account

This step is manual (vCenter's API for it isn't covered by pyVmomi):

1. Go to **Administration → Single Sign On → Users and Groups**.
2. On the **Users** tab, set the domain to `vsphere.local` and click **Add**.
3. Create `svc-labdeploy` with a strong password.

### Folders, roles and permissions: run the script

[`scripts/setup_vcenter.py`](../scripts/setup_vcenter.py) does the rest. Run it from any Linux
machine that can reach vCenter on port 443:

```sh
python3 -m venv ~/labdeploy-setup && ~/labdeploy-setup/bin/pip install pyvmomi
~/labdeploy-setup/bin/python scripts/setup_vcenter.py
```

It asks for the vCenter address and an administrator's password (used for that run only), and lets
you pick the datacenter, cluster, datastore and port group. It shows what it will change and waits
for you to confirm. Then it:

- creates the folders;
- creates two roles:
  - **Lab Deploy:** what the panel does to its machines;
  - **Lab Deploy (placement):** only lets it put VMs in the cluster;
- grants the account permissions (see the table below);
- checks the account's effective privileges, including that it can't touch a VM outside `Labs`;
- prints the `VCENTER_*` settings for part 3.

It's safe to re-run, e.g. after a new version of the panel needs another privilege.

<details>
<summary>Doing it by hand instead</summary>

1. Create the folders in **VMs and Templates**:
   - right-click the datacenter → **New Folder → New VM and Template Folder** → `Labs`;
   - inside `Labs`, create `Templates` and `Machines` the same way.
2. In **Administration → Access Control → Roles**, create the role `Lab Deploy` with these privileges:

   | Category | Privileges |
   |---|---|
   | Datastore | Allocate space; Browse datastore |
   | Network | Assign network |
   | Resource | Assign virtual machine to resource pool |
   | Virtual machine → Change Configuration | Advanced configuration; Change CPU count; Change Memory; Change Settings; Modify device settings |
   | Virtual machine → Edit Inventory | Create from existing; Remove |
   | Virtual machine → Interaction | Power off; Power on; Reset |
   | Virtual machine → Provisioning | Clone template; Clone virtual machine; Deploy template |
   | Virtual machine → Snapshot management | Create snapshot; Revert to snapshot |

3. Create a second role, `Lab Deploy (placement)`, with only **Resource → Assign virtual machine to
   resource pool**.
4. On each object below, open the **Permissions** tab and add `svc-labdeploy` (domain `vsphere.local`):

   | Object | Role | Propagate to children |
   |---|---|---|
   | The datacenter | Read-only | Yes |
   | The `Labs` folder | Lab Deploy | Yes |
   | The datastore machines go on | Lab Deploy | Yes |
   | The LAN port group | Lab Deploy | Yes |
   | The cluster (or host) | Lab Deploy (placement) | Yes |

   Don't give the cluster the full `Lab Deploy` role. VMs inherit permissions from their cluster,
   so that would let the panel power off or delete every VM on it, vCenter included.

</details>

## 2. The Ubuntu 26.04 template

Machines are **linked clones** of the template's snapshot named `clean`:
- each deploy takes seconds, and only the changes use disk space;
- on each machine's first boot, **cloud-init** sets its hostname, creates the `ubuntu` user with a
  generated password (plus your SSH key, if you gave one), and turns on DHCP.

The template therefore needs cloud-init and VMware Tools, with all trace of its own first boot removed.

### Create the VM

1. **Upload the ISO.** In **Storage → *datastore* → Files**, create a folder `ISO` and upload
   `ubuntu-26.04.x-live-server-amd64.iso` into it.
2. **Create the VM** in `Labs/Templates`, named `tpl-ubuntu-26.04`:
   - Guest OS: Linux, Ubuntu Linux (64-bit)
   - 2 vCPU, 2 GB memory, 25 GB disk, **thin provisioned**
   - Network adapter: **VMXNET3**, on the LAN port group
   - CD/DVD: **Datastore ISO File**, the ISO, **Connect at power on**
3. **Install Ubuntu Server**:
   - accept the defaults;
   - tick **Install OpenSSH server**;
   - create any user, e.g. `builder`. It's deleted at the end.
4. **Reboot**, then in **Edit Settings** set the CD/DVD to **Client Device**. Just disconnecting it
   would leave every clone pointing at the ISO.
5. SSH in as `builder` (the console shows its address).

### Prepare it

[`scripts/template-prepare.sh`](../scripts/template-prepare.sh) does this part. Piped over SSH,
`sudo` can't ask for a password, so first let `builder` use it without one (on the VM; the clean-up
step removes it):

```sh
echo 'builder ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/builder
```

Then, from a machine with this repo:

```sh
ssh builder@<vm address> 'sudo bash -s' < scripts/template-prepare.sh
```

It updates every package, installs VMware Tools (`open-vm-tools`) and cloud-init, grows the root
volume into the whole disk (the installer only uses half), and lets cloud-init run on clones and
read its data from vCenter. The installer turned cloud-init off: while
`/etc/cloud/cloud-init.disabled` exists, clones get no hostname, user or password. It's safe to
re-run.

Optionally, install anything every machine should have, now.

### Clean it, and shut it down

[`scripts/template-clean.sh`](../scripts/template-clean.sh) forgets the template's own identity so
each clone gets its own: it resets cloud-init, empties the machine-id, and deletes the SSH host keys
and the installer's network config. It then deletes `builder` (with its sudoers file) and powers
off, so your SSH session ends and there's no way back in. Without `--yes` it only says what it would
do.

```sh
ssh builder@<vm address> 'sudo bash -s -- --yes' < scripts/template-clean.sh
```

The machine-id reset matters: without it, clones can end up sharing one DHCP lease. (The panel also asks
for leases by MAC address, but don't rely on that alone.)

### Snapshot it, and make it a template

With the VM powered off:

1. **Take a snapshot** named exactly **`clean`**. Leave "Include virtual machine's memory" unticked.
2. **Convert it:** right-click, then **Template → Convert to Template**.

Don't delete the template, or its `clean` snapshot, while any machine exists: every machine's disk is
built on top of that snapshot.

To update it later, build a new template (e.g. `tpl-ubuntu-26.04-v2`) and point `vsphere:` in
`backend/templates.yaml` at it. Machines that already exist keep using the old one; delete the old
template once they're all gone.

## 3. Tell the panel

On the panel's server, edit `/srv/lab-deploy/lab-deploy.env`. The first deploy created it, with a
database password already filled in. Set the `VCENTER_*` lines:

| Setting | What it is | Where to find it in vCenter |
|---|---|---|
| `VCENTER_HOST` | vCenter's address | The address you open in the browser |
| `VCENTER_USER`, `VCENTER_PASSWORD` | The service account | `svc-labdeploy@vsphere.local` and its password |
| `VCENTER_INSECURE` | `1` to accept vCenter's own self-signed certificate | — |
| `VCENTER_DATACENTER` | Datacenter name | Top level of the inventory |
| `VCENTER_CLUSTER` | Cluster name; or, for a host not in a cluster, the host's name as vCenter shows it | — |
| `VCENTER_DATASTORE` | Datastore name | — |
| `VCENTER_NETWORK` | The LAN port group | e.g. `VM Network` |

Then apply it, on the server:

```sh
cd /srv/lab-deploy && docker compose up -d
curl -sk https://<panel address>/api/health   # {"database":"ok","vcenter":"ok"} once it can sign in
```

Re-running the pipeline does the same.

The server must be able to reach vCenter on port 443. Machines' addresses come from the DHCP server
on the port group; the panel reads them from VMware Tools.

## 4. Check it

1. Open the panel, go to **Machines → Ubuntu Server**, and deploy `ubuntu01` for 2 hours.
2. In vCenter, `ubuntu01-xxxx` appears in `Labs/Machines`, as a linked clone, and powers on.
3. Within a minute or two, the panel shows its address. `ssh ubuntu@<address>` works with the
   password on its page, and `hostname` prints `ubuntu01`.
4. Try **Stop**, **Start**, **Reboot**, and **Reset to clean**: a file you created is gone, and
   the password is unchanged.
5. **Destroy** it: the VM is deleted in vCenter.

If something fails, the machine's **Activity** log and **Admin → Jobs** show vCenter's error message.
The worker's own log has the rest: `docker compose -f /srv/lab-deploy/compose.yaml logs worker`.
